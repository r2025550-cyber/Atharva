import asyncio
import os
from typing import Optional
from pytgcalls import PyTgCalls, idle
from pytgcalls.types import Update
from pytgcalls.types.input_stream import AudioPiped
from pytgcalls.types.stream import StreamAudioEnded
from pyrogram import Client
from loguru import logger
from .queue import MusicQueue

# Tuning
DEFAULT_VOLUME = 100  # percent
MAX_VOLUME = 200
MIN_VOLUME = 0

class Player:
    def __init__(self, user_client: Client):
        self.app = user_client
        self.call = PyTgCalls(self.app)
        self.queue = MusicQueue()
        self.volume: dict[int, int] = {}  # chat_id -> volume percent

    async def start(self):
        @self.call.on_stream_end()
        async def on_end(_, update: Update):
            chat_id = update.chat_id
            logger.info(f"Stream ended in chat {chat_id}, moving to next track")
            await self._play_next(chat_id)

        await self.call.start()
        logger.info("PyTgCalls connected")

    async def join(self, chat_id: int):
        # If already connected, do nothing
        try:
            await self.call.join_group_call(chat_id, AudioPiped("silence.mp3"))  # fake join then immediately skip
            await self.call.leave_group_call(chat_id)
        except Exception:
            pass

    async def leave(self, chat_id: int):
        try:
            await self.call.leave_group_call(chat_id)
        except Exception:
            pass

    async def enqueue_and_play(self, chat_id: int, stream_url: str, title: str, duration: int, requested_by: int) -> bool:
        self.queue.add(chat_id, (requested_by, stream_url, title, duration))
        # If nothing playing, start
        if not await self._is_playing(chat_id):
            await self._play_next(chat_id)
            return True
        return False

    async def _is_playing(self, chat_id: int) -> bool:
        try:
            call = self.call.get_call(chat_id)
            return call is not None
        except Exception:
            return False

    async def _play_next(self, chat_id: int):
        nxt = self.queue.pop(chat_id)
        if not nxt:
            try:
                await self.call.leave_group_call(chat_id)
            except Exception:
                pass
            return
        requested_by, url, title, duration = nxt
        vol = self.volume.get(chat_id, DEFAULT_VOLUME)
        params = {}
        if vol != 100:
            # adjust ffmpeg volume filter
            params['audio_parameters'] = {'preset': None, 'additional_ffmpeg_parameters': f'-filter:a volume={vol/100.0}'}
        try:
            await self.call.join_group_call(chat_id, AudioPiped(url, **params))
        except Exception as e:
            logger.error(f"Failed to start stream: {e}")
            await self._play_next(chat_id)

    async def skip(self, chat_id: int):
        await self._play_next(chat_id)

    async def stop(self, chat_id: int):
        self.queue.clear(chat_id)
        try:
            await self.call.leave_group_call(chat_id)
        except Exception:
            pass

    async def pause(self, chat_id: int):
        try:
            await self.call.pause_stream(chat_id)
        except Exception:
            pass

    async def resume(self, chat_id: int):
        try:
            await self.call.resume_stream(chat_id)
        except Exception:
            pass

    def set_volume(self, chat_id: int, vol: int):
        vol = max(MIN_VOLUME, min(MAX_VOLUME, vol))
        self.volume[chat_id] = vol
        return vol
