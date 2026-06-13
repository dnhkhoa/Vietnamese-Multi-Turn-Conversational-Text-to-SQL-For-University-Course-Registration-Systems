from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from .business_rules import MAX_CREDITS_PER_SEMESTER, check_registration_eligibility, get_credit_load


RowDict = Dict[str, Any]


def current_term(conn: sqlite3.Connection) -> tuple[Optional[int], Optional[int]]:
    row = conn.execute(
        """
        SELECT NamHoc, HocKy
        FROM LopHP
        ORDER BY NamHoc DESC, HocKy DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None, None
    return int(row["NamHoc"]), int(row["HocKy"])


def _fetch_all(conn: sqlite3.Connection, sql: str, params: Optional[dict] = None) -> List[RowDict]:
    return [dict(row) for row in conn.execute(sql, params or {}).fetchall()]


def _fetch_one(conn: sqlite3.Connection, sql: str, params: Optional[dict] = None) -> Optional[RowDict]:
    row = conn.execute(sql, params or {}).fetchone()
    return dict(row) if row else None


def _student(conn: sqlite3.Connection, ma_sv: str) -> Optional[RowDict]:
    return _fetch_one(
        conn,
        """
        SELECT MaSV, HoTen, TrangThaiSV, MaCTDT, MaNganh, TenNganh
        FROM v_sinh_vien_day_du
        WHERE MaSV = :ma_sv
        """,
        {"ma_sv": ma_sv},
    )


def _passed_courses(conn: sqlite3.Connection, ma_sv: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT MaMH
        FROM v_ket_qua_day_du
        WHERE MaSV = :ma_sv
          AND KetQua = 'DAT'
        """,
        {"ma_sv": ma_sv},
    ).fetchall()
    return {row["MaMH"] for row in rows}


def _failed_courses(conn: sqlite3.Connection, ma_sv: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT DISTINCT MaMH
        FROM v_ket_qua_day_du
        WHERE MaSV = :ma_sv
          AND KetQua = 'KHONG_DAT'
          AND MaMH NOT IN (
              SELECT MaMH
              FROM v_ket_qua_day_du
              WHERE MaSV = :ma_sv
                AND KetQua = 'DAT'
          )
        """,
        {"ma_sv": ma_sv},
    ).fetchall()
    return {row["MaMH"] for row in rows}


def _curriculum_courses(conn: sqlite3.Connection, ma_ctdt: str, loai_yc: Optional[str] = None) -> List[RowDict]:
    conditions = ["MaCTDT = :ma_ctdt"]
    params: Dict[str, Any] = {"ma_ctdt": ma_ctdt}
    if loai_yc:
        conditions.append("LoaiYC = :loai_yc")
        params["loai_yc"] = loai_yc
    return _fetch_all(
        conn,
        f"""
        SELECT MaMH, TenMH, SoTC, LoaiYC, HKGoiY
        FROM v_mon_hoc_ctdt
        WHERE {' AND '.join(conditions)}
        ORDER BY HKGoiY, LoaiYC, TenMH
        """,
        params,
    )


def _open_offerings(
    conn: sqlite3.Connection,
    ma_mh: str,
    nam_hoc: int,
    hoc_ky: int,
) -> List[RowDict]:
    return _fetch_all(
        conn,
        """
        SELECT MaLHP, MaMH, TenMH, Nhom, SoTC, NamHoc, HocKy, TrangThaiLHP, SoChoCon, LichHocText, TenGV
        FROM v_lop_hoc_phan_day_du
        WHERE MaMH = :ma_mh
          AND NamHoc = :nam_hoc
          AND HocKy = :hoc_ky
          AND TrangThaiLHP = 'MO'
          AND SoChoCon > 0
        ORDER BY SoChoCon DESC, Nhom ASC
        """,
        {"ma_mh": ma_mh, "nam_hoc": nam_hoc, "hoc_ky": hoc_ky},
    )


def _missing_prerequisite_count(conn: sqlite3.Connection, ma_sv: str, ma_mh: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS SoMonThieu
        FROM v_tien_quyet_day_du tq
        LEFT JOIN KetQua kq
            ON kq.MaSV = :ma_sv
           AND kq.MaMH = tq.MaMHTQ
           AND kq.KetQua = 'DAT'
        WHERE tq.MaMH = :ma_mh
          AND kq.MaMH IS NULL
        """,
        {"ma_sv": ma_sv, "ma_mh": ma_mh},
    ).fetchone()
    return int(row["SoMonThieu"])


def _priority(course: RowDict, failed: set[str], hoc_ky: int, eligible: bool) -> tuple[str, int, List[str]]:
    reasons: List[str] = []
    score = 0
    if course["MaMH"] in failed:
        reasons.append("MON_DA_ROT_NEN_HOC_LAI")
        score += 100
    if course["LoaiYC"] == "BAT_BUOC":
        reasons.append("MON_BAT_BUOC")
        score += 60
    else:
        reasons.append("MON_TU_CHON")
        score += 20
    if course["HKGoiY"] <= hoc_ky:
        reasons.append("DUNG_TIEN_DO_HOAC_DA_DEN_KY")
        score += 30
    else:
        reasons.append("CHUA_DEN_HK_GOI_Y")
        score -= 15
    if eligible:
        reasons.append("CO_LOP_DU_DIEU_KIEN")
        score += 40
    else:
        reasons.append("CHUA_CO_LOP_DU_DIEU_KIEN")
        score -= 40

    if score >= 120:
        level = "VERY_HIGH"
    elif score >= 90:
        level = "HIGH"
    elif score >= 55:
        level = "MEDIUM"
    else:
        level = "LOW"
    return level, score, reasons


