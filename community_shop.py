import asyncio
import logging

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
    ("Dimond", 2094392860, 1573457988222451804),
)
log = logging.getLogger("rivercity.shop")


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
            await desk.record(f"perks:{ctx.message.id}", tier, "tier-perks", benefits, ctx.author.id)
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
        perks = discord.Embed(title="River City Roleplay | Supporter Perks")
        desk = self.bot.get_cog('StaffDesk')
        overrides = {}
        try:
            async with desk.lock:
                await desk.load(guild)
                overrides = {r['user']: r['detail'] for r in desk.rows.values() if r['kind'] == 'tier-perks'}
        except discord.HTTPException:
            log.exception('Could not load saved tier perks')
        complete = True
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as client:
            for tier, (name, pid, role_id) in enumerate(TIERS, 1):
                url = f"https://www.roblox.com/game-pass/{pid}"
                shop.add_field(name=f"Tier {tier} · {name}", value=f"[View pass]({url}) · <@&{role_id}>", inline=False)
                lines = [f"Verified Discord role · <@&{role_id}>"]
                try:
                    async with client.get(f"https://apis.roblox.com/game-passes/v1/game-passes/{pid}/product-info") as response:
                        response.raise_for_status()
                        details = (await response.json()).get("Description")
                        if details and details.strip():
                            lines.append(details.strip())
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, AttributeError):
                    complete = False
                if tier in overrides:
                    lines.append(overrides[tier])
                lines.append(f"[Full Roblox pass details]({url})")
                value = "\n".join(lines)
                for start in range(0, len(value), 1000):
                    perks.add_field(name=f"Tier {tier} · {name}" if not start else f"{name} continued",
                                    value=value[start:start+1000], inline=False)
        shop.add_field(name="What's included?", value=f"See all four tiers in <#{PERKS}>.", inline=False)
        for cid, embed, marker in ((SHOP, shop, "rc-shop"), (PERKS, perks, "rc-perks")):
            channel = guild.get_channel(cid)
            if channel is None:
                continue
            embed.set_footer(text=marker)
            try:
                existing = None
                async for msg in channel.history(limit=None):
                    if msg.author.id == self.bot.user.id and msg.embeds and msg.embeds[0].footer.text == marker:
                        existing = msg
                        break
                view = Purchase(self.bot) if cid == SHOP else None
                if existing:
                    if (cid != PERKS or complete or overrides) and existing.embeds[0].to_dict() != embed.to_dict():
                        await existing.edit(embed=embed, view=view)
                else:
                    await channel.send(embed=embed, view=view, nonce=marker)
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
            embeds = []
            for i, attachment in enumerate(message.attachments):
                f = await attachment.to_file(filename=f"{i}-{attachment.filename}", use_cached=True, spoiler=attachment.is_spoiler())
                files.append(f)
                if attachment.is_spoiler() or not (attachment.content_type or "").startswith("image/"):
                    continue
                embed = discord.Embed()
                embed.set_image(url=f"attachment://{f.filename}")
                if not embeds:
                    embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
                embeds.append(embed)
            await message.channel.send(content=message.content or None, files=files, embeds=embeds,
                                       reference=message.reference, nonce=f"img{message.id}", allowed_mentions=discord.AllowedMentions.none())
            await message.delete()
        except discord.HTTPException:
            log.exception("Image conversion failed for %s", message.id)
        finally:
            for file in files:
                file.close()
