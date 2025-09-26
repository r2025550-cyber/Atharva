from typing import Deque, Dict, Tuple, Optional
from collections import deque

# Each item: (requested_by_id, stream_url, title, duration)
QueueItem = Tuple[int, str, str, int]

class MusicQueue:
    def __init__(self):
        self.queues: Dict[int, Deque[QueueItem]] = {}

    def _get(self, chat_id: int) -> Deque[QueueItem]:
        return self.queues.setdefault(chat_id, deque())

    def add(self, chat_id: int, item: QueueItem):
        self._get(chat_id).append(item)

    def pop(self, chat_id: int) -> Optional[QueueItem]:
        q = self._get(chat_id)
        return q.popleft() if q else None

    def peek(self, chat_id: int) -> Optional[QueueItem]:
        q = self._get(chat_id)
        return q[0] if q else None

    def clear(self, chat_id: int):
        self._get(chat_id).clear()

    def list(self, chat_id: int) -> list[QueueItem]:
        return list(self._get(chat_id))

    def __len__(self):
        return sum(len(q) for q in self.queues.values())