def recommend_courses(
    conn: sqlite3.Connection,
    ma_sv: str,
    nam_hoc: Optional[int] = None,
    hoc_ky: Optional[int] = None,
    loai_yc: Optional[str] = None,
    limit: int = 10,
    include_ineligible: bool = True,
) -> List[RowDict]:
    student = _student(conn, ma_sv)
    if student is None:
        return [
            {
                "TrangThaiGoiY": "KHONG_GOI_Y",
                "MaSV": ma_sv,
                "LyDoKhongGoiY": "SINH_VIEN_KHONG_TON_TAI",
            }
        ]
    if student["TrangThaiSV"] != "DANG_HOC":
        return [
            {
                "TrangThaiGoiY": "KHONG_GOI_Y",
                "MaSV": ma_sv,
                "HoTen": student["HoTen"],
                "LyDoKhongGoiY": "SINH_VIEN_KHONG_DANG_HOC",
            }
        ]

    current_nam_hoc, current_hoc_ky = current_term(conn)
    nam_hoc = int(nam_hoc or current_nam_hoc or 0)
    hoc_ky = int(hoc_ky or current_hoc_ky or 0)
    passed = _passed_courses(conn, ma_sv)
    failed = _failed_courses(conn, ma_sv)
    credit_load = get_credit_load(conn, ma_sv, nam_hoc, hoc_ky)
    curriculum = _curriculum_courses(conn, student["MaCTDT"], loai_yc=loai_yc)

    recommendations: List[RowDict] = []
    for course in curriculum:
        if course["MaMH"] in passed:
            continue
        offerings = _open_offerings(conn, course["MaMH"], nam_hoc, hoc_ky)
        if not offerings:
            recommendations.append(
                {
                    "TrangThaiGoiY": "KHONG_GOI_Y",
                    "MucUuTien": "LOW",
                    "DiemUuTien": 0,
                    "MaSV": ma_sv,
                    "HoTen": student["HoTen"],
                    "MaMH": course["MaMH"],
                    "TenMH": course["TenMH"],
                    "SoTC": course["SoTC"],
                    "LoaiYC": course["LoaiYC"],
                    "HKGoiY": course["HKGoiY"],
                    "NamHoc": nam_hoc,
                    "HocKy": hoc_ky,
                    "LyDoGoiY": "KHONG_CO_LOP_MO_KY_NAY",
                    "LyDoKhongGoiY": "KHONG_CO_LOP_MO_KY_NAY",
                }
            )
            continue

        best: Optional[RowDict] = None
        best_eligibility: Optional[RowDict] = None
        for offering in offerings:
            eligibility = check_registration_eligibility(conn, ma_sv, offering["MaLHP"])
            if eligibility["CoTheDangKy"] == 1:
                best = offering
                best_eligibility = eligibility
                break
            if best is None:
                best = offering
                best_eligibility = eligibility

        assert best is not None and best_eligibility is not None
        eligible = best_eligibility["CoTheDangKy"] == 1
        if not eligible and not include_ineligible:
            continue

        priority, score, reasons = _priority(course, failed, hoc_ky, eligible)
        missing_prereq = _missing_prerequisite_count(conn, ma_sv, course["MaMH"])
        reasons_from_eligibility = best_eligibility.get("LyDoKhongDangKy") or []
        if reasons_from_eligibility:
            reasons.extend(str(reason) for reason in reasons_from_eligibility)
        recommendations.append(
            {
                "TrangThaiGoiY": "GOI_Y" if eligible else "KHONG_GOI_Y",
                "MucUuTien": priority,
                "DiemUuTien": score,
                "MaSV": ma_sv,
                "HoTen": student["HoTen"],
                "MaMH": course["MaMH"],
                "TenMH": course["TenMH"],
                "SoTC": course["SoTC"],
                "LoaiYC": course["LoaiYC"],
                "HKGoiY": course["HKGoiY"],
                "MaLHPGoiY": best["MaLHP"],
                "Nhom": best["Nhom"],
                "NamHoc": nam_hoc,
                "HocKy": hoc_ky,
                "SoChoCon": best["SoChoCon"],
                "LichHocText": best["LichHocText"],
                "TenGV": best["TenGV"],
                "TinChiHienTai": credit_load,
                "TinChiSauDangKy": credit_load + course["SoTC"],
                "SoMonTienQuyetThieu": missing_prereq,
                "LyDoGoiY": ", ".join(dict.fromkeys(reasons)),
                "LyDoKhongGoiY": ", ".join(reasons_from_eligibility),
            }
        )

    recommendations.sort(
        key=lambda row: (
            0 if row.get("TrangThaiGoiY") == "GOI_Y" else 1,
            -int(row.get("DiemUuTien") or 0),
            int(row.get("HKGoiY") or 99),
            str(row.get("TenMH") or ""),
        )
    )
    return recommendations[: max(1, int(limit))]
