from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "equipment-rental-ai"}


def test_chat_requires_access_token():
    response = client.post("/api/v1/chat", json={"message": "Xin chào"})
    assert response.status_code == 401
