from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence, Tuple

import pandas as pd
from rapidfuzz import fuzz, process

from .business_rules import (
    DEFAULT_DB_PATH,
    MAX_CREDITS_PER_SEMESTER,
    apply_views_if_missing,
    check_registration_eligibility,
    connect_db,
    find_eligible_offerings_for_course,
)
from .llm_state_parser import ParsedState, QwenStateParser, RemoteStateParser, StateParserError, validate_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def strip_accents(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_text(text: str) -> str:
    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9_\-\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def as_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def dataframe_from_rows(rows: Iterable[sqlite3.Row | Dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([dict(row) for row in rows])


@dataclass
class QueryContext:
    intent: Optional[str] = None
    edit_operation: Optional[str] = None
    slots: Dict[str, Any] = field(default_factory=dict)
    sql: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    last_df: Optional[pd.DataFrame] = None
    last_user_text: str = ""

    def copy(self) -> "QueryContext":
        return QueryContext(
            intent=self.intent,
            edit_operation=self.edit_operation,
            slots=dict(self.slots),
            sql=self.sql,
            params=dict(self.params),
            last_df=self.last_df.copy() if self.last_df is not None else None,
            last_user_text=self.last_user_text,
        )


@dataclass
class QueryResult:
    user_text: str
    intent: str
    edit_operation: str
    slots: Dict[str, Any]
    sql: Optional[str]
    params: Dict[str, Any]
    dataframe: pd.DataFrame
    message: str
    warnings: List[str] = field(default_factory=list)
    parser_source: str = "rule"
    parser_warning: Optional[str] = None


class StateParser(Protocol):
    def parse(self, utterance: str, previous_state: Dict[str, Any]) -> ParsedState:
        ...


class Catalog:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.courses = self._load_courses()
        self.course_aliases = self._build_course_aliases()
        self.majors = self._load_majors()
        self.major_aliases = self._build_major_aliases()

    def _load_courses(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT MaMH, TenMH, SoTC FROM MonHoc ORDER BY TenMH"
        ).fetchall()
        return [dict(row) for row in rows]

    def _load_majors(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT MaNganh, TenNganh FROM Nganh ORDER BY MaNganh").fetchall()
        return [dict(row) for row in rows]

    def _build_course_aliases(self) -> Dict[str, str]:
        alias_map: Dict[str, str] = {}
        for course in self.courses:
            ma_mh = course["MaMH"]
            names = {course["TenMH"], ma_mh}
            manual = COURSE_ALIASES.get(ma_mh, [])
            names.update(manual)
            for name in names:
                alias_map[normalize_text(name)] = ma_mh
        return alias_map

    def _build_major_aliases(self) -> Dict[str, str]:
        alias_map: Dict[str, str] = {}
        for major in self.majors:
            ma_nganh = major["MaNganh"]
            names = {major["TenNganh"], ma_nganh}
            names.update(MAJOR_ALIASES.get(ma_nganh, []))
            for name in names:
                alias_map[normalize_text(name)] = ma_nganh
        return alias_map

    def match_course(
        self,
        text: str,
        threshold: int = 78,
        allow_fuzzy: bool = True,
    ) -> Optional[Dict[str, Any]]:
        norm_text = normalize_text(text)
        ma_mh = self._exact_entity_match(norm_text, self.course_aliases)
        if ma_mh is None and allow_fuzzy:
            match = process.extractOne(
                norm_text,
                list(self.course_aliases.keys()),
                scorer=fuzz.WRatio,
            )
            if match and match[1] >= threshold:
                ma_mh = self.course_aliases[match[0]]
        if ma_mh is None:
            return None
        return self.get_course(ma_mh)

    def match_major(
        self,
        text: str,
        threshold: int = 78,
        allow_fuzzy: bool = True,
    ) -> Optional[Dict[str, Any]]:
        norm_text = normalize_text(text)
        ma_nganh = self._exact_entity_match(norm_text, self.major_aliases)
        if ma_nganh is None and allow_fuzzy:
            match = process.extractOne(
                norm_text,
                list(self.major_aliases.keys()),
                scorer=fuzz.WRatio,
            )
            if match and match[1] >= threshold:
                ma_nganh = self.major_aliases[match[0]]
        if ma_nganh is None:
            return None
        return self.get_major(ma_nganh)

    def get_course(self, ma_mh: str) -> Optional[Dict[str, Any]]:
        for course in self.courses:
            if course["MaMH"].upper() == ma_mh.upper():
                return dict(course)
        return None

    def get_major(self, ma_nganh: str) -> Optional[Dict[str, Any]]:
        for major in self.majors:
            if major["MaNganh"] == str(ma_nganh):
                return dict(major)
        return None

    @staticmethod
    def _exact_entity_match(norm_text: str, alias_map: Dict[str, str]) -> Optional[str]:
        tokenized = f" {norm_text} "
        best_alias = None
        for alias in alias_map:
            if not alias:
                continue
            if re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", tokenized):
                if best_alias is None or len(alias) > len(best_alias):
                    best_alias = alias
        return alias_map[best_alias] if best_alias else None


class VietnameseNL2SQLEngine:
    """Rule-based, context-aware NL2SQL baseline for the course registration domain."""

    def __init__(
        self,
        db_path: Path | str = DEFAULT_DB_PATH,
        state_parser: Optional[StateParser] = None,
        parser_mode: str = "rule",
        lora_path: Optional[Path | str] = None,
        remote_api_url: Optional[str] = None,
    ):
        self.db_path = Path(db_path)
        self.context = QueryContext()
        self._lock = threading.RLock()
        self.conn = connect_db(self.db_path)
        apply_views_if_missing(self.conn)
        self.catalog = Catalog(self.conn)
        self.parser_mode = parser_mode
        self.state_parser = state_parser
        self.parser_load_error: Optional[str] = None
        if self.parser_mode == "remote" and self.state_parser is None:
            configured_url = remote_api_url or os.getenv("NL2SQL_QWEN_API_URL")
            if configured_url:
                try:
                    self.state_parser = RemoteStateParser(configured_url)
                except Exception as exc:
                    self.parser_load_error = str(exc)
                    self.parser_mode = "rule"
            else:
                self.parser_load_error = "NL2SQL_QWEN_API_URL is not configured"
                self.parser_mode = "rule"
        if self.parser_mode == "hybrid" and self.state_parser is None:
            configured_lora = lora_path or os.getenv("NL2SQL_LORA_PATH")
            if configured_lora:
                try:
                    self.state_parser = QwenStateParser(configured_lora)
                except Exception as exc:
                    self.parser_load_error = str(exc)
                    self.parser_mode = "rule"

    def close(self) -> None:
        with self._lock:
            self.conn.close()

    def reset(self) -> None:
        with self._lock:
            self.context = QueryContext()

    def ask(self, user_text: str) -> QueryResult:
        with self._lock:
            base_context = self.context.copy()
            parsed = self._parse(user_text, base_context)
            intent = parsed["intent"]
            slots = parsed["slots"]
            edit_operation = parsed["edit_operation"]
            parser_source = parsed.get("parser_source", "rule")
            parser_warning = parsed.get("parser_warning")

            result = self._execute_intent(
                user_text,
                intent,
                slots,
                edit_operation,
                parser_source=parser_source,
                parser_warning=parser_warning,
            )

            self.context = QueryContext(
                intent=result.intent,
                edit_operation=result.edit_operation,
                slots=dict(result.slots),
                sql=result.sql,
                params=dict(result.params),
                last_df=result.dataframe.copy(),
                last_user_text=user_text,
            )
            return result

    def _parse(self, user_text: str, previous: QueryContext) -> Dict[str, Any]:
        rule_parsed = self._parse_rule(user_text, previous)
        if self.parser_mode not in {"hybrid", "remote"} or self.state_parser is None:
            if self.parser_load_error:
                rule_parsed["parser_warning"] = self.parser_load_error
            return rule_parsed

        previous_state = self._previous_state(previous)
        try:
            llm_state = self.state_parser.parse(user_text, previous_state)
            llm_parsed = self._normalize_external_state(llm_state.as_dict(), user_text)
            llm_parsed["parser_source"] = "qwen"
            return llm_parsed
        except Exception as exc:
            if isinstance(exc, StateParserError):
                self.parser_load_error = str(exc)
                self.parser_mode = "rule"
                self.state_parser = None
            rule_parsed["parser_source"] = "rule_fallback"
            rule_parsed["parser_warning"] = str(exc)
            return rule_parsed

    def _parse_rule(self, user_text: str, previous: QueryContext) -> Dict[str, Any]:
        norm = normalize_text(user_text)
        slots = self._initial_slots_from_context(norm, previous)
        extracted_slots = self._extract_slots(user_text)
        edit_operation = self._detect_edit_operation(norm, previous, extracted_slots)

        if edit_operation == "REMOVE_FILTER":
            slots = self._remove_requested_filters(norm, slots)
        else:
            slots.update(extracted_slots)

        intent = self._detect_intent(norm, slots, previous, edit_operation)
        if edit_operation in {"CHANGE_INTENT", "AGGREGATE"} and intent != previous.intent:
            slots = self._keep_reusable_slots(slots)
            slots.update(extracted_slots)

        return {"intent": intent, "slots": slots, "edit_operation": edit_operation, "parser_source": "rule"}

    @staticmethod
    def _previous_state(previous: QueryContext) -> Dict[str, Any]:
        if previous.intent is None:
            return {}
        return {
            "intent": previous.intent,
            "edit_operation": previous.edit_operation or "NEW_QUERY",
            "slots": dict(previous.slots),
        }

    def _normalize_external_state(self, state: Dict[str, Any], user_text: str) -> Dict[str, Any]:
        parsed = validate_state(state)
        slots = dict(parsed.slots)

        ma_mh = slots.get("MaMH")
        if ma_mh:
            course = self.catalog.get_course(str(ma_mh))
            if course:
                slots["MaMH"] = course["MaMH"]
                slots["TenMH"] = course["TenMH"]

        ma_nganh = slots.get("MaNganh")
        if ma_nganh:
            major = self.catalog.get_major(str(ma_nganh))
            if major:
                slots["MaNganh"] = major["MaNganh"]
                slots["TenNganh"] = major["TenNganh"]

        extracted = self._extract_slots(user_text)
        for key in ["MaSV", "MaMH", "TenMH", "MaLHP", "MaNganh", "TenNganh"]:
            if key in extracted:
                slots[key] = extracted[key]

        return {
            "intent": parsed.intent,
            "edit_operation": parsed.edit_operation,
            "slots": slots,
        }

    def _initial_slots_from_context(self, norm: str, previous: QueryContext) -> Dict[str, Any]:
        if previous.intent is None:
            return {}
        reset_markers = [
            "cho toi xem",
            "hay liet ke",
            "liet ke",
            "tim ",
            "tra cuu",
            "danh sach",
            "sinh vien ",
            "sinh vien nao",
            "mon nao",
            "moi mon",
        ]
        if any(marker in norm for marker in reset_markers) and not self._has_reference(norm):
            return {}
        return dict(previous.slots)

    def _extract_slots(self, user_text: str) -> Dict[str, Any]:
        norm = normalize_text(user_text)
        slots: Dict[str, Any] = {}

        ma_sv = re.search(r"(?<!\d)(\d{8})(?!\d)", norm)
        if ma_sv:
            slots["MaSV"] = ma_sv.group(1)

        ma_lhp = re.search(r"\b(lhp\d{9})\b", norm)
        if ma_lhp:
            slots["MaLHP"] = ma_lhp.group(1).upper()

        ma_mh = re.search(r"\b([a-z]{4}\d{6}e)\b", norm)
        if ma_mh:
            course = self.catalog.get_course(ma_mh.group(1).upper())
            if course:
                slots.update({"MaMH": course["MaMH"], "TenMH": course["TenMH"]})

        course = self.catalog.match_course(user_text, allow_fuzzy=False)
        if course is None:
            course_phrase = self._extract_entity_phrase(norm, "mon")
            if course_phrase:
                course = self.catalog.match_course(course_phrase, allow_fuzzy=True)
        if course:
            slots.update({"MaMH": course["MaMH"], "TenMH": course["TenMH"]})

        if self._should_match_major(norm):
            major = self.catalog.match_major(user_text, allow_fuzzy=False)
            if major is None:
                major_phrase = self._extract_entity_phrase(norm, "nganh")
                if major_phrase:
                    major = self.catalog.match_major(major_phrase, allow_fuzzy=True)
            if major:
                slots.update({"MaNganh": major["MaNganh"], "TenNganh": major["TenNganh"]})

        hoc_ky = self._extract_semester(norm)
        if hoc_ky is not None:
            slots["HocKy"] = hoc_ky

        nam_hoc = re.search(r"\b(20\d{2})\b", norm)
        if nam_hoc:
            slots["NamHoc"] = int(nam_hoc.group(1))

        group = re.search(r"\b(?:nhom|nhom lop|group)\s*0?([1-9]\d?)\b", norm)
        if group:
            slots["Nhom"] = f"{int(group.group(1)):02d}"

        thu = self._extract_weekday(norm)
        if thu is not None:
            slots["Thu"] = thu

        is_directional_sang = "doi sang" in norm or "chuyen sang" in norm
        if "buoi sang" in norm or "lop sang" in norm or (re.search(r"\bsang\b", norm) and not is_directional_sang):
            slots["Buoi"] = "SANG"
        if "buoi chieu" in norm or re.search(r"\bchieu\b", norm):
            slots["Buoi"] = "CHIEU"

        tiet_range = re.search(r"\btiet\s*(\d{1,2})(?:\s*(?:-|den|toi)\s*(\d{1,2}))?", norm)
        if tiet_range:
            slots["TietBD"] = int(tiet_range.group(1))
            if tiet_range.group(2):
                slots["TietKT"] = int(tiet_range.group(2))

        credits = re.search(r"\b([1-9])\s*(?:tin chi|tc)\b", norm)
        if credits:
            slots["SoTC"] = int(credits.group(1))

        room = re.search(r"\b([a-z]\d-\d{3}[a-z]?|f1-\d{3})\b", norm)
        if room:
            slots["MaPhong"] = room.group(1).upper()
        building = re.search(r"\b(a[2-5]|f1)\b", norm)
        if building and ("phong" in norm or "day" in norm or "nha" in norm):
            slots["DayNha"] = building.group(1).upper()

        if any(x in norm for x in ["con cho", "con slot", "dang ky duoc", "dang ki duoc", "dk duoc", "dk dc", "co the dang ky"]):
            slots["CoTheDangKy"] = 1
        if "het cho" in norm or "lop day" in norm or "da day" in norm or "full" in norm:
            slots["TrangThaiLHP"] = "DAY"
        if "dang mo" in norm or "lop mo" in norm or "trang thai mo" in norm:
            slots["TrangThaiLHP"] = "MO"
        if "lop dong" in norm or "da dong" in norm or "trang thai dong" in norm:
            slots["TrangThaiLHP"] = "DONG"
        if "lop huy" in norm or "bi huy" in norm or "trang thai huy" in norm:
            slots["TrangThaiLHP"] = "HUY"

        if "bat buoc" in norm:
            slots["LoaiYC"] = "BAT_BUOC"
        if "tu chon" in norm:
            slots["LoaiYC"] = "TU_CHON"

        if "khong dat" in norm or "chua dat" in norm or "rot" in norm or "truot" in norm:
            slots["KetQua"] = "KHONG_DAT"
        elif (re.search(r"\bdat\b", norm) or "qua mon" in norm or re.search(r"\bda qua\b", norm)) and not any(
            marker in norm for marker in ["qua mon nao", "can qua mon", "truoc khi hoc"]
        ):
            slots["KetQua"] = "DAT"

        if any(x in norm for x in ["mon nao yeu cau", "yeu cau hoc"]) and "truoc" in norm:
            slots["PrereqDirection"] = "REQUIRED_BY"
        elif any(
            x in norm
            for x in [
                "can hoc truoc",
                "tien quyet cua",
                "dieu kien tien quyet",
                "truoc khi hoc",
                "can qua mon",
                "thieu tien quyet",
                "thieu mon",
            ]
        ) or ("tien quyet" in norm and "mon nao yeu cau" not in norm):
            slots["PrereqDirection"] = "PREREQUISITES_OF"

        limit = self._extract_limit(norm)
        if limit is not None:
            slots["Limit"] = limit

        sort_by, sort_direction = self._extract_sort(norm)
        if sort_by:
            slots["SortBy"] = sort_by
            slots["SortDirection"] = sort_direction or slots.get("SortDirection", "ASC")

        return slots

    @staticmethod
    def _extract_semester(norm: str) -> Optional[int]:
        match = re.search(r"\b(?:hoc ky|hk|ky)\s*([1-8])\b", norm)
        if match:
            return int(match.group(1))
        if "ky nay" in norm:
            return 1
        return None

    @staticmethod
    def _should_match_major(norm: str) -> bool:
        if any(marker in norm for marker in ["nganh", "khoa", "ctdt", "chuong trinh"]):
            return True
        return any(re.search(rf"(?<![a-z0-9]){alias}(?![a-z0-9])", norm) for alias in ["cntt", "kmt", "cdt", "dtd", "dvt"])

    @staticmethod
    def _extract_entity_phrase(norm: str, marker: str) -> Optional[str]:
        stop_words = (
            " ky ",
            " hoc ky ",
            " hk ",
            " buoi ",
            " thu ",
            " tiet ",
            " con ",
            " khong ",
            " chua ",
            " can ",
            " co ",
            " nhom ",
            " may ",
            " bao nhieu ",
            " la ",
            " cho ",
            " cua ",
            " trong ",
            " nam ",
            " sap ",
        )
        match = re.search(rf"\b{marker}\s+(.+)$", norm)
        if not match:
            return None
        phrase = f" {match.group(1).strip()} "
        for stop in stop_words:
            idx = phrase.find(stop)
            if idx > 0:
                phrase = phrase[:idx]
                break
        phrase = phrase.strip()
        generic_phrases = {
            "nay",
            "do",
            "kia",
            "gi",
            "nao",
            "co",
            "cac",
            "nhung",
            "tat ca",
            "tu chon",
            "bat buoc",
            "nay can hoc truoc mon gi",
        }
        if phrase in generic_phrases:
            return None
        if not phrase or len(phrase) < 3:
            return None
        return phrase

    @staticmethod
    def _extract_weekday(norm: str) -> Optional[int]:
        match = re.search(r"\bthu\s*([2-7])\b", norm)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _extract_limit(norm: str) -> Optional[int]:
        match = re.search(r"\b(?:lay|top|chi hien|hien|gioi han)\s*(\d{1,3})\b", norm)
        if match:
            return max(1, min(int(match.group(1)), 200))
        if any(x in norm for x in ["mot ket qua", "dau tien", "nhieu nhat", "it nhat"]):
            return 1
        return None

    @staticmethod
    def _extract_sort(norm: str) -> Tuple[Optional[str], Optional[str]]:
        direction = "ASC"
        if any(x in norm for x in ["giam dan", "nhieu nhat", "cao nhat", "dong nhat"]):
            direction = "DESC"
        if any(x in norm for x in ["tang dan", "it nhat", "thap nhat"]):
            direction = "ASC"

        sort_map = [
            ("SoChoCon", ["cho con", "slot", "con lai"]),
            ("SiSoDK", ["si so", "dang ky nhieu", "nhieu sinh vien", "dong nhat"]),
            ("SoTC", ["tin chi"]),
            ("TenMH", ["ten mon", "mon hoc"]),
            ("Thu", ["thu trong tuan", "theo thu", "thu"]),
            ("TietBD", ["tiet"]),
            ("TGDK", ["thoi gian dang ky", "ngay dang ky"]),
        ]
        if "sap" not in norm and "nhieu nhat" not in norm and "it nhat" not in norm:
            return None, None
        for col, markers in sort_map:
            if any(marker in norm for marker in markers):
                return col, direction
        return None, direction

    def _detect_edit_operation(
        self,
        norm: str,
        previous: QueryContext,
        extracted_slots: Dict[str, Any],
    ) -> str:
        if previous.intent is None:
            return "NEW_QUERY"
        eligibility_markers = ["co dk duoc", "dk duoc", "dk dc", "dang ky duoc", "dang ki duoc", "co dang ky duoc"]
        has_eligibility_marker = any(x in norm for x in eligibility_markers)
        if has_eligibility_marker and self._has_reference(norm):
            return "RESOLVE_REFERENCE"
        if has_eligibility_marker and norm.startswith("sinh vien ") and not self._has_reference(norm):
            return "NEW_QUERY"
        if previous.intent == "REGISTRATION_ELIGIBILITY_CHECK" and has_eligibility_marker and any(
            slot in extracted_slots for slot in ["MaMH", "MaSV", "MaLHP"]
        ):
            return "CHANGE_ENTITY"
        if any(x in norm for x in ["tong tin chi", "bao nhieu tin chi da dang ky", "dang ky bao nhieu tin chi"]):
            if previous.intent != "STUDENT_RESULT_LOOKUP" and self._has_reference(norm):
                return "RESOLVE_REFERENCE"
            return "CHANGE_INTENT"
        if has_eligibility_marker and (
            "MaSV" in previous.slots or "MaSV" in extracted_slots or "MaLHP" in extracted_slots or "sinh vien" in norm
        ):
            return "CHANGE_INTENT"
        if any(x in norm for x in ["may tin chi", "so tin chi", "thong tin mon"]) and any(
            x in norm for x in ["doi qua", "doi sang", "chuyen sang"]
        ):
            return "CHANGE_INTENT"
        if previous.intent == "AGGREGATION_STATISTICS" and "liet ke" in norm and "lop" in norm:
            return "CHANGE_INTENT"
        if (
            "KetQua" in extracted_slots
            and "KetQua" in previous.slots
            and extracted_slots["KetQua"] != previous.slots.get("KetQua")
        ):
            return "REPLACE_FILTER"
        if any(x in norm for x in ["bo loc", "bo dieu kien", "khong can", "tat ca"]):
            return "REMOVE_FILTER"
        if any(x in norm for x in ["doi sang", "doi qua", "thay vi", "chuyen sang"]):
            if any(slot in extracted_slots for slot in ["MaMH", "MaSV", "MaLHP", "MaNganh"]):
                return "CHANGE_ENTITY"
            return "REPLACE_FILTER"
        if norm.startswith(("con ", "the ", "vay ", "mon ", "lop ")) and any(
            slot in extracted_slots for slot in ["MaMH", "MaSV", "MaLHP"]
        ):
            return "CHANGE_ENTITY"
        if self._has_reference(norm):
            return "RESOLVE_REFERENCE"
        if "sap" in norm:
            return "SORT"
        if "chi lay" in norm and any(x in norm for x in ["buoi", "thu ", "con cho", "dang ky duoc", "mo"]):
            return "ADD_FILTER"
        if previous.intent and any(x in norm for x in ["chi hoc ky", "chi xem hoc ky", "loc hoc ky"]):
            return "ADD_FILTER"
        if re.search(r"\b(?:lay|top|chi hien|hien|gioi han)\s*\d", norm) or "dau tien" in norm:
            return "LIMIT"
        if self._has_aggregation_marker(norm):
            return "AGGREGATE"
        if any(x in norm for x in ["chi lay", "loc", "them dieu kien", "con cho", "buoi", "thu "]):
            return "ADD_FILTER"
        return "NEW_QUERY"

    @staticmethod
    def _has_reference(norm: str) -> bool:
        after_reference = r"(?:$|\s+(?:co|thi|la|can|thuoc|may|bao|chua|khong|thieu|yeu|hoc|nam|nay|nua|nhe|gi|sao|dang))"
        reference_patterns = [
            r"\bmon nay\b",
            rf"\bmon do{after_reference}",
            r"\blop nay\b",
            rf"\blop do{after_reference}",
            r"\bsinh vien nay\b",
            rf"\bsinh vien do{after_reference}",
            r"\bban nay\b",
            rf"\bban do{after_reference}",
            r"\bnguoi nay\b",
            r"\bno\b",
        ]
        return any(re.search(pattern, norm) for pattern in reference_patterns)

    @staticmethod
    def _has_aggregation_marker(norm: str) -> bool:
        return bool(re.search(r"\bdem\b", norm)) or any(
            marker in norm
            for marker in [
                "thong ke",
                "moi mon",
                "bao nhieu",
                "may lop",
                "co may",
                "tong",
                "trung binh",
                "nhieu nhat",
                "it nhat",
            ]
        )

    @staticmethod
    def _has_schedule_marker(norm: str) -> bool:
        return bool(re.search(r"\btiet\s*\d", norm)) or any(
            marker in norm
            for marker in [
                "lich",
                "thu ",
                "buoi",
                "lop sang",
                "lop chieu",
                "phong",
                "ai day",
                "giang vien",
                "day lop",
            ]
        )

    @staticmethod
    def _remove_requested_filters(norm: str, slots: Dict[str, Any]) -> Dict[str, Any]:
        new_slots = dict(slots)
        filter_markers = {
            "Buoi": ["buoi", "sang", "chieu"],
            "Thu": ["thu"],
            "CoTheDangKy": ["con cho", "dang ky duoc"],
            "TrangThaiLHP": ["trang thai", "mo", "dong", "day", "huy"],
            "HocKy": ["hoc ky", "hk", "ky"],
            "SoTC": ["tin chi"],
            "Nhom": ["nhom"],
            "Limit": ["gioi han", "top", "lay"],
        }
        for slot, markers in filter_markers.items():
            if any(marker in norm for marker in markers):
                new_slots.pop(slot, None)
        if "tat ca" in norm:
            for slot in ["Buoi", "Thu", "CoTheDangKy", "TrangThaiLHP", "HocKy", "SoTC", "Nhom"]:
                new_slots.pop(slot, None)
        return new_slots

    @staticmethod
    def _keep_reusable_slots(slots: Dict[str, Any]) -> Dict[str, Any]:
        reusable = {
            "MaSV",
            "HoTen",
            "MaMH",
            "TenMH",
            "MaLHP",
            "PrereqDirection",
            "MaNganh",
            "TenNganh",
            "CoTheDangKy",
            "NamHoc",
            "HocKy",
            "Nhom",
        }
        return {k: v for k, v in slots.items() if k in reusable}

    def _detect_intent(
        self,
        norm: str,
        slots: Dict[str, Any],
        previous: QueryContext,
        edit_operation: str,
    ) -> str:
        if any(x in norm for x in ["du dieu kien", "co hoc duoc"]) or (
            any(x in norm for x in ["dang ky duoc", "dang ki duoc", "dk duoc", "dk dc", "co dang ky duoc", "co dk duoc"])
            and ("MaSV" in slots or "MaLHP" in slots or "sinh vien" in norm)
        ):
            return "REGISTRATION_ELIGIBILITY_CHECK"
        if "da dang ky" in norm or ("MaSV" in slots and "lich" in norm):
            return "STUDENT_REGISTRATION_LOOKUP"
        if previous.intent and edit_operation == "CHANGE_ENTITY":
            return previous.intent
        if "MaSV" in slots and any(
            x in norm
            for x in ["thong tin", "chuong trinh", "ctdt", "nganh nao", "khoa nao", "trang thai"]
        ):
            return "STUDENT_INFO_LOOKUP"
        if any(
            x in norm
            for x in [
                "tien quyet",
                "hoc truoc",
                "can hoc truoc",
                "thieu mon",
                "mon nao yeu cau",
                "truoc khi hoc",
                "can qua mon",
            ]
        ) or (
            "yeu cau hoc" in norm and "truoc" in norm
        ):
            return "PREREQUISITE_LOOKUP"
        if any(x in norm for x in ["tong tin chi", "bao nhieu tin chi da dang ky", "dang ky bao nhieu tin chi"]):
            return "CREDIT_SUMMARY"
        if any(x in norm for x in ["ket qua", "da dat", "chua dat", "da qua", "rot", "truot", "qua mon"]):
            return "STUDENT_RESULT_LOOKUP"
        if any(x in norm for x in ["chuong trinh", "ctdt", "nganh", "bat buoc", "tu chon"]) and "MaNganh" in slots:
            return "CURRICULUM_COURSE_SEARCH"
        if any(x in norm for x in ["may tin chi", "so tin chi", "thuoc nganh", "thong tin mon"]):
            return "COURSE_INFO_SEARCH"
        if any(x in norm for x in ["liet ke lop", "liet ke cac lop", "tim lop", "cho toi xem cac lop", "xem cac lop", "lop hoc phan", "lop mon"]):
            if self._has_schedule_marker(norm):
                return "COURSE_SCHEDULE_SEARCH"
            if not (
                re.search(r"\bdem\b", norm)
                or any(x in norm for x in ["bao nhieu", "may lop", "co may", "trung binh", "nhieu nhat", "it nhat"])
            ):
                return "COURSE_OFFERING_SEARCH"
        if self._has_aggregation_marker(norm):
            return "AGGREGATION_STATISTICS"
        if self._has_schedule_marker(norm):
            return "COURSE_SCHEDULE_SEARCH"
        if previous.intent and edit_operation in {
            "ADD_FILTER",
            "REMOVE_FILTER",
            "REPLACE_FILTER",
            "CHANGE_ENTITY",
            "SORT",
            "LIMIT",
            "RESOLVE_REFERENCE",
        }:
            return previous.intent
        return "COURSE_OFFERING_SEARCH"

    def _execute_intent(
        self,
        user_text: str,
        intent: str,
        slots: Dict[str, Any],
        edit_operation: str,
        parser_source: str = "rule",
        parser_warning: Optional[str] = None,
    ) -> QueryResult:
        warnings: List[str] = []
        if parser_warning:
            warnings.append(f"Parser fallback: {parser_warning}")
        if intent == "REGISTRATION_ELIGIBILITY_CHECK":
            df, sql, params, message = self._execute_eligibility(slots)
        elif intent == "STUDENT_INFO_LOOKUP":
            df, sql, params, message = self._execute_student_info(slots)
        elif intent == "PREREQUISITE_LOOKUP":
            df, sql, params, message = self._execute_prerequisite(slots)
        elif intent == "STUDENT_REGISTRATION_LOOKUP":
            df, sql, params, message = self._execute_student_registrations(slots)
        elif intent == "STUDENT_RESULT_LOOKUP":
            df, sql, params, message = self._execute_student_results(slots)
        elif intent == "CREDIT_SUMMARY":
            df, sql, params, message = self._execute_credit_summary(slots)
        elif intent == "COURSE_INFO_SEARCH":
            df, sql, params, message = self._execute_course_info(slots)
        elif intent == "CURRICULUM_COURSE_SEARCH":
            df, sql, params, message = self._execute_curriculum(slots)
        elif intent == "COURSE_SCHEDULE_SEARCH":
            df, sql, params, message = self._execute_schedule(slots)
        elif intent == "AGGREGATION_STATISTICS":
            df, sql, params, message = self._execute_statistics(slots, normalize_text(user_text))
        else:
            df, sql, params, message = self._execute_offering_search(slots)

        if df.empty:
            warnings.append("Không có dòng phù hợp với câu hỏi hiện tại.")
        return QueryResult(
            user_text=user_text,
            intent=intent,
            edit_operation=edit_operation,
            slots=slots,
            sql=sql,
            params=params,
            dataframe=df,
            message=message,
            warnings=warnings,
            parser_source=parser_source,
            parser_warning=parser_warning,
        )

    def _execute_sql(
        self,
        sql: str,
        params: Dict[str, Any],
        limit: Optional[int] = None,
    ) -> pd.DataFrame:
        final_sql = sql.strip()
        if limit and " limit " not in normalize_text(final_sql):
            final_sql += f"\nLIMIT {int(limit)}"
        rows = self.conn.execute(final_sql, params).fetchall()
        return dataframe_from_rows(rows)

    def _execute_offering_search(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        where, params, needs_lich = self._offering_filters(slots)
        view = "v_lop_hoc_phan_lich" if needs_lich else "v_lop_hoc_phan_day_du"
        columns = (
            "MaLHP, TenMH, Nhom, SoTC, NamHoc, HocKy, TrangThaiLHP, "
            "SiSoDK, SiSoTD, SoChoCon, LichHocText, TenGV"
        )
        if needs_lich:
            columns = (
                "MaLHP, TenMH, Nhom, SoTC, NamHoc, HocKy, ThuText, TietText, "
                "Buoi, MaPhong, TrangThaiLHP, SoChoCon, TenGV"
            )
        sql = f"SELECT DISTINCT {columns}\nFROM {view}\n{where}\n{self._order_clause(slots, view)}"
        df = self._execute_sql(sql, params, slots.get("Limit", 50))
        return df, sql, params, self._summary_message(df, "lớp học phần")

    def _execute_schedule(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        where, params, _needs_lich = self._offering_filters(slots, force_schedule=True)
        sql = (
            "SELECT DISTINCT MaLHP, TenMH, Nhom, ThuText, TietText, Buoi, MaPhong, "
            "TenGV, TrangThaiLHP, SoChoCon\n"
            "FROM v_lop_hoc_phan_lich\n"
            f"{where}\n"
            f"{self._order_clause(slots, 'v_lop_hoc_phan_lich')}"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 80))
        return df, sql, params, self._summary_message(df, "buổi học")

    def _execute_course_info(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        conditions = []
        params: Dict[str, Any] = {}
        if "MaMH" in slots:
            conditions.append("MaMH = :ma_mh")
            params["ma_mh"] = slots["MaMH"]
        if "SoTC" in slots:
            conditions.append("SoTC = :so_tc")
            params["so_tc"] = slots["SoTC"]
        if "MaNganh" in slots:
            conditions.append("MaNganh = :ma_nganh")
            params["ma_nganh"] = slots["MaNganh"]
        if "LoaiYC" in slots:
            conditions.append("LoaiYC = :loai_yc")
            params["loai_yc"] = slots["LoaiYC"]
        if "HocKy" in slots:
            conditions.append("HKGoiY = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        where = self._where_clause(conditions)
        sql = (
            "SELECT DISTINCT MaMH, TenMH, SoTC, TenNganh, LoaiYC, HKGoiY\n"
            "FROM v_mon_hoc_ctdt\n"
            f"{where}\n"
            "ORDER BY HKGoiY, TenMH"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 80))
        return df, sql, params, self._summary_message(df, "môn học")

    def _execute_student_info(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        conditions = []
        params: Dict[str, Any] = {}
        if "MaSV" in slots:
            conditions.append("MaSV = :ma_sv")
            params["ma_sv"] = slots["MaSV"]
        if "MaNganh" in slots:
            conditions.append("MaNganh = :ma_nganh")
            params["ma_nganh"] = slots["MaNganh"]
        sql = (
            "SELECT MaSV, HoTen, TrangThaiSV, MaKhoaHoc, TenKhoaHoc, MaCTDT, "
            "TenCTDT, MaNganh, TenNganh\n"
            "FROM v_sinh_vien_day_du\n"
            f"{self._where_clause(conditions)}\n"
            "ORDER BY MaSV"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 50))
        return df, sql, params, self._summary_message(df, "sinh viên")

    def _execute_curriculum(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        conditions = []
        params: Dict[str, Any] = {}
        join_student = False
        if "MaSV" in slots:
            join_student = True
            conditions.append("sv.MaSV = :ma_sv")
            params["ma_sv"] = slots["MaSV"]
        if "MaNganh" in slots:
            conditions.append("mh.MaNganh = :ma_nganh")
            params["ma_nganh"] = slots["MaNganh"]
        if "LoaiYC" in slots:
            conditions.append("mh.LoaiYC = :loai_yc")
            params["loai_yc"] = slots["LoaiYC"]
        if "HocKy" in slots:
            conditions.append("mh.HKGoiY = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        from_clause = "v_mon_hoc_ctdt mh"
        if join_student:
            from_clause += "\nJOIN v_sinh_vien_day_du sv ON mh.MaCTDT = sv.MaCTDT"
        sql = (
            "SELECT DISTINCT mh.MaMH, mh.TenMH, mh.SoTC, mh.TenNganh, mh.LoaiYC, mh.HKGoiY\n"
            f"FROM {from_clause}\n"
            f"{self._where_clause(conditions)}\n"
            "ORDER BY mh.HKGoiY, mh.TenMH"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 100))
        return df, sql, params, self._summary_message(df, "môn trong chương trình")

    def _execute_prerequisite(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        params: Dict[str, Any] = {}
        if "MaSV" in slots and "MaMH" in slots:
            sql = (
                "SELECT tq.MaMH, tq.TenMH, tq.MaMHTQ, tq.TenMHTQ\n"
                "FROM v_tien_quyet_day_du tq\n"
                "LEFT JOIN KetQua kq ON kq.MaSV = :ma_sv AND kq.MaMH = tq.MaMHTQ AND kq.KetQua = 'DAT'\n"
                "WHERE tq.MaMH = :ma_mh AND kq.MaMH IS NULL\n"
                "ORDER BY tq.MaMHTQ"
            )
            params = {"ma_sv": slots["MaSV"], "ma_mh": slots["MaMH"]}
            label = "môn tiên quyết còn thiếu"
        elif "MaMH" in slots:
            direction = slots.get("PrereqDirection")
            if direction == "REQUIRED_BY":
                sql = (
                    "SELECT MaMH, TenMH, MaMHTQ, TenMHTQ\n"
                    "FROM v_tien_quyet_day_du\n"
                    "WHERE MaMHTQ = :ma_mh\n"
                    "ORDER BY TenMH"
                )
            elif direction == "PREREQUISITES_OF":
                sql = (
                    "SELECT MaMH, TenMH, MaMHTQ, TenMHTQ\n"
                    "FROM v_tien_quyet_day_du\n"
                    "WHERE MaMH = :ma_mh\n"
                    "ORDER BY TenMHTQ"
                )
            else:
                sql = (
                    "SELECT MaMH, TenMH, MaMHTQ, TenMHTQ\n"
                    "FROM v_tien_quyet_day_du\n"
                    "WHERE MaMH = :ma_mh OR MaMHTQ = :ma_mh\n"
                    "ORDER BY TenMH"
                )
            params = {"ma_mh": slots["MaMH"]}
            label = "quan hệ tiên quyết"
        else:
            sql = (
                "SELECT MaMH, TenMH, MaMHTQ, TenMHTQ\n"
                "FROM v_tien_quyet_day_du\n"
                "ORDER BY TenMH"
            )
            label = "quan hệ tiên quyết"
        df = self._execute_sql(sql, params, slots.get("Limit", 80))
        return df, sql, params, self._summary_message(df, label)

    def _execute_student_registrations(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        conditions = []
        params: Dict[str, Any] = {}
        if "MaSV" in slots:
            conditions.append("MaSV = :ma_sv")
            params["ma_sv"] = slots["MaSV"]
        if "MaMH" in slots:
            conditions.append("MaMH = :ma_mh")
            params["ma_mh"] = slots["MaMH"]
        if "MaLHP" in slots:
            conditions.append("MaLHP = :ma_lhp")
            params["ma_lhp"] = slots["MaLHP"]
        if "HocKy" in slots:
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        if "NamHoc" in slots:
            conditions.append("NamHoc = :nam_hoc")
            params["nam_hoc"] = slots["NamHoc"]
        if "Buoi" in slots:
            conditions.append("BuoiText LIKE :buoi")
            params["buoi"] = f"%{slots['Buoi']}%"
        sql = (
            "SELECT MaSV, HoTen, MaLHP, TenMH, Nhom, SoTC, NamHoc, HocKy, "
            "LichHocText, TenGV, TGDK\n"
            "FROM v_dang_ky_day_du\n"
            f"{self._where_clause(conditions)}\n"
            f"{self._order_clause(slots, 'v_dang_ky_day_du')}"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 100))
        return df, sql, params, self._summary_message(df, "lớp đã đăng ký")

    def _execute_student_results(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        conditions = []
        params: Dict[str, Any] = {}
        if "MaSV" in slots:
            conditions.append("MaSV = :ma_sv")
            params["ma_sv"] = slots["MaSV"]
        if "MaMH" in slots:
            conditions.append("MaMH = :ma_mh")
            params["ma_mh"] = slots["MaMH"]
        if "KetQua" in slots:
            conditions.append("KetQua = :ket_qua")
            params["ket_qua"] = slots["KetQua"]
        if "HocKy" in slots:
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        if "NamHoc" in slots:
            conditions.append("NamHoc = :nam_hoc")
            params["nam_hoc"] = slots["NamHoc"]
        sql = (
            "SELECT MaSV, HoTen, MaMH, TenMH, SoTC, NamHoc, HocKy, KetQua\n"
            "FROM v_ket_qua_day_du\n"
            f"{self._where_clause(conditions)}\n"
            f"{self._order_clause(slots, 'v_ket_qua_day_du')}"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 100))
        return df, sql, params, self._summary_message(df, "kết quả học tập")

    def _execute_credit_summary(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        conditions = []
        params: Dict[str, Any] = {}
        if "MaSV" in slots:
            conditions.append("MaSV = :ma_sv")
            params["ma_sv"] = slots["MaSV"]
        if "MaNganh" in slots:
            conditions.append("MaNganh = :ma_nganh")
            params["ma_nganh"] = slots["MaNganh"]
        if "HocKy" in slots:
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        if "NamHoc" in slots:
            conditions.append("NamHoc = :nam_hoc")
            params["nam_hoc"] = slots["NamHoc"]
        sql = (
            "SELECT MaSV, HoTen, TenNganh, NamHoc, HocKy, SoLopDaDangKy, "
            "SoMonDaDangKy, TongTinChiDangKy\n"
            "FROM v_tin_chi_dang_ky_sv\n"
            f"{self._where_clause(conditions)}\n"
            f"{self._order_clause(slots, 'v_tin_chi_dang_ky_sv')}"
        )
        df = self._execute_sql(sql, params, slots.get("Limit", 100))
        return df, sql, params, self._summary_message(df, "dòng tổng hợp tín chỉ")

    def _execute_eligibility(self, slots: Dict[str, Any]) -> Tuple[pd.DataFrame, Optional[str], Dict[str, Any], str]:
        ma_sv = slots.get("MaSV")
        ma_lhp = slots.get("MaLHP")
        ma_mh = slots.get("MaMH")
        params: Dict[str, Any] = {}
        if not ma_sv:
            return pd.DataFrame(), None, params, "Cần mã sinh viên để kiểm tra điều kiện đăng ký."
        if ma_lhp:
            result = check_registration_eligibility(
                self.conn,
                ma_sv=ma_sv,
                ma_lhp=ma_lhp,
                max_credits=MAX_CREDITS_PER_SEMESTER,
            )
            row = self._flatten_eligibility_row(result)
            df = pd.DataFrame([row])
            sql = "-- business_rules.check_registration_eligibility(:ma_sv, :ma_lhp)"
            params = {"ma_sv": ma_sv, "ma_lhp": ma_lhp}
            return df, sql, params, self._eligibility_message(df)
        if ma_mh:
            eligible = find_eligible_offerings_for_course(
                self.conn,
                ma_sv=ma_sv,
                ma_mh=ma_mh,
                nam_hoc=slots.get("NamHoc"),
                hoc_ky=slots.get("HocKy"),
                max_credits=MAX_CREDITS_PER_SEMESTER,
            )
            rows = eligible
            message = self._summary_message(pd.DataFrame(rows), "lớp có thể đăng ký")
            if not rows:
                candidate_sql = (
                    "SELECT MaLHP\n"
                    "FROM v_lop_hoc_phan_day_du\n"
                    "WHERE MaMH = :ma_mh\n"
                    + ("AND NamHoc = :nam_hoc\n" if slots.get("NamHoc") else "")
                    + ("AND HocKy = :hoc_ky\n" if slots.get("HocKy") else "")
                    + "ORDER BY HocKy, Nhom"
                )
                candidate_params: Dict[str, Any] = {"ma_mh": ma_mh}
                if slots.get("NamHoc"):
                    candidate_params["nam_hoc"] = slots["NamHoc"]
                if slots.get("HocKy"):
                    candidate_params["hoc_ky"] = slots["HocKy"]
                candidates = self.conn.execute(candidate_sql, candidate_params).fetchall()
                rows = [
                    check_registration_eligibility(
                        self.conn,
                        ma_sv=ma_sv,
                        ma_lhp=row["MaLHP"],
                        max_credits=MAX_CREDITS_PER_SEMESTER,
                    )
                    for row in candidates
                ]
                message = "Không có lớp đủ điều kiện; bảng dưới đây liệt kê lý do theo từng lớp."
            df = pd.DataFrame([self._flatten_eligibility_row(row) for row in rows])
            sql = "-- business_rules.find_eligible_offerings_for_course(:ma_sv, :ma_mh)"
            params = {"ma_sv": ma_sv, "ma_mh": ma_mh}
            if slots.get("HocKy"):
                params["hoc_ky"] = slots["HocKy"]
            return df, sql, params, message
        return pd.DataFrame(), None, params, "Cần mã lớp học phần hoặc môn học để kiểm tra đăng ký."

    @staticmethod
    def _flatten_eligibility_row(row: Dict[str, Any]) -> Dict[str, Any]:
        keys = [
            "MaSV",
            "HoTen",
            "TrangThaiSV",
            "MaLHP",
            "MaMH",
            "TenMH",
            "Nhom",
            "NamHoc",
            "HocKy",
            "SoTC",
            "TrangThaiLHP",
            "SiSoDK",
            "SiSoTD",
            "SoChoCon",
            "TinChiHienTai",
            "TinChiSauDangKy",
            "SoMonTienQuyetThieu",
            "SoLopTrungLich",
            "SoLopCungMonDaDangKy",
            "CoTheDangKy",
            "LyDoKhongDangKy",
        ]
        flat = {key: row.get(key) for key in keys}
        reasons = flat.get("LyDoKhongDangKy")
        if isinstance(reasons, list):
            flat["LyDoKhongDangKy"] = ", ".join(reasons)
        return flat

    @staticmethod
    def _eligibility_message(df: pd.DataFrame) -> str:
        if df.empty:
            return "Không tìm thấy lớp có thể đăng ký."
        value = int(df.iloc[0].get("CoTheDangKy", 0))
        if value == 1:
            return "Sinh viên có thể đăng ký lớp này."
        reasons = df.iloc[0].get("LyDoKhongDangKy") or "không thỏa điều kiện"
        return f"Sinh viên chưa đăng ký được lớp này: {reasons}."

    def _execute_statistics(
        self,
        slots: Dict[str, Any],
        norm: str,
    ) -> Tuple[pd.DataFrame, str, Dict[str, Any], str]:
        if "tin chi" in norm and "trung binh" in norm:
            sql = (
                "SELECT NamHoc, HocKy, ROUND(AVG(TongTinChiDangKy), 2) AS TinChiTrungBinh\n"
                "FROM v_tin_chi_dang_ky_sv\n"
                "GROUP BY NamHoc, HocKy\n"
                "ORDER BY NamHoc, HocKy"
            )
            params: Dict[str, Any] = {}
            df = self._execute_sql(sql, params, slots.get("Limit", 20))
            return df, sql, params, self._summary_message(df, "dòng thống kê")

        if "sinh vien" in norm and "dang ky" in norm:
            conditions = []
            params: Dict[str, Any] = {}
            if "MaMH" in slots:
                conditions.append("MaMH = :ma_mh")
                params["ma_mh"] = slots["MaMH"]
            if "HocKy" in slots:
                conditions.append("HocKy = :hoc_ky")
                params["hoc_ky"] = slots["HocKy"]
            if "NamHoc" in slots:
                conditions.append("NamHoc = :nam_hoc")
                params["nam_hoc"] = slots["NamHoc"]
            sql = (
                "SELECT MaMH, TenMH, COUNT(DISTINCT MaSV) AS SoSinhVienDangKy\n"
                "FROM v_dang_ky_day_du\n"
                f"{self._where_clause(conditions)}\n"
                "GROUP BY MaMH, TenMH\n"
                "ORDER BY SoSinhVienDangKy DESC, TenMH"
            )
            default_limit = 1 if "nhieu nhat" in norm or "it nhat" in norm else 20
            if "it nhat" in norm:
                sql = sql.replace("ORDER BY SoSinhVienDangKy DESC, TenMH", "ORDER BY SoSinhVienDangKy ASC, TenMH")
            df = self._execute_sql(sql, params, slots.get("Limit", default_limit))
            return df, sql, params, self._summary_message(df, "dòng thống kê")

        if "sinh vien" in norm and ("nhieu nhat" in norm or "tin chi" in norm):
            sql = (
                "SELECT MaSV, HoTen, NamHoc, HocKy, TongTinChiDangKy\n"
                "FROM v_tin_chi_dang_ky_sv\n"
                "ORDER BY TongTinChiDangKy DESC, MaSV ASC"
            )
            params = {}
            df = self._execute_sql(sql, params, slots.get("Limit", 10))
            return df, sql, params, self._summary_message(df, "sinh viên")

        if "rot" in norm or "khong dat" in norm:
            conditions = ["KetQua = 'KHONG_DAT'"]
            params = {}
            if "MaMH" in slots:
                conditions.append("MaMH = :ma_mh")
                params["ma_mh"] = slots["MaMH"]
            sql = (
                "SELECT MaMH, TenMH, COUNT(DISTINCT MaSV) AS SoSinhVienKhongDat\n"
                "FROM v_ket_qua_day_du\n"
                f"{self._where_clause(conditions)}\n"
                "GROUP BY MaMH, TenMH\n"
                "ORDER BY SoSinhVienKhongDat DESC, TenMH"
            )
            df = self._execute_sql(sql, params, slots.get("Limit", 20))
            return df, sql, params, self._summary_message(df, "dòng thống kê")

        if "con cho" in norm:
            sql = (
                "SELECT MaMH, TenMH, COUNT(*) AS SoLopConCho, SUM(SoChoCon) AS TongSoChoCon\n"
                "FROM v_lop_hoc_phan_day_du\n"
                "WHERE CoTheDangKy = 1\n"
                "GROUP BY MaMH, TenMH\n"
                "ORDER BY TongSoChoCon DESC, TenMH"
            )
            params = {}
            df = self._execute_sql(sql, params, slots.get("Limit", 20))
            return df, sql, params, self._summary_message(df, "dòng thống kê")

        if "lop" in norm or "MaMH" in slots or "HocKy" in slots or "Buoi" in slots or "Thu" in slots:
            if "moi mon" in norm or "theo tung mon" in norm or "tung mon" in norm or "MaMH" not in slots:
                conditions = []
                params = {}
                if "HocKy" in slots:
                    conditions.append("HocKy = :hoc_ky")
                    params["hoc_ky"] = slots["HocKy"]
                if "NamHoc" in slots:
                    conditions.append("NamHoc = :nam_hoc")
                    params["nam_hoc"] = slots["NamHoc"]
                if slots.get("CoTheDangKy") == 1:
                    conditions.append("CoTheDangKy = 1")
                sql = (
                    "SELECT MaMH, TenMH, COUNT(DISTINCT MaLHP) AS SoLopHocPhan\n"
                    "FROM v_lop_hoc_phan_day_du\n"
                    f"{self._where_clause(conditions)}\n"
                    "GROUP BY MaMH, TenMH\n"
                    "ORDER BY SoLopHocPhan DESC, TenMH"
                )
                df = self._execute_sql(sql, params, slots.get("Limit", 40))
            else:
                where, params, needs_lich = self._offering_filters(slots)
                view = "v_lop_hoc_phan_lich" if needs_lich else "v_lop_hoc_phan_day_du"
                sql = (
                    "SELECT MaMH, TenMH, COUNT(DISTINCT MaLHP) AS SoLopHocPhan\n"
                    f"FROM {view}\n"
                    f"{where}\n"
                    "GROUP BY MaMH, TenMH\n"
                    "ORDER BY TenMH"
                )
                df = self._execute_sql(sql, params, slots.get("Limit", 20))
            return df, sql, params, self._summary_message(df, "dòng thống kê")

        sql = (
            "SELECT MaMH, TenMH, COUNT(*) AS SoLopHocPhan\n"
            "FROM v_lop_hoc_phan_day_du\n"
            "GROUP BY MaMH, TenMH\n"
            "ORDER BY SoLopHocPhan DESC, TenMH"
        )
        params = {}
        df = self._execute_sql(sql, params, slots.get("Limit", 40))
        return df, sql, params, self._summary_message(df, "dòng thống kê")

    def _offering_filters(
        self,
        slots: Dict[str, Any],
        force_schedule: bool = False,
    ) -> Tuple[str, Dict[str, Any], bool]:
        conditions = []
        params: Dict[str, Any] = {}
        needs_lich = force_schedule
        if "MaMH" in slots:
            conditions.append("MaMH = :ma_mh")
            params["ma_mh"] = slots["MaMH"]
        if "MaLHP" in slots:
            conditions.append("MaLHP = :ma_lhp")
            params["ma_lhp"] = slots["MaLHP"]
        if "HocKy" in slots:
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        if "NamHoc" in slots:
            conditions.append("NamHoc = :nam_hoc")
            params["nam_hoc"] = slots["NamHoc"]
        if "Nhom" in slots:
            conditions.append("Nhom = :nhom")
            params["nhom"] = slots["Nhom"]
        if "SoTC" in slots:
            conditions.append("SoTC = :so_tc")
            params["so_tc"] = slots["SoTC"]
        if "TrangThaiLHP" in slots:
            conditions.append("TrangThaiLHP = :trang_thai")
            params["trang_thai"] = slots["TrangThaiLHP"]
        if slots.get("CoTheDangKy") == 1:
            conditions.append("CoTheDangKy = 1")
        if "Thu" in slots:
            needs_lich = True
            conditions.append("Thu = :thu")
            params["thu"] = slots["Thu"]
        if "Buoi" in slots:
            needs_lich = True
            conditions.append("Buoi = :buoi")
            params["buoi"] = slots["Buoi"]
        if "TietBD" in slots:
            needs_lich = True
            conditions.append("TietBD <= :tiet_bd")
            params["tiet_bd"] = slots["TietBD"]
        if "TietKT" in slots:
            needs_lich = True
            conditions.append("TietKT >= :tiet_kt")
            params["tiet_kt"] = slots["TietKT"]
        if "MaPhong" in slots:
            needs_lich = True
            conditions.append("MaPhong = :ma_phong")
            params["ma_phong"] = slots["MaPhong"]
        if "DayNha" in slots:
            needs_lich = True
            conditions.append("DayNha = :day_nha")
            params["day_nha"] = slots["DayNha"]
        return self._where_clause(conditions), params, needs_lich

    @staticmethod
    def _where_clause(conditions: Sequence[str]) -> str:
        if not conditions:
            return ""
        return "WHERE " + " AND ".join(conditions)

    @staticmethod
    def _order_clause(slots: Dict[str, Any], view: str) -> str:
        requested = slots.get("SortBy")
        direction = slots.get("SortDirection", "ASC")
        direction = "DESC" if direction == "DESC" else "ASC"
        allowed = {
            "v_lop_hoc_phan_day_du": {
                "SoChoCon",
                "SiSoDK",
                "SoTC",
                "TenMH",
                "MaLHP",
                "HocKy",
            },
            "v_lop_hoc_phan_lich": {
                "Thu",
                "TietBD",
                "SoChoCon",
                "SiSoDK",
                "SoTC",
                "TenMH",
                "MaLHP",
            },
            "v_dang_ky_day_du": {"TGDK", "TenMH", "SoTC", "HocKy", "MaLHP"},
            "v_ket_qua_day_du": {"TenMH", "SoTC", "HocKy", "NamHoc"},
            "v_tin_chi_dang_ky_sv": {"TongTinChiDangKy", "SoLopDaDangKy", "HocKy", "MaSV"},
        }
        if requested in allowed.get(view, set()):
            return f"ORDER BY {requested} {direction}"
        if view == "v_lop_hoc_phan_lich":
            return "ORDER BY Thu, TietBD, TenMH, Nhom"
        if view == "v_dang_ky_day_du":
            return "ORDER BY HocKy, TenMH, Nhom"
        if view == "v_ket_qua_day_du":
            return "ORDER BY NamHoc, HocKy, TenMH"
        if view == "v_tin_chi_dang_ky_sv":
            return "ORDER BY NamHoc, HocKy, MaSV"
        return "ORDER BY TenMH, HocKy, Nhom"

    @staticmethod
    def _summary_message(df: pd.DataFrame, label: str) -> str:
        count = len(df)
        if count == 0:
            return f"Không tìm thấy {label} phù hợp."
        return f"Tìm thấy {count} {label} phù hợp."


COURSE_ALIASES: Dict[str, List[str]] = {
    "INPR130185E": ["nhap mon lap trinh", "lap trinh co ban", "introduction to programming", "inpr"],
    "CALC140101E": ["giai tich", "calculus", "calc"],
    "LIAL140102E": ["dai so tuyen tinh", "linear algebra", "lial"],
    "ACEN140103E": ["tieng anh hoc thuat", "academic english", "anh van", "acen"],
    "PHYS140104E": ["vat ly ky thuat", "engineering physics", "phys"],
    "DASA230179E": ["cau truc du lieu va giai thuat", "ctdlgt", "ctdl", "data structures and algorithms", "dsa"],
    "OOPR230279E": ["lap trinh huong doi tuong", "oop", "object oriented programming"],
    "PROS220301E": ["xac suat thong ke", "probability and statistics", "pros"],
    "DISM230302E": ["toan roi rac", "discrete mathematics", "dism"],
    "DBSY230184E": ["co so du lieu", "csdl", "database systems", "database", "dbsy"],
    "COAR230280E": ["kien truc may tinh", "computer architecture", "coar"],
    "OSYS330281E": ["he dieu hanh", "operating systems", "os", "osys"],
    "NECO330282E": ["mang may tinh", "computer networks", "network", "neco"],
    "DBMS330284E": ["quan tri co so du lieu", "dbms", "database management systems", "quan tri csdl"],
    "WEPR330383E": ["lap trinh web", "web programming", "web", "wepr"],
    "SOEN330384E": ["cong nghe phan mem", "software engineering", "se", "soen"],
    "ARIN330585E": ["tri tue nhan tao", "ai", "artificial intelligence", "arin"],
    "INDS331085E": ["nhap mon khoa hoc du lieu", "data science", "khoa hoc du lieu", "inds"],
    "MALE431085E": ["hoc may", "machine learning", "ml", "male"],
    "NLPR431585E": ["xu ly ngon ngu tu nhien", "nlp", "nlpr", "natural language processing"],
    "DIPR430685E": ["xu ly anh so", "digital image processing", "dip", "dipr"],
    "MOPR331279E": ["lap trinh di dong", "mobile programming", "mobile", "mopr"],
    "CYSE430387E": ["an toan thong tin", "an ninh mang", "cybersecurity", "cyse"],
    "CLCO430986E": ["dien toan dam may", "cloud computing", "cloud", "clco"],
    "DAEN431188E": ["ky thuat du lieu", "data engineering", "daen"],
    "GRPR421201E": ["do an tot nghiep", "graduation project", "grpr"],
    "CIRC130401E": ["mach dien", "electric circuits", "circ"],
    "ELDE230402E": ["linh kien dien tu", "electronic devices", "elde"],
    "DIEL330403E": ["dien tu so", "digital electronics", "diel"],
    "SIGN330404E": ["tin hieu va he thong", "signals and systems", "sign"],
    "COMM430405E": ["he thong truyen thong", "communication systems", "comm"],
    "EMBE330406E": ["he thong nhung", "embedded systems", "embe"],
    "IOTP431486E": ["lap trinh iot", "iot programming", "iot", "iotp"],
    "MECH130501E": ["co ky thuat", "engineering mechanics", "mech"],
    "CAME230502E": ["cad cam", "cad/cam engineering", "came"],
    "ROBO330503E": ["robotics", "robot", "robo"],
    "MACH330504E": ["chi tiet may", "machine elements", "mach"],
    "CONT330601E": ["ly thuyet dieu khien", "control theory", "cont"],
    "PLCS330602E": ["plc", "plc systems", "plcs"],
    "AUTO430603E": ["he thong tu dong hoa", "automation systems", "auto"],
}


MAJOR_ALIASES: Dict[str, List[str]] = {
    "10": ["cntt", "cong nghe thong tin", "it"],
    "19": ["kmt", "ky thuat may tinh", "cong nghe ky thuat may tinh", "may tinh"],
    "46": ["cdt", "co dien tu", "cong nghe ky thuat co dien tu", "mechatronics"],
    "51": ["dtd", "tu dong hoa", "dieu khien va tu dong hoa", "automation"],
    "41": ["dvt", "dien tu truyen thong", "dien tu vien thong", "electronics"],
}
