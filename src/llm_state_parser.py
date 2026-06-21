from __future__ import annotations

import json
import os
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


os.environ.setdefault("TRANSFORMERS_NO_TORCHVISION", "1")
os.environ.setdefault("TRANSFORMERS_NO_VISION", "1")
os.environ.setdefault("TRANSFORMERS_NO_AUDIO", "1")

ALLOWED_INTENTS = {
    "COURSE_OFFERING_SEARCH",
    "COURSE_SCHEDULE_SEARCH",
    "COURSE_INFO_SEARCH",
    "CURRICULUM_COURSE_SEARCH",
    "STUDENT_INFO_LOOKUP",
    "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_RESULT_LOOKUP",
    "CREDIT_SUMMARY",
    "COURSE_RECOMMENDATION",
    "REGISTRATION_ELIGIBILITY_CHECK",
    "PREREQUISITE_LOOKUP",
    "AGGREGATION_STATISTICS",
}

ALLOWED_EDIT_OPERATIONS = {
    "NEW_QUERY",
    "ADD_FILTER",
    "REMOVE_FILTER",
    "REPLACE_FILTER",
    "CHANGE_ENTITY",
    "CHANGE_INTENT",
    "RESOLVE_REFERENCE",
    "SORT",
    "LIMIT",
    "AGGREGATE",
}

