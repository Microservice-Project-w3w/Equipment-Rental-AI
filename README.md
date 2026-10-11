# Trợ lý AI cho thuê thiết bị

AI chạy riêng trên Windows tại `E:\equipment-rental-AI`, port `8090`. Backend Java vẫn giữ bốn service Identity, Organization-Customer, Inventory và Rental. Không cần thêm Billing/Logistics/Maintenance hoặc chạy Java ai-service để dùng bản này.

## AI làm được gì?

| Câu hỏi | Dữ liệu được lấy |
| --- | --- |
| Tồn kho ở chi nhánh tôi có bao nhiêu thiết bị? | Thiết bị và kho từ Inventory; đếm theo trạng thái, lọc mã/serial/ghi chú, kho hoặc trạng thái. |
| Thiết bị loại ID 1 có đủ cho khoảng ngày thuê không? | Availability qua Rental gọi Inventory, có xét giữ chỗ; cần chi nhánh, ID loại, ngày giờ nhận/trả và số lượng. Không đoán ID loại từ tên. |
| Thiết bị nào đang bảo trì hoặc hư hỏng? | Thiết bị ở trạng thái MAINTENANCE, DAMAGED, INSPECTION. Chưa có phiếu, lịch, kỹ thuật viên hay chi phí sửa chữa. |
| Đơn nào sắp đến ngày trả trong 7 ngày tới? | Ngày bắt đầu/kết thúc đơn thuê và địa chỉ giao từ yêu cầu thuê. Chỉ là kế hoạch dự kiến, không xác nhận đã giao/đã nhận thực tế. |
| Giá trị hợp đồng đang hiệu lực là bao nhiêu? | Giá trị hợp đồng SIGNED/ACTIVE/EXTENDED, không phải doanh thu đã thu hay tiền đã thanh toán. |
| Báo giá nào chờ duyệt? | Báo giá SENT/PENDING_APPROVAL của các chi nhánh được giao. |
| Thông tin khách hàng số 2? | Hồ sơ khách hàng từ Organization-Customer theo quyền người hỏi. |

**Chưa có API thanh toán/hóa đơn/công nợ/thu cọc trong backend bốn service.** Câu hỏi về thanh toán sẽ nhận thông báo chưa có dữ liệu; AI không suy ra đã trả/còn nợ từ giá trị hợp đồng. Tương tự, trạng thái bảo trì không phải lịch bảo trì và ngày thuê dự kiến không phải bằng chứng giao nhận.

Bỏ công cụ “tôi đang dùng tài khoản nào” khỏi chat. AI vẫn gọi `GET /api/v1/auth/me` để xác thực JWT trước khi tra cứu, không bỏ bước xác thực.

## Quyền và cách kết nối

- Chỉ ADMIN và MANAGER được dùng chat.
- AI chuyển JWT của người hỏi qua Gateway; từng tool kiểm tra permission và organization/branch scope. Manager không được yêu cầu dữ liệu ngoài phạm vi được giao.
- Luồng: frontend gọi `POST /api/v1/ai/chat` tại Gateway → AI Python → API public của các service qua Gateway → Ollama diễn đạt kết quả.
- Tool ưu tiên GET qua danh sách endpoint cố định, không gọi `/internal/**` và không tự tạo/duyệt/hủy/sửa dữ liệu. Nếu bật DB fallback, API mất kết nối/timeout/502/503/504 mới chuyển sang các truy vấn SELECT cố định trên view được cấp quyền.
- Thiếu ID/ngày cần thiết thì hỏi lại. Không có quyền, API lỗi hoặc chưa hỗ trợ thì nói rõ; không dùng dữ liệu mẫu thay dữ liệu thật.
- Danh sách trả lời giới hạn 50 bản ghi nhưng tổng số được tính trên dữ liệu đã lấy. Lịch sử chat nằm trong RAM và mất khi AI restart.

## Chạy và thử

