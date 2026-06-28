from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .llm_state_parser import ALLOWED_EDIT_OPERATIONS, ALLOWED_INTENTS, validate_state
from .nl2sql_engine import COURSE_ALIASES, MAJOR_ALIASES, normalize_text


ENTITY_KEYS = ("MaMH", "MaSV", "MaLHP", "MaNganh")
STUDENT_REQUIRED_INTENTS = {
    "STUDENT_INFO_LOOKUP",
    "STUDENT_REGISTRATION_LOOKUP",
    "STUDENT_RESULT_LOOKUP",
    "CREDIT_SUMMARY",
}


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def catalog_values(connection: sqlite3.Connection) -> Dict[str, set[str]]:
    return {
        "MaMH": {str(row[0]) for row in connection.execute("SELECT MaMH FROM MonHoc")},
        "MaSV": {str(row[0]) for row in connection.execute("SELECT MaSV FROM SinhVien")},
        "MaLHP": {str(row[0]) for row in connection.execute("SELECT MaLHP FROM LopHP")},
        "MaNganh": {str(row[0]) for row in connection.execute("SELECT MaNganh FROM Nganh")},
    }


def entity_aliases(connection: sqlite3.Connection) -> Dict[str, Dict[str, List[str]]]:
    aliases: Dict[str, Dict[str, List[str]]] = {key: {} for key in ENTITY_KEYS}
    for code, name in connection.execute("SELECT MaMH, TenMH FROM MonHoc"):
        values = [str(code), str(name), *COURSE_ALIASES.get(str(code), [])]
        aliases["MaMH"][str(code)] = [normalize_text(value) for value in values]
    for code, name in connection.execute("SELECT MaNganh, TenNganh FROM Nganh"):
        values = [str(code), str(name), *MAJOR_ALIASES.get(str(code), [])]
        aliases["MaNganh"][str(code)] = [normalize_text(value) for value in values]
    for key in ("MaSV", "MaLHP"):
        for value in catalog_values(connection)[key]:
            aliases[key][value] = [normalize_text(value)]
    return aliases


def value_is_mentioned(question: str, key: str, value: Any, aliases: Dict[str, Dict[str, List[str]]]) -> bool:
    normalized = normalize_text(question)
    candidates = aliases.get(key, {}).get(str(value), [normalize_text(str(value))])
    return any(candidate and candidate in normalized for candidate in candidates)


