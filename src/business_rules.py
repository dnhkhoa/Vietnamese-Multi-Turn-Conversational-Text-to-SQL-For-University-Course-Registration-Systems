from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = Path(
    os.getenv(
        "COURSE_REGISTRATION_DB_PATH",
        str(PROJECT_ROOT / "data" / "course_registration.db"),
    )
)
DEFAULT_VIEWS_PATH = PROJECT_ROOT / "data" / "views.sql"
MAX_CREDITS_PER_SEMESTER = 28


RowDict = Dict[str, Any]


def connect_db(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def table_or_view_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name = :name
          AND type IN ('table', 'view')
        LIMIT 1
        """,
        {"name": name},
    ).fetchone()
    return row is not None


def get_current_term(conn: sqlite3.Connection) -> tuple[int, int]:
    if table_or_view_exists(conn, "HocKyHeThong"):
        row = conn.execute(
            """
            SELECT NamHoc, HocKy
            FROM HocKyHeThong
            WHERE DangMoDangKy = 1
            ORDER BY NamHoc DESC, HocKy DESC
            LIMIT 1
            """
        ).fetchone()
        if row is not None:
            return int(row["NamHoc"]), int(row["HocKy"])

    if table_or_view_exists(conn, "CauHinhDangKy"):
        rows = conn.execute(
            """
            SELECT MaCauHinh, GiaTri
            FROM CauHinhDangKy
            WHERE MaCauHinh IN ('NAM_HOC_HIEN_TAI', 'HOC_KY_HIEN_TAI')
            """
        ).fetchall()
        values = {str(row["MaCauHinh"]): row["GiaTri"] for row in rows}
        if "NAM_HOC_HIEN_TAI" in values and "HOC_KY_HIEN_TAI" in values:
            return int(values["NAM_HOC_HIEN_TAI"]), int(values["HOC_KY_HIEN_TAI"])

    row = conn.execute(
        """
        SELECT NamHoc, HocKy
        FROM LopHP
        ORDER BY NamHoc DESC, HocKy DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        raise ValueError("Không tìm thấy học kỳ hiện tại trong database.")
    return int(row["NamHoc"]), int(row["HocKy"])


def passed_courses_source(conn: sqlite3.Connection) -> str:
    if table_or_view_exists(conn, "v_ket_qua_tot_nhat_sv"):
        return "v_ket_qua_tot_nhat_sv"
    return "v_ket_qua_day_du" if table_or_view_exists(conn, "v_ket_qua_day_du") else "KetQua"


def apply_views_if_missing(
    conn: sqlite3.Connection,
    views_path: Path | str = DEFAULT_VIEWS_PATH,
) -> None:
    view_count = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type = 'view' AND name LIKE 'v_%'"
    ).fetchone()[0]
    if view_count > 0:
        return

    views_path = Path(views_path)
    if not views_path.exists():
        raise FileNotFoundError(f"views file not found: {views_path}")

    conn.executescript(views_path.read_text(encoding="utf-8"))
    conn.commit()


def _fetch_all(
    conn: sqlite3.Connection,
    sql: str,
    params: Optional[dict] = None,
) -> List[RowDict]:
    rows = conn.execute(sql, params or {}).fetchall()
    return [dict(row) for row in rows]


def _fetch_one(
    conn: sqlite3.Connection,
    sql: str,
    params: Optional[dict] = None,
) -> Optional[RowDict]:
    row = conn.execute(sql, params or {}).fetchone()
    return dict(row) if row else None


def to_dataframe(rows: Iterable[RowDict]):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("pandas is not installed") from exc
    return pd.DataFrame(list(rows))


def get_student(conn: sqlite3.Connection, ma_sv: str) -> Optional[RowDict]:
    return _fetch_one(
        conn,
        """
        SELECT MaSV, HoTen, TrangThaiSV, MaKhoaHoc, TenKhoaHoc, MaCTDT, MaNganh, TenNganh
        FROM v_sinh_vien_day_du
        WHERE MaSV = :ma_sv
        """,
        {"ma_sv": ma_sv},
    )


