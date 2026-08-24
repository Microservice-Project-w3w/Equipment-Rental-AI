import jwt
from typing import Dict, Any

class PermissionService:
    @staticmethod
    def extract_user_context(token: str) -> Dict[str, Any]:
        """
        Decode JWT (không verify signature vì Gateway/Identity làm)
        để lấy context (role, userId, organizationId).
        """
        try:
            # Decode payload, bỏ qua signature verification
            decoded = jwt.decode(token, options={"verify_signature": False})
            return decoded
        except jwt.DecodeError:
            print("Failed to decode token")
            return {"role": "guest"}
            
    @staticmethod
    def can_access_tool(role: str, tool_name: str) -> bool:
        """
        Kiểm tra role có quyền gọi tool này không.
        """
        # Mapping ví dụ
        role_permissions = {
            "customer": ["get_customer_info", "get_pending_quotations"],
            "admin": ["get_customer_info", "get_pending_quotations", "approve_quotation"],
            "guest": []
        }
        
        allowed_tools = role_permissions.get(role, [])
        return tool_name in allowed_tools
