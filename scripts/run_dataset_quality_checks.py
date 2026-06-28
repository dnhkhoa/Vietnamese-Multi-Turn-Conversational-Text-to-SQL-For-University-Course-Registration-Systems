from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.dataset_semantic_validator import read_jsonl, validate_rows
from src.state_tracking_evaluator import evaluate_rows


def oracle_predictions(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    predictions: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        prediction: Dict[str, Any] = {
            "predicted_state": row["expected_state"],
            "predicted_result_hash": row["expected_result"]["result_hash"],
        }
        if row["gold_sql_kind"] == "sql":
            prediction["pred_sql"] = row["gold_sql"]
            prediction["pred_params"] = row["gold_params"]
        predictions[row["id"]] = prediction
    return predictions


def main() -> None:
    parser = argparse.ArgumentParser(description="Run semantic and evaluator self-tests for a dataset version")
    parser.add_argument("--version", required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    version = args.version.strip().lower()
    data_dir = args.data_dir
    audit = json.loads((data_dir / f"dataset_audit_{version}.json").read_text(encoding="utf-8"))
    dev_rows = read_jsonl(data_dir / f"state_tracking_dev_{version}.jsonl")
    test_rows = read_jsonl(data_dir / f"state_tracking_test_{version}.jsonl")
    semantic_dev = validate_rows(dev_rows, args.db)
    semantic_test = validate_rows(test_rows, args.db)
    oracle = evaluate_rows(test_rows, oracle_predictions(test_rows), args.db)
    checks = {
        "database_fingerprint_present": bool(audit.get("database", {}).get("sha256")),
        "duplicate_rows_zero": audit["after"]["duplicate_rows"] == 0,
        "split_overlap_zero": not any(audit["after"]["split_overlap"].values()),
        "unrecoverable_history_zero": audit["after"]["unrecoverable_history_rows"] == 0,
        "gold_validation_clean": audit["gold_validation"]["failed"] == 0,
        "semantic_all_clean": audit["semantic_audit"]["errors"] == 0,
        "semantic_dev_clean": semantic_dev["errors"] == 0,
        "semantic_test_clean": semantic_test["errors"] == 0,
        "oracle_joint_state_exact": oracle["state_tracking"]["joint_state_exact_match"] == 1.0,
        "oracle_slot_f1": oracle["state_tracking"]["slot_micro_f1"] == 1.0,
        "oracle_sql_execution": oracle["sql"]["execution_accuracy"] == 1.0,
        "oracle_business_result": oracle["business_rule"]["result_hash_accuracy"] == 1.0,
    }
    report = {
        "version": version,
        "database": audit["database"],
        "passed": all(checks.values()),
        "checks": checks,
        "semantic_dev": semantic_dev,
        "semantic_test": semantic_test,
        "evaluator_oracle_self_test": oracle,
    }
    output = data_dir / f"quality_gate_{version}.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
