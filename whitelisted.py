"""Whitelisted department directory for River City Roleplay."""
import discord
from discord import ui

ASSET_URL = "https://raw.githubusercontent.com/landondpaynepc-debug/River-City-Systems/3b5cd8dc8bfbffa41903a0601de2ac33fd372806/assets"


def panel_image(filename, description):
    item = discord.MediaGalleryItem(f"{ASSET_URL}/{filename}", description=description)
    return ui.MediaGallery(item)


DEPARTMENTS = {
    "law": ("River City Law Enforcement", "🚓", "https://discord.gg/2uyNuaQtKW"),
    "fire": ("River City Fire Department", "🚒", "https://discord.gg/eHwvwrFKsh"),
    "dot": ("River City Department of Transportation", "🚧", "https://discord.gg/TyUqZE5VCa"),
}


class DepartmentMenu(ui.Select):
    def __init__(self):
        super().__init__(
            custom_id="rivercity:whitelisted:department",
            placeholder="Select a department",
            options=[
                discord.SelectOption(label=name, value=key, emoji=emoji)
                for key, (name, emoji, _) in DEPARTMENTS.items()
            ],
        )

    async def callback(self, interaction: discord.Interaction):
        name, _, url = DEPARTMENTS[self.values[0]]
        view = ui.LayoutView()
        view.add_item(ui.Container(
            ui.TextDisplay(f"## {name}"),
            ui.ActionRow(ui.Button(label="Join department Discord", url=url)),
        ))
        await interaction.response.send_message(view=view, ephemeral=True)


class DepartmentPanel(ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ui.Container(
            panel_image("whitelisted.webp", "River City Roleplay — Whitelisted Departments"),
            ui.TextDisplay("## River City Departments\n> Select a whitelisted department below to get its Discord invite."),
            ui.ActionRow(DepartmentMenu()),
            ui.Separator(),
            panel_image("footer.png", "River City Roleplay"),
            accent_colour=0x176BEA,
        ))
