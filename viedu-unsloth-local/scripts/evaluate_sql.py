import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

from sql_validator import validate_sql


ROOT = Path(__file__).resolve().parents[1]


def load_jsonl(path):
    with Path(path).open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def normalize(sql):
    return " ".join((sql or "").strip().rstrip(";").split()).lower()


def execute(conn, sql):
    return conn.execute(sql).fetchall()


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pred_file", required=True)
    parser.add_argument("--gold_file")
    parser.add_argument("--sqlite_db")
    args = parser.parse_args()

    preds = load_jsonl(args.pred_file)
    gold_by_id = {}
    if args.gold_file and Path(args.gold_file).exists():
        gold_by_id = {row["id"]: row for row in load_jsonl(args.gold_file)}
    conn = sqlite3.connect(args.sqlite_db) if args.sqlite_db and Path(args.sqlite_db).exists() else None
    total = len(preds)
    exact = 0
    valid = 0
    exec_correct = 0
    invalid_examples = []
    exec_errors = []
    error_types = Counter()
    by_operation = defaultdict(lambda: Counter(total=0, exact=0, valid=0, exec=0))
    by_tag = defaultdict(lambda: Counter(total=0, exact=0, valid=0, exec=0))
    by_join = defaultdict(lambda: Counter(total=0, exact=0, valid=0, exec=0))

    for row in preds:
        pred_sql = row.get("pred_sql", "")
        gold_row = gold_by_id.get(row.get("id"), {})
        gold_sql = row.get("gold_sql") or gold_row.get("gold_sql", "")
        meta = row.get("metadata") or gold_row.get("metadata", {}) or {}
        validation = validate_sql(pred_sql)
        is_exact = normalize(pred_sql) == normalize(gold_sql)
        is_valid = validation["is_valid"]
        is_exec = False
        if is_exact:
            exact += 1
        if is_valid:
            valid += 1
        else:
            error_types[validation["reason"]] += 1
            if len(invalid_examples) < 25:
                invalid_examples.append({"id": row.get("id"), "reason": validation["reason"], "pred_sql": pred_sql})
        if conn and is_valid:
            try:
                pred_rows = execute(conn, validation["normalized_sql"])
                gold_rows = execute(conn, gold_sql)
                is_exec = pred_rows == gold_rows
                if is_exec:
                    exec_correct += 1
            except Exception as exc:
                error_types[type(exc).__name__] += 1
                if len(exec_errors) < 25:
                    exec_errors.append({"id": row.get("id"), "error": str(exc), "pred_sql": pred_sql})
        op = meta.get("operation") or "unknown"
        join_bucket = str(validation["join_count"])
        buckets = [by_operation[op], by_join[join_bucket]]
        for tag in meta.get("tags", []) or ["no_tag"]:
            buckets.append(by_tag[tag])
        for bucket in buckets:
            bucket["total"] += 1
            bucket["exact"] += int(is_exact)
            bucket["valid"] += int(is_valid)
            bucket["exec"] += int(is_exec)

    def rates(counter):
        n = counter["total"] or 1
        return {
            "total": counter["total"],
            "exact_match": counter["exact"] / n,
            "valid_sql_rate": counter["valid"] / n,
            "execution_accuracy": counter["exec"] / n if conn else None,
        }

    report = {
        "total": total,
        "exact_match": exact / total if total else 0,
        "valid_sql_rate": valid / total if total else 0,
        "execution_accuracy": exec_correct / total if conn and total else None,
        "execution_accuracy_available": conn is not None,
        "average_latency_ms": sum(row.get("latency_ms", 0) for row in preds) / total if total else None,
        "error_type_summary": dict(error_types),
    }
    metrics_by_category = {
        "operation": {key: rates(value) for key, value in by_operation.items()},
        "tag": {key: rates(value) for key, value in by_tag.items()},
        "join_count": {key: rates(value) for key, value in by_join.items()},
    }

    out_dir = ROOT / "outputs" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "eval_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "metrics_by_category.json").write_text(json.dumps(metrics_by_category, ensure_ascii=False, indent=2), encoding="utf-8")
    write_jsonl(out_dir / "error_examples.jsonl", invalid_examples + exec_errors)
    if not conn:
        print("Execution accuracy unavailable: SQLite database was not provided or does not exist.")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
