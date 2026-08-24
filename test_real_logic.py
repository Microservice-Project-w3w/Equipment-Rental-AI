import asyncio
import jwt
from app.chatbot.orchestrator import ChatOrchestrator
from dotenv import load_dotenv

load_dotenv()

async def test_logic():
    # 1. Tạo 1 token giả có role admin
    payload = {"userId": "123", "role": "admin", "customerId": "CUST-001"}
    token = jwt.encode(payload, "secret", algorithm="HS256")
    
    # 2. Khởi tạo orchestrator
    orchestrator = ChatOrchestrator()
    
    # 3. Hỏi câu hỏi gọi tool
    print("User: Cho tôi xem các báo giá đang chờ duyệt")
    result = await orchestrator.handle_message(
        message="Cho tôi xem các báo giá đang chờ duyệt",
        token=token,
        conversation_id="test-conv"
    )
    print("\nSystem Tool Output:", result["data"])
    print("\nAI Answer:", result["answer"])
    
if __name__ == "__main__":
    asyncio.run(test_logic())
