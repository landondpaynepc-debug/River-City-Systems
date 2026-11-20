import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands, tasks

from verification import GUILD

ROOM = 1573452372103929856
log = logging.getLogger("rivercity.waiting")


RECORDING = Path(__file__).with_name("assets") / "waiting-room.m4a"


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
        try:
            await self.play_recording(member, room)
        except Exception as exc:
            log.exception("Staff waiting-room playback failed")
            await room.send(self.failure_message(exc), allowed_mentions=discord.AllowedMentions.none())

    @staticmethod
    def failure_message(exc):
        if isinstance(exc, PermissionError):
            return str(exc)
        if isinstance(exc, discord.opus.OpusNotLoaded):
            return "Voice playback failed because the host could not load the Opus audio encoder."
        return f"Waiting-room playback failed ({type(exc).__name__}). Staff can check the voice logs."

    @commands.command()
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def play(self, ctx):
        room = ctx.guild.get_channel(ROOM)
        if not room or not ctx.author.voice or ctx.author.voice.channel != room:
            return await ctx.send(f"Join <#{ROOM}> first to replay the recording.")
        try:
            played = await self.play_recording(ctx.author, room)
        except Exception as exc:
            log.exception("Manual waiting-room playback failed")
            return await ctx.send(self.failure_message(exc))
        if played:
            await ctx.send("The recording finished playing.", delete_after=10)

    async def play_recording(self, member, room):
        import imageio_ffmpeg

        async with self.speech_lock:
            if not member.voice or member.voice.channel != room:
                return False
            me = room.guild.me
            permissions = room.permissions_for(me)
            if not permissions.connect or not permissions.speak:
                raise PermissionError("The bot needs Connect and Speak permissions in the staff waiting room.")
            voice_client = await self.connection(room)
            if me.voice and (me.voice.mute or me.voice.suppress):
                raise PermissionError("The bot is muted or suppressed in the staff waiting room.")
            # Discord can connect the gateway before the encrypted media session is ready.
            state = voice_client._connection
            for _ in range(100):
                if not state.dave_protocol_version or state.can_encrypt:
                    break
                await asyncio.sleep(0.1)
            else:
                raise RuntimeError("Discord voice encryption did not become ready")
            if not member.voice or member.voice.channel != room:
                return False

            loop = asyncio.get_running_loop()
            done = loop.create_future()

            def finish(error):
                if not done.done():
                    if error:
                        done.set_exception(error)
                    else:
                        done.set_result(None)

            source = discord.FFmpegPCMAudio(str(RECORDING), executable=imageio_ffmpeg.get_ffmpeg_exe())
            try:
                voice_client.play(source, after=lambda error: loop.call_soon_threadsafe(finish, error))
            except Exception:
                source.cleanup()
                raise
            try:
                await asyncio.wait_for(done, timeout=45)
            finally:
                if voice_client.is_playing():
                    voice_client.stop()
            log.info("Staff waiting-room recording finished in channel %s", room.id)
            return True
