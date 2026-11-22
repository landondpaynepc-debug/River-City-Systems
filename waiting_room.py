import asyncio
import hashlib
import io
import logging
import secrets

import discord
import imageio_ffmpeg
from gtts import gTTS
from discord.ext import commands
from discord.gateway import DiscordVoiceWebSocket
from discord.voice_state import ConnectionFlowState, VoiceConnectionState

from verification import GUILD

ROOM = 1573452372103929856
log = logging.getLogger("rivercity.waiting")


class WaitingRoomSocket(DiscordVoiceWebSocket):
    # discord.py drops binary messages received before Session Description.
    pending_sender = None

    async def received_binary_message(self, msg):
        opcode = msg[2]
        log.info("Waiting-room voice binary opcode %s", opcode)
        if opcode == self.MLS_EXTERNAL_SENDER and self._connection.dave_session is None:
            self.pending_sender = msg[3:]
        await super().received_binary_message(msg)

    async def received_message(self, msg):
        if msg["op"] != self.HEARTBEAT_ACK:
            log.info("Waiting-room voice opcode %s", msg["op"])
        await super().received_message(msg)
        session = self._connection.dave_session
        if session is not None and self.pending_sender is not None:
            session.set_external_sender(self.pending_sender)
            self.pending_sender = None


class WaitingRoomConnection(VoiceConnectionState):
    async def _connect_websocket(self, resume):
        ws = await WaitingRoomSocket.from_connection_state(
            self, resume=resume, hook=self.hook, seq_ack=getattr(self.ws, "seq_ack", -1)
        )
        self.state = ConnectionFlowState.websocket_connected
        return ws


class WaitingRoomVoice(discord.VoiceClient):
    def create_connection_state(self):
        return WaitingRoomConnection(self)


def spoken_welcome(display_name):
    message = (
        f"Welcome to River City Roleplay Staff Waiting Room {display_name}! "
        "Please wait as our staff is reviewing somethings."
    )
    audio = io.BytesIO()
    gTTS(message, lang="en", timeout=(2, 5)).write_to_fp(audio)
    return audio.getvalue()


async def play_source(vc, source):
    loop = asyncio.get_running_loop()
    done = loop.create_future()

    def finish(error):
        if not done.done():
            done.set_result(error)

    try:
        vc.play(source, after=lambda error: loop.call_soon_threadsafe(finish, error))
    except BaseException:
        source.cleanup()
        raise
    error = await asyncio.wait_for(done, timeout=30)
    if error:
        raise error


class WaitingRoom(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()

    async def play(self, room, member):
        async with self.lock:
            if not member.voice or member.voice.channel != room:
                return
            perms = room.permissions_for(room.guild.me)
            if not (perms.connect and perms.speak):
                raise PermissionError("Connect and Speak are required in the waiting room")
            vc = room.guild.voice_client
            try:
                if vc and not vc.is_connected():
                    await vc.disconnect(force=True)
                    vc = None
                if vc is None:
                    vc = await room.connect(cls=WaitingRoomVoice, timeout=30, reconnect=True)
                elif vc.channel != room:
                    await vc.move_to(room)
                # Let the joining listener and the encrypted media session become ready.
                for _ in range(150):
                    state = vc._connection
                    if vc.is_connected() and (not state.dave_protocol_version or state.can_encrypt):
                        break
                    await asyncio.sleep(.2)
                else:
                    raise TimeoutError("Discord media negotiation timed out")
                if not member.voice or member.voice.channel != room:
                    return
                me = room.guild.me.voice
                if me and (me.mute or me.suppress):
                    raise PermissionError("The bot is muted or suppressed")
                await asyncio.sleep(.5)
                audio = await asyncio.wait_for(
                    asyncio.to_thread(spoken_welcome, member.display_name), timeout=12
                )
                if not member.voice or member.voice.channel != room:
                    return
                source = discord.FFmpegOpusAudio(
                    io.BytesIO(audio), pipe=True, executable=imageio_ffmpeg.get_ffmpeg_exe()
                )
                await play_source(vc, source)
                log.info("Waiting-room personalized greeting finished")
            finally:
                if vc:
                    await vc.disconnect(force=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        room = after.channel
        if member.bot or member.guild.id != GUILD or room is None or room.id != ROOM:
            return
        if before.channel and before.channel.id == ROOM:
            return

        # Duplicate gateway listeners can overlap during a Render deployment.
        # Only the process whose marker Discord accepted should open a voice session.
        receipt_room = await self.bot.receipt_channel(member.guild)
        marker = secrets.token_hex(12)
        nonce = hashlib.sha256(f"wait:{member.id}:{after.session_id}:{before.channel and before.channel.id}".encode()).hexdigest()[:24]
        try:
            receipt = await receipt_room.send(marker, nonce=nonce, silent=True, delete_after=60)
        except discord.NotFound as error:
            if error.code != 10008:
                raise
            # A quick rejoin can reuse a voice session whose previous receipt was deleted.
            window = int(discord.utils.utcnow().timestamp()) // 2
            retry_nonce = hashlib.sha256(f"{nonce}:{window}".encode()).hexdigest()[:24]
            receipt = await receipt_room.send(marker, nonce=retry_nonce, silent=True, delete_after=60)
        if receipt.content != marker:
            return
        try:
            await self.play(room, member)
        except Exception:
            log.exception("Waiting-room greeting failed for channel %s", ROOM)
        finally:
            try:
                await receipt.delete()
            except discord.HTTPException:
                pass
