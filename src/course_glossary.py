# src/course_glossary.py
#     Module trung tâm để:
#       - load glossary
#       - normalize alias
#       - build system prompt
#       - tính prompt_sha256
#       - tính glossary_sha256
#       - validate MaMH tồn tại trong DB
#       - estimate token budget

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GLOSSARY_PATH = PROJECT_ROOT / "config" / "course_glossary_k23.json"
STATE_PROMPT_VERSION = "state-json-v2-k23-glossary"
BASE_STATE_SYSTEM_PROMPT = (
    "Ban la bo phan tich state cho bai toan Vietnamese multi-turn text-to-SQL "
    "trong he thong dang ky mon hoc. Chi tra JSON hop le gom intent, edit_operation, slots."
)


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_form(value: str) -> str:
    text = strip_accents(str(value)).upper().strip()
    return re.sub(r"\s+", " ", text)


def load_course_glossary(path: Path | str = DEFAULT_GLOSSARY_PATH) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def glossary_sha256(glossary: Optional[Dict[str, Any]] = None) -> str:
    data = glossary or load_course_glossary()
    return sha256_text(canonical_json(data))


def _entry_lines(glossary: Dict[str, Any]) -> List[str]:
    lines = []
    for entry in glossary.get("entries", []):
        forms = ", ".join(str(form) for form in entry["forms"])
        context_note = " [course-context only]" if entry.get("requires_course_context") else ""
        lines.append(f"- {forms} => {entry['ma_mh']}{context_note}")
    return lines


def build_system_prompt(glossary: Optional[Dict[str, Any]] = None) -> str:
    data = glossary or load_course_glossary()
    glossary_lines = "\n".join(_entry_lines(data))
    return "\n".join(
        [
            BASE_STATE_SYSTEM_PROMPT,
            "",
            f"Course glossary version: {data['version']}.",
            "Rules for course abbreviations:",
            "- Matching is case-insensitive.",
            "- Return only MaMH in slots; do not output aliases or rewritten course names.",
            "- Map short aliases only when the user is clearly talking about a course, class, registration, prerequisite, schedule, or credits.",
            "- Do not map pronouns or generic words, e.g. \"ai da dang ky?\" must not become the AI course.",
            "- Do not invent MaMH outside this glossary.",
            "Glossary:",
            glossary_lines,
        ]
    ).strip()


def prompt_sha256(glossary: Optional[Dict[str, Any]] = None) -> str:
    return sha256_text(build_system_prompt(glossary))


def prompt_metadata(glossary: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    data = glossary or load_course_glossary()
    return {
        "prompt_version": STATE_PROMPT_VERSION,
        "prompt_sha256": prompt_sha256(data),
        "glossary_version": str(data["version"]),
        "glossary_sha256": glossary_sha256(data),
    }


def course_code_aliases_for_validation(glossary: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    data = glossary or load_course_glossary()
    aliases: Dict[str, str] = {}
    for entry in data.get("entries", []):
        ma_mh = str(entry["ma_mh"]).upper()
        aliases[ma_mh] = ma_mh
        for form in entry.get("forms", []):
            aliases[normalize_form(str(form))] = ma_mh
    return aliases


def estimate_prompt_tokens(prompt: str) -> int:
    # Conservative approximation for CI without requiring a tokenizer download.
    return len(re.findall(r"[A-Za-z0-9_]+|[^\sA-Za-z0-9_]", prompt))


def validate_glossary(
    glossary: Optional[Dict[str, Any]] = None,
    db_path: Optional[Path | str] = None,
    max_entries: int = 30,
    max_forms: int = 80,
) -> List[str]:
    data = glossary or load_course_glossary()
    errors: List[str] = []
    if not isinstance(data.get("version"), str) or not data["version"]:
        errors.append("version is required")
    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty list")
        return errors
    if len(entries) > max_entries:
        errors.append(f"entries exceeds limit: {len(entries)} > {max_entries}")

    form_count = 0
    seen_pairs = set()
    for idx, entry in enumerate(entries):
        for key in ["ma_mh", "official_name", "forms", "requires_course_context"]:
            if key not in entry:
                errors.append(f"entries[{idx}] missing {key}")
        forms = entry.get("forms", [])
        if not isinstance(forms, list) or not forms:
            errors.append(f"entries[{idx}].forms must be a non-empty list")
            continue
        form_count += len(forms)
        ma_mh = str(entry.get("ma_mh", "")).upper()
        for form in forms:
            normalized = normalize_form(str(form))
            pair = (normalized, ma_mh)
            if pair in seen_pairs:
                errors.append(f"duplicate form for same course: {form} -> {ma_mh}")
            seen_pairs.add(pair)
    if form_count > max_forms:
        errors.append(f"forms exceeds limit: {form_count} > {max_forms}")

    if db_path:
        with sqlite3.connect(db_path) as conn:
            valid_codes = {row[0] for row in conn.execute("SELECT MaMH FROM MonHoc")}
        for entry in entries:
            ma_mh = str(entry.get("ma_mh", "")).upper()
            if ma_mh not in valid_codes:
                errors.append(f"MaMH not found in MonHoc: {ma_mh}")
    return errors


def glossary_forms(glossary: Optional[Dict[str, Any]] = None) -> Iterable[Dict[str, Any]]:
    data = glossary or load_course_glossary()
    for entry in data.get("entries", []):
        for form in entry.get("forms", []):
            yield {
                "ma_mh": str(entry["ma_mh"]).upper(),
                "official_name": entry["official_name"],
                "form": str(form),
                "requires_course_context": bool(entry.get("requires_course_context")),
            }
