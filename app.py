import asyncio
import logging
import os
from datetime import timedelta
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

GUILD = 1491365342646112386
WELCOME = 1572082493715386398
DEST = 1572082450232774727
PANEL = 1572082489743249591
SUPPORT = int(os.getenv("SUPPORT_ROLE_ID") or 0)
BLUE = 0x4285BA
ticket_lock = asyncio.Lock()
panel_lock = asyncio.Lock()
log = logging.getLogger("rivercity")


def card(title, description):
    embed = discord.Embed(title=title, description=description, color=BLUE)
    embed.set_footer(text="River City Roleplay")
    return embed


class RiverBot(commands.Bot):
    async def setup_hook(self):
        self.add_view(Panel())
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
        embed = card("Welcome to River City Roleplay!", f"{member.mention}, welcome to the city! Read the server rules and introduce yourself. If you need staff assistance, visit <#{PANEL}>.")
        embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(member.mention, embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))


def support_role(guild):
    role = guild.get_role(SUPPORT)
    if SUPPORT and (not role or role.is_default()):
        raise ValueError("Check the SUPPORT_ROLE_ID setting.")
    return role


def ticket_owner(channel):
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


class Panel(TicketView):
    @discord.ui.button(label="Request Assistance", style=discord.ButtonStyle.primary, custom_id="rc:open")
    async def open_ticket(self, interaction, button):
        if interaction.channel_id != PANEL:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild, member = interaction.guild, interaction.user
        dest = guild.get_channel(DEST)
        role = support_role(guild)
        async with ticket_lock:
            if isinstance(dest, discord.CategoryChannel):
                rooms = await guild.fetch_channels()
            elif isinstance(dest, discord.TextChannel):
                if not dest.permissions_for(member).view_channel:
                    raise ValueError("You need access to the assistance parent channel. Please contact staff.")
                rooms = await guild.active_threads()
            else:
                raise ValueError("Staff must configure a ticket category or text channel.")
            existing = next((room for room in rooms if ticket_owner(room) == member.id), None)
            if existing:
                await interaction.followup.send(f"Your ticket is already open in {existing.mention}.", ephemeral=True)
                return
            name = f"assistance-{member.id}"
            if isinstance(dest, discord.CategoryChannel):
                access = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False),
                              member: access, guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True, send_messages=True, read_message_history=True)}
                if role:
                    overwrites[role] = access
                else:
                    for staff_role in guild.roles:
                        if not staff_role.is_default() and staff_role.permissions.manage_channels:
                            overwrites[staff_role] = access
                room = await guild.create_text_channel(name, category=dest, overwrites=overwrites, topic=f"River City assistance | owner={member.id}")
            else:
                room = await dest.create_thread(name=name, type=discord.ChannelType.private_thread, invitable=False)
            try:
                if isinstance(room, discord.Thread):
                    await room.add_user(member)
                await room.send(member.mention, embed=card("Assistance ticket", "Describe what happened and what you need help with. A staff member can claim this ticket below."), view=Controls())
            except discord.HTTPException:
                await room.delete(reason="Incomplete ticket setup")
                raise
        await interaction.followup.send(f"Your private ticket is ready in {room.mention}.", ephemeral=True)


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


async def ensure_panel(channel):
    async with panel_lock:
        async for message in channel.history(limit=None):
            if message.author == bot.user and any(getattr(button, "custom_id", None) == "rc:open" for row in message.components for button in row.children):
                return message
        return await channel.send(embed=card("River City Assistance", "Need help from staff? Select **Request Assistance** to open a private ticket."), view=Panel())


@bot.event
async def on_ready():
    guild = bot.get_guild(GUILD)
    channel = guild and guild.get_channel(PANEL)
    if channel:
        await ensure_panel(channel)
    else:
        log.error("Configured server or panel channel is unavailable")


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


@bot.command(name="help")
async def show_help(ctx):
    await ctx.send(embed=card("River City Systems", f"**Member assistance** · <#{PANEL}>\n\n**Staff commands**\n`.kick @member [reason]`\n`.ban @member [reason]`\n`.unban user_id [reason]`\n`.timeout @member minutes [reason]`\n`.untimeout @member [reason]`\n`.clear 1–100`\n`.ticketpanel`"))


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingPermissions):
        message = "You don’t have permission to use that command."
    elif isinstance(error, commands.UserInputError):
        message = f"{error}\nUsage: `.{ctx.command} {ctx.command.signature}`"
    else:
        cause = getattr(error, "original", error)
        log.error("Command failed", exc_info=cause)
        message = "Action failed. Check the target, bot permissions, and role order."
    await ctx.send(message)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("Set DISCORD_TOKEN in .env or the host environment before starting the bot.")
    bot.run(token)
