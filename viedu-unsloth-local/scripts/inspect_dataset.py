import argparse
import json
import re
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = ROOT / "outputs" / "logs" / "dataset_inspection.json"


def dataset_root(path):
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp.name)
        return Path(tmp.name), tmp
    return path, None


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def split_from_name(path):
    name = path.name.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", name) if token]
    for split in ("dev", "test", "valid", "validation", "train"):
        if split in tokens:
            return "dev" if split in {"valid", "validation"} else split
    return "unknown"


def sql_features(sql):
    sql_u = f" {sql.upper()} "
    return {
        "JOIN": " JOIN " in sql_u,
        "LEFT JOIN": " LEFT JOIN " in sql_u,
        "GROUP BY": " GROUP BY " in sql_u,
        "HAVING": " HAVING " in sql_u,
        "ORDER BY": " ORDER BY " in sql_u,
        "LIMIT": " LIMIT " in sql_u,
        "COUNT": "COUNT(" in sql_u,
        "SUM": "SUM(" in sql_u,
        "AVG": "AVG(" in sql_u,
        "DISTINCT": " DISTINCT " in sql_u,
        "subquery": bool(re.search(r"\(\s*SELECT\s+", sql, flags=re.I)),
    }


def classify_json(path, data):
    if not isinstance(data, list) or not data:
        return "other"
    first = data[0]
    if isinstance(first, dict) and {"input", "output"}.issubset(first):
        return "training_format"
    if isinstance(first, dict) and "turns" in first:
        return "conversation"
    return "other"


def inspect_training(path, data, summary):
    split = split_from_name(path)
    bucket = summary["splits"][split]
    bucket["training_samples"] += len(data)
    bucket["conversation_ids"].update(str(row.get("conversation_id", "")) for row in data if row.get("conversation_id"))
    for row in data:
        text = row.get("input", "")
        sql = row.get("output", "")
        bucket["unique_utterances"].add(text)
        bucket["unique_sql"].add(sql)
        if row.get("operation"):
            summary["operation_distribution"][row["operation"]] += 1
        for tag in row.get("tags", []) or []:
            summary["tag_distribution"][tag] += 1
        for name, present in sql_features(sql).items():
            if present:
                summary["sql_feature_counts"][name] += 1


def inspect_conversation(path, data, summary):
    split = split_from_name(path)
    bucket = summary["splits"][split]
    bucket["conversations"] += len(data)
    for conv in data:
        turns = conv.get("turns", []) or []
        bucket["turns"] += len(turns)
        bucket["turns_per_conversation"].append(len(turns))
        for turn in turns:
            bucket["unique_utterances"].add(turn.get("utterance", ""))
            sql = turn.get("sql", "")
            bucket["unique_sql"].add(sql)
            if turn.get("operation"):
                summary["operation_distribution"][turn["operation"]] += 1
            for tag in turn.get("tags", []) or []:
                summary["tag_distribution"][tag] += 1
            for name, present in sql_features(sql).items():
                if present:
                    summary["sql_feature_counts"][name] += 1


def finalize(summary):
    for split, bucket in summary["splits"].items():
        turns_per = bucket.pop("turns_per_conversation")
        conv_ids = bucket.pop("conversation_ids")
        bucket["conversations_from_training_ids"] = len(conv_ids)
        bucket["unique_utterance_count"] = len(bucket.pop("unique_utterances"))
        bucket["unique_sql_count"] = len(bucket.pop("unique_sql"))
        bucket["avg_turns_per_conversation"] = round(sum(turns_per) / len(turns_per), 2) if turns_per else None
    summary["operation_distribution"] = dict(summary["operation_distribution"])
    summary["tag_distribution"] = dict(summary["tag_distribution"])
    summary["sql_feature_counts"] = dict(summary["sql_feature_counts"])
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_path", required=True)
    args = parser.parse_args()
    root, tmp = dataset_root(args.dataset_path)
    try:
        files = [path for path in root.rglob("*") if path.is_file()]
        summary = {
            "dataset_path": str(Path(args.dataset_path)),
            "files": [str(path.relative_to(root)) for path in files],
            "conversation_files": [],
            "training_format_files": [],
            "schema_files": [],
            "database_files": [],
            "evaluation_files": [],
            "splits": defaultdict(lambda: {
                "conversations": 0,
                "turns": 0,
                "training_samples": 0,
                "turns_per_conversation": [],
                "conversation_ids": set(),
                "unique_utterances": set(),
                "unique_sql": set(),
            }),
            "operation_distribution": Counter(),
            "tag_distribution": Counter(),
            "sql_feature_counts": Counter(),
        }
        for path in files:
            low = path.name.lower()
            if low in {"schema.sql", "seed_data.sql", "tables.json", "schema.json"}:
                summary["schema_files"].append(str(path.relative_to(root)))
            if path.suffix.lower() in {".sqlite", ".db"}:
                summary["database_files"].append(str(path.relative_to(root)))
            if "eval" in low or "evaluation" in low:
                summary["evaluation_files"].append(str(path.relative_to(root)))
            if path.suffix.lower() != ".json":
                continue
            data = load_json(path)
            kind = classify_json(path, data)
            if kind == "training_format":
                summary["training_format_files"].append(str(path.relative_to(root)))
                inspect_training(path, data, summary)
            elif kind == "conversation":
                summary["conversation_files"].append(str(path.relative_to(root)))
                inspect_conversation(path, data, summary)
        result = finalize(summary)
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOG_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"Saved: {LOG_PATH}")
    finally:
        if tmp:
            tmp.cleanup()


if __name__ == "__main__":
    main()
