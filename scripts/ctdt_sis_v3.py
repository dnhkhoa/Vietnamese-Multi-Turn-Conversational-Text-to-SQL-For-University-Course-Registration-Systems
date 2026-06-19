from __future__ import annotations

import argparse
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "ctdt_sis_v2_fixed.db"
DEFAULT_OUTPUT_DB = PROJECT_ROOT / "data" / "ctdt_sis_v3.db"
CURRENT_YEAR_KEY = "NAM_HOC_HIEN_TAI"
CURRENT_TERM_KEY = "HOC_KY_HIEN_TAI"
DYNAMIC_PROFILE_LABELS = ("TRUNG_LICH", "THIEU_TIEN_QUYET", "VUOT_TIN_CHI")
TARGET_NULL_ACADEMIC_WARNING_RATIO = 0.78
NO_MON_WARNING_DEBT_THRESHOLD = 1
MIN_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS = 12
TARGET_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS = 15
MAX_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS = 18
REALISTIC_TOTAL_CREDITS_TO_GRADUATE = 150
NEAR_GRADUATION_CREDIT_RATIO = 0.85


PROFILE_NOTES = {
    "DUNG_TIEN_DO": "Sinh viên đang học đúng tiến độ tương đối so với dữ liệu học tập hiện có.",
    "HOC_LAI_NHIEU": "Sinh viên có nhiều lần học lại hoặc cải thiện điểm trong lịch sử học tập.",
    "ROT_DAI_CUONG": "Sinh viên từng rớt một số môn đại cương hoặc nền tảng.",
    "ROT_NEN_TANG_CNTT": "Sinh viên từng rớt một số môn nền tảng công nghệ thông tin.",
    "CAI_THIEN_DIEM": "Sinh viên có lịch sử học cải thiện điểm sau khi đã đạt môn.",
    "DIEM_TB_CAO": "Sinh viên có điểm trung bình cao và đạt hầu hết các môn đã học.",
    "DIEM_TB_THAP": "Sinh viên có điểm trung bình thấp theo dữ liệu kết quả học tập.",
    "GAN_TOT_NGHIEP": "Sinh viên đã tích lũy nhiều tín chỉ và gần hoàn thành chương trình.",
}


WARNING_NOTES = {
    "CANH_BAO_DIEM_TB_THAP": "Sinh viên bị cảnh báo học vụ vì GPA hiện tại dưới 2.0.",
    "CANH_BAO_NO_MON": "Sinh viên bị cảnh báo học vụ vì còn nợ môn: có học phần không đạt và chưa có lần học lại đạt.",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build ctdt_sis_v3.db from ctdt_sis_v2_fixed.db.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DB)
    parser.add_argument("--force", action="store_true", help="Overwrite output DB if it already exists.")
    return parser.parse_args()


def copy_database(source: Path, output: Path, force: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source DB not found: {source}")
    if output.exists() and not force:
        raise FileExistsError(f"Output DB already exists: {output}. Use --force to overwrite.")
    output.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, output)


def strict_prerequisite_filter_sql() -> str:
    return """
    SELECT DISTINCT dk.MaSV, dk.MaLHP
    FROM DangKy dk
    JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
    JOIN QuanHeHocPhan qh
      ON qh.MaMH = lhp.MaMH
     AND qh.LoaiQuanHe = 'TIEN_QUYET'
    WHERE NOT EXISTS (
        SELECT 1
        FROM KetQuaHocTap kq
        WHERE kq.MaSV = dk.MaSV
          AND kq.MaMH = qh.MaMHDieuKien
          AND kq.KetQua = 'DAT'
          AND (
              kq.NamHoc < lhp.NamHoc
              OR (kq.NamHoc = lhp.NamHoc AND kq.HocKy < lhp.HocKy)
          )
    )
    """


def remove_strict_prerequisite_violations(conn: sqlite3.Connection) -> int:
    rows = conn.execute(strict_prerequisite_filter_sql()).fetchall()
    conn.execute("DROP TABLE IF EXISTS _v3_dang_ky_xoa")
    conn.execute("CREATE TEMP TABLE _v3_dang_ky_xoa (MaSV TEXT NOT NULL, MaLHP TEXT NOT NULL, PRIMARY KEY (MaSV, MaLHP))")
    conn.executemany(
        "INSERT INTO _v3_dang_ky_xoa (MaSV, MaLHP) VALUES (?, ?)",
        [(row["MaSV"], row["MaLHP"]) for row in rows],
    )
    conn.execute(
        """
        DELETE FROM DangKy
        WHERE EXISTS (
            SELECT 1
            FROM _v3_dang_ky_xoa x
            WHERE x.MaSV = DangKy.MaSV
              AND x.MaLHP = DangKy.MaLHP
        )
        """
    )
    conn.execute("DROP TABLE _v3_dang_ky_xoa")
    return len(rows)


def semester_window_for(today: date) -> tuple[int, int, date, date]:
    if 1 <= today.month <= 5:
        return today.year, 1, date(today.year, 1, 5), date(today.year, 5, 31)
    return today.year, 2, date(today.year, 6, 1), date(today.year, 12, 31)


def refresh_system_semesters(conn: sqlite3.Connection, today: date | None = None) -> tuple[int, int]:
    today = today or date.today()
    current_year, current_term, current_start, current_end = semester_window_for(today)
    semesters = [
        (current_year, 1, date(current_year, 1, 5), date(current_year, 5, 31)),
        (current_year, 2, date(current_year, 6, 1), date(current_year, 12, 31)),
    ]
    rows = []
    for year, term, start, end in semesters:
        is_current = year == current_year and term == current_term
        if is_current:
            status = "DANG_MO_DANG_KY"
            open_flag = 1
        elif end < current_start:
            status = "DA_KET_THUC"
            open_flag = 0
        else:
            status = "SAP_MO"
            open_flag = 0
        rows.append(
            (
                f"{year}-{term}",
                year,
                term,
                f"Học kỳ {term} năm học {year}",
                status,
                open_flag,
                start.isoformat(),
                end.isoformat(),
            )
        )
    conn.executemany(
        """
        INSERT INTO HocKyHeThong
            (MaHocKy, NamHoc, HocKy, TenHocKy, TrangThai, DangMoDangKy, NgayBatDau, NgayKetThuc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(NamHoc, HocKy) DO UPDATE SET
            MaHocKy = excluded.MaHocKy,
            TenHocKy = excluded.TenHocKy,
            TrangThai = excluded.TrangThai,
            DangMoDangKy = excluded.DangMoDangKy,
            NgayBatDau = excluded.NgayBatDau,
            NgayKetThuc = excluded.NgayKetThuc
        """,
        rows,
    )
    return current_year, current_term