def validate_rows(rows: Sequence[Dict[str, Any]], db_path: Path) -> Dict[str, Any]:
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    ids: set[str] = set()
    dialogue_turns: Dict[str, List[int]] = collections.defaultdict(list)
    connection = sqlite3.connect(db_path)
    try:
        catalog = catalog_values(connection)
        aliases = entity_aliases(connection)
    finally:
        connection.close()

    def error(row: Dict[str, Any], code: str, detail: str) -> None:
        errors.append({"id": row.get("id"), "code": code, "detail": detail})

    def warning(row: Dict[str, Any], code: str, detail: str) -> None:
        warnings.append({"id": row.get("id"), "code": code, "detail": detail})

    for row in rows:
        row_id = str(row.get("id") or "")
        if not row_id:
            error(row, "missing_id", "Row has no id")
        elif row_id in ids:
            error(row, "duplicate_id", row_id)
        ids.add(row_id)
        dialogue_turns[str(row.get("dialogue_id"))].append(int(row.get("turn_id", 0)))

        state = row.get("expected_state") or {}
        previous = row.get("previous_state") or {}
        try:
            parsed = validate_state(state)
        except Exception as exc:
            error(row, "invalid_state", str(exc))
            continue
        if parsed.intent not in ALLOWED_INTENTS:
            error(row, "unknown_intent", parsed.intent)
        if parsed.edit_operation not in ALLOWED_EDIT_OPERATIONS:
            error(row, "unknown_edit_operation", parsed.edit_operation)
        if parsed.edit_operation != "NEW_QUERY" and not previous:
            error(row, "context_operation_without_previous_state", parsed.edit_operation)

        slots = parsed.slots
        if parsed.intent in STUDENT_REQUIRED_INTENTS and not slots.get("MaSV"):
            error(row, "missing_student", parsed.intent)
        if parsed.intent == "REGISTRATION_ELIGIBILITY_CHECK" and (
            not slots.get("MaSV") or not (slots.get("MaMH") or slots.get("MaLHP"))
        ):
            error(row, "incomplete_eligibility_state", json.dumps(slots, ensure_ascii=False))
        if parsed.intent == "PREREQUISITE_LOOKUP" and not slots.get("MaMH"):
            error(row, "missing_prerequisite_course", json.dumps(slots, ensure_ascii=False))

        for key in ENTITY_KEYS:
            value = slots.get(key)
            if value not in (None, "") and str(value) not in catalog[key]:
                error(row, "unknown_entity", f"{key}={value}")
        hoc_ky = slots.get("HocKy")
        if hoc_ky is not None and (not isinstance(hoc_ky, int) or not 1 <= hoc_ky <= 8):
            error(row, "invalid_semester", str(hoc_ky))
        limit = slots.get("Limit")
        if limit is not None and (not isinstance(limit, int) or not 1 <= limit <= 1000):
            error(row, "invalid_limit", str(limit))
        if slots.get("CoTheDangKy") not in (None, 0, 1):
            error(row, "invalid_availability", str(slots.get("CoTheDangKy")))

        previous_slots = previous.get("slots") or {}
        history = previous.get("entity_history") or {}
        question = str(row.get("user_question") or "")
        for key in ENTITY_KEYS:
            expected = slots.get(key)
            if expected in (None, "") or expected == previous_slots.get(key):
                continue
            known_history = [str(value) for value in history.get(key, [])]
            if not value_is_mentioned(question, key, expected, aliases) and str(expected) not in known_history:
                error(row, "unresolved_entity_provenance", f"{key}={expected}")

        sql_kind = row.get("gold_sql_kind")
        sql = str(row.get("gold_sql") or "")
        params = row.get("gold_params") or {}
        if sql_kind == "sql":
            if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
                error(row, "unsafe_or_missing_sql", sql[:80])
            placeholders = set(re.findall(r":([A-Za-z_][A-Za-z0-9_]*)", sql))
            param_keys = set(params)
            if placeholders != param_keys:
                error(row, "sql_param_mismatch", f"placeholders={sorted(placeholders)}, params={sorted(param_keys)}")
        elif sql_kind == "business_rule":
            if not sql.startswith("-- business_rules."):
                error(row, "invalid_business_rule_marker", sql[:80])
        else:
            error(row, "unknown_gold_kind", str(sql_kind))

        result = row.get("expected_result") or {}
        if result.get("result_hash") is None:
            error(row, "missing_result_hash", "expected_result.result_hash")
        if int(result.get("row_count", -1)) < 0:
            error(row, "invalid_row_count", str(result.get("row_count")))
        if result.get("rows_truncated") and len(result.get("rows") or []) >= int(result.get("row_count", 0)):
            warning(row, "redundant_truncated_flag", "rows_truncated=true but all rows are present")

    length_distribution = collections.Counter(len(turns) for turns in dialogue_turns.values())
    for dialogue_id, turns in dialogue_turns.items():
        if len(turns) != len(set(turns)):
            errors.append({"id": dialogue_id, "code": "duplicate_turn_id", "detail": str(turns)})

    return {
        "rows": len(rows),
        "dialogues": len(dialogue_turns),
        "dialogue_length_distribution": dict(sorted(length_distribution.items())),
        "errors": len(errors),
        "warnings": len(warnings),
        "error_codes": dict(sorted(collections.Counter(item["code"] for item in errors).items())),
        "warning_codes": dict(sorted(collections.Counter(item["code"] for item in warnings).items())),
        "error_examples": errors[:50],
        "warning_examples": warnings[:50],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Semantic audit for state-tracking evaluation JSONL")
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--db", type=Path, default=Path("data/course_registration.db"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-warnings", action="store_true")
    args = parser.parse_args()
    report = validate_rows(read_jsonl(args.dataset), args.db)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if report["errors"] or (args.fail_on_warnings and report["warnings"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
