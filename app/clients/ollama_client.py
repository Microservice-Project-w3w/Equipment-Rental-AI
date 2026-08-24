import httpx
import os
import json
from typing import List, Dict, Any

class OllamaClient:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "viet-tutor-frog")
        self.timeout = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", 120))
        
    async def chat(self, messages: List[Dict[str, str]], json_format: bool = False) -> str:
        """
        Gửi request tới Ollama API.
        messages format: [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        """
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False
        }
        
        if json_format:
            payload["format"] = "json"
            
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                return data.get("message", {}).get("content", "")
            except Exception as e:
                print(f"Error calling Ollama API: {e}")
                return "Xin lỗi, tôi đang gặp sự cố khi kết nối tới hệ thống xử lý ngôn ngữ."
