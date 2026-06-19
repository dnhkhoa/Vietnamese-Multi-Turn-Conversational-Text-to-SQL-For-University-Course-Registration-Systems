from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import unicodedata
from collections import defaultdict
from pathlib import Path


DEFAULT_SOURCE = Path("ctdt_sis_v2.db")
DEFAULT_OUTPUT = Path("ctdt_sis_v2_fixed.db")


COURSE_RENAMES = {
    "CLCO332779E": "Cloud computing (2+1) - elective",
    "CLCO432779E": "Cloud computing (2+1) - core",
    "INSE330379E": "Information Security (INSE330379E)",
    "INSE330380E": "Information Security (INSE330380E)",
    "GRPR423279E": "Internship (2 credits)",
    "ITIN441085E": "Internship (4 credits)",
}


def strip_accents(value: str) -> str:
    value = value.replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def normalize_text(value: str) -> str:
    value = strip_accents(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def schedules_overlap(schedules_a: list[tuple[int, int, int]], schedules_b: list[tuple[int, int, int]]) -> bool:
    for day_a, start_a, end_a in schedules_a:
        for day_b, start_b, end_b in schedules_b:
            if day_a == day_b and start_a <= end_b and start_b <= end_a:
                return True
    return False


def copy_database(source: Path, output: Path) -> None:
    if not source.exists():
        raise FileNotFoundError(source)
    if output.exists():
        output.unlink()
    shutil.copy2(source, output)


def delete_invalid_prerequisite_registrations(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT DISTINCT dk.MaSV, dk.MaLHP
        FROM DangKy dk
        JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
        JOIN QuanHeHocPhan qh
          ON qh.MaMH = lhp.MaMH
         AND qh.LoaiQuanHe = 'TIEN_QUYET'
        LEFT JOIN KetQua kq
          ON kq.MaSV = dk.MaSV
         AND kq.MaMH = qh.MaMHDieuKien
         AND kq.KetQua = 'DAT'
        WHERE kq.MaSV IS NULL
        """
    ).fetchall()
    conn.executemany("DELETE FROM DangKy WHERE MaSV = ? AND MaLHP = ?", rows)
    return len(rows)


def refresh_registration_counts(conn: sqlite3.Connection) -> None:
    conn.execute("UPDATE LopHP SET SiSoDK = 0")
    conn.execute(
        """
        UPDATE LopHP
        SET SiSoDK = (
            SELECT COUNT(*)
            FROM DangKy dk
            WHERE dk.MaLHP = LopHP.MaLHP
        )
        """
    )
    conn.execute(
        """
        UPDATE LopHP
        SET TrangThai = 'DAY'
        WHERE TrangThai IN ('MO', 'DAY')
          AND SiSoDK >= SiSoTD
        """
    )
    conn.execute(
        """
        UPDATE LopHP
        SET TrangThai = 'MO'
        WHERE TrangThai IN ('MO', 'DAY')
          AND SiSoDK < SiSoTD
        """
    )
    conn.execute(
        """
        UPDATE HoSoHocTapSinhVien
        SET TinChiDangKyHienTai = (
            SELECT COALESCE(SUM(mh.SoTC), 0)
            FROM DangKy dk
            JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
            JOIN MonHoc mh ON mh.MaMH = lhp.MaMH
            WHERE dk.MaSV = HoSoHocTapSinhVien.MaSV
        )
        """
    )


def fix_course_names_and_aliases(conn: sqlite3.Connection) -> int:
    renamed = 0
    for ma_mh, ten_mh in COURSE_RENAMES.items():
        cur = conn.execute("UPDATE MonHoc SET TenMH = ? WHERE MaMH = ?", (ten_mh, ma_mh))
        renamed += cur.rowcount

    for ma_mh, ten_mh in COURSE_RENAMES.items():
        alias = normalize_text(ten_mh)
        conn.execute(
            """
            INSERT OR IGNORE INTO MonHocAlias
                (MaMH, Alias, AliasNormalized, LoaiAlias, Nguon)
            VALUES (?, ?, ?, 'TEN_MON_KHONG_DAU', 'FIX_V2')
            """,
            (ma_mh, alias, alias),
        )

    ambiguous_aliases = conn.execute(
        """
        SELECT AliasNormalized
        FROM MonHocAlias
        GROUP BY AliasNormalized
        HAVING COUNT(DISTINCT MaMH) > 1
        """
    ).fetchall()
    conn.executemany(
        "DELETE FROM MonHocAlias WHERE AliasNormalized = ?",
        ambiguous_aliases,
    )

    conn.execute(
        """
        UPDATE MonHoc
        SET HocPhanTienQuyetText = (
                SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                FROM QuanHeHocPhan qh
                JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                WHERE qh.MaMH = MonHoc.MaMH
                  AND qh.LoaiQuanHe = 'TIEN_QUYET'
            ),
            HocPhanHocTruocText = (
                SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                FROM QuanHeHocPhan qh
                JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                WHERE qh.MaMH = MonHoc.MaMH
                  AND qh.LoaiQuanHe = 'HOC_TRUOC'
            ),
            HocPhanTuongDuongText = (
                SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                FROM QuanHeHocPhan qh
                JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                WHERE qh.MaMH = MonHoc.MaMH
                  AND qh.LoaiQuanHe = 'TUONG_DUONG'
            )
        """
    )
    return renamed


def fix_result_history_order(conn: sqlite3.Connection) -> int:
    pairs = conn.execute(
        """
        WITH latest AS (
            SELECT MaSV, MaMH, KetQua, NamHoc, HocKy, LanHoc, KetQuaID,
                   ROW_NUMBER() OVER (
                       PARTITION BY MaSV, MaMH
                       ORDER BY NamHoc DESC, HocKy DESC, LanHoc DESC, KetQuaID DESC
                   ) AS rn
            FROM KetQuaHocTap
            WHERE KetQua IN ('DAT', 'KHONG_DAT')
        )
        SELECT k.MaSV, k.MaMH
        FROM KetQua k
        JOIN latest
          ON latest.MaSV = k.MaSV
         AND latest.MaMH = k.MaMH
         AND latest.rn = 1
        WHERE k.KetQua = 'DAT'
          AND latest.KetQua = 'KHONG_DAT'
        """
    ).fetchall()

    fixed = 0
    for ma_sv, ma_mh in pairs:
        fail_row = conn.execute(
            """
            SELECT KetQuaID
            FROM KetQuaHocTap
            WHERE MaSV = ?
              AND MaMH = ?
              AND KetQua = 'KHONG_DAT'
            ORDER BY NamHoc DESC, HocKy DESC, LanHoc DESC, KetQuaID DESC
            LIMIT 1
            """,
            (ma_sv, ma_mh),
        ).fetchone()
        pass_row = conn.execute(
            """
            SELECT KetQuaID
            FROM KetQuaHocTap
            WHERE MaSV = ?
              AND MaMH = ?
              AND KetQua = 'DAT'
            ORDER BY NamHoc DESC, HocKy DESC, LanHoc DESC, KetQuaID DESC
            LIMIT 1
            """,
            (ma_sv, ma_mh),
        ).fetchone()
        if not fail_row or not pass_row:
            continue

        conn.execute(
            """
            UPDATE KetQuaHocTap
            SET NamHoc = 2024,
                HocKy = 1,
                LanHoc = 1,
                LoaiHoc = 'HOC_MOI'
            WHERE KetQuaID = ?
            """,
            (fail_row[0],),
        )
        conn.execute(
            """
            UPDATE KetQuaHocTap
            SET NamHoc = 2024,
                HocKy = 2,
                LanHoc = 2,
                LoaiHoc = 'HOC_LAI'
            WHERE KetQuaID = ?
            """,
            (pass_row[0],),
        )
        conn.execute(
            """
            UPDATE KetQua
            SET NamHoc = 2024,
                HocKy = 2,
                KetQua = 'DAT'
            WHERE MaSV = ?
              AND MaMH = ?
            """,
            (ma_sv, ma_mh),
        )
        fixed += 1
    return fixed


def rebuild_teaching_assignments(conn: sqlite3.Connection) -> int:
    lecturers_by_department: dict[str | None, list[str]] = defaultdict(list)
    all_lecturers: list[str] = []
    for ma_gv, ma_khoa_bm in conn.execute("SELECT MaGV, MaKhoaBM FROM GiangVien ORDER BY MaGV"):
        lecturers_by_department[ma_khoa_bm].append(ma_gv)
        all_lecturers.append(ma_gv)

    schedules_by_class = {
        ma_lhp: [(thu, tiet_bd, tiet_kt) for thu, tiet_bd, tiet_kt in rows]
        for ma_lhp, rows in (
            (ma_lhp, conn.execute(
                """
                SELECT Thu, TietBD, TietKT
                FROM LichHoc
                WHERE MaLHP = ?
                ORDER BY Thu, TietBD, TietKT
                """,
                (ma_lhp,),
            ).fetchall())
            for (ma_lhp,) in conn.execute("SELECT MaLHP FROM LopHP")
        )
    }

    offerings = conn.execute(
        """
        SELECT lhp.MaLHP, lhp.NamHoc, lhp.HocKy, mh.MaKhoaBM
        FROM LopHP lhp
        JOIN MonHoc mh ON mh.MaMH = lhp.MaMH
        ORDER BY lhp.NamHoc, lhp.HocKy, mh.MaKhoaBM, lhp.MaLHP
        """
    ).fetchall()

    conn.execute("DELETE FROM PhanCong")
    occupied: dict[tuple[str, int, int], list[tuple[int, int, int]]] = defaultdict(list)
    load: dict[tuple[str, int, int], int] = defaultdict(int)
    assigned = 0

    for ma_lhp, nam_hoc, hoc_ky, ma_khoa_bm in offerings:
        schedules = schedules_by_class[ma_lhp]
        candidates = lecturers_by_department.get(ma_khoa_bm, []) + [
            gv for gv in all_lecturers if gv not in set(lecturers_by_department.get(ma_khoa_bm, []))
        ]
        chosen = None
        compatible = []
        for ma_gv in candidates:
            key = (ma_gv, nam_hoc, hoc_ky)
            if not schedules_overlap(occupied[key], schedules):
                compatible.append(ma_gv)
        if compatible:
            chosen = min(compatible, key=lambda gv: (load[(gv, nam_hoc, hoc_ky)], gv))
        else:
            chosen = min(
                candidates,
                key=lambda gv: (
                    sum(1 for existing in occupied[(gv, nam_hoc, hoc_ky)] if schedules_overlap([existing], schedules)),
                    load[(gv, nam_hoc, hoc_ky)],
                    gv,
                ),
            )

        conn.execute(
            """
            INSERT INTO PhanCong (MaLHP, MaGV, VaiTro)
            VALUES (?, ?, 'GIANG_VIEN_CHINH')
            """,
            (ma_lhp, chosen),
        )
        occupied[(chosen, nam_hoc, hoc_ky)].extend(schedules)
        load[(chosen, nam_hoc, hoc_ky)] += 1
        assigned += 1

    return assigned


def audit_counts(conn: sqlite3.Connection) -> dict[str, int | str]:
    checks: dict[str, int | str] = {}
    checks["integrity_check"] = conn.execute("PRAGMA integrity_check").fetchone()[0]
    checks["foreign_key_errors"] = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    checks["duplicate_course_names"] = conn.execute(
        """
        WITH norm AS (
            SELECT lower(trim(replace(replace(replace(replace(TenMH, '  ', ' '), char(9), ' '), '(*)', ''), '  ', ' '))) AS n
            FROM MonHoc
        )
        SELECT COUNT(*)
        FROM (
            SELECT n
            FROM norm
            GROUP BY n
            HAVING COUNT(*) > 1
        )
        """
    ).fetchone()[0]
    checks["ambiguous_aliases"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM (
            SELECT AliasNormalized
            FROM MonHocAlias
            GROUP BY AliasNormalized
            HAVING COUNT(DISTINCT MaMH) > 1
        )
        """
    ).fetchone()[0]
    checks["missing_prerequisite_registrations"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM DangKy dk
        JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
        JOIN QuanHeHocPhan qh
          ON qh.MaMH = lhp.MaMH
         AND qh.LoaiQuanHe = 'TIEN_QUYET'
        LEFT JOIN KetQua kq
          ON kq.MaSV = dk.MaSV
         AND kq.MaMH = qh.MaMHDieuKien
         AND kq.KetQua = 'DAT'
        WHERE kq.MaSV IS NULL
        """
    ).fetchone()[0]
    checks["student_schedule_conflicts"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM DangKy d1
        JOIN DangKy d2 ON d2.MaSV = d1.MaSV AND d2.MaLHP > d1.MaLHP
        JOIN LopHP l1 ON l1.MaLHP = d1.MaLHP
        JOIN LopHP l2 ON l2.MaLHP = d2.MaLHP AND l2.NamHoc = l1.NamHoc AND l2.HocKy = l1.HocKy
        JOIN LichHoc lh1 ON lh1.MaLHP = d1.MaLHP
        JOIN LichHoc lh2 ON lh2.MaLHP = d2.MaLHP
         AND lh2.Thu = lh1.Thu
         AND lh1.TietBD <= lh2.TietKT
         AND lh2.TietBD <= lh1.TietKT
        """
    ).fetchone()[0]
    checks["room_schedule_conflicts"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM LichHoc lh1
        JOIN LichHoc lh2
          ON lh2.MaLich > lh1.MaLich
         AND lh2.MaPhong = lh1.MaPhong
         AND lh2.Thu = lh1.Thu
         AND lh1.TietBD <= lh2.TietKT
         AND lh2.TietBD <= lh1.TietKT
        JOIN LopHP l1 ON l1.MaLHP = lh1.MaLHP
        JOIN LopHP l2 ON l2.MaLHP = lh2.MaLHP AND l2.NamHoc = l1.NamHoc AND l2.HocKy = l1.HocKy
        """
    ).fetchone()[0]
    checks["lecturer_schedule_conflicts"] = conn.execute(
        """
        SELECT COUNT(*)
        FROM PhanCong pc1
        JOIN PhanCong pc2 ON pc2.MaGV = pc1.MaGV AND pc2.MaLHP > pc1.MaLHP
        JOIN LopHP l1 ON l1.MaLHP = pc1.MaLHP
        JOIN LopHP l2 ON l2.MaLHP = pc2.MaLHP AND l2.NamHoc = l1.NamHoc AND l2.HocKy = l1.HocKy
        JOIN LichHoc lh1 ON lh1.MaLHP = pc1.MaLHP
        JOIN LichHoc lh2 ON lh2.MaLHP = pc2.MaLHP
         AND lh2.Thu = lh1.Thu
         AND lh1.TietBD <= lh2.TietKT
         AND lh2.TietBD <= lh1.TietKT
        """
    ).fetchone()[0]
    checks["enrollment_count_mismatches"] = conn.execute(
        """
        WITH cnt AS (
            SELECT MaLHP, COUNT(*) AS ActualDK
            FROM DangKy
            GROUP BY MaLHP
        )
        SELECT COUNT(*)
        FROM LopHP l
        LEFT JOIN cnt ON cnt.MaLHP = l.MaLHP
        WHERE l.SiSoDK != COALESCE(cnt.ActualDK, 0)
        """
    ).fetchone()[0]
    checks["current_credit_mismatches"] = conn.execute(
        """
        WITH current_credits AS (
            SELECT dk.MaSV, COALESCE(SUM(mh.SoTC), 0) AS Credits
            FROM DangKy dk
            JOIN LopHP l ON l.MaLHP = dk.MaLHP
            JOIN MonHoc mh ON mh.MaMH = l.MaMH
            GROUP BY dk.MaSV
        )
        SELECT COUNT(*)
        FROM HoSoHocTapSinhVien hs
        LEFT JOIN current_credits cc ON cc.MaSV = hs.MaSV
        WHERE hs.TinChiDangKyHienTai != COALESCE(cc.Credits, 0)
        """
    ).fetchone()[0]
    checks["ketqua_latest_mismatches"] = conn.execute(
        """
        WITH latest AS (
            SELECT MaSV, MaMH, KetQua,
                   ROW_NUMBER() OVER (
                       PARTITION BY MaSV, MaMH
                       ORDER BY NamHoc DESC, HocKy DESC, LanHoc DESC, KetQuaID DESC
                   ) AS rn
            FROM KetQuaHocTap
            WHERE KetQua IN ('DAT', 'KHONG_DAT')
        )
        SELECT COUNT(*)
        FROM KetQua k
        JOIN latest
          ON latest.MaSV = k.MaSV
         AND latest.MaMH = k.MaMH
         AND latest.rn = 1
        WHERE k.KetQua != latest.KetQua
        """
    ).fetchone()[0]
    return checks


def fix_database(source: Path, output: Path) -> dict[str, int | str]:
    copy_database(source, output)
    conn = sqlite3.connect(output)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("BEGIN")
        deleted_registrations = delete_invalid_prerequisite_registrations(conn)
        refresh_registration_counts(conn)
        renamed_courses = fix_course_names_and_aliases(conn)
        fixed_histories = fix_result_history_order(conn)
        rebuilt_assignments = rebuild_teaching_assignments(conn)
        conn.commit()

        checks = audit_counts(conn)
        checks["deleted_invalid_registrations"] = deleted_registrations
        checks["renamed_courses"] = renamed_courses
        checks["fixed_result_histories"] = fixed_histories
        checks["rebuilt_teaching_assignments"] = rebuilt_assignments
        return checks
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a fixed copy of ctdt_sis_v2.db.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    checks = fix_database(args.source, args.output)
    print(f"Fixed DB written to: {args.output.resolve()}")
    for key, value in checks.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