INTENT_ALIASES = {
    "COURSE_SEARCH": "COURSE_OFFERING_SEARCH",
    "VIEW_COURSE": "COURSE_OFFERING_SEARCH",
    "VIEW_COURSES": "COURSE_OFFERING_SEARCH",
    "VIEW_COURSE_CLASSES": "COURSE_OFFERING_SEARCH",
    "VIEW_CLASSES": "COURSE_OFFERING_SEARCH",
    "SEARCH_COURSE_CLASSES": "COURSE_OFFERING_SEARCH",
    "SEARCH_COURSE_REGISTRATION": "COURSE_OFFERING_SEARCH",
    "SEARCH_COURSE_REGISTRATIONS": "COURSE_OFFERING_SEARCH",
    "SEARCH_COURSE_OFFERING": "COURSE_OFFERING_SEARCH",
    "SEARCH_COURSE_OFFERINGS": "COURSE_OFFERING_SEARCH",
    "VIEW_COURSE_OFFERING": "COURSE_OFFERING_SEARCH",
    "VIEW_COURSE_OFFERINGS": "COURSE_OFFERING_SEARCH",
    "LIST_COURSE_CLASSES": "COURSE_OFFERING_SEARCH",
    "LIST_CLASSES": "COURSE_OFFERING_SEARCH",
    "LIST_OPEN_COURSES": "COURSE_OFFERING_SEARCH",
    "GET_OPEN_COURSES": "COURSE_OFFERING_SEARCH",
    "OPEN_COURSES": "COURSE_OFFERING_SEARCH",
    "OPEN_COURSE_SEARCH": "COURSE_OFFERING_SEARCH",
    "LIST_OPEN_CLASSES": "COURSE_OFFERING_SEARCH",
    "GET_OPEN_CLASSES": "COURSE_OFFERING_SEARCH",
    "OPEN_CLASSES": "COURSE_OFFERING_SEARCH",
    "FIND_CLASSES": "COURSE_OFFERING_SEARCH",
    "COURSE_CLASSES_SEARCH": "COURSE_OFFERING_SEARCH",
    "COURSE_CLASS_SEARCH": "COURSE_OFFERING_SEARCH",
    "COURSE_OFFERINGS": "COURSE_OFFERING_SEARCH",
    "COURSE_REGISTRATION_SEARCH": "COURSE_OFFERING_SEARCH",
    "COURSE_REGISTRATION": "COURSE_OFFERING_SEARCH",
    "VIEW_SCHEDULE": "COURSE_SCHEDULE_SEARCH",
    "SEARCH_SCHEDULE": "COURSE_SCHEDULE_SEARCH",
    "CLASS_SCHEDULE": "COURSE_SCHEDULE_SEARCH",
    "COURSE_SCHEDULE": "COURSE_SCHEDULE_SEARCH",
    "COURSE_INFO": "COURSE_INFO_SEARCH",
    "VIEW_COURSE_INFO": "COURSE_INFO_SEARCH",
    "SEARCH_COURSE_INFO": "COURSE_INFO_SEARCH",
    "CURRICULUM_SEARCH": "CURRICULUM_COURSE_SEARCH",
    "CURRICULUM": "CURRICULUM_COURSE_SEARCH",
    "PROGRAM_COURSES": "CURRICULUM_COURSE_SEARCH",
    "STUDENT_INFO": "STUDENT_INFO_LOOKUP",
    "VIEW_STUDENT_INFO": "STUDENT_INFO_LOOKUP",
    "STUDENT_REGISTRATIONS": "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_REGISTRATION": "STUDENT_REGISTRATION_LOOKUP",
    "VIEW_STUDENT_REGISTRATION": "STUDENT_REGISTRATION_LOOKUP",
    "VIEW_STUDENT_REGISTRATIONS": "STUDENT_REGISTRATION_LOOKUP",
    "LIST_REGISTERED_COURSES": "STUDENT_REGISTRATION_LOOKUP",
    "LIST_STUDENT_COURSES": "STUDENT_REGISTRATION_LOOKUP",
    "LIST_REGISTERED_CLASSES": "STUDENT_REGISTRATION_LOOKUP",
    "REGISTERED_CLASSES": "STUDENT_REGISTRATION_LOOKUP",
    "GET_STUDENT_REGISTERED_COURSES": "STUDENT_REGISTRATION_LOOKUP",
    "GET_REGISTERED_COURSES": "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_RESULTS": "STUDENT_RESULT_LOOKUP",
    "STUDENT_RESULT": "STUDENT_RESULT_LOOKUP",
    "LIST_COMPLETED_COURSES": "STUDENT_RESULT_LOOKUP",
    "LIST_PASSED_COURSES": "STUDENT_RESULT_LOOKUP",
    "LIST_STUDIED_COURSES": "STUDENT_RESULT_LOOKUP",
    "GET_STUDENT_RESULTS": "STUDENT_RESULT_LOOKUP",
    "GET_STUDIED_COURSES": "STUDENT_RESULT_LOOKUP",
    "CHECK_COURSE_STATUS": "STUDENT_RESULT_LOOKUP",
    "CHECK_GRADE": "STUDENT_RESULT_LOOKUP",
    "CHECK_REGISTRATION": "REGISTRATION_ELIGIBILITY_CHECK",
    "CHECK_COURSE_REGISTRATION": "REGISTRATION_ELIGIBILITY_CHECK",
    "REGISTRATION_CHECK": "REGISTRATION_ELIGIBILITY_CHECK",
    "REGISTRATION_ELIGIBILITY": "REGISTRATION_ELIGIBILITY_CHECK",
    "ELIGIBILITY_CHECK": "REGISTRATION_ELIGIBILITY_CHECK",
    "CONFIRM_REGISTRATION": "REGISTRATION_ELIGIBILITY_CHECK",
    "PREREQUISITES": "PREREQUISITE_LOOKUP",
    "PREREQUISITE": "PREREQUISITE_LOOKUP",
    "PREREQUISITE_SEARCH": "PREREQUISITE_LOOKUP",
    "LOOKUP_PREREQUISITE": "PREREQUISITE_LOOKUP",
    "STATISTICS": "AGGREGATION_STATISTICS",
    "AGGREGATE": "AGGREGATION_STATISTICS",
    "COUNT_STATISTICS": "AGGREGATION_STATISTICS",
    "LIST_CLASSES_PER_COURSE": "AGGREGATION_STATISTICS",
    "SELECT_SUBJECTS": "AGGREGATION_STATISTICS",
    "GET_STUDENT_CREDITS": "CREDIT_SUMMARY",
    "FILTER_REQUIRED_COURSES": "CURRICULUM_COURSE_SEARCH",
    "LIST_COURSES_BY_MAJOR": "CURRICULUM_COURSE_SEARCH",
    "COURSES_BY_MAJOR": "CURRICULUM_COURSE_SEARCH",
    "COURSE_RECOMMENDATION_SEARCH": "COURSE_RECOMMENDATION",
    "RECOMMEND_COURSES": "COURSE_RECOMMENDATION",
    "COURSE_ADVICE": "COURSE_RECOMMENDATION",
    "ACADEMIC_ADVICE": "COURSE_RECOMMENDATION",
    "SUGGEST_COURSES": "COURSE_RECOMMENDATION",
    "SUGGEST_REGISTRATION": "COURSE_RECOMMENDATION",
}

