"""Verified account access using Bloxlink's guild-scoped API."""
import asyncio
import logging
import os
import time
import re

import aiohttp
import discord
from discord.ext import commands, tasks

GUILD = 1491365342646112386
JOIN_ROLE = 1572082428678373436
VERIFIED_ROLE = 1572082425528459365
STAFF_ROLES = (1572082402434613308, 1572274368233611436)
VERIFY_URL = 'https://blox.link/verify'
log = logging.getLogger('rivercity.verification')


class VerificationUnavailable(Exception):
    pass


def parse_roblox_id(data):
    value = data.get('robloxID') if isinstance(data, dict) else None
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return int(value) if str(value).isdigit() and int(value) > 0 else None


class Bloxlink:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.retry_at = 0

    async def lookup(self, discord_id):
        key = os.getenv('BLOXLINK_API_KEY', '').strip()
        if not key:
            raise VerificationUnavailable('Verification is awaiting staff setup. Please contact assistance.')
        async with self.lock:
            if time.monotonic() < self.retry_at:
                raise VerificationUnavailable('Verification is busy. Please try again shortly.')
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as client:
                    async with client.get(
                        f'https://api.blox.link/v4/public/guilds/{GUILD}/discord-to-roblox/{int(discord_id)}',
                        headers={'Authorization': key}, allow_redirects=False,
                    ) as response:
                        if response.status == 404:
                            return None
                        if response.status != 200:
                            self.retry_at = time.monotonic() + (60 if response.status == 429 else 15)
                            log.warning('Bloxlink lookup returned HTTP %s', response.status)
                            raise VerificationUnavailable('Account verification is temporarily unavailable. Staff have been notified in the bot logs.')
                        data = await response.json()
                roblox_id = parse_roblox_id(data)
                if roblox_id is None:
                    raise VerificationUnavailable('Bloxlink did not return a valid linked account. Finish linking and try again.')
                return roblox_id
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                raise VerificationUnavailable('Could not reach Bloxlink. Please try again shortly.') from None


def roles_for(guild):
    pending, verified = guild.get_role(JOIN_ROLE), guild.get_role(VERIFIED_ROLE)
    if not pending or not verified or pending == verified:
        raise VerificationUnavailable('Staff must configure the join and verified roles.')
    for role in (pending, verified):
        if not role.is_assignable() or role.is_default() or role.managed or role.permissions.administrator:
            raise VerificationUnavailable('The bot needs Manage Roles and must be above the join and verified roles.')
    return pending, verified


def pending_roles(guild):
    return [role for role in guild.roles if role.id == JOIN_ROLE or
            re.sub('[^a-z]', '', role.name.lower()) == 'unverified']


async def apply_verified_roles(guild, user_id, roblox_id):
    pending, verified = roles_for(guild)
    member = await guild.fetch_member(user_id)
    pending_set = [role for role in pending_roles(guild) if role in member.roles]
    for role in pending_set:
        if not role.is_assignable() or role.managed or role.permissions.administrator:
            raise VerificationUnavailable(f"I cannot remove the Unverified role ({role.id}). Staff must check role order.")
    changed = verified not in member.roles or bool(pending_set)
    # Independent role endpoints preserve unrelated roles during concurrent updates.
    if verified not in member.roles:
        await member.add_roles(verified, reason=f'Bloxlink verified Roblox ID {roblox_id}')
    if pending_set:
        await member.remove_roles(*pending_set, reason='Bloxlink confirmed Roblox account ownership')
    saved = await guild.fetch_member(user_id)
    if any(role in saved.roles for role in pending_roles(guild)) or verified not in saved.roles:
        raise VerificationUnavailable('The role update has not completed. Please try again or contact staff.')
    if changed:
        log.info('Verification roles repaired: Discord=%s CommunityMember=%s UnverifiedRemoved=%s',
                 user_id, verified.id, [role.id for role in pending_set])
    return changed


