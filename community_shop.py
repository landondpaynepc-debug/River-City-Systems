from cards import BODY, FIELD, layout, footer, text_parts
import asyncio
import logging
from pathlib import Path

import aiohttp
import discord
from discord.ext import commands, tasks

from verification import GUILD, VerificationUnavailable

SHOP = 1572082475520499712
PHOTOS = 1572093132789522525
PERKS = 1573456915067969586
STORE = "https://www.roblox.com/games/103698123997551/River-City-Roleplay-Racing#!/store"
TIERS = (
    ("Bronze", 2094218921, 1573457828650295459),
    ("Silver", 2093558908, 1573457830919536660),
    ("Platinum", 2093018918, 1573457833368748182),
    ("Diamond", 2094392860, 1573457988222451804),
)
log = logging.getLogger("rivercity.shop")


PERK_DETAILS = (
    """- Access to `#bronze-lounge`
- Bronze name color
- **$5,000** in-game cash on claim
- 1 free **civilian vehicle** from the Bronze list (e.g. basic sedan, SUV, or truck)
- Priority in support tickets
- Exclusive entry into monthly Bronze vehicle giveaways""",
    """- Access to `#silver-lounge`
- Silver name color
- **$15,000** cash on claim
- 1 free **mid-tier vehicle** (e.g. sports car, police interceptor package, or higher-end civilian)
- Faster department application processing
- Reduced cooldowns on certain commands
- Priority queue for staff-hosted events""",
    """- Access to `#platinum-lounge`
- Platinum name color + role icon
- **$35,000** cash on claim
- 1 free **high-tier vehicle** of choice (e.g. supercar, unmarked police car, fire apparatus, or EMS vehicle)
- 1 free **property** (house/apartment)
- Priority department placement (PD, FD, EMS, etc. when slots open)
- Ability to request temporary vehicle liveries / custom plates (staff approval)""",
    """- Access to `#diamond-lounge` (highest)
- Diamond name color + exclusive animated icon
- **$75,000** cash on claim
- 1 free **top-tier vehicle** + 1 free **high-end property**
- Permanent custom role (name + color)
- Highest priority for department applications and promotions
- Ability to request **1 custom vehicle** per month (within reason & balance)
- Direct feedback channel with senior staff
- Exclusive Diamond-only seasonal rewards & early access to new vehicles/updates""",
)
CLAIM_RULES = (
    "- All physical perks (cash, cars, properties) must be claimed via ticket within **7 days** or they expire.\n"
    "- Higher tiers keep all lower-tier lounge access and name colors."
)