EDIT_OPERATION_ALIASES = {
    "NEW": "NEW_QUERY",
    "NONE": "NEW_QUERY",
    "NULL": "NEW_QUERY",
    "NO_OP": "NEW_QUERY",
    "NO_CHANGE": "NEW_QUERY",
    "QUERY": "NEW_QUERY",
    "SEARCH": "NEW_QUERY",
    "VIEW": "NEW_QUERY",
    "LIST": "NEW_QUERY",
    "FILTER": "ADD_FILTER",
    "ADD_CONDITION": "ADD_FILTER",
    "ADD": "ADD_FILTER",
    "ADD_FILTERS": "ADD_FILTER",
    "REMOVE_CONDITION": "REMOVE_FILTER",
    "REMOVE_FILTERS": "REMOVE_FILTER",
    "REPLACE_CONDITION": "REPLACE_FILTER",
    "UPDATE_FILTER": "REPLACE_FILTER",
    "UPDATE": "REPLACE_FILTER",
    "UPDATE_SLOT": "REPLACE_FILTER",
    "CHANGE_COURSE": "CHANGE_ENTITY",
    "CHANGE_COURSE_ID": "CHANGE_ENTITY",
    "CHANGE_CLASS": "CHANGE_ENTITY",
    "CHANGE_STUDENT": "CHANGE_ENTITY",
    "CHANGE_SUBJECT": "CHANGE_ENTITY",
    "CHANGE_OBJECT": "CHANGE_ENTITY",
    "SWITCH_INTENT": "CHANGE_INTENT",
    "CHANGE_TASK": "CHANGE_INTENT",
    "CHANGE_FILTER": "REPLACE_FILTER",
    "SWITCH_FILTER": "REPLACE_FILTER",
    "REFERENCE": "RESOLVE_REFERENCE",
    "REFER": "RESOLVE_REFERENCE",
    "REFERENCE_RESOLUTION": "RESOLVE_REFERENCE",
    "FOLLOW_UP": "RESOLVE_REFERENCE",
    "COUNT": "AGGREGATE",
    "STATISTIC": "AGGREGATE",
}

SLOT_ALIASES = {
    "student_id": "MaSV",
    "ma_sv": "MaSV",
    "masv": "MaSV",
    "course_id": "MaMH",
    "ma_mh": "MaMH",
    "mamh": "MaMH",
    "class_id": "MaLHP",
    "section_id": "MaLHP",
    "ma_lhp": "MaLHP",
    "malhp": "MaLHP",
    "semester": "HocKy",
    "hoc_ky": "HocKy",
    "term": "HocKy",
    "year": "NamHoc",
    "nam_hoc": "NamHoc",
    "weekday": "Thu",
    "thu": "Thu",
    "session": "Buoi",
    "buoi": "Buoi",
    "room": "MaPhong",
    "ma_phong": "MaPhong",
    "available": "CoTheDangKy",
    "has_slot": "CoTheDangKy",
    "remaining_seats": "CoTheDangKy",
    "available_only": "CoTheDangKy",
    "time_of_day": "Buoi",
    "status": "TrangThaiLHP",
    "result": "KetQua",
    "prereq_direction": "PrereqDirection",
    "limit": "Limit",
    "sort": "SortBy",
    "sort_by": "SortBy",
    "use_logged_in_student": "UseLoggedInStudent",
}

ALLOWED_SLOTS = {
    "MaSV",
    "HoTen",
    "MaMH",
    "TenMH",
    "MaLHP",
    "MaNganh",
    "TenNganh",
    "HocKy",
    "NamHoc",
    "Nhom",
    "Thu",
    "Buoi",
    "TietBD",
    "TietKT",
    "MaPhong",
    "DayNha",
    "CoTheDangKy",
    "TrangThaiLHP",
    "LoaiYC",
    "KetQua",
    "PrereqDirection",
    "Limit",
    "SortBy",
    "SortDirection",
    "UseLoggedInStudent",
}

SYSTEM_PROMPT = (
    "Ban la bo phan tich state cho bai toan Vietnamese multi-turn text-to-SQL trong he thong dang ky mon hoc.\n"
    "Chi tra ve mot JSON object hop le, khong markdown, khong giai thich.\n"
    "Schema bat buoc: {\"intent\": string, \"edit_operation\": string, \"slots\": object}.\n"
    "intent BAT BUOC la mot trong cac gia tri sau, khong duoc tao intent moi: "
    + ", ".join(sorted(ALLOWED_INTENTS))
    + ".\n"
    "edit_operation BAT BUOC la mot trong cac gia tri sau: "
    + ", ".join(sorted(ALLOWED_EDIT_OPERATIONS))
    + ".\n"
    "Neu khong chac intent, chon intent gan nhat trong danh sach allowed, tuyet doi khong sinh label moi."
)

INT_SLOTS = {"HocKy", "NamHoc", "Thu", "TietBD", "TietKT", "CoTheDangKy", "Limit"}
UPPER_SLOTS = {"MaSV", "MaMH", "MaLHP", "MaNganh", "Nhom", "Buoi", "TrangThaiLHP", "LoaiYC", "KetQua", "PrereqDirection", "SortBy", "SortDirection", "MaPhong", "DayNha"}

MODEL_COURSE_CODE_ALIASES = {
    "CSDL": "DBSY230184E",
    "CSCL": "DBSY230184E",
    "CT430101E": "DBSY230184E",
    "DBSY": "DBSY230184E",
    "AI": "ARIN330585E",
    "AI580101E": "ARIN330585E",
    "ARIN": "ARIN330585E",
    "ML": "MALE431085E",
    "MALE": "MALE431085E",
    "NLP": "NLPR431585E",
    "NLPR": "NLPR431585E",
}

