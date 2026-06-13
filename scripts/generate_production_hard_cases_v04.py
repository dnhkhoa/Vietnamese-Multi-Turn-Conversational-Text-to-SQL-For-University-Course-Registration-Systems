from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.business_rules import DEFAULT_DB_PATH
from src.llm_state_parser import ParsedState, validate_state
from src.nl2sql_engine import VietnameseNL2SQLEngine


SYSTEM_PROMPT = (
    "Bạn là bộ phân tích state cho bài toán Vietnamese multi-turn text-to-SQL "
    "trong hệ thống đăng ký môn học. Chỉ trả JSON hợp lệ gồm intent, edit_operation, slots."
)


class ExpectedStateParser:
    def __init__(self) -> None:
        self.states: List[Dict[str, Any]] = []

    def set_states(self, states: Sequence[Dict[str, Any]]) -> None:
        self.states = [dict(state) for state in states]

    def parse(self, utterance: str, previous_state: Dict[str, Any]) -> ParsedState:
        if not self.states:
            raise RuntimeError("No expected state queued")
        state = self.states.pop(0)
        parsed = validate_state(state)
        return ParsedState(parsed.intent, parsed.edit_operation, dict(parsed.slots))


def state(intent: str, edit: str, slots: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"intent": intent, "edit_operation": edit, "slots": slots or {}}


def turn(utterance: str, intent: str, edit: str, slots: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"utterance": utterance, "expected_state": state(intent, edit, slots)}


def dialogue(dialogue_id: str, source: str, turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"dialogue_id": dialogue_id, "db_id": "course_registration", "source": source, "turns": turns}