def get_offering(conn: sqlite3.Connection, ma_lhp: str) -> Optional[RowDict]:
    return _fetch_one(
        conn,
        """
        SELECT
            MaLHP, MaMH, TenMH, Nhom, SoTC, NamHoc, HocKy,
            TrangThaiLHP, SiSoTD, SiSoDK, SoChoCon, CoTheDangKy,
            LichHocText, BuoiText, ThuText, TenGV
        FROM v_lop_hoc_phan_day_du
        WHERE MaLHP = :ma_lhp
        """,
        {"ma_lhp": ma_lhp},
    )


def get_missing_prerequisites(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_mh: str,
) -> List[RowDict]:
    result_source = passed_courses_source(conn)
    return _fetch_all(
        conn,
        f"""
        SELECT
            tq.MaMH,
            tq.TenMH,
            tq.MaMHTQ,
            tq.TenMHTQ
        FROM v_tien_quyet_day_du tq
        LEFT JOIN {result_source} kq
            ON kq.MaSV = :ma_sv
           AND kq.MaMH = tq.MaMHTQ
           AND kq.KetQua = 'DAT'
        WHERE tq.MaMH = :ma_mh
          AND kq.MaMH IS NULL
        ORDER BY tq.MaMHTQ
        """,
        {"ma_sv": ma_sv, "ma_mh": ma_mh},
    )


def get_schedule_conflicts(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_lhp: str,
) -> List[RowDict]:
    return _fetch_all(
        conn,
        """
        WITH target AS (
            SELECT MaLHP, MaMH, NamHoc, HocKy
            FROM LopHP
            WHERE MaLHP = :ma_lhp
        )
        SELECT DISTINCT
            dk.MaSV,
            cur.MaLHP AS MaLHPDangKy,
            cur.MaMH AS MaMHDangKy,
            cur.TenMH AS TenMHDangKy,
            cur.Nhom AS NhomDangKy,
            cur.Thu AS ThuTrung,
            cur.TietBD AS TietBDDangKy,
            cur.TietKT AS TietKTDangKy,
            tgt.TietBD AS TietBDMucTieu,
            tgt.TietKT AS TietKTMucTieu,
            cur.MaPhong AS MaPhongDangKy,
            tgt.MaPhong AS MaPhongMucTieu
        FROM DangKy dk
        JOIN v_lop_hoc_phan_lich cur ON dk.MaLHP = cur.MaLHP
        JOIN LopHP cur_lhp ON cur.MaLHP = cur_lhp.MaLHP
        JOIN target t
        JOIN v_lop_hoc_phan_lich tgt ON t.MaLHP = tgt.MaLHP
        WHERE dk.MaSV = :ma_sv
          AND cur.MaLHP <> :ma_lhp
          AND cur_lhp.NamHoc = t.NamHoc
          AND cur_lhp.HocKy = t.HocKy
          AND cur.Thu = tgt.Thu
          AND cur.TietBD <= tgt.TietKT
          AND cur.TietKT >= tgt.TietBD
        ORDER BY cur.Thu, cur.TietBD, cur.MaLHP
        """,
        {"ma_sv": ma_sv, "ma_lhp": ma_lhp},
    )


def get_same_course_registrations(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_lhp: str,
) -> List[RowDict]:
    return _fetch_all(
        conn,
        """
        WITH target AS (
            SELECT MaLHP, MaMH, NamHoc, HocKy
            FROM LopHP
            WHERE MaLHP = :ma_lhp
        )
        SELECT
            dk.MaSV,
            lhp.MaLHP,
            lhp.MaMH,
            mh.TenMH,
            lhp.NamHoc,
            lhp.HocKy,
            lhp.Nhom
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
        JOIN target t
        WHERE dk.MaSV = :ma_sv
          AND lhp.MaLHP <> t.MaLHP
          AND lhp.MaMH = t.MaMH
          AND lhp.NamHoc = t.NamHoc
          AND lhp.HocKy = t.HocKy
        ORDER BY lhp.MaLHP
        """,
        {"ma_sv": ma_sv, "ma_lhp": ma_lhp},
    )