SLOT_VALUE_ALIASES = {
    ("Buoi", "MORNING"): "SANG",
    ("Buoi", "AM"): "SANG",
    ("Buoi", "SANG"): "SANG",
    ("Buoi", "AFTERNOON"): "CHIEU",
    ("Buoi", "PM"): "CHIEU",
    ("Buoi", "CHIEU"): "CHIEU",
    ("CoTheDangKy", "TRUE"): 1,
    ("CoTheDangKy", "YES"): 1,
    ("CoTheDangKy", "CON_CHO"): 1,
    ("CoTheDangKy", "AVAILABLE"): 1,
    ("CoTheDangKy", "FALSE"): 0,
    ("CoTheDangKy", "NO"): 0,
    ("CoTheDangKy", "FULL"): 0,
    ("TrangThaiLHP", "OPEN"): "MO",
    ("TrangThaiLHP", "OPENED"): "MO",
    ("TrangThaiLHP", "AVAILABLE"): "MO",
    ("TrangThaiLHP", "MO"): "MO",
    ("TrangThaiLHP", "CLOSED"): "DONG",
    ("TrangThaiLHP", "FULL"): "DAY",
    ("LoaiYC", "REQUIRED"): "BAT_BUOC",
    ("LoaiYC", "MANDATORY"): "BAT_BUOC",
    ("LoaiYC", "ELECTIVE"): "TU_CHON",
    ("LoaiYC", "OPTIONAL"): "TU_CHON",
}


@dataclass
class ParsedState:
    intent: str
    edit_operation: str
    slots: Dict[str, Any]
    raw_text: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "edit_operation": self.edit_operation,
            "slots": dict(self.slots),
        }


class StateParserError(RuntimeError):
    pass


def compact_previous_state(previous_state: Dict[str, Any]) -> Dict[str, Any]:
    if not previous_state:
        return {}
    return {
        "intent": previous_state.get("intent"),
        "edit_operation": previous_state.get("edit_operation"),
        "slots": previous_state.get("slots", {}),
    }


def extract_json_object(text: str) -> Dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise StateParserError(f"LLM did not return JSON: {text[:200]}")
        obj = json.loads(match.group(0))
    if not isinstance(obj, dict):
        raise StateParserError("LLM JSON output is not an object")
    return obj