def current_term(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute("SELECT NamHoc, HocKy FROM LopHP ORDER BY NamHoc DESC, HocKy DESC LIMIT 1").fetchone()
    return int(row[0]), int(row[1])


def students(conn: sqlite3.Connection, limit: int) -> List[str]:
    return [
        row[0]
        for row in conn.execute(
            """
            SELECT MaSV
            FROM SinhVien
            WHERE TrangThai = 'DANG_HOC'
            ORDER BY MaSV
            LIMIT :limit
            """,
            {"limit": limit},
        )
    ]


def df_hash(rows: List[Dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compact_rows(rows: List[Dict[str, Any]], max_rows: int) -> Dict[str, Any]:
    return {
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows[:max_rows],
        "rows_truncated": len(rows) > max_rows,
        "row_count": len(rows),
        "result_hash": df_hash(rows),
    }


def dataframe_rows(df, max_rows: int) -> Dict[str, Any]:
    records = df.fillna("").to_dict(orient="records") if not df.empty else []
    return compact_rows(records, max_rows)


def qwen_rows(dialogues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in dialogues:
        previous_state: Dict[str, Any] = {}
        for item_turn in item["turns"]:
            expected_state = item_turn["expected_state"]
            rows.append(
                {
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": json.dumps(
                                {"previous_state": previous_state, "utterance": item_turn["utterance"]},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        },
                        {"role": "assistant", "content": json.dumps(expected_state, ensure_ascii=False, sort_keys=True)},
                    ],
                    "metadata": {"dialogue_id": item["dialogue_id"], "source": item["source"]},
                }
            )
            previous_state = expected_state
    return rows


def eval_rows(dialogues: Sequence[Dict[str, Any]], db_path: Path, max_rows: int) -> List[Dict[str, Any]]:
    parser = ExpectedStateParser()
    engine = VietnameseNL2SQLEngine(db_path, state_parser=parser, parser_mode="hybrid")
    rows: List[Dict[str, Any]] = []
    try:
        for item in dialogues:
            previous_state: Dict[str, Any] = {}
            parser.set_states([turn_item["expected_state"] for turn_item in item["turns"]])
            engine.reset()
            for turn_id, turn_item in enumerate(item["turns"], start=1):
                expected_state = turn_item["expected_state"]
                result = engine.ask(turn_item["utterance"])
                rows.append(
                    {
                        "id": f"{item['dialogue_id']}_turn_{turn_id:02d}",
                        "dialogue_id": item["dialogue_id"],
                        "turn_id": turn_id,
                        "db_id": item["db_id"],
                        "source": item["source"],
                        "previous_state": previous_state,
                        "user_question": turn_item["utterance"],
                        "expected_state": expected_state,
                        "gold_sql": result.sql,
                        "gold_params": result.params,
                        "gold_message": result.message,
                        "gold_warnings": result.warnings,
                        "expected_result": dataframe_rows(result.dataframe, max_rows),
                    }
                )
                previous_state = expected_state
    finally:
        engine.close()
    return rows


def build_dialogues(student_ids: Sequence[str], nam_hoc: int, hoc_ky: int, count: int, seed: int) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    output: List[Dict[str, Any]] = []
    next_hoc_ky = hoc_ky + 1
    invalid_names = ["abcxyz", "blockchain lượng tử", "nhập môn phép thuật", "quản trị rồng số"]
    out_scope = [
        "hôm nay ăn gì",
        "thời tiết hôm nay thế nào",
        "đặt vé xe giúp tôi",
        "bitcoin hôm nay tăng không",
        "kể chuyện cười đi",
    ]
    soft_questions = [
        "môn nào nhẹ để học kỳ này",
        "môn nào dễ thở hơn cho tôi",
        "kỳ này nên chọn môn nào nhẹ",
        "môn nào phù hợp nếu tôi muốn giảm tải",
    ]
    missing_student_questions = [
        "kì này tôi nên đăng ký môn nào",
        "gợi ý môn cho tôi với",
        "tôi còn thiếu môn gì",
        "học kỳ này nên học môn nào",
    ]
    for idx in range(1, count + 1):
        student = student_ids[(idx - 1) % len(student_ids)]
        other = student_ids[(idx * 7) % len(student_ids)]
        kind = idx % 6
        if kind == 1:
            output.append(
                dialogue(
                    f"prod_hard_missing_student_{idx:04d}",
                    "production_missing_required_slot_v04",
                    [
                        turn(
                            rng.choice(missing_student_questions),
                            "COURSE_RECOMMENDATION",
                            "NEW_QUERY",
                            {"NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                        turn(
                            f"mssv của tôi là {student}",
                            "STUDENT_INFO_LOOKUP",
                            "CHANGE_INTENT",
                            {"MaSV": student},
                        ),
                        turn(
                            "vậy gợi ý lại giúp tôi",
                            "COURSE_RECOMMENDATION",
                            "CHANGE_INTENT",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                    ],
                )
            )
        elif kind == 2:
            invalid_name = rng.choice(invalid_names)
            output.append(
                dialogue(
                    f"prod_hard_invalid_entity_{idx:04d}",
                    "production_invalid_entity_v04",
                    [
                        turn(
                            f"môn {invalid_name} mấy tín chỉ",
                            "COURSE_INFO_SEARCH",
                            "NEW_QUERY",
                            {"TenMH": invalid_name},
                        ),
                        turn(
                            "nếu không có thì quay lại gợi ý môn kỳ này cho sinh viên " + student,
                            "COURSE_RECOMMENDATION",
                            "CHANGE_INTENT",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                    ],
                )
            )
        elif kind == 3:
            output.append(
                dialogue(
                    f"prod_hard_out_scope_{idx:04d}",
                    "production_out_of_scope_v04",
                    [
                        turn(rng.choice(out_scope), "OUT_OF_SCOPE", "NEW_QUERY", {}),
                        turn(
                            f"quay lại đăng ký môn, sinh viên {student} nên học gì kỳ này",
                            "COURSE_RECOMMENDATION",
                            "CHANGE_INTENT",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                    ],
                )
            )
        elif kind == 4:
            output.append(
                dialogue(
                    f"prod_hard_prereq_impact_{idx:04d}",
                    "production_prereq_impact_v04",
                    [
                        turn(
                            "nếu tôi không học CSDL kỳ này thì ảnh hưởng gì",
                            "PREREQUISITE_LOOKUP",
                            "NEW_QUERY",
                            {"MaMH": "DBSY230184E", "PrereqDirection": "REQUIRED_BY"},
                        ),
                        turn(
                            f"với sinh viên {student} thì có nên ưu tiên học CSDL không",
                            "REGISTRATION_ELIGIBILITY_CHECK",
                            "CHANGE_INTENT",
                            {"MaSV": student, "MaMH": "DBSY230184E", "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                    ],
                )
            )
        elif kind == 5:
            output.append(
                dialogue(
                    f"prod_hard_multi_student_{idx:04d}",
                    "production_multi_student_context_v04",
                    [
                        turn(
                            f"sinh viên {student} kỳ này nên đăng ký môn nào",
                            "COURSE_RECOMMENDATION",
                            "NEW_QUERY",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                        turn(
                            f"còn sinh viên {other} thì sao",
                            "COURSE_RECOMMENDATION",
                            "CHANGE_ENTITY",
                            {"MaSV": other, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                        turn(
                            "bạn thứ hai đã học những môn gì",
                            "STUDENT_RESULT_LOOKUP",
                            "CHANGE_INTENT",
                            {"MaSV": other},
                        ),
                        turn(
                            "quay lại sinh viên đầu tiên và chỉ lấy môn bắt buộc",
                            "COURSE_RECOMMENDATION",
                            "CHANGE_INTENT",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky, "LoaiYC": "BAT_BUOC"},
                        ),
                    ],
                )
            )
        else:
            output.append(
                dialogue(
                    f"prod_hard_ambiguous_advice_{idx:04d}",
                    "production_ambiguous_advice_v04",
                    [
                        turn(f"mssv {student} cần tư vấn", "STUDENT_INFO_LOOKUP", "NEW_QUERY", {"MaSV": student}),
                        turn(
                            rng.choice(soft_questions),
                            "COURSE_RECOMMENDATION",
                            "CHANGE_INTENT",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                        ),
                        turn(
                            "kỳ sau thì sao",
                            "COURSE_RECOMMENDATION",
                            "REPLACE_FILTER",
                            {"MaSV": student, "NamHoc": nam_hoc, "HocKy": next_hoc_ky},
                        ),
                    ],
                )
            )
    return output


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_report(path: Path, train_rows: List[Dict[str, Any]], eval_data: List[Dict[str, Any]]) -> None:
    intents = Counter()
    sources = Counter()
    edits = Counter()
    result_rows: Dict[str, List[int]] = defaultdict(list)
    for row in train_rows:
        assistant = json.loads(row["messages"][2]["content"])
        intents[assistant["intent"]] += 1
        edits[assistant["edit_operation"]] += 1
        sources[row["metadata"]["source"]] += 1
    for row in eval_data:
        result_rows[row["expected_state"]["intent"]].append(row["expected_result"]["row_count"])
    report = {
        "dataset": "production_hard_cases_v04",
        "train_rows": len(train_rows),
        "eval_rows": len(eval_data),
        "sources": dict(sources.most_common()),
        "intents": dict(intents.most_common()),
        "edit_operations": dict(edits.most_common()),
        "eval_row_count_by_intent": {
            intent: {
                "count": len(values),
                "zero": sum(value == 0 for value in values),
                "min": min(values),
                "max": max(values),
                "avg": round(sum(values) / len(values), 2),
            }
            for intent, values in sorted(result_rows.items())
        },
        "quality_gates": {
            "all_eval_rows_have_expected_state": all("expected_state" in row for row in eval_data),
            "all_train_states_validate": True,
            "contains_out_of_scope": intents["OUT_OF_SCOPE"] > 0,
            "contains_missing_required_slot": sources["production_missing_required_slot_v04"] > 0,
            "contains_invalid_entity": sources["production_invalid_entity_v04"] > 0,
            "contains_multi_student_context": sources["production_multi_student_context_v04"] > 0,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--count", type=int, default=180)
    parser.add_argument("--seed", type=int, default=20260613)
    parser.add_argument("--max-result-rows", type=int, default=100)
    parser.add_argument("--dialogues-output", type=Path, default=PROJECT_ROOT / "data" / "production_hard_dialogues_v04.jsonl")
    parser.add_argument("--qwen-output", type=Path, default=PROJECT_ROOT / "data" / "qwen_state_tracking_production_hard_v04.jsonl")
    parser.add_argument("--eval-output", type=Path, default=PROJECT_ROOT / "data" / "state_tracking_production_hard_eval_v04.jsonl")
    parser.add_argument("--report-output", type=Path, default=PROJECT_ROOT / "data" / "production_hard_quality_report_v04.json")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        nam_hoc, hoc_ky = current_term(conn)
        student_ids = students(conn, args.count + 20)
    finally:
        conn.close()

    dialogues = build_dialogues(student_ids, nam_hoc, hoc_ky, args.count, args.seed)
    train_rows = qwen_rows(dialogues)
    for row in train_rows:
        validate_state(json.loads(row["messages"][2]["content"]))
    eval_data = eval_rows(dialogues, args.db, args.max_result_rows)

    write_jsonl(args.dialogues_output, dialogues)
    write_jsonl(args.qwen_output, train_rows)
    write_jsonl(args.eval_output, eval_data)
    write_report(args.report_output, train_rows, eval_data)
    print(f"Wrote {len(train_rows)} train rows and {len(eval_data)} eval rows")


if __name__ == "__main__":
    main()
