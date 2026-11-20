from cards import layout, footer
"""River City ER:LC session announcements and member voting."""
import asyncio
from discord_logs import MOD_LOG
import logging
import os
import re
import time
import hashlib
import json
from datetime import datetime, timezone, timedelta

import aiohttp
import discord
from discord import ui
from discord.ext import commands, tasks

from panels import ASSETS, gallery

CODE = "VCRPRC"
JOIN = f"https://policeroleplay.community/join/{CODE}"
BANNERS = {"ssu": "SSU.png", "ssd": "SSD.png", "ssv": "SESSION VOTE.png", "info": "SESSION INFO.png"}
lock = asyncio.Lock()
stats_lock = asyncio.Lock()
stats_cache = (0, "")
server_online = None
log = logging.getLogger("rivercity.sessions")


def emoji(guild, names, fallback):
    if guild:
        for name in names:
            for item in guild.emojis:
                if item.available and item.name.casefold() == name:
                    return item
    return fallback


def community_role(guild):
    configured = os.getenv("COMMUNITY_MEMBER_ROLE_ID", "").strip()
    if configured:
        return guild.get_role(int(configured)) if configured.isdecimal() else None
    matches = [r for r in guild.roles if re.sub("[^a-z]", "", r.name.casefold()) in {"communitymember", "communitymembers"}]
    return matches[0] if len(matches) == 1 else None


def welcome(member, dashboard):
    icon = emoji(member.guild, ("welcome", "palm", "palmtree", "rivercity"), "🌴")
    view = ui.LayoutView(timeout=None)
    count = member.guild.member_count
    row = ui.ActionRow(ui.Button(label=f"Members: {count:,}" if count is not None else "Members", disabled=True),
                       ui.Button(label="Dashboard", emoji=emoji(member.guild, ("dashboard", "clipboard"), "📋"),
                                 url=f"https://discord.com/channels/{member.guild.id}/{dashboard}"))
    view.add_item(ui.Container(ui.TextDisplay(f"{icon} Welcome {member.mention} to **River City Roleplay**! We hope you enjoy your stay."), row))
    return view


def format_stats(data):
    players = data.get("Players")
    queue = data.get("Queue")
    staff = "Unavailable"
    if isinstance(players, list):
        staff = sum(p.get("Permission") in {"Server Administrator", "Server Moderator", "Server Owner", "Server Co-Owner"} for p in players)
    count, capacity = data.get("CurrentPlayers"), data.get("MaxPlayers")
    online = f"{count}/{capacity}" if isinstance(count, int) and isinstance(capacity, int) else "Unavailable"
    waiting = len(queue) if isinstance(queue, list) else "Unavailable"
    return f"**Players**   {online}\n**Queue**   {waiting}\n**Staff in game**   {staff}\n-# Checked <t:{int(time.time())}:R> • ER:LC"


async def stats():
    global stats_cache, server_online
    async with stats_lock:
        if time.monotonic() < stats_cache[0]:
            return stats_cache[1]
        wait = 30
        result = "Live counts are temporarily unavailable. You can still join with the code below."
        server_online = None
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as client:
                async with client.get("https://api.erlc.gg/v2/server", params={"Players": "true", "Queue": "true"},
                                      headers={"Server-Key": os.environ["ERLC_SERVER_KEY"]}, allow_redirects=False) as response:
                    if response.status == 200:
                        data = await response.json()
                        result = format_stats(data)
                        count = data.get("CurrentPlayers")
                        server_online = count > 0 if isinstance(count, int) else None
                    else:
                        log.warning("ER:LC status returned HTTP %s", response.status)
                        if response.status == 429:
                            wait = max(wait, float(response.headers.get("Retry-After", 60)))
        except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError):
            log.warning("ER:LC status could not be read")
        stats_cache = time.monotonic() + wait, result
        return result


def components(message):
    return ui.LayoutView.from_message(message).walk_children()


def kind_of(message):
    for item in components(message):
        ident = getattr(item, "custom_id", "") or ""
        if ident in ("rc:session:ssv", "rc:session:ssu", "rc:session:ssd"):
            return ident.rsplit(":", 1)[1]
    return None


def voters(message):
    for item in components(message):
        if isinstance(item, ui.TextDisplay) and item.content.startswith("**Voters"):
            return [int(n) for n in re.findall(r"<@(\d+)>", item.content)]
    return []


async def latest(channel, bot_id):
    async for message in channel.history(limit=None):
        if message.author.id == bot_id and message.components and kind_of(message):
            return message
    return None


