from collections import defaultdict, deque
from typing import Deque, Dict, Tuple, Optional, List

QueueItem = Tuple[int, str, str, int]

class MusicQueue:
    def __init__(self):
        self._store: Dict[int, Deque[QueueItem]] = defaultdict(deque)

    def add(self, chat_id: int, item: QueueItem):
        self._store[chat_id].append(item)

    def pop(self, chat_id: int) -> Optional[QueueItem]:
        if self._store[chat_id]:
            return self._store[chat_id].popleft()
        return None

    def clear(self, chat_id: int):
        self._store[chat_id].clear()

    def list(self, chat_id: int) -> List[QueueItem]:
        return list(self._store[chat_id])