def get_open_registration_semester(conn: sqlite3.Connection) -> sqlite3.Row:
    rows = conn.execute(
        """
        SELECT MaHocKy, NamHoc, HocKy
        FROM HocKyHeThong
        WHERE DangMoDangKy = 1
          AND TrangThai = 'DANG_MO_DANG_KY'
        """
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(f"Expected exactly one open registration semester, found {len(rows)}")
    return rows[0]


def sync_current_registration_config(conn: sqlite3.Connection) -> tuple[int, int]:
    semester = get_open_registration_semester(conn)
    rows = [
        (CURRENT_YEAR_KEY, str(semester["NamHoc"]), "Năm học/kế hoạch đăng ký hiện tại của hệ thống."),
        (CURRENT_TERM_KEY, str(semester["HocKy"]), "Học kỳ đăng ký hiện tại của hệ thống."),
        ("MA_HOC_KY_HIEN_TAI", semester["MaHocKy"], "Mã học kỳ đăng ký hiện tại của hệ thống."),
    ]
    conn.executemany(
        """
        INSERT INTO CauHinhDangKy (MaCauHinh, GiaTri, MoTa)
        VALUES (?, ?, ?)
        ON CONFLICT(MaCauHinh) DO UPDATE SET
            GiaTri = excluded.GiaTri,
            MoTa = excluded.MoTa
        """,
        rows,
    )
    return int(semester["NamHoc"]), int(semester["HocKy"])


def remove_non_current_registrations(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT dk.MaSV, dk.MaLHP
        FROM DangKy dk
        JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
        WHERE NOT EXISTS (
            SELECT 1
            FROM HocKyHeThong hk
            WHERE hk.NamHoc = lhp.NamHoc
              AND hk.HocKy = lhp.HocKy
              AND hk.DangMoDangKy = 1
              AND hk.TrangThai = 'DANG_MO_DANG_KY'
        )
        """
    ).fetchall()
    conn.execute(
        """
        DELETE FROM DangKy
        WHERE EXISTS (
            SELECT 1
            FROM LopHP lhp
            WHERE lhp.MaLHP = DangKy.MaLHP
              AND NOT EXISTS (
                  SELECT 1
                  FROM HocKyHeThong hk
                  WHERE hk.NamHoc = lhp.NamHoc
                    AND hk.HocKy = lhp.HocKy
                    AND hk.DangMoDangKy = 1
                    AND hk.TrangThai = 'DANG_MO_DANG_KY'
              )
        )
        """
    )
    return len(rows)


def recalculate_registration_derived_fields(conn: sqlite3.Connection) -> None:
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
        SET TrangThai = CASE
            WHEN SiSoDK >= SiSoTD THEN 'DAY'
            ELSE 'MO'
        END
        WHERE TrangThai IN ('MO', 'DAY')
          AND EXISTS (
              SELECT 1
              FROM HocKyHeThong hk
              WHERE hk.NamHoc = LopHP.NamHoc
                AND hk.HocKy = LopHP.HocKy
                AND hk.DangMoDangKy = 1
                AND hk.TrangThai = 'DANG_MO_DANG_KY'
          )
        """
    )
    conn.execute(
        """
        UPDATE LopHP
        SET TrangThai = 'DONG'
        WHERE TrangThai IN ('MO', 'DAY')
          AND NOT EXISTS (
              SELECT 1
              FROM HocKyHeThong hk
              WHERE hk.NamHoc = LopHP.NamHoc
                AND hk.HocKy = LopHP.HocKy
                AND hk.DangMoDangKy = 1
                AND hk.TrangThai = 'DANG_MO_DANG_KY'
          )
        """
    )
    conn.execute(
        """
        UPDATE HoSoHocTapSinhVien
        SET TinChiDangKyHienTai = COALESCE((
            SELECT SUM(mh.SoTC)
            FROM DangKy dk
            JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
            JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
            WHERE dk.MaSV = HoSoHocTapSinhVien.MaSV
              AND EXISTS (
                  SELECT 1
                  FROM HocKyHeThong hk
                  WHERE hk.NamHoc = lhp.NamHoc
                    AND hk.HocKy = lhp.HocKy
                    AND hk.DangMoDangKy = 1
                    AND hk.TrangThai = 'DANG_MO_DANG_KY'
              )
        ), 0)
        """
    )


def normalize_required_course_suggested_terms(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT MaCTDT, MaMH
        FROM CTDT_MonHoc
        WHERE LoaiYC = 'BAT_BUOC'
          AND HKGoiY IS NULL
        """
    ).fetchall()
    conn.execute(
        """
        WITH ordered AS (
            SELECT
                MaCTDT,
                MaMH,
                CAST(((ROW_NUMBER() OVER (
                    PARTITION BY MaCTDT
                    ORDER BY
                        CASE
                            WHEN STTTrongCTDT GLOB '[0-9]*' THEN CAST(STTTrongCTDT AS INTEGER)
                            ELSE 9999
                        END,
                        ExcelRow,
                        MaMH
                ) - 1) / 5) AS INTEGER) + 1 AS SuggestedTerm
            FROM CTDT_MonHoc
            WHERE LoaiYC = 'BAT_BUOC'
        )
        UPDATE CTDT_MonHoc
        SET HKGoiY = (
            SELECT CASE
                WHEN ordered.SuggestedTerm > 8 THEN 8
                ELSE ordered.SuggestedTerm
            END
            FROM ordered
            WHERE ordered.MaCTDT = CTDT_MonHoc.MaCTDT
              AND ordered.MaMH = CTDT_MonHoc.MaMH
        )
        WHERE LoaiYC = 'BAT_BUOC'
          AND HKGoiY IS NULL
        """
    )
    return len(rows)


def normalize_curriculum_requirements(conn: sqlite3.Connection) -> tuple[int, int]:
    credit_rows = conn.execute(
        """
        SELECT MaCTDT
        FROM CTDT
        WHERE TongTinChiToiThieu IS NULL
           OR TongTinChiToiThieu > 180
        """
    ).fetchall()
    conn.execute(
        """
        UPDATE CTDT
        SET TongTinChiToiThieu = ?
        WHERE TongTinChiToiThieu IS NULL
           OR TongTinChiToiThieu > 180
        """,
        (REALISTIC_TOTAL_CREDITS_TO_GRADUATE,),
    )

    group_rows = conn.execute(
        """
        SELECT MaCTDT, MaNhomTC
        FROM CTDT_NhomTuChon
        WHERE HocKyGoiY IS NULL
        """
    ).fetchall()
    conn.execute(
        """
        UPDATE CTDT_NhomTuChon
        SET HocKyGoiY = COALESCE(
            (
                SELECT CAST(ROUND(AVG(cm.HKGoiY)) AS INTEGER)
                FROM CTDT_MonHoc cm
                WHERE cm.MaCTDT = CTDT_NhomTuChon.MaCTDT
                  AND cm.MaNhomTC = CTDT_NhomTuChon.MaNhomTC
                  AND cm.HKGoiY IS NOT NULL
            ),
            CASE
                WHEN MaNhomTC LIKE '%HK1%' THEN 1
                WHEN MaNhomTC LIKE '%HK2%' THEN 2
                ELSE 7
            END
        )
        WHERE HocKyGoiY IS NULL
        """
    )
    return len(credit_rows), len(group_rows)


def _schedule_conflicts(
    existing: list[tuple[int, int, int]],
    candidate: list[tuple[int, int, int]],
) -> bool:
    for cur_day, cur_start, cur_end in existing:
        for new_day, new_start, new_end in candidate:
            if cur_day == new_day and cur_start <= new_end and new_start <= cur_end:
                return True
    return False


def balance_current_registrations(conn: sqlite3.Connection) -> int:
    open_semester = get_open_registration_semester(conn)
    year = int(open_semester["NamHoc"])
    term = int(open_semester["HocKy"])
    class_rows = conn.execute(
        """
        SELECT
            lhp.MaLHP,
            lhp.MaMH,
            mh.SoTC,
            lhp.SiSoTD,
            lhp.SiSoDK,
            COALESCE(cm.HKGoiY, 8) AS HKGoiY,
            cm.LoaiYC
        FROM LopHP lhp
        JOIN MonHoc mh ON mh.MaMH = lhp.MaMH
        JOIN CTDT_MonHoc cm ON cm.MaMH = lhp.MaMH
        WHERE lhp.NamHoc = ?
          AND lhp.HocKy = ?
          AND lhp.TrangThai = 'MO'
        ORDER BY cm.LoaiYC, cm.HKGoiY, lhp.SiSoDK, lhp.MaLHP
        """,
        (year, term),
    ).fetchall()
    classes = [dict(row) for row in class_rows]
    class_schedules = {
        row["MaLHP"]: [
            (int(slot["Thu"]), int(slot["TietBD"]), int(slot["TietKT"]))
            for slot in conn.execute(
                "SELECT Thu, TietBD, TietKT FROM LichHoc WHERE MaLHP = ?",
                (row["MaLHP"],),
            ).fetchall()
        ]
        for row in classes
    }
    current_counts = {row["MaLHP"]: int(row["SiSoDK"]) for row in classes}
    current_courses = {
        row["MaSV"]: {course["MaMH"] for course in conn.execute(
            """
            SELECT lhp.MaMH
            FROM DangKy dk
            JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
            WHERE dk.MaSV = ?
              AND lhp.NamHoc = ?
              AND lhp.HocKy = ?
            """,
            (row["MaSV"], year, term),
        ).fetchall()}
        for row in conn.execute("SELECT MaSV FROM SinhVien WHERE TrangThai = 'DANG_HOC'").fetchall()
    }
    current_schedules = {
        row["MaSV"]: [
            (int(slot["Thu"]), int(slot["TietBD"]), int(slot["TietKT"]))
            for slot in conn.execute(
                """
                SELECT lh.Thu, lh.TietBD, lh.TietKT
                FROM DangKy dk
                JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
                JOIN LichHoc lh ON lh.MaLHP = lhp.MaLHP
                WHERE dk.MaSV = ?
                  AND lhp.NamHoc = ?
                  AND lhp.HocKy = ?
                """,
                (row["MaSV"], year, term),
            ).fetchall()
        ]
        for row in conn.execute("SELECT MaSV FROM SinhVien WHERE TrangThai = 'DANG_HOC'").fetchall()
    }

    students = conn.execute(
        """
        SELECT
            sv.MaSV,
            kh.MaCTDT,
            hs.GioiHanTinChi,
            hs.TinChiDangKyHienTai,
            hs.TinChiTichLuy
        FROM SinhVien sv
        JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
        JOIN HoSoHocTapSinhVien hs ON hs.MaSV = sv.MaSV
        WHERE sv.TrangThai = 'DANG_HOC'
        ORDER BY sv.MaSV
        """,
    ).fetchall()

    inserted: list[tuple[str, str, str]] = []
    for student in students:
        ma_sv = student["MaSV"]
        ma_ctdt = student["MaCTDT"]
        credit_limit = int(student["GioiHanTinChi"])
        current_credits = int(student["TinChiDangKyHienTai"])
        if current_credits >= MIN_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS:
            continue
        suggested_stage = max(1, min(8, int(student["TinChiTichLuy"] or 0) // 20 + 1))
        allowed_courses = {
            row["MaMH"]: row
            for row in conn.execute(
                """
                SELECT MaMH, COALESCE(HKGoiY, 8) AS HKGoiY, LoaiYC
                FROM CTDT_MonHoc
                WHERE MaCTDT = ?
                """,
                (ma_ctdt,),
            ).fetchall()
        }
        passed_courses = {
            row["MaMH"]
            for row in conn.execute(
                """
                SELECT DISTINCT MaMH
                FROM KetQuaHocTap
                WHERE MaSV = ?
                  AND KetQua = 'DAT'
                  AND (NamHoc < ? OR (NamHoc = ? AND HocKy < ?))
                """,
                (ma_sv, year, year, term),
            ).fetchall()
        }
        missing_prereq_courses = {
            row["MaMH"]
            for row in conn.execute(
                """
                SELECT DISTINCT qh.MaMH
                FROM QuanHeHocPhan qh
                WHERE qh.LoaiQuanHe = 'TIEN_QUYET'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM KetQuaHocTap kq
                      WHERE kq.MaSV = ?
                        AND kq.MaMH = qh.MaMHDieuKien
                        AND kq.KetQua = 'DAT'
                        AND (kq.NamHoc < ? OR (kq.NamHoc = ? AND kq.HocKy < ?))
                  )
                """,
                (ma_sv, year, year, term),
            ).fetchall()
        }
        while current_credits < MIN_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS:
            max_credits = min(credit_limit, MAX_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS)
            candidate_rows = []
            for allow_improvement in (False, True):
                candidate_rows = sorted(
                    (
                        row
                        for row in classes
                        if row["MaMH"] in allowed_courses
                        and row["MaMH"] not in current_courses[ma_sv]
                        and (allow_improvement or row["MaMH"] not in passed_courses)
                        and row["MaMH"] not in missing_prereq_courses
                        and current_counts[row["MaLHP"]] < int(row["SiSoTD"])
                        and current_credits + int(row["SoTC"]) <= max_credits
                        and not _schedule_conflicts(current_schedules[ma_sv], class_schedules[row["MaLHP"]])
                    ),
                    key=lambda row: (
                        1 if row["MaMH"] in passed_courses else 0,
                        abs(int(allowed_courses[row["MaMH"]]["HKGoiY"]) - suggested_stage),
                        0 if allowed_courses[row["MaMH"]]["LoaiYC"] == "BAT_BUOC" else 1,
                        current_counts[row["MaLHP"]],
                        row["MaLHP"],
                    ),
                )
                if candidate_rows:
                    break
            if not candidate_rows:
                break
            selected = candidate_rows[0]
            tgdk = f"{year}-06-20 09:{len(inserted) % 60:02d}:00"
            inserted.append((ma_sv, selected["MaLHP"], tgdk))
            current_counts[selected["MaLHP"]] += 1
            current_courses[ma_sv].add(selected["MaMH"])
            current_schedules[ma_sv].extend(class_schedules[selected["MaLHP"]])
            current_credits += int(selected["SoTC"])

    conn.executemany(
        """
        INSERT OR IGNORE INTO DangKy (MaSV, MaLHP, TGDK)
        VALUES (?, ?, ?)
        """,
        inserted,
    )
    return len(inserted)


def normalize_learning_attempts(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS _v3_kqht_order")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_kqht_order (
            KetQuaID INTEGER PRIMARY KEY,
            NewLanHoc INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO _v3_kqht_order (KetQuaID, NewLanHoc)
        SELECT KetQuaID, NewLanHoc
        FROM (
            SELECT
                KetQuaID,
                ROW_NUMBER() OVER (
                    PARTITION BY MaSV, MaMH
                    ORDER BY NamHoc, HocKy, KetQuaID
                ) AS NewLanHoc
            FROM KetQuaHocTap
        )
        """
    )
    conn.execute(
        """
        UPDATE KetQuaHocTap
        SET LanHoc = (
            SELECT NewLanHoc
            FROM _v3_kqht_order o
            WHERE o.KetQuaID = KetQuaHocTap.KetQuaID
        )
        """
    )
    conn.execute("DROP TABLE _v3_kqht_order")
    conn.execute(
        """
        UPDATE KetQuaHocTap AS cur
        SET LoaiHoc = CASE
            WHEN cur.LanHoc = 1 THEN 'HOC_MOI'
            WHEN EXISTS (
                SELECT 1
                FROM KetQuaHocTap prev
                WHERE prev.MaSV = cur.MaSV
                  AND prev.MaMH = cur.MaMH
                  AND prev.LanHoc < cur.LanHoc
                  AND prev.KetQua = 'DAT'
            ) THEN 'CAI_THIEN'
            ELSE 'HOC_LAI'
        END
        """
    )