class Vote(ui.Button):
    def __init__(self, guild=None):
        super().__init__(label="Vote / Withdraw", emoji=emoji(guild, ("vote", "checkmark", "check"), "✅"),
                         style=discord.ButtonStyle.primary, custom_id="rc:session:ssv")

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with lock:
            message = await latest(interaction.channel, interaction.client.user.id)
            if not message or message.id != interaction.message.id:
                await interaction.followup.send("This vote has ended.", ephemeral=True)
                return
            ids = voters(message)
            uid = interaction.user.id
            if uid in ids:
                ids.remove(uid)
                reply = "Your vote was withdrawn."
            elif len(ids) >= 100:
                await interaction.followup.send("This vote has reached 100 members.", ephemeral=True)
                return
            else:
                ids.append(uid)
                reply = "Your vote is counted. You’ll be mentioned when this session starts."
            await message.edit(view=session_card("ssv", interaction.guild, ids=ids), allowed_mentions=discord.AllowedMentions.none())
        await interaction.followup.send(reply, ephemeral=True)


def has_staff_role(member):
    guild = getattr(member, "guild", None)
    if guild is None:
        return False
    configured = os.getenv("STAFF_ROLE_ID", "").strip()
    if configured:
        role = guild.get_role(int(configured)) if configured.isdecimal() else None
    else:
        matches = [r for r in guild.roles if r.name.strip().casefold() == "staff"]
        role = matches[0] if len(matches) == 1 else None
    return role is not None and not role.is_default() and member.get_role(role.id) is not None


class Refresh(ui.Button):
    def __init__(self, guild=None):
        super().__init__(label="Refresh", emoji=emoji(guild, ("refresh",), "🔄"), custom_id="rc:session:refresh")

    async def callback(self, interaction):
        if not has_staff_role(interaction.user):
            await interaction.response.send_message("Only members with the Staff role can refresh server info.", ephemeral=True)
            return
        await interaction.response.defer()
        await interaction.edit_original_response(view=session_card("info", interaction.guild, numbers=await stats()))


def session_card(kind, guild, *, ids=(), numbers="", dashboard=None, mentions=""):
    view = ui.LayoutView(timeout=None)
    titles = {"ssv": "Session Vote", "ssu": "Session Startup", "ssd": "Session Shutdown", "info": "Session Information"}
    parts = [gallery("banner.png", titles[kind]), ui.Separator()]
    if mentions:
        parts.append(ui.TextDisplay(mentions))
    icon = emoji(guild, ("erlc", "session", "controller"), "🎮")
    parts.append(ui.TextDisplay(f"### {icon} {titles[kind]}"))
    join = ui.Button(label="Join Server", emoji=icon, url=JOIN)
    if kind == "ssv":
        parts.extend([ui.TextDisplay("Can you join the next River City session? Cast your vote below. Select the button again to withdraw before startup."),
                      ui.TextDisplay(f"**Voters ({len(ids)})**\n" + (" ".join(f"<@{n}>" for n in ids) or "Be the first to vote.")),
                      ui.ActionRow(Vote(guild))])
    elif kind == "ssu":
        parts.extend([ui.TextDisplay(f"The city is open! Review the in-game regulations in <#{dashboard}>, then join with code **{CODE}**. If you voted, please join when you can."),
                      ui.ActionRow(join, ui.Button(label="Session open", disabled=True, custom_id="rc:session:ssu"))])
    elif kind == "ssd":
        parts.extend([ui.TextDisplay("Today’s session has concluded. Thank you to the civilians, departments, and staff who brought River City to life. Watch this channel for the next vote."),
                      ui.ActionRow(ui.Button(label="Session closed", custom_id="rc:session:ssd", disabled=True))])
    else:
        status = ui.Button(label="Status unavailable", disabled=True, custom_id="rc:session:status")
        if server_online is not None:
            status.label = "Online" if server_online else "Offline"
            status.emoji = discord.PartialEmoji.from_str(
                "<:green_wifi:1507960431220752456>" if server_online else "<:closed_wifi:1507960524221186139>")
        parts.extend([ui.TextDisplay(f"Welcome to River City Roleplay. Use **{CODE}** to join the private server. Live counts update every 30 seconds."),
                      ui.Separator(), ui.TextDisplay(numbers), ui.ActionRow(status, join, Refresh(guild))])
    parts.extend([ui.Separator(), gallery("footer.png", "River City Roleplay")])
    view.add_item(ui.Container(*parts))
    return view


async def publish(ctx, kind, **kwargs):
    files = [discord.File(ASSETS / BANNERS[kind], filename="banner.png"), discord.File(ASSETS / "footer.png")]
    try:
        return await ctx.send(view=session_card(kind, ctx.guild, **kwargs), files=files,
                              allowed_mentions=discord.AllowedMentions.none())
    finally:
        for file in files:
            file.close()


