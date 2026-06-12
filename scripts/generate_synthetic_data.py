from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Sequence

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.business_rules import DEFAULT_DB_PATH
from src.llm_state_parser import ParsedState
from src.nl2sql_engine import COURSE_ALIASES, MAJOR_ALIASES, VietnameseNL2SQLEngine


DEFAULT_SYNTHETIC_OUTPUT = PROJECT_ROOT / "data" / "synthetic_eval.jsonl"
DEFAULT_MANUAL_OUTPUT = PROJECT_ROOT / "data" / "manual_labeled_eval.jsonl"
DEFAULT_QWEN_OUTPUT = PROJECT_ROOT / "data" / "qwen_state_tracking_train.jsonl"
DEFAULT_STATE_EVAL_OUTPUT = PROJECT_ROOT / "data" / "state_tracking_eval_v02.jsonl"


@dataclass(frozen=True)
class CourseRef:
    ma_mh: str
    ten_mh: str
    aliases: Sequence[str]


@dataclass(frozen=True)
class MajorRef:
    ma_nganh: str
    ten_nganh: str
    aliases: Sequence[str]


@dataclass(frozen=True)
class CatalogData:
    courses: Sequence[CourseRef]
    majors: Sequence[MajorRef]
    students: Sequence[str]
    offerings: Sequence[str]
    prerequisite_course_ids: Sequence[str]


def load_catalog(db_path: Path) -> CatalogData:
    conn = sqlite3.connect(db_path)
    try:
        courses = []
        for ma_mh, ten_mh in conn.execute("SELECT MaMH, TenMH FROM MonHoc ORDER BY MaMH"):
            aliases = [ten_mh, ma_mh]
            aliases.extend(COURSE_ALIASES.get(ma_mh, []))
            courses.append(CourseRef(ma_mh=ma_mh, ten_mh=ten_mh, aliases=dedupe(aliases)))

        majors = []
        for ma_nganh, ten_nganh in conn.execute("SELECT MaNganh, TenNganh FROM Nganh ORDER BY MaNganh"):
            aliases = [ten_nganh, ma_nganh]
            aliases.extend(MAJOR_ALIASES.get(ma_nganh, []))
            majors.append(MajorRef(ma_nganh=ma_nganh, ten_nganh=ten_nganh, aliases=dedupe(aliases)))

        students = [
            row[0]
            for row in conn.execute(
                """
                SELECT MaSV
                FROM SinhVien
                WHERE TrangThai = 'DANG_HOC'
                ORDER BY MaSV
                LIMIT 200
                """
            )
        ]
        offerings = [row[0] for row in conn.execute("SELECT MaLHP FROM LopHP ORDER BY MaLHP LIMIT 240")]
        prerequisite_course_ids = [
            row[0]
            for row in conn.execute(
                """
                SELECT DISTINCT MaMH
                FROM TienQuyet
                ORDER BY MaMH
                """
            )
        ]
    finally:
        conn.close()
    return CatalogData(
        courses=courses,
        majors=majors,
        students=students,
        offerings=offerings,
        prerequisite_course_ids=prerequisite_course_ids,
    )


def dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        clean = str(value).strip()
        key = clean.lower()
        if clean and key not in seen:
            seen.add(key)
            result.append(clean)
    return result


