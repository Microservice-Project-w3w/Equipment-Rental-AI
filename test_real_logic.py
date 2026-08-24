"""Smoke test thủ công khi Ollama, Gateway và Identity đang chạy."""

import asyncio
import os

from dotenv import load_dotenv

from app.chatbot.orchestrator import ChatOrchestrator


load_dotenv()


async def run_logic() -> None:
    token = os.getenv("TEST_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Hãy đặt TEST_ACCESS_TOKEN bằng access token thật trước khi chạy.")

    result = await ChatOrchestrator().handle_message(
        message="Tài khoản đang đăng nhập của tôi là ai?",
        token=token,
        conversation_id="manual-smoke-test",
    )
    print(result)


if __name__ == "__main__":
    asyncio.run(run_logic())
