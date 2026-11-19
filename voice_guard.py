"""Voice-required ERLC moderation with durable Discord receipts."""
import asyncio
import hashlib
import json
import logging
import os
import re
import secrets
import time

import aiohttp
import discord
from discord.ext import commands, tasks
from verification import GUILD, VerificationUnavailable

from discord_logs import MOD_LOG
GRACE = 60
DURATION = 300
PREFIX = 'rc-vc-state:'
log = logging.getLogger('rivercity.voice')


def player_map(data):
    result = {}
    rows = data.get('Players') if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError('Missing players snapshot')
    for row in rows:
        match = re.fullmatch(r'([A-Za-z0-9_]{3,20}):([0-9]+)', str(row.get('Player', '')))
        if match:
            result[int(match[2])] = match[1]
    return result


def in_voice(member):
    return bool(member and member.voice and member.voice.channel)


def manual_override(record, commands):
    for entry in commands:
        if entry.get('Timestamp', 0) <= record['started'] + 10:
            continue
        parts = str(entry.get('Command', '')).lower().split()
        if len(parts) >= 2 and parts[0] in (':jail', ':unjail', ':free'):
            targets = parts[1].split(',')
            if any(t in ('all', 'others') or record['name'].lower().startswith(t) for t in targets):
                return True
    return False


