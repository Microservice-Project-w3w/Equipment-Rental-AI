from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any


def _number(value: Any) -> str:
    try:
        number = Decimal(str(value))
        if not number.is_finite():
            raise InvalidOperation()
        text = format(number, ",f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return text.replace(",", "_").replace(".", ",").replace("_", ".")
    except (InvalidOperation, ValueError):
        return "chưa có số liệu"


def _date(value: Any) -> str:
    try:
        return datetime.fromisoformat(str(value)).strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(value or "chưa có thời gian")


def is_natural_answer(value: str) -> bool:
    """Reject model protocol/tool dumps, not just the first character."""
    text = value.strip()
    if not text or len(text) > 6000:
        return False
    lowered = text.casefold()
    markers = ("<function", "</function", "<tool", "</tool", "system_data",
               "function_call", "tool_calls", '"tool"', '"result"', '"availableQuantity"'.casefold())
    if any(marker in lowered for marker in markers) or chr(96) * 3 in text:
        return False
    if text.startswith(("{", "[")):
        return False
    try:
        decoded = json.loads(text)
        if isinstance(decoded, (dict, list)):
            return False
    except (ValueError, TypeError):
        pass
    return not bool(re.search(r'<\|(?:im_start|im_end|assistant|end)', text, re.I))


def fallback_answer(tool: str, result: Any) -> str:
    """Render verified API facts without another model call or business writes."""
    data = result if isinstance(result, dict) else {}
    if tool == "check_equipment_availability":
        quantity = _number(data.get("requestedQuantity"))
        available = _number(data.get("availableQuantity"))
        dates = f"từ {_date(data.get('startAt'))} đến {_date(data.get('endAt'))}"
        if data.get("available") is True:
            answer = (f"Hiện có {available} thiết bị loại ID {data.get('equipmentTypeId')} "
                      f"khả dụng {dates}, đáp ứng yêu cầu thuê {quantity} thiết bị của bạn.")
        else:
            answer = (f"Chưa đủ thiết bị cho yêu cầu thuê {quantity} thiết bị loại ID "
                      f"{data.get('equipmentTypeId')} {dates}. Số lượng khả dụng được ghi nhận là {available}.")
        return answer + "\nĐây là kết quả kiểm tra tại thời điểm tra cứu, chưa tạo đơn hay giữ chỗ thiết bị."

    if tool in {"get_inventory_stock", "get_maintenance_equipment"}:
        total = _number(data.get("totalEquipment"))
        if tool == "get_maintenance_equipment":
            answer = f"Có {total} thiết bị đang bảo trì, hư hỏng hoặc chờ kiểm tra trong phạm vi của bạn."
            equipment = data.get("equipment", [])
            if equipment:
                answer += "\nMột số thiết bị: " + ", ".join(
                    str(item.get("assetCode") or f"ID {item.get('id')}") for item in equipment[:5]) + "."
            if data.get("equipmentListTruncated"):
                answer += "\nDanh sách chi tiết bị giới hạn; tổng số vẫn tính toàn bộ kết quả."
            return answer + "\nĐây chỉ là trạng thái trong kho, chưa có lịch bảo trì hay phiếu sửa chữa."
        labels = {"AVAILABLE": "sẵn sàng", "RESERVED": "đang giữ chỗ",
                  "CHECKED_OUT": "đã xuất", "IN_TRANSIT": "đang chuyển",
                  "INSPECTION": "chờ kiểm tra", "MAINTENANCE": "bảo trì",
                  "DAMAGED": "hư hỏng", "LOST": "thất lạc", "RETIRED": "ngừng sử dụng"}
        answer = f"Hệ thống ghi nhận {total} thiết bị trong phạm vi tra cứu của bạn."
        counts = data.get("countsByStatus", {})
        if counts:
            answer += "\n" + "; ".join(f"{labels.get(status, status)}: {_number(count)}"
                                      for status, count in counts.items()) + "."
        answer += f"\nCó {_number(data.get('availableInWarehouse'))} thiết bị ở trạng thái sẵn sàng và đang thuộc kho."
        return answer + "\nMuốn thuê theo khoảng ngày cụ thể, bạn cần kiểm tra lịch trống; số tồn hiện tại chưa bảo đảm khả dụng cho ngày thuê."

    if tool == "get_pending_quotations":
        quotations = result if isinstance(result, list) else []
        if not quotations:
            return "Hiện không có báo giá chờ duyệt trong phạm vi tra cứu của bạn."
        codes = ", ".join(str(row.get("quotationCode") or f"ID {row.get('id')}") for row in quotations[:5])
        answer = f"Có {len(quotations)} báo giá đang chờ duyệt.\n" + codes + "."
        if len(quotations) > 5:
            answer += "\nTrên đây là 5 báo giá đầu tiên; bạn có thể xem toàn bộ tại trang Báo giá chờ duyệt."
        return answer + "\nTôi chỉ tra cứu, chưa duyệt hay từ chối báo giá nào."

    if tool == "get_customer_info":
        if not data:
            return "Chưa có thông tin khách hàng để hiển thị."
        lines = [f"Thông tin khách hàng: {data.get('displayName') or data.get('customerCode') or data.get('id')}."]
        for key, label in (("customerCode", "Mã khách hàng"), ("phone", "Điện thoại"), ("email", "Email"), ("address", "Địa chỉ")):
            if data.get(key):
                lines.append(f"{label}: {data[key]}")
        return "\n".join(lines)

    if tool == "get_contract_values":
        answer = (f"Có {_number(data.get('totalContracts'))} hợp đồng trong phạm vi tra cứu.\n"
                  f"Tổng giá trị các hợp đồng đã ký, đang hiệu lực hoặc đã gia hạn: "
                  f"{_number(data.get('activeContractValue'))} VND.")
        if data.get("contractListTruncated"):
            answer += "\nDanh sách chi tiết hiển thị tối đa 50 hợp đồng; tổng giá trị tính theo toàn bộ kết quả phù hợp."
        return answer + "\nĐây là giá trị hợp đồng, không phải tiền đã thu; chưa có dữ liệu thanh toán hay công nợ."

    if tool == "get_rental_handover_plan":
        total = data.get("totalEvents", 0)
        if not total:
            return "Không có mốc giao/nhận trả dự kiến phù hợp với khoảng thời gian và phạm vi bạn yêu cầu."
        lines = [f"Có {_number(total)} mốc giao/nhận trả dự kiến phù hợp:"]
        events = data.get("events", [])
        for event in events[:5]:
            label = "Giao dự kiến" if event.get("eventType") == "EXPECTED_HANDOVER" else "Nhận trả dự kiến"
            code = event.get("orderCode") or f"ID {event.get('orderId')}"
            lines.append(f"• {code}: {label} lúc {_date(event.get('scheduledAt'))}.")
        if total > len(events[:5]):
            lines.append(f"Đang hiển thị {len(events[:5])} trên tổng số {_number(total)} mốc dự kiến.")
        lines.append("Đây là kế hoạch theo ngày thuê, không phải xác nhận đã giao hoặc đã nhận thiết bị.")
        return "\n".join(lines)

    return ("Xin chào! Tôi có thể giúp bạn tra cứu tồn kho, lịch trống thiết bị, báo giá chờ duyệt, "
            "hồ sơ khách hàng, giá trị hợp đồng và kế hoạch nhận–trả. "
            "Bạn hãy nêu nội dung cần tra cứu; tôi không tự tạo đơn hay thay đổi dữ liệu.")