Cần môi trường Python >= 3.12 đã cài dependency. Bật các service backend và Gateway trước khi thử chat với dữ liệu thật. Ollama chạy riêng với model đã có; không cần Docker pull thêm model.

PowerShell:

```powershell
cd E:\equipment-rental-AI
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\.venv-win\Scripts\Activate.ps1
python -m pytest -q
python run.py
```

Kiểm tra `API_GATEWAY_BASE_URL`, `APP_HOST=0.0.0.0`, `APP_PORT=8090`, `OLLAMA_BASE_URL` và `OLLAMA_MODEL` trong `.env`. Không commit `.env`, thư mục virtualenv hay model. Nếu sửa code khi AI đang chạy chế độ development, Uvicorn tự reload; nếu không thì dừng và chạy lại `python run.py`.

Đăng nhập Admin/Manager ở frontend, mở trang Trợ lý AI và chọn câu hỏi gợi ý. Có thể chỉ rõ “chi nhánh 1/2” khi tài khoản được phép; không mặc định ID trên các máy giống nhau.

Frontend cũng có nút chat tròn màu xanh ở góc dưới bên phải dành cho Admin/Manager. Đóng cửa sổ giữ lại hội thoại; đăng xuất/đổi tài khoản sẽ bỏ trạng thái chat trên giao diện.

### Khi model trả mã kỹ thuật hoặc quá tải

Sau khi tool lấy được dữ liệu thật, AI yêu cầu Ollama diễn đạt thành tiếng Việt. Nếu lượt này lỗi hoặc trả JSON/function call thay cho lời đáp, `app/chatbot/response_generator.py` dựng câu trả lời từ kết quả tool, không tự thêm số liệu. Lỗi ở bước chọn tool vẫn báo lỗi, không giả vờ đã tra cứu.

Các biến cấu hình mặc định:

```dotenv
CHAT_RATE_LIMIT_REQUESTS=10
CHAT_RATE_LIMIT_WINDOW_SECONDS=60
CHAT_MAX_CONCURRENT_REQUESTS=1
```

Giới hạn áp dụng sau xác thực, theo user, dùng cửa sổ trượt. Một user chỉ gửi một câu đang xử lý; toàn bộ process mặc định xử lý một lượt để tránh quá tải model. Vượt giới hạn trả HTTP 429 kèm `Retry-After`. Đây là giới hạn trong RAM của một process, không dùng chung giữa nhiều worker và bị reset khi restart; chưa thay thế rate limit phân tán ở môi trường production.

Có thể dừng cả bốn service Java và Ollama rồi chạy `python -m pytest -q`: các test mặc định mô phỏng backend/database/model. Test DB và runtime là opt-in ở phần dưới. Khi chưa bật DB fallback, tra cứu dữ liệu thật cần API tương ứng đang chạy.

Bộ test chạy bằng MockTransport và mô phỏng Ollama: kiểm tra đường dẫn API, JWT, scope, quyền, dữ liệu thiếu, lọc tồn kho, kế hoạch nhận/trả, giá trị hợp đồng và việc không suy đoán thanh toán. **Không tải model và không khởi động Ollama để chạy test**; chưa thay thế kiểm thử chất lượng câu trả lời bằng model thật.

## Máy ít RAM: chỉ bật service có dữ liệu cần hỏi

Gateway, Identity và AI Python cần chạy để đăng nhập, kiểm tra session/quyền và nhận câu hỏi. MySQL phục vụ các service Java đang bật. Các service nghiệp vụ còn lại tùy câu hỏi:

| Muốn hỏi | Bật thêm |
| --- | --- |
| Tồn kho, thiết bị đang bảo trì/hư hỏng | Inventory |
| Báo giá chờ duyệt, giá trị hợp đồng, kế hoạch nhận/trả dự kiến | Rental |
| Hồ sơ khách hàng | Organization-Customer |
| Lịch trống có xét giữ chỗ | Rental + Inventory |