class VoiceGuard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.owner = secrets.token_hex(12)
        self.missing = {}
        self.links = {}
        self.backoff = 0
        self.started = False
        self.poll.start()

    def cog_unload(self):
        self.poll.cancel()

    @commands.Cog.listener()
    async def on_disconnect(self):
        # Never punish based on voice observations spanning a lost Gateway connection.
        self.missing.clear()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.guild.id == GUILD and after.channel and before.channel != after.channel:
            for rid, (_, discord_id) in list(self.links.items()):
                if discord_id == member.id:
                    self.missing.pop(rid, None)

    async def api(self, path, params=None, command=None):
        key = os.getenv('ERLC_SERVER_KEY', '')
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as client:
            method = client.post if command else client.get
            kwargs = {'json': {'command': command}} if command else {'params': params}
            async with method('https://api.erlc.gg/v2/server' + path,
                              headers={'Server-Key': key}, allow_redirects=False, **kwargs) as response:
                if not 200 <= response.status < 300:
                    self.backoff = time.monotonic() + (60 if response.status == 429 else 15)
                    raise VerificationUnavailable(f'ERLC HTTP {response.status}')
                if command:
                    return
                return await response.json()

    async def linked_member(self, guild, roblox_id):
        cached = self.links.get(roblox_id)
        if cached and time.monotonic() - cached[0] < 60:
            return guild.get_member(cached[1]) if cached[1] else None
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as client:
            async with client.get(
                f'https://api.blox.link/v4/public/guilds/{GUILD}/roblox-to-discord/{roblox_id}',
                headers={'Authorization': os.getenv('BLOXLINK_API_KEY', '')}, allow_redirects=False,
            ) as response:
                if response.status == 404:
                    self.links[roblox_id] = (time.monotonic(), None)
                    return None
                if response.status != 200:
                    self.backoff = time.monotonic() + 60
                    raise VerificationUnavailable(f'Bloxlink reverse lookup HTTP {response.status}')
                data = await response.json()
        ids = data.get('discordIDs', data.get('DiscordIDs'))
        if not isinstance(ids, list):
            raise VerificationUnavailable('Bloxlink reverse lookup returned an unexpected schema')
        ids = {int(n) for n in ids if str(n).isdecimal()}
        # Multiple Discord identities are ambiguous; never guess which person to punish.
        if len(ids) != 1:
            self.links[roblox_id] = (time.monotonic(), None)
            return None
        discord_id = ids.pop()
        member = guild.get_member(discord_id)
        if member is None:
            try:
                member = await guild.fetch_member(discord_id)
            except discord.NotFound:
                return None
        if member.bot:
            return None
        service = self.bot.get_cog('Verification')
        if await service.accounts.lookup(discord_id) != roblox_id:
            return None
        self.links[roblox_id] = (time.monotonic(), discord_id)
        return member

    async def records(self, room):
        records = {}
        async for message in room.history(limit=None):
            if message.author.id != self.bot.user.id or not message.content.startswith(PREFIX):
                continue
            try:
                row = json.loads(message.content[len(PREFIX):])
                records.setdefault(int(row['roblox']), (message, row))
            except (ValueError, KeyError, TypeError):
                raise VerificationUnavailable('Voice state receipt needs staff review') from None
        return {rid: pair for rid, pair in records.items() if pair[1]['state'] != 'cleared'}

    async def save(self, message, row):
        await message.edit(content=PREFIX + json.dumps(row, separators=(',', ':')),
                           allowed_mentions=discord.AllowedMentions.none())

    async def audit(self, channel, row, status):
        embed = discord.Embed(title='Voice requirement | ' + status,
            description=f"**Player:** {row['name']} ({row['roblox']})\n**Discord:** <@{row['discord']}>\n"
                        f"**Reason:** In game without a Discord voice connection after {GRACE} seconds.\n"
                        f"**Jail duration:** 5 minutes\n**Release due:** <t:{int(row['due'])}:R>")
        embed.set_footer(text='River City Roleplay | Automatic VC enforcement')
        if row.get('audit') and row.get('audit_channel') == channel.id:
            await channel.get_partial_message(row['audit']).edit(embed=embed)
        else:
            sent = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none(),
                                      nonce=hashlib.sha256(str(row['nonce']).encode()).hexdigest()[:24])
            row['audit'] = sent.id
            row['audit_channel'] = channel.id

    @tasks.loop(seconds=10)
    async def poll(self):
        if not self.bot.is_ready() or time.monotonic() < self.backoff:
            return
        guild = self.bot.get_guild(GUILD)
        if not guild or not self.bot.intents.voice_states:
            return
        missing_keys = [name for name in ('BLOXLINK_API_KEY', 'ERLC_SERVER_KEY') if not os.getenv(name)]
        if missing_keys:
            log.warning('Voice checks require %s', ', '.join(missing_keys))
            self.backoff = time.monotonic() + 300
            return
        channel = guild.get_channel(MOD_LOG)
        if not channel:
            log.warning('Auto-jail paused: jail log channel unavailable')
            return
        try:
            room = await self.bot.receipt_channel(guild)
            # Discord-enforced nonce elects one active instance for each minute.
            lease_bucket = int(time.time()) // 60
            leader = await room.send(self.owner, nonce=f'vc-leader-{lease_bucket}',
                                     delete_after=180, silent=True)
            if leader.content != self.owner:
                self.missing.clear()
                return
            data = await self.api('', params={'Players': 'true', 'CommandLogs': 'true'})
            players = player_map(data)
            records = await self.records(room)
            if not self.started:
                log.info('Auto-jail enabled: grace=60s, jail=300s, any guild VC; restored %s records', len(records))
                self.started = True
            now = time.time()
            # Release work runs before any new punishment and survives redeploys.
            for rid, (message, row) in records.items():
                if row['state'] == 'preparing':
                    row['state'] = 'failed'
                    await self.save(message, row)
                    continue
                if row['state'] in ('requested', 'active'):
                    if manual_override(row, data.get('CommandLogs', [])):
                        row['state'] = 'manual'
                        await self.save(message, row)
                        await self.audit(channel, row, 'Staff override - automatic release cancelled')
                        continue
                    if now >= row['due'] and rid in players:
                        if any(other != rid and n.lower().startswith(players[rid].lower()) for other, n in players.items()):
                            continue
                        await self.api('/command', command=f":unjail {players[rid]}")
                        row['state'] = 'released'
                        await self.save(message, row)
                        await self.audit(channel, row, 'Released')
                        log.info('Auto-jail release succeeded for Roblox ID %s', rid)
                        return
                elif row['state'] in ('released', 'failed', 'manual'):
                    member = guild.get_member(row['discord'])
                    if rid not in players or in_voice(member):
                        row['state'] = 'cleared'
                        await self.save(message, row)
                        self.missing.pop(rid, None)
            for rid in list(self.missing):
                if rid not in players:
                    self.missing.pop(rid, None)
            for rid, name in players.items():
                if rid in records:
                    continue
                member = await self.linked_member(guild, rid)
                if not member or in_voice(member):
                    self.missing.pop(rid, None)
                    continue
                since = self.missing.setdefault(rid, time.monotonic())
                if time.monotonic() - since < GRACE:
                    continue
                # Refresh the selected account immediately before the action.
                if await self.bot.get_cog('Verification').accounts.lookup(member.id) != rid:
                    self.missing.pop(rid, None)
                    continue
                if in_voice(member) or not self.bot.is_ready():
                    self.missing.pop(rid, None)
                    continue
                # Full names can still be prefix selectors: skip ambiguous names.
                if any(other != rid and other_name.lower().startswith(name.lower()) for other, other_name in players.items()):
                    continue
                fresh = player_map(await self.api('', params={'Players': 'true'}))
                if fresh.get(rid) != name or in_voice(member) or int(time.time()) // 60 != lease_bucket:
                    continue
                if any(other != rid and n.lower().startswith(name.lower()) for other, n in fresh.items()):
                    continue
                row = {'roblox': rid, 'discord': member.id, 'name': name, 'started': time.time(),
                       'due': time.time() + DURATION, 'state': 'preparing', 'nonce': secrets.token_hex(12)}
                # Persist an intent before sending a non-idempotent game command.
                receipt = await room.send(PREFIX + json.dumps(row, separators=(',', ':')), silent=True,
                    nonce=hashlib.sha256(f'vc-jail:{rid}:{int(time.time()) // 300}'.encode()).hexdigest()[:24])
                if json.loads(receipt.content[len(PREFIX):])['nonce'] != row['nonce']:
                    continue
                await self.audit(channel, row, 'Jail requested')
                row['state'] = 'requested'
                await self.save(receipt, row)
                try:
                    await self.api('/command', command=f':jail {name}')
                except VerificationUnavailable as exc:
                    if str(exc) not in ('ERLC HTTP 400', 'ERLC HTTP 403', 'ERLC HTTP 422', 'ERLC HTTP 429'):
                        raise
                    row['state'] = 'failed'
                    await self.save(receipt, row)
                    await self.audit(channel, row, 'Jail request rejected')
                    raise
                row['state'] = 'active'
                row['due'] = time.time() + DURATION
                await self.save(receipt, row)
                await self.audit(channel, row, 'Jailed')
                log.info('Auto-jail accepted for Roblox ID %s', rid)
                return  # Space all game commands by at least one polling interval.
        except (aiohttp.ClientError, asyncio.TimeoutError, discord.HTTPException, ValueError, TypeError, VerificationUnavailable) as exc:
            # Ambiguous network failures leave the durable intent for timed release.
            self.missing.clear()
            self.backoff = max(self.backoff, time.monotonic() + 30)
            log.warning('Auto-jail paused/retrying (%s)', type(exc).__name__)

    @poll.before_loop
    async def ready(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(GUILD)
        if guild:
            try:
                rid = await self.bot.get_cog('Verification').accounts.lookup(guild.owner_id)
                member = await self.linked_member(guild, rid) if rid else None
                log.info('Auto-jail Bloxlink reverse/forward identity check: %s', bool(member))
            except (VerificationUnavailable, aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                log.warning('Auto-jail identity lookup could not be validated; unknown accounts will be skipped')
