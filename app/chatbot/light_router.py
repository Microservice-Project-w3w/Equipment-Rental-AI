"""Restricted Vietnamese lookup routing. No model, invented IDs or business writes."""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any

TOOL_SERVICES = {
    "get_inventory_stock": frozenset({"inventory"}),
    "get_maintenance_equipment": frozenset({"inventory"}),
    "check_equipment_availability": frozenset({"rental", "inventory"}),
    "get_pending_quotations": frozenset({"rental"}),
    "get_contract_values": frozenset({"rental"}),
    "get_rental_handover_plan": frozenset({"rental"}),
    "get_customer_info": frozenset({"organization-customer"}),
}

def normalize(message: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", message.casefold())
                   if unicodedata.category(char) != "Mn").replace("đ", "d")

def select_light_tool(message: str) -> tuple[str, dict[str, Any]]:
    text = normalize(message)
    params: dict[str, Any] = {}
    patterns = {
        "organization_id": r"(?:organization[_ ]?id|org[_ ]?id|to chuc)\s*[:=#]?\s*(\d+)\b",
        "branch_id": r"(?:branch[_ ]?id|chi nhanh)\s*[:=#]?\s*(\d+)\b",
        "customer_id": r"(?:customer[_ ]?id|khach hang(?:\s+(?:id|so))?)\s*[:=#]?\s*(\d+)\b",
        "equipment_type_id": r"(?:equipment[_ ]?type[_ ]?id|loai thiet bi(?:\s+id)?)\s*[:=#]?\s*(\d+)\b",
        "warehouse_id": r"(?:warehouse[_ ]?id|kho(?:\s+id)?)\s*[:=#]?\s*(\d+)\b",
        "contract_id": r"(?:contract[_ ]?id|hop dong(?:\s+(?:id|so))?)\s*[:=#]?\s*(\d+)\b",
        "quantity": r"(?:quantity|so luong)\s*[:=#]?\s*(\d+)\b",
    }
    for key, pattern in patterns.items():
        matches = re.findall(pattern, text)
        if len(set(matches)) > 1:
            raise ValueError(f"Chỉ chọn một {key} cho mỗi câu hỏi.")
        if matches:
            params[key] = int(matches[0])
            if params[key] <= 0:
                raise ValueError(f"{key} phải là số nguyên dương.")

    if re.search(r"\b(lich trong|kha dung|co du|con trong|du thiet bi)\b", text):
        dates = re.findall(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}(?::\d{2})?(?:z|[+-]\d{2}:\d{2})?", text)
        if len(dates) == 2:
            params.update(start_at=dates[0].replace("t", "T").replace("z", "Z"),
                          end_at=dates[1].replace("t", "T").replace("z", "Z"))
        return "check_equipment_availability", params
    if re.search(r"\b(bao tri|hu hong|hong hoc)\b", text):
        return "get_maintenance_equipment", params
    if "ton kho" in text or re.search(r"bao nhieu thiet bi|so luong thiet bi", text):
        return "get_inventory_stock", params
    if "bao gia" in text and re.search(r"cho|duyet", text):
        return "get_pending_quotations", params
    if "hop dong" in text and re.search(r"gia tri|tong|hieu luc", text):
        return "get_contract_values", params
    if "khach hang" in text or "customerid" in text:
        return "get_customer_info", params
    if re.search(r"\b(giao|nhan|tra thiet bi|ngay tra)\b", text):
        interval = re.search(r"(?:trong\s+)?(\d+)\s+ngay\s+toi", text)
        if interval:
            days = int(interval.group(1))
            if not 1 <= days <= 90:
                raise ValueError("Chọn khoảng từ 1 đến 90 ngày tới.")
            today = datetime.now(timezone(timedelta(hours=7))).date()
            # Calendar window includes today and exactly N dates.
            params.update(from_date=today.isoformat(), to_date=(today + timedelta(days=days - 1)).isoformat())
        return "get_rental_handover_plan", params
    return "none", {}
