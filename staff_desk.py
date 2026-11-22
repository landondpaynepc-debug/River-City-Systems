from cards import layout, read_card, footer
import asyncio
import hashlib
import json
import logging
import time

import discord
from discord.ext import commands

from discord_logs import MOD_LOG, post_log
from staff_access import has_staff_role
from verification import GUILD

WELCOME = 1572082493715386398
PREFIX = "rc-staff-v1 "
log = logging.getLogger("rivercity.staff")


def staff(member):
    return isinstance(member, discord.Member) and (
        member.guild_permissions.manage_guild or has_staff_role(member)
    )


class CallView(discord.ui.View):
    def __init__(self, service):
        super().__init__(timeout=None)
        self.service = service

    @discord.ui.button(label="Respond to call", custom_id="rc:staff:respond")
    async def respond(self, interaction, button):
        if interaction.guild_id != GUILD or not staff(interaction.user):
            return await interaction.response.send_message("Staff only.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        key = f"call:{interaction.message.id}"
        async with self.service.lock:
            await self.service.load(interaction.guild)
            if footer(interaction.message) == f"Caller {interaction.user.id}":
                return await interaction.followup.send("Another staff member must respond.", ephemeral=True)
            row = await self.service.record(key, interaction.user.id, "point", "Staff call response")
        embed = read_card(interaction.message)
        embed.clear_fields()
        embed.set_footer(text=footer(interaction.message))
        embed.title = "Staff call answered"
        embed.add_field(name="Responding staff", value=f"<@{row['user']}>")
        await interaction.message.edit(content=None, embeds=[], view=layout(embed))
        await interaction.followup.send(f"Response credited to <@{row['user']}>.", ephemeral=True)


class StaffDesk(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()
        self.room = None
        self.rows = {}

    async def load(self, guild):
        if self.room is None:
            room = await self.bot.receipt_channel(guild)
            rows = {}
            async for msg in room.history(limit=None, oldest_first=True):
                if msg.author.id == self.bot.user.id and msg.content.startswith(PREFIX):
                    row = json.loads(msg.content[len(PREFIX):])
                    rows[row["key"]] = row
            self.rows, self.room = rows, room

    async def record(self, key, user, kind, detail, actor=0):
        if key not in self.rows:
            row = dict(key=key, user=user, kind=kind, detail=detail[:650], actor=actor, at=int(time.time()))
            msg = await self.room.send(PREFIX + json.dumps(row, ensure_ascii=False), silent=True,
                                       nonce=hashlib.sha256(key.encode()).hexdigest()[:24])
            self.rows[key] = json.loads(msg.content[len(PREFIX):])
        return self.rows[key]

    def balance(self, user):
        return sum(1 if r["kind"] == "point" else -175 if r["kind"] == "reward" else 0
                   for r in self.rows.values() if r["user"] == user)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, event):
        if event.guild_id != GUILD or event.channel_id != WELCOME or str(event.emoji) != "👋":
            return
        member = event.member
        if not staff(member) or member.bot:
            return
        message = await member.guild.get_channel(WELCOME).fetch_message(event.message_id)
        if message.author.id != self.bot.user.id:
            return
        def is_welcome(component):
            return "to **River City Roleplay**! We hope you enjoy your stay." in getattr(component, "content", "") or any(
                is_welcome(child) for child in getattr(component, "children", [])
            )
        if any(is_welcome(component) for component in message.components):
            async with self.lock:
                await self.load(member.guild)
                await self.record(f"wave:{message.id}:{member.id}", member.id, "point", "Welcome wave")

    @commands.Cog.listener()
    async def on_river_mod_call(self, guild, row):
        # A mod call can be returned first as unanswered and later with a moderator.
        ident = lambda value: str(value or "").rpartition(":")[-1]
        responder = ident(row.get("Moderator"))
        caller = ident(row.get("Caller"))
        if not responder.isdecimal() or not caller.isdecimal() or caller == responder:
            return
        link = self.bot.get_cog("VoiceGuard")
        member = await link.linked_member(guild, int(responder)) if link else None
        if staff(member) and not member.bot:
            async with self.lock:
                await self.load(guild)
                await self.record(f"erlc:{caller}:{row['Timestamp']}", member.id, "point", "Answered ER:LC moderator call")

    @commands.command()
    @commands.cooldown(1, 120, commands.BucketType.user)
    async def staffcall(self, ctx, *, reason):
        embed = discord.Embed(title="Staff assistance requested", description=reason[:2000])
        embed.add_field(name="Requested by", value=ctx.author.mention)
        embed.set_footer(text=f"Caller {ctx.author.id}")
        room = ctx.guild.get_channel(MOD_LOG)
        if room is None:
            raise commands.BadArgument("The staff log channel is unavailable.")
        await room.send(view=layout(embed, controls=CallView(self)))
        await ctx.reply("Your call has been sent to staff.", mention_author=False)

    @commands.command()
    async def points(self, ctx):
        async with self.lock:
            await self.load(ctx.guild)
            points = self.balance(ctx.author.id)
        await ctx.send(f"{ctx.author.mention} has **{points} staff points**. A reward costs 175 points.")

    @commands.command()
    async def redeem(self, ctx, choice: str, *, department=""):
        options = {"staff": "Next staff rank interview", "department": "Next department rank interview", "roblox": "Roblox payment"}
        choice = choice.lower()
        if not staff(ctx.author) or choice not in options or (choice == "department" and not department.strip()):
            raise commands.BadArgument("Staff can use .redeem staff, .redeem department <name>, or .redeem roblox.")
        detail = options[choice] + (" — " + department[:100] if choice == "department" else "")
        async with self.lock:
            await self.load(ctx.guild)
            if self.balance(ctx.author.id) < 175:
                return await ctx.send("You need 175 staff points.")
            room = ctx.guild.get_channel(MOD_LOG)
            if not room:
                raise commands.BadArgument("The moderation log is unavailable.")
            await room.send(f"Reward request #{ctx.message.id} · {ctx.author.mention} · {detail}",
                            nonce=f"rw{ctx.message.id}")
            await self.record(f"reward:{ctx.message.id}", ctx.author.id, "reward", detail)
        await ctx.send("175 points redeemed. Management has received your request.")

    @commands.command()
    async def shift(self, ctx, action="status"):
        if not staff(ctx.author):
            raise commands.BadArgument("Shifts are for staff.")
        action = action.lower()
        states = {"start": ("off",), "break": ("start", "resume"), "resume": ("break",), "end": ("start", "break", "resume")}
        async with self.lock:
            await self.load(ctx.guild)
            history = [r for r in self.rows.values() if r["user"] == ctx.author.id and r["kind"] == "shift"]
            current = history[-1]["detail"] if history else "off"
            if current == "end":
                current = "off"
            if action == "status":
                active = 0
                for i, row in enumerate(history):
                    if row["detail"] in ("start", "resume"):
                        until = history[i+1]["at"] if i+1 < len(history) else int(time.time())
                        active += max(0, until-row["at"])
                return await ctx.send(f"Shift status: **{current}** · Total on duty: **{active // 60} minutes**.")
            if current not in states.get(action, ()):
                raise commands.BadArgument(f"Current state: {current}. Use start, break, resume, end, or status.")
            await self.record(f"shift:{ctx.message.id}", ctx.author.id, "shift", action)
        await post_log(ctx.guild, MOD_LOG, "Staff shift", f"{ctx.author.mention} · {action}")
        await ctx.send(f"Shift updated: **{action}**.")

    async def case(self, ctx, member, kind, detail):
        async with self.lock:
            await self.load(ctx.guild)
            await self.record(f"case:{ctx.message.id}", member.id, kind, detail, ctx.author.id)
        await post_log(ctx.guild, MOD_LOG, kind.title(), f"Member: {member.mention}\nStaff: {ctx.author.mention}\n{detail}")
        await ctx.send(f"Recorded {kind} for {member.mention}.")

    async def rank(self, ctx, member, role, reason, promote):
        if member.bot or member == ctx.author or member == ctx.guild.owner or role.is_default() or not role.is_assignable():
            raise commands.BadArgument("Choose an assignable role and another eligible member.")
        if ctx.author != ctx.guild.owner and (role >= ctx.author.top_role or member.top_role >= ctx.author.top_role):
            raise commands.BadArgument("The member and role must be below your highest role.")
        if member.top_role >= ctx.guild.me.top_role or (role in member.roles) == promote:
            raise commands.BadArgument("Check the current role and the bot’s role hierarchy.")
        change = member.add_roles if promote else member.remove_roles
        await change(role, reason=f"{ctx.author} ({ctx.author.id}): {reason}"[:512])
        await self.case(ctx, member, "promotion" if promote else "demotion", f"{role.name} · {reason}")

    @commands.command()
    @commands.has_guild_permissions(manage_roles=True)
    async def promote(self, ctx, member: discord.Member, role: discord.Role, *, reason):
        await self.rank(ctx, member, role, reason, True)

    @commands.command()
    @commands.has_guild_permissions(manage_roles=True)
    async def demote(self, ctx, member: discord.Member, role: discord.Role, *, reason):
        await self.rank(ctx, member, role, reason, False)

    @commands.command()
    @commands.has_guild_permissions(moderate_members=True)
    async def infraction(self, ctx, member: discord.Member, *, reason):
        await self.case(ctx, member, "infraction", reason)

    @commands.command()
    @commands.has_guild_permissions(moderate_members=True)
    async def memberlog(self, ctx, member: discord.Member, *, note):
        await self.case(ctx, member, "member log", note)

    @commands.command(aliases=["mylogs"])
    async def logs(self, ctx, member: discord.Member = None):
        target = member or ctx.author
        if target != ctx.author and not ctx.author.guild_permissions.moderate_members:
            raise commands.BadArgument("You can only view your own records.")
        async with self.lock:
            await self.load(ctx.guild)
            rows = [r for r in self.rows.values() if r["user"] == target.id and r["kind"] in ("promotion", "demotion", "infraction", "member log", "reward")]
        lines = [f"<t:{r['at']}:d> · **{r['kind'].title()}** · {r['detail']}" for r in rows]
        try:
            await ctx.author.send(f"River City records for {target}: {len(rows)}")
            for line in lines:
                await ctx.author.send(line)
        except discord.Forbidden:
            return await ctx.send("Enable server direct messages to receive your records.")
        await ctx.send("Your records were sent by DM.")
