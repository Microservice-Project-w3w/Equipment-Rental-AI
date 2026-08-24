import httpx
import os
from typing import Dict, Any, Optional

class ApiGatewayClient:
    def __init__(self):
        self.base_url = os.getenv("API_GATEWAY_BASE_URL", "http://localhost:8080")
        self.timeout = int(os.getenv("API_GATEWAY_TIMEOUT_SECONDS", 30))
        
    def _get_headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
    async def get(self, endpoint: str, token: str, params: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(url, headers=self._get_headers(token), params=params)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"Gateway GET error: {e}")
                return {"error": str(e)}

    async def post(self, endpoint: str, token: str, payload: Dict[str, Any]) -> Any:
        url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, headers=self._get_headers(token), json=payload)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError as e:
                print(f"Gateway POST error: {e}")
                return {"error": str(e)}
