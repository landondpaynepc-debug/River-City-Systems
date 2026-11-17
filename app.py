import asyncio
import logging
import os
from datetime import timedelta
from pathlib import Path

import discord
from aiohttp import web
from discord.ext import commands
from dotenv import load_dotenv

from panels import ASSETS, Panel, SUPPORT_TYPES
from sessions import Sessions, session_card, stats, welcome

load_dotenv(Path(__file__).with_name(".env"))

GUILD = 1491365342646112386
WELCOME = 1572082493715386398
DEST = 1572082450232774727
PANEL = 1572082489743249591
SUPPORT = int(os.getenv("SUPPORT_ROLE_ID") or 0)
DASHBOARD = 1492006832779165756
HIGH_RANK = int(os.getenv("HIGH_RANK_ROLE_ID") or 1572082345949790311)
BLUE = 0x1066EC
ticket_lock = asyncio.Lock()
panel_lock = asyncio.Lock()
log = logging.getLogger("rivercity")


def card(title, description):
    embed = discord.Embed(title=title, description=description, color=BLUE)
    embed.set_footer(text="River City Roleplay")
    return embed


class RiverBot(commands.Bot):
    async def setup_hook(self):
        await self.add_cog(Sessions(DASHBOARD))
        self.add_view(session_card("ssv", None))
        self.add_view(session_card("info", None, numbers="Loading counts…"))
        self.add_view(build_panel(PANEL))
        self.add_view(build_panel(DASHBOARD))
        self.add_view(Controls())

    async def process_commands(self, message):
        if message.guild and message.guild.id == GUILD:
            await super().process_commands(message)


intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = RiverBot(command_prefix=".", intents=intents,
               allowed_mentions=discord.AllowedMentions.none(), help_command=None)


@bot.event
async def on_member_join(member):
    if member.guild.id != GUILD or member.bot:
        return
    channel = member.guild.get_channel(WELCOME)
    if channel:
        await channel.send(view=welcome(member, DASHBOARD), allowed_mentions=discord.AllowedMentions(users=[member]))


def support_role(guild):
    role = guild.get_role(SUPPORT)
    if SUPPORT and (not role or role.is_default()):
        raise ValueError("Check the SUPPORT_ROLE_ID setting.")
    return role


def ticket_owner(channel):
    if high_ticket(channel):
        value = channel.topic.rsplit("=", 1)[-1]
        return int(value) if value.isdecimal() else None
    if isinstance(channel, discord.TextChannel) and channel.category_id == DEST:
        prefix = "River City assistance | owner="
        value = (channel.topic or "").removeprefix(prefix)
        if channel.topic and channel.topic.startswith(prefix) and value.isdecimal():
            return int(value)
    if isinstance(channel, discord.Thread) and channel.parent_id == DEST and channel.owner_id == bot.user.id and channel.is_private():
        if channel.name.startswith("assistance-") and channel.name[11:].isdecimal():
            return int(channel.name[11:])
    return None


def is_staff(member, channel):
    if high_ticket(channel):
        return member.guild_permissions.administrator or bool(HIGH_RANK and member.get_role(HIGH_RANK))
    if member.guild_permissions.administrator or (SUPPORT and member.get_role(SUPPORT)):
        return True
    perms = channel.permissions_for(member)
    return perms.manage_threads if isinstance(channel, discord.Thread) else perms.manage_channels


class TicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def interaction_check(self, interaction):
        return interaction.guild_id == GUILD

    async def on_error(self, interaction, error, item):
        log.exception("Ticket action failed", exc_info=error)
        message = str(error) if isinstance(error, ValueError) else "The ticket action failed. Ask staff to check the bot permissions and logs."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


def high_ticket(channel):
    return isinstance(channel, discord.TextChannel) and (channel.topic or "").startswith("River City Roleplay | management | owner=")


