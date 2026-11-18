"""Verified account access using Bloxlink's guild-scoped API."""
import asyncio
import logging
import os
import time

import aiohttp
import discord
from discord.ext import commands

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


class VerificationView(discord.ui.View):
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
            member = await interaction.guild.fetch_member(user_id)
            # Remove the restrictive pending role before granting access. A failed
            # add leaves the member without access; retry safely completes it.
            if pending in member.roles:
                await member.remove_roles(pending, reason='Bloxlink confirmed Roblox account ownership')
            try:
                await member.add_roles(verified, reason=f'Bloxlink verified Roblox ID {roblox_id}')
            except discord.HTTPException:
                await member.add_roles(pending, reason='Restore pending role after failed verification role assignment')
                raise
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


def verification_embed(guild):
    embed = discord.Embed(title='RIVER CITY ROLEPLAY • VERIFICATION', colour=0x1066EC,
        description='Welcome to River City Roleplay! Link your Roblox account to unlock our community.\n\n'
        '**01 — Link your account**\nPress **Verify with Roblox** and complete verification on Bloxlink. '
        'Use your current Discord account and select **River City Roleplay**.\n\n'
        '**02 — Confirm your verification**\nReturn here and press **Check Verification**. '
        'We confirm your linked account before giving you the Community Member role.\n\n'
        '**03 — Join the community**\nRead the rules, explore the channels, and join a session. '
        'Use the same Roblox account when playing ER:LC.\n\n'
        '**Need help?** Open a ticket in <#1572082489743249591>.')
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text='River City Roleplay • Account linking powered by Bloxlink')
    return embed


class Verification(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.accounts = Bloxlink()
        self.busy = set()
        self.cooldowns = {}
        self.panel_lock = asyncio.Lock()
        bot.add_view(VerificationView(self))

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
            view = VerificationView(self)
            async for message in ctx.channel.history(limit=100):
                if message.author.id == ctx.bot.user.id and any(
                    getattr(item, 'custom_id', None) == 'rc:verification:check'
                    for row in message.components for item in getattr(row, 'children', [])
                ):
                    await message.edit(embed=verification_embed(ctx.guild), view=view)
                    return
            await ctx.send(embed=verification_embed(ctx.guild), view=view,
                           allowed_mentions=discord.AllowedMentions.none())

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
