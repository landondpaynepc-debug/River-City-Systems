import logging

import discord
from discord.ext import commands

from verification import GUILD

ROOM = 1573452372103929856
log = logging.getLogger("rivercity.waiting")


class WaitingRoom(commands.Cog):
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        room = after.channel
        if member.bot or member.guild.id != GUILD or room is None or room.id != ROOM:
            return
        if before.channel and before.channel.id == ROOM:
            return

        panel = discord.ui.LayoutView(timeout=None)
        panel.add_item(discord.ui.Container(
            discord.ui.TextDisplay(
                "Hello and thanks for contacting our Faculty Team. "
                "Please wait momentarily while we review a few things."
            ),
            discord.ui.TextDisplay("-# River City Roleplay | Faculty Team"),
            accent_colour=discord.Colour(0x246BCE),
        ))
        try:
            await room.send(view=panel, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Could not post Faculty Team greeting in waiting room %s", ROOM)
