from __future__ import annotations

import argparse
import json
import random
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "course_registration.db"
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "v04" / "augmentation_dialogues_v04.jsonl"


@dataclass(frozen=True)
class Course:
    code: str
    name: str


def turn(utterance: str, intent: str, operation: str, slots: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "utterance": utterance,
        "intent": intent,
        "edit_operation": operation,
        "slots": slots or {},
    }


def dialogue(dialogue_id: str, turns: Sequence[Dict[str, Any]], source: str) -> Dict[str, Any]:
    return {
        "dialogue_id": dialogue_id,
        "db_id": "course_registration",
        "source": source,
        "turns": list(turns),
    }


def write_jsonl(path: Path, rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_catalog(db_path: Path) -> tuple[List[Course], List[str]]:
    connection = sqlite3.connect(db_path)
    try:
        courses = [Course(str(code), str(name)) for code, name in connection.execute("SELECT MaMH, TenMH FROM MonHoc ORDER BY MaMH")]
        students = [str(row[0]) for row in connection.execute("SELECT MaSV FROM SinhVien ORDER BY MaSV")]
    finally:
        connection.close()
    if len(courses) < 2 or len(students) < 2:
        raise RuntimeError("Database needs at least two courses and two students")
    return courses, students


def course_text(course: Course, index: int) -> str:
    return course.code if index % 3 == 0 else course.name


def offering_flow(index: int, course: Course, replacement: Course, length: int) -> List[Dict[str, Any]]:
    semester = 1 + index % 2
    session = "SANG" if index % 2 == 0 else "CHIEU"
    session_text = "buổi sáng" if session == "SANG" else "buổi chiều"
    first_questions = [
        f"Cho mình xem lớp của môn {course_text(course, index)} với.",
        f"Môn {course_text(course, index)} kỳ này có lớp nào vậy?",
        f"co lop nao cua mon {course_text(course, index)} khong",
        f"Tìm giúp các lớp học phần {course_text(course, index)}.",
    ]
    questions = [
        first_questions[index % len(first_questions)],
        f"Mình chỉ xem học kỳ {semester} thôi.",
        "Cho xem luôn giờ học của mấy lớp đó.",
        f"Lọc lớp học {session_text} nhé.",
        "Chỉ giữ lớp nào vẫn còn chỗ.",
        f"Thế đổi qua môn {course_text(replacement, index + 1)} thì sao?",
        "Bỏ điều kiện buổi học đi.",
        "Lấy 5 lớp đầu là được.",
    ]
    states = [
        ("COURSE_OFFERING_SEARCH", "NEW_QUERY", {"MaMH": course.code}),
        ("COURSE_OFFERING_SEARCH", "ADD_FILTER", {"MaMH": course.code, "HocKy": semester}),
        ("COURSE_SCHEDULE_SEARCH", "CHANGE_INTENT", {"MaMH": course.code, "HocKy": semester}),
        ("COURSE_SCHEDULE_SEARCH", "ADD_FILTER", {"MaMH": course.code, "HocKy": semester, "Buoi": session}),
        ("COURSE_SCHEDULE_SEARCH", "ADD_FILTER", {"MaMH": course.code, "HocKy": semester, "Buoi": session, "CoTheDangKy": 1}),
        ("COURSE_SCHEDULE_SEARCH", "CHANGE_ENTITY", {"MaMH": replacement.code, "HocKy": semester, "Buoi": session, "CoTheDangKy": 1}),
        ("COURSE_SCHEDULE_SEARCH", "REMOVE_FILTER", {"MaMH": replacement.code, "HocKy": semester, "CoTheDangKy": 1}),
        ("COURSE_SCHEDULE_SEARCH", "LIMIT", {"MaMH": replacement.code, "HocKy": semester, "CoTheDangKy": 1, "Limit": 5}),
    ]
    return [turn(questions[i], *states[i]) for i in range(length)]


def course_info_flow(index: int, course: Course, replacement: Course, length: int) -> List[Dict[str, Any]]:
    questions = [
        f"Môn {course_text(course, index)} là môn gì?",
        "Môn này có mấy tín chỉ vậy?",
        "Muốn học môn đó thì phải qua môn nào trước?",
        f"Còn {course_text(replacement, index + 1)} thì cần học trước môn gì?",
        "Cho mình xem lại thông tin môn vừa đổi.",
        "Môn đó hiện có những lớp nào?",
        "Có lớp buổi chiều không?",
        "Cho 5 kết quả đầu thôi.",
    ]
    states = [
        ("COURSE_INFO_SEARCH", "NEW_QUERY", {"MaMH": course.code}),
        ("COURSE_INFO_SEARCH", "RESOLVE_REFERENCE", {"MaMH": course.code}),
        ("PREREQUISITE_LOOKUP", "CHANGE_INTENT", {"MaMH": course.code, "PrereqDirection": "PREREQUISITES_OF"}),
        ("PREREQUISITE_LOOKUP", "CHANGE_ENTITY", {"MaMH": replacement.code, "PrereqDirection": "PREREQUISITES_OF"}),
        ("COURSE_INFO_SEARCH", "CHANGE_INTENT", {"MaMH": replacement.code}),
        ("COURSE_OFFERING_SEARCH", "CHANGE_INTENT", {"MaMH": replacement.code}),
        ("COURSE_SCHEDULE_SEARCH", "CHANGE_INTENT", {"MaMH": replacement.code, "Buoi": "CHIEU"}),
        ("COURSE_SCHEDULE_SEARCH", "LIMIT", {"MaMH": replacement.code, "Buoi": "CHIEU", "Limit": 5}),
    ]
    return [turn(questions[i], *states[i]) for i in range(length)]


def credit_flow(index: int, student: str, replacement: str, length: int) -> List[Dict[str, Any]]:
    semester = 1 + index % 2
    questions = [
        f"Xem giúp mình thông tin sinh viên {student}.",
        "Bạn này đã tích lũy bao nhiêu tín chỉ rồi?",
        f"Riêng học kỳ {semester} thì bao nhiêu?",
        f"Đổi sang xem cho bạn {replacement} nhé.",
        "Bạn đó đã qua những môn nào?",
        f"Tổng tín chỉ kỳ {semester} của bạn ấy là bao nhiêu?",
        "Bỏ điều kiện học kỳ, tính tất cả đi.",
        "Hiện 5 dòng đầu thôi.",
    ]
    states = [
        ("STUDENT_INFO_LOOKUP", "NEW_QUERY", {"MaSV": student}),
        ("CREDIT_SUMMARY", "CHANGE_INTENT", {"MaSV": student}),
        ("CREDIT_SUMMARY", "ADD_FILTER", {"MaSV": student, "HocKy": semester}),
        ("CREDIT_SUMMARY", "CHANGE_ENTITY", {"MaSV": replacement, "HocKy": semester}),
        ("STUDENT_RESULT_LOOKUP", "CHANGE_INTENT", {"MaSV": replacement, "KetQua": "DAT"}),
        ("CREDIT_SUMMARY", "CHANGE_INTENT", {"MaSV": replacement, "HocKy": semester}),
        ("CREDIT_SUMMARY", "REMOVE_FILTER", {"MaSV": replacement}),
        ("CREDIT_SUMMARY", "LIMIT", {"MaSV": replacement, "Limit": 5}),
    ]
    return [turn(questions[i], *states[i]) for i in range(length)]


def statistics_flow(index: int, course: Course, replacement: Course, length: int) -> List[Dict[str, Any]]:
    semester = 1 + index % 2
    questions = [
        "Mỗi môn hiện có bao nhiêu lớp?",
        "Chỉ tính những lớp vẫn còn chỗ nhé.",
        "Cho mình 5 môn đầu tiên.",
        f"Có bao nhiêu sinh viên đăng ký môn {course_text(course, index)}?",
        f"Đổi sang thống kê môn {course_text(replacement, index + 1)}.",
        f"Thống kê số lớp ở học kỳ {semester} đi.",
        "Bỏ hết bộ lọc, đếm lại số lớp theo môn.",
        "Lấy 10 kết quả đầu thôi.",
    ]
    states = [
        ("AGGREGATION_STATISTICS", "NEW_QUERY", {}),
        ("AGGREGATION_STATISTICS", "AGGREGATE", {"CoTheDangKy": 1}),
        ("AGGREGATION_STATISTICS", "LIMIT", {"CoTheDangKy": 1, "Limit": 5}),
        ("AGGREGATION_STATISTICS", "AGGREGATE", {"MaMH": course.code}),
        ("AGGREGATION_STATISTICS", "CHANGE_ENTITY", {"MaMH": replacement.code}),
        ("AGGREGATION_STATISTICS", "AGGREGATE", {"HocKy": semester}),
        ("AGGREGATION_STATISTICS", "REMOVE_FILTER", {}),
        ("AGGREGATION_STATISTICS", "LIMIT", {"Limit": 10}),
    ]
    return [turn(questions[i], *states[i]) for i in range(length)]


def generate(db_path: Path, seed: int, dialogues_per_family: int, version: str = "v04") -> List[Dict[str, Any]]:
    courses, students = load_catalog(db_path)
    rng = random.Random(seed)
    families = (offering_flow, course_info_flow, credit_flow, statistics_flow)
    family_names = ("offering", "course_info", "credit", "statistics")
    rows: List[Dict[str, Any]] = []
    for family_index, (family, family_name) in enumerate(zip(families, family_names)):
        for index in range(dialogues_per_family):
            length = 2 + ((index + family_index) % 7)
            course, replacement = rng.sample(courses, 2)
            student, replacement_student = rng.sample(students, 2)
            if family is credit_flow:
                turns = family(index, student, replacement_student, length)
            else:
                turns = family(index, course, replacement, length)
            rows.append(
                dialogue(
                    f"{version}_{family_name}_{index + 1:04d}",
                    turns,
                    source=f"targeted_natural_synthetic_{version}",
                )
            )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate targeted, variable-length v04 augmentation dialogues")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--seed", type=int, default=20260621)
    parser.add_argument("--dialogues-per-family", type=int, default=120)
    parser.add_argument("--version", default="v04")
    args = parser.parse_args()
    rows = generate(args.db, args.seed, args.dialogues_per_family, version=args.version)
    write_jsonl(args.output, rows)
    lengths: Dict[int, int] = {}
    for row in rows:
        length = len(row["turns"])
        lengths[length] = lengths.get(length, 0) + 1
    print(json.dumps({"dialogues": len(rows), "turns": sum(len(row["turns"]) for row in rows), "lengths": lengths}, indent=2))


if __name__ == "__main__":
    main()