def next_term(year: int, term: int) -> tuple[int, int]:
    if term == 1:
        return year, 2
    return year + 1, 1


def previous_term(year: int, term: int) -> tuple[int, int]:
    if term == 2:
        return year, 1
    return year - 1, 2


def normalize_academic_timeline(conn: sqlite3.Connection) -> tuple[int, int, int]:
    open_semester = get_open_registration_semester(conn)
    open_year = int(open_semester["NamHoc"])
    open_term = int(open_semester["HocKy"])
    prev_year, prev_term = previous_term(open_year, open_term)

    moved_synthetic_rows = conn.execute(
        """
        SELECT COUNT(*)
        FROM KetQuaHocTap
        WHERE KetQua IN ('DAT', 'KHONG_DAT')
          AND (NamHoc > ? OR (NamHoc = ? AND HocKy >= ?))
          AND MaLHP IS NULL
          AND LoaiHoc = 'HOC_LAI'
        """,
        (open_year, open_year, open_term),
    ).fetchone()[0]
    conn.execute(
        """
        UPDATE KetQuaHocTap
        SET NamHoc = ?,
            HocKy = ?,
            GhiChu = 'Bổ sung kết quả học lại đạt để cân bằng dữ liệu nợ môn v3; đã đưa về học kỳ quá khứ hợp lệ.'
        WHERE KetQua IN ('DAT', 'KHONG_DAT')
          AND (NamHoc > ? OR (NamHoc = ? AND HocKy >= ?))
          AND MaLHP IS NULL
          AND LoaiHoc = 'HOC_LAI'
        """,
        (prev_year, prev_term, open_year, open_year, open_term),
    )

    deleted_completed_rows = conn.execute(
        """
        SELECT COUNT(*)
        FROM KetQuaHocTap
        WHERE KetQua IN ('DAT', 'KHONG_DAT')
          AND (NamHoc > ? OR (NamHoc = ? AND HocKy >= ?))
        """,
        (open_year, open_year, open_term),
    ).fetchone()[0]
    conn.execute(
        """
        DELETE FROM KetQuaHocTap
        WHERE KetQua IN ('DAT', 'KHONG_DAT')
          AND (NamHoc > ? OR (NamHoc = ? AND HocKy >= ?))
        """,
        (open_year, open_year, open_term),
    )

    deleted_study_rows = conn.execute(
        "SELECT COUNT(*) FROM KetQuaHocTap WHERE KetQua = 'DANG_HOC'",
    ).fetchone()[0]
    conn.execute("DELETE FROM KetQuaHocTap WHERE KetQua = 'DANG_HOC'")
    return int(moved_synthetic_rows), int(deleted_completed_rows), int(deleted_study_rows)


