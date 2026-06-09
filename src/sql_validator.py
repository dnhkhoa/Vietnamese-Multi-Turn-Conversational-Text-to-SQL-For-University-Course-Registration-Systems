import argparse
import json
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "processed" / "university_v02"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "database" / "university_registration.sqlite"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def iter_sql_items(dataset):
    for item in dataset:
        if "turns" in item:
            for turn in item["turns"]:
                yield {
                    "id": f"{item['conversation_id']}_turn_{turn['turn_id']}",
                    "sql": turn["sql"],
                }
        else:
            yield {
                "id": item.get("id") or f"{item.get('conversation_id', 'unknown')}_turn_{item.get('turn_id', 'unknown')}",
                "sql": item.get("output") or item.get("sql"),
            }


def validate_sql(conn, sql):
    conn.execute(f"SELECT 1 FROM ({sql}) AS candidate_query LIMIT 1").fetchall()


def validate_file(dataset_path, db_path):
    dataset = load_json(dataset_path)
    conn = sqlite3.connect(db_path)
    checked = 0
    failures = []
    try:
        for item in iter_sql_items(dataset):
            checked += 1
            try:
                validate_sql(conn, item["sql"])
            except Exception as exc:
                failures.append({
                    "id": item["id"],
                    "error": str(exc),
                    "sql": item["sql"],
                })
    finally:
        conn.close()

    return {
        "dataset": str(dataset_path),
        "db_path": str(db_path),
        "checked": checked,
        "valid": checked - len(failures),
        "invalid": len(failures),
        "failures": failures[:20],
    }


def main():
    parser = argparse.ArgumentParser(description="Validate generated SQL against the university_v02 SQLite database.")
    parser.add_argument("dataset", nargs="?", default=DEFAULT_DATA_DIR / "conversation" / "university_multi_turn_test_v02.json")
    parser.add_argument("--db", default=DEFAULT_DB_PATH)
    parser.add_argument("--fail-on-error", action="store_true")
    args = parser.parse_args()

    report = validate_file(Path(args.dataset), Path(args.db))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_error and report["invalid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