Không cần bật cả bốn service cho mọi câu hỏi. Mặc định AI ưu tiên API. Có thể bật DB fallback dưới đây để đọc database hiện có khi service nghiệp vụ tắt; đây không phải dữ liệu cache/snapshot và vẫn cần MySQL, Gateway, Identity đang hoạt động. Nếu API và DB đều lỗi, AI báo chưa lấy được dữ liệu, không trả số 0 thay lỗi kết nối.

Mặc định `CHAT_MODE=natural`: Ollama chọn công cụ và diễn đạt câu trả lời. `.env` riêng phải dùng đúng tên model đã có, hiện máy demo dùng `OLLAMA_MODEL=viet-tutor-frog`. Không cần tải Qwen. `.env` trong thư mục backend không tự cấu hình process Python ở ổ E.

Khi chỉ muốn demo tra cứu tồn kho, có thể không bật Ollama và chạy chế độ nhẹ trong PowerShell:

```powershell
cd E:\equipment-rental-AI
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\.venv-win\Scripts\Activate.ps1
$env:CHAT_MODE="light"
$env:CHAT_ENABLED_SERVICES="inventory"
python run.py
```

Chế độ nhẹ nhận diện một số mẫu câu bằng quy tắc, lấy dữ liệu API và dựng lời đáp tiếng Việt; không phải chat tự do qua model. Ví dụ: `Tồn kho chi nhánh 1`, `Thiết bị nào đang bảo trì?`. ID là dữ liệu thật của máy đang chạy, không tự đoán từ tên thiết bị. Để hỏi Rental hoặc khách hàng, sửa danh sách thành `inventory,rental,organization-customer` và bật service tương ứng.

Quay lại chat model: dừng Python, đặt `$env:CHAT_MODE="natural"`, rồi chạy lại. Biến trong PowerShell hiện tại ưu tiên hơn `.env`, nên kiểm tra cả hai khi đổi chế độ.

`GET /api/v1/ai/capabilities` qua Gateway với Bearer Admin/Manager cho biết chế độ và công cụ đã bật. Frontend có nút **Xem cấu hình tra cứu** trong chat. Đây là cấu hình, không khẳng định service đang online. Hội thoại được giới hạn mặc định 200 cuộc, hết hạn sau một giờ không sử dụng (`CHAT_MAX_CONVERSATIONS`, `CHAT_HISTORY_TTL_SECONDS`), mất khi restart. AI kiểm tra `/auth/me` trước mỗi lượt; session bị thu hồi hoặc tài khoản mất quyền Manager/Admin không được tiếp tục dùng token cũ để chat.

## Đọc database dự phòng khi service nghiệp vụ tắt

Luồng: xác thực Identity → thử API → nếu API không kết nối được hoặc trả 502/503/504, xác thực lại Identity và lấy quyền/tổ chức/chi nhánh hiện tại → SELECT trên view → Ollama diễn đạt (hoặc dựng lời đáp nếu dùng `light`). Không fallback cho 400/401/403/404/422/500, phản hồi thành công nhưng sai dữ liệu, hay khi Identity lỗi. Quyền trong JWT cũ không đủ để đọc DB; Identity phải trả các trường mới `permissions`, `organizationId`, `branchIds`.

### Cài và cấu hình lần đầu

Cập nhật dependency trong đúng virtualenv chạy AI. Nếu AI chạy Windows, cài vào `.venv-win`, không phải `.venv` của WSL:

