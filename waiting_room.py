import asyncio
import logging
from functools import lru_cache
from pathlib import Path

import discord
from discord.ext import commands, tasks

from verification import GUILD

ROOM = 1573452372103929856
log = logging.getLogger("rivercity.waiting")


@lru_cache(maxsize=1)
def recording_packets():
    import imageio_ffmpeg

    path = Path(__file__).with_name("assets") / "waiting-room.m4a"
    source = discord.FFmpegOpusAudio(str(path), executable=imageio_ffmpeg.get_ffmpeg_exe())
    try:
        packets = tuple(p for p in iter(source.read, b"") if not p.startswith((b"OpusHead", b"OpusTags")))
    finally:
        source.cleanup()
    if not packets:
        raise RuntimeError("The waiting-room recording could not be decoded")
    return packets


class GreetingAudio(discord.AudioSource):
    def __init__(self, packets):
        self.packets = iter(packets)

    def read(self):
        return next(self.packets, b"")

    def is_opus(self):
        return True


class WaitingRoom(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.connect_lock = asyncio.Lock()
        self.speech_lock = asyncio.Lock()
        self.stay.start()

    def cog_unload(self):
        self.stay.cancel()

    async def connection(self, room):
        async with self.connect_lock:
            vc = room.guild.voice_client
            if vc and vc.is_connected():
                if vc.channel != room:
                    await vc.move_to(room)
                return vc
            if vc:
                await vc.disconnect(force=True)
            return await room.connect(timeout=20, reconnect=True, self_deaf=True)

    @tasks.loop(minutes=1)
    async def stay(self):
        room = self.bot.get_channel(ROOM)
        if isinstance(room, discord.VoiceChannel):
            try:
                await self.connection(room)
            except (discord.DiscordException, OSError, RuntimeError, asyncio.TimeoutError):
                log.exception("Could not connect to staff waiting room")

    @stay.before_loop
    async def ready(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        room = after.channel
        if member.bot or member.guild.id != GUILD or before.channel == room or not room or room.id != ROOM:
            return
        greeting = f"Hello {member.display_name}! Thanks for contacting River City Roleplay Staff. Please wait while are team is reviewing somethings."
        async with self.speech_lock:
            if not member.voice or member.voice.channel != room:
                return
            try:
                me = room.guild.me
                permissions = room.permissions_for(me)
                if not permissions.connect or not permissions.speak:
                    raise RuntimeError("The bot needs Connect and Speak in the waiting room")
                vc = await self.connection(room)
                if me.voice and (me.voice.mute or me.voice.suppress):
                    raise RuntimeError("The bot is server-muted or suppressed in the waiting room")
                source = GreetingAudio(await asyncio.to_thread(recording_packets))
                await asyncio.sleep(1)
                if not member.voice or member.voice.channel != room:
                    return
                loop = asyncio.get_running_loop()
                done = loop.create_future()

                def finish(error):
                    if not done.done():
                        if error:
                            done.set_exception(error)
                        else:
                            done.set_result(None)

                vc.play(source, after=lambda error: loop.call_soon_threadsafe(finish, error))
                try:
                    await asyncio.wait_for(done, timeout=45)
                finally:
                    if vc.is_playing():
                        vc.stop()
                log.info("Waiting room greeting playback completed in %s", ROOM)
            except Exception:
                log.exception("Waiting room speech failed")
                await room.send(greeting, allowed_mentions=discord.AllowedMentions.none())
