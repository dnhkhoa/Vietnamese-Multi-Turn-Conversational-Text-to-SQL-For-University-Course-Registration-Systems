from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "course_registration.db"

SYSTEM_PROMPT = (
    "Bạn là bộ phân tích state cho bài toán Vietnamese multi-turn text-to-SQL "
    "trong hệ thống đăng ký môn học. Chỉ trả JSON hợp lệ gồm intent, edit_operation, slots."
)


def rows_to_dicts(cursor: sqlite3.Cursor) -> List[Dict[str, Any]]:
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def result_hash(rows: List[Dict[str, Any]]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compact_result(rows: List[Dict[str, Any]], max_rows: int) -> Dict[str, Any]:
    return {
        "columns": list(rows[0].keys()) if rows else [],
        "rows": rows[:max_rows],
        "rows_truncated": len(rows) > max_rows,
        "row_count": len(rows),
        "result_hash": result_hash(rows),
    }


def query_result(conn: sqlite3.Connection, sql: str, params: Dict[str, Any], max_rows: int) -> Dict[str, Any]:
    rows = rows_to_dicts(conn.execute(sql, params))
    return compact_result(rows, max_rows)


def current_term(conn: sqlite3.Connection) -> tuple[int, int]:
    row = conn.execute(
        "SELECT NamHoc, HocKy FROM LopHP ORDER BY NamHoc DESC, HocKy DESC LIMIT 1"
    ).fetchone()
    return int(row[0]), int(row[1])


def load_students(conn: sqlite3.Connection, limit: int) -> List[str]:
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


def recommendation_sql() -> str:
    return """
    WITH sv AS (
        SELECT MaSV, MaCTDT
        FROM v_sinh_vien_day_du
        WHERE MaSV = :ma_sv
    ),
    passed AS (
        SELECT MaMH
        FROM v_ket_qua_day_du
        WHERE MaSV = :ma_sv
          AND KetQua = 'DAT'
    ),
    open_lhp AS (
        SELECT
            MaMH,
            MIN(MaLHP) AS MaLHPGoiY,
            MAX(SoChoCon) AS SoChoCon
        FROM v_lop_hoc_phan_day_du
        WHERE NamHoc = :nam_hoc
          AND HocKy = :hoc_ky
          AND TrangThaiLHP = 'MO'
          AND SoChoCon > 0
        GROUP BY MaMH
    )
    SELECT
        'GOI_Y' AS TrangThaiGoiY,
        CASE
            WHEN ctdt.LoaiYC = 'BAT_BUOC' THEN 'HIGH'
            WHEN ctdt.HKGoiY <= :hoc_ky THEN 'MEDIUM'
            ELSE 'LOW'
        END AS MucUuTien,
        sv.MaSV,
        ctdt.MaMH,
        ctdt.TenMH,
        ctdt.SoTC,
        ctdt.LoaiYC,
        ctdt.HKGoiY,
        open_lhp.MaLHPGoiY,
        open_lhp.SoChoCon,
        :nam_hoc AS NamHoc,
        :hoc_ky AS HocKy
    FROM sv
    JOIN v_mon_hoc_ctdt ctdt ON ctdt.MaCTDT = sv.MaCTDT
    JOIN open_lhp ON open_lhp.MaMH = ctdt.MaMH
    LEFT JOIN passed ON passed.MaMH = ctdt.MaMH
    WHERE passed.MaMH IS NULL
      AND (:loai_yc IS NULL OR ctdt.LoaiYC = :loai_yc)
    ORDER BY
        CASE ctdt.LoaiYC WHEN 'BAT_BUOC' THEN 0 ELSE 1 END,
        ctdt.HKGoiY,
        open_lhp.SoChoCon DESC,
        ctdt.TenMH
    LIMIT :limit
    """


def gold_for_state(
    conn: sqlite3.Connection,
    state: Dict[str, Any],
    max_rows: int,
) -> tuple[str, Dict[str, Any], Dict[str, Any]]:
    slots = state["slots"]
    intent = state["intent"]
    params: Dict[str, Any] = {}

    if intent == "COURSE_RECOMMENDATION":
        sql = recommendation_sql()
        params = {
            "ma_sv": slots["MaSV"],
            "nam_hoc": slots.get("NamHoc"),
            "hoc_ky": slots.get("HocKy"),
            "loai_yc": slots.get("LoaiYC"),
            "limit": slots.get("Limit", 10),
        }
        return sql, params, query_result(conn, sql, params, max_rows)

    if intent == "STUDENT_INFO_LOOKUP":
        sql = """
        SELECT MaSV, HoTen, TrangThaiSV, MaKhoaHoc, TenKhoaHoc, MaCTDT, MaNganh, TenNganh
        FROM v_sinh_vien_day_du
        WHERE MaSV = :ma_sv
        """
        params = {"ma_sv": slots["MaSV"]}
        return sql, params, query_result(conn, sql, params, max_rows)

    if intent == "STUDENT_RESULT_LOOKUP":
        conditions = ["MaSV = :ma_sv"]
        params = {"ma_sv": slots["MaSV"]}
        if slots.get("KetQua"):
            conditions.append("KetQua = :ket_qua")
            params["ket_qua"] = slots["KetQua"]
        if slots.get("HocKy"):
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        sql = f"""
        SELECT MaSV, HoTen, MaMH, TenMH, SoTC, NamHoc, HocKy, KetQua
        FROM v_ket_qua_day_du
        WHERE {' AND '.join(conditions)}
        ORDER BY NamHoc, HocKy, TenMH
        """
        return sql, params, query_result(conn, sql, params, max_rows)

    if intent == "COURSE_OFFERING_SEARCH":
        conditions = ["1 = 1"]
        params = {}
        if slots.get("NamHoc"):
            conditions.append("NamHoc = :nam_hoc")
            params["nam_hoc"] = slots["NamHoc"]
        if slots.get("HocKy"):
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        if slots.get("TrangThaiLHP"):
            conditions.append("TrangThaiLHP = :trang_thai")
            params["trang_thai"] = slots["TrangThaiLHP"]
        sql = f"""
        SELECT DISTINCT MaLHP, TenMH, Nhom, SoTC, NamHoc, HocKy, TrangThaiLHP, SoChoCon, LichHocText, TenGV
        FROM v_lop_hoc_phan_day_du
        WHERE {' AND '.join(conditions)}
        ORDER BY TenMH, Nhom
        LIMIT 50
        """
        return sql, params, query_result(conn, sql, params, max_rows)

    if intent == "CREDIT_SUMMARY":
        conditions = ["MaSV = :ma_sv"]
        params = {"ma_sv": slots["MaSV"]}
        if slots.get("HocKy"):
            conditions.append("HocKy = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        sql = f"""
        SELECT MaSV, HoTen, NamHoc, HocKy, TongTinChiDangKy
        FROM v_tin_chi_dang_ky_sv
        WHERE {' AND '.join(conditions)}
        ORDER BY NamHoc, HocKy
        """
        return sql, params, query_result(conn, sql, params, max_rows)

    if intent == "CURRICULUM_COURSE_SEARCH":
        conditions = ["sv.MaSV = :ma_sv"]
        params = {"ma_sv": slots["MaSV"]}
        if slots.get("HocKy"):
            conditions.append("ctdt.HKGoiY = :hoc_ky")
            params["hoc_ky"] = slots["HocKy"]
        if slots.get("LoaiYC"):
            conditions.append("ctdt.LoaiYC = :loai_yc")
            params["loai_yc"] = slots["LoaiYC"]
        sql = f"""
        SELECT ctdt.MaMH, ctdt.TenMH, ctdt.SoTC, ctdt.LoaiYC, ctdt.HKGoiY, sv.MaSV
        FROM v_sinh_vien_day_du sv
        JOIN v_mon_hoc_ctdt ctdt ON ctdt.MaCTDT = sv.MaCTDT
        WHERE {' AND '.join(conditions)}
        ORDER BY ctdt.HKGoiY, ctdt.LoaiYC, ctdt.TenMH
        """
        return sql, params, query_result(conn, sql, params, max_rows)

    raise ValueError(f"unsupported intent for gap augmentation: {intent}")


def turn(utterance: str, intent: str, edit: str, slots: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "utterance": utterance,
        "expected_state": {
            "intent": intent,
            "edit_operation": edit,
            "slots": slots,
        },
    }


def build_dialogues(students: List[str], nam_hoc: int, hoc_ky: int, seed: int, count: int) -> List[Dict[str, Any]]:
    rng = random.Random(seed)
    dialogues = []
    recommendation_questions = [
        "kì này tôi nên đăng ký môn nào",
        "ki nay toi nen dang ky mon nao",
        "học kỳ hiện tại gợi ý môn cho mình",
        "mình nên đăng kí gì ở hk này",
        "hk này nên học môn nào cho hợp lý",
        "gợi ý môn phù hợp cho tôi trong kỳ này",
        "tôi nên đăng ký gì kỳ này nếu còn thiếu môn",
        "môn nào nên ưu tiên đăng ký trước kỳ này",
    ]
    studied_questions = [
        "tôi đã học những môn gì",
        "toi da hoc nhung mon gi",
        "mình đã qua những môn nào rồi",
        "cho tôi xem các môn đã học",
        "các môn tôi đã đạt là gì",
        "liệt kê môn mình đã học xong",
    ]
    current_term_questions = [
        "cho tôi những môn mở ở kì này",
        "cho toi nhung mon mo o ki nay",
        "các lớp đang mở hk này",
        "học kỳ hiện tại có lớp nào còn mở",
        "kì này trường mở những lớp nào",
        "ki nay co lop hoc phan nao dang mo",
    ]

    for idx in range(1, count + 1):
        student = students[(idx - 1) % len(students)]
        if idx % 4 == 1:
            turns = [
                turn(
                    f"mình là mssv {student}",
                    "STUDENT_INFO_LOOKUP",
                    "NEW_QUERY",
                    {"MaSV": student},
                ),
                turn(
                    rng.choice(recommendation_questions),
                    "COURSE_RECOMMENDATION",
                    "CHANGE_INTENT",
                    {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                ),
                turn(
                    "ưu tiên môn bắt buộc trước",
                    "COURSE_RECOMMENDATION",
                    "ADD_FILTER",
                    {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky, "LoaiYC": "BAT_BUOC"},
                ),
                turn(
                    "còn môn tự chọn thì sao",
                    "COURSE_RECOMMENDATION",
                    "REPLACE_FILTER",
                    {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky, "LoaiYC": "TU_CHON"},
                ),
            ]
            source = "freeform_recommendation_v03"
        elif idx % 4 == 2:
            turns = [
                turn(
                    f"sinh viên {student} đang học ngành nào",
                    "STUDENT_INFO_LOOKUP",
                    "NEW_QUERY",
                    {"MaSV": student},
                ),
                turn(
                    rng.choice(studied_questions),
                    "STUDENT_RESULT_LOOKUP",
                    "RESOLVE_REFERENCE",
                    {"MaSV": student},
                ),
                turn(
                    "chỉ lấy các môn đã đạt",
                    "STUDENT_RESULT_LOOKUP",
                    "ADD_FILTER",
                    {"MaSV": student, "KetQua": "DAT"},
                ),
                turn(
                    "vậy tổng tín chỉ kỳ này của tôi là bao nhiêu",
                    "CREDIT_SUMMARY",
                    "CHANGE_INTENT",
                    {"MaSV": student, "HocKy": hoc_ky},
                ),
            ]
            source = "freeform_studied_courses_v03"
        elif idx % 4 == 3:
            turns = [
                turn(
                    rng.choice(current_term_questions),
                    "COURSE_OFFERING_SEARCH",
                    "NEW_QUERY",
                    {"NamHoc": nam_hoc, "HocKy": hoc_ky, "TrangThaiLHP": "MO"},
                ),
                turn(
                    "giới hạn 10 lớp thôi",
                    "COURSE_OFFERING_SEARCH",
                    "LIMIT",
                    {"NamHoc": nam_hoc, "HocKy": hoc_ky, "TrangThaiLHP": "MO", "Limit": 10},
                ),
                turn(
                    f"còn theo CTĐT của sinh viên {student} thì kỳ này nên xem môn nào",
                    "CURRICULUM_COURSE_SEARCH",
                    "CHANGE_INTENT",
                    {"MaSV": student, "HocKy": hoc_ky},
                ),
                turn(
                    "lọc môn bắt buộc thôi",
                    "CURRICULUM_COURSE_SEARCH",
                    "ADD_FILTER",
                    {"MaSV": student, "HocKy": hoc_ky, "LoaiYC": "BAT_BUOC"},
                ),
            ]
            source = "freeform_current_term_v03"
        else:
            turns = [
                turn(
                    f"mssv {student} cần tư vấn đăng ký",
                    "STUDENT_INFO_LOOKUP",
                    "NEW_QUERY",
                    {"MaSV": student},
                ),
                turn(
                    rng.choice(recommendation_questions),
                    "COURSE_RECOMMENDATION",
                    "CHANGE_INTENT",
                    {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                ),
                turn(
                    rng.choice(studied_questions),
                    "STUDENT_RESULT_LOOKUP",
                    "CHANGE_INTENT",
                    {"MaSV": student},
                ),
                turn(
                    "quay lại phần gợi ý đăng ký kỳ này",
                    "COURSE_RECOMMENDATION",
                    "CHANGE_INTENT",
                    {"MaSV": student, "NamHoc": nam_hoc, "HocKy": hoc_ky},
                ),
            ]
            source = "freeform_context_switch_advising_v03"
        dialogues.append(
            {
                "dialogue_id": f"gap_aug_v03_{idx:04d}",
                "db_id": "course_registration",
                "source": source,
                "turns": turns,
            }
        )
    return dialogues


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
                                {
                                    "previous_state": previous_state,
                                    "utterance": item_turn["utterance"],
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                        },
                        {
                            "role": "assistant",
                            "content": json.dumps(expected_state, ensure_ascii=False, sort_keys=True),
                        },
                    ],
                    "metadata": {
                        "dialogue_id": item["dialogue_id"],
                        "source": item["source"],
                    },
                }
            )
            previous_state = expected_state
    return rows


def eval_rows(conn: sqlite3.Connection, dialogues: Iterable[Dict[str, Any]], max_rows: int) -> List[Dict[str, Any]]:
    rows = []
    for item in dialogues:
        previous_state: Dict[str, Any] = {}
        for idx, item_turn in enumerate(item["turns"], start=1):
            expected_state = item_turn["expected_state"]
            gold_sql, gold_params, expected_result = gold_for_state(conn, expected_state, max_rows)
            rows.append(
                {
                    "id": f"{item['dialogue_id']}_turn_{idx:02d}",
                    "dialogue_id": item["dialogue_id"],
                    "turn_id": idx,
                    "db_id": item["db_id"],
                    "source": item["source"],
                    "previous_state": previous_state,
                    "user_question": item_turn["utterance"],
                    "expected_state": expected_state,
                    "gold_sql": gold_sql,
                    "gold_sql_kind": "advisor_recommendation" if expected_state["intent"] == "COURSE_RECOMMENDATION" else "sql",
                    "gold_params": gold_params,
                    "expected_result": expected_result,
                }
            )
            previous_state = expected_state
    return rows


def write_jsonl(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--dialogues-output", type=Path, default=PROJECT_ROOT / "data" / "gap_aug_dialogues_v03.jsonl")
    parser.add_argument("--qwen-output", type=Path, default=PROJECT_ROOT / "data" / "qwen_state_tracking_gap_aug_v03.jsonl")
    parser.add_argument("--eval-output", type=Path, default=PROJECT_ROOT / "data" / "state_tracking_gap_eval_v03.jsonl")
    parser.add_argument("--count", type=int, default=160)
    parser.add_argument("--seed", type=int, default=20260613)
    parser.add_argument("--max-result-rows", type=int, default=100)
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    try:
        nam_hoc, hoc_ky = current_term(conn)
        students = load_students(conn, limit=max(args.count, 50))
        dialogues = build_dialogues(students, nam_hoc, hoc_ky, args.seed, args.count)
        qwen = qwen_rows(dialogues)
        evaluation = eval_rows(conn, dialogues, args.max_result_rows)
    finally:
        conn.close()

    write_jsonl(args.dialogues_output, dialogues)
    write_jsonl(args.qwen_output, qwen)
    write_jsonl(args.eval_output, evaluation)
    print(f"Wrote {len(dialogues)} dialogues to {args.dialogues_output}")
    print(f"Wrote {len(qwen)} Qwen examples to {args.qwen_output}")
    print(f"Wrote {len(evaluation)} eval rows to {args.eval_output}")


if __name__ == "__main__":
    main()
