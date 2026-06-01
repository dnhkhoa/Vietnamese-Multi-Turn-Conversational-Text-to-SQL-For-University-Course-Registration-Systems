import json
import re
from collections import Counter
from pathlib import Path


DATA_DIR = Path("data/word-level")

FILES = {
    "train": DATA_DIR / "train.json",
    "dev": DATA_DIR / "dev.json",
    "test": DATA_DIR / "test.json",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_sql(sample):
    for key in ["query", "sql", "SQL"]:
        if key in sample:
            return sample[key]
    return ""


def get_question(sample):
    for key in ["question", "utterance", "text"]:
        if key in sample:
            return sample[key]
    return ""


def inspect_sql(sql):
    sql_upper = " " + sql.upper() + " "

    return {
        "has_where": " WHERE " in sql_upper,
        "has_order_by": " ORDER BY " in sql_upper,
        "has_group_by": " GROUP BY " in sql_upper,
        "has_having": " HAVING " in sql_upper,
        "has_limit": " LIMIT " in sql_upper,
        "has_join": " JOIN " in sql_upper,
        "has_nested": bool(re.search(r"\(\s*SELECT\s+", sql_upper)),
        "has_union": " UNION " in sql_upper,
        "has_intersect": " INTERSECT " in sql_upper,
        "has_except": " EXCEPT " in sql_upper,
    }


def inspect_file(name, path):
    print("=" * 80)
    print(f"File: {name}")
    print(f"Path: {path}")

    data = load_json(path)
    print("Total samples:", len(data))

    db_counter = Counter()
    stat_counter = Counter()

    missing_sql = 0
    missing_question = 0

    for sample in data:
        sql = get_sql(sample)
        question = get_question(sample)
        db_id = sample.get("db_id", "unknown")

        if not sql:
            missing_sql += 1
            continue

        if not question:
            missing_question += 1

        db_counter[db_id] += 1

        features = inspect_sql(sql)
        for k, v in features.items():
            if v:
                stat_counter[k] += 1

    print("Missing SQL:", missing_sql)
    print("Missing question:", missing_question)

    print("\nSQL statistics:")
    for k, v in stat_counter.items():
        print(f"{k}: {v}")

    print("\nNumber of DBs:", len(db_counter))

    print("\nTop 10 DBs:")
    for db, count in db_counter.most_common(10):
        print(db, count)

    print("\nFirst sample:")
    if data:
        print("Keys:", list(data[0].keys()))
        print("Question:", get_question(data[0]))
        print("SQL:", get_sql(data[0]))
        print("DB:", data[0].get("db_id"))


def main():
    for name, path in FILES.items():
        if path.exists():
            inspect_file(name, path)
        else:
            print(f"File not found: {path}")


if __name__ == "__main__":
    main()