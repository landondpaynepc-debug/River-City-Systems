import asyncio
import ctypes
import logging
import os
import tempfile
import wave
from pathlib import Path

import discord
from discord.ext import commands, tasks

from verification import GUILD

ROOM = 1573452372103929856
log = logging.getLogger("rivercity.waiting")


def speak_to_file(text, filename):
    import espeakng_loader
    lib = ctypes.CDLL(str(espeakng_loader.get_library_path()))
    data = Path(espeakng_loader.get_data_path())
    parent = data.parent if data.name == "espeak-ng-data" else data
    rate = lib.espeak_Initialize(2, 0, os.fsencode(parent), 0)
    if rate <= 0:
        raise RuntimeError("Speech initialization failed")
    samples = []
    callback_type = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p)

    @callback_type
    def capture(pointer, count, events):
        if pointer and count:
            samples.append(ctypes.string_at(pointer, count * 2))
        return 0

    try:
        lib.espeak_SetSynthCallback(capture)
        lib.espeak_SetVoiceByName(b"en-us")
        payload = text.encode("utf-8") + b"\x00"
        result = lib.espeak_Synth(payload, len(payload), 0, 1, 0, 1, None, None)
        if result or not samples:
            raise RuntimeError("Speech synthesis failed")
        with wave.open(str(filename), "wb") as output:
            output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
            output.writeframes(b"".join(samples))
    finally:
        lib.espeak_Terminate()


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
                import imageio_ffmpeg
                vc = await self.connection(room)
                with tempfile.TemporaryDirectory() as folder:
                    path = Path(folder) / "greeting.wav"
                    await asyncio.to_thread(speak_to_file, greeting, path)
                    source = discord.FFmpegOpusAudio(str(path), executable=imageio_ffmpeg.get_ffmpeg_exe())
                    loop = asyncio.get_running_loop()
                    done = loop.create_future()

                    def finish(error):
                        if not done.done():
                            if error:
                                done.set_exception(error)
                            else:
                                done.set_result(None)

                    try:
                        vc.play(source, after=lambda error: loop.call_soon_threadsafe(finish, error))
                        await asyncio.wait_for(done, timeout=45)
                    finally:
                        if vc.is_playing():
                            vc.stop()
                        source.cleanup()
            except Exception:
                log.exception("Waiting room speech failed")
                await room.send(greeting, allowed_mentions=discord.AllowedMentions.none())
