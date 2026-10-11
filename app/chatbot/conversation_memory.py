from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from time import monotonic


class ConversationMemory:
    """Bộ nhớ RAM; dữ liệu mất khi AI service khởi động lại."""

    def __init__(self, history_limit: int, max_conversations: int = 200,
                 ttl_seconds: int = 3600, clock=monotonic):
        self._history_limit = history_limit
        self._max_conversations = max_conversations
        self._ttl = ttl_seconds
        self._clock = clock
        self._messages: OrderedDict[tuple[int, str], deque[dict[str, str]]] = OrderedDict()
        self._touched: dict[tuple[int, str], float] = {}
        self._lock = asyncio.Lock()

    def _prune(self) -> None:
        now = self._clock()
        for key in list(self._messages):
            if now - self._touched[key] >= self._ttl:
                self._messages.pop(key)
                self._touched.pop(key)

    async def get(self, user_id: int, conversation_id: str) -> list[dict[str, str]]:
        async with self._lock:
            self._prune()
            key = (user_id, conversation_id)
            history = self._messages.get(key)
            if history is None:
                return []  # Reading an unknown ID must not allocate a conversation.
            self._messages.move_to_end(key)
            self._touched[key] = self._clock()
            return list(history)

    async def add_exchange(
        self,
        user_id: int,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        async with self._lock:
            self._prune()
            key = (user_id, conversation_id)
            if key not in self._messages:
                while len(self._messages) >= self._max_conversations:
                    expired, _ = self._messages.popitem(last=False)
                    self._touched.pop(expired)
                self._messages[key] = deque(maxlen=self._history_limit)
            history = self._messages[key]
            self._messages.move_to_end(key)
            self._touched[key] = self._clock()
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": assistant_message})

    async def clear(self, user_id: int, conversation_id: str) -> None:
        async with self._lock:
            self._messages.pop((user_id, conversation_id), None)
            self._touched.pop((user_id, conversation_id), None)