def normalize_state_object(obj: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(obj)

    if "intent" not in state:
        for key in ["label", "task", "type", "intent_name"]:
            if key in state:
                state["intent"] = state[key]
                break
    if "edit_operation" not in state:
        for key in ["edit", "operation", "op", "action"]:
            if key in state:
                state["edit_operation"] = state[key]
                break

    raw_slots = state.get("slots")
    if not isinstance(raw_slots, dict):
        raw_slots = {}
    for key in ["filter", "filters", "entities", "params", "parameters"]:
        value = state.get(key)
        if isinstance(value, dict):
            raw_slots.update(value)

    if "sort" in state and "SortBy" not in raw_slots:
        raw_slots["SortBy"] = state["sort"]
    state["slots"] = normalize_slots(raw_slots)

    if not state.get("edit_operation"):
        state["edit_operation"] = "NEW_QUERY"
    if not state.get("intent") and state["slots"]:
        state["intent"] = "COURSE_OFFERING_SEARCH"

    return state


def normalize_text(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-zA-Z0-9_\-\s]", " ", text).lower()
    return re.sub(r"\s+", " ", text).strip()


def canonical_intent(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip().upper()
    if token in {"", "NONE", "NULL"}:
        return None
    return INTENT_ALIASES.get(token, token)


def infer_allowed_intent_from_utterance(
    utterance: str,
    previous_state: Dict[str, Any],
    slots: Dict[str, Any],
) -> str:
    norm = normalize_text(utterance)
    previous_intent = canonical_intent(previous_state.get("intent"))
    has_reference = any(
        marker in norm
        for marker in [
            "mon nay",
            "mon do",
            "lop nay",
            "lop do",
            "sinh vien nay",
            "sinh vien do",
            "ban nay",
            "ban do",
            "nguoi nay",
            "nguoi do",
        ]
    )
    if previous_intent in ALLOWED_INTENTS and has_reference:
        return previous_intent
    if any(marker in norm for marker in ["mssv", "ma sinh vien", "ma sv", "thong tin cua toi", "toi la ai"]):
        return "STUDENT_INFO_LOOKUP"
    if any(marker in norm for marker in ["da hoc", "hoc nhung mon gi", "mon da hoc", "ket qua", "da dat", "chua dat", "rot", "truot", "qua mon"]):
        return "STUDENT_RESULT_LOOKUP"
    if "da dang ky" in norm or "da dang ki" in norm or "dang ky nhung lop nao" in norm or "dang ki nhung lop nao" in norm:
        return "STUDENT_REGISTRATION_LOOKUP"
    if any(marker in norm for marker in ["du dieu kien", "dang ky duoc", "dang ki duoc", "dk duoc", "co dk duoc"]):
        return "REGISTRATION_ELIGIBILITY_CHECK"
    if any(
        marker in norm
        for marker in [
            "tien quyet",
            "hoc truoc",
            "can hoc truoc",
            "truoc khi hoc",
            "yeu cau hoc",
            "nen hoc mon nao truoc",
            "hoc mon nao truoc",
            "mon nao truoc",
        ]
    ):
        return "PREREQUISITE_LOOKUP"
    if any(marker in norm for marker in ["nen dang ky", "nen dang ki", "nen hoc", "goi y", "phu hop cho toi"]):
        return "COURSE_RECOMMENDATION"
    if any(marker in norm for marker in ["tong tin chi", "bao nhieu tin chi da dang ky", "dang ky bao nhieu tin chi"]):
        return "CREDIT_SUMMARY"
    if any(marker in norm for marker in ["ctdt", "chuong trinh", "nganh", "khoa", "bat buoc", "tu chon", "hoc duoc"]):
        return "CURRICULUM_COURSE_SEARCH"
    if any(marker in norm for marker in ["moi mon", "bao nhieu lop", "co may lop", "thong ke", "dem "]):
        return "AGGREGATION_STATISTICS"
    if any(marker in norm for marker in ["lich", "thu ", "buoi", "phong", "giang vien", "ai day"]):
        return "COURSE_SCHEDULE_SEARCH"
    if any(marker in norm for marker in ["may tin chi", "so tin chi", "thong tin mon", "thuoc nganh"]):
        return "COURSE_INFO_SEARCH"
    if previous_intent in ALLOWED_INTENTS and any(marker in norm for marker in ["chi lay", "loc", "doi sang", "chuyen sang", "lay ", "top "]):
        return previous_intent
    return "COURSE_OFFERING_SEARCH"


def repair_state_for_utterance(
    obj: Dict[str, Any],
    utterance: str,
    previous_state: Dict[str, Any],
) -> Dict[str, Any]:
    state = normalize_state_object(obj)
    norm = normalize_text(utterance)
    slots = dict(state.get("slots") or {})
    previous_slots = dict(previous_state.get("slots") or {})

    carries_context = any(
        marker in norm
        for marker in [
            "chi lay",
            "loc",
            "doi sang",
            "chuyen sang",
            "mon nay",
            "mon do",
            "lop do",
            "sinh vien nay",
            "sinh vien do",
            "ban nay",
            "ban do",
            "nguoi nay",
            "nguoi do",
            "lay ",
        ]
    )
    if carries_context:
        merged_slots = dict(previous_slots)
        merged_slots.update(slots)
        slots = merged_slots

    is_directional_sang = "doi sang" in norm or "chuyen sang" in norm
    if "buoi sang" in norm or "lop sang" in norm or (re.search(r"\bsang\b", norm) and not is_directional_sang):
        slots["Buoi"] = "SANG"
    if "buoi chieu" in norm or re.search(r"\bchieu\b", norm):
        slots["Buoi"] = "CHIEU"
    if any(marker in norm for marker in ["con cho", "con slot", "dang ky duoc", "dang ki duoc"]):
        slots["CoTheDangKy"] = 1
    if (
        "dang mo" in norm
        or "lop mo" in norm
        or "trang thai mo" in norm
        or (re.search(r"\bmo\b", norm) and any(marker in norm for marker in ["lop", "mon", "hoc phan"]))
    ):
        slots["TrangThaiLHP"] = "MO"
    if "bat buoc" in norm:
        slots["LoaiYC"] = "BAT_BUOC"
    if "tu chon" in norm:
        slots["LoaiYC"] = "TU_CHON"
    if "rot" in norm or "truot" in norm or "khong dat" in norm or "chua dat" in norm:
        slots["KetQua"] = "KHONG_DAT"
    elif "da qua" in norm or "qua mon" in norm or re.search(r"\bqua\b", norm):
        slots["KetQua"] = "DAT"
    limit_match = re.search(r"\b(?:lay|top)\s*(\d+)\b", norm)
    if limit_match:
        slots["Limit"] = int(limit_match.group(1))

    if any(marker in norm for marker in ["tien quyet", "yeu cau", "hoc truoc", "truoc mon gi"]):
        if "MaMH" not in slots and "MaMH" in previous_slots:
            slots["MaMH"] = previous_slots["MaMH"]
        slots["PrereqDirection"] = "REQUIRED_BY" if "yeu cau" in norm and "truoc" in norm else "PREREQUISITES_OF"

    generic_open_course_query = (
        (
            "mon hoc mo" in norm
            or "nhung mon mo" in norm
            or "cac mon mo" in norm
            or ("mon nao" in norm and "hoc duoc" in norm and any(marker in norm for marker in ["khoa", "nganh"]))
        )
        and "MaMH" not in slots
    )
    if generic_open_course_query:
        slots.pop("MaMH", None)
        slots.pop("TenMH", None)

    if "doi sang" in norm or "chuyen sang" in norm:
        if "Buoi" not in previous_slots and not any(marker in norm for marker in ["buoi sang", "lop sang", "buoi chieu", "lop chieu"]):
            slots.pop("Buoi", None)
        if "CoTheDangKy" not in previous_slots and not any(marker in norm for marker in ["con cho", "con slot", "dang ky duoc", "dang ki duoc"]):
            slots.pop("CoTheDangKy", None)

    if isinstance(slots.get("HocKy"), int) and not 1 <= slots["HocKy"] <= 8:
        slots.pop("HocKy", None)

    state["slots"] = slots
    intent = state.get("intent")
    intent_token = canonical_intent(intent)

    if intent_token is None:
        previous_intent = previous_state.get("intent")
        if previous_intent and any(
            marker in norm
            for marker in [
                "chi lay",
                "loc",
                "doi sang",
                "mon nay",
                "mon do",
                "lop do",
                "sinh vien nay",
                "sinh vien do",
                "ban nay",
                "ban do",
                "nguoi nay",
                "nguoi do",
                "lay ",
            ]
        ):
            state["intent"] = previous_intent
        elif "tin chi" in norm and "sinh vien" in norm:
            state["intent"] = "CREDIT_SUMMARY"
        elif "moi mon" in norm or "bao nhieu lop" in norm:
            state["intent"] = "AGGREGATION_STATISTICS"
        else:
            state["intent"] = "COURSE_OFFERING_SEARCH"

    intent = state.get("intent")
    intent_token = canonical_intent(intent)

    if any(marker in norm for marker in ["tien quyet", "yeu cau", "hoc truoc", "truoc mon gi"]):
        state["intent"] = "PREREQUISITE_LOOKUP"
        intent_token = "PREREQUISITE_LOOKUP"

    if intent_token == "LIST_COURSES":
        if any(marker in norm for marker in ["nganh", "khoa", "chuong trinh", "hoc duoc"]):
            state["intent"] = "CURRICULUM_COURSE_SEARCH"
        elif "dang ky" in norm and "sinh vien" in norm:
            state["intent"] = "STUDENT_REGISTRATION_LOOKUP"
        else:
            state["intent"] = "COURSE_OFFERING_SEARCH"
    elif intent_token == "FIND_COURSE":
        if any(marker in norm for marker in ["lhp", "hoc thu", "phong", "giang vien", "lich"]):
            state["intent"] = "COURSE_SCHEDULE_SEARCH"
        elif any(marker in norm for marker in ["tien quyet", "yeu cau", "hoc truoc", "truoc"]):
            state["intent"] = "PREREQUISITE_LOOKUP"
        else:
            state["intent"] = "COURSE_INFO_SEARCH"
    elif intent_token == "GET_COURSE":
        if "sinh vien" in norm and any(marker in norm for marker in ["nganh", "khoa", "hoc"]):
            state["intent"] = "STUDENT_INFO_LOOKUP"
        else:
            state["intent"] = "COURSE_INFO_SEARCH"

    intent_token = canonical_intent(state.get("intent"))
    if intent_token not in ALLOWED_INTENTS:
        state["intent"] = infer_allowed_intent_from_utterance(utterance, previous_state, slots)

    edit_operation = state.get("edit_operation")
    edit_token = edit_operation.strip().upper() if isinstance(edit_operation, str) else edit_operation
    if edit_token in {"", "NONE", "NULL", None}:
        if any(marker in norm for marker in ["doi sang", "chuyen sang"]):
            state["edit_operation"] = "CHANGE_ENTITY"
        elif any(marker in norm for marker in ["chi lay", "loc", "bat buoc", "con cho", "buoi"]):
            state["edit_operation"] = "ADD_FILTER"
        elif any(marker in norm for marker in ["mon nay", "mon do", "lop do", "ban do"]):
            state["edit_operation"] = "RESOLVE_REFERENCE"
        elif any(marker in norm for marker in ["lay ", "top "]):
            state["edit_operation"] = "LIMIT"
        else:
            state["edit_operation"] = "NEW_QUERY"

    return state


def normalize_slots(slots: Dict[str, Any]) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {}
    for key, value in slots.items():
        canonical = SLOT_ALIASES.get(str(key), SLOT_ALIASES.get(str(key).lower(), key))
        normalized[canonical] = value
    return normalized


def validate_state(obj: Dict[str, Any]) -> ParsedState:
    obj = normalize_state_object(obj)
    intent = obj.get("intent")
    edit_operation = obj.get("edit_operation")
    intent = canonical_intent(intent)
    if isinstance(edit_operation, str):
        edit_operation = EDIT_OPERATION_ALIASES.get(
            edit_operation.strip().upper(),
            edit_operation.strip().upper(),
        )
    slots = obj.get("slots", {})
    if intent not in ALLOWED_INTENTS:
        raise StateParserError(f"Invalid intent: {intent}")
    if edit_operation not in ALLOWED_EDIT_OPERATIONS:
        raise StateParserError(f"Invalid edit_operation: {edit_operation}")
    if not isinstance(slots, dict):
        raise StateParserError("slots must be an object")

    clean_slots: Dict[str, Any] = {}
    for key, value in slots.items():
        if key not in ALLOWED_SLOTS or value in (None, ""):
            continue
        if isinstance(value, str):
            token = value.strip().upper()
            value = SLOT_VALUE_ALIASES.get((key, token), value)
            if key == "MaMH":
                value = MODEL_COURSE_CODE_ALIASES.get(token, value)
        if key in INT_SLOTS:
            try:
                int_value = int(value)
            except (TypeError, ValueError):
                continue
            if key == "HocKy" and not 1 <= int_value <= 8:
                continue
            clean_slots[key] = int_value
        elif key in UPPER_SLOTS and isinstance(value, str):
            clean_slots[key] = value.strip().upper()
        else:
            clean_slots[key] = value.strip() if isinstance(value, str) else value

    return ParsedState(intent=intent, edit_operation=edit_operation, slots=clean_slots)


def extract_state_from_response(obj: Dict[str, Any]) -> tuple[Dict[str, Any], str]:
    def looks_like_state(candidate: Dict[str, Any]) -> bool:
        return bool(
            {"intent", "edit_operation", "slots", "filter", "filters", "entities", "params", "parameters"}.intersection(
                candidate.keys()
            )
        )

    candidates = [
        obj.get("state"),
        obj.get("result"),
        obj.get("prediction"),
        obj.get("parsed"),
        obj.get("output"),
    ]

    if looks_like_state(obj):
        return obj, json.dumps(obj, ensure_ascii=False)

    choices = obj.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                candidates.append(message.get("content"))
            candidates.append(first.get("text"))

    for key in ["answer", "response", "text", "raw_text", "generated_text", "content"]:
        candidates.append(obj.get(key))

    last_preview = json.dumps(obj, ensure_ascii=False)[:500]
    for candidate in candidates:
        if isinstance(candidate, dict):
            if looks_like_state(candidate):
                return candidate, json.dumps(candidate, ensure_ascii=False)
        elif isinstance(candidate, str) and candidate.strip():
            last_preview = candidate[:500]
            try:
                parsed = extract_json_object(candidate)
            except Exception:
                continue
            if looks_like_state(parsed):
                return parsed, candidate
    raise StateParserError(f"Remote Qwen API response does not contain a state JSON: {last_preview}")


class QwenStateParser:
    def __init__(
        self,
        adapter_path: str | Path,
        base_model: Optional[str] = None,
        max_new_tokens: int = 192,
        repair_output: bool = True,
    ) -> None:
        self.adapter_path = Path(adapter_path)
        if not self.adapter_path.exists():
            raise StateParserError(f"Adapter path does not exist: {self.adapter_path}")
        self.base_model = base_model or self._read_base_model()
        self.max_new_tokens = max_new_tokens
        self.repair_output = repair_output
        self._tokenizer = None
        self._model = None
        self._torch = None
        if os.getenv("NL2SQL_SKIP_QWEN_PREFLIGHT") != "1":
            self._preflight_runtime()

    def _read_base_model(self) -> str:
        config_path = self.adapter_path / "adapter_config.json"
        if config_path.exists():
            config = json.loads(config_path.read_text(encoding="utf-8"))
            base = config.get("base_model_name_or_path")
            if base:
                return str(base)
        return "Qwen/Qwen2.5-Coder-7B-Instruct"

    def _min_vram_gb(self) -> float:
        name = self.base_model.lower()
        if "1.5b" in name or "1_5b" in name:
            return 3.5
        if "3b" in name:
            return 5.0
        if "7b" in name:
            return 7.0
        if "14b" in name or "15b" in name:
            return 12.0
        return 7.0

    def _preflight_runtime(self) -> None:
        try:
            import torch
        except ImportError:
            return
        if not torch.cuda.is_available():
            return
        total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        min_vram_gb = self._min_vram_gb()
        if total_vram_gb < min_vram_gb and os.getenv("NL2SQL_FORCE_LOW_VRAM") != "1":
            raise StateParserError(
                f"{self.base_model} needs about {min_vram_gb:.1f} GB VRAM, but this GPU appears to have "
                f"({total_vram_gb:.1f} GB). Use Kaggle/Colab/T4+, a smaller adapter, or set "
                "NL2SQL_FORCE_LOW_VRAM=1 to try anyway."
            )

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except Exception as exc:
            raise StateParserError(
                "Cannot import Qwen inference dependencies. Check the model environment from "
                "requirements-train.txt. Original error: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        self._torch = torch
        local_files_only = os.getenv("NL2SQL_ALLOW_MODEL_DOWNLOAD") != "1"
        if torch.cuda.is_available():
            total_vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            min_vram_gb = self._min_vram_gb()
            if total_vram_gb < min_vram_gb and os.getenv("NL2SQL_FORCE_LOW_VRAM") != "1":
                raise StateParserError(
                    f"{self.base_model} needs about {min_vram_gb:.1f} GB VRAM, but this GPU appears to have "
                    f"({total_vram_gb:.1f} GB). Use Kaggle/Colab/T4+, a smaller adapter, or set "
                    "NL2SQL_FORCE_LOW_VRAM=1 to try anyway."
                )

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.adapter_path,
            trust_remote_code=True,
            local_files_only=True,
        )
        if not getattr(self._tokenizer, "chat_template", None):
            template_path = self.adapter_path / "chat_template.jinja"
            if template_path.exists():
                self._tokenizer.chat_template = template_path.read_text(encoding="utf-8")

        model_kwargs: Dict[str, Any] = {"trust_remote_code": True}
        if torch.cuda.is_available():
            model_kwargs.update({"device_map": "auto", "torch_dtype": torch.float16})
            try:
                from transformers import BitsAndBytesConfig

                model_kwargs["quantization_config"] = BitsAndBytesConfig(
                    load_in_4bit=True,
                    bnb_4bit_compute_dtype=torch.float16,
                    bnb_4bit_quant_type="nf4",
                    bnb_4bit_use_double_quant=True,
                )
            except Exception:
                pass
        else:
            model_kwargs.update({"device_map": None, "torch_dtype": torch.float32})

        base = AutoModelForCausalLM.from_pretrained(
            self.base_model,
            local_files_only=local_files_only,
            **model_kwargs,
        )
        self._model = PeftModel.from_pretrained(base, self.adapter_path)
        self._model.eval()

    def parse(self, utterance: str, previous_state: Dict[str, Any]) -> ParsedState:
        self._load()
        assert self._tokenizer is not None
        assert self._model is not None
        assert self._torch is not None

        payload = {
            "previous_state": compact_previous_state(previous_state),
            "utterance": utterance,
        }
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, sort_keys=True)},
        ]
        prompt = self._tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = self._tokenizer(prompt, return_tensors="pt")
        model_device = next(self._model.parameters()).device
        inputs = {key: value.to(model_device) for key, value in inputs.items()}

        with self._torch.inference_mode():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
                do_sample=False,
                temperature=None,
                top_p=None,
                pad_token_id=self._tokenizer.eos_token_id,
            )
        generated = output_ids[0, inputs["input_ids"].shape[-1] :]
        text = self._tokenizer.decode(generated, skip_special_tokens=True)
        raw_state = extract_json_object(text)
        state_obj = repair_state_for_utterance(raw_state, utterance, previous_state) if self.repair_output else raw_state
        state = validate_state(state_obj)
        state.raw_text = text
        return state


class RemoteStateParser:
    def __init__(self, api_url: str, timeout_seconds: float = 60.0, repair_output: bool = True) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.repair_output = repair_output
        if not self.api_url:
            raise StateParserError("Remote Qwen API URL is empty")

    def parse(self, utterance: str, previous_state: Dict[str, Any]) -> ParsedState:
        payload = {
            "question": utterance,
            "utterance": utterance,
            "previous_state": compact_previous_state(previous_state),
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            f"{self.api_url}/parse",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise StateParserError(f"Remote Qwen API HTTP {exc.code}: {detail[:300]}") from exc
        except urllib.error.URLError as exc:
            raise StateParserError(f"Remote Qwen API connection failed: {exc}") from exc

        obj = json.loads(response_body)
        state_obj, raw_text = extract_state_from_response(obj)
        if self.repair_output:
            state_obj = repair_state_for_utterance(state_obj, utterance, previous_state)
        parsed = validate_state(state_obj)
        if isinstance(raw_text, str):
            parsed.raw_text = raw_text
        return parsed
