from cards import layout
import logging

import discord
from discord.ext import commands

MOD_LOG = 1572082553689481297
DISCORD_LOG = 1573114535001460926
log = logging.getLogger("rivercity.events")

MOD_ACTIONS = {
    "kick", "ban", "unban", "member_prune", "member_move", "member_disconnect",
    "message_delete", "message_bulk_delete", "automod_block_message",
    "automod_flag_message", "automod_timeout_member", "automod_quarantine_user",
}


async def post_log(guild, destination, title, details, *, nonce=None):
    channel = guild.get_channel(destination)
    if channel is None:
        log.error("Log channel %s unavailable in guild %s", destination, guild.id)
        return
    embed = discord.Embed(title=title, description=details[:4096], timestamp=discord.utils.utcnow())
    try:
        await channel.send(view=layout(embed), nonce=nonce, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.exception("Could not send %s to %s", title, destination)


class DiscordLogs(commands.Cog):
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id

    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry):
        if entry.guild.id != self.guild_id:
            return
        action = entry.action.name
        fields = dict(entry.after) if isinstance(entry.action, discord.AuditLogAction) else {}
        moderation = action in MOD_ACTIONS or (
            action == "member_update" and bool({"timed_out_until", "mute", "deaf"} & fields.keys())
        )
        # Our moderation commands record the staff member directly after success.
        if moderation and entry.user_id == self.bot.user.id and (
            (entry.reason or "").startswith("RC mod | ") or action in {"message_delete", "message_bulk_delete"}
        ):
            return
        target = entry.target
        details = f"Actor: <@{entry.user_id}>\nTarget: {target} ({getattr(target, 'id', 'unknown')})"
        if fields:
            details += "\nChanged: " + ", ".join(fields)
        if entry.reason:
            details += f"\nReason: {entry.reason}"
        await post_log(entry.guild, MOD_LOG if moderation else DISCORD_LOG,
                       action.replace("_", " ").title(), details, nonce=str(entry.id))

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild.id == self.guild_id:
            await post_log(member.guild, DISCORD_LOG, "Member joined", f"{member} ({member.id})")

    @commands.Cog.listener()
    async def on_raw_member_remove(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if guild and guild.id == self.guild_id:
            await post_log(guild, DISCORD_LOG, "Member left", f"{payload.user} ({payload.user.id})")

    async def message_event(self, payload, title, details):
        if payload.guild_id != self.guild_id or payload.channel_id in (
            MOD_LOG, DISCORD_LOG, self.bot.receipt_channel_id
        ):
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild:
            await post_log(guild, DISCORD_LOG, title, f"Channel: <#{payload.channel_id}>\n{details}")

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if "content" in payload.data:
            await self.message_event(payload, "Message edited", f"Message ID: {payload.message_id}")

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        await self.message_event(payload, "Message deleted", f"Message ID: {payload.message_id}")

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        await self.message_event(payload, "Messages deleted", f"Messages: {len(payload.message_ids)}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.guild.id == self.guild_id and before.channel != after.channel:
            previous = before.channel.mention if before.channel else "Disconnected"
            current = after.channel.mention if after.channel else "Disconnected"
            await post_log(member.guild, DISCORD_LOG, "Voice channel changed",
                           f"Member: {member} ({member.id})\nFrom: {previous}\nTo: {current}")
