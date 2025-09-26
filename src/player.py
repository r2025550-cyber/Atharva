import asyncio
from typing import Dict, Tuple, Optional
from loguru import logger
from pyrogram import Client
from tgcaller import TgCaller, AudioConfig

from .queue import MusicQueue

DEFAULT_VOLUME = 100
MAX_VOLUME = 200
MIN_VOLUME = 0

QueueItem = Tuple[int, str, str, int]

class Player:
    def __init__(self, user_client: Client):
        self.app = user_client
        self.caller = TgCaller(self.app)
        self.queue = MusicQueue()
        self.current: Dict[int, Optional[QueueItem]] = {}
        self.volume: Dict[int, int] = {}

    async def start(self):
        @self.caller.on_stream_end
        async def on_end(_, update):
            chat_id = update.chat_id
            logger.info(f"Stream ended in chat {chat_id}, moving to next track")
            await self._play_next(chat_id)

        @self.caller.on_error
        async def on_err(_, error):
            logger.error(f"TgCaller error: {error}")

        await self.caller.start()
        logger.info("TgCaller started")

    async def join(self, chat_id: int):
        if not await self.caller.is_connected(chat_id):
            await self.caller.join_call(chat_id, audio_config=AudioConfig.high_quality())
            logger.info(f"Joined call: {chat_id}")

    async def leave(self, chat_id: int):
        try:
            await self.caller.leave_call(chat_id)
        except Exception as e:
            logger.debug(f"leave_call ignored: {e}")

    async def enqueue_and_maybe_start(self, chat_id: int, stream_url: str, title: str, duration: int, requested_by: int) -> bool:
        self.queue.add(chat_id, (requested_by, stream_url, title, duration))
        if not await self.caller.is_connected(chat_id):
            await self.join(chat_id)
        if not self.current.get(chat_id):
            await self._play_next(chat_id)
            return True
        return False

    async def _play_next(self, chat_id: int):
        nxt = self.queue.pop(chat_id)
        if not nxt:
            self.current[chat_id] = None
            return
        self.current[chat_id] = nxt
        requested_by, url, title, duration = nxt
        try:
            await self.caller.play(chat_id, url)
            await self.apply_volume(chat_id)
            logger.info(f"Playing in {chat_id}: {title}")
        except Exception as e:
            logger.error(f"Failed to start stream: {e}")
            await self._play_next(chat_id)

    async def skip(self, chat_id: int):
        await self._play_next(chat_id)

    async def stop(self, chat_id: int):
        self.queue.clear(chat_id)
        self.current[chat_id] = None
        try:
            await self.caller.stop_stream(chat_id)
        except Exception as e:
            logger.debug(f"stop_stream ignored: {e}")

    async def pause(self, chat_id: int):
        try:
            await self.caller.pause(chat_id)
        except Exception as e:
            logger.debug(f"pause ignored: {e}")

    async def resume(self, chat_id: int):
        try:
            await self.caller.resume(chat_id)
        except Exception as e:
            logger.debug(f"resume ignored: {e}")

    def set_volume(self, chat_id: int, vol: int):
        vol = max(MIN_VOLUME, min(MAX_VOLUME, vol))
        self.volume[chat_id] = vol
        return vol

    async def apply_volume(self, chat_id: int):
        vol = self.volume.get(chat_id, DEFAULT_VOLUME) / 100.0
        try:
            await self.caller.set_volume(chat_id, max(0.0, min(2.0, vol)))
        except Exception as e:
            logger.debug(f"set_volume ignored: {e}")
