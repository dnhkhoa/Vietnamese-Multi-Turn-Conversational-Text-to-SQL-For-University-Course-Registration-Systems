from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from generate_gap_aug_v03 import (
    DEFAULT_DB,
    current_term,
    eval_rows,
    load_students,
    qwen_rows,
    turn,
    write_jsonl,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


TRAIN_RECOMMENDATION = [
    "kì này tôi nên đăng ký môn nào",
    "ki nay toi nen dang ky mon nao",
    "học kỳ hiện tại gợi ý môn cho mình",
    "mình nên đăng kí gì ở hk này",
    "hk này nên học môn nào cho hợp lý",
    "gợi ý môn phù hợp cho tôi trong kỳ này",
    "tôi nên đăng ký gì kỳ này nếu còn thiếu môn",
    "môn nào nên ưu tiên đăng ký trước kỳ này",
    "với tiến độ hiện tại thì nên học môn gì tiếp",
    "tư vấn giúp tôi môn nên đăng ký học kỳ này",
]

EVAL_RECOMMENDATION = [
    "kỳ này mình nên chọn môn gì",
    "co the goi y mon hoc cho toi trong hoc ky nay khong",
    "dựa trên kết quả học tập, tôi nên đăng kí lớp nào",
    "học kỳ này còn môn nào phù hợp để đăng ký",
    "mình nên ưu tiên học môn nào trước trong kỳ hiện tại",
    "cho tôi danh sách môn nên đăng ký sắp tới",
]

TRAIN_STUDIED = [
    "tôi đã học những môn gì",
    "toi da hoc nhung mon gi",
    "mình đã qua những môn nào rồi",
    "cho tôi xem các môn đã học",
    "các môn tôi đã đạt là gì",
    "liệt kê môn mình đã học xong",
    "tôi đã hoàn thành những môn nào",
    "xem lịch sử các môn đã học của tôi",
]

EVAL_STUDIED = [
    "toi hoc xong nhung mon nao roi",
    "các môn đã qua của mình là gì",
    "cho xem transcript các môn đã đạt",
    "mình còn nhớ đã học môn nào không",
    "liệt kê những môn sinh viên này đã hoàn thành",
]

TRAIN_CURRENT_TERM = [
    "cho tôi những môn mở ở kì này",
    "cho toi nhung mon mo o ki nay",
    "các lớp đang mở hk này",
    "học kỳ hiện tại có lớp nào còn mở",
    "kì này trường mở những lớp nào",
    "ki nay co lop hoc phan nao dang mo",
    "các lớp học phần mở trong kỳ hiện tại",
]

EVAL_CURRENT_TERM = [
    "đợt này có lớp nào đang mở không",
    "hoc ky nay lop nao con mo",
    "danh sách học phần mở ở học kỳ hiện tại",
    "những lớp nào còn mở trong hk hiện tại",
    "kỳ đang đăng ký có môn nào mở",
]

CURRENT_TERM_HEADS_TRAIN = ["cho tôi", "liệt kê", "xem giúp tôi", "tôi muốn xem", "cần xem", "hiển thị"]
CURRENT_TERM_HEADS_EVAL = ["cho mình", "mở danh sách", "tra giúp", "mình cần biết", "xem thử", "cho xem"]
CURRENT_TERM_OBJECTS_TRAIN = [
    "những môn mở",
    "các lớp học phần mở",
    "lớp đang mở",
    "học phần còn mở",
    "môn học phần đang mở",
    "các lớp còn nhận đăng ký",
]
CURRENT_TERM_OBJECTS_EVAL = [
    "môn đang mở",
    "lớp học phần còn mở",
    "học phần mở đăng ký",
    "danh sách lớp mở",
    "các môn có lớp mở",
]
CURRENT_TERM_TIMES_TRAIN = ["ở kì này", "trong ki nay", "hk này", "học kỳ hiện tại", "kỳ đang đăng ký"]
CURRENT_TERM_TIMES_EVAL = ["đợt này", "hoc ky nay", "hk hiện tại", "kỳ hiện tại", "kỳ này"]

PROFILE_OPENERS = [
    "mình là mssv {student}",
    "tôi đăng nhập với mã sinh viên {student}",
    "hồ sơ hiện tại là sinh viên {student}",
    "mssv của tôi là {student}",
]

TRAIN_REQUIRED_FILTER = ["ưu tiên môn bắt buộc trước", "chỉ xem môn bắt buộc", "lọc môn bắt buộc giúp tôi"]
EVAL_REQUIRED_FILTER = ["ưu tiên học phần bắt buộc", "giữ lại nhóm bắt buộc thôi", "xem riêng các môn bắt buộc"]
TRAIN_ELECTIVE_FILTER = ["còn môn tự chọn thì sao", "đổi sang tự chọn", "nếu chỉ lấy tự chọn thì sao"]
EVAL_ELECTIVE_FILTER = ["chuyển qua nhóm tự chọn", "vậy các môn elective thì sao", "lọc riêng môn tự chọn"]
TRAIN_LIMIT = ["lấy 10 lớp đầu thôi", "giới hạn 10 kết quả", "cho xem 10 dòng trước"]
EVAL_LIMIT = ["chỉ trả trước 10 lớp", "rút gọn còn 10 kết quả", "hiện tối đa 10 học phần"]
TRAIN_PASSED_FILTER = ["chỉ lấy môn đã đạt", "lọc các môn qua rồi", "chỉ xem môn pass"]
EVAL_PASSED_FILTER = ["chỉ giữ môn đạt", "lọc những môn đã pass", "xem riêng các môn qua môn"]
TRAIN_RECOMMEND_RETURN = [
    "sau đó gợi ý môn nên đăng ký",
    "từ danh sách đó tư vấn môn nên đăng ký",
    "quay lại tư vấn đăng ký kỳ này",
]
EVAL_RECOMMEND_RETURN = [
    "tiếp tục đề xuất môn nên học",
    "quay về phần tư vấn đăng ký",
    "dựa trên đó đề xuất môn phù hợp",
]
TRAIN_SWITCH_RETURN = ["quay lại phần gợi ý đăng ký kỳ này", "vậy quay lại tư vấn môn nên học", "tiếp tục gợi ý đăng ký cho kỳ này"]
EVAL_SWITCH_RETURN = ["trở lại phần đề xuất môn học", "tư vấn tiếp môn nên đăng ký", "quay về gợi ý kỳ hiện tại"]

CURRENT_TERM = {
    "NamHoc": 2026,
    "HocKy": 2,
}


def dialogue(dialogue_id: str, source: str, turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "dialogue_id": dialogue_id,
        "db_id": "course_registration",
        "source": source,
        "turns": turns,
    }


def choose(rng: random.Random, values: Sequence[str]) -> str:
    return rng.choice(list(values))


def split_values(split: str, train_values: Sequence[str], eval_values: Sequence[str]) -> Sequence[str]:
    return eval_values if split == "eval" else train_values


def generated_current_term_question(idx: int, split: str) -> str:
    heads = CURRENT_TERM_HEADS_EVAL if split == "eval" else CURRENT_TERM_HEADS_TRAIN
    objects = CURRENT_TERM_OBJECTS_EVAL if split == "eval" else CURRENT_TERM_OBJECTS_TRAIN
    times = CURRENT_TERM_TIMES_EVAL if split == "eval" else CURRENT_TERM_TIMES_TRAIN
    head = heads[idx % len(heads)]
    obj = objects[(idx // len(heads)) % len(objects)]
    time = times[(idx // (len(heads) * len(objects))) % len(times)]
    return f"{head} {obj} {time}"


def build_profile_recommendation(
    idx: int,
    student: str,
    rng: random.Random,
    rec_questions: Sequence[str],
    split: str,
) -> Dict[str, Any]:
    base = {"MaSV": student}
    rec = {"MaSV": student, **CURRENT_TERM}
    return dialogue(
        f"advisor_{split}_recommendation_{idx:04d}",
        f"advisor_recommendation_{split}_v03",
        [
            turn(choose(rng, PROFILE_OPENERS).format(student=student), "STUDENT_INFO_LOOKUP", "NEW_QUERY", base),
            turn(choose(rng, rec_questions), "COURSE_RECOMMENDATION", "CHANGE_INTENT", rec),
            turn(
                choose(rng, split_values(split, TRAIN_REQUIRED_FILTER, EVAL_REQUIRED_FILTER)),
                "COURSE_RECOMMENDATION",
                "ADD_FILTER",
                {**rec, "LoaiYC": "BAT_BUOC"},
            ),
            turn(
                choose(rng, split_values(split, TRAIN_ELECTIVE_FILTER, EVAL_ELECTIVE_FILTER)),
                "COURSE_RECOMMENDATION",
                "REPLACE_FILTER",
                {**rec, "LoaiYC": "TU_CHON"},
            ),
        ],
    )


def build_studied_then_recommendation(
    idx: int,
    student: str,
    rng: random.Random,
    studied_questions: Sequence[str],
    rec_questions: Sequence[str],
    split: str,
) -> Dict[str, Any]:
    return dialogue(
        f"advisor_{split}_studied_{idx:04d}",
        f"advisor_studied_context_{split}_v03",
        [
            turn(f"sinh viên {student} đang theo chương trình nào", "STUDENT_INFO_LOOKUP", "NEW_QUERY", {"MaSV": student}),
            turn(choose(rng, studied_questions), "STUDENT_RESULT_LOOKUP", "RESOLVE_REFERENCE", {"MaSV": student}),
            turn(
                choose(rng, split_values(split, TRAIN_PASSED_FILTER, EVAL_PASSED_FILTER)),
                "STUDENT_RESULT_LOOKUP",
                "ADD_FILTER",
                {"MaSV": student, "KetQua": "DAT"},
            ),
            turn(
                choose(rng, rec_questions),
                "COURSE_RECOMMENDATION",
                "CHANGE_INTENT",
                {"MaSV": student, **CURRENT_TERM},
            ),
        ],
    )


def build_current_term_to_advising(
    idx: int,
    student: str,
    rng: random.Random,
    current_questions: Sequence[str],
    split: str,
) -> Dict[str, Any]:
    opened = {**CURRENT_TERM, "TrangThaiLHP": "MO"}
    local_idx = idx // 4
    limit = 5 + local_idx
    limit_templates = {
        "train": [
            "lấy {limit} lớp đầu thôi",
            "giới hạn {limit} kết quả",
            "cho xem {limit} dòng trước",
            "rút gọn còn {limit} lớp",
        ],
        "eval": [
            "chỉ trả trước {limit} lớp",
            "hiện tối đa {limit} học phần",
            "cho mình {limit} kết quả đầu",
            "giới hạn còn {limit} dòng",
        ],
    }[split]
    limit_utterance = limit_templates[local_idx % len(limit_templates)].format(limit=limit)
    return dialogue(
        f"advisor_{split}_current_term_{idx:04d}",
        f"advisor_current_term_{split}_v03",
        [
            turn(generated_current_term_question(local_idx, split), "COURSE_OFFERING_SEARCH", "NEW_QUERY", opened),
            turn(
                limit_utterance,
                "COURSE_OFFERING_SEARCH",
                "LIMIT",
                {**opened, "Limit": limit},
            ),
            turn(
                f"nếu xét theo CTĐT của sinh viên {student} thì kỳ này nên xem môn nào",
                "CURRICULUM_COURSE_SEARCH",
                "CHANGE_INTENT",
                {"MaSV": student, "HocKy": CURRENT_TERM["HocKy"]},
            ),
            turn(
                choose(rng, split_values(split, TRAIN_RECOMMEND_RETURN, EVAL_RECOMMEND_RETURN)),
                "COURSE_RECOMMENDATION",
                "CHANGE_INTENT",
                {"MaSV": student, **CURRENT_TERM},
            ),
        ],
    )


def build_context_switch_advising(
    idx: int,
    student: str,
    rng: random.Random,
    studied_questions: Sequence[str],
    rec_questions: Sequence[str],
    split: str,
) -> Dict[str, Any]:
    rec = {"MaSV": student, **CURRENT_TERM}
    return dialogue(
        f"advisor_{split}_switch_{idx:04d}",
        f"advisor_context_switch_{split}_v03",
        [
            turn(f"mssv {student} cần tư vấn đăng ký", "STUDENT_INFO_LOOKUP", "NEW_QUERY", {"MaSV": student}),
            turn(choose(rng, rec_questions), "COURSE_RECOMMENDATION", "CHANGE_INTENT", rec),
            turn(choose(rng, studied_questions), "STUDENT_RESULT_LOOKUP", "CHANGE_INTENT", {"MaSV": student}),
            turn(
                choose(rng, split_values(split, TRAIN_SWITCH_RETURN, EVAL_SWITCH_RETURN)),
                "COURSE_RECOMMENDATION",
                "CHANGE_INTENT",
                rec,
            ),
        ],
    )


def build_dialogues(
    students: Sequence[str],
    seed: int,
    count: int,
    split: str,
    rec_questions: Sequence[str],
    studied_questions: Sequence[str],
    current_questions: Sequence[str],
) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    factories = [
        build_profile_recommendation,
        build_studied_then_recommendation,
        build_current_term_to_advising,
        build_context_switch_advising,
    ]
    output = []
    for idx in range(1, count + 1):
        student = students[(idx - 1) % len(students)]
        factory = factories[(idx - 1) % len(factories)]
        if factory is build_profile_recommendation:
            item = factory(idx, student, rng, rec_questions, split)
        elif factory is build_studied_then_recommendation:
            item = factory(idx, student, rng, studied_questions, rec_questions, split)
        elif factory is build_current_term_to_advising:
            item = factory(idx, student, rng, current_questions, split)
        else:
            item = factory(idx, student, rng, studied_questions, rec_questions, split)
        output.append(item)
    return output


def normalize_question(text: str) -> str:
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def summarize_qwen(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    intents = Counter()
    edits = Counter()
    slots = Counter()
    sources = Counter()
    previous_count = 0
    normalized_questions = Counter()
    full_inputs = Counter()
    for row in rows:
        user_payload = json.loads(row["messages"][1]["content"])
        assistant_payload = json.loads(row["messages"][2]["content"])
        if user_payload.get("previous_state"):
            previous_count += 1
        normalized_questions[normalize_question(user_payload["utterance"])] += 1
        full_inputs[json.dumps(user_payload, ensure_ascii=False, sort_keys=True)] += 1
        sources[row["metadata"]["source"]] += 1
        intents[assistant_payload["intent"]] += 1
        edits[assistant_payload["edit_operation"]] += 1
        slots.update(assistant_payload.get("slots", {}).keys())
    return {
        "rows": len(rows),
        "sources": dict(sources.most_common()),
        "intents": dict(intents.most_common()),
        "edit_operations": dict(edits.most_common()),
        "slots": dict(slots.most_common()),
        "with_previous_state": previous_count,
        "duplicate_question_count": sum(count - 1 for count in normalized_questions.values() if count > 1),
        "duplicate_full_input_count": sum(count - 1 for count in full_inputs.values() if count > 1),
    }


def summarize_eval(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_intent: Dict[str, List[int]] = defaultdict(list)
    missing_gold = 0
    truncated = 0
    for row in rows:
        intent = row["expected_state"]["intent"]
        result = row["expected_result"]
        by_intent[intent].append(int(result.get("row_count", 0)))
        if not row.get("gold_sql") or not result.get("result_hash"):
            missing_gold += 1
        if result.get("rows_truncated"):
            truncated += 1
    return {
        "rows": len(rows),
        "missing_gold": missing_gold,
        "truncated_results": truncated,
        "row_count_by_intent": {
            intent: {
                "count": len(values),
                "zero": sum(value == 0 for value in values),
                "min": min(values),
                "max": max(values),
                "avg": round(sum(values) / len(values), 2),
            }
            for intent, values in sorted(by_intent.items())
        },
    }


def train_eval_overlap(train_rows: List[Dict[str, Any]], eval_rows_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    train_questions = {
        normalize_question(json.loads(row["messages"][1]["content"])["utterance"])
        for row in train_rows
    }
    eval_questions = {
        normalize_question(row["user_question"])
        for row in eval_rows_data
    }
    overlap = sorted(train_questions & eval_questions)
    return {
        "question_overlap_count": len(overlap),
        "question_overlap_examples": overlap[:20],
    }


def existing_train_overlap(
    train_rows: List[Dict[str, Any]],
    eval_rows_data: List[Dict[str, Any]],
    existing_paths: Sequence[Path],
) -> Dict[str, Any]:
    existing_questions = set()
    for path in existing_paths:
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if "messages" not in row:
                continue
            user_payload = json.loads(row["messages"][1]["content"])
            existing_questions.add(normalize_question(user_payload["utterance"]))
    train_questions = {
        normalize_question(json.loads(row["messages"][1]["content"])["utterance"])
        for row in train_rows
    }
    eval_questions = {
        normalize_question(row["user_question"])
        for row in eval_rows_data
    }
    train_overlap = sorted(train_questions & existing_questions)
    eval_overlap = sorted(eval_questions & existing_questions)
    return {
        "existing_question_count": len(existing_questions),
        "new_train_overlap_count": len(train_overlap),
        "new_train_overlap_examples": train_overlap[:20],
        "new_eval_overlap_count": len(eval_overlap),
        "new_eval_overlap_examples": eval_overlap[:20],
    }


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_markdown(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = f"""# Advisor Gap Dataset v03

This package adds advisor-oriented state-tracking data for model-only parsing.

## Outputs

- Train dialogues: `{report['files']['train_dialogues']}`
- Eval dialogues: `{report['files']['eval_dialogues']}`
- Train Qwen state tracking: `{report['files']['train_qwen']}`
- Eval with gold SQL/result: `{report['files']['eval_state']}`
- Quality report: `{report['files']['quality_report']}`

## Train Summary

```json
{json.dumps(report['train_qwen'], ensure_ascii=False, indent=2)}
```

## Eval Summary

```json
{json.dumps(report['eval_state'], ensure_ascii=False, indent=2)}
```

## Leakage Check

```json
{json.dumps(report['leakage'], ensure_ascii=False, indent=2)}
```

## Existing Dataset Overlap Check

```json
{json.dumps(report['existing_dataset_leakage'], ensure_ascii=False, indent=2)}
```

## Contract Note

The dataset intentionally introduces `COURSE_RECOMMENDATION`.
Production parser/backend must support this intent before merging the files into the main training set.
"""
    path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--train-dialogues-output", type=Path, default=PROJECT_ROOT / "data" / "advisor_gap_train_dialogues_v03.jsonl")
    parser.add_argument("--eval-dialogues-output", type=Path, default=PROJECT_ROOT / "data" / "advisor_gap_eval_dialogues_v03.jsonl")
    parser.add_argument("--train-qwen-output", type=Path, default=PROJECT_ROOT / "data" / "qwen_state_tracking_advisor_gap_train_v03.jsonl")
    parser.add_argument("--eval-output", type=Path, default=PROJECT_ROOT / "data" / "state_tracking_advisor_gap_eval_v03.jsonl")
    parser.add_argument("--quality-report-output", type=Path, default=PROJECT_ROOT / "data" / "advisor_gap_quality_report_v03.json")
    parser.add_argument("--markdown-report-output", type=Path, default=PROJECT_ROOT / "docs" / "advisor_gap_dataset_v03.md")
    parser.add_argument("--train-dialogues", type=int, default=240)
    parser.add_argument("--eval-dialogues", type=int, default=80)
    parser.add_argument("--seed", type=int, default=20260613)
    parser.add_argument("--max-result-rows", type=int, default=100)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        nam_hoc, hoc_ky = current_term(conn)
        CURRENT_TERM["NamHoc"] = nam_hoc
        CURRENT_TERM["HocKy"] = hoc_ky
        students = load_students(conn, limit=args.train_dialogues + args.eval_dialogues + 20)
        if len(students) < args.train_dialogues + args.eval_dialogues:
            raise RuntimeError("not enough students to create disjoint train/eval student splits")
        train_students = students[: args.train_dialogues]
        eval_students = students[args.train_dialogues : args.train_dialogues + args.eval_dialogues]

        train_dialogues = build_dialogues(
            train_students,
            args.seed,
            args.train_dialogues,
            "train",
            TRAIN_RECOMMENDATION,
            TRAIN_STUDIED,
            TRAIN_CURRENT_TERM,
        )
        eval_dialogues = build_dialogues(
            eval_students,
            args.seed + 99,
            args.eval_dialogues,
            "eval",
            EVAL_RECOMMENDATION,
            EVAL_STUDIED,
            EVAL_CURRENT_TERM,
        )
        train_qwen = qwen_rows(train_dialogues)
        eval_state = eval_rows(conn, eval_dialogues, args.max_result_rows)
    finally:
        conn.close()

    write_jsonl(args.train_dialogues_output, train_dialogues)
    write_jsonl(args.eval_dialogues_output, eval_dialogues)
    write_jsonl(args.train_qwen_output, train_qwen)
    write_jsonl(args.eval_output, eval_state)

    leakage = train_eval_overlap(train_qwen, eval_state)
    existing_leakage = existing_train_overlap(
        train_qwen,
        eval_state,
        [
            PROJECT_ROOT / "data" / "qwen_state_tracking_train_v02.jsonl",
            PROJECT_ROOT / "data" / "qwen_state_tracking_train.jsonl",
        ],
    )
    eval_summary = summarize_eval(eval_state)
    train_summary = summarize_qwen(train_qwen)
    report = {
        "dataset": "advisor_gap_dataset_v03",
        "current_term": dict(CURRENT_TERM),
        "files": {
            "train_dialogues": str(args.train_dialogues_output.relative_to(PROJECT_ROOT)),
            "eval_dialogues": str(args.eval_dialogues_output.relative_to(PROJECT_ROOT)),
            "train_qwen": str(args.train_qwen_output.relative_to(PROJECT_ROOT)),
            "eval_state": str(args.eval_output.relative_to(PROJECT_ROOT)),
            "quality_report": str(args.quality_report_output.relative_to(PROJECT_ROOT)),
            "markdown_report": str(args.markdown_report_output.relative_to(PROJECT_ROOT)),
        },
        "train_qwen": train_summary,
        "eval_state": eval_summary,
        "leakage": leakage,
        "existing_dataset_leakage": existing_leakage,
        "student_split": {
            "train_students": len(set(train_students)),
            "eval_students": len(set(eval_students)),
            "overlap": len(set(train_students) & set(eval_students)),
        },
        "quality_gates": {
            "no_train_eval_question_overlap": leakage["question_overlap_count"] == 0,
            "no_overlap_with_existing_qwen_train": existing_leakage["new_train_overlap_count"] == 0
            and existing_leakage["new_eval_overlap_count"] == 0,
            "no_duplicate_full_train_input": train_summary["duplicate_full_input_count"] == 0,
            "no_student_overlap": len(set(train_students) & set(eval_students)) == 0,
            "eval_has_gold_for_every_row": eval_summary["missing_gold"] == 0,
            "contains_course_recommendation": train_summary["intents"].get("COURSE_RECOMMENDATION", 0) > 0,
        },
    }
    write_json(args.quality_report_output, report)
    write_markdown(args.markdown_report_output, report)

    print(json.dumps(report["quality_gates"], ensure_ascii=False, indent=2))
    print(f"Wrote {len(train_qwen)} train samples and {len(eval_state)} eval rows")


if __name__ == "__main__":
    main()