def is_already_registered(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_lhp: str,
) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM DangKy
        WHERE MaSV = :ma_sv
          AND MaLHP = :ma_lhp
        LIMIT 1
        """,
        {"ma_sv": ma_sv, "ma_lhp": ma_lhp},
    ).fetchone()
    return row is not None


def get_credit_load(
    conn: sqlite3.Connection,
    ma_sv: str,
    nam_hoc: int,
    hoc_ky: int,
) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(SUM(mh.SoTC), 0) AS TongTinChi
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
        WHERE dk.MaSV = :ma_sv
          AND lhp.NamHoc = :nam_hoc
          AND lhp.HocKy = :hoc_ky
        """,
        {"ma_sv": ma_sv, "nam_hoc": nam_hoc, "hoc_ky": hoc_ky},
    ).fetchone()
    return int(row["TongTinChi"])


def check_registration_eligibility(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_lhp: str,
    max_credits: int = MAX_CREDITS_PER_SEMESTER,
) -> RowDict:
    student = get_student(conn, ma_sv)
    offering = get_offering(conn, ma_lhp)

    if student is None:
        return {
            "MaSV": ma_sv,
            "MaLHP": ma_lhp,
            "CoTheDangKy": 0,
            "LyDoKhongDangKy": ["SINH_VIEN_KHONG_TON_TAI"],
        }

    if offering is None:
        return {
            "MaSV": ma_sv,
            "HoTen": student["HoTen"],
            "MaLHP": ma_lhp,
            "CoTheDangKy": 0,
            "LyDoKhongDangKy": ["LOP_KHONG_TON_TAI"],
        }

    missing_prereq = get_missing_prerequisites(conn, ma_sv, offering["MaMH"])
    schedule_conflicts = get_schedule_conflicts(conn, ma_sv, ma_lhp)
    same_course_regs = get_same_course_registrations(conn, ma_sv, ma_lhp)
    already_registered = is_already_registered(conn, ma_sv, ma_lhp)
    current_credits = get_credit_load(conn, ma_sv, offering["NamHoc"], offering["HocKy"])
    credits_after = current_credits + offering["SoTC"]

    reasons: List[str] = []
    if student["TrangThaiSV"] != "DANG_HOC":
        reasons.append("SINH_VIEN_KHONG_DANG_HOC")
    if already_registered:
        reasons.append("DA_DANG_KY_LOP_NAY")
    if offering["TrangThaiLHP"] != "MO":
        reasons.append("LOP_KHONG_MO")
    if offering["SoChoCon"] <= 0:
        reasons.append("LOP_HET_CHO")
    if missing_prereq:
        reasons.append("THIEU_TIEN_QUYET")
    if schedule_conflicts:
        reasons.append("TRUNG_LICH")
    if same_course_regs:
        reasons.append("DA_DANG_KY_MON_NAY")
    if credits_after > max_credits:
        reasons.append("VUOT_TIN_CHI")

    return {
        "MaSV": ma_sv,
        "HoTen": student["HoTen"],
        "TrangThaiSV": student["TrangThaiSV"],
        "MaLHP": ma_lhp,
        "MaMH": offering["MaMH"],
        "TenMH": offering["TenMH"],
        "Nhom": offering["Nhom"],
        "NamHoc": offering["NamHoc"],
        "HocKy": offering["HocKy"],
        "SoTC": offering["SoTC"],
        "TrangThaiLHP": offering["TrangThaiLHP"],
        "SiSoDK": offering["SiSoDK"],
        "SiSoTD": offering["SiSoTD"],
        "SoChoCon": offering["SoChoCon"],
        "TinChiHienTai": current_credits,
        "TinChiSauDangKy": credits_after,
        "SoMonTienQuyetThieu": len(missing_prereq),
        "SoLopTrungLich": len(schedule_conflicts),
        "SoLopCungMonDaDangKy": len(same_course_regs),
        "CoTheDangKy": 1 if not reasons else 0,
        "LyDoKhongDangKy": reasons,
        "MonTienQuyetThieu": missing_prereq,
        "LopTrungLich": schedule_conflicts,
        "LopCungMonDaDangKy": same_course_regs,
    }


