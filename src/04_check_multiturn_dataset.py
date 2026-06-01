import json
from pathlib import Path
from collections import Counter


DATA_DIR = Path("data/processed")
SPLITS = ["train", "dev", "test"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def check_split(split):
    path = DATA_DIR / f"multi_turn_{split}_v01.json"

    if not path.exists():
        print(f"Missing file: {path}")
        return

    data = load_json(path)

    turn_counts = []
    operation_counter = Counter()
    db_counter = Counter()

    bad_final_sql = 0
    bad_turn_id = 0

    for conv in data:
        turns = conv.get("turns", [])
        turn_counts.append(len(turns))
        db_counter[conv.get("db_id", "unknown")] += 1

        if turns and conv.get("final_sql") != turns[-1].get("sql"):
            bad_final_sql += 1

        for i, turn in enumerate(turns, start=1):
            if turn.get("turn_id") != i:
                bad_turn_id += 1

            operation_counter[turn.get("operation", "unknown")] += 1

    print("=" * 80)
    print(f"Split: {split}")
    print("Conversations:", len(data))

    if turn_counts:
        print("Total turns:", sum(turn_counts))
        print("Average turns:", round(sum(turn_counts) / len(turn_counts), 2))
        print("Min turns:", min(turn_counts))
        print("Max turns:", max(turn_counts))

    print("Bad final_sql:", bad_final_sql)
    print("Bad turn_id:", bad_turn_id)

    print("\nOperation distribution:")
    for op, count in operation_counter.most_common():
        print(f"  {op}: {count}")

    print("\nTop DBs:")
    for db, count in db_counter.most_common(10):
        print(f"  {db}: {count}")


def main():
    for split in SPLITS:
        check_split(split)


if __name__ == "__main__":
    main()