class Purchase(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(discord.ui.Button(label="Visit Roblox store", url=STORE))

    @discord.ui.button(label="Check Purchase", custom_id="rc:shop:check", style=discord.ButtonStyle.primary)
    async def check(self, interaction, button):
        if interaction.guild_id != GUILD:
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            rid = await self.bot.get_cog("Verification").accounts.lookup(interaction.user.id)
        except VerificationUnavailable:
            return await interaction.followup.send("Bloxlink is unavailable. Try again shortly.", ephemeral=True)
        if not rid:
            return await interaction.followup.send("Link your Roblox account with Bloxlink first.", ephemeral=True)
        results = []
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=12)) as client:
            for name, pid, role_id in TIERS:
                try:
                    url = f"https://inventory.roblox.com/v1/users/{rid}/items/GamePass/{pid}/is-owned"
                    async with client.get(url, allow_redirects=False) as response:
                        response.raise_for_status()
                        owned = await response.json()
                    if not isinstance(owned, bool):
                        raise ValueError("Unexpected ownership response")
                    if not owned:
                        results.append(f"{name} · No purchase found")
                        continue
                    role = interaction.guild.get_role(role_id)
                    if not role or role.permissions.administrator or not role.is_assignable():
                        results.append(f"{name} · Owned. Staff must check the role hierarchy.")
                        continue
                    if role not in interaction.user.roles:
                        await interaction.user.add_roles(role, reason=f"Verified Roblox pass {pid} for account {rid}")
                    results.append(f"{name} · Verified · {role.mention}")
                except (discord.HTTPException, aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                    results.append(f"{name} · Could not complete the check. Try again or contact staff.")
        await interaction.followup.send("\n".join(results), ephemeral=True)


class CommunityShop(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.panel_lock = asyncio.Lock()
        self.sync.start()

    def cog_unload(self):
        self.sync.cancel()

    @commands.command()
    @commands.has_guild_permissions(manage_guild=True)
    async def setperks(self, ctx, tier: commands.Range[int, 1, 4], *, benefits):
        if len(benefits) > 650:
            raise commands.BadArgument("Use up to 650 characters for a tier’s perk list.")
        desk = self.bot.get_cog("StaffDesk")
        async with desk.lock:
            await desk.load(ctx.guild)
            await desk.record(f"perks:{ctx.message.id}", tier, "tier-perks-v2", benefits, ctx.author.id)
        async with self.panel_lock:
            await self.publish()
        await ctx.send(f"Tier {tier} perks saved.")

    @tasks.loop(minutes=30)
    async def sync(self):
        async with self.panel_lock:
            await self.publish()

    async def publish(self):
        guild = self.bot.get_guild(GUILD)
        if not guild:
            return
        shop = discord.Embed(title="River City Roleplay | Supporter Shop",
            description="Choose a pass on Roblox, then use **Check Purchase** to claim its Discord role with your linked account.")
        perks = discord.Embed(title="River City Roleplay – Supporter Perks")
        desk = self.bot.get_cog('StaffDesk')
        overrides = {}
        try:
            async with desk.lock:
                await desk.load(guild)
                overrides = {r['user']: r['detail'] for r in desk.rows.values() if r['kind'] == 'tier-perks-v2'}
        except discord.HTTPException:
            log.exception('Could not load saved tier perks')
        for tier, (name, pid, role_id) in enumerate(TIERS, 1):
            url = f"https://www.roblox.com/game-pass/{pid}"
            shop.add_field(name=f"Tier {tier} · {name}", value=f"[View pass]({url}) · <@&{role_id}>", inline=False)
            lines = []
            if tier > 1:
                lines.append(f"*Everything from {TIERS[tier-2][0]} +*\n")
            lines.append(f"- Verified Discord role: <@&{role_id}>")
            lines.append(overrides.get(tier) or PERK_DETAILS[tier-1])
            perks.add_field(name=f"Tier {tier} – {name}", value="\n".join(lines), inline=False)
        perks.add_field(name="Claim rules", value=CLAIM_RULES, inline=False)
        shop.add_field(name="What's included?", value=f"See all four tiers in <#{PERKS}>.", inline=False)
        for cid, embed, marker in ((SHOP, shop, "rc-shop"), (PERKS, perks, "rc-perks")):
            channel = guild.get_channel(cid)
            if channel is None:
                continue
            embed.set_footer(text=marker)
            try:
                existing = None
                async for msg in channel.history(limit=None):
                    if msg.author.id == self.bot.user.id and footer(msg) == marker:
                        existing = msg
                        break
                view = Purchase(self.bot) if cid == SHOP else None
                banner = "shop.webp" if cid == SHOP else "perks.webp"
                panel = layout(embed, controls=view, banner=banner)
                if existing and existing.flags.components_v2:
                    # Compare persisted text independently of Discord-generated media URLs.
                    if (any(a.filename == banner for a in existing.attachments)
                        and text_parts(existing, BODY) == ([embed.description] if embed.description else [])
                        and [n.content for n in panel.walk_children() if isinstance(n, discord.ui.TextDisplay) and n.id and n.id >= FIELD]
                        == [part for i in range(25) for part in text_parts(existing, FIELD+i)]):
                        continue
                art = discord.File(Path(__file__).with_name("assets") / banner, filename=banner)
                try:
                    if existing:
                        await existing.edit(content=None, embeds=[], attachments=[art], view=panel)
                    else:
                        await channel.send(file=art, view=panel, nonce=marker)
                finally:
                    art.close()
            except discord.HTTPException:
                log.exception("Could not publish panel in %s", cid)

    @sync.before_loop
    async def ready(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.guild.id != GUILD or message.author.bot or not message.attachments:
            return
        if message.channel.id != PHOTOS:
            return
        if message.stickers or message.poll or message.type not in (discord.MessageType.default, discord.MessageType.reply):
            return
        if not any(not a.is_spoiler() and (a.content_type or "").startswith("image/") for a in message.attachments):
            return
        if any(a.size > message.guild.filesize_limit for a in message.attachments):
            return
        files = []
        try:
            panel = discord.ui.LayoutView(timeout=None)
            box = discord.ui.Container(discord.ui.TextDisplay(f'**Posted by** {message.author.mention}'))
            panel.add_item(box)
            if message.content:
                box.add_item(discord.ui.TextDisplay(message.content[:3900]))
            gallery = discord.ui.MediaGallery()
            other_files = []
            for i, attachment in enumerate(message.attachments):
                f = await attachment.to_file(filename=f"{i}-{attachment.filename}", use_cached=True, spoiler=attachment.is_spoiler())
                files.append(f)
                if attachment.is_spoiler() or not (attachment.content_type or "").startswith("image/"):
                    other_files.append(discord.ui.File(f"attachment://{f.filename}", spoiler=attachment.is_spoiler()))
                    continue
                gallery.add_item(media=f"attachment://{f.filename}", description=attachment.description or attachment.filename)
            box.add_item(gallery)
            for item in other_files:
                box.add_item(item)
            await message.channel.send(files=files, view=panel,
                                       reference=message.reference, nonce=f"img{message.id}", allowed_mentions=discord.AllowedMentions.none())
            await message.delete()
        except discord.HTTPException:
            log.exception("Image conversion failed for %s", message.id)
        finally:
            for file in files:
                file.close()
