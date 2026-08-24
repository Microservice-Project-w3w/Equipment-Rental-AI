import json
from app.clients.ollama_client import OllamaClient
from app.clients.api_gateway_client import ApiGatewayClient
from app.services.permission_service import PermissionService
from app.tools import customer_tools, rental_tools

class ChatOrchestrator:
    def __init__(self):
        self.ollama = OllamaClient()
        self.gateway = ApiGatewayClient()
        
    async def handle_message(self, message: str, token: str, conversation_id: str) -> dict:
        # Lấy context từ token
        context = PermissionService.extract_user_context(token)
        role = context.get("role", "guest")
        
        # 1. Phân loại Intent và gọi tool (ReAct/JSON format)
        system_prompt = f"""Bạn là một hệ thống phân tích ý định. Bạn có các công cụ sau:
1. get_pending_quotations: Lấy danh sách báo giá chờ duyệt. (Tham số: không có)
2. get_customer_info: Lấy thông tin khách hàng. (Tham số: customer_id)

Người dùng hỏi: "{message}"

Hãy xác định công cụ cần gọi. Trả về đúng định dạng JSON:
{{"tool": "tên_công_cụ", "params": {{"tên_tham_số": "giá trị"}}}}
Nếu không cần công cụ nào, trả về: {{"tool": "none"}}
Chỉ trả về JSON, không giải thích.
"""
        messages = [{"role": "system", "content": system_prompt}]
        intent_response = await self.ollama.chat(messages, json_format=True)
        
        tool_data = {"data": []}
        tool_used = None
        sources = []
        
        try:
            intent_json = json.loads(intent_response)
            tool_name = intent_json.get("tool")
            
            if tool_name and tool_name != "none":
                if PermissionService.can_access_tool(role, tool_name):
                    tool_used = tool_name
                    # Thực thi tool
                    if tool_name == "get_pending_quotations":
                        result = await rental_tools.get_pending_quotations(self.gateway, token)
                        tool_data["data"] = result
                        sources.append({"service": "rental-service", "endpoint": "/api/v1/quotations?status=pending"})
                    elif tool_name == "get_customer_info":
                        customer_id = intent_json.get("params", {}).get("customer_id")
                        if customer_id:
                            result = await customer_tools.get_customer_info(self.gateway, token, customer_id)
                            tool_data["data"] = result
                            sources.append({"service": "customer-service", "endpoint": f"/api/v1/customers/{customer_id}"})
                else:
                    tool_data["error"] = "Bạn không có quyền sử dụng chức năng này."
        except json.JSONDecodeError:
            pass # Không parse được JSON, tiếp tục
            
        # 2. Sinh câu trả lời cuối cùng
        final_system_prompt = f"""Bạn là trợ lý AI cho Equipment Rental. 
Thông tin từ hệ thống: {json.dumps(tool_data, ensure_ascii=False)}
Hãy trả lời câu hỏi của người dùng một cách tự nhiên bằng tiếng Việt."""
        final_messages = [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": message}
        ]
        
        answer = await self.ollama.chat(final_messages, json_format=False)
        
        return {
            "conversationId": conversation_id,
            "answer": answer,
            "data": tool_data.get("data", []) if isinstance(tool_data.get("data"), list) else [tool_data.get("data")] if tool_data.get("data") else [],
            "actions": [],
            "sources": sources
        }