async def create_ticket(interaction, route, subject, details):
    if interaction.guild_id != GUILD or interaction.channel_id != PANEL:
        return
    await interaction.response.defer(ephemeral=True, thinking=True)
    guild, member = interaction.guild, interaction.user
    high = route == "high"
    dest = guild.get_channel(DEST)
    try:
        if not isinstance(dest, (discord.TextChannel, discord.CategoryChannel)):
            raise ValueError("The configured ticket destination is unavailable.")
        if high:
            role = guild.get_role(HIGH_RANK)
            if HIGH_RANK and (not role or role.is_default()):
                raise ValueError("Management role setup needs staff attention.")
        else:
            role = support_role(guild)
        async with ticket_lock:
            use_thread = not high and isinstance(dest, discord.TextChannel)
            rooms = await guild.active_threads() if use_thread else await guild.fetch_channels()
            existing = next((r for r in rooms if high_ticket(r) == high and ticket_owner(r) == member.id), None)
            if existing:
                await interaction.followup.send(f"You already have an open {SUPPORT_TYPES[route]} ticket: {existing.mention}", ephemeral=True)
                return
            if use_thread:
                if not dest.permissions_for(member).view_channel or not dest.permissions_for(member).send_messages_in_threads:
                    raise ValueError("Ask staff for permission to use the assistance parent channel.")
                room = await dest.create_thread(name=f"assistance-{member.id}", type=discord.ChannelType.private_thread, invitable=False)
            else:
                category = dest if isinstance(dest, discord.CategoryChannel) else dest.category
                access = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                              member: access, guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True, send_messages=True, read_message_history=True)}
                if role:
                    overwrites[role] = access
                elif not high:
                    for staff_role in guild.roles:
                        if not staff_role.is_default() and staff_role.permissions.manage_channels:
                            overwrites[staff_role] = access
                prefix = "management" if high else "assistance"
                topic = "River City Roleplay | management | owner=" if high else "River City assistance | owner="
                room = await guild.create_text_channel(f"{prefix}-{member.id}", category=category, overwrites=overwrites, topic=f"{topic}{member.id}")
            try:
                if use_thread:
                    await room.add_user(member)
                team = "management" if high else "the support team"
                embed = card(SUPPORT_TYPES[route], f"{member.mention}, your request is open for {team} to review. Add any relevant screenshots or message links here. A staff member can claim the ticket below.\n\n**Subject**  {discord.utils.escape_markdown(subject)}\n\n{details}")
                ping = role.mention if role and not use_thread else ""
                await room.send(ping or None, embed=embed, view=Controls(),
                                allowed_mentions=discord.AllowedMentions(roles=[role]) if ping else discord.AllowedMentions.none())
            except discord.HTTPException:
                await room.delete(reason="Incomplete ticket setup")
                raise
        await interaction.followup.send(f"Your {SUPPORT_TYPES[route]} ticket is ready: {room.mention}", ephemeral=True)
    except (discord.HTTPException, ValueError) as error:
        log.exception("Could not create ticket")
        message = str(error) if isinstance(error, ValueError) else "Staff must check the bot’s channel and role permissions."
        await interaction.followup.send(message, ephemeral=True)


class Controls(TicketView):
    @discord.ui.button(label="Claim", style=discord.ButtonStyle.success, custom_id="rc:claim")
    async def claim(self, interaction, button):
        if not ticket_owner(interaction.channel) or not is_staff(interaction.user, interaction.channel):
            await interaction.response.send_message("Only ticket staff can claim this ticket.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with ticket_lock:
            message = await interaction.channel.fetch_message(interaction.message.id)
            embed = message.embeds[0]
            if embed.fields:
                await interaction.followup.send("This ticket has already been claimed.", ephemeral=True)
                return
            embed.add_field(name="Claimed by", value=interaction.user.mention)
            embed.color = discord.Color.green()
            await message.edit(embed=embed)
        await interaction.followup.send("You claimed this ticket.", ephemeral=True)

    @discord.ui.button(label="Close", style=discord.ButtonStyle.danger, custom_id="rc:close")
    async def close(self, interaction, button):
        owner = ticket_owner(interaction.channel)
        if not owner or (owner != interaction.user.id and not is_staff(interaction.user, interaction.channel)):
            await interaction.response.send_message("Only the requester or ticket staff can close this ticket.", ephemeral=True)
            return
        await interaction.response.send_message("Closing this ticket.", ephemeral=True)
        await interaction.channel.delete(reason=f"Ticket closed by {interaction.user.id}")


def build_panel(channel_id):
    kind = "dashboard" if channel_id == DASHBOARD else "assistance"
    return Panel(kind, GUILD, channel_id, PANEL, create_ticket)


async def ensure_panel(channel):
    kind = "dashboard" if channel.id == DASHBOARD else "assistance"
    markers = {"rc:rules:v2"} if kind == "dashboard" else {"rc:desk:v2", "rc:open"}
    async with panel_lock:
        previous = None
        async for message in channel.history(limit=None):
            if message.author != bot.user:
                continue
            view = discord.ui.LayoutView.from_message(message)
            if any(getattr(item, "custom_id", None) in markers for item in view.walk_children()):
                previous = message
                break
        banner = "Dashboard (2).PNG" if kind == "dashboard" else "Assistance.png"
        files = [discord.File(ASSETS / banner, filename=f"{kind}.png"), discord.File(ASSETS / "footer.png")]
        try:
            if previous:
                return await previous.edit(content=None, embeds=[], attachments=files, view=build_panel(channel.id))
            return await channel.send(files=files, view=build_panel(channel.id))
        finally:
            for file in files:
                file.close()


@bot.event
async def on_ready():
    guild = bot.get_guild(GUILD)
    if guild and os.getenv("ERLC_SERVER_KEY"):
        snapshot = await stats()
        log.info("ER:LC live counts available: %s", snapshot.startswith("**Players**"))
    if guild and guild.me.display_name != "River City Roleplay":
        try:
            await guild.me.edit(nick="River City Roleplay")
        except discord.HTTPException:
            log.warning("Could not set the bot nickname to River City Roleplay")
    for ident in (DASHBOARD, PANEL):
        channel = guild and guild.get_channel(ident)
        if not channel:
            log.error("Panel channel %s is unavailable", ident)
            continue
        try:
            await ensure_panel(channel)
        except discord.HTTPException:
            log.exception("Could not publish panel in %s", ident)


@bot.command()
@commands.has_guild_permissions(manage_guild=True)
async def dashboard(ctx):
    channel = ctx.guild.get_channel(DASHBOARD)
    if not channel:
        raise commands.BadArgument("The dashboard channel is unavailable.")
    message = await ensure_panel(channel)
    await ctx.send(f"Dashboard: {message.jump_url}")


@bot.command()
@commands.has_guild_permissions(manage_guild=True)
async def ticketpanel(ctx):
    channel = ctx.guild.get_channel(PANEL)
    if not channel:
        raise commands.BadArgument("The panel channel is unavailable.")
    message = await ensure_panel(channel)
    await ctx.send(f"Assistance panel: {message.jump_url}")


def check_target(ctx, member):
    if member in (ctx.author, ctx.guild.me, ctx.guild.owner):
        raise commands.BadArgument("Choose another member below your highest role.")
    if member.top_role >= ctx.guild.me.top_role or (ctx.author != ctx.guild.owner and member.top_role >= ctx.author.top_role):
        raise commands.BadArgument("Both you and the bot must rank above that member.")


def audit(ctx, reason):
    return f"{ctx.author} ({ctx.author.id}): {reason}"[:512]


@bot.command()
@commands.has_guild_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    check_target(ctx, member)
    await member.kick(reason=audit(ctx, reason))
    await ctx.send(f"Kicked **{member}**.")


@bot.command()
@commands.has_guild_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    check_target(ctx, member)
    await member.ban(reason=audit(ctx, reason), delete_message_seconds=0)
    await ctx.send(f"Banned **{member}**.")


@bot.command()
@commands.has_guild_permissions(ban_members=True)
async def unban(ctx, user_id: int, *, reason="No reason provided"):
    await ctx.guild.unban(discord.Object(id=user_id), reason=audit(ctx, reason))
    await ctx.send(f"Unbanned user {user_id}.")


@bot.command()
@commands.has_guild_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: commands.Range[int, 1, 40320], *, reason="No reason provided"):
    check_target(ctx, member)
    await member.timeout(timedelta(minutes=minutes), reason=audit(ctx, reason))
    await ctx.send(f"Timed out **{member}** for {minutes} minutes.")


