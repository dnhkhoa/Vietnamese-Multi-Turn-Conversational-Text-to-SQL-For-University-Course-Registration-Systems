from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

import pandas as pd

from .business_rules import MAX_CREDITS_PER_SEMESTER, check_registration_eligibility
from .student_profile import get_student_profile


RowDict = Dict[str, Any]


def recommend_courses(
    conn: sqlite3.Connection,
    ma_sv: str,
    nam_hoc: Optional[int] = None,
    hoc_ky: Optional[int] = None,
    limit: int = 10,
) -> pd.DataFrame:
    profile = get_student_profile(conn, ma_sv, nam_hoc=nam_hoc, hoc_ky=hoc_ky)
    curriculum = conn.execute(
        """
        SELECT MaMH, TenMH, SoTC, LoaiYC, HKGoiY
        FROM v_mon_hoc_ctdt
        WHERE MaCTDT = :ma_ctdt
        ORDER BY HKGoiY, LoaiYC, TenMH
        """,
        {"ma_ctdt": profile.ma_ctdt},
    ).fetchall()

    rows: List[RowDict] = []
    for course in curriculum:
        ma_mh = str(course["MaMH"])
        if ma_mh in profile.passed_courses:
            continue
        if ma_mh in profile.registered_courses:
            continue

        sections = _candidate_sections(conn, ma_mh, profile.current_nam_hoc, profile.current_hoc_ky)
        eligible_sections: List[RowDict] = []
        blocked_reasons: set[str] = set()
        for section in sections:
            eligibility = check_registration_eligibility(
                conn,
                ma_sv=profile.ma_sv,
                ma_lhp=section["MaLHP"],
                max_credits=MAX_CREDITS_PER_SEMESTER,
            )
            if eligibility["CoTheDangKy"] == 1:
                eligible_sections.append({**section, **eligibility})
            else:
                blocked_reasons.update(str(reason) for reason in eligibility.get("LyDoKhongDangKy", []))

        if not eligible_sections and sections:
            rows.append(
                _blocked_row(
                    profile=profile,
                    course=dict(course),
                    blocked_reasons=sorted(blocked_reasons),
                    status="KHONG_GOI_Y",
                )
            )
            continue
        if not eligible_sections:
            rows.append(
                _blocked_row(
                    profile=profile,
                    course=dict(course),
                    blocked_reasons=["KHONG_CO_LOP_MO_KY_HIEN_TAI"],
                    status="KHONG_GOI_Y",
                )
            )
            continue

        best = _rank_sections(eligible_sections)[0]
        rows.append(_recommended_row(profile=profile, course=dict(course), section=best))

    ranked = sorted(rows, key=_rank_recommendation_row)
    visible = ranked[:limit]
    return pd.DataFrame(visible)


def _candidate_sections(conn: sqlite3.Connection, ma_mh: str, nam_hoc: int, hoc_ky: int) -> List[RowDict]:
    rows = conn.execute(
        """
        SELECT MaLHP, MaMH, TenMH, Nhom, NamHoc, HocKy, TrangThaiLHP, SoTC,
               SiSoDK, SiSoTD, SoChoCon, LichHocText, TenGV
        FROM v_lop_hoc_phan_day_du
        WHERE MaMH = :ma_mh
          AND NamHoc = :nam_hoc
          AND HocKy = :hoc_ky
          AND TrangThaiLHP = 'MO'
          AND SoChoCon > 0
        ORDER BY SoChoCon DESC, Nhom ASC
        """,
        {"ma_mh": ma_mh, "nam_hoc": nam_hoc, "hoc_ky": hoc_ky},
    ).fetchall()
    return [dict(row) for row in rows]


def _rank_sections(sections: List[RowDict]) -> List[RowDict]:
    return sorted(sections, key=lambda row: (-int(row.get("SoChoCon") or 0), str(row.get("Nhom") or "")))


def _recommended_row(profile, course: RowDict, section: RowDict) -> RowDict:
    reasons = _positive_reasons(profile, course)
    reasons.extend(["DU_TIEN_QUYET", "LOP_DANG_MO_CON_CHO", "KHONG_TRUNG_LICH", "KHONG_VUOT_TIN_CHI"])
    return {
        "TrangThaiGoiY": "GOI_Y",
        "MucUuTien": _priority(profile, course),
        "MaSV": profile.ma_sv,
        "HoTen": profile.ho_ten,
        "MaMH": course["MaMH"],
        "TenMH": course["TenMH"],
        "SoTC": course["SoTC"],
        "LoaiYC": course["LoaiYC"],
        "HKGoiY": course["HKGoiY"],
        "MaLHPGoiY": section["MaLHP"],
        "Nhom": section["Nhom"],
        "NamHoc": profile.current_nam_hoc,
        "HocKy": profile.current_hoc_ky,
        "SoChoCon": section["SoChoCon"],
        "LichHocText": section["LichHocText"],
        "TenGV": section["TenGV"],
        "LyDoGoiY": ", ".join(reasons),
        "LyDoKhongGoiY": "",
    }


def _blocked_row(profile, course: RowDict, blocked_reasons: List[str], status: str) -> RowDict:
    return {
        "TrangThaiGoiY": status,
        "MucUuTien": "LOW",
        "MaSV": profile.ma_sv,
        "HoTen": profile.ho_ten,
        "MaMH": course["MaMH"],
        "TenMH": course["TenMH"],
        "SoTC": course["SoTC"],
        "LoaiYC": course["LoaiYC"],
        "HKGoiY": course["HKGoiY"],
        "MaLHPGoiY": None,
        "Nhom": None,
        "NamHoc": profile.current_nam_hoc,
        "HocKy": profile.current_hoc_ky,
        "SoChoCon": None,
        "LichHocText": None,
        "TenGV": None,
        "LyDoGoiY": "",
        "LyDoKhongGoiY": ", ".join(blocked_reasons),
    }


def _positive_reasons(profile, course: RowDict) -> List[str]:
    reasons = ["THUOC_CTDT"]
    if course.get("LoaiYC") == "BAT_BUOC":
        reasons.append("MON_BAT_BUOC")
    else:
        reasons.append("MON_TU_CHON")
    hkg = int(course.get("HKGoiY") or 0)
    if hkg == profile.estimated_term_index:
        reasons.append("DUNG_KY_GOI_Y")
    elif hkg < profile.estimated_term_index:
        reasons.append("MON_CON_THIEU_TU_KY_TRUOC")
    else:
        reasons.append("MON_KY_SAU_NHUNG_DU_DIEU_KIEN")
    return reasons


def _priority(profile, course: RowDict) -> str:
    hkg = int(course.get("HKGoiY") or 0)
    if course.get("LoaiYC") == "BAT_BUOC" and hkg <= profile.estimated_term_index:
        return "HIGH"
    if hkg <= profile.estimated_term_index + 1:
        return "MEDIUM"
    return "LOW"


def _rank_recommendation_row(row: RowDict) -> tuple[int, int, int, str]:
    status_rank = 0 if row["TrangThaiGoiY"] == "GOI_Y" else 1
    priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(str(row.get("MucUuTien")), 3)
    semester = int(row.get("HKGoiY") or 99)
    return (status_rank, priority_rank, semester, str(row.get("TenMH") or ""))