```powershell
cd E:\equipment-rental-AI
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
& .\.venv-win\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Trong `.env` của AI, thêm cấu hình sau. Dùng mật khẩu riêng tối thiểu 12 ký tự, không dùng mật khẩu root/MySQL của backend:

```dotenv
AI_DB_FALLBACK_ENABLED=false
AI_DB_HOST=127.0.0.1
AI_DB_PORT=3307
AI_DB_USER=equipment_ai_reader
AI_DB_PASSWORD=<mật khẩu riêng của tài khoản chỉ đọc>
AI_DB_TIMEOUT_SECONDS=5
AI_DB_API_TIMEOUT_SECONDS=3
AI_DB_MAX_ROWS=2000
```

Chạy setup một lần từ WSL; `.venv` WSL cũng cần dependency mới:

```bash
cd /mnt/e/equipment-rental-AI
.venv/bin/python -m pip install -e ".[test]"
.venv/bin/python scripts/setup_db_fallback.py --backend-env /home/thaibinh/backend_microservice/.env
```

Script dùng root chỉ trong bước cấp quyền, không dùng root để chat. Nó đọc migration `infra/mysql/migrations/20261011_ai_readonly_views.sql` trong backend, tạo 9 view trên **inventory_db, rental_db, organization_customer_db** và chỉ cấp SELECT trên các view. Không tạo database mới, không nạp lại seed, không đổi bảng nghiệp vụ hay mật khẩu account có sẵn. Nếu account đã tồn tại với quyền rộng hơn, script từ chối sử dụng thay vì tự thu hồi quyền của account đó.

Sau setup, đổi `AI_DB_FALLBACK_ENABLED=true`, khởi động lại Identity bản mới và AI Python. Các biến PowerShell còn tồn tại ưu tiên hơn `.env`. Máy demo đã được tạo reader và cấu hình `.env` riêng; không cần chạy setup lại nếu không đổi password/database. Không commit `.env` hoặc password.

Nếu kết nối MySQL từ Windows không tới `127.0.0.1:3307`, kiểm tra cổng publish Docker/WSL và chỉnh `AI_DB_HOST` thành địa chỉ WSL mà Windows truy cập được. Không mở MySQL công khai lên Internet.

### Giới hạn và cách kiểm tra

- Có thể chỉ chạy MySQL + Gateway + Identity + AI Python; Ollama thêm khi dùng `natural`. Ba service nghiệp vụ có thể tắt. Không bỏ Identity/Gateway.
- Chat hiển thị `DATABASE_FALLBACK`, thời điểm đọc và cảnh báo chỉ đọc. Kết quả đọc DB không xác nhận giao nhận/thanh toán hay tạo giữ chỗ.
- Không nhận SQL/tên bảng từ model. Truy vấn có tham số, lọc organization/branch từ Identity, giới hạn 2.000 bản ghi mỗi truy vấn và 5 giây cho kết nối/đọc. Vượt giới hạn báo lỗi thay vì trả tổng thiếu. Không trộn dữ liệu API và DB trong cùng một lượt tool.
- Lịch trống xét thời gian overlap, trạng thái HELD/CONFIRMED và expires_at. HELD hết hạn không chặn thiết bị dù scheduler tắt. Chỉ xét thiết bị AVAILABLE trong kho/model/loại đang hoạt động. Báo giá/đơn giữ chỗ quá hạn được suy ra hết hạn khi đọc view; **không cập nhật trạng thái lưu trong DB**.
- Không đọc identity_db, số giấy tờ, ngày sinh hoặc bảng thanh toán chưa có. Quyền reader chỉ giới hạn cột/view, còn phạm vi từng người được ép ở truy vấn Python. Bảo vệ `.env` vì lộ credential reader vẫn có thể lộ dữ liệu của các view.
- Fallback phụ thuộc schema cũ; đổi schema cần cập nhật migration và adapter cùng nhau. Đây là phương án demo máy ít RAM, không phải thay thế nghiệp vụ của các service hoặc giải pháp chịu lỗi đầy đủ cho production.

Test DB thật (MySQL demo; không cần Java/Ollama) tạo/dọn tài khoản tạm và reservation `AI-FB-AUDIT-*`, không reset seed:

```bash
RUN_DB_FALLBACK_TESTS=1 .venv/bin/python -m pytest -q tests/test_database_fallback_live.py
```

Test toàn luồng với Identity + Gateway online, ba service nghiệp vụ tắt, reader đã cấu hình; không cần Ollama:

```bash
RUN_AI_FALLBACK_LIVE=1 .venv/bin/python -m pytest -q tests/test_database_fallback_runtime.py
```