class VerificationActions(discord.ui.View):
    def __init__(self, service):
        super().__init__(timeout=None)
        self.service = service
        self.add_item(discord.ui.Button(label='Verify with Roblox', style=discord.ButtonStyle.link,
                                        url=VERIFY_URL, emoji='🔗'))

    @discord.ui.button(label='Check Verification', style=discord.ButtonStyle.success,
                       custom_id='rc:verification:check', emoji='✅')
    async def check(self, interaction, button):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild or interaction.guild.id != GUILD or interaction.user.bot:
            await interaction.followup.send('Use this panel inside River City Roleplay.', ephemeral=True)
            return
        user_id = interaction.user.id
        if user_id in self.service.busy:
            await interaction.followup.send('Your verification check is already running.', ephemeral=True)
            return
        now = time.monotonic()
        if now < self.service.cooldowns.get(user_id, 0):
            await interaction.followup.send('Please wait 15 seconds before checking again.', ephemeral=True)
            return
        self.service.busy.add(user_id)
        self.service.cooldowns[user_id] = now + 15
        try:
            pending, verified = roles_for(interaction.guild)
            roblox_id = await self.service.accounts.lookup(user_id)
            if roblox_id is None:
                await interaction.followup.send(
                    'No linked account was found. Press **Verify with Roblox**, sign in using this Discord account, '
                    'select **River City Roleplay** and finish linking your Roblox account. Then press **Check Verification**.', ephemeral=True)
                return
            await apply_verified_roles(interaction.guild, user_id, roblox_id)
            await interaction.followup.send(
                f'✅ **You are verified!**\nLinked account: https://www.roblox.com/users/{roblox_id}/profile\n'
                'Your Community Member role is active. Welcome to River City Roleplay!', ephemeral=True)
        except VerificationUnavailable as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
        except discord.HTTPException:
            log.warning('Verification role update failed for Discord member %s', user_id)
            await interaction.followup.send('I could not update your roles. Please contact staff and try again.', ephemeral=True)
        finally:
            self.service.busy.discard(user_id)


class VerificationView(discord.ui.LayoutView):
    def __init__(self, service, guild=None):
        super().__init__(timeout=None)
        actions = VerificationActions(service)
        self.check = actions.check
        row = discord.ui.ActionRow()
        for button in list(actions.children):
            actions.remove_item(button)
            row.add_item(button)
        intro = discord.ui.TextDisplay(
            '## RIVER CITY ROLEPLAY | VERIFICATION\n'
            'Welcome to River City Roleplay! Link your Roblox account to unlock our community.')
        header = (discord.ui.Section(intro, accessory=discord.ui.Thumbnail(guild.icon.url))
                  if guild and guild.icon else intro)
        self.add_item(discord.ui.Container(
            header, discord.ui.Separator(),
            discord.ui.TextDisplay(
                '**01 - Link your account**\nPress **Verify with Roblox** and complete linking on Bloxlink. '
                'Use your current Discord account and select **River City Roleplay**.'),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay('**02 - Confirm your verification**\nReturn here and press **Check Verification**. '
                'Your roles sync automatically after linking. You can also press **Check Verification** to update them now.'),
            discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
            discord.ui.TextDisplay('**03 - Join the community**\nRead the rules and join a session using your linked Roblox account. '
                'Stay connected to a voice channel while in game.'),
            discord.ui.Separator(),
            discord.ui.TextDisplay('**Need help?** Open a ticket in <#1572082489743249591>.'),
            row, discord.ui.Separator(),
            discord.ui.TextDisplay('-# River City Roleplay | Account linking powered by Bloxlink'),
            ))


