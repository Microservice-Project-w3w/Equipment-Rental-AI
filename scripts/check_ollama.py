import asyncio
import json
import sys

from app.clients.ollama_client import OllamaClient, OllamaError


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def main() -> None:
    try:
        result = await OllamaClient().check_health()
    except OllamaError as exc:
        print(f"Ollama: DOWN - {exc}")
        raise SystemExit(1) from exc

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["modelAvailable"]:
        print("Model cấu hình trong OLLAMA_MODEL chưa có trong Ollama.")
        raise SystemExit(2)


if __name__ == "__main__":
    asyncio.run(main())