def rebuild_ketqua_summary(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM KetQua")
    conn.execute(
        """
        INSERT INTO KetQua (MaSV, MaMH, NamHoc, HocKy, KetQua)
        SELECT MaSV, MaMH, NamHoc, HocKy, KetQua
        FROM (
            SELECT
                kq.MaSV,
                kq.MaMH,
                kq.NamHoc,
                kq.HocKy,
                kq.KetQua,
                ROW_NUMBER() OVER (
                    PARTITION BY kq.MaSV, kq.MaMH
                    ORDER BY
                        CASE WHEN kq.KetQua = 'DAT' THEN 1 ELSE 0 END DESC,
                        kq.NamHoc DESC,
                        kq.HocKy DESC,
                        kq.KetQuaID DESC
                ) AS rn
            FROM KetQuaHocTap kq
            WHERE kq.KetQua IN ('DAT', 'KHONG_DAT')
        )
        WHERE rn = 1
        """
    )


def rebalance_academic_debt(conn: sqlite3.Connection) -> int:
    open_semester = get_open_registration_semester(conn)
    open_year = int(open_semester["NamHoc"])
    open_term = int(open_semester["HocKy"])
    prev_year, prev_term = previous_term(open_year, open_term)
    total_students = conn.execute("SELECT COUNT(*) FROM HoSoHocTapSinhVien").fetchone()[0]
    low_gpa_students = conn.execute(
        "SELECT COUNT(*) FROM HoSoHocTapSinhVien WHERE GPA < 2.0",
    ).fetchone()[0]
    target_null_students = round(total_students * TARGET_NULL_ACADEMIC_WARNING_RATIO)
    keep_debt_count = max(0, total_students - low_gpa_students - target_null_students)

    conn.execute("DROP TABLE IF EXISTS _v3_debt_course")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_debt_course AS
        SELECT DISTINCT fail.MaSV, fail.MaMH
        FROM KetQuaHocTap fail
        JOIN HoSoHocTapSinhVien hs ON fail.MaSV = hs.MaSV
        WHERE hs.GPA >= 2.0
          AND fail.KetQua = 'KHONG_DAT'
          AND (fail.NamHoc < ? OR (fail.NamHoc = ? AND fail.HocKy < ?))
          AND NOT EXISTS (
              SELECT 1
              FROM KetQuaHocTap pass
              WHERE pass.MaSV = fail.MaSV
                AND pass.MaMH = fail.MaMH
                AND pass.KetQua = 'DAT'
                AND (pass.NamHoc < ? OR (pass.NamHoc = ? AND pass.HocKy < ?))
          )
        """,
        (open_year, open_year, open_term, open_year, open_year, open_term),
    )
    conn.execute("CREATE INDEX idx_v3_debt_course_sv_mh ON _v3_debt_course(MaSV, MaMH)")

    conn.execute("DROP TABLE IF EXISTS _v3_keep_debt_student")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_keep_debt_student (
            MaSV TEXT PRIMARY KEY
        )
        """
    )
    conn.execute(
        """
        INSERT INTO _v3_keep_debt_student (MaSV)
        SELECT MaSV
        FROM (
            SELECT MaSV, COUNT(*) AS SoMonConNo
            FROM _v3_debt_course
            GROUP BY MaSV
            ORDER BY SoMonConNo DESC, MaSV
            LIMIT ?
        )
        """,
        (keep_debt_count,),
    )

    conn.execute("DROP TABLE IF EXISTS _v3_resolved_debt_course")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_resolved_debt_course AS
        SELECT dc.MaSV, dc.MaMH
        FROM _v3_debt_course dc
        LEFT JOIN _v3_keep_debt_student keep ON dc.MaSV = keep.MaSV
        WHERE keep.MaSV IS NULL
        """
    )
    conn.execute("CREATE INDEX idx_v3_resolved_debt_sv_mh ON _v3_resolved_debt_course(MaSV, MaMH)")
    resolved_rows = conn.execute("SELECT COUNT(*) FROM _v3_resolved_debt_course").fetchone()[0]

    conn.execute("DROP TABLE IF EXISTS _v3_resolved_attempt")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_resolved_attempt (
            MaSV TEXT NOT NULL,
            MaMH TEXT NOT NULL,
            LanHoc INTEGER NOT NULL,
            NamHoc INTEGER NOT NULL,
            HocKy INTEGER NOT NULL,
            PRIMARY KEY (MaSV, MaMH)
        )
        """
    )

    rows = conn.execute(
        """
        SELECT
            r.MaSV,
            r.MaMH,
            COALESCE(MAX(kq.LanHoc), 0) + 1 AS NewLanHoc,
            COALESCE((
                SELECT k2.NamHoc
                FROM KetQuaHocTap k2
                WHERE k2.MaSV = r.MaSV
                  AND k2.MaMH = r.MaMH
                  AND (k2.NamHoc < ? OR (k2.NamHoc = ? AND k2.HocKy < ?))
                ORDER BY k2.NamHoc DESC, k2.HocKy DESC, k2.KetQuaID DESC
                LIMIT 1
            ), ?) AS LastNamHoc,
            COALESCE((
                SELECT k2.HocKy
                FROM KetQuaHocTap k2
                WHERE k2.MaSV = r.MaSV
                  AND k2.MaMH = r.MaMH
                  AND (k2.NamHoc < ? OR (k2.NamHoc = ? AND k2.HocKy < ?))
                ORDER BY k2.NamHoc DESC, k2.HocKy DESC, k2.KetQuaID DESC
                LIMIT 1
            ), ?) AS LastHocKy
        FROM _v3_resolved_debt_course r
        LEFT JOIN KetQuaHocTap kq
          ON r.MaSV = kq.MaSV
         AND r.MaMH = kq.MaMH
        GROUP BY r.MaSV, r.MaMH
        ORDER BY r.MaSV, r.MaMH
        """,
        (open_year, open_year, open_term, prev_year, open_year, open_year, open_term, prev_term),
    ).fetchall()
    attempts = []
    for row in rows:
        year, term = next_term(int(row["LastNamHoc"]), int(row["LastHocKy"]))
        if year > open_year or (year == open_year and term >= open_term):
            year, term = prev_year, prev_term
        attempts.append((row["MaSV"], row["MaMH"], int(row["NewLanHoc"]), year, term))
    conn.executemany(
        """
        INSERT INTO _v3_resolved_attempt (MaSV, MaMH, LanHoc, NamHoc, HocKy)
        VALUES (?, ?, ?, ?, ?)
        """,
        attempts,
    )

    created_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO KetQuaHocTap
            (
                MaSV, MaMH, MaLHP, LanHoc, NamHoc, HocKy,
                DiemQuaTrinh, DiemThi, DiemTongKet, DiemChu, DiemHe4,
                KetQua, LoaiHoc, GhiChu, ThoiDiemTao
            )
        SELECT
            MaSV, MaMH, NULL, LanHoc, NamHoc, HocKy,
            6.0, 6.0, 6.0, 'C', 2.0,
            'DAT', 'HOC_LAI', 'Bổ sung kết quả học lại đạt để cân bằng dữ liệu nợ môn v3', ?
        FROM _v3_resolved_attempt
        """,
        (created_at,),
    )
    conn.execute(
        """
        UPDATE KetQua
        SET
            NamHoc = (
                SELECT a.NamHoc
                FROM _v3_resolved_attempt a
                WHERE a.MaSV = KetQua.MaSV
                  AND a.MaMH = KetQua.MaMH
            ),
            HocKy = (
                SELECT a.HocKy
                FROM _v3_resolved_attempt a
                WHERE a.MaSV = KetQua.MaSV
                  AND a.MaMH = KetQua.MaMH
            ),
            KetQua = 'DAT'
        WHERE EXISTS (
            SELECT 1
            FROM _v3_resolved_attempt a
            WHERE a.MaSV = KetQua.MaSV
              AND a.MaMH = KetQua.MaMH
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO KetQua (MaSV, MaMH, NamHoc, HocKy, KetQua)
        SELECT MaSV, MaMH, NamHoc, HocKy, 'DAT'
        FROM _v3_resolved_attempt
        """
    )
    conn.execute("DROP TABLE _v3_resolved_attempt")
    conn.execute("DROP TABLE _v3_resolved_debt_course")
    conn.execute("DROP TABLE _v3_keep_debt_student")
    conn.execute("DROP TABLE _v3_debt_course")
    return resolved_rows


def recalculate_academic_profile_metrics(conn: sqlite3.Connection) -> None:
    open_semester = get_open_registration_semester(conn)
    open_year = int(open_semester["NamHoc"])
    open_term = int(open_semester["HocKy"])
    conn.execute("DROP TABLE IF EXISTS _v3_pass_best")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_pass_best AS
        SELECT kq.MaSV, kq.MaMH, MAX(COALESCE(kq.DiemHe4, 0)) AS BestDiemHe4
        FROM KetQuaHocTap kq
        WHERE kq.KetQua = 'DAT'
          AND (kq.NamHoc < ? OR (kq.NamHoc = ? AND kq.HocKy < ?))
        GROUP BY kq.MaSV, kq.MaMH
        """,
        (open_year, open_year, open_term),
    )
    conn.execute("CREATE INDEX idx_v3_pass_best_sv ON _v3_pass_best(MaSV)")
    conn.execute("DROP TABLE IF EXISTS _v3_pass_agg")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_pass_agg AS
        SELECT
            pb.MaSV,
            COUNT(*) AS SoMonDaDau,
            COALESCE(SUM(mh.SoTC), 0) AS TinChiTichLuy,
            ROUND(SUM(pb.BestDiemHe4 * mh.SoTC) / NULLIF(SUM(mh.SoTC), 0), 2) AS GPA
        FROM _v3_pass_best pb
        JOIN MonHoc mh ON pb.MaMH = mh.MaMH
        GROUP BY pb.MaSV
        """
    )
    conn.execute("CREATE INDEX idx_v3_pass_agg_sv ON _v3_pass_agg(MaSV)")
    conn.execute("DROP TABLE IF EXISTS _v3_fail_agg")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_fail_agg AS
        SELECT MaSV, COUNT(DISTINCT MaMH) AS SoMonTungRot
        FROM KetQuaHocTap
        WHERE KetQua = 'KHONG_DAT'
          AND (NamHoc < ? OR (NamHoc = ? AND HocKy < ?))
        GROUP BY MaSV
        """,
        (open_year, open_year, open_term),
    )
    conn.execute("CREATE INDEX idx_v3_fail_agg_sv ON _v3_fail_agg(MaSV)")
    conn.execute("DROP TABLE IF EXISTS _v3_repeat_agg")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_repeat_agg AS
        SELECT MaSV, COUNT(*) AS SoLanHocLaiCaiThien
        FROM KetQuaHocTap
        WHERE LanHoc > 1
          AND LoaiHoc IN ('HOC_LAI', 'CAI_THIEN')
          AND (NamHoc < ? OR (NamHoc = ? AND HocKy < ?))
        GROUP BY MaSV
        """,
        (open_year, open_year, open_term),
    )
    conn.execute("CREATE INDEX idx_v3_repeat_agg_sv ON _v3_repeat_agg(MaSV)")
    conn.execute(
        """
        UPDATE HoSoHocTapSinhVien
        SET
            GPA = COALESCE((SELECT GPA FROM _v3_pass_agg WHERE _v3_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV), GPA),
            TinChiTichLuy = COALESCE((SELECT TinChiTichLuy FROM _v3_pass_agg WHERE _v3_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            SoMonDaDau = COALESCE((SELECT SoMonDaDau FROM _v3_pass_agg WHERE _v3_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            SoMonTungRot = COALESCE((SELECT SoMonTungRot FROM _v3_fail_agg WHERE _v3_fail_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            SoLanHocLaiCaiThien = COALESCE((SELECT SoLanHocLaiCaiThien FROM _v3_repeat_agg WHERE _v3_repeat_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0)
        """
    )
    conn.execute("DROP TABLE _v3_repeat_agg")
    conn.execute("DROP TABLE _v3_fail_agg")
    conn.execute("DROP TABLE _v3_pass_agg")
    conn.execute("DROP TABLE _v3_pass_best")


def normalize_student_profiles(conn: sqlite3.Connection) -> None:
    open_semester = get_open_registration_semester(conn)
    open_year = int(open_semester["NamHoc"])
    open_term = int(open_semester["HocKy"])
    conn.execute(
        """
        UPDATE HoSoHocTapSinhVien
        SET NhomHoSo = CASE
            WHEN GPA < 2.0 THEN 'DIEM_TB_THAP'
            WHEN GPA >= 3.2 THEN 'DIEM_TB_CAO'
            WHEN TinChiTichLuy >= (
                SELECT CAST(ROUND(ctdt.TongTinChiToiThieu * ?) AS INTEGER)
                FROM SinhVien sv
                JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
                JOIN CTDT ctdt ON ctdt.MaCTDT = kh.MaCTDT
                WHERE sv.MaSV = HoSoHocTapSinhVien.MaSV
            ) THEN 'GAN_TOT_NGHIEP'
            WHEN SoMonTungRot >= 8 OR SoLanHocLaiCaiThien >= 4 THEN 'HOC_LAI_NHIEU'
            WHEN SoLanHocLaiCaiThien > 0 THEN 'CAI_THIEN_DIEM'
            ELSE 'DUNG_TIEN_DO'
        END
        """,
        (NEAR_GRADUATION_CREDIT_RATIO,),
    )
    conn.execute("DROP TABLE IF EXISTS _v3_mon_con_no")
    conn.execute(
        """
        CREATE TEMP TABLE _v3_mon_con_no AS
        SELECT fail.MaSV, COUNT(DISTINCT fail.MaMH) AS SoMonConNo
        FROM KetQuaHocTap fail
        WHERE fail.KetQua = 'KHONG_DAT'
          AND (fail.NamHoc < ? OR (fail.NamHoc = ? AND fail.HocKy < ?))
          AND NOT EXISTS (
              SELECT 1
              FROM KetQuaHocTap pass
              WHERE pass.MaSV = fail.MaSV
                AND pass.MaMH = fail.MaMH
                AND pass.KetQua = 'DAT'
                AND (pass.NamHoc < ? OR (pass.NamHoc = ? AND pass.HocKy < ?))
          )
        GROUP BY fail.MaSV
        """,
        (open_year, open_year, open_term, open_year, open_year, open_term),
    )
    conn.execute("CREATE INDEX idx_v3_mon_con_no_masv ON _v3_mon_con_no(MaSV)")
    conn.execute(
        """
        UPDATE HoSoHocTapSinhVien
        SET CanhBaoHocVu = CASE
            WHEN GPA < 2.0 THEN 'CANH_BAO_DIEM_TB_THAP'
            WHEN EXISTS (
                SELECT 1
                FROM _v3_mon_con_no debt
                WHERE debt.MaSV = HoSoHocTapSinhVien.MaSV
                  AND debt.SoMonConNo >= ?
            ) THEN 'CANH_BAO_NO_MON'
            ELSE NULL
        END
        """,
        (NO_MON_WARNING_DEBT_THRESHOLD,),
    )
    conn.execute(
        """
        UPDATE HoSoHocTapSinhVien
        SET GhiChu = CASE
            WHEN CanhBaoHocVu = 'CANH_BAO_DIEM_TB_THAP'
                THEN 'Sinh viên bị cảnh báo học vụ vì GPA hiện tại dưới 2.0.'
            WHEN CanhBaoHocVu = 'CANH_BAO_NO_MON'
                THEN 'Sinh viên bị cảnh báo học vụ vì còn nợ môn: có học phần không đạt và chưa có lần học lại đạt.'
            WHEN NhomHoSo = 'GAN_TOT_NGHIEP'
                THEN 'Sinh viên đã tích lũy nhiều tín chỉ và gần hoàn thành chương trình.'
            WHEN NhomHoSo = 'DIEM_TB_CAO'
                THEN 'Sinh viên có điểm trung bình cao và đạt hầu hết các môn đã học.'
            WHEN NhomHoSo = 'DIEM_TB_THAP'
                THEN 'Sinh viên có điểm trung bình thấp theo dữ liệu kết quả học tập.'
            WHEN NhomHoSo = 'HOC_LAI_NHIEU'
                THEN 'Sinh viên có nhiều lần học lại hoặc cải thiện điểm trong lịch sử học tập.'
            WHEN NhomHoSo = 'CAI_THIEN_DIEM'
                THEN 'Sinh viên có lịch sử học cải thiện điểm sau khi đã đạt môn.'
            WHEN NhomHoSo = 'ROT_DAI_CUONG'
                THEN 'Sinh viên từng rớt một số môn đại cương hoặc nền tảng.'
            WHEN NhomHoSo = 'ROT_NEN_TANG_CNTT'
                THEN 'Sinh viên từng rớt một số môn nền tảng công nghệ thông tin.'
            ELSE 'Sinh viên đang học đúng tiến độ tương đối so với dữ liệu học tập hiện có.'
        END
        """
    )
    conn.execute("DROP TABLE _v3_mon_con_no")


def normalize_graduation_status(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT sv.MaSV
        FROM SinhVien sv
        JOIN HoSoHocTapSinhVien hs ON hs.MaSV = sv.MaSV
        JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
        JOIN CTDT ctdt ON ctdt.MaCTDT = kh.MaCTDT
        WHERE sv.TrangThai = 'DA_TOT_NGHIEP'
          AND (
              hs.CanhBaoHocVu IS NOT NULL
              OR hs.TinChiTichLuy < ctdt.TongTinChiToiThieu
          )
        """
    ).fetchall()
    conn.execute(
        """
        UPDATE SinhVien
        SET TrangThai = 'DANG_HOC'
        WHERE TrangThai = 'DA_TOT_NGHIEP'
          AND EXISTS (
              SELECT 1
              FROM HoSoHocTapSinhVien hs
              JOIN KhoaHoc kh ON kh.MaKhoaHoc = SinhVien.MaKhoaHoc
              JOIN CTDT ctdt ON ctdt.MaCTDT = kh.MaCTDT
              WHERE hs.MaSV = SinhVien.MaSV
                AND (
                    hs.CanhBaoHocVu IS NOT NULL
                    OR hs.TinChiTichLuy < ctdt.TongTinChiToiThieu
                )
          )
        """
    )
    return len(rows)


def suspend_active_students_without_current_registration(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT sv.MaSV
        FROM SinhVien sv
        WHERE sv.TrangThai = 'DANG_HOC'
          AND NOT EXISTS (
              SELECT 1
              FROM DangKy dk
              JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
              JOIN HocKyHeThong hk
                ON hk.NamHoc = lhp.NamHoc
               AND hk.HocKy = lhp.HocKy
               AND hk.DangMoDangKy = 1
              WHERE dk.MaSV = sv.MaSV
          )
        """
    ).fetchall()
    conn.execute(
        """
        UPDATE SinhVien
        SET TrangThai = 'TAM_NGUNG'
        WHERE TrangThai = 'DANG_HOC'
          AND NOT EXISTS (
              SELECT 1
              FROM DangKy dk
              JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
              JOIN HocKyHeThong hk
                ON hk.NamHoc = lhp.NamHoc
               AND hk.HocKy = lhp.HocKy
               AND hk.DangMoDangKy = 1
              WHERE dk.MaSV = SinhVien.MaSV
          )
        """
    )
    return len(rows)


def sync_current_study_rows(conn: sqlite3.Connection) -> int:
    open_semester = get_open_registration_semester(conn)
    open_year = int(open_semester["NamHoc"])
    open_term = int(open_semester["HocKy"])
    conn.execute("DELETE FROM KetQuaHocTap WHERE KetQua = 'DANG_HOC'")
    created_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO KetQuaHocTap
            (
                MaSV, MaMH, MaLHP, LanHoc, NamHoc, HocKy,
                DiemQuaTrinh, DiemThi, DiemTongKet, DiemChu, DiemHe4,
                KetQua, LoaiHoc, GhiChu, ThoiDiemTao
            )
        SELECT
            dk.MaSV,
            lhp.MaMH,
            dk.MaLHP,
            COALESCE((
                SELECT MAX(prev.LanHoc)
                FROM KetQuaHocTap prev
                WHERE prev.MaSV = dk.MaSV
                  AND prev.MaMH = lhp.MaMH
                  AND prev.KetQua IN ('DAT', 'KHONG_DAT')
                  AND (prev.NamHoc < lhp.NamHoc OR (prev.NamHoc = lhp.NamHoc AND prev.HocKy < lhp.HocKy))
            ), 0) + 1,
            lhp.NamHoc,
            lhp.HocKy,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            'DANG_HOC',
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM KetQuaHocTap prev
                    WHERE prev.MaSV = dk.MaSV
                      AND prev.MaMH = lhp.MaMH
                      AND prev.KetQua = 'DAT'
                      AND (prev.NamHoc < lhp.NamHoc OR (prev.NamHoc = lhp.NamHoc AND prev.HocKy < lhp.HocKy))
                ) THEN 'CAI_THIEN'
                WHEN EXISTS (
                    SELECT 1
                    FROM KetQuaHocTap prev
                    WHERE prev.MaSV = dk.MaSV
                      AND prev.MaMH = lhp.MaMH
                      AND prev.KetQua = 'KHONG_DAT'
                      AND (prev.NamHoc < lhp.NamHoc OR (prev.NamHoc = lhp.NamHoc AND prev.HocKy < lhp.HocKy))
                ) THEN 'HOC_LAI'
                ELSE 'HOC_MOI'
            END,
            'Đăng ký hiện tại',
            ?
        FROM DangKy dk
        JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
        WHERE lhp.NamHoc = ?
          AND lhp.HocKy = ?
        """,
        (created_at, open_year, open_term),
    )
    return conn.execute(
        """
        SELECT COUNT(*)
        FROM KetQuaHocTap
        WHERE KetQua = 'DANG_HOC'
          AND NamHoc = ?
          AND HocKy = ?
        """,
        (open_year, open_term),
    ).fetchone()[0]


def rebuild_current_registration_view(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_dang_ky_hien_tai_sv;

        CREATE VIEW v_dang_ky_hien_tai_sv AS
        SELECT
            dk.MaSV,
            sv.HoTen,
            hs.NhomHoSo,
            dk.MaLHP,
            lhp.MaMH,
            mh.TenMH,
            mh.SoTC,
            lhp.NamHoc,
            lhp.HocKy,
            lhp.Nhom,
            lhp.TrangThai AS TrangThaiLHP,
            dk.TGDK,
            CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM KetQuaHocTap kq
                    WHERE kq.MaSV = dk.MaSV
                      AND kq.MaMH = lhp.MaMH
                      AND kq.KetQua = 'DAT'
                      AND (
                          kq.NamHoc < lhp.NamHoc
                          OR (kq.NamHoc = lhp.NamHoc AND kq.HocKy < lhp.HocKy)
                      )
                ) THEN 'CAI_THIEN'
                WHEN EXISTS (
                    SELECT 1
                    FROM KetQuaHocTap kq
                    WHERE kq.MaSV = dk.MaSV
                      AND kq.MaMH = lhp.MaMH
                      AND kq.KetQua = 'KHONG_DAT'
                      AND (
                          kq.NamHoc < lhp.NamHoc
                          OR (kq.NamHoc = lhp.NamHoc AND kq.HocKy < lhp.HocKy)
                      )
                ) THEN 'HOC_LAI'
                ELSE 'HOC_MOI'
            END AS LoaiDangKy
        FROM DangKy dk
        JOIN SinhVien sv ON dk.MaSV = sv.MaSV
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
        LEFT JOIN HoSoHocTapSinhVien hs ON dk.MaSV = hs.MaSV
        WHERE EXISTS (
            SELECT 1
            FROM HocKyHeThong hk
            WHERE hk.NamHoc = lhp.NamHoc
              AND hk.HocKy = lhp.HocKy
              AND hk.DangMoDangKy = 1
              AND hk.TrangThai = 'DANG_MO_DANG_KY'
        );
        """
    )


def rebuild_registration_eligibility_view(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_dieu_kien_dang_ky_mon_sv;

        CREATE VIEW v_dieu_kien_dang_ky_mon_sv AS
        WITH base AS (
            SELECT
                sv.MaSV,
                sv.HoTen,
                sv.TrangThai AS TrangThaiSV,
                hs.NhomHoSo,
                COALESCE(hs.GioiHanTinChi, 28) AS GioiHanTinChi,
                lhp.MaLHP,
                lhp.MaMH,
                mh.TenMH,
                mh.SoTC,
                lhp.NamHoc,
                lhp.HocKy,
                lhp.Nhom,
                lhp.TrangThai AS TrangThaiLHP,
                lhp.SiSoTD,
                lhp.SiSoDK,
                lhp.SiSoTD - lhp.SiSoDK AS SoChoCon,
                (
                    SELECT COUNT(*)
                    FROM QuanHeHocPhan qh
                    WHERE qh.MaMH = lhp.MaMH
                      AND qh.LoaiQuanHe = 'TIEN_QUYET'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM KetQuaHocTap kq
                          WHERE kq.MaSV = sv.MaSV
                            AND kq.MaMH = qh.MaMHDieuKien
                            AND kq.KetQua = 'DAT'
                            AND (
                                kq.NamHoc < lhp.NamHoc
                                OR (kq.NamHoc = lhp.NamHoc AND kq.HocKy < lhp.HocKy)
                            )
                      )
                ) AS SoMonTienQuyetThieu,
                (
                    SELECT COUNT(*)
                    FROM DangKy dk
                    WHERE dk.MaSV = sv.MaSV
                      AND dk.MaLHP = lhp.MaLHP
                ) AS DaDangKyLopNay,
                (
                    SELECT COUNT(*)
                    FROM DangKy dk
                    JOIN LopHP cur ON dk.MaLHP = cur.MaLHP
                    WHERE dk.MaSV = sv.MaSV
                      AND cur.NamHoc = lhp.NamHoc
                      AND cur.HocKy = lhp.HocKy
                      AND cur.MaMH = lhp.MaMH
                      AND cur.MaLHP <> lhp.MaLHP
                ) AS SoLopCungMonDaDangKy,
                (
                    SELECT COUNT(DISTINCT cur.MaLHP)
                    FROM DangKy dk
                    JOIN LopHP cur ON dk.MaLHP = cur.MaLHP
                    JOIN LichHoc cur_l ON cur.MaLHP = cur_l.MaLHP
                    JOIN LichHoc tgt_l ON tgt_l.MaLHP = lhp.MaLHP
                    WHERE dk.MaSV = sv.MaSV
                      AND cur.NamHoc = lhp.NamHoc
                      AND cur.HocKy = lhp.HocKy
                      AND cur.MaLHP <> lhp.MaLHP
                      AND cur_l.Thu = tgt_l.Thu
                      AND cur_l.TietBD <= tgt_l.TietKT
                      AND cur_l.TietKT >= tgt_l.TietBD
                ) AS SoLopTrungLich,
                (
                    SELECT COALESCE(SUM(reg_mh.SoTC), 0)
                    FROM DangKy dk
                    JOIN LopHP cur ON dk.MaLHP = cur.MaLHP
                    JOIN MonHoc reg_mh ON cur.MaMH = reg_mh.MaMH
                    WHERE dk.MaSV = sv.MaSV
                      AND cur.NamHoc = lhp.NamHoc
                      AND cur.HocKy = lhp.HocKy
                ) AS TinChiHienTai
            FROM SinhVien sv
            CROSS JOIN LopHP lhp
            JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
            LEFT JOIN HoSoHocTapSinhVien hs ON sv.MaSV = hs.MaSV
            WHERE EXISTS (
                SELECT 1
                FROM HocKyHeThong hk
                WHERE hk.NamHoc = lhp.NamHoc
                  AND hk.HocKy = lhp.HocKy
                  AND hk.DangMoDangKy = 1
                  AND hk.TrangThai = 'DANG_MO_DANG_KY'
            )
        )
        SELECT
            *,
            TinChiHienTai + SoTC AS TinChiSauDangKy,
            TRIM(
                CASE WHEN TrangThaiSV <> 'DANG_HOC' THEN 'SINH_VIEN_KHONG_DANG_HOC|' ELSE '' END ||
                CASE WHEN DaDangKyLopNay > 0 THEN 'DA_DANG_KY_LOP_NAY|' ELSE '' END ||
                CASE WHEN TrangThaiLHP <> 'MO' THEN 'LOP_KHONG_MO|' ELSE '' END ||
                CASE WHEN SoChoCon <= 0 THEN 'LOP_HET_CHO|' ELSE '' END ||
                CASE WHEN SoMonTienQuyetThieu > 0 THEN 'THIEU_TIEN_QUYET|' ELSE '' END ||
                CASE WHEN SoLopTrungLich > 0 THEN 'TRUNG_LICH|' ELSE '' END ||
                CASE WHEN SoLopCungMonDaDangKy > 0 THEN 'DA_DANG_KY_MON_NAY|' ELSE '' END ||
                CASE WHEN TinChiHienTai + SoTC > GioiHanTinChi THEN 'VUOT_TIN_CHI|' ELSE '' END,
                '|'
            ) AS LyDoKhongDangKy,
            CASE
                WHEN TrangThaiSV = 'DANG_HOC'
                 AND DaDangKyLopNay = 0
                 AND TrangThaiLHP = 'MO'
                 AND SoChoCon > 0
                 AND SoMonTienQuyetThieu = 0
                 AND SoLopTrungLich = 0
                 AND SoLopCungMonDaDangKy = 0
                 AND TinChiHienTai + SoTC <= GioiHanTinChi
                THEN 1
                ELSE 0
            END AS CoTheDangKy
        FROM base;
        """
    )


def upsert_metadata(
    conn: sqlite3.Connection,
    removed_prereq_count: int,
    removed_non_current_count: int,
    moved_future_synthetic_count: int,
    deleted_future_completed_count: int,
    deleted_stale_study_count: int,
    resolved_debt_count: int,
    filled_hk_goi_y_count: int,
    normalized_ctdt_credit_count: int,
    filled_group_hk_count: int,
    normalized_graduation_count: int,
    added_current_registration_count: int,
    suspended_without_registration_count: int,
    synced_current_study_count: int,
) -> None:
    target_null_students = round(
        conn.execute("SELECT COUNT(*) FROM HoSoHocTapSinhVien").fetchone()[0]
        * TARGET_NULL_ACADEMIC_WARNING_RATIO
    )
    rows = [
        ("PHIEN_BAN_CSDL", "ctdt_sis_v3"),
        ("THOI_DIEM_TAO_V3", datetime.now().isoformat(timespec="seconds")),
        ("SCRIPT_TAO_V3", "scripts/ctdt_sis_v3.py"),
        ("V3_SO_DANG_KY_XOA_DO_TIEN_QUYET", str(removed_prereq_count)),
        ("V3_SO_DANG_KY_XOA_NGOAI_HOC_KY_HIEN_TAI", str(removed_non_current_count)),
        ("V3_SO_KQHT_TUONG_LAI_SYNTHETIC_DUA_VE_QUA_KHU", str(moved_future_synthetic_count)),
        ("V3_SO_KQHT_HIEN_TAI_TUONG_LAI_XOA", str(deleted_future_completed_count)),
        ("V3_SO_KQHT_DANG_HOC_CU_XOA", str(deleted_stale_study_count)),
        ("V3_SO_KET_QUA_HOC_LAI_DAT_BO_SUNG", str(resolved_debt_count)),
        ("V3_SO_MON_BAT_BUOC_BO_SUNG_HK_GOI_Y", str(filled_hk_goi_y_count)),
        ("V3_SO_CTDT_CHUAN_HOA_TONG_TIN_CHI", str(normalized_ctdt_credit_count)),
        ("V3_SO_NHOM_TU_CHON_BO_SUNG_HK_GOI_Y", str(filled_group_hk_count)),
        ("V3_SO_SINH_VIEN_TOT_NGHIEP_CHUYEN_VE_DANG_HOC", str(normalized_graduation_count)),
        ("V3_SO_DANG_KY_HIEN_TAI_BO_SUNG", str(added_current_registration_count)),
        ("V3_SO_SINH_VIEN_DANG_HOC_CHUYEN_TAM_NGUNG_DO_KHONG_CO_DANG_KY", str(suspended_without_registration_count)),
        ("V3_SO_KQHT_DANG_HOC_DONG_BO_TU_DANG_KY", str(synced_current_study_count)),
        ("V3_TI_LE_MUC_TIEU_SINH_VIEN_KHONG_CANH_BAO", str(TARGET_NULL_ACADEMIC_WARNING_RATIO)),
        ("V3_MUC_TIEU_SINH_VIEN_KHONG_CANH_BAO", str(target_null_students)),
        (
            "V3_NOI_DUNG_CHUAN_HOA",
            "Xoa dang ky sai tien quyet; tinh lai si so/tin chi; chuan hoa KetQuaHocTap; "
            "xoa ket qua hien tai/tuong lai; dong bo DANG_HOC tu DangKy; "
            "bo sung ket qua hoc lai dat de can bang no mon theo ty le; "
            "chuan hoa NhomHoSo/GhiChu/trang thai tot nghiep; "
            "can bang tin chi DangKy hien tai; rebuild view hien tai va dieu kien dang ky.",
        ),
        (
            "V3_LOGIC_CANH_BAO_NO_MON",
            f"CANH_BAO_NO_MON neu sinh vien co tu {NO_MON_WARNING_DEBT_THRESHOLD} mon tro len tung KHONG_DAT "
            "va chua co bat ky lan DAT nao cho cung MaMH trong KetQuaHocTap.",
        ),
        ("V3_NGUONG_CANH_BAO_NO_MON", str(NO_MON_WARNING_DEBT_THRESHOLD)),
    ]
    conn.executemany(
        """
        INSERT INTO ThongTinTaoDuLieu (MaThongTin, GiaTri)
        VALUES (?, ?)
        ON CONFLICT(MaThongTin) DO UPDATE SET GiaTri = excluded.GiaTri
        """,
        rows,
    )


def validate(conn: sqlite3.Connection) -> None:
    checks = {
        "foreign_key_check": "PRAGMA foreign_key_check",
        "dang_ky_sai_tien_quyet": strict_prerequisite_filter_sql(),
        "siso_mismatch": """
            SELECT l.MaLHP
            FROM LopHP l
            LEFT JOIN (SELECT MaLHP, COUNT(*) AS cnt FROM DangKy GROUP BY MaLHP) d ON l.MaLHP = d.MaLHP
            WHERE l.SiSoDK <> COALESCE(d.cnt, 0)
        """,
        "tin_chi_mismatch": """
            SELECT hs.MaSV
            FROM HoSoHocTapSinhVien hs
            LEFT JOIN (
              SELECT dk.MaSV, SUM(mh.SoTC) AS tc
              FROM DangKy dk
              JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
              JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
              WHERE EXISTS (
                  SELECT 1
                  FROM HocKyHeThong hk
                  WHERE hk.NamHoc = lhp.NamHoc
                    AND hk.HocKy = lhp.HocKy
                    AND hk.DangMoDangKy = 1
                    AND hk.TrangThai = 'DANG_MO_DANG_KY'
              )
              GROUP BY dk.MaSV
            ) x ON hs.MaSV = x.MaSV
            WHERE hs.TinChiDangKyHienTai <> COALESCE(x.tc, 0)
        """,
        "dang_ky_ngoai_hoc_ky_hien_tai": """
            SELECT dk.MaSV, dk.MaLHP
            FROM DangKy dk
            JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
            WHERE NOT EXISTS (
                SELECT 1
                FROM HocKyHeThong hk
                WHERE hk.NamHoc = lhp.NamHoc
                  AND hk.HocKy = lhp.HocKy
                  AND hk.DangMoDangKy = 1
                  AND hk.TrangThai = 'DANG_MO_DANG_KY'
            )
        """,
        "sinh_vien_dang_hoc_chua_dang_ky_hien_tai": """
            SELECT sv.MaSV
            FROM SinhVien sv
            WHERE sv.TrangThai = 'DANG_HOC'
              AND (
                  SELECT COUNT(*)
                  FROM DangKy dk
                  JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
                  WHERE dk.MaSV = sv.MaSV
                    AND EXISTS (
                        SELECT 1
                        FROM HocKyHeThong hk
                        WHERE hk.NamHoc = lhp.NamHoc
                          AND hk.HocKy = lhp.HocKy
                          AND hk.DangMoDangKy = 1
                          AND hk.TrangThai = 'DANG_MO_DANG_KY'
                    )
              ) < 1
        """,
        "sinh_vien_dang_hoc_tin_chi_thap_qua_nhieu": f"""
            SELECT sv.MaSV
            FROM SinhVien sv
            JOIN HoSoHocTapSinhVien hs ON hs.MaSV = sv.MaSV
            WHERE sv.TrangThai = 'DANG_HOC'
              AND hs.TinChiDangKyHienTai < {MIN_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS}
            LIMIT (
                SELECT CASE
                    WHEN (
                        SELECT COUNT(*)
                        FROM SinhVien sv2
                        JOIN HoSoHocTapSinhVien hs2 ON hs2.MaSV = sv2.MaSV
                        WHERE sv2.TrangThai = 'DANG_HOC'
                          AND hs2.TinChiDangKyHienTai < {MIN_CURRENT_CREDITS_FOR_ACTIVE_STUDENTS}
                    ) <= (
                        SELECT CAST(COUNT(*) * 0.3 AS INTEGER)
                        FROM SinhVien
                        WHERE TrangThai = 'DANG_HOC'
                    )
                    THEN 0
                    ELSE 1
                END
            )
        """,
        "ctdt_required_missing_hk_goi_y": """
            SELECT MaCTDT, MaMH
            FROM CTDT_MonHoc
            WHERE LoaiYC = 'BAT_BUOC'
              AND HKGoiY IS NULL
        """,
        "ctdt_elective_group_missing_hk_goi_y": """
            SELECT MaCTDT, MaNhomTC
            FROM CTDT_NhomTuChon
            WHERE HocKyGoiY IS NULL
        """,
        "ket_qua_hoan_tat_o_hoc_ky_hien_tai_tuong_lai": """
            SELECT kq.KetQuaID
            FROM KetQuaHocTap kq
            WHERE kq.KetQua IN ('DAT', 'KHONG_DAT')
              AND EXISTS (
                  SELECT 1
                  FROM HocKyHeThong hk
                  WHERE hk.DangMoDangKy = 1
                    AND (
                        kq.NamHoc > hk.NamHoc
                        OR (kq.NamHoc = hk.NamHoc AND kq.HocKy >= hk.HocKy)
                    )
              )
        """,
        "ket_qua_dang_hoc_ngoai_hoc_ky_hien_tai": """
            SELECT kq.KetQuaID
            FROM KetQuaHocTap kq
            WHERE kq.KetQua = 'DANG_HOC'
              AND NOT EXISTS (
                  SELECT 1
                  FROM HocKyHeThong hk
                  WHERE hk.DangMoDangKy = 1
                    AND hk.NamHoc = kq.NamHoc
                    AND hk.HocKy = kq.HocKy
              )
        """,
        "dang_ky_thieu_ket_qua_dang_hoc": """
            SELECT dk.MaSV, dk.MaLHP
            FROM DangKy dk
            JOIN LopHP lhp ON lhp.MaLHP = dk.MaLHP
            WHERE NOT EXISTS (
                SELECT 1
                FROM KetQuaHocTap kq
                WHERE kq.MaSV = dk.MaSV
                  AND kq.MaLHP = dk.MaLHP
                  AND kq.MaMH = lhp.MaMH
                  AND kq.KetQua = 'DANG_HOC'
            )
        """,
        "ket_qua_dang_hoc_khong_co_dang_ky": """
            SELECT kq.KetQuaID
            FROM KetQuaHocTap kq
            WHERE kq.KetQua = 'DANG_HOC'
              AND NOT EXISTS (
                  SELECT 1
                  FROM DangKy dk
                  WHERE dk.MaSV = kq.MaSV
                    AND dk.MaLHP = kq.MaLHP
              )
        """,
        "ketqua_summary_mismatch": """
            WITH best AS (
              SELECT MaSV, MaMH, NamHoc, HocKy, KetQua
              FROM (
                SELECT
                    MaSV,
                    MaMH,
                    NamHoc,
                    HocKy,
                    KetQua,
                    ROW_NUMBER() OVER (
                        PARTITION BY MaSV, MaMH
                        ORDER BY
                            CASE WHEN KetQua = 'DAT' THEN 1 ELSE 0 END DESC,
                            NamHoc DESC,
                            HocKy DESC,
                            KetQuaID DESC
                    ) AS rn
                FROM KetQuaHocTap
                WHERE KetQua IN ('DAT', 'KHONG_DAT')
              )
              WHERE rn = 1
            )
            SELECT k.MaSV, k.MaMH
            FROM KetQua k
            JOIN best b ON b.MaSV = k.MaSV AND b.MaMH = k.MaMH
            WHERE k.NamHoc <> b.NamHoc
               OR k.HocKy <> b.HocKy
               OR k.KetQua <> b.KetQua
            UNION ALL
            SELECT b.MaSV, b.MaMH
            FROM best b
            LEFT JOIN KetQua k ON k.MaSV = b.MaSV AND k.MaMH = b.MaMH
            WHERE k.MaSV IS NULL
            UNION ALL
            SELECT k.MaSV, k.MaMH
            FROM KetQua k
            LEFT JOIN best b ON b.MaSV = k.MaSV AND b.MaMH = k.MaMH
            WHERE b.MaSV IS NULL
        """,
        "ghi_chu_canh_bao_no_mon_mismatch": """
            SELECT MaSV
            FROM HoSoHocTapSinhVien
            WHERE CanhBaoHocVu = 'CANH_BAO_NO_MON'
              AND GhiChu NOT LIKE '%nợ môn%'
        """,
        "ghi_chu_canh_bao_diem_mismatch": """
            SELECT MaSV
            FROM HoSoHocTapSinhVien
            WHERE CanhBaoHocVu = 'CANH_BAO_DIEM_TB_THAP'
              AND GhiChu NOT LIKE '%GPA%'
        """,
        "dynamic_profile_labels": f"""
            SELECT MaSV
            FROM HoSoHocTapSinhVien
            WHERE NhomHoSo IN ({','.join(repr(x) for x in DYNAMIC_PROFILE_LABELS)})
        """,
        "nhom_ho_so_mismatch": """
            SELECT hs.MaSV
            FROM HoSoHocTapSinhVien hs
            JOIN SinhVien sv ON sv.MaSV = hs.MaSV
            JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
            JOIN CTDT ctdt ON ctdt.MaCTDT = kh.MaCTDT
            WHERE hs.NhomHoSo <> CASE
                WHEN hs.GPA < 2.0 THEN 'DIEM_TB_THAP'
                WHEN hs.GPA >= 3.2 THEN 'DIEM_TB_CAO'
                WHEN hs.TinChiTichLuy >= CAST(ROUND(ctdt.TongTinChiToiThieu * 0.85) AS INTEGER) THEN 'GAN_TOT_NGHIEP'
                WHEN hs.SoMonTungRot >= 8 OR hs.SoLanHocLaiCaiThien >= 4 THEN 'HOC_LAI_NHIEU'
                WHEN hs.SoLanHocLaiCaiThien > 0 THEN 'CAI_THIEN_DIEM'
                ELSE 'DUNG_TIEN_DO'
            END
        """,
        "sinh_vien_tot_nghiep_khong_hop_le": """
            SELECT sv.MaSV
            FROM SinhVien sv
            JOIN HoSoHocTapSinhVien hs ON hs.MaSV = sv.MaSV
            JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
            JOIN CTDT ctdt ON ctdt.MaCTDT = kh.MaCTDT
            WHERE sv.TrangThai = 'DA_TOT_NGHIEP'
              AND (
                  hs.CanhBaoHocVu IS NOT NULL
                  OR hs.TinChiTichLuy < ctdt.TongTinChiToiThieu
              )
        """,
        "lan_hoc_order_error": """
            SELECT *
            FROM (
              SELECT MaSV, MaMH, KetQuaID, LanHoc, NamHoc, HocKy,
                     LAG(NamHoc) OVER (PARTITION BY MaSV, MaMH ORDER BY LanHoc, KetQuaID) AS prev_year,
                     LAG(HocKy) OVER (PARTITION BY MaSV, MaMH ORDER BY LanHoc, KetQuaID) AS prev_term
              FROM KetQuaHocTap
            ) x
            WHERE prev_year IS NOT NULL
              AND (NamHoc < prev_year OR (NamHoc = prev_year AND HocKy < prev_term))
        """,
        "lan_hoc_hoc_moi_error": "SELECT KetQuaID FROM KetQuaHocTap WHERE LanHoc > 1 AND LoaiHoc = 'HOC_MOI'",
        "canh_bao_hoc_vu_mismatch": f"""
            WITH debt AS (
              SELECT fail.MaSV, COUNT(DISTINCT fail.MaMH) AS SoMonConNo
              FROM KetQuaHocTap fail
              WHERE fail.KetQua = 'KHONG_DAT'
                AND EXISTS (
                  SELECT 1
                  FROM HocKyHeThong hk
                  WHERE hk.DangMoDangKy = 1
                    AND (
                        fail.NamHoc < hk.NamHoc
                        OR (fail.NamHoc = hk.NamHoc AND fail.HocKy < hk.HocKy)
                    )
                )
                AND NOT EXISTS (
                  SELECT 1
                  FROM KetQuaHocTap pass
                  WHERE pass.MaSV = fail.MaSV
                    AND pass.MaMH = fail.MaMH
                    AND pass.KetQua = 'DAT'
                    AND EXISTS (
                      SELECT 1
                      FROM HocKyHeThong hk
                      WHERE hk.DangMoDangKy = 1
                        AND (
                            pass.NamHoc < hk.NamHoc
                            OR (pass.NamHoc = hk.NamHoc AND pass.HocKy < hk.HocKy)
                        )
                    )
                )
              GROUP BY fail.MaSV
            )
            SELECT hs.MaSV
            FROM HoSoHocTapSinhVien hs
            LEFT JOIN debt ON hs.MaSV = debt.MaSV
            WHERE COALESCE(hs.CanhBaoHocVu, '') <> COALESCE(
              CASE
                WHEN hs.GPA < 2.0 THEN 'CANH_BAO_DIEM_TB_THAP'
                WHEN COALESCE(debt.SoMonConNo, 0) >= {NO_MON_WARNING_DEBT_THRESHOLD} THEN 'CANH_BAO_NO_MON'
                ELSE NULL
              END,
              ''
            )
        """,
        "target_null_academic_warning_ratio": f"""
            SELECT MaSV
            FROM HoSoHocTapSinhVien
            WHERE CanhBaoHocVu IS NOT NULL
            LIMIT (
                SELECT CASE
                    WHEN (
                        SELECT COUNT(*)
                        FROM HoSoHocTapSinhVien
                        WHERE CanhBaoHocVu IS NULL
                    ) BETWEEN
                        CAST((SELECT COUNT(*) FROM HoSoHocTapSinhVien) * ({TARGET_NULL_ACADEMIC_WARNING_RATIO} - 0.03) AS INTEGER)
                        AND
                        CAST((SELECT COUNT(*) FROM HoSoHocTapSinhVien) * ({TARGET_NULL_ACADEMIC_WARNING_RATIO} + 0.03) AS INTEGER)
                    THEN 0
                    ELSE 1
                END
            )
        """,
    }
    for name, sql in checks.items():
        rows = conn.execute(sql).fetchall()
        if rows:
            raise RuntimeError(f"Validation failed for {name}: {len(rows)} rows")


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        refresh_system_semesters(conn)
        sync_current_registration_config(conn)
        removed_non_current_count = remove_non_current_registrations(conn)
        removed_prereq_count = remove_strict_prerequisite_violations(conn)
        filled_hk_goi_y_count = normalize_required_course_suggested_terms(conn)
        normalized_ctdt_credit_count, filled_group_hk_count = normalize_curriculum_requirements(conn)
        moved_future_synthetic_count, deleted_future_completed_count, deleted_stale_study_count = normalize_academic_timeline(conn)
        recalculate_registration_derived_fields(conn)
        normalize_learning_attempts(conn)
        rebuild_ketqua_summary(conn)
        recalculate_academic_profile_metrics(conn)
        resolved_debt_count = rebalance_academic_debt(conn)
        normalize_learning_attempts(conn)
        rebuild_ketqua_summary(conn)
        recalculate_academic_profile_metrics(conn)
        normalize_student_profiles(conn)
        normalized_graduation_count = normalize_graduation_status(conn)
        added_current_registration_count = balance_current_registrations(conn)
        suspended_without_registration_count = suspend_active_students_without_current_registration(conn)
        recalculate_registration_derived_fields(conn)
        synced_current_study_count = sync_current_study_rows(conn)
        normalize_learning_attempts(conn)
        rebuild_current_registration_view(conn)
        rebuild_registration_eligibility_view(conn)
        upsert_metadata(
            conn,
            removed_prereq_count,
            removed_non_current_count,
            moved_future_synthetic_count,
            deleted_future_completed_count,
            deleted_stale_study_count,
            resolved_debt_count,
            filled_hk_goi_y_count,
            normalized_ctdt_credit_count,
            filled_group_hk_count,
            normalized_graduation_count,
            added_current_registration_count,
            suspended_without_registration_count,
            synced_current_study_count,
        )
        validate(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    copy_database(source, output, args.force)
    migrate(output)
    print(f"Created {output}")


if __name__ == "__main__":
    main()
