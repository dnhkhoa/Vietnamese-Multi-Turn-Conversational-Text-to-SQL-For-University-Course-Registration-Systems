import argparse
import json
import re
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "data" / "processed"
SYSTEM_PROMPT = (
    "You are a Text-to-SQL assistant for a Vietnamese university course registration database. "
    "Generate only one valid SQLite SELECT query. Do not explain."
)
USER_TEMPLATE = """You are given a Vietnamese multi-turn question and a SQLite database schema.
Generate only one valid SQLite SELECT query.
Do not explain.
Do not use tables or columns outside the schema.
Do not generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, or multiple statements.

Schema:
{schema}

Dialogue history:
{history}

Current question:
{question}

SQL:"""


def open_dataset(path):
    path = Path(path)
    if path.is_file() and path.suffix.lower() == ".zip":
        tmp = tempfile.TemporaryDirectory()
        with zipfile.ZipFile(path) as zf:
            zf.extractall(tmp.name)
        return Path(tmp.name), tmp
    return path, None


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def split_from_name(path):
    name = path.name.lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", name) if token]
    for split in ("dev", "test", "valid", "validation", "train"):
        if split in tokens:
            return "dev" if split in {"valid", "validation"} else split
    return "train"


def schema_text(root):
    for name in ("schema.sql", "tables.json", "schema.json"):
        matches = list(root.rglob(name))
        if matches:
            path = matches[0]
            if path.suffix == ".sql":
                return path.read_text(encoding="utf-8")
            data = load_json(path)
            if isinstance(data, dict) and isinstance(data.get("tables"), dict):
                lines = [f"{table}({', '.join(cols)})" for table, cols in data["tables"].items()]
                fks = data.get("foreign_keys") or []
                if fks:
                    lines.append("Foreign keys:")
                    lines.extend(f"{src} -> {dst}" for src, dst in fks)
                return "\n".join(lines)
            return json.dumps(data, ensure_ascii=False, indent=2)
    return ""


def parse_training_input(text):
    schema = ""
    history = ""
    question = ""
    if "Schema:\n" in text:
        schema_part = text.split("Schema:\n", 1)[1]
        if "\nHistory:\n" in schema_part:
            schema, rest = schema_part.split("\nHistory:\n", 1)
            history, rest = rest.split("\nCurrent question:", 1)
        else:
            schema, rest = schema_part.split("\nCurrent question:", 1)
        question = rest.split("\nGenerate SQL:", 1)[0].strip()
    else:
        question_match = re.search(r"Current question:\s*(.*?)\nGenerate SQL:", text, flags=re.S)
        question = question_match.group(1).strip() if question_match else text.strip()
    return schema.strip(), history.strip() or "(none)", question.strip()


def make_row(row, split, default_schema):
    schema, history, question = parse_training_input(row.get("input", ""))
    schema = schema or default_schema
    user = USER_TEMPLATE.format(schema=schema, history=history, question=question)
    gold_sql = row.get("output", "").strip()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
        {"role": "assistant", "content": gold_sql},
    ]
    text = (
        f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n"
        f"<|im_start|>user\n{user}<|im_end|>\n"
        f"<|im_start|>assistant\n{gold_sql}<|im_end|>"
    )
    return {
        "id": row.get("id") or f"{split}_{row.get('conversation_id', 'unknown')}_{row.get('turn_id', 'x')}",
        "split": split,
        "messages": messages,
        "text": text,
        "gold_sql": gold_sql,
        "metadata": {
            "conversation_id": row.get("conversation_id"),
            "turn_id": row.get("turn_id"),
            "domain": row.get("domain"),
            "db_id": row.get("db_id"),
            "operation": row.get("operation"),
            "tags": row.get("tags", []),
            "difficulty": row.get("difficulty"),
        },
    }


def history_until(turns, index):
    lines = []
    for turn in turns[:index]:
        lines.append(f"User: {turn.get('utterance', '')}")
        lines.append(f"SQL: {turn.get('sql', '')}")
    return "\n".join(lines) or "(none)"


def rows_from_conversations(path, conversations, split, default_schema):
    rows = []
    for conv in conversations:
        turns = conv.get("turns", []) or []
        for idx, turn in enumerate(turns):
            user = USER_TEMPLATE.format(
                schema=default_schema,
                history=history_until(turns, idx),
                question=turn.get("utterance", ""),
            )
            sql = turn.get("sql", "").strip()
            rows.append(
                {
                    "id": f"{conv.get('conversation_id', path.stem)}_turn_{turn.get('turn_id', idx + 1)}",
                    "split": split,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": user},
                        {"role": "assistant", "content": sql},
                    ],
                    "text": f"<|im_start|>system\n{SYSTEM_PROMPT}<|im_end|>\n<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n{sql}<|im_end|>",
                    "gold_sql": sql,
                    "metadata": {
                        "conversation_id": conv.get("conversation_id"),
                        "turn_id": turn.get("turn_id"),
                        "domain": conv.get("domain"),
                        "db_id": conv.get("db_id"),
                        "operation": turn.get("operation"),
                        "tags": turn.get("tags", []),
                        "difficulty": turn.get("difficulty"),
                    },
                }
            )
    return rows


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset_path", required=True)
    parser.add_argument("--mode", choices=["direct_sql", "state_json"], default="direct_sql")
    args = parser.parse_args()
    if args.mode != "direct_sql":
        raise SystemExit("state_json is reserved for a later phase. Use --mode direct_sql.")
    root, tmp = open_dataset(args.dataset_path)
    skipped = []
    outputs = {"train": [], "dev": [], "test": []}
    try:
        default_schema = schema_text(root)
        json_files = [path for path in root.rglob("*.json") if path.is_file()]
        training_files = []
        conversation_files = []
        for path in json_files:
            try:
                data = load_json(path)
            except Exception as exc:
                skipped.append({"file": str(path), "reason": f"json_load_error:{exc}"})
                continue
            if isinstance(data, list) and data and isinstance(data[0], dict) and {"input", "output"}.issubset(data[0]):
                training_files.append((path, data))
            elif isinstance(data, list) and data and isinstance(data[0], dict) and "turns" in data[0]:
                conversation_files.append((path, data))
        if training_files:
            for path, data in training_files:
                split = split_from_name(path)
                for row in data:
                    try:
                        outputs[split].append(make_row(row, split, default_schema))
                    except Exception as exc:
                        skipped.append({"file": str(path), "id": row.get("id"), "reason": str(exc)})
        else:
            for path, data in conversation_files:
                split = split_from_name(path)
                outputs[split].extend(rows_from_conversations(path, data, split, default_schema))
        for split, rows in outputs.items():
            write_jsonl(OUT_DIR / f"{split}_sft.jsonl", rows)
            print(f"{split}: {len(rows)} rows")
        write_jsonl(OUT_DIR / "skipped_rows.jsonl", skipped)
        print(f"Skipped rows: {len(skipped)}")
    finally:
        if tmp:
            tmp.cleanup()


if __name__ == "__main__":
    main()
