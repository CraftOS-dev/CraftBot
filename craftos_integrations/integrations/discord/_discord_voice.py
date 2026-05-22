# -*- coding: utf-8 -*-
"""Discord voice helpers - underscore-prefixed so the autoloader skips it.

Loaded lazily by discord.py only when a voice method is invoked.
Requires extra deps (discord.py[voice], PyNaCl, FFmpeg, openai).

API-key access goes through ConfigStore.extras["openai_api_key"]
(set via configure(extras={"openai_api_key": "..."})).
"""

from __future__ import annotations

import asyncio
import io
import os
import wave
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from ...config import ConfigStore

try:
    import discord
    from discord.ext import commands

    DISCORD_PY_AVAILABLE = True
except ImportError:
    DISCORD_PY_AVAILABLE = False

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False


def _get_openai_audio_api_key() -> str:
    return ConfigStore.extras.get("openai_api_key", "") or os.environ.get(
        "OPENAI_API_KEY", ""
    )


@dataclass
class VoiceSession:
    guild_id: str
    channel_id: str
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_recording: bool = False
    is_speaking: bool = False
    audio_buffer: Dict[int, List[bytes]] = field(default_factory=dict)
    transcript_callback: Optional[Callable] = None
    last_transcripts: Dict[int, str] = field(default_factory=dict)


class AudioRecordingSink:
    def __init__(
        self, session: VoiceSession, on_audio_chunk: Optional[Callable] = None
    ):
        self.session = session
        self.on_audio_chunk = on_audio_chunk
        self.audio_data: Dict[int, io.BytesIO] = {}

    def write(self, data: bytes, user_id: int):
        if user_id not in self.audio_data:
            self.audio_data[user_id] = io.BytesIO()
        self.audio_data[user_id].write(data)
        if user_id not in self.session.audio_buffer:
            self.session.audio_buffer[user_id] = []
        self.session.audio_buffer[user_id].append(data)
        if self.on_audio_chunk:
            self.on_audio_chunk(user_id, data)

    def cleanup(self):
        for buffer in self.audio_data.values():
            buffer.close()
        self.audio_data.clear()