@bot.command()
@commands.has_guild_permissions(moderate_members=True)
async def untimeout(ctx, member: discord.Member, *, reason="No reason provided"):
    check_target(ctx, member)
    await member.timeout(None, reason=audit(ctx, reason))
    await ctx.send(f"Removed the timeout for **{member}**.")


@bot.command()
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: commands.Range[int, 1, 100]):
    deleted = await ctx.channel.purge(limit=amount, before=ctx.message)
    await ctx.message.delete()
    await ctx.send(f"Cleared {len(deleted)} messages.", delete_after=5)


@bot.command(name="cmds", aliases=["help", "commands"])
async def show_help(ctx):
    session_help = "**Sessions**\n`.ssv` vote · `.ssu` startup · `.ssd` shutdown\n`.serverinfo` live ER:LC counts"
    await ctx.send(embed=card("River City Roleplay", f"{session_help}\n\n**Command list** · `.cmds`, `.commands`, `.help`\n**Member assistance** · <#{PANEL}>\n\n**Staff commands**\n`.kick @member [reason]`\n`.ban @member [reason]`\n`.unban user_id [reason]`\n`.timeout @member minutes [reason]`\n`.untimeout @member [reason]`\n`.clear 1–100`\n`.ticketpanel`\n`.dashboard`"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        message = "You don’t have permission to use that command."
    elif isinstance(error, commands.CheckFailure):
        message = "This command requires Manage Server or the configured Session Host role."
    elif isinstance(error, commands.CommandOnCooldown):
        message = f"Try again in {error.retry_after:.0f} seconds."
    elif isinstance(error, commands.UserInputError):
        message = f"{error}\nUsage: `.{ctx.command} {ctx.command.signature}`"
    else:
        cause = getattr(error, "original", error)
        log.error("Command failed", exc_info=cause)
        message = "Action failed. Check the target, bot permissions, and role order."
    await ctx.send(message)


async def health(request):
    ready = bot.is_ready()
    return web.Response(text="ready" if ready else "connecting", status=200 if ready else 503)


async def run_hosted(token, port):
    application = web.Application()
    application.router.add_get("/", health)
    application.router.add_get("/health", health)
    runner = web.AppRunner(application)
    await runner.setup()
    try:
        await web.TCPSite(runner, "0.0.0.0", port).start()
        async with bot:
            await bot.start(token)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in .env or the host environment before starting the bot.")
    if os.getenv("PORT") or os.getenv("RENDER_SERVICE_TYPE") in {"pserv", "web", "private_service", "web_service"}:
        asyncio.run(run_hosted(token, int(os.getenv("PORT") or 10000)))
    else:
        bot.run(token)
