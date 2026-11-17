"""Discord dashboard and assistance panels for River City Roleplay."""
import asyncio
import os
from pathlib import Path

import discord
from discord import ui

BRAND = "River City Roleplay"
ASSETS = Path(__file__).with_name("assets")
RULES = {
    "Discord Regulations": "**Respect other members**\nDiscuss the scene or the decision without attacking the person behind it. Slurs, harassment, threats, and repeated unwanted DMs can be reported to the assistance desk.\n\n**Use the right channel**\nKeep session coordination in the sessions channel and reports in a private ticket. Ask once, give staff time to respond, and avoid repeated mentions or mass pings.\n\n**Protect private information**\nKeep real names, contact details, and private conversations out of public chat. When submitting evidence, crop unrelated messages and identify the time, channel, and people involved.\n\n**Resolve disagreements**\nIf staff pause a scene, follow their direction and let other players continue. Open a ticket afterward with the relevant message link or clip. Use High Rank Support for sensitive staff concerns.",
    "In-Game Regulations": "**Start scenes fairly**\nGive other players a reason to engage and time to react. Establish what your character can actually see or hear. Information learned from a stream, Discord call, or player list stays out of the scene.\n\n**Play consequences**\nRoleplay collisions, injuries, arrests, and vehicle damage. A character who has just crashed should give responders a chance to assess the scene before driving away.\n\n**Keep control of your character**\nDescribe your own actions and let others decide their reactions. Avoid forcing outcomes, using glitches, resetting to escape detention, or returning immediately to a scene after your character has died.\n\n**Respect scene boundaries**\nGive active calls space. Ask the host before staging a large event or entering a restricted department scene. If a dispute stops play, note the time and use the assistance desk so the session can continue.",
    "Banned Vehicles & Items": "**Check session restrictions**\nRead the host’s briefing before spawning special vehicles or equipment. Restrictions can change with the department, event, or training scenario. Ask about the exact model when its status is unclear.\n\n**Match the vehicle to your role**\nUse a department vehicle only when authorized to act for that department. Emergency lights, liveries, and equipment should match the assignment you are playing.\n\n**Keep scenes accessible**\nPark clear of spawn points, station exits, and active scenes. Avoid using vehicles or props to obstruct other players outside an agreed roleplay scenario.\n\n**Request a ruling**\nGive General Support the vehicle name, intended use, and session. Wait for a host decision on disputed equipment. If asked to switch, safely pull over and choose an approved alternative.",
    "Booster Vehicles": "**Confirm eligibility**\nBefore spawning a booster vehicle, confirm your booster role and ask the host which models are available for this session. A vehicle purchased in Roblox can still have a server-side restriction.\n\n**Use the approved setup**\nKeep the model, livery, and equipment consistent with the approval. Department markings and emergency equipment require separate department authorization.\n\n**Drive for the scene**\nUse roads, speeds, and parking appropriate to the scenario. Give emergency scenes room and roleplay collisions or damage just as you would in any other vehicle.\n\n**When access changes**\nIf your booster role disappears or a host updates the list, switch vehicles at a safe stopping point. For an access check, send General Support your Roblox username and the vehicle name.",
    "Graphical Guidelines": "**Department identity**\nUse the current department-approved liveries, uniform templates, and unit identifiers while on duty. Keep rank markings consistent with the role you are authorized to play.\n\n**Legibility**\nCheck text and unit numbers at ordinary in-game viewing distance. Use enough contrast for other players to identify the vehicle or uniform during a moving scene.\n\n**Custom designs**\nBefore using a custom design in an official role, send the host or department lead a preview showing the front, sides, and back. Include the vehicle model or uniform type.\n\n**Respect creators**\nUse artwork you own or have permission to use. Avoid impersonating another unit, copying private designs, or displaying offensive material. If staff request a correction, use the approved default until the revision is cleared.",
}
NOTIFICATIONS = ("Session", "Event", "Staff", "Giveaway", "News")
SUPPORT_TYPES = {"general": "General Support", "high": "High Rank Support"}
role_lock = asyncio.Lock()


def gallery(filename, description):
    return ui.MediaGallery(discord.MediaGalleryItem(f"attachment://{filename}", description=description))


class DeskMenu(ui.Select):
    def __init__(self, intake):
        super().__init__(custom_id="rc:desk:v2", placeholder="Choose a support type", options=[
            discord.SelectOption(label="General Support", value="general", emoji="✉️", description="Questions, reports, and regular assistance."),
            discord.SelectOption(label="High Rank Support", value="high", emoji="📋", description="Sensitive issues needing management attention."),
        ])
        self.intake = intake

    async def callback(self, interaction):
        await interaction.response.send_modal(RequestForm(self.values[0], self.intake))


class RequestForm(ui.Modal):
    subject = ui.TextInput(label="What do you need help with?", max_length=100)
    details = ui.TextInput(label="Details", style=discord.TextStyle.paragraph, max_length=1800,
                           placeholder="Describe what happened. Include usernames or message links if relevant.")

    def __init__(self, route, intake):
        super().__init__(title=SUPPORT_TYPES[route], timeout=600)
        self.route, self.intake = route, intake

    async def on_submit(self, interaction):
        await self.intake(interaction, self.route, self.subject.value, self.details.value)


