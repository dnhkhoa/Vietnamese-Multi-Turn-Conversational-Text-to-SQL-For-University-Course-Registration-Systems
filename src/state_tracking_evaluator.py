from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .llm_state_parser import extract_json_object, validate_state


def read_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql or "").strip().rstrip(";").casefold()


def safe_select(sql: str) -> bool:
    stripped = (sql or "").strip()
    if not stripped.upper().startswith(("SELECT", "WITH")):
        return False
    without_literals = re.sub(r"'(?:''|[^'])*'", "''", stripped)
    without_literals = re.sub(r'"(?:""|[^"])*"', '""', without_literals)
    without_tail = without_literals.rstrip().rstrip(";")
    return ";" not in without_tail


def query_hash(connection: sqlite3.Connection, sql: str, params: Dict[str, Any]) -> str:
    cursor = connection.execute(sql, params)
    columns = [item[0] for item in (cursor.description or [])]
    rows = cursor.fetchall()
    if not rows:
        return "empty"
    records = [
        {column: "" if value is None else str(value) for column, value in zip(columns, row)}
        for row in rows
    ]
    serialized = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in records
    ]
    payload = json.dumps(sorted(serialized), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def prediction_map(data: Any) -> Dict[str, Dict[str, Any]]:
    if isinstance(data, dict):
        return {
            str(key): value if isinstance(value, dict) else {"prediction": value}
            for key, value in data.items()
        }
    result = {}
    for item in data:
        item_id = item.get("id") or item.get("sample_id")
        if item_id:
            result[str(item_id)] = item
    return result


def predicted_state(item: Dict[str, Any]) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    candidate: Any = None
    for key in ("predicted_state", "state", "prediction_state"):
        if key in item:
            candidate = item[key]
            break
    if candidate is None and {"intent", "edit_operation", "slots"}.intersection(item):
        candidate = {key: item.get(key) for key in ("intent", "edit_operation", "slots")}
    if candidate is None:
        raw = item.get("prediction") or item.get("output")
        if isinstance(raw, str) and "{" in raw:
            candidate = raw
    if candidate is None:
        return None, "missing"
    try:
        if isinstance(candidate, str):
            candidate = extract_json_object(candidate)
        parsed = validate_state(candidate)
        return parsed.as_dict(), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def predicted_sql(item: Dict[str, Any]) -> Optional[str]:
    for key in ("pred_sql", "prediction_sql", "sql"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    prediction = item.get("prediction") or item.get("output")
    if isinstance(prediction, str) and prediction.strip().upper().startswith(("SELECT", "WITH")):
        return prediction.strip()
    return None


def slot_items(slots: Dict[str, Any]) -> set[Tuple[str, str]]:
    return {(str(key), canonical(value)) for key, value in slots.items()}


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def evaluate_rows(
    gold_rows: Sequence[Dict[str, Any]], predictions: Dict[str, Dict[str, Any]], db_path: Path
) -> Dict[str, Any]:
    state_counts = collections.Counter()
    slot_tp = slot_fp = slot_fn = 0
    by_intent: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    state_errors: List[Dict[str, Any]] = []
    sql_errors: List[Dict[str, Any]] = []
    sql_total = sql_exact = sql_execution = sql_covered = 0
    business_total = business_hash_covered = business_hash_correct = business_state_exact = 0

    connection = sqlite3.connect(f"file:{db_path.resolve().as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    try:
        for gold in gold_rows:
            item_id = str(gold["id"])
            prediction = predictions.get(item_id, {})
            gold_state = validate_state(gold["expected_state"]).as_dict()
            intent = gold_state["intent"]
            state_counts["total"] += 1
            by_intent[intent]["total"] += 1
            pred_state, state_error = predicted_state(prediction)
            if pred_state is None:
                state_counts["missing_or_invalid"] += 1
                if len(state_errors) < 50:
                    state_errors.append({"id": item_id, "error": state_error})
            else:
                state_counts["covered"] += 1
                intent_ok = pred_state["intent"] == gold_state["intent"]
                edit_ok = pred_state["edit_operation"] == gold_state["edit_operation"]
                slots_ok = pred_state["slots"] == gold_state["slots"]
                joint_ok = intent_ok and edit_ok and slots_ok
                state_counts["intent_correct"] += int(intent_ok)
                state_counts["edit_operation_correct"] += int(edit_ok)
                state_counts["slots_exact"] += int(slots_ok)
                state_counts["joint_state_exact"] += int(joint_ok)
                by_intent[intent]["joint_correct"] += int(joint_ok)
                gold_slot_set = slot_items(gold_state["slots"])
                pred_slot_set = slot_items(pred_state["slots"])
                slot_tp += len(gold_slot_set & pred_slot_set)
                slot_fp += len(pred_slot_set - gold_slot_set)
                slot_fn += len(gold_slot_set - pred_slot_set)

            if gold.get("gold_sql_kind") == "sql":
                sql_total += 1
                sql = predicted_sql(prediction)
                if sql:
                    sql_covered += 1
                    sql_exact += int(normalize_sql(sql) == normalize_sql(str(gold.get("gold_sql") or "")))
                    if not safe_select(sql):
                        if len(sql_errors) < 50:
                            sql_errors.append({"id": item_id, "error": "unsafe_or_multi_statement_sql"})
                    else:
                        try:
                            params = prediction.get("pred_params") or prediction.get("params") or gold.get("gold_params") or {}
                            actual_hash = query_hash(connection, sql, params)
                            gold_hash = query_hash(
                                connection,
                                str(gold.get("gold_sql") or ""),
                                gold.get("gold_params") or {},
                            )
                            sql_execution += int(actual_hash == gold_hash)
                        except Exception as exc:
                            if len(sql_errors) < 50:
                                sql_errors.append({"id": item_id, "error": f"{type(exc).__name__}: {exc}"})
            else:
                business_total += 1
                business_state_exact += int(
                    pred_state is not None
                    and pred_state["intent"] == gold_state["intent"]
                    and pred_state["edit_operation"] == gold_state["edit_operation"]
                    and pred_state["slots"] == gold_state["slots"]
                )
                predicted_hash = prediction.get("predicted_result_hash") or prediction.get("result_hash")
                if predicted_hash:
                    business_hash_covered += 1
                    business_hash_correct += int(predicted_hash == gold["expected_result"]["result_hash"])
    finally:
        connection.close()

    precision = slot_tp / (slot_tp + slot_fp) if slot_tp + slot_fp else 0.0
    recall = slot_tp / (slot_tp + slot_fn) if slot_tp + slot_fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total = state_counts["total"]
    return {
        "state_tracking": {
            "total": total,
            "covered": state_counts["covered"],
            "missing_or_invalid": state_counts["missing_or_invalid"],
            "intent_accuracy": rate(state_counts["intent_correct"], total),
            "edit_operation_accuracy": rate(state_counts["edit_operation_correct"], total),
            "slots_exact_match": rate(state_counts["slots_exact"], total),
            "joint_state_exact_match": rate(state_counts["joint_state_exact"], total),
            "slot_micro_precision": round(precision, 6),
            "slot_micro_recall": round(recall, 6),
            "slot_micro_f1": round(f1, 6),
            "by_gold_intent": {
                intent: {
                    "total": counts["total"],
                    "joint_state_exact_match": rate(counts["joint_correct"], counts["total"]),
                }
                for intent, counts in sorted(by_intent.items())
            },
            "error_examples": state_errors,
        },
        "sql": {
            "total": sql_total,
            "covered": sql_covered,
            "exact_match": rate(sql_exact, sql_total),
            "execution_accuracy": rate(sql_execution, sql_total),
            "execution_errors": len(sql_errors),
            "error_examples": sql_errors,
        },
        "business_rule": {
            "total": business_total,
            "state_exact_match": rate(business_state_exact, business_total),
            "result_hash_covered": business_hash_covered,
            "result_hash_accuracy": rate(business_hash_correct, business_total),
            "result_hash_accuracy_on_covered": rate(business_hash_correct, business_hash_covered),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate state, slots, SQL execution, and business-rule results")
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--pred", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=Path("data/course_registration.db"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    gold_rows = read_json_or_jsonl(args.gold)
    predictions = prediction_map(read_json_or_jsonl(args.pred))
    report = evaluate_rows(gold_rows, predictions, args.db)
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
