import argparse
import json
import re
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "processed" / "university_v02"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "database" / "university_registration.sqlite"


def load_json_or_jsonl(path):
    path = Path(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def normalize_sql(sql):
    sql = re.sub(r"\s+", " ", (sql or "")).strip().rstrip(";")
    return sql.lower()


def result_rows(conn, sql):
    cursor = conn.execute(sql)
    return [tuple(row) for row in cursor.fetchall()]


def result_signature(rows):
    return sorted(str(row) for row in rows)


def load_gold(path):
    rows = load_json_or_jsonl(path)
    gold = {}
    for item in rows:
        if "turns" in item:
            for turn in item["turns"]:
                gold[f"{item['conversation_id']}_turn_{turn['turn_id']}"] = turn["sql"]
        else:
            gold[item["id"]] = item.get("output") or item.get("sql")
    return gold


def load_predictions(path):
    rows = load_json_or_jsonl(path)
    if isinstance(rows, dict):
        return {key: value for key, value in rows.items()}
    predictions = {}
    for item in rows:
        item_id = item.get("id") or item.get("sample_id")
        sql = item.get("prediction") or item.get("pred_sql") or item.get("sql") or item.get("output")
        if item_id:
            predictions[item_id] = sql
    return predictions


def evaluate(gold_path, pred_path, db_path):
    gold = load_gold(gold_path)
    predictions = load_predictions(pred_path)
    conn = sqlite3.connect(db_path)

    exact = 0
    execution = 0
    missing = 0
    pred_errors = []
    gold_errors = []

    try:
        for item_id, gold_sql in gold.items():
            pred_sql = predictions.get(item_id)
            if not pred_sql:
                missing += 1
                continue

            if normalize_sql(pred_sql) == normalize_sql(gold_sql):
                exact += 1

            try:
                gold_rows = result_signature(result_rows(conn, gold_sql))
            except Exception as exc:
                gold_errors.append({"id": item_id, "error": str(exc), "sql": gold_sql})
                continue

            try:
                pred_rows = result_signature(result_rows(conn, pred_sql))
            except Exception as exc:
                pred_errors.append({"id": item_id, "error": str(exc), "sql": pred_sql})
                continue

            if pred_rows == gold_rows:
                execution += 1
    finally:
        conn.close()

    total = len(gold)
    evaluated = total - missing
    return {
        "gold": str(gold_path),
        "predictions": str(pred_path),
        "db_path": str(db_path),
        "total": total,
        "evaluated": evaluated,
        "missing_predictions": missing,
        "exact_match": exact,
        "exact_match_rate": round(exact / total, 4) if total else 0.0,
        "execution_match": execution,
        "execution_match_rate": round(execution / total, 4) if total else 0.0,
        "prediction_sql_errors": len(pred_errors),
        "gold_sql_errors": len(gold_errors),
        "sample_prediction_errors": pred_errors[:20],
        "sample_gold_errors": gold_errors[:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate Text-to-SQL predictions with exact and execution match.")
    parser.add_argument("--gold", default=DEFAULT_DATA_DIR / "training" / "university_train_format_test_v02.json")
    parser.add_argument("--pred", required=True, help="JSON/JSONL predictions. Use fields id + prediction/pred_sql/sql/output, or a JSON object id -> sql.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    args = parser.parse_args()

    report = evaluate(Path(args.gold), Path(args.pred), Path(args.db))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
