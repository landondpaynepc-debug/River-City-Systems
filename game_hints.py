import asyncio
import logging
import os
import secrets
from datetime import time, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

HINTS = (
    "New in town? A taxi shift, roadside breakdown, or delivery run is an easy way to start a scene.",
    "Calling 911? Give the nearest postal or landmark first, then explain what happened and who needs help.",
    "Getting pulled over? Signal, find a safe spot, and give the officer room to approach.",
    "Crashed your car? Play out the damage. A fender bender and a highway rollover should feel different.",
    "Give Fire & Rescue something to work with. Tell the medic where your character feels pain and let them respond.",
    "See DOT cones ahead? Slow down early and follow the marked route around the work zone.",
    "Witnessed a hit-and-run? The vehicle’s color and last known direction can give police a lead.",
    "A minor collision can make a great scene. Check on the other driver, exchange details, and call for a tow if needed.",
    "Keep Discord callouts out of character. Your character needs an in-game reason to know where someone is.",
    "Give the other player a turn. Describe what your character attempts and leave room for their response.",
    "Value your character’s life. If someone has you at gunpoint and there’s no realistic escape, play out the fear.",
    "Think someone broke a rule? Finish the scene when possible, save a clip, and report it to staff. Pause if staff asks.",
    "A good scene can start at a red light. Ask for directions, compliment someone’s car, or invite them to a local meetup.",
)
TIMES = [time(hour, minute, tzinfo=timezone.utc) for hour in range(24) for minute in range(0, 60, 10)]
log = logging.getLogger("rivercity.hints")


class GameHints(commands.Cog):
    def __init__(self, bot, guild_id):
        self.bot = bot
        self.guild_id = guild_id
        self.broadcast.start()

    def cog_unload(self):
        self.broadcast.cancel()

    @tasks.loop(time=TIMES)
    async def broadcast(self):
        guild = self.bot.get_guild(self.guild_id)
        key = os.getenv("ERLC_SERVER_KEY")
        if not guild or not key or not self.bot.is_ready():
            return
        slot = int(discord.utils.utcnow().timestamp()) // 600
        command = ":h [River City Hint] | " + HINTS[slot % len(HINTS)]
        try:
            async with aiohttp.ClientSession(headers={"Server-Key": key}, timeout=aiohttp.ClientTimeout(total=12)) as client:
                url = "https://api.erlc.gg/v2/server"
                async with client.get(url, allow_redirects=False) as response:
                    response.raise_for_status()
                    server = await response.json()
                if not server.get("CurrentPlayers", 0):
                    return
                room = await self.bot.receipt_channel(guild)
                marker = secrets.token_hex(12)
                receipt = await room.send(marker, nonce=f"hint-{slot}", silent=True, delete_after=180)
                if receipt.content != marker:
                    return
                async with client.post(url + "/command", json={"command": command}, allow_redirects=False) as response:
                    if not 200 <= response.status < 300:
                        log.warning("Hint rejected by ER:LC (HTTP %s)", response.status)
                        return
                log.info("ER:LC accepted hint %s", slot % len(HINTS) + 1)
        except (aiohttp.ClientError, asyncio.TimeoutError, discord.HTTPException, ValueError, AttributeError):
            log.exception("Could not broadcast scheduled ER:LC hint")

    @broadcast.before_loop
    async def ready(self):
        await self.bot.wait_until_ready()
