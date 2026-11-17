"""Discord dashboard and assistance panels for River City Roleplay."""
import asyncio
import os
from pathlib import Path

import discord
from discord import ui

BRAND = "River City Roleplay"
ASSETS = Path(__file__).with_name("assets")
RULES = {
    "Discord Regulations": "Treat other members respectfully. Keep chat in its designated channel. Avoid spam, harassment, impersonation and sharing private information. Use the assistance desk to report a concern.",
    "In-Game Regulations": "Stay in character during scenes. Give other players time to respond, roleplay collisions and injuries, and keep out-of-character information out of your character’s decisions.",
    "Banned Vehicles & Items": "Check with the session host before using restricted vehicles, weapons or equipment. Ask General Support about a specific model or item.",
    "Booster Vehicles": "Confirm your booster access and the current vehicle list with staff before spawning a booster vehicle.",
    "Graphical Guidelines": "Use department-approved liveries and uniforms when acting in an official role. Ask staff to check custom graphics before using them in a session.",
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
        await interaction.response.send_message(f"**{BRAND} • {title}**\n{RULES[title]}", ephemeral=True)


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
        parts = [gallery(f"{kind}.jpg", f"{BRAND} {kind}"), ui.Separator()]
        if kind == "assistance":
            parts.extend([
                ui.TextDisplay("**✉️ River City Roleplay Support Desk**\nNeed help? Open a ticket and a staff member will review your request. Choose the team that best matches your issue."),
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
        if not interaction.response.is_done():
            await interaction.response.send_message("This action failed. Ask staff to check the bot permissions.", ephemeral=True)
        else:
            await interaction.followup.send("This action failed. Ask staff to check the bot permissions.", ephemeral=True)
