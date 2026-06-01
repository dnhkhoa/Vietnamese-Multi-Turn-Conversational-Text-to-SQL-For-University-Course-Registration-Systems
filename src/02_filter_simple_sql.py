import json
import re
from pathlib import Path
from tqdm import tqdm
import sqlglot


DATA_DIR = Path("data/word-level")
OUT_DIR = Path("data/processed")

INPUT_FILES = {
    "train": DATA_DIR / "train.json",
    "dev": DATA_DIR / "dev.json",
    "test": DATA_DIR / "test.json",
}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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


def is_simple_sql(sql):
    sql_upper = " " + sql.upper() + " "

    banned_keywords = [
        " JOIN ",
        " GROUP BY ",
        " HAVING ",
        " UNION ",
        " INTERSECT ",
        " EXCEPT ",
    ]

    for kw in banned_keywords:
        if kw in sql_upper:
            return False

    if re.search(r"\(\s*SELECT\s+", sql_upper):
        return False

    if not sql_upper.strip().startswith("SELECT"):
        return False

    try:
        sqlglot.parse_one(sql)
    except Exception:
        return False

    return True


def process_split(split_name, input_path):
    data = load_json(input_path)
    simple_samples = []

    for sample in tqdm(data, desc=f"Filtering {split_name}"):
        sql = get_sql(sample)
        question = get_question(sample)

        if not sql or not question:
            continue

        if is_simple_sql(sql):
            simple_samples.append(sample)

    out_path = OUT_DIR / f"simple_{split_name}.json"
    save_json(simple_samples, out_path)

    print(f"\nSplit: {split_name}")
    print("Original samples:", len(data))
    print("Simple samples:", len(simple_samples))
    print("Saved to:", out_path)


def main():
    for split_name, input_path in INPUT_FILES.items():
        if input_path.exists():
            process_split(split_name, input_path)
        else:
            print(f"File not found: {input_path}")


if __name__ == "__main__":
    main()