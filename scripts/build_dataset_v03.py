from __future__ import annotations

import argparse
import collections
import hashlib
import json
import math
import random
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.business_rules import DEFAULT_DB_PATH
from src.dataset_semantic_validator import validate_rows as validate_semantic_rows
from src.llm_state_parser import SYSTEM_PROMPT
from src.nl2sql_engine import VietnameseNL2SQLEngine


DEFAULT_INPUTS = (
    PROJECT_ROOT / "data" / "synthetic_eval_v02.jsonl",
    PROJECT_ROOT / "data" / "manual_labeled_eval_v02.jsonl",
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "v03"
ENTITY_KEYS = ("MaMH", "MaSV", "MaLHP", "MaNganh")
SOURCE_RENAMES = {
    "curated_manual_labeled_500": "curated_synthetic_manual_style",
    "stateful_context_switch_v02": "stateful_context_switch",
    "student_profile_advising_v02": "student_profile_advising",
    "template_synthetic_30k": "template_synthetic",
}


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stable_score(seed: int, *parts: str) -> str:
    payload = ":".join([str(seed), *parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def update_history(history: Dict[str, List[str]], slots: Dict[str, Any]) -> Dict[str, List[str]]:
    updated = {key: list(values) for key, values in history.items()}
    for key in ENTITY_KEYS:
        value = slots.get(key)
        if value in (None, ""):
            continue
        token = str(value)
        values = updated.setdefault(key, [])
        if not values or values[-1] != token:
            values.append(token)
        updated[key] = values[-8:]
    return updated


def state_with_history(state: Dict[str, Any], history: Dict[str, List[str]]) -> Dict[str, Any]:
    result = {
        "intent": state["intent"],
        "edit_operation": state["edit_operation"],
        "slots": dict(state.get("slots") or {}),
    }
    compact_history = {key: list(values) for key, values in history.items() if values}
    if compact_history:
        result["entity_history"] = compact_history
    return result


def flatten_dialogues(dialogues: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for dialogue in dialogues:
        previous_state: Dict[str, Any] = {}
        history: Dict[str, List[str]] = {key: [] for key in ENTITY_KEYS}
        source = SOURCE_RENAMES.get(dialogue.get("source"), dialogue.get("source"))
        for turn_index, turn in enumerate(dialogue.get("turns") or [], start=1):
            expected_state = {
                "intent": turn["intent"],
                "edit_operation": turn["edit_operation"],
                "slots": dict(turn.get("slots") or {}),
            }
            baseline = dict(turn.get("baseline") or {})
            row_id = f"{dialogue['dialogue_id']}_turn_{turn_index:02d}"
            payload = {"previous_state": previous_state, "utterance": turn["utterance"]}
            rows.append(
                {
                    "id": row_id,
                    "dialogue_id": dialogue["dialogue_id"],
                    "turn_id": turn_index,
                    "db_id": dialogue.get("db_id", "course_registration"),
                    "source": source,
                    "previous_state": previous_state,
                    "user_question": turn["utterance"],
                    "expected_state": expected_state,
                    "gold_sql": baseline.get("sql"),
                    "gold_sql_kind": baseline.get("sql_kind", "sql"),
                    "gold_params": baseline.get("params", {}),
                    "expected_result": {
                        "columns": baseline.get("columns", []),
                        "rows": baseline.get("expected_rows", []),
                        "rows_truncated": baseline.get("expected_rows_truncated", False),
                        "row_count": baseline.get("row_count", 0),
                        "result_hash": baseline.get("result_hash"),
                    },
                    "_signature": canonical([payload, expected_state]),
                }
            )
            history = update_history(history, expected_state["slots"])
            previous_state = state_with_history(expected_state, history)
    return rows


def deduplicate(rows: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    owner: Dict[str, str] = {}
    for row in rows:
        signature = row["_signature"]
        if signature in owner:
            dropped.append({"id": row["id"], "duplicate_of": owner[signature]})
            continue
        owner[signature] = row["id"]
        kept.append(row)
    return kept, dropped


def stratified_dialogue_split(
    rows: Sequence[Dict[str, Any]], seed: int, dev_ratio: float, test_ratio: float
) -> Dict[str, str]:
    grouped: Dict[str, set[str]] = collections.defaultdict(set)
    for row in rows:
        grouped[row["source"]].add(row["dialogue_id"])

    assignments: Dict[str, str] = {}
    for source, dialogue_ids in sorted(grouped.items()):
        ordered = sorted(dialogue_ids, key=lambda value: stable_score(seed, source, value))
        count = len(ordered)
        test_count = max(1, round(count * test_ratio)) if count >= 3 else 0
        dev_count = max(1, round(count * dev_ratio)) if count >= 3 else 0
        if test_count + dev_count >= count:
            dev_count = max(0, count - test_count - 1)
        for dialogue_id in ordered[:test_count]:
            assignments[dialogue_id] = "test"
        for dialogue_id in ordered[test_count : test_count + dev_count]:
            assignments[dialogue_id] = "dev"
        for dialogue_id in ordered[test_count + dev_count :]:
            assignments[dialogue_id] = "train"
    return assignments


def public_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in row.items() if not key.startswith("_")}


def sft_row(row: Dict[str, Any], split: str) -> Dict[str, Any]:
    user_payload = {
        "previous_state": row["previous_state"],
        "utterance": row["user_question"],
    }
    return {
        "id": row["id"],
        "split": split,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": canonical(user_payload)},
            {"role": "assistant", "content": canonical(row["expected_state"])},
        ],
        "metadata": {
            "dialogue_id": row["dialogue_id"],
            "turn_id": row["turn_id"],
            "source": row["source"],
        },
    }


def balance_rows(rows: Sequence[Dict[str, Any]], seed: int, max_ratio: float) -> tuple[List[Dict[str, Any]], int]:
    by_intent: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        by_intent[row["expected_state"]["intent"]].append(row)
    smallest = min(len(items) for items in by_intent.values())
    cap = max(1, math.ceil(smallest * max_ratio))
    balanced: List[Dict[str, Any]] = []
    for intent, items in sorted(by_intent.items()):
        ordered = sorted(items, key=lambda row: stable_score(seed, intent, row["_signature"], row["id"]))
        balanced.extend(ordered[:cap])
    balanced.sort(key=lambda row: stable_score(seed, "balanced", row["id"]))
    return balanced, cap


def dataframe_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return "empty"
    normalized = df.fillna("").astype(str)
    records = [
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for record in normalized.to_dict(orient="records")
    ]
    payload = json.dumps(sorted(records), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def refresh_gold(rows: Sequence[Dict[str, Any]], db_path: Path, max_rows: int = 30) -> Dict[str, Any]:
    """Rebuild SQL/business-rule results from the labeled state against the current database."""
    changed = 0
    failures: List[Dict[str, Any]] = []
    engine = VietnameseNL2SQLEngine(db_path=db_path, parser_mode="rule")
    sql_connection = sqlite3.connect(db_path)
    try:
        for row in rows:
            state = row["expected_state"]
            try:
                result = engine._execute_intent(
                    row["user_question"],
                    state["intent"],
                    dict(state.get("slots") or {}),
                    state["edit_operation"],
                    parser_source="dataset_v03_gold_refresh",
                )
                refreshed_sql = result.sql
                refreshed_kind = (
                    "business_rule"
                    if refreshed_sql and refreshed_sql.startswith("-- business_rules.")
                    else "sql"
                )
                # The engine applies some default display limits without adding them to
                # result.sql. SQL gold must describe the result obtained by executing the
                # exported SQL itself, so refresh SQL rows independently here.
                if refreshed_kind == "sql":
                    frame = pd.read_sql_query(refreshed_sql, sql_connection, params=result.params)
                else:
                    frame = result.dataframe
                refreshed_result = {
                    "columns": list(frame.columns),
                    "rows": frame.head(max_rows).fillna("").to_dict(orient="records") if not frame.empty else [],
                    "rows_truncated": len(frame) > max_rows,
                    "row_count": len(frame),
                    "result_hash": dataframe_hash(frame),
                }
                old_gold = canonical(
                    [
                        row.get("gold_sql"),
                        row.get("gold_sql_kind"),
                        row.get("gold_params"),
                        row.get("expected_result"),
                    ]
                )
                new_gold = canonical([refreshed_sql, refreshed_kind, result.params, refreshed_result])
                if old_gold != new_gold:
                    changed += 1
                row["gold_sql"] = refreshed_sql
                row["gold_sql_kind"] = refreshed_kind
                row["gold_params"] = dict(result.params)
                row["expected_result"] = refreshed_result
            except Exception as exc:
                failures.append({"id": row["id"], "error": f"{type(exc).__name__}: {exc}"})
    finally:
        engine.close()
        sql_connection.close()
    return {"checked": len(rows), "changed": changed, "failed": len(failures), "failure_examples": failures[:20]}


def validate_sql_gold(rows: Sequence[Dict[str, Any]], db_path: Path) -> Dict[str, Any]:
    checked = 0
    failures: List[Dict[str, Any]] = []
    connection = sqlite3.connect(db_path)
    try:
        for row in rows:
            if row.get("gold_sql_kind") != "sql":
                continue
            checked += 1
            try:
                frame = pd.read_sql_query(row["gold_sql"], connection, params=row.get("gold_params") or {})
                expected = row.get("expected_result") or {}
                problems = []
                if list(frame.columns) != list(expected.get("columns") or []):
                    problems.append("columns")
                if len(frame) != int(expected.get("row_count", 0)):
                    problems.append("row_count")
                expected_hash = expected.get("result_hash")
                if expected_hash and dataframe_hash(frame) != expected_hash:
                    problems.append("result_hash")
                if problems:
                    failures.append({"id": row["id"], "mismatches": problems})
            except Exception as exc:
                failures.append({"id": row["id"], "error": f"{type(exc).__name__}: {exc}"})
    finally:
        connection.close()
    return {"checked": checked, "failed": len(failures), "failure_examples": failures[:20]}


def distribution(rows: Sequence[Dict[str, Any]], field: str) -> Dict[str, int]:
    if field == "source":
        values = (row["source"] for row in rows)
    else:
        values = (row["expected_state"][field] for row in rows)
    return dict(sorted(collections.Counter(values).items()))


def split_overlap(splits: Dict[str, Sequence[Dict[str, Any]]]) -> Dict[str, int]:
    signatures = {name: {row["_signature"] for row in rows} for name, rows in splits.items()}
    return {
        "train_dev": len(signatures["train"] & signatures["dev"]),
        "train_test": len(signatures["train"] & signatures["test"]),
        "dev_test": len(signatures["dev"] & signatures["test"]),
    }


def count_unrecoverable_history(rows: Sequence[Dict[str, Any]]) -> int:
    markers = ("quay lại", "ban đầu", "trở lại")
    count = 0
    for row in rows:
        question = row["user_question"].casefold()
        expected_course = row["expected_state"].get("slots", {}).get("MaMH")
        previous_slots = row["previous_state"].get("slots", {})
        history = row["previous_state"].get("entity_history", {}).get("MaMH", [])
        if (
            expected_course
            and any(marker in question for marker in markers)
            and expected_course != previous_slots.get("MaMH")
            and expected_course.casefold() not in question
            and expected_course not in history
        ):
            count += 1
    return count


def render_report(audit: Dict[str, Any]) -> str:
    before = audit["before"]
    after = audit["after"]
    sql_validation = audit["gold_validation"]
    gold_refresh = audit["gold_refresh"]
    semantic_audit = audit["semantic_audit"]
    version = audit["version"]
    return f"""# Dataset improvement report {version}

Generated deterministically with seed `{audit['seed']}` from the listed dialogue files. Earlier dataset versions were preserved.

## What changed

- Split by `dialogue_id`, stratified by source, before exporting train/dev/test artifacts.
- Removed exact duplicate state-tracking examples globally.
- Added bounded `entity_history` to `previous_state` and aligned the training system prompt with inference.
- Renamed the misleading `curated_manual_labeled_500` source to `curated_synthetic_manual_style_v03`.
- Created a full deduplicated train set and a balanced default train set capped at {after['balanced_intent_cap']} rows per intent.
- Separated executable SQL evaluation rows from business-rule evaluation rows.
- Re-executed all held-out SQL gold queries against the configured database snapshot and checked columns, row counts, and result hashes.
- Refreshed {gold_refresh['changed']} stale or incomplete SQL/business-rule result records against the current database.
- Wrote a split manifest and a machine-readable audit file for reproducibility.
- Applied semantic validation for entity provenance, required slots, catalog membership, SQL parameters, safe read-only SQL, and result metadata.

## Before and after

| Metric | v02 | {version} |
|---|---:|---:|
| Raw examples | {before['rows']} | {after['deduplicated_rows']} deduplicated |
| Exact duplicate examples | {before['duplicate_rows']} | {after['duplicate_rows']} |
| Train/eval exact overlap | {before['train_eval_overlap']} | {after['split_overlap']['train_test']} |
| Unrecoverable long-range references | {before['unrecoverable_history_rows']} | {after['unrecoverable_history_rows']} |
| Default train examples | n/a | {after['split_rows']['train_balanced']} |
| Full train examples | n/a | {after['split_rows']['train_full']} |
| Dev examples | n/a | {after['split_rows']['dev']} |
| Test examples | {before['eval_rows']} leaked | {after['split_rows']['test']} held out |
| Held-out SQL gold validation failures | not checked | {sql_validation['failed']} / {sql_validation['checked']} |
| Gold records refreshed | n/a | {gold_refresh['changed']} / {gold_refresh['checked']} |
| Semantic validation errors | not checked | {semantic_audit['errors']} |

## Output files

- `qwen_state_tracking_train_{version}.jsonl`: balanced default SFT train set.
- `qwen_state_tracking_train_full_{version}.jsonl`: all deduplicated train examples.
- `qwen_state_tracking_dev_{version}.jsonl` and `qwen_state_tracking_test_{version}.jsonl`: SFT-format held-out splits.
- `state_tracking_dev_{version}.jsonl` and `state_tracking_test_{version}.jsonl`: evaluation format with SQL/result gold.
- `state_tracking_test_sql_{version}.jsonl`: executable SQL-only benchmark.
- `state_tracking_test_business_rule_{version}.jsonl`: business-rule-only benchmark.
- `split_manifest_{version}.json`: dialogue-to-split assignments.
- `dataset_audit_{version}.json`: detailed counts and validation results.
- `semantic_audit_{version}.json`: semantic gate results and dialogue-length distribution.

## Problems and remaining limitations

- No genuine user-collected and independently human-annotated conversations were available. The former “manual” source was synthetic/manual-style, so v03 labels it honestly instead of claiming it is human data.
- Source dialogue length and diversity are reported by the audit. This pipeline never fabricates random truncations merely to improve the distribution.
- SQL gold is generated by the deterministic engine from labeled states. Re-execution verifies consistency with the database, but independent semantic annotation is still required for a publication-grade benchmark.
- SQL expected results are defined by executing the exported SQL itself; UI DataFrames are not used as SQL gold.
- Business-rule outputs are not SQL and must be evaluated separately, which is why the pipeline exports a dedicated split.
- Model quality was not re-evaluated because the local machine has no usable GPU and the model environment/cache were removed. Dataset integrity results do not imply a model accuracy result.

## Final assessment

{version.upper()} fixes the measurable leakage, duplication, missing history, misleading source naming, mixed evaluation protocol, and reproducibility issues found in v02. It is suitable for a clean retraining experiment. A publication-grade test set still requires genuinely held-out user conversations and independent human annotation.
"""


def analyze_v02(train_path: Path, eval_path: Path) -> Dict[str, Any]:
    train = read_jsonl(train_path)
    eval_rows = read_jsonl(eval_path)
    pairs = []
    for row in train:
        user = json.loads(row["messages"][1]["content"])
        assistant = json.loads(row["messages"][2]["content"])
        pairs.append(canonical([user, assistant]))
    pair_set = set(pairs)
    overlap = 0
    unrecoverable = 0
    for row in eval_rows:
        payload = {"previous_state": row["previous_state"], "utterance": row["user_question"]}
        if canonical([payload, row["expected_state"]]) in pair_set:
            overlap += 1
        question = row["user_question"].casefold()
        expected = row["expected_state"].get("slots", {}).get("MaMH")
        previous = row["previous_state"].get("slots", {}).get("MaMH")
        if expected and ("quay lại" in question or "ban đầu" in question) and expected != previous and expected.casefold() not in question:
            unrecoverable += 1
    return {
        "rows": len(train),
        "eval_rows": len(eval_rows),
        "duplicate_rows": len(pairs) - len(pair_set),
        "train_eval_overlap": overlap,
        "unrecoverable_history_rows": unrecoverable,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build leakage-free state-tracking dataset v03")
    parser.add_argument("--inputs", nargs="+", type=Path, default=list(DEFAULT_INPUTS))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--seed", type=int, default=20260621)
    parser.add_argument("--dev-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--max-intent-ratio", type=float, default=2.5)
    parser.add_argument("--version", default="v03")
    args = parser.parse_args()
    version = args.version.strip().lower()
    if not version or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in version):
        raise SystemExit("--version must contain only letters, digits, underscore, or hyphen")

    dialogues: List[Dict[str, Any]] = []
    for path in args.inputs:
        dialogues.extend(read_jsonl(path))
    input_length_distribution = dict(
        sorted(collections.Counter(len(dialogue.get("turns") or []) for dialogue in dialogues).items())
    )

    all_rows = flatten_dialogues(dialogues)
    clean_rows, dropped = deduplicate(all_rows)
    gold_refresh = refresh_gold(clean_rows, args.db)
    if gold_refresh["failed"]:
        write_json(args.output_dir / f"gold_refresh_failures_{version}.json", gold_refresh)
        raise SystemExit(f"Could not refresh all {version} gold records")
    semantic_audit = validate_semantic_rows(clean_rows, args.db)
    write_json(args.output_dir / f"semantic_audit_{version}.json", semantic_audit)
    if semantic_audit["errors"]:
        raise SystemExit(f"Semantic validation failed; inspect semantic_audit_{version}.json")
    assignments = stratified_dialogue_split(clean_rows, args.seed, args.dev_ratio, args.test_ratio)
    splits: Dict[str, List[Dict[str, Any]]] = {"train": [], "dev": [], "test": []}
    for row in clean_rows:
        splits[assignments[row["dialogue_id"]]].append(row)

    balanced_train, intent_cap = balance_rows(splits["train"], args.seed, args.max_intent_ratio)
    for name in splits:
        splits[name].sort(key=lambda row: (row["dialogue_id"], row["turn_id"]))

    output = args.output_dir
    write_jsonl(output / f"qwen_state_tracking_train_{version}.jsonl", (sft_row(row, "train") for row in balanced_train))
    write_jsonl(output / f"qwen_state_tracking_train_full_{version}.jsonl", (sft_row(row, "train") for row in splits["train"]))
    write_jsonl(output / f"qwen_state_tracking_dev_{version}.jsonl", (sft_row(row, "dev") for row in splits["dev"]))
    write_jsonl(output / f"qwen_state_tracking_test_{version}.jsonl", (sft_row(row, "test") for row in splits["test"]))
    write_jsonl(output / f"state_tracking_dev_{version}.jsonl", (public_row(row) for row in splits["dev"]))
    write_jsonl(output / f"state_tracking_test_{version}.jsonl", (public_row(row) for row in splits["test"]))
    write_jsonl(
        output / f"state_tracking_test_sql_{version}.jsonl",
        (public_row(row) for row in splits["test"] if row["gold_sql_kind"] == "sql"),
    )
    write_jsonl(
        output / f"state_tracking_test_business_rule_{version}.jsonl",
        (public_row(row) for row in splits["test"] if row["gold_sql_kind"] == "business_rule"),
    )

    manifest = {
        "seed": args.seed,
        "strategy": "source-stratified dialogue split after global exact deduplication",
        "ratios": {"train": 1 - args.dev_ratio - args.test_ratio, "dev": args.dev_ratio, "test": args.test_ratio},
        "assignments": dict(sorted(assignments.items())),
    }
    write_json(output / f"split_manifest_{version}.json", manifest)
    write_jsonl(output / f"dropped_duplicates_{version}.jsonl", dropped)

    before = analyze_v02(
        PROJECT_ROOT / "data" / "qwen_state_tracking_train_v02.jsonl",
        PROJECT_ROOT / "data" / "state_tracking_eval_v02.jsonl",
    )
    gold_validation = validate_sql_gold([*splits["dev"], *splits["test"]], args.db)
    after = {
        "deduplicated_rows": len(clean_rows),
        "duplicate_rows": len(clean_rows) - len({row["_signature"] for row in clean_rows}),
        "duplicates_removed": len(dropped),
        "unrecoverable_history_rows": count_unrecoverable_history(clean_rows),
        "balanced_intent_cap": intent_cap,
        "split_rows": {
            "train_balanced": len(balanced_train),
            "train_full": len(splits["train"]),
            "dev": len(splits["dev"]),
            "test": len(splits["test"]),
            "test_sql": sum(row["gold_sql_kind"] == "sql" for row in splits["test"]),
            "test_business_rule": sum(row["gold_sql_kind"] == "business_rule" for row in splits["test"]),
        },
        "split_dialogues": dict(collections.Counter(assignments.values())),
        "split_overlap": split_overlap(splits),
        "train_full_intents": distribution(splits["train"], "intent"),
        "train_balanced_intents": distribution(balanced_train, "intent"),
        "test_intents": distribution(splits["test"], "intent"),
        "sources": distribution(clean_rows, "source"),
        "input_dialogue_length_distribution": input_length_distribution,
    }
    audit = {
        "version": version,
        "seed": args.seed,
        "database": {
            "path": str(args.db.resolve().relative_to(PROJECT_ROOT)),
            "size_bytes": args.db.stat().st_size,
            "sha256": file_sha256(args.db),
        },
        "inputs": [str(path.resolve().relative_to(PROJECT_ROOT)) for path in args.inputs],
        "before": before,
        "after": after,
        "gold_refresh": gold_refresh,
        "gold_validation": gold_validation,
        "semantic_audit": semantic_audit,
        "remaining_limitations": [
            "No genuinely user-collected, independently human-annotated test set is available.",
            "Older v02 sources remain template-driven; added sources improve but do not replace real linguistic diversity.",
            "SQL gold is engine-generated, although held-out SQL was independently re-executed for consistency.",
            "Model accuracy was not measured on this CPU-only machine.",
        ],
    }
    write_json(output / f"dataset_audit_{version}.json", audit)
    (output / f"DATASET_REPORT_{version.upper()}.md").write_text(render_report(audit), encoding="utf-8")

    if after["duplicate_rows"] or any(after["split_overlap"].values()) or gold_validation["failed"]:
        raise SystemExit(f"{version} integrity checks failed; inspect dataset_audit_{version}.json")
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