def df_hash(df: pd.DataFrame) -> str:
    if df.empty:
        return "empty"
    normalized = df.fillna("").astype(str)
    records = normalized.to_dict(orient="records")
    payload = json.dumps(records, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compact_df(df: pd.DataFrame, max_rows: int = 2) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    return df.head(max_rows).fillna("").to_dict(orient="records")


def df_records(df: pd.DataFrame, max_rows: int) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    return df.head(max_rows).fillna("").to_dict(orient="records")


class ExpectedStateParser:
    def __init__(self) -> None:
        self._states: List[Dict[str, Any]] = []

    def set_states(self, states: Sequence[Dict[str, Any]]) -> None:
        self._states = [dict(state) for state in states]

    def parse(self, utterance: str, previous_state: Dict[str, Any]) -> ParsedState:
        if not self._states:
            raise RuntimeError("ExpectedStateParser has no state queued")
        state = self._states.pop(0)
        return ParsedState(
            intent=state["intent"],
            edit_operation=state["edit_operation"],
            slots=dict(state.get("slots", {})),
        )


def turn(
    utterance: str,
    intent: str,
    edit: str,
    slots: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "utterance": utterance,
        "intent": intent,
        "edit_operation": edit,
        "slots": slots or {},
    }


def dialogue(dialogue_id: str, source: str, turns: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "dialogue_id": dialogue_id,
        "db_id": "course_registration",
        "source": source,
        "turns": turns,
    }


def slots_with(base: Dict[str, Any], **updates: Any) -> Dict[str, Any]:
    output = dict(base)
    output.update({key: value for key, value in updates.items() if value is not None})
    return output


def alias(ref: CourseRef | MajorRef, rng: random.Random) -> str:
    candidates = list(ref.aliases)
    return rng.choice(candidates[: min(len(candidates), 8)])


def course_by_id(catalog: CatalogData, ma_mh: str) -> CourseRef:
    for course in catalog.courses:
        if course.ma_mh == ma_mh:
            return course
    return catalog.courses[0]


def prerequisite_course(catalog: CatalogData, rng: random.Random) -> CourseRef:
    if catalog.prerequisite_course_ids:
        return course_by_id(catalog, rng.choice(catalog.prerequisite_course_ids))
    return rng.choice(catalog.courses)


def synthetic_offer_schedule(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    course = rng.choice(catalog.courses)
    replacement = rng.choice([c for c in catalog.courses if c.ma_mh != course.ma_mh])
    day = rng.choice([2, 3, 4, 5, 6, 7])
    buoi_text, buoi = rng.choice([("buổi sáng", "SANG"), ("buổi chiều", "CHIEU")])
    base = {"MaMH": course.ma_mh}
    filtered = slots_with(base, Buoi=buoi, CoTheDangKy=1)
    changed = slots_with(filtered, MaMH=replacement.ma_mh)
    final_is_sort = rng.random() < 0.67
    final_utterance = rng.choice(["Sắp theo thứ trong tuần", "Sắp theo thứ"]) if final_is_sort else f"Chỉ lấy thứ {day}"
    final_slots = slots_with(changed, **({"SortBy": "Thu"} if final_is_sort else {"Thu": day}))
    return dialogue(
        f"syn_offer_schedule_{idx:05d}",
        "template_synthetic_30k",
        [
            turn(rng.choice([
                f"Cho tôi xem các lớp môn {alias(course, rng)}",
                f"Tìm lớp học phần của môn {alias(course, rng)}",
                f"Liệt kê lớp môn {alias(course, rng)}",
            ]), "COURSE_OFFERING_SEARCH", "NEW_QUERY", base),
            turn(rng.choice([
                f"Chỉ lấy lớp {buoi_text} còn chỗ",
                f"Lọc lớp {buoi_text} còn chỗ",
                f"Chỉ xem lớp {buoi_text} đăng ký được",
            ]), "COURSE_SCHEDULE_SEARCH", "ADD_FILTER", filtered),
            turn(rng.choice([
                f"Đổi sang môn {alias(replacement, rng)}",
                f"Chuyển sang môn {alias(replacement, rng)}",
                f"Thế môn {alias(replacement, rng)} thì sao?",
            ]), "COURSE_SCHEDULE_SEARCH", "CHANGE_ENTITY", changed),
            turn(final_utterance, "COURSE_SCHEDULE_SEARCH", "SORT" if final_is_sort else "ADD_FILTER", final_slots),
        ],
    )


def synthetic_course_info(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    course = rng.choice(catalog.courses)
    replacement = rng.choice([c for c in catalog.courses if c.ma_mh != course.ma_mh])
    base = {"MaMH": course.ma_mh}
    return dialogue(
        f"syn_course_info_{idx:05d}",
        "template_synthetic_30k",
        [
            turn(rng.choice([
                f"Môn {alias(course, rng)} mấy tín chỉ?",
                f"Số tín chỉ của môn {alias(course, rng)} là bao nhiêu?",
                f"Thông tin môn {alias(course, rng)}",
            ]), "COURSE_INFO_SEARCH", "NEW_QUERY", base),
            turn("Môn này thuộc ngành nào?", "COURSE_INFO_SEARCH", "RESOLVE_REFERENCE", base),
            turn(rng.choice([
                "Môn này cần học trước môn gì?",
                "Điều kiện tiên quyết của môn này là gì?",
                "Trước khi học môn này cần qua môn nào?",
            ]), "PREREQUISITE_LOOKUP", "RESOLVE_REFERENCE", slots_with(base, PrereqDirection="PREREQUISITES_OF")),
            turn(rng.choice([
                f"Còn môn {alias(replacement, rng)} thì sao?",
                f"Đổi sang môn {alias(replacement, rng)}",
            ]), "PREREQUISITE_LOOKUP", "CHANGE_ENTITY", {"MaMH": replacement.ma_mh, "PrereqDirection": "PREREQUISITES_OF"}),
        ],
    )


def synthetic_curriculum(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    major = rng.choice(catalog.majors)
    semester = rng.randint(1, 8)
    loai = rng.choice(["BAT_BUOC", "TU_CHON"])
    loai_text = "bắt buộc" if loai == "BAT_BUOC" else "tự chọn"
    opposite = "TU_CHON" if loai == "BAT_BUOC" else "BAT_BUOC"
    opposite_text = "tự chọn" if opposite == "TU_CHON" else "bắt buộc"
    base = {"MaNganh": major.ma_nganh, "LoaiYC": loai}
    sem_slots = slots_with(base, HocKy=semester)
    return dialogue(
        f"syn_curriculum_{idx:05d}",
        "template_synthetic_30k",
        [
            turn(rng.choice([
                f"Ngành {alias(major, rng)} có những môn {loai_text} nào?",
                f"Các môn {loai_text} của ngành {alias(major, rng)}",
            ]), "CURRICULUM_COURSE_SEARCH", "NEW_QUERY", base),
            turn(rng.choice([
                f"Chỉ học kỳ {semester}",
                f"Lọc học kỳ {semester}",
                f"Chỉ xem học kỳ {semester}",
            ]), "CURRICULUM_COURSE_SEARCH", "ADD_FILTER", sem_slots),
            turn(f"Đổi sang môn {opposite_text}", "CURRICULUM_COURSE_SEARCH", "REPLACE_FILTER", slots_with(sem_slots, LoaiYC=opposite)),
            turn("Lấy 5 môn đầu thôi", "CURRICULUM_COURSE_SEARCH", "LIMIT", slots_with(sem_slots, LoaiYC=opposite, Limit=5)),
        ],
    )


def synthetic_student(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    student = rng.choice(catalog.students)
    semester = rng.choice([1, 2])
    course = rng.choice(catalog.courses)
    return dialogue(
        f"syn_student_{idx:05d}",
        "template_synthetic_30k",
        [
            turn(rng.choice([
                f"Thông tin sinh viên {student}",
                f"Sinh viên {student} học ngành nào?",
                f"Sinh viên {student} theo chương trình nào?",
            ]), "STUDENT_INFO_LOOKUP", "NEW_QUERY", {"MaSV": student}),
            turn(rng.choice([
                f"Bạn này đã đăng ký những lớp nào kỳ {semester}?",
                f"Lịch học của sinh viên này kỳ {semester}",
            ]), "STUDENT_REGISTRATION_LOOKUP", "RESOLVE_REFERENCE", {"MaSV": student, "HocKy": semester}),
            turn(rng.choice([
                "Bạn này rớt môn nào?",
                "Sinh viên này chưa đạt môn nào?",
            ]), "STUDENT_RESULT_LOOKUP", "RESOLVE_REFERENCE", {"MaSV": student, "KetQua": "KHONG_DAT"}),
            turn(f"Tổng tín chỉ kỳ {semester} của sinh viên này", "CREDIT_SUMMARY", "CHANGE_INTENT", {"MaSV": student, "HocKy": semester}),
        ],
    )


def synthetic_eligibility(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    student = rng.choice(catalog.students)
    course = rng.choice(catalog.courses)
    replacement = rng.choice([c for c in catalog.courses if c.ma_mh != course.ma_mh])
    offering = rng.choice(catalog.offerings)
    semester = rng.choice([1, 2])
    return dialogue(
        f"syn_eligibility_{idx:05d}",
        "template_synthetic_30k",
        [
            turn(
                f"Sinh viên {student} đăng ký được môn {alias(course, rng)} không?",
                "REGISTRATION_ELIGIBILITY_CHECK",
                "NEW_QUERY",
                {"MaSV": student, "MaMH": course.ma_mh},
            ),
            turn(
                f"Vậy môn {alias(replacement, rng)} thì sao?",
                "REGISTRATION_ELIGIBILITY_CHECK",
                "CHANGE_ENTITY",
                {"MaSV": student, "MaMH": replacement.ma_mh},
            ),
            turn(
                f"Lớp {offering} còn đăng ký được cho sinh viên {student} không?",
                "REGISTRATION_ELIGIBILITY_CHECK",
                "CHANGE_ENTITY",
                {"MaSV": student, "MaLHP": offering},
            ),
            turn(
                f"Sinh viên {student} đăng ký được môn {alias(course, rng)} học kỳ {semester} không?",
                "REGISTRATION_ELIGIBILITY_CHECK",
                "NEW_QUERY",
                {"MaSV": student, "MaMH": course.ma_mh, "HocKy": semester},
            ),
        ],
    )


def synthetic_statistics(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    course = rng.choice(catalog.courses)
    semester = rng.choice([1, 2])
    use_semester = rng.random() < 0.5
    stats_utterance = (
        f"Môn {alias(course, rng)} kỳ {semester} có bao nhiêu sinh viên đăng ký?"
        if use_semester
        else f"Có bao nhiêu sinh viên đăng ký môn {alias(course, rng)}?"
    )
    stats_slots = slots_with({"MaMH": course.ma_mh}, **({"HocKy": semester} if use_semester else {}))
    stats_edit = "CHANGE_ENTITY" if use_semester else "AGGREGATE"
    return dialogue(
        f"syn_statistics_{idx:05d}",
        "template_synthetic_30k",
        [
            turn("Mỗi môn có bao nhiêu lớp?", "AGGREGATION_STATISTICS", "NEW_QUERY", {}),
            turn("Đếm số lớp còn chỗ theo từng môn", "AGGREGATION_STATISTICS", "AGGREGATE", {"CoTheDangKy": 1}),
            turn("Lấy 5 môn đầu thôi", "AGGREGATION_STATISTICS", "LIMIT", {"CoTheDangKy": 1, "Limit": 5}),
            turn(stats_utterance, "AGGREGATION_STATISTICS", stats_edit, stats_slots),
        ],
    )


def synthetic_registration_lookup(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    student = rng.choice(catalog.students)
    course = rng.choice(catalog.courses)
    semester = rng.choice([1, 2])
    return dialogue(
        f"syn_registration_{idx:05d}",
        "template_synthetic_30k",
        [
            turn(f"Sinh viên {student} đã đăng ký những lớp nào?", "STUDENT_REGISTRATION_LOOKUP", "NEW_QUERY", {"MaSV": student}),
            turn(f"Chỉ xem học kỳ {semester}", "STUDENT_REGISTRATION_LOOKUP", "ADD_FILTER", {"MaSV": student, "HocKy": semester}),
            turn(
                f"Bạn này đã đăng ký môn {alias(course, rng)} chưa?",
                "STUDENT_REGISTRATION_LOOKUP",
                "RESOLVE_REFERENCE",
                {"MaSV": student, "HocKy": semester, "MaMH": course.ma_mh},
            ),
            turn("Bỏ điều kiện học kỳ", "STUDENT_REGISTRATION_LOOKUP", "REMOVE_FILTER", {"MaSV": student, "MaMH": course.ma_mh}),
        ],
    )


def synthetic_context_switch(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    student = rng.choice(catalog.students)
    other_student = rng.choice([value for value in catalog.students if value != student])
    first_course = prerequisite_course(catalog, rng)
    second_course = rng.choice([course for course in catalog.courses if course.ma_mh != first_course.ma_mh])
    semester = rng.choice([1, 2])
    return dialogue(
        f"syn_context_switch_{idx:05d}",
        "stateful_context_switch_v02",
        [
            turn(
                rng.choice([
                    f"Em là sinh viên {student}, em học được môn {alias(first_course, rng)} chưa?",
                    f"Kiểm tra giúp {student} có đăng ký được {alias(first_course, rng)} không.",
                    f"Với hồ sơ của sinh viên {student}, môn {alias(first_course, rng)} có đăng ký được không?",
                ]),
                "REGISTRATION_ELIGIBILITY_CHECK",
                "NEW_QUERY",
                {"MaSV": student, "MaMH": first_course.ma_mh},
            ),
            turn(
                rng.choice([
                    f"Vậy đổi sang môn {alias(second_course, rng)} thì sao?",
                    f"Nếu thay bằng {alias(second_course, rng)} thì kết quả thế nào?",
                    f"Còn {alias(second_course, rng)} thì sinh viên này học được không?",
                ]),
                "REGISTRATION_ELIGIBILITY_CHECK",
                "CHANGE_ENTITY",
                {"MaSV": student, "MaMH": second_course.ma_mh},
            ),
            turn(
                f"Thử kiểm tra cùng môn đó cho sinh viên {other_student}.",
                "REGISTRATION_ELIGIBILITY_CHECK",
                "CHANGE_ENTITY",
                {"MaSV": other_student, "MaMH": second_course.ma_mh},
            ),
            turn(
                rng.choice([
                    f"Quay lại sinh viên {student}, chỉ xét học kỳ {semester}.",
                    f"Vẫn là bạn {student}, lọc học kỳ {semester} thôi.",
                ]),
                "REGISTRATION_ELIGIBILITY_CHECK",
                "REPLACE_FILTER",
                {"MaSV": student, "MaMH": second_course.ma_mh, "HocKy": semester},
            ),
            turn(
                "Quay lại môn ban đầu, bạn đó còn thiếu tiên quyết gì?",
                "PREREQUISITE_LOOKUP",
                "CHANGE_INTENT",
                {"MaSV": student, "MaMH": first_course.ma_mh, "PrereqDirection": "PREREQUISITES_OF"},
            ),
            turn(
                "Còn những môn bạn đó đã qua thì liệt kê lại.",
                "STUDENT_RESULT_LOOKUP",
                "CHANGE_INTENT",
                {"MaSV": student, "KetQua": "DAT"},
            ),
        ],
    )


def synthetic_student_profile_advising(idx: int, rng: random.Random, catalog: CatalogData) -> Dict[str, Any]:
    student = rng.choice(catalog.students)
    target_course = prerequisite_course(catalog, rng)
    semester = rng.choice([2, 3, 4, 5])
    return dialogue(
        f"syn_profile_advising_{idx:05d}",
        "student_profile_advising_v02",
        [
            turn(
                rng.choice([
                    f"Mình là MSSV {student}, cho mình xem ngành và chương trình đào tạo.",
                    f"Hồ sơ sinh viên {student} đang theo ngành nào và CTĐT nào?",
                    f"Tra cứu profile học tập của sinh viên {student}.",
                ]),
                "STUDENT_INFO_LOOKUP",
                "NEW_QUERY",
                {"MaSV": student},
            ),
            turn(
                f"Theo CTĐT của mình, học kỳ {semester} nên học những môn nào?",
                "CURRICULUM_COURSE_SEARCH",
                "RESOLVE_REFERENCE",
                {"MaSV": student, "HocKy": semester},
            ),
            turn(
                "Chỉ lấy các môn bắt buộc trong danh sách đó.",
                "CURRICULUM_COURSE_SEARCH",
                "ADD_FILTER",
                {"MaSV": student, "HocKy": semester, "LoaiYC": "BAT_BUOC"},
            ),
            turn(
                rng.choice([
                    f"Với kết quả học tập hiện tại, mình học được {alias(target_course, rng)} chưa?",
                    f"Mình có đủ điều kiện đăng ký môn {alias(target_course, rng)} không?",
                    f"Xem giúp mình môn {alias(target_course, rng)} có bị thiếu tiên quyết không.",
                ]),
                "REGISTRATION_ELIGIBILITY_CHECK",
                "CHANGE_INTENT",
                {"MaSV": student, "MaMH": target_course.ma_mh},
            ),
            turn(
                "Nếu chưa được thì thiếu môn tiên quyết nào?",
                "PREREQUISITE_LOOKUP",
                "RESOLVE_REFERENCE",
                {"MaSV": student, "MaMH": target_course.ma_mh, "PrereqDirection": "PREREQUISITES_OF"},
            ),
            turn(
                "Cho xem các môn mình đã đạt để đối chiếu.",
                "STUDENT_RESULT_LOOKUP",
                "CHANGE_INTENT",
                {"MaSV": student, "KetQua": "DAT"},
            ),
        ],
    )


SYNTHETIC_FACTORIES: Sequence[Callable[[int, random.Random, CatalogData], Dict[str, Any]]] = [
    synthetic_offer_schedule,
    synthetic_course_info,
    synthetic_curriculum,
    synthetic_student,
    synthetic_eligibility,
    synthetic_statistics,
    synthetic_registration_lookup,
    synthetic_context_switch,
    synthetic_student_profile_advising,
]


def generate_synthetic_dialogues(target_turns: int, seed: int, catalog: CatalogData) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    dialogues = []
    turns = 0
    idx = 1
    while turns < target_turns:
        factory = SYNTHETIC_FACTORIES[(idx - 1) % len(SYNTHETIC_FACTORIES)]
        item = factory(idx, rng, catalog)
        if turns + len(item["turns"]) > target_turns:
            item["turns"] = item["turns"][: target_turns - turns]
        dialogues.append(item)
        turns += len(item["turns"])
        idx += 1
    return dialogues


def generate_manual_labeled_dialogues(target_turns: int, seed: int, catalog: CatalogData) -> List[Dict[str, Any]]:
    """Curated hard labeled examples. These are author-labeled synthetic/manual-style cases."""
    rng = random.Random(seed + 777)
    dialogues = []
    turns = 0
    idx = 1
    hard_openers = [
        lambda s, c, _m, _o: [
            turn(f"sv {s} xem lịch hk1", "STUDENT_REGISTRATION_LOOKUP", "NEW_QUERY", {"MaSV": s, "HocKy": 1}),
            turn(f"có đk được {alias(c, rng)} không", "REGISTRATION_ELIGIBILITY_CHECK", "CHANGE_INTENT", {"MaSV": s, "MaMH": c.ma_mh}),
            turn("môn đó thiếu tiên quyết gì", "PREREQUISITE_LOOKUP", "RESOLVE_REFERENCE", {"MaSV": s, "MaMH": c.ma_mh, "PrereqDirection": "PREREQUISITES_OF"}),
            turn("cho xem kết quả môn đó", "STUDENT_RESULT_LOOKUP", "RESOLVE_REFERENCE", {"MaSV": s, "MaMH": c.ma_mh}),
        ],
        lambda s, c, m, _o: [
            turn(f"ngành {alias(m, rng)} kỳ 3 có môn nào", "CURRICULUM_COURSE_SEARCH", "NEW_QUERY", {"MaNganh": m.ma_nganh, "HocKy": 3}),
            turn("lọc môn bắt buộc thôi", "CURRICULUM_COURSE_SEARCH", "ADD_FILTER", {"MaNganh": m.ma_nganh, "HocKy": 3, "LoaiYC": "BAT_BUOC"}),
            turn(f"đổi qua {alias(c, rng)} mấy tín chỉ", "COURSE_INFO_SEARCH", "CHANGE_INTENT", {"MaMH": c.ma_mh}),
            turn("môn này có lớp chiều còn slot không", "COURSE_SCHEDULE_SEARCH", "RESOLVE_REFERENCE", {"MaMH": c.ma_mh, "Buoi": "CHIEU", "CoTheDangKy": 1}),
        ],
        lambda s, c, _m, o: [
            turn(f"lhp {o} học thứ mấy phòng nào", "COURSE_SCHEDULE_SEARCH", "NEW_QUERY", {"MaLHP": o}),
            turn("giảng viên lớp đó là ai", "COURSE_SCHEDULE_SEARCH", "RESOLVE_REFERENCE", {"MaLHP": o}),
            turn(f"{s} có đăng ký được lớp đó không", "REGISTRATION_ELIGIBILITY_CHECK", "RESOLVE_REFERENCE", {"MaSV": s, "MaLHP": o}),
            turn(f"nếu đổi sang môn {alias(c, rng)} thì sao", "REGISTRATION_ELIGIBILITY_CHECK", "CHANGE_ENTITY", {"MaSV": s, "MaMH": c.ma_mh}),
        ],
        lambda _s, c, _m, _o: [
            turn(f"{alias(c, rng)} có bao nhiêu lớp còn chỗ hk2", "AGGREGATION_STATISTICS", "NEW_QUERY", {"MaMH": c.ma_mh, "HocKy": 2, "CoTheDangKy": 1}),
            turn("liệt kê các lớp đó", "COURSE_OFFERING_SEARCH", "CHANGE_INTENT", {"MaMH": c.ma_mh, "HocKy": 2, "CoTheDangKy": 1}),
            turn("chỉ lấy buổi sáng", "COURSE_SCHEDULE_SEARCH", "ADD_FILTER", {"MaMH": c.ma_mh, "HocKy": 2, "CoTheDangKy": 1, "Buoi": "SANG"}),
            turn("bỏ điều kiện còn chỗ", "COURSE_SCHEDULE_SEARCH", "REMOVE_FILTER", {"MaMH": c.ma_mh, "HocKy": 2, "Buoi": "SANG"}),
        ],
        lambda s, c, _m, _o: [
            turn(f"{s} đã qua {alias(c, rng)} chưa", "STUDENT_RESULT_LOOKUP", "NEW_QUERY", {"MaSV": s, "MaMH": c.ma_mh, "KetQua": "DAT"}),
            turn("nếu rớt thì sao", "STUDENT_RESULT_LOOKUP", "REPLACE_FILTER", {"MaSV": s, "MaMH": c.ma_mh, "KetQua": "KHONG_DAT"}),
            turn("tổng tín chỉ kỳ này của bạn đó", "CREDIT_SUMMARY", "CHANGE_INTENT", {"MaSV": s, "HocKy": 1}),
            turn("bạn đó đang học ngành nào", "STUDENT_INFO_LOOKUP", "RESOLVE_REFERENCE", {"MaSV": s}),
        ],
    ]

    while turns < target_turns:
        student = rng.choice(catalog.students)
        course = rng.choice(catalog.courses)
        major = rng.choice(catalog.majors)
        offering = rng.choice(catalog.offerings)
        turn_list = hard_openers[(idx - 1) % len(hard_openers)](student, course, major, offering)
        if turns + len(turn_list) > target_turns:
            turn_list = turn_list[: target_turns - turns]
        dialogues.append(dialogue(f"manual_labeled_{idx:04d}", "curated_manual_labeled_500", turn_list))
        turns += len(turn_list)
        idx += 1
    return dialogues


def enrich_dialogues(
    dialogues: Sequence[Dict[str, Any]],
    db_path: Path,
    include_result_hash: bool,
    expected_result_max_rows: int,
    progress_label: str,
) -> List[Dict[str, Any]]:
    state_parser = ExpectedStateParser()
    engine = VietnameseNL2SQLEngine(db_path, state_parser=state_parser, parser_mode="hybrid")
    enriched = []
    try:
        for idx, item in enumerate(dialogues, start=1):
            engine.reset()
            state_parser.set_states(
                {
                    "intent": item_turn["intent"],
                    "edit_operation": item_turn["edit_operation"],
                    "slots": item_turn["slots"],
                }
                for item_turn in item["turns"]
            )
            turns = []
            for item_turn in item["turns"]:
                result = engine.ask(item_turn["utterance"])
                result_hash = df_hash(result.dataframe)
                baseline = {
                    "intent": result.intent,
                    "edit_operation": result.edit_operation,
                    "slots": result.slots,
                    "sql": result.sql,
                    "sql_kind": "business_rule" if result.sql and result.sql.startswith("-- business_rules.") else "sql",
                    "params": result.params,
                    "row_count": len(result.dataframe),
                    "columns": list(result.dataframe.columns),
                    "preview_rows": compact_df(result.dataframe),
                    "expected_rows": df_records(result.dataframe, expected_result_max_rows),
                    "expected_rows_truncated": len(result.dataframe) > expected_result_max_rows,
                    "result_hash": result_hash,
                }
                if include_result_hash:
                    baseline["result_hash"] = result_hash
                turns.append({**item_turn, "baseline": baseline})
            enriched.append({**item, "turns": turns})
            if idx % 1000 == 0:
                print(f"{progress_label}: enriched {idx}/{len(dialogues)} dialogues")
    finally:
        engine.close()
    return enriched


def qwen_messages_from_dialogues(dialogues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    examples = []
    system = (
        "Bạn là bộ phân tích state cho bài toán Vietnamese multi-turn text-to-SQL "
        "trong hệ thống đăng ký môn học. Chỉ trả JSON hợp lệ gồm intent, edit_operation, slots."
    )
    for item in dialogues:
        prev_state: Dict[str, Any] = {}
        for item_turn in item["turns"]:
            user_payload = {
                "previous_state": prev_state,
                "utterance": item_turn["utterance"],
            }
            assistant_payload = {
                "intent": item_turn["intent"],
                "edit_operation": item_turn["edit_operation"],
                "slots": item_turn["slots"],
            }
            examples.append(
                {
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
                        {"role": "assistant", "content": json.dumps(assistant_payload, ensure_ascii=False, sort_keys=True)},
                    ],
                    "metadata": {
                        "dialogue_id": item["dialogue_id"],
                        "source": item["source"],
                    },
                }
            )
            prev_state = assistant_payload
    return examples


def state_eval_rows_from_dialogues(dialogues: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for item in dialogues:
        previous_state: Dict[str, Any] = {}
        for turn_index, item_turn in enumerate(item["turns"], start=1):
            expected_state = {
                "intent": item_turn["intent"],
                "edit_operation": item_turn["edit_operation"],
                "slots": item_turn["slots"],
            }
            baseline = item_turn.get("baseline", {})
            rows.append(
                {
                    "id": f"{item['dialogue_id']}_turn_{turn_index:02d}",
                    "dialogue_id": item["dialogue_id"],
                    "turn_id": turn_index,
                    "db_id": item["db_id"],
                    "source": item["source"],
                    "previous_state": previous_state,
                    "user_question": item_turn["utterance"],
                    "expected_state": expected_state,
                    "gold_sql": baseline.get("sql"),
                    "gold_sql_kind": baseline.get("sql_kind", "sql"),
                    "gold_params": baseline.get("params", {}),
                    "expected_result": {
                        "columns": baseline.get("columns", []),
                        "rows": baseline.get("expected_rows", []),
                        "rows_truncated": baseline.get("expected_rows_truncated", False),
                        "row_count": baseline.get("row_count", 0),
                        "result_hash": baseline.get("result_hash"),
                    },
                }
            )
            previous_state = expected_state
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def count_turns(dialogues: Sequence[Dict[str, Any]]) -> int:
    return sum(len(item["turns"]) for item in dialogues)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_SYNTHETIC_OUTPUT)
    parser.add_argument("--manual-output", type=Path, default=DEFAULT_MANUAL_OUTPUT)
    parser.add_argument("--qwen-output", type=Path, default=DEFAULT_QWEN_OUTPUT)
    parser.add_argument("--state-eval-output", type=Path, default=DEFAULT_STATE_EVAL_OUTPUT)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--target-turns", type=int, default=30000)
    parser.add_argument("--manual-turns", type=int, default=500)
    parser.add_argument("--expected-result-max-rows", type=int, default=100)
    parser.add_argument("--include-result-hash", action="store_true")
    args = parser.parse_args()

    catalog = load_catalog(args.db)

    synthetic = generate_synthetic_dialogues(args.target_turns, args.seed, catalog)
    manual = generate_manual_labeled_dialogues(args.manual_turns, args.seed, catalog)

    synthetic_enriched = enrich_dialogues(
        synthetic,
        args.db,
        include_result_hash=args.include_result_hash,
        expected_result_max_rows=args.expected_result_max_rows,
        progress_label="synthetic",
    )
    manual_enriched = enrich_dialogues(
        manual,
        args.db,
        include_result_hash=args.include_result_hash,
        expected_result_max_rows=args.expected_result_max_rows,
        progress_label="manual",
    )

    write_jsonl(args.output, synthetic_enriched)
    write_jsonl(args.manual_output, manual_enriched)
    write_jsonl(args.qwen_output, qwen_messages_from_dialogues([*synthetic_enriched, *manual_enriched]))
    write_jsonl(args.state_eval_output, state_eval_rows_from_dialogues([*synthetic_enriched, *manual_enriched]))

    print(f"Wrote {len(synthetic_enriched)} synthetic dialogues / {count_turns(synthetic_enriched)} turns to {args.output}")
    print(f"Wrote {len(manual_enriched)} curated labeled dialogues / {count_turns(manual_enriched)} turns to {args.manual_output}")
    print(f"Wrote {count_turns(synthetic_enriched) + count_turns(manual_enriched)} Qwen state-tracking examples to {args.qwen_output}")
    print(f"Wrote {count_turns(synthetic_enriched) + count_turns(manual_enriched)} state-tracking eval rows to {args.state_eval_output}")


if __name__ == "__main__":
    main()