def find_eligible_offerings_for_course(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_mh: str,
    nam_hoc: Optional[int] = None,
    hoc_ky: Optional[int] = None,
    max_credits: int = MAX_CREDITS_PER_SEMESTER,
) -> List[RowDict]:
    params: Dict[str, Any] = {"ma_mh": ma_mh}
    filters = ["MaMH = :ma_mh", "TrangThaiLHP = 'MO'", "SoChoCon > 0"]
    if nam_hoc is not None:
        filters.append("NamHoc = :nam_hoc")
        params["nam_hoc"] = nam_hoc
    if hoc_ky is not None:
        filters.append("HocKy = :hoc_ky")
        params["hoc_ky"] = hoc_ky

    candidates = _fetch_all(
        conn,
        f"""
        SELECT MaLHP
        FROM v_lop_hoc_phan_day_du
        WHERE {' AND '.join(filters)}
        ORDER BY SoChoCon DESC, Nhom ASC
        """,
        params,
    )

    eligible = []
    for row in candidates:
        result = check_registration_eligibility(
            conn,
            ma_sv=ma_sv,
            ma_lhp=row["MaLHP"],
            max_credits=max_credits,
        )
        if result["CoTheDangKy"] == 1:
            eligible.append(result)
    return eligible


def find_alternative_offerings(
    conn: sqlite3.Connection,
    ma_sv: str,
    ma_lhp: str,
    max_credits: int = MAX_CREDITS_PER_SEMESTER,
) -> List[RowDict]:
    target = get_offering(conn, ma_lhp)
    if target is None:
        return []

    candidates = _fetch_all(
        conn,
        """
        SELECT MaLHP
        FROM v_lop_hoc_phan_day_du
        WHERE MaMH = :ma_mh
          AND NamHoc = :nam_hoc
          AND HocKy = :hoc_ky
          AND MaLHP <> :ma_lhp
          AND TrangThaiLHP = 'MO'
          AND SoChoCon > 0
        ORDER BY SoChoCon DESC, Nhom ASC
        """,
        {
            "ma_mh": target["MaMH"],
            "nam_hoc": target["NamHoc"],
            "hoc_ky": target["HocKy"],
            "ma_lhp": ma_lhp,
        },
    )

    alternatives = []
    for row in candidates:
        result = check_registration_eligibility(
            conn,
            ma_sv=ma_sv,
            ma_lhp=row["MaLHP"],
            max_credits=max_credits,
        )
        if result["CoTheDangKy"] == 1:
            alternatives.append(result)
    return alternatives


def find_course_candidates(conn: sqlite3.Connection, text: str, limit: int = 10) -> List[RowDict]:
    pattern = f"%{text}%"
    return _fetch_all(
        conn,
        """
        SELECT DISTINCT MaMH, TenMH, SoTC
        FROM MonHoc
        WHERE MaMH LIKE :pattern
           OR TenMH LIKE :pattern
        ORDER BY TenMH
        LIMIT :limit
        """,
        {"pattern": pattern, "limit": limit},
    )


def _pick_demo_pair(conn: sqlite3.Connection) -> RowDict:
    return _fetch_one(
        conn,
        """
        SELECT dk.MaSV, lhp.MaLHP
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        WHERE lhp.TrangThai = 'MO'
        LIMIT 1
        """,
    ) or _fetch_one(
        conn,
        """
        SELECT sv.MaSV, lhp.MaLHP
        FROM SinhVien sv
        CROSS JOIN LopHP lhp
        WHERE sv.TrangThai = 'DANG_HOC'
          AND lhp.TrangThai = 'MO'
        LIMIT 1
        """,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--ma-sv", default=None)
    parser.add_argument("--ma-lhp", default=None)
    parser.add_argument("--max-credits", type=int, default=MAX_CREDITS_PER_SEMESTER)
    args = parser.parse_args()

    with connect_db(args.db) as conn:
        apply_views_if_missing(conn)
        if args.ma_sv is None or args.ma_lhp is None:
            demo_pair = _pick_demo_pair(conn)
            if demo_pair is None:
                raise RuntimeError("cannot find demo student/offering pair")
            ma_sv = args.ma_sv or demo_pair["MaSV"]
            ma_lhp = args.ma_lhp or demo_pair["MaLHP"]
        else:
            ma_sv = args.ma_sv
            ma_lhp = args.ma_lhp

        result = {
            "eligibility": check_registration_eligibility(
                conn,
                ma_sv=ma_sv,
                ma_lhp=ma_lhp,
                max_credits=args.max_credits,
            ),
            "alternatives": find_alternative_offerings(
                conn,
                ma_sv=ma_sv,
                ma_lhp=ma_lhp,
                max_credits=args.max_credits,
            )[:5],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
