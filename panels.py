from cards import layout
"""Discord dashboard and assistance panels for River City Roleplay."""
import asyncio
import os
from pathlib import Path

import discord
from discord import ui

BRAND = "River City Roleplay"
ASSETS = Path(__file__).with_name("assets")
RULES = {
    "Discord Regulations": """Welcome to **River City Roleplay (RCRP)**! These rules apply to everyone in our Discord, including staff and department members.

**1. Respect other members.** Treat people with respect in chat, voice calls, and tickets. Harassment, slurs, threats, and targeting someone because of who they are are prohibited.

**2. Keep content appropriate.** Keep your messages, uploads, profile, and server nickname appropriate for the community. Sexually explicit content, graphic violence, and shock media are prohibited.

**3. Use the right channels.** Follow channel topics and check pinned messages before posting. Use the support ticket system for reports, appeals, and questions that need staff attention.

**4. Avoid spam and disruptive pings.** Give others room to chat. Flooding channels, repeating the same request, and repeatedly tagging staff or departments are prohibited.

**5. Be considerate in voice chat.** Let others speak and keep your mic at a reasonable volume. Soundboard spam, mic blasting, and deliberately talking over session hosts disrupt everyone.

**6. Ask before advertising.** Get staff approval before promoting a Discord server, business, social account, or paid service. This includes unsolicited promotional DMs to RCRP members.

**7. Protect people’s privacy.** Keep personal information private. Sharing someone’s address, phone number, or private messages without permission is prohibited. If a private message is evidence for a report, send it to staff through a ticket.

**8. Keep roleplay fair.** Keep in-character disputes out of community chat. Using Discord to pass along information your character couldn’t know, such as a suspect’s location during a pursuit, counts as metagaming.

**9. Respect department access.** Use department channels and resources only as authorized. Impersonating staff, claiming a rank you haven’t earned, or sharing restricted material outside your department is prohibited.

**10. Handle moderation through tickets.** Follow staff directions during a session. If you disagree with a decision, open a ticket, explain what happened, and include any relevant evidence. Using alternate accounts to bypass a timeout or ban is prohibited.

All members must also follow Discord’s Terms of Service and Community Guidelines. Depending on the severity and history of a violation, staff may issue a warning, timeout, kick, or ban.""",
    "In-Game Regulations": """These rules apply to everyone in our **Emergency Response: Liberty County (ER:LC)** sessions, including civilians, law enforcement, Fire & Rescue, and DOT.

**1. Stay in character.** Play a believable character and respond to what happens around you. If someone breaks a rule, finish the scene when possible and report it afterward. Pause if staff directs you to.

**2. No random deathmatch (RDM) or vehicle deathmatch (VDM).** You need a valid in-character reason to use force. A minor traffic accident alone is no reason to shoot someone. Deliberately running people over to disrupt a scene is prohibited.

**3. Value your character’s life.** React to danger realistically. If someone already has you at gunpoint and you have no reasonable way to escape, comply. Give your character a believable reason before taking a serious risk.

**4. Drive realistically and roleplay crashes.** Traffic laws apply during normal driving. During a pursuit, consider your vehicle, the terrain, and any damage. After a major crash, stop and roleplay the impact and injuries. A vehicle that still moves in-game can still be disabled in the scene.

**5. No metagaming.** Use only information your character learned in the scene or through an authorized in-character channel. For example, hearing a suspect’s location in a Discord call doesn’t give your officer a reason to go there.

**6. No powergaming.** Give other players a fair chance to respond. For example, write `*reaches for the driver's door*` and let the driver react. You cannot decide another character’s injuries or force the outcome of a struggle.

**7. Follow the New Life Rule (NLR).** If your character dies and you respawn, your involvement in that incident ends. Stay away until the scene clears. You may not return for revenge or tell another player who killed you. If EMS treats you and your character survives, continue the same scene.

**8. No combat logging or resetting.** Stay through arrests, pursuits, medical treatment, and other active scenes. Leaving, resetting, or switching teams to avoid an outcome is prohibited. If you disconnect accidentally, let staff know and rejoin when possible.

**9. No cop baiting or scene interference.** Give your character a reason to get involved. Repeatedly ramming a patrol car to start a chase, driving through a road closure, or showing up at an unrelated scene just to cause chaos disrupts other players’ roleplay.

**10. Follow department procedures.** Use only the teams, uniforms, vehicles, and equipment you’re authorized to use. Law enforcement needs an in-character basis for stops and arrests. Fire & Rescue and DOT should coordinate with scene command before entering an active incident.

**11. Get approval for major scenes.** Ask session staff before starting a server-wide event, such as a mass-casualty incident or a citywide shutdown. Wait for approval so departments can coordinate and existing scenes can finish.

**12. Play fairly and follow staff directions.** Exploits, cheats, and abusing game mechanics for an advantage are prohibited. If staff pauses a scene, stop and listen. Bring disputes to a support ticket with the players’ usernames, the approximate time, and a clip if you have one.""",
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
        await interaction.message.edit(view=self.view)


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
        super().__init__(custom_id="rc:rules:v3", placeholder="View Rules & Regulations",
                         options=[discord.SelectOption(label=title) for title in RULES])

    async def callback(self, interaction):
        title = self.values[0]
        heading = {
            "Discord Regulations": "River City Roleplay | Discord Rules",
            "In-Game Regulations": "River City Roleplay | In-Game Rules",
        }.get(title, title)
        embed = discord.Embed(title=heading, description=RULES[title])
        embed.set_footer(text=BRAND)
        await interaction.response.send_message(view=layout(embed), ephemeral=True)
        await interaction.message.edit(view=self.view)


class RoleMenu(ui.Select):
    def __init__(self):
        super().__init__(custom_id="rc:roles:v2", placeholder="Select Your Roles", options=[
            discord.SelectOption(label=f"{name} Notification", value=name, description=f"Toggle {name.lower()} notifications.")
            for name in NOTIFICATIONS])

    async def callback(self, interaction):
        name = self.values[0]
        ident = os.getenv(f"{name.upper()}_NOTIFICATION_ROLE_ID", "")
        guild = interaction.guild
        await interaction.response.edit_message(view=self.view)
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
