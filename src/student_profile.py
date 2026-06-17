from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .business_rules import get_current_term, passed_courses_source


RowDict = Dict[str, Any]


@dataclass(frozen=True)
class StudentProfile:
    ma_sv: str
    ho_ten: str
    ma_nganh: str
    ten_nganh: str
    ma_ctdt: str
    ten_ctdt: str
    nam_nhap_hoc: int
    current_nam_hoc: int
    current_hoc_ky: int
    estimated_term_index: int
    passed_courses: List[str]
    registered_courses: List[str]

    def as_dict(self) -> RowDict:
        return {
            "MaSV": self.ma_sv,
            "HoTen": self.ho_ten,
            "MaNganh": self.ma_nganh,
            "TenNganh": self.ten_nganh,
            "MaCTDT": self.ma_ctdt,
            "TenCTDT": self.ten_ctdt,
            "NamNhapHoc": self.nam_nhap_hoc,
            "NamHocHienTai": self.current_nam_hoc,
            "HocKyHienTai": self.current_hoc_ky,
            "HocKyUocTinhTheoTienDo": self.estimated_term_index,
            "passed_courses": list(self.passed_courses),
            "registered_courses": list(self.registered_courses),
        }


def list_students(conn: sqlite3.Connection, limit: int = 50) -> List[RowDict]:
    rows = conn.execute(
        """
        SELECT MaSV, HoTen, TenNganh, MaCTDT
        FROM v_sinh_vien_day_du
        ORDER BY MaSV
        LIMIT :limit
        """,
        {"limit": limit},
    ).fetchall()
    return [dict(row) for row in rows]


def get_student_profile(
    conn: sqlite3.Connection,
    ma_sv: str,
    nam_hoc: Optional[int] = None,
    hoc_ky: Optional[int] = None,
) -> StudentProfile:
    student = conn.execute(
        """
        SELECT MaSV, HoTen, MaNganh, TenNganh, MaCTDT, TenCTDT, NamNhapHoc
        FROM v_sinh_vien_day_du
        WHERE MaSV = :ma_sv
        """,
        {"ma_sv": ma_sv},
    ).fetchone()
    if student is None:
        raise ValueError(f"Không tìm thấy sinh viên {ma_sv}.")

    current_nam_hoc, current_hoc_ky = (nam_hoc, hoc_ky) if nam_hoc and hoc_ky else get_current_term(conn)
    estimated_term = max(1, (int(current_nam_hoc) - int(student["NamNhapHoc"])) * 2 + int(current_hoc_ky))

    result_source = passed_courses_source(conn)
    passed = conn.execute(
        f"""
        SELECT DISTINCT MaMH
        FROM {result_source}
        WHERE MaSV = :ma_sv AND KetQua = 'DAT'
        """,
        {"ma_sv": ma_sv},
    ).fetchall()
    registered = conn.execute(
        """
        SELECT DISTINCT lhp.MaMH
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        WHERE dk.MaSV = :ma_sv
        """,
        {"ma_sv": ma_sv},
    ).fetchall()

    return StudentProfile(
        ma_sv=str(student["MaSV"]),
        ho_ten=str(student["HoTen"]),
        ma_nganh=str(student["MaNganh"]),
        ten_nganh=str(student["TenNganh"]),
        ma_ctdt=str(student["MaCTDT"]),
        ten_ctdt=str(student["TenCTDT"]),
        nam_nhap_hoc=int(student["NamNhapHoc"]),
        current_nam_hoc=int(current_nam_hoc),
        current_hoc_ky=int(current_hoc_ky),
        estimated_term_index=estimated_term,
        passed_courses=[str(row["MaMH"]) for row in passed],
        registered_courses=[str(row["MaMH"]) for row in registered],
    )


def get_curriculum_status(conn: sqlite3.Connection, ma_sv: str) -> List[RowDict]:
    profile = get_student_profile(conn, ma_sv)
    result_source = passed_courses_source(conn)
    rows = conn.execute(
        f"""
        SELECT mh.MaMH, mh.TenMH, mh.SoTC, mh.LoaiYC, mh.HKGoiY,
               CASE WHEN kq.MaMH IS NOT NULL THEN 1 ELSE 0 END AS DaDat,
               CASE WHEN dk.MaMH IS NOT NULL THEN 1 ELSE 0 END AS DangKyRoi
        FROM v_mon_hoc_ctdt mh
        LEFT JOIN (
            SELECT DISTINCT MaMH
            FROM {result_source}
            WHERE MaSV = :ma_sv AND KetQua = 'DAT'
        ) kq ON kq.MaMH = mh.MaMH
        LEFT JOIN (
            SELECT DISTINCT lhp.MaMH
            FROM DangKy dk
            JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
            WHERE dk.MaSV = :ma_sv
        ) dk ON dk.MaMH = mh.MaMH
        WHERE mh.MaCTDT = :ma_ctdt
        ORDER BY mh.HKGoiY, mh.LoaiYC, mh.TenMH
        """,
        {"ma_sv": ma_sv, "ma_ctdt": profile.ma_ctdt},
    ).fetchall()
    return [dict(row) for row in rows]
