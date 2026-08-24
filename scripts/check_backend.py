import asyncio
import json
import sys

from app.clients.api_gateway_client import ApiGatewayClient, GatewayError


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


async def main() -> None:
    try:
        result = await ApiGatewayClient().check_health()
    except GatewayError as exc:
        print(f"API Gateway: DOWN - {exc.detail}")
        raise SystemExit(1) from exc

    print("API Gateway: UP")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
