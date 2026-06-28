import json
from pathlib import Path

from src.dataset_semantic_validator import validate_rows
import sqlite3

from src.state_tracking_evaluator import evaluate_rows, query_hash


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "ctdt_sis_v3.db"
TEST_PATH = PROJECT_ROOT / "data" / "v9" / "state_tracking_test_v9.jsonl"


def load_test_rows() -> list[dict]:
    with TEST_PATH.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_semantic_validator_accepts_current_test_split() -> None:
    report = validate_rows(load_test_rows(), DB_PATH)

    assert report["errors"] == 0
    assert report["warnings"] == 0


def test_semantic_validator_rejects_unknown_catalog_entity() -> None:
    row = next(item for item in load_test_rows() if item["gold_sql_kind"] == "sql")
    broken = json.loads(json.dumps(row))
    broken["expected_state"]["slots"]["MaMH"] = "NOT_A_REAL_COURSE"

    report = validate_rows([broken], DB_PATH)

    assert report["errors"] > 0
    assert "unknown_entity" in report["error_codes"]


def test_evaluator_scores_oracle_predictions_perfectly() -> None:
    rows = load_test_rows()[:20]
    predictions = {}
    for row in rows:
        prediction = {
            "predicted_state": row["expected_state"],
            "predicted_result_hash": row["expected_result"]["result_hash"],
        }
        if row["gold_sql_kind"] == "sql":
            prediction["pred_sql"] = row["gold_sql"]
            prediction["pred_params"] = row["gold_params"]
        predictions[row["id"]] = prediction

    report = evaluate_rows(rows, predictions, DB_PATH)

    assert report["state_tracking"]["joint_state_exact_match"] == 1.0
    assert report["state_tracking"]["slot_micro_f1"] == 1.0
    assert report["sql"]["execution_accuracy"] == 1.0
    if report["business_rule"]["total"]:
        assert report["business_rule"]["result_hash_accuracy"] == 1.0


def test_evaluator_counts_missing_predictions_as_incorrect() -> None:
    rows = load_test_rows()[:5]

    report = evaluate_rows(rows, {}, DB_PATH)

    assert report["state_tracking"]["covered"] == 0
    assert report["state_tracking"]["joint_state_exact_match"] == 0.0
    assert report["sql"]["covered"] == 0


def test_execution_hash_is_independent_of_tied_row_order() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        first = query_hash(connection, "SELECT 1 AS value UNION ALL SELECT 2", {})
        reversed_order = query_hash(connection, "SELECT 2 AS value UNION ALL SELECT 1", {})
    finally:
        connection.close()

    assert first == reversed_order
