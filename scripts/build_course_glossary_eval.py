from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.course_glossary import glossary_forms, prompt_metadata


DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "eval" / "course_glossary_k23_eval.jsonl"


def row(
    case_id: str,
    category: str,
    utterance: str,
    expected_state: Dict[str, Any],
    previous_state: Dict[str, Any] | None = None,
    metadata: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "id": case_id,
        "category": category,
        "utterance": utterance,
        "previous_state": previous_state or {},
        "expected_state": expected_state,
        "metadata": {**prompt_metadata(), **(metadata or {})},
    }


def expected(intent: str, edit_operation: str, slots: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {"intent": intent, "edit_operation": edit_operation, "slots": slots or {}}


def build_cases(limit: int = 150) -> List[Dict[str, Any]]:
    forms = list(glossary_forms())
    cases: List[Dict[str, Any]] = []

    for idx, item in enumerate(forms, start=1):
        cases.append(
            row(
                f"abbr_info_{idx:03d}",
                "alias_info",
                f"Mon {item['form']} may tin chi?",
                expected("COURSE_INFO_SEARCH", "NEW_QUERY", {"MaMH": item["ma_mh"]}),
                metadata=item,
            )
        )

    for idx, item in enumerate(forms[:32], start=1):
        cases.append(
            row(
                f"abbr_schedule_{idx:03d}",
                "alias_schedule",
                f"Lop {item['form']} con cho hoc ky 2 khong?",
                expected("COURSE_SCHEDULE_SEARCH", "NEW_QUERY", {"MaMH": item["ma_mh"], "HocKy": 2, "CoTheDangKy": 1}),
                metadata=item,
            )
        )

    for idx, item in enumerate(forms[:20], start=1):
        previous_ma_mh = "DBSY230184E" if item["ma_mh"] != "DBSY230184E" else "ARIN330585E"
        cases.append(
            row(
                f"abbr_change_{idx:03d}",
                "change_entity",
                f"Doi sang {item['form']}",
                expected("COURSE_INFO_SEARCH", "CHANGE_ENTITY", {"MaMH": item["ma_mh"]}),
                previous_state={
                    "intent": "COURSE_INFO_SEARCH",
                    "edit_operation": "NEW_QUERY",
                    "slots": {"MaMH": previous_ma_mh},
                },
                metadata=item,
            )
        )

    for idx in range(10):
        first = forms[idx]
        second = forms[-idx - 1]
        cases.append(
            row(
                f"abbr_two_course_{idx + 1:03d}",
                "two_course_change",
                f"Doi tu {first['form']} sang {second['form']}",
                expected("COURSE_INFO_SEARCH", "CHANGE_ENTITY", {"MaMH": second["ma_mh"]}),
                previous_state={
                    "intent": "COURSE_INFO_SEARCH",
                    "edit_operation": "NEW_QUERY",
                    "slots": {"MaMH": first["ma_mh"]},
                },
                metadata={"first_ma_mh": first["ma_mh"], "second_ma_mh": second["ma_mh"]},
            )
        )

    negative_cases = [
        ("negative_ai_001", "ai da dang ky hoc ky 2?", "AI pronoun, not Artificial Intelligence"),
        ("negative_ai_002", "cho toi biet ai con no mon", "AI pronoun, not Artificial Intelligence"),
        ("negative_ai_003", "ai hoc lop nay?", "AI pronoun, not Artificial Intelligence"),
        ("negative_ml_001", "ml trong bao cao nay la metric gi?", "Generic ML acronym outside course registration"),
        ("negative_ml_002", "co bao nhieu ml du lieu?", "Measurement/unit style wording"),
        ("negative_os_001", "may tinh nay dung os gi?", "Generic OS outside course registration"),
        ("negative_os_002", "loi os tren may tinh phong lab", "Generic OS outside course registration"),
        ("negative_ds_001", "ds sinh vien dang ky lop nay", "DS as danh sach, not Data Science"),
        ("negative_ds_002", "xuat ds lop con cho", "DS as danh sach, not Data Science"),
        ("negative_cloud_001", "cloud luu file nao?", "Generic cloud storage outside course query"),
        ("negative_nlp_001", "nlp pipeline co loi tokenization", "Generic NLP outside registration"),
        ("negative_generic_001", "ai la giang vien lop nay?", "AI pronoun with class query"),
    ]
    for case_id, utterance, note in negative_cases:
        cases.append(
            row(
                case_id,
                "negative_ambiguous_alias",
                utterance,
                expected("COURSE_OFFERING_SEARCH", "NEW_QUERY", {}),
                metadata={"forbid_ma_mh": True, "note": note},
            )
        )

    regression_cases = [
        ("regression_001", "hoc ky 2 con lop nao mo?", expected("COURSE_OFFERING_SEARCH", "NEW_QUERY", {"HocKy": 2, "CoTheDangKy": 1})),
        ("regression_002", "sinh vien 22110001 da dang ky nhung lop nao?", expected("STUDENT_REGISTRATION_LOOKUP", "NEW_QUERY", {"MaSV": "22110001"})),
        ("regression_003", "mon nay tien quyet gi?", expected("PREREQUISITE_LOOKUP", "RESOLVE_REFERENCE", {"PrereqDirection": "PREREQUISITES_OF"})),
        ("regression_004", "cho toi xem chuong trinh dao tao nganh cntt", expected("CURRICULUM_COURSE_SEARCH", "NEW_QUERY", {"MaNganh": "10"})),
        ("regression_005", "lop LHP202620024 hoc phong nao?", expected("COURSE_SCHEDULE_SEARCH", "NEW_QUERY", {"MaLHP": "LHP202620024"})),
        ("regression_006", "22110001 co dang ky duoc lop LHP202620024 khong?", expected("REGISTRATION_ELIGIBILITY_CHECK", "NEW_QUERY", {"MaSV": "22110001", "MaLHP": "LHP202620024"})),
        ("regression_007", "tong tin chi da dang ky cua 22110001", expected("CREDIT_SUMMARY", "NEW_QUERY", {"MaSV": "22110001"})),
        ("regression_008", "mon nao co nhieu lop nhat?", expected("AGGREGATION_STATISTICS", "NEW_QUERY", {})),
    ]
    for case_id, utterance, state in regression_cases:
        cases.append(row(case_id, "regression_no_abbreviation", utterance, state))

    return cases[:limit]


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for item in rows:
            f.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--limit", type=int, default=150)
    args = parser.parse_args()
    cases = build_cases(args.limit)
    write_jsonl(args.output, cases)
    print(f"Wrote {len(cases)} glossary eval cases to {args.output}")


if __name__ == "__main__":
    main()