class RulesMenu(ui.Select):
    def __init__(self):
        super().__init__(custom_id="rc:rules:v2", placeholder="View Rules & Regulations",
                         options=[discord.SelectOption(label=title) for title in RULES])

    async def callback(self, interaction):
        title = self.values[0]
        embed = discord.Embed(title=title, description=RULES[title], color=0x1066EC)
        embed.set_footer(text=BRAND)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class RoleMenu(ui.Select):
    def __init__(self):
        super().__init__(custom_id="rc:roles:v2", placeholder="Select Your Roles", options=[
            discord.SelectOption(label=f"{name} Notification", value=name, description=f"Toggle {name.lower()} notifications.")
            for name in NOTIFICATIONS])

    async def callback(self, interaction):
        name = self.values[0]
        ident = os.getenv(f"{name.upper()}_NOTIFICATION_ROLE_ID", "")
        guild = interaction.guild
        await interaction.response.defer(ephemeral=True, thinking=True)
        async with role_lock:
            if ident:
                role = guild.get_role(int(ident)) if ident.isdecimal() else None
            else:
                matches = [r for r in await guild.fetch_roles() if r.name == f"{name} Notification"]
                if len(matches) > 1:
                    await interaction.followup.send("Staff must select the intended role ID in the bot settings.", ephemeral=True)
                    return
                role = matches[0] if matches else await guild.create_role(name=f"{name} Notification", permissions=discord.Permissions.none(), reason="River City Roleplay notification role")
            reserved = {os.getenv("SUPPORT_ROLE_ID"), os.getenv("HIGH_RANK_ROLE_ID") or "1572082345949790311"}
            if (not role or str(role.id) in reserved or role.permissions.value or not role.is_assignable()
                    or any(c.overwrites_for(role).pair()[0].value for c in guild.channels)):
                await interaction.followup.send("This role needs staff setup. Notification roles must be assignable and grant no permissions.", ephemeral=True)
                return
            member = await guild.fetch_member(interaction.user.id)
            if member.get_role(role.id):
                await member.remove_roles(role, reason="Dashboard notification opt-out")
                text = "Removed"
            else:
                await member.add_roles(role, reason="Dashboard notification opt-in")
                text = "Added"
        await interaction.followup.send(f"{text} **{role.name}**.", ephemeral=True)


class Panel(ui.LayoutView):
    def __init__(self, kind, guild_id, channel_id, desk_id, intake):
        super().__init__(timeout=None)
        self.guild_id, self.channel_id = guild_id, channel_id
        parts = [gallery(f"{kind}.png", f"{BRAND} {kind}"), ui.Separator()]
        if kind == "assistance":
            parts.extend([
                ui.TextDisplay("**✉️ River City Roleplay Assistance**\nNeed help in the city? Choose a support type below to open a private ticket.\n\n**General Support** handles server questions, player reports, and help with sessions.\n**High Rank Support** goes directly to management for staff concerns or sensitive issues.\n\nTell us what happened and who was involved so the right team can help."),
                ui.ActionRow(DeskMenu(intake)), ui.Separator(),
                ui.TextDisplay("-# Ticket content may be reviewed by the assigned team and server administrators for moderation, safety, and support quality."),
            ])
        else:
            parts.extend([
                ui.TextDisplay("Welcome to **River City Roleplay**! Before your first scene, review the city regulations and choose which updates you want to receive."),
                ui.Separator(), ui.TextDisplay("**Regulations**\nReview community expectations and in-game guidelines before joining a session."),
                ui.ActionRow(RulesMenu()), ui.Separator(),
                ui.TextDisplay("**Self Roles**\nSelect a notification role to add it. Select it again to remove it."),
                ui.ActionRow(RoleMenu()),
            ])
            links = ui.ActionRow(ui.Button(label="Support Desk", url=f"https://discord.com/channels/{guild_id}/{desk_id}"))
            for label, key in (("Guidebook", "GUIDEBOOK_URL"), ("Staff Application", "STAFF_APPLICATION_URL"), ("Ban Appeal", "BAN_APPEAL_URL")):
                url = os.getenv(key, "").strip()
                if url.startswith("https://"):
                    links.add_item(ui.Button(label=label, url=url))
            parts.append(links)
        parts.extend([ui.Separator(), gallery("footer.png", "River City Roleplay — Experience Real Roleplay")])
        self.add_item(ui.Container(*parts))

    async def interaction_check(self, interaction):
        return interaction.guild_id == self.guild_id and interaction.channel_id == self.channel_id

    async def on_error(self, interaction, error, item):
        import logging
        logging.getLogger(__name__).exception("Panel interaction failed", exc_info=error)
        if isinstance(error, discord.HTTPException) and error.code in {10062, 40060}:
            return
        if not interaction.response.is_done():
            await interaction.response.send_message("This action failed. Ask staff to check the bot permissions.", ephemeral=True)
        else:
            await interaction.followup.send("This action failed. Ask staff to check the bot permissions.", ephemeral=True)