def is_verification_panel(message):
    if any('VERIFICATION' in (embed.title or '').upper() and 'RIVER CITY' in (embed.title or '').upper()
           for embed in message.embeds):
        return True
    return any(getattr(item, 'custom_id', None) == 'rc:verification:check'
               for item in discord.ui.LayoutView.from_message(message).walk_children())


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.accounts = Bloxlink()
        self.busy = set()
        self.cooldowns = {}
        self.panel_lock = asyncio.Lock()
        self.checked_connection = False
        self.upgrade_task = None
        self.sync_due = {}
        self.sync_queue = set()
        self.sync_roles.start()
        bot.add_view(VerificationView(self))

    def cog_unload(self):
        self.sync_roles.cancel()
        if self.upgrade_task:
            self.upgrade_task.cancel()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if after.guild.id != GUILD or after.bot or before.roles == after.roles:
            return
        if any(role in after.roles for role in pending_roles(after.guild)) or not after.get_role(VERIFIED_ROLE):
            self.sync_queue.add(after.id)
            self.sync_due[after.id] = 0

    @tasks.loop(seconds=15)
    async def sync_roles(self):
        if not self.bot.is_ready() or not os.getenv('BLOXLINK_API_KEY'):
            return
        guild = self.bot.get_guild(GUILD)
        if not guild:
            return
        now = time.monotonic()
        unverified = pending_roles(guild)
        candidates = []
        for member in guild.members:
            marker = any(re.sub('[^a-z]', '', role.name.lower()) == 'verified' for role in member.roles)
            needs_sync = any(role in member.roles for role in unverified) or (marker and not member.get_role(VERIFIED_ROLE))
            if not member.bot and (needs_sync or member.id in self.sync_queue):
                if member.id not in self.busy and self.sync_due.get(member.id, 0) <= now:
                    candidates.append(member)
        candidates.sort(key=lambda m: (m.id not in self.sync_queue, self.sync_due.get(m.id, 0)))
        for member in candidates[:3]:
            self.busy.add(member.id)
            self.sync_queue.discard(member.id)
            self.sync_due[member.id] = now + 120
            try:
                account = await self.accounts.lookup(member.id)
                if account is not None:
                    await apply_verified_roles(guild, member.id, account)
            except VerificationUnavailable as exc:
                log.warning('Verification role sync waiting: %s', exc)
            except discord.HTTPException as exc:
                log.warning('Verification role sync failed: member=%s HTTP=%s', member.id, exc.status)
            finally:
                self.busy.discard(member.id)

    @sync_roles.before_loop
    async def before_role_sync(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        if self.checked_connection:
            return
        guild = self.bot.get_guild(GUILD)
        if not guild:
            return
        if self.upgrade_task is None:
            self.upgrade_task = asyncio.create_task(self.upgrade_panels(guild))
        try:
            pending, verified = roles_for(guild)
            log.info('Verification role mapping: pending=%s (%s); community=%s (%s); pending members=%s',
                     pending.name, pending.id, verified.name, verified.id, len(pending.members))
            log.info('All Unverified roles: %s; cached members=%s total=%s',
                     [(r.id, r.name, len(r.members)) for r in pending_roles(guild)], len(guild.members), guild.member_count)
            account = await self.accounts.lookup(guild.owner_id)
            log.info('Bloxlink guild lookup completed; owner linked: %s; verification roles assignable: True', bool(account))
            self.checked_connection = True
        except VerificationUnavailable as exc:
            log.warning('Verification startup check: %s', exc)

    @commands.command(name='verify')
    @commands.guild_only()
    @commands.cooldown(1, 10, commands.BucketType.guild)
    async def verify(self, ctx, mode: str = ''):
        """Post/update the verification panel. Use .verify lock to gate public channels."""
        if not (ctx.author.guild_permissions.manage_guild or any(ctx.author.get_role(n) for n in STAFF_ROLES)):
            await ctx.send('Only staff can post the verification panel. Use its buttons to verify your account.')
            return
        if mode not in ('', 'lock'):
            await ctx.send('Usage: `.verify` or `.verify lock` (Manage Server required).')
            return
        async with self.panel_lock:
            if mode == 'lock':
                if not ctx.author.guild_permissions.manage_guild:
                    await ctx.send('Manage Server is required to configure verification access.')
                    return
                try:
                    if not await self.accounts.lookup(ctx.author.id):
                        raise VerificationUnavailable('Link your own account with Bloxlink first so setup can validate the connection.')
                    await self.gate(ctx)
                except VerificationUnavailable as exc:
                    await ctx.send(str(exc))
                    return
                except discord.HTTPException:
                    await ctx.send('Channel setup could not finish. Check Manage Channels/Manage Roles and run `.verify lock` again. Some channels may already be gated.')
                    return
            view = VerificationView(self, ctx.guild)
            async for message in ctx.channel.history(limit=100):
                if message.author.id == ctx.bot.user.id and is_verification_panel(message):
                    await self.update_panel(message, ctx.guild)
                    return
            sent = await ctx.send(view=view, allowed_mentions=discord.AllowedMentions.none())
            await self.confirm_panel(sent)

    async def confirm_panel(self, message):
        saved = await message.channel.fetch_message(message.id)
        valid = saved.flags.components_v2 and not saved.embeds and any(c.type.value == 17 for c in saved.components)
        log.info('Verification panel check: channel=%s message=%s components_v2=%s embeds=%s container=%s',
                 saved.channel.id, saved.id, saved.flags.components_v2, len(saved.embeds),
                 any(c.type.value == 17 for c in saved.components))
        if not valid:
            raise RuntimeError('Discord did not store the verification panel as Components V2')

    async def update_panel(self, message, guild):
        await message.edit(content=None, embeds=[], attachments=[], view=VerificationView(self, guild),
                           allowed_mentions=discord.AllowedMentions.none())
        await self.confirm_panel(message)

    async def upgrade_panels(self, guild):
        priority = guild.get_channel(1572426473057558579)
        channels = ([priority] if priority else []) + [c for c in [*guild.text_channels, *guild.threads] if c != priority]
        log.info('Verification migration starting; priority channel available: %s', bool(priority))
        for channel in channels:
            try:
                found = False
                if channel == priority:
                    perms = channel.permissions_for(guild.me)
                    log.info('Verification channel permissions: view=%s history=%s send=%s', perms.view_channel, perms.read_message_history, perms.send_messages)
                    if not (perms.view_channel and perms.read_message_history and perms.send_messages):
                        overwrite = channel.overwrites_for(guild.me)
                        overwrite.view_channel = True
                        overwrite.read_message_history = True
                        overwrite.send_messages = True
                        await channel.set_permissions(guild.me, overwrite=overwrite, reason='Maintain the requested verification panel')
                async for message in channel.history(limit=100):
                    if channel == priority and message.author.id == self.bot.user.id:
                        log.info('Verification candidate: message=%s v2=%s embeds=%s component_types=%s', message.id, message.flags.components_v2, len(message.embeds), [c.type.value for c in message.components])
                    if message.author.id == self.bot.user.id and is_verification_panel(message):
                        found = True
                        await self.update_panel(message, guild)
                if channel == priority and not found:
                    sent = await channel.send(view=VerificationView(self, guild),
                        nonce=f'rcv2-{channel.id}', allowed_mentions=discord.AllowedMentions.none())
                    await self.confirm_panel(sent)
            except discord.HTTPException as exc:
                log.warning('Could not update verification panels in %s: HTTP %s', channel.id, exc.status)
            except Exception:
                log.exception('Verification migration failed in channel %s', channel.id)

    async def gate(self, ctx):
        pending, verified = roles_for(ctx.guild)
        me = ctx.guild.me
        if not me.guild_permissions.manage_channels or not me.guild_permissions.manage_roles:
            raise VerificationUnavailable('The bot needs Manage Channels and Manage Roles before setting up access.')
        # Keep onboarding/support reachable. Never grant the verified role access
        # to channels that were private to staff or individual ticket owners.
        exemptions = {ctx.channel.id, 1572082493715386398, 1572082489743249591}
        targets = [c for c in ctx.guild.channels
                   if not isinstance(c, discord.CategoryChannel) and c.id not in exemptions
                   and (c.permissions_for(ctx.guild.default_role).view_channel
                        or c.overwrites_for(verified).view_channel is True)]
        for channel in targets:
            # Avoid turning a private role-restricted room into a public one.
            if not channel.permissions_for(ctx.guild.default_role).view_channel and channel.overwrites_for(pending).view_channel is not False:
                continue
            for target in (me, *[r for n in STAFF_ROLES if (r := ctx.guild.get_role(n))]):
                overwrite = channel.overwrites_for(target)
                overwrite.view_channel = True
                await channel.set_permissions(target, overwrite=overwrite, reason='Preserve bot and staff access during verification setup')
            for target, overwrite in channel.overwrites.items():
                if target in (me, verified) or target.id in STAFF_ROLES:
                    continue
                privileged = (target.permissions.administrator if isinstance(target, discord.Role)
                              else target.guild_permissions.administrator)
                if privileged:
                    continue
                if overwrite.view_channel is True:
                    overwrite.view_channel = None
                    await channel.set_permissions(target, overwrite=overwrite, reason='Require verified role for public community access')
            for role, allowed in ((verified, True), (pending, False), (ctx.guild.default_role, False)):
                overwrite = channel.overwrites_for(role)
                overwrite.view_channel = allowed
                await channel.set_permissions(role, overwrite=overwrite, reason='River City verified member access')
        for ident in exemptions:
            channel = ctx.guild.get_channel(ident)
            if channel:
                overwrite = channel.overwrites_for(pending)
                overwrite.view_channel = True
                await channel.set_permissions(pending, overwrite=overwrite, reason='Keep verification and assistance available')
        log.info('Verification access configured for %s public channels; panel channel %s', len(targets), ctx.channel.id)
