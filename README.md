# Equipment Rental AI

Chatbot là một FastAPI độc lập, chạy native trên Windows và dùng model do bạn
tự chọn trong Ollama. Dự án này không cần Docker.

## Kiến trúc

~~~text
Frontend :5173
   ├── đăng nhập/nghiệp vụ ──> API Gateway :8080 ──> microservices :8081-8087
   └── chat + cùng JWT ──────> AI API :8090 ──> Ollama :11434
                                      └───────> API Gateway :8080
~~~

AI chỉ gọi backend qua API_GATEWAY_BASE_URL. Client chặn URL đầy đủ,
/internal/** và mọi path nằm ngoài allowlist. AI không kết nối MySQL và
không gọi trực tiếp cổng 8081-8087.

Trước mỗi câu chat, AI gọi GET /api/v1/auth/me qua Gateway để Identity
Service xác thực JWT. Permission trong JWT chỉ dùng để ẩn tool không phù hợp;
quyền và data scope cuối cùng vẫn do backend kiểm tra.

## Yêu cầu

- Python 3.12 trở lên.
- Ollama đang chạy trên Windows.
- Model đã được cài bằng Ollama.
- Backend và API Gateway đang chạy trong Ubuntu/WSL.

Kiểm tra:

~~~powershell
python --version
ollama list
curl.exe http://localhost:8080/gateway/health/identity
~~~

Windows thường chuyển tiếp cổng WSL qua localhost. Nếu lệnh kiểm tra Gateway
không kết nối được, lấy IP của WSL bằng:

~~~powershell
wsl hostname -I
~~~

Sau đó đặt API_GATEWAY_BASE_URL=http://WSL-IP:8080 trong .env.

## Cài và chạy native trên Windows

Mở PowerShell:

~~~powershell
E:
cd E:\equipment-rental-ai

.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
~~~

Nếu chưa có virtual environment:

~~~powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
~~~

Tạo .env nếu chưa có:

~~~powershell
Copy-Item .env.example .env
~~~

Cấu hình tối thiểu:

~~~dotenv
APP_HOST=127.0.0.1
APP_PORT=8090
CORS_ORIGINS=http://localhost:5173

OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=ten-chinh-xac-trong-ollama-list

API_GATEWAY_BASE_URL=http://localhost:8080
~~~

Không cần chạy ollama serve nếu ứng dụng Ollama trên Windows đã hoạt động.
Kiểm tra hai dependency:

~~~powershell
python -m scripts.check_ollama
python -m scripts.check_backend
~~~

Chạy AI API:

~~~powershell
python run.py
~~~

Địa chỉ:

- AI API: http://localhost:8090
- Swagger: http://localhost:8090/docs
- Liveness: http://localhost:8090/api/v1/health
- Dependency status: http://localhost:8090/api/v1/health/dependencies
- Ollama models: http://localhost:8090/api/v1/models

## Chạy backend trong Ubuntu/WSL

Database và Redis của backend vẫn có thể chạy bằng Docker trong Ubuntu. AI
service bên ổ E không dùng Docker.

~~~bash
cd /home/thaibinh/backend
docker compose --env-file .env -f infra/docker-compose.yml up -d

set -a
source .env
set +a
~~~

Mỗi service chạy trong một terminal Ubuntu:

~~~bash
mvn -pl services/identity-service spring-boot:run
mvn -pl services/organization-customer-service spring-boot:run
mvn -pl services/inventory-service spring-boot:run
mvn -pl services/rental-service spring-boot:run
mvn -pl services/logistics-service spring-boot:run
mvn -pl services/billing-service spring-boot:run
mvn -pl services/maintenance-service spring-boot:run
mvn -pl api-gateway spring-boot:run
~~~

Chạy Gateway sau các service.

## Gọi chatbot

Frontend đăng nhập qua POST http://localhost:8080/api/v1/auth/login, lấy
data.accessToken, sau đó gửi chính token đó sang AI API:

~~~http
POST http://localhost:8090/api/v1/chat
Authorization: Bearer <accessToken>
Content-Type: application/json

{
  "message": "Cho tôi xem báo giá đang chờ duyệt",
  "conversationId": "optional-id"
}
~~~

Ví dụ PowerShell:

~~~powershell
$headers = @{ Authorization = "Bearer $accessToken" }
$body = @{ message = "Tài khoản đang đăng nhập của tôi là ai?" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "http://localhost:8090/api/v1/chat" -Headers $headers -ContentType "application/json" -Body $body
~~~

Xóa lịch sử hội thoại trong RAM:

~~~http
DELETE /api/v1/chat/{conversationId}
Authorization: Bearer <accessToken>
~~~

## Tool đã tích hợp

- Hồ sơ tài khoản hiện tại: GET /api/v1/auth/me.
- Báo giá chờ duyệt: GET /api/v1/quotations với organization/branch scope.
- Chi tiết khách hàng:
  GET /api/v1/organizations/{organizationId}/customers/{customerId}.

Đây là các tool đọc dữ liệu để tạo nền an toàn trước. Các thao tác ghi như duyệt
báo giá, thu tiền hoặc cập nhật thiết bị chưa được cho AI thực hiện.

## Test

~~~powershell
pytest
~~~

Smoke test thật cần access token hợp lệ:

~~~powershell
$env:TEST_ACCESS_TOKEN="<access-token>"
python test_real_logic.py
~~~
