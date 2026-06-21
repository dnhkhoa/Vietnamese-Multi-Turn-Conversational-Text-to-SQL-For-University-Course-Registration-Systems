from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


SYSTEM_PROMPT = (
    "Ban la bo phan tich state cho bai toan Vietnamese multi-turn text-to-SQL "
    "trong he thong dang ky mon hoc. Chi tra JSON hop le gom intent, edit_operation, slots."
)

ALLOWED_INTENTS = {
    "COURSE_OFFERING_SEARCH",
    "COURSE_SCHEDULE_SEARCH",
    "COURSE_INFO_SEARCH",
    "CURRICULUM_COURSE_SEARCH",
    "STUDENT_INFO_LOOKUP",
    "ACADEMIC_PROFILE_LOOKUP",
    "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_RESULT_LOOKUP",
    "CREDIT_SUMMARY",
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
    "ACADEMIC_PROFILE": "ACADEMIC_PROFILE_LOOKUP",
    "ACADEMIC_PROGRESS": "ACADEMIC_PROFILE_LOOKUP",
    "ACADEMIC_WARNING": "ACADEMIC_PROFILE_LOOKUP",
    "STUDENT_ACADEMIC_PROFILE": "ACADEMIC_PROFILE_LOOKUP",
    "STUDENT_PROGRESS": "ACADEMIC_PROFILE_LOOKUP",
    "STUDENT_WARNING": "ACADEMIC_PROFILE_LOOKUP",
    "STUDENT_REGISTRATIONS": "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_REGISTRATION": "STUDENT_REGISTRATION_LOOKUP",
    "VIEW_STUDENT_REGISTRATION": "STUDENT_REGISTRATION_LOOKUP",
    "VIEW_STUDENT_REGISTRATIONS": "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_RESULTS": "STUDENT_RESULT_LOOKUP",
    "STUDENT_RESULT": "STUDENT_RESULT_LOOKUP",
    "CHECK_REGISTRATION": "REGISTRATION_ELIGIBILITY_CHECK",
    "CHECK_COURSE_REGISTRATION": "REGISTRATION_ELIGIBILITY_CHECK",
    "REGISTRATION_CHECK": "REGISTRATION_ELIGIBILITY_CHECK",
    "REGISTRATION_ELIGIBILITY": "REGISTRATION_ELIGIBILITY_CHECK",
    "ELIGIBILITY_CHECK": "REGISTRATION_ELIGIBILITY_CHECK",
    "PREREQUISITES": "PREREQUISITE_LOOKUP",
    "PREREQUISITE": "PREREQUISITE_LOOKUP",
    "PREREQUISITE_SEARCH": "PREREQUISITE_LOOKUP",
    "LOOKUP_PREREQUISITE": "PREREQUISITE_LOOKUP",
    "STATISTICS": "AGGREGATION_STATISTICS",
    "AGGREGATE": "AGGREGATION_STATISTICS",
    "COUNT_STATISTICS": "AGGREGATION_STATISTICS",
}

EDIT_OPERATION_ALIASES = {
    "NEW": "NEW_QUERY",
    "QUERY": "NEW_QUERY",
    "SEARCH": "NEW_QUERY",
    "VIEW": "NEW_QUERY",
    "LIST": "NEW_QUERY",
    "FILTER": "ADD_FILTER",
    "ADD_CONDITION": "ADD_FILTER",
    "ADD_FILTERS": "ADD_FILTER",
    "REMOVE_CONDITION": "REMOVE_FILTER",
    "REMOVE_FILTERS": "REMOVE_FILTER",
    "REPLACE_CONDITION": "REPLACE_FILTER",
    "UPDATE_FILTER": "REPLACE_FILTER",
    "CHANGE_COURSE": "CHANGE_ENTITY",
    "CHANGE_COURSE_ID": "CHANGE_ENTITY",
    "CHANGE_CLASS": "CHANGE_ENTITY",
    "CHANGE_STUDENT": "CHANGE_ENTITY",
    "CHANGE_SUBJECT": "CHANGE_ENTITY",
    "CHANGE_OBJECT": "CHANGE_ENTITY",
    "SWITCH_INTENT": "CHANGE_INTENT",
    "CHANGE_TASK": "CHANGE_INTENT",
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
}

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


@dataclass(frozen=True)
class QwenMemoryProfile:
    model_label: str
    min_vram_gb: float


def qwen_memory_profile(base_model: str) -> QwenMemoryProfile:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*b", base_model, flags=re.IGNORECASE)
    if not match:
        return QwenMemoryProfile(model_label=base_model or "Qwen adapter", min_vram_gb=7.0)

    size_b = float(match.group(1))
    if size_b <= 0.7:
        min_vram_gb = 2.0
    elif size_b <= 1.7:
        min_vram_gb = 3.0
    elif size_b <= 3.5:
        min_vram_gb = 4.0
    elif size_b <= 7.5:
        min_vram_gb = 7.0
    else:
        min_vram_gb = max(7.0, size_b)

    size_label = match.group(1).rstrip("0").rstrip(".")
    return QwenMemoryProfile(model_label=f"Qwen2.5 Coder {size_label}B", min_vram_gb=min_vram_gb)


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
    if isinstance(intent, str):
        intent = INTENT_ALIASES.get(intent.strip().upper(), intent.strip().upper())
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
                clean_slots[key] = int(value)
            except (TypeError, ValueError):
                continue
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
    ) -> None:
        self.adapter_path = Path(adapter_path)
        if not self.adapter_path.exists():
            raise StateParserError(f"Adapter path does not exist: {self.adapter_path}")
        self.base_model = base_model or self._read_base_model()
        self.max_new_tokens = max_new_tokens
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
        return "Qwen/Qwen2.5-Coder-3B-Instruct"

    def _preflight_runtime(self) -> None:
        try:
            import torch
        except ImportError:
            return
        self._check_gpu_vram(torch)

    def _check_gpu_vram(self, torch_module: Any) -> None:
        if os.getenv("NL2SQL_FORCE_LOW_VRAM") == "1":
            return
        if not torch_module.cuda.is_available():
            return
        profile = qwen_memory_profile(self.base_model)
        total_vram_gb = torch_module.cuda.get_device_properties(0).total_memory / (1024**3)
        if total_vram_gb < profile.min_vram_gb:
            raise StateParserError(
                f"{profile.model_label} adapter needs about {profile.min_vram_gb:.1f} GB GPU memory for local "
                f"4-bit inference, but this local GPU appears to have {total_vram_gb:.1f} GB. Use a smaller "
                "adapter, run the parser remotely, or set NL2SQL_FORCE_LOW_VRAM=1 to try anyway."
            )

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            raise StateParserError(
                "Missing training dependencies. Install requirements-train.txt before using Qwen parser."
            ) from exc

        self._torch = torch
        local_files_only = os.getenv("NL2SQL_ALLOW_MODEL_DOWNLOAD") != "1"
        self._check_gpu_vram(torch)

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.adapter_path,
            trust_remote_code=True,
            local_files_only=True,
        )

        model_kwargs: Dict[str, Any] = {"trust_remote_code": True}
        if not torch.cuda.is_available():
            model_kwargs.update({"device_map": None, "torch_dtype": torch.float32})
        else:
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
        state = validate_state(extract_json_object(text))
        state.raw_text = text
        return state


class RemoteStateParser:
    def __init__(self, api_url: str, timeout_seconds: float = 60.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
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
        parsed = validate_state(state_obj)
        if isinstance(raw_text, str):
            parsed.raw_text = raw_text
        return parsed
