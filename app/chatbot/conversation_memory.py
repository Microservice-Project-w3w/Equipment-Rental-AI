from __future__ import annotations

import asyncio
from collections import defaultdict, deque


class ConversationMemory:
    """Bộ nhớ RAM; dữ liệu mất khi AI service khởi động lại."""

    def __init__(self, history_limit: int):
        self._history_limit = history_limit
        self._messages: dict[tuple[int, str], deque[dict[str, str]]] = defaultdict(
            lambda: deque(maxlen=self._history_limit)
        )
        self._lock = asyncio.Lock()

    async def get(self, user_id: int, conversation_id: str) -> list[dict[str, str]]:
        async with self._lock:
            return list(self._messages[(user_id, conversation_id)])

    async def add_exchange(
        self,
        user_id: int,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        async with self._lock:
            history = self._messages[(user_id, conversation_id)]
            history.append({"role": "user", "content": user_message})
            history.append({"role": "assistant", "content": assistant_message})

    async def clear(self, user_id: int, conversation_id: str) -> None:
        async with self._lock:
            self._messages.pop((user_id, conversation_id), None)
