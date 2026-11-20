import asyncio
import ctypes
import logging
import os
import struct
import subprocess
import sys
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


class GreetingAudio(discord.AudioSource):
    def __init__(self, packets):
        self.packets = iter(packets)

    def read(self):
        return next(self.packets, b"")

    def is_opus(self):
        return True


def backup_audio():
    data = (Path(__file__).with_name("assets") / "waiting-room.dca").read_bytes()
    packets = []
    offset = 0
    while offset < len(data):
        size, = struct.unpack_from("<H", data, offset)
        offset += 2
        if not size or offset + size > len(data):
            raise ValueError("Invalid greeting packet")
        packets.append(data[offset:offset + size])
        offset += size
    return GreetingAudio(packets)


def prepare_audio(greeting):
    try:
        import imageio_ffmpeg
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "greeting.wav"
            # Keep native voice-engine stalls or crashes outside the gateway process.
            subprocess.run([sys.executable, __file__, str(path)], input=greeting.encode(),
                           check=True, timeout=8, stdout=subprocess.DEVNULL)
            with wave.open(str(path)) as audio:
                pcm = audio.readframes(audio.getnframes())
                if not any(pcm) or audio.getnframes() < audio.getframerate() // 2:
                    raise ValueError("Speech engine produced no audible greeting")
            source = discord.FFmpegOpusAudio(str(path), executable=imageio_ffmpeg.get_ffmpeg_exe())
            try:
                packets = [p for p in iter(source.read, b"") if not p.startswith((b"OpusHead", b"OpusTags"))]
            finally:
                source.cleanup()
            if len(packets) < 25:
                raise ValueError("Encoder produced no playable greeting")
            return GreetingAudio(packets)
    except Exception:
        log.exception("Personalized greeting unavailable. Playing bundled voice clip.")
        return backup_audio()


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
                source = await asyncio.to_thread(prepare_audio, greeting)
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


if __name__ == "__main__":
    speak_to_file(sys.stdin.buffer.read().decode(), sys.argv[1])
