import json
from pathlib import Path
from tqdm import tqdm

from utils_sql import parse_simple_sql, build_sql, normalize_sql


IN_DIR = Path("data/processed")
OUT_DIR = Path("data/processed")

SPLITS = ["train", "dev", "test"]


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


def condition_to_vietnamese(condition):
    c = condition

    replacements = [
        (" >= ", " lớn hơn hoặc bằng "),
        (" <= ", " nhỏ hơn hoặc bằng "),
        (" != ", " khác "),
        (" <> ", " khác "),
        (" > ", " lớn hơn "),
        (" < ", " nhỏ hơn "),
        (" = ", " bằng "),
    ]

    for op, vi in replacements:
        if op in c:
            left, right = c.split(op, 1)
            return f"Trong đó {left.strip()} {vi} {right.strip()}"

    if " LIKE " in c.upper():
        return f"Trong đó thỏa điều kiện {c}"

    return f"Trong đó thỏa điều kiện {c}"


def order_to_vietnamese(order_item):
    col = order_item["column"]
    direction = order_item["direction"]

    if direction == "DESC":
        return f"Sắp xếp theo {col} giảm dần"
    return f"Sắp xếp theo {col} tăng dần"


def limit_to_vietnamese(limit_value):
    return f"Chỉ lấy {limit_value} kết quả đầu tiên"


def base_utterance(select_cols, table_name, first_condition=None):
    select_text = ", ".join(select_cols) if select_cols else "*"

    if first_condition:
        cond_vi = condition_to_vietnamese(first_condition)
        cond_vi = cond_vi.replace("Trong đó", "").strip()
        return f"Liệt_kê {select_text} từ bảng {table_name}, {cond_vi}"

    return f"Liệt_kê {select_text} từ bảng {table_name}"


def generate_conversation(sample, conv_id, split_name):
    original_sql = get_sql(sample)
    db_id = sample.get("db_id", "unknown")

    parsed = parse_simple_sql(original_sql)

    select_cols = parsed["select"]
    table_name = parsed["from"]
    conditions = parsed["where"]
    order_by = parsed["order_by"]
    limit = parsed["limit"]

    if not table_name:
        return None

    turns = []

    current_conditions = []
    current_order_by = []
    current_limit = None

    turn_id = 1

    if conditions:
        first_condition = conditions[0]
        current_conditions.append(first_condition)

        sql = build_sql(
            select_cols=select_cols,
            table_name=table_name,
            conditions=current_conditions,
            order_by=current_order_by,
            limit=current_limit
        )

        turns.append({
            "turn_id": turn_id,
            "utterance": base_utterance(select_cols, table_name, first_condition),
            "sql": sql,
            "operation": "filter_add"
        })

        turn_id += 1

        for cond in conditions[1:]:
            current_conditions.append(cond)

            sql = build_sql(
                select_cols=select_cols,
                table_name=table_name,
                conditions=current_conditions,
                order_by=current_order_by,
                limit=current_limit
            )

            turns.append({
                "turn_id": turn_id,
                "utterance": condition_to_vietnamese(cond),
                "sql": sql,
                "operation": "filter_add"
            })

            turn_id += 1

    else:
        sql = build_sql(
            select_cols=select_cols,
            table_name=table_name,
            conditions=current_conditions,
            order_by=current_order_by,
            limit=current_limit
        )

        turns.append({
            "turn_id": turn_id,
            "utterance": base_utterance(select_cols, table_name),
            "sql": sql,
            "operation": "select"
        })

        turn_id += 1

    if order_by:
        current_order_by = order_by

        sql = build_sql(
            select_cols=select_cols,
            table_name=table_name,
            conditions=current_conditions,
            order_by=current_order_by,
            limit=current_limit
        )

        if len(order_by) == 1:
            utterance = order_to_vietnamese(order_by[0])
        else:
            utterance = "Sắp_xếp kết_quả theo các cột đã yêu_cầu"

        turns.append({
            "turn_id": turn_id,
            "utterance": utterance,
            "sql": sql,
            "operation": "order_add"
        })

        turn_id += 1

    if limit:
        current_limit = limit

        sql = build_sql(
            select_cols=select_cols,
            table_name=table_name,
            conditions=current_conditions,
            order_by=current_order_by,
            limit=current_limit
        )

        turns.append({
            "turn_id": turn_id,
            "utterance": limit_to_vietnamese(limit),
            "sql": sql,
            "operation": "limit_add"
        })

        turn_id += 1

    if len(turns) < 2:
        return None

    return {
        "conversation_id": f"{split_name}_conv_{conv_id:06d}",
        "source_question": get_question(sample),
        "source_sql": normalize_sql(original_sql),
        "db_id": db_id,
        "turns": turns,
        "final_sql": turns[-1]["sql"]
    }


def process_split(split_name):
    in_path = IN_DIR / f"simple_{split_name}.json"
    out_path = OUT_DIR / f"multi_turn_{split_name}_v01.json"

    if not in_path.exists():
        print(f"File not found: {in_path}")
        return

    data = load_json(in_path)

    conversations = []
    conv_id = 1

    for sample in tqdm(data, desc=f"Generating {split_name}"):
        try:
            conv = generate_conversation(sample, conv_id, split_name)

            if conv:
                conversations.append(conv)
                conv_id += 1

        except Exception:
            continue

    save_json(conversations, out_path)

    print(f"\nSplit: {split_name}")
    print("Generated conversations:", len(conversations))
    print("Saved to:", out_path)

    if conversations:
        print("\nExample:")
        print(json.dumps(conversations[0], ensure_ascii=False, indent=2))


def main():
    for split_name in SPLITS:
        process_split(split_name)


if __name__ == "__main__":
    main()