class DiscordVoiceManager:
    def __init__(self, bot_token: str):
        if not DISCORD_PY_AVAILABLE:
            raise ImportError(
                "discord.py is required for voice features. Install with: pip install discord.py[voice]"
            )
        self.bot_token = bot_token
        self.bot: Optional[Any] = None
        self.voice_sessions: Dict[str, VoiceSession] = {}
        self._running = False

    # ------------------------------------------------------------------
    # Internal: resolve a guild (and optionally require an active voice
    # client) before doing real work. Returns (guild, error_dict).
    # ------------------------------------------------------------------
    def _get_guild_or_error(self, guild_id: str, *, require_voice: bool = False):
        if not self.bot:
            return None, {"error": "Bot not running. Call start() first."}
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return None, {"error": f"Guild {guild_id} not found"}
        if require_voice and not guild.voice_client:
            return None, {"error": "Not connected to voice in this guild"}
        return guild, None

    async def start(self) -> Dict[str, Any]:
        try:
            intents = discord.Intents.default()
            intents.message_content = True
            intents.voice_states = True
            intents.guilds = True
            self.bot = commands.Bot(command_prefix="!", intents=intents)

            @self.bot.event
            async def on_ready():
                self._running = True

            asyncio.create_task(self.bot.start(self.bot_token))
            for _ in range(30):
                if self._running:
                    return {
                        "ok": True,
                        "result": {
                            "status": "connected",
                            "bot_user": str(self.bot.user),
                        },
                    }
                await asyncio.sleep(1)
            return {"error": "Bot failed to connect within timeout"}
        except Exception as e:
            return {"error": str(e)}

    async def stop(self) -> Dict[str, Any]:
        try:
            if self.bot:
                for guild_id in list(self.voice_sessions.keys()):
                    await self.leave_voice(guild_id)
                await self.bot.close()
                self._running = False
                return {"ok": True, "result": {"status": "disconnected"}}
            return {"ok": True, "result": {"status": "not_running"}}
        except Exception as e:
            return {"error": str(e)}

    async def join_voice(
        self,
        guild_id: str,
        channel_id: str,
        self_deaf: bool = False,
        self_mute: bool = False,
    ) -> Dict[str, Any]:
        try:
            if not self._running:
                return {"error": "Bot not running. Call start() first."}
            guild, err = self._get_guild_or_error(guild_id)
            if err:
                return err
            channel = guild.get_channel(int(channel_id))
            if not channel:
                return {"error": f"Channel {channel_id} not found"}
            if not isinstance(channel, discord.VoiceChannel):
                return {"error": "Channel is not a voice channel"}
            if guild_id in self.voice_sessions:
                await self.leave_voice(guild_id)
            await channel.connect(self_deaf=self_deaf, self_mute=self_mute)
            self.voice_sessions[guild_id] = VoiceSession(
                guild_id=guild_id, channel_id=channel_id
            )
            return {
                "ok": True,
                "result": {
                    "status": "connected",
                    "guild_id": guild_id,
                    "channel_id": channel_id,
                    "channel_name": channel.name,
                },
            }
        except Exception as e:
            return {"error": str(e)}

    async def leave_voice(self, guild_id: str) -> Dict[str, Any]:
        try:
            guild, err = self._get_guild_or_error(guild_id)
            if err:
                return err
            if guild.voice_client:
                await guild.voice_client.disconnect()
            if guild_id in self.voice_sessions:
                del self.voice_sessions[guild_id]
            return {
                "ok": True,
                "result": {"status": "disconnected", "guild_id": guild_id},
            }
        except Exception as e:
            return {"error": str(e)}

    async def speak_text(
        self,
        guild_id: str,
        text: str,
        tts_provider: str = "openai",
        voice: str = "alloy",
    ) -> Dict[str, Any]:
        try:
            guild, err = self._get_guild_or_error(guild_id, require_voice=True)
            if err:
                return err
            voice_client = guild.voice_client
            audio_file = await self._generate_tts(text, tts_provider, voice)
            if not audio_file:
                return {"error": "Failed to generate TTS audio"}
            voice_client.play(discord.FFmpegPCMAudio(audio_file))
            while voice_client.is_playing():
                await asyncio.sleep(0.1)
            return {"ok": True, "result": {"status": "spoken", "text": text}}
        except Exception as e:
            return {"error": str(e)}

    async def play_audio(self, guild_id: str, audio_path: str) -> Dict[str, Any]:
        try:
            guild, err = self._get_guild_or_error(guild_id, require_voice=True)
            if err:
                return err
            guild.voice_client.play(discord.FFmpegPCMAudio(audio_path))
            return {
                "ok": True,
                "result": {"status": "playing", "audio_path": audio_path},
            }
        except Exception as e:
            return {"error": str(e)}

    async def stop_audio(self, guild_id: str) -> Dict[str, Any]:
        try:
            guild, err = self._get_guild_or_error(guild_id, require_voice=True)
            if err:
                return err
            guild.voice_client.stop()
            return {"ok": True, "result": {"status": "stopped"}}
        except Exception as e:
            return {"error": str(e)}

    def get_voice_status(self, guild_id: str) -> Dict[str, Any]:
        try:
            session = self.voice_sessions.get(guild_id)
            if not session:
                return {"ok": True, "result": {"connected": False}}
            guild = self.bot.get_guild(int(guild_id)) if self.bot else None
            is_connected = bool(
                guild and guild.voice_client and guild.voice_client.is_connected()
            )
            return {
                "ok": True,
                "result": {
                    "connected": is_connected,
                    "guild_id": guild_id,
                    "channel_id": session.channel_id,
                    "is_recording": session.is_recording,
                    "is_speaking": session.is_speaking,
                    "connected_at": session.connected_at.isoformat(),
                },
            }
        except Exception as e:
            return {"error": str(e)}

    async def start_listening(
        self,
        guild_id: str,
        on_transcript: Optional[Callable[[int, str], None]] = None,
        auto_transcribe: bool = True,
        transcribe_interval: float = 3.0,
    ) -> Dict[str, Any]:
        try:
            session = self.voice_sessions.get(guild_id)
            if not session:
                return {"error": "Not connected to voice in this guild"}
            _, err = self._get_guild_or_error(guild_id, require_voice=True)
            if err:
                return err
            session.is_recording = True
            session.transcript_callback = on_transcript
            if auto_transcribe:
                asyncio.create_task(
                    self._auto_transcribe_loop(guild_id, transcribe_interval)
                )
            return {
                "ok": True,
                "result": {
                    "status": "listening",
                    "guild_id": guild_id,
                    "auto_transcribe": auto_transcribe,
                },
            }
        except Exception as e:
            return {"error": str(e)}

    async def stop_listening(self, guild_id: str) -> Dict[str, Any]:
        try:
            session = self.voice_sessions.get(guild_id)
            if not session:
                return {"error": "No active session for this guild"}
            session.is_recording = False
            final_transcripts = dict(session.last_transcripts)
            session.audio_buffer.clear()
            return {
                "ok": True,
                "result": {"status": "stopped", "transcripts": final_transcripts},
            }
        except Exception as e:
            return {"error": str(e)}

    async def _auto_transcribe_loop(self, guild_id: str, interval: float):
        while True:
            session = self.voice_sessions.get(guild_id)
            if not session or not session.is_recording:
                break
            for user_id, chunks in list(session.audio_buffer.items()):
                if chunks and len(chunks) > 10:
                    audio_data = b"".join(chunks)
                    session.audio_buffer[user_id] = []
                    transcript = await self._transcribe_audio(audio_data)
                    if transcript:
                        session.last_transcripts[user_id] = transcript
                        if session.transcript_callback:
                            try:
                                session.transcript_callback(user_id, transcript)
                            except Exception:
                                pass
            await asyncio.sleep(interval)

    async def _transcribe_audio(self, audio_data: bytes) -> Optional[str]:
        api_key = _get_openai_audio_api_key()
        if not OPENAI_AVAILABLE or not api_key:
            return None
        try:
            wav_path = self._pcm_to_wav(audio_data)
            if not wav_path:
                return None
            client = OpenAI(api_key=api_key)
            with open(wav_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="text",
                )
            os.unlink(wav_path)
            return transcript.strip() if transcript else None
        except Exception:
            return None

    def _pcm_to_wav(
        self, pcm_data: bytes, sample_rate: int = 48000, channels: int = 2
    ) -> Optional[str]:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
                with wave.open(f.name, "wb") as wav_file:
                    wav_file.setnchannels(channels)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(pcm_data)
                return f.name
        except Exception:
            return None

    async def _generate_tts(
        self, text: str, provider: str = "openai", voice: str = "alloy"
    ) -> Optional[str]:
        try:
            api_key = _get_openai_audio_api_key()
            if provider == "openai" and OPENAI_AVAILABLE and api_key:
                client = OpenAI(api_key=api_key)
                response = client.audio.speech.create(
                    model="tts-1", voice=voice, input=text
                )
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    response.stream_to_file(f.name)
                    return f.name
            elif provider == "gtts" or not OPENAI_AVAILABLE:
                from gtts import gTTS

                tts = gTTS(text=text, lang="en")
                with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
                    tts.save(f.name)
                    return f.name
            return None
        except Exception:
            return None

    async def transcribe_and_respond(
        self,
        guild_id: str,
        response_generator: Callable[[str], str],
        voice: str = "alloy",
    ) -> Dict[str, Any]:
        try:
            session = self.voice_sessions.get(guild_id)
            if not session:
                return {"error": "Not connected to voice in this guild"}

            async def on_transcript(user_id: int, transcript: str):
                if not transcript or len(transcript.strip()) < 2:
                    return
                response_text = response_generator(transcript)
                if response_text:
                    await self.speak_text(
                        guild_id, response_text, tts_provider="openai", voice=voice
                    )

            return await self.start_listening(
                guild_id=guild_id,
                on_transcript=lambda uid, txt: asyncio.create_task(
                    on_transcript(uid, txt)
                ),
                auto_transcribe=True,
            )
        except Exception as e:
            return {"error": str(e)}
