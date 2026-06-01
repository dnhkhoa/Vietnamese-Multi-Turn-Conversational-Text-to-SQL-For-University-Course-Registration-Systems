import json
from pathlib import Path


DATA_DIR = Path("data/processed")
SPLITS = ["train", "dev", "test"]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def build_history(turns, current_index):
    """
    Lấy các turn trước current_index để làm history.
    current_index là vị trí của turn hiện tại trong list turns.
    """
    history_lines = []

    for turn in turns[:current_index]:
        history_lines.append(f"User: {turn['utterance']}")
        history_lines.append(f"SQL: {turn['sql']}")

    return "\n".join(history_lines)


def build_input(db_id, history, current_question):
    """
    Format input cho model Text-to-SQL.
    Bản v0.1 chưa đưa schema chi tiết vào, chỉ dùng db_id.
    Sau này có thể bổ sung schema từ tables.json.
    """
    if history:
        return (
            f"Database: {db_id}\n"
            f"History:\n{history}\n"
            f"Current question: {current_question}\n"
            f"Generate SQL:"
        )

    return (
        f"Database: {db_id}\n"
        f"Current question: {current_question}\n"
        f"Generate SQL:"
    )


def convert_split(split):
    in_path = DATA_DIR / f"multi_turn_{split}_v01.json"
    out_path = DATA_DIR / f"train_format_{split}_v01.json"

    if not in_path.exists():
        print(f"Missing file: {in_path}")
        return

    conversations = load_json(in_path)
    training_samples = []

    for conv in conversations:
        conversation_id = conv["conversation_id"]
        db_id = conv.get("db_id", "unknown")
        turns = conv.get("turns", [])

        for i, turn in enumerate(turns):
            history = build_history(turns, i)
            input_text = build_input(
                db_id=db_id,
                history=history,
                current_question=turn["utterance"]
            )

            sample = {
                "id": f"{conversation_id}_turn_{turn['turn_id']}",
                "conversation_id": conversation_id,
                "turn_id": turn["turn_id"],
                "db_id": db_id,
                "input": input_text,
                "output": turn["sql"],
                "operation": turn.get("operation", "unknown")
            }

            training_samples.append(sample)

    save_json(training_samples, out_path)

    print("=" * 80)
    print(f"Split: {split}")
    print("Conversations:", len(conversations))
    print("Training samples:", len(training_samples))
    print("Saved to:", out_path)

    if training_samples:
        print("\nExample:")
        print(json.dumps(training_samples[0], ensure_ascii=False, indent=2))


def main():
    for split in SPLITS:
        convert_split(split)


if __name__ == "__main__":
    main()