def host():
    async def allowed(ctx):
        role_id = int(os.getenv("SESSION_HOST_ROLE_ID") or 0)
        return ctx.author.guild_permissions.manage_guild or (role_id and ctx.author.get_role(role_id))
    return commands.check(allowed)


class Sessions(commands.Cog):
    def __init__(self, dashboard, bot):
        self.dashboard = dashboard
        self.bot = bot
        self.live_messages = {}
        self.restore_task = asyncio.create_task(self.restore_live_messages())
        self.live_updates.start()
        self.game_logger = GameLogger(bot)

    def cog_unload(self):
        self.restore_task.cancel()
        self.live_updates.cancel()
        self.game_logger.poll.cancel()

    @tasks.loop(seconds=30)
    async def live_updates(self):
        if not self.live_messages:
            return
        numbers = await stats()
        for channel_id, message in list(self.live_messages.items()):
            try:
                await message.edit(view=session_card("info", message.guild, numbers=numbers),
                                   allowed_mentions=discord.AllowedMentions.none())
            except discord.NotFound:
                self.live_messages.pop(channel_id, None)
            except discord.HTTPException:
                log.warning("Could not update live session card %s", message.id)

    @live_updates.before_loop
    async def wait_until_ready(self):
        await self.bot.wait_until_ready()

    async def restore_live_messages(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(1491365342646112386)
        if not guild:
            return
        for channel in [*guild.text_channels, *guild.threads]:
            try:
                async for message in channel.history(limit=None):
                    if message.author.id == self.bot.user.id and any(
                        getattr(item, "custom_id", None) == "rc:session:refresh" for item in components(message)
                    ):
                        self.live_messages.setdefault(channel.id, message)
                        log.info("Live server-info card found in %s", channel.id)
                        break
            except discord.HTTPException:
                log.warning("Could not restore live session card in %s", channel.id)
        log.info("Restored %s live server-info cards", len(self.live_messages))


    @commands.command()
    @host()
    async def ssv(self, ctx):
        async with lock:
            previous = await latest(ctx.channel, ctx.bot.user.id)
            if previous and kind_of(previous) == "ssv":
                await ctx.send(f"The open session vote is here: {previous.jump_url}")
                return
            await publish(ctx, "ssv")

    @commands.command()
    @host()
    async def ssu(self, ctx):
        async with lock:
            previous = await latest(ctx.channel, ctx.bot.user.id)
            if previous and kind_of(previous) == "ssu":
                await ctx.send(f"The current startup is here: {previous.jump_url}")
                return
            ids = voters(previous) if previous and kind_of(previous) == "ssv" else []
            role = community_role(ctx.guild)
            if role and role.is_default():
                role = None
            names = ([role.mention] if role else []) + [f"<@{n}>" for n in ids]
            files = [discord.File(ASSETS / BANNERS["ssu"], filename="banner.png"), discord.File(ASSETS / "footer.png")]
            try:
                await ctx.send(view=session_card("ssu", ctx.guild, dashboard=self.dashboard, mentions=" ".join(names)), files=files,
                               allowed_mentions=discord.AllowedMentions(everyone=False, roles=[role] if role else False,
                                                                        users=[discord.Object(id=n) for n in ids], replied_user=False))
            finally:
                for file in files:
                    file.close()
            if not role:
                await ctx.send("Startup posted. Set COMMUNITY_MEMBER_ROLE_ID to enable the community role ping.")

    @commands.command()
    @host()
    async def ssd(self, ctx):
        async with lock:
            previous = await latest(ctx.channel, ctx.bot.user.id)
            if previous and kind_of(previous) == "ssd":
                await ctx.send(f"The shutdown is already posted: {previous.jump_url}")
                return
            await publish(ctx, "ssd")

    @commands.command()
    @commands.cooldown(1, 10, commands.BucketType.user)
    async def serverinfo(self, ctx):
        if not has_staff_role(ctx.author):
            await ctx.send("Only members with the Staff role can use .serverinfo.")
            return
        async with lock:
            numbers = await stats()
            previous = self.live_messages.get(ctx.channel.id)
            if previous:
                try:
                    await previous.edit(view=session_card("info", ctx.guild, numbers=numbers),
                                        allowed_mentions=discord.AllowedMentions.none())
                    return
                except discord.NotFound:
                    self.live_messages.pop(ctx.channel.id, None)
            self.live_messages[ctx.channel.id] = await publish(ctx, "info", numbers=numbers)


GAME_LOG_TYPES = {
    'JoinLogs': 'Player joined / left',
    'KillLogs': 'In-game kill',
    'CommandLogs': 'In-game command',
    'ModCalls': 'Moderator call',
    'EmergencyCalls': 'Emergency call',
}


def game_events(data):
    """Stable identities, including identical records occurring in one second."""
    events = []
    for kind in GAME_LOG_TYPES:
        rows = data.get(kind, [])
        if not isinstance(rows, list):
            continue
        occurrences = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            stamp = row.get('Timestamp', row.get('StartedAt'))
            if not isinstance(stamp, (int, float)) or isinstance(stamp, bool):
                continue
            raw = json.dumps([kind, row], sort_keys=True, separators=(',', ':'))
            occurrences[raw] = occurrences.get(raw, 0) + 1
            digest = hashlib.sha256(f'{raw}:{occurrences[raw]}'.encode()).hexdigest()[:24]
            events.append((stamp, digest, kind, row))
    return sorted(events)


def safe_game_value(value):
    text = str(value)
    for key, secret in os.environ.items():
        if any(word in key.upper() for word in ('TOKEN', 'KEY', 'PASSWORD', 'SECRET')) and len(secret) >= 12:
            text = text.replace(secret, '[redacted]')
    return discord.utils.escape_mentions(discord.utils.escape_markdown(text))[:1000] or 'None'


class GameLogger:
    """Replay API log windows; Discord history survives Render restarts."""
    def __init__(self, bot):
        self.bot = bot
        self.seen = {}
        self.restored = set()
        self.floors = {}
        self.retry_at = 0
        self.poll.start()

    async def restore(self, channel):
        if channel.id in self.restored:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        seen = set()
        async for message in channel.history(limit=None, after=cutoff):
            if message.author.id == self.bot.user.id:
                marker = footer(message)
                if marker.startswith('RC event '):
                    seen.add(marker.removeprefix('RC event '))
        self.seen[channel.id] = seen
        self.floors[channel.id] = cutoff.timestamp() if seen else time.time() - 300
        self.restored.add(channel.id)
        log.info('Game log destination ready: %s (%s prior events)', channel.id, len(seen))

    async def deliver(self, channel, event):
        stamp, digest, kind, row = event
        await self.restore(channel)
        if digest in self.seen[channel.id] or stamp < self.floors[channel.id]:
            return
        title = GAME_LOG_TYPES[kind]
        if kind == 'JoinLogs':
            title = 'Player joined' if row.get('Join') else 'Player left'
        embed = discord.Embed(title=title,
                              timestamp=datetime.fromtimestamp(stamp, timezone.utc))
        for name, value in row.items():
            if name not in ('Timestamp', 'StartedAt', 'Join'):
                embed.add_field(name=safe_game_value(name)[:256], value=safe_game_value(value), inline=False)
                if len(embed.fields) >= 5:
                    break
        embed.set_footer(text=f'RC event {digest}')
        await channel.send(view=layout(embed), allowed_mentions=discord.AllowedMentions.none(),
                           nonce=digest, silent=True)
        self.seen[channel.id].add(digest)
        if kind == 'ModCalls' and row.get('Timestamp') and row.get('Moderator'):
            self.bot.dispatch('river_mod_call', channel.guild, row)

    @tasks.loop(seconds=30)
    async def poll(self):
        if time.monotonic() < self.retry_at or not self.bot.is_ready():
            return
        key = os.getenv('ERLC_SERVER_KEY', '').strip()
        if not key:
            return
        try:
            guild = self.bot.get_guild(1491365342646112386)
            channel = guild.get_channel(1572425404726251572) if guild else None
            if channel is None:
                log.warning('Game logging channel 1572425404726251572 is unavailable')
                self.retry_at = time.monotonic() + 300
                return
            await self.restore(channel)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
                async with client.get('https://api.erlc.gg/v2/server',
                                      params={kind: 'true' for kind in GAME_LOG_TYPES},
                                      headers={'Server-Key': key}, allow_redirects=False) as response:
                    if response.status != 200:
                        retry = response.headers.get('Retry-After', '60')
                        self.retry_at = time.monotonic() + max(30, min(float(retry) if retry.isdecimal() else 60, 900))
                        log.warning('Game logs API returned HTTP %s', response.status)
                        return
                    data = await response.json()
            if not isinstance(data, dict):
                return
            jail_channel = guild.get_channel(MOD_LOG)
            events = game_events(data)
            for event in events:
                await self.deliver(channel, event)
            for event in events:
                if event[2] == 'CommandLogs' and re.match(r'^:(?:jail|unjail|free|kick|ban|unban|warn)(?:\s|$)', str(event[3].get('Command', '')), re.I):
                    if jail_channel:
                        await self.deliver(jail_channel, event)
        except (aiohttp.ClientError, asyncio.TimeoutError, discord.HTTPException, ValueError, TypeError, OverflowError):
            # No API payloads or credentials in application logs.
            log.warning('Game log polling/delivery failed; will retry next cycle')
            self.retry_at = time.monotonic() + 60

    @poll.before_loop
    async def ready(self):
        await self.bot.wait_until_ready()
