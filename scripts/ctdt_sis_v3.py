from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import unicodedata
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
CTDT_ID = "CTDT_HCMUTE_CNTT"


# Official semester placement from data/9.-INFORMATION-TECHNOLOGY_K23-1-1.pdf,
# pages 2-5. PHED130713E in the PDF is represented by PHED130715E in the
# source workbook/database (same Physical Education 3 course title).
PDF_K23_SEMESTERS = {
    "LLCT130105E": 1,
    "MATH132401E": 1,
    "ACEN340535E": 1,
    "ACEN340635E": 1,
    "INIT130185E": 1,
    "INPR130285E": 1,
    "PHED110513E": 1,
    "LLCT120205E": 2,
    "MATH132501E": 2,
    "MATH143001E": 2,
    "ACEN440735E": 2,
    "ACEN440835E": 2,
    "PRTE230385E": 2,
    "PHYS130902E": 2,
    "PHED110613E": 2,
    "LLCT120405E": 3,
    "DIGR230485E": 3,
    "DASA230179E": 3,
    "OOPR230279E": 3,
    "EEEN231780E": 3,
    "DBSY230184E": 3,
    "PHYS111202E": 3,
    "PHED130715E": 3,
    "DBMS330284E": 4,
    "WIPR230579E": 4,
    "OPSY330280E": 4,
    "CAAL230180E": 4,
    "NEES330380E": 4,
    "PRBE214262E": 4,
    "MATH132901E": 4,
    "LLCT120314E": 4,
    "GELA220405E": 5,
    "WEPR330479E": 5,
    "ARIN330585E": 5,
    "INSE330380E": 5,
    "PROJ215879E": 5,
    "LLCT230214E": 5,
    "IEPR550935E": 5,
    "OOSE330679E": 6,
    "DEPA330879E": 6,
    "MOPR331279E": 6,
    "NPRO430980E": 6,
    "ADNT330580E": 6,
    "ETHA332080E": 6,
    "ISAD330384E": 6,
    "BDES333877E": 6,
    "DAMI330484E": 6,
    "ENTW611038E": 6,
    "ITEN420885E": 7,
    "ITIN441085E": 7,
    "SOTE431079E": 7,
    "MTSE431179E": 7,
    "POSE431479E": 7,
    "CNDE430780E": 7,
    "NSEC430880E": 7,
    "POCN431280E": 7,
    "BDAN333977E": 7,
    "DBSE431284E": 7,
    "POIS431184E": 7,
    "GRPR471979E": 8,
}


# Strict prerequisites printed in the main curriculum grid (pages 4-5).
PDF_K23_GRID_PREREQUISITES = {
    "MOPR331279E": ("DBSY230184E",),
    "NPRO430980E": ("INSE330380E", "DASA230179E"),
    "ADNT330580E": ("NEES330380E",),
    "ETHA332080E": ("NEES330380E", "INSE330380E"),
    "SOTE431079E": ("OOSE330679E", "DBSY230184E"),
    "MTSE431179E": ("WEPR330479E", "OOSE330679E"),
    "CNDE430780E": ("NEES330380E", "ADNT330580E"),
    "NSEC430880E": ("NEES330380E", "INSE330380E"),
}


# Unambiguous prerequisites from course descriptions (pages 7-22). None is
# an explicit "Prerequisites: None" and therefore removes synthetic rules.
PDF_K23_DESCRIPTION_PREREQUISITES = {
    "INIT130185E": None,
    "INPR130285E": None,
    "PRTE230385E": None,
    "DIGR230485E": None,
    "ARIN330585E": None,
    "DASA230179E": ("INPR130285E", "PRTE230385E"),
    "OOPR230279E": ("INPR130285E",),
    "INSE330380E": None,
    "WEPR330479E": ("INPR130285E",),
    "WIPR230579E": ("INPR130285E", "OOPR230279E", "DBMS330284E"),
    "OOSD330879E": ("OOPR230279E",),
    "SOTE431079E": ("SOEN330679E",),
    "MTSE431179E": ("WEPR330479E",),
    "MOPR331279E": ("WEPR330479E",),
    "SOPM431679E": None,
    "ADMP431879E": ("MOPR331279E",),
    "DBMS330284E": ("DBSY230184E",),
    "DAWH430784E": ("DBSY230184E",),
    "INRE431084E": None,
    "DAMI330484E": None,
    "ISAD330384E": None,
    "DBSE431284E": ("DBSY230184E", "INSE330380E"),
    "CAAL230180E": None,
    "OPSY330280E": ("CAAL230180E",),
    "NEES330380E": None,
    "DCTE330480E": ("NEES330380E",),
    "ADNT330580E": ("NEES330380E",),
    "UNOS330680E": ("NEES330380E",),
    "CNDE430780E": ("NEES330380E", "ADNT330580E"),
    "NSEC430880E": ("NEES330380E", "INSE330380E"),
    "NPRO430980E": ("NEES330380E", "INPR130285E"),
    "ESYS431080E": ("CAAL230180E",),
    "NSMS432280E": ("NEES330380E", "ADNT330580E"),
    "WISE432380E": ("NEES330380E",),
}


CANONICAL_COURSE_ALIASES = {
    "INPR130285E": ("nhap mon lap trinh", ["nmlt", "nm l.trinh", "nm lap trinh", "nhập môn lập trình", "lap trinh co ban"]),
    "PRTE230385E": ("ky thuat lap trinh", ["ktlt", "kỹ thuật lập trình"]),
    "DASA230179E": ("cau truc du lieu va giai thuat", ["ctdlgt", "ctdl gt", "dsa", "cấu trúc dữ liệu và giải thuật"]),
    "OOPR230279E": ("lap trinh huong doi tuong", ["lthdt", "oop", "lập trình hướng đối tượng"]),
    "DBSY230184E": ("co so du lieu", ["csdl", "c sở d liệu", "c so d lieu", "cơ sở dữ liệu", "database"]),
    "DBMS330284E": ("quan tri co so du lieu", ["qtcsdl", "quan tri csdl", "quản trị cơ sở dữ liệu"]),
    "MATH143001E": ("dai so tuyen tinh", ["đsố", "dso", "dai so", "đại số", "đại số tuyến tính"]),
    "DIGR230485E": ("toan roi rac", ["trr", "toán rời rạc"]),
    "WEPR330479E": ("lap trinh web", ["lt web", "web programming", "lập trình web"]),
    "ARIN330585E": ("tri tue nhan tao", ["ttnt", "artificial intelligence", "trí tuệ nhân tạo"]),
    "NEES330380E": ("mang may tinh", ["mmt", "networking essentials", "mạng máy tính"]),
}


PDF_K23_NEW_ELECTIVES = {
    "OOSD330879E": "Object-Oriented Software Design",
    "DLEA432085E": "Deep Learning",
}


PDF_K23_EQUIVALENT_CODES = {
    "PHED130713E": "PHED130715E",
    "WESE431479E": "WESE331479E",
}


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


def has_column(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    return any(row["name"] == column_name for row in conn.execute(f"PRAGMA table_info({table_name})"))


def add_column_if_missing(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if not has_column(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFD", value.replace("đ", "d").replace("Đ", "D"))
    without_accents = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    cleaned = re.sub(r"[^a-z0-9_\-\s]", " ", without_accents.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def ensure_pdf_catalog_courses(conn: sqlite3.Connection) -> int:
    inserted = 0
    for ma_mh, title in PDF_K23_NEW_ELECTIVES.items():
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO MonHoc
                (MaMH, TenMH, SoTC, SoTietLT, SoTietTH, MaKhoaBM,
                 HocPhanTienQuyetText, HocPhanHocTruocText,
                 HocPhanTuongDuongText, LaMonDieuKien)
            VALUES (?, ?, 3, 2, 1, 'CONG_NGHE_THONG_TIN', NULL, NULL, NULL, 0)
            """,
            (ma_mh, title),
        )
        inserted += cur.rowcount
        conn.execute(
            """
            INSERT OR IGNORE INTO CTDT_MonHoc
                (MaCTDT, MaMH, LoaiYC, HKGoiY, MaNhomTC, TenNhomTC, STTTrongCTDT, ExcelRow)
            SELECT ?, ?, 'TU_CHON', NULL, 'NHOM04', TenNhom, NULL, NULL
            FROM CTDT_NhomTuChon
            WHERE MaCTDT = ? AND MaNhomTC = 'NHOM04'
            """,
            (CTDT_ID, ma_mh, CTDT_ID),
        )
    return inserted


def rebuild_curriculum_relationships(conn: sqlite3.Connection) -> dict[str, int]:
    existing: dict[tuple[str, str, str], tuple[str, str, int | None]] = {}
    if conn.execute("SELECT type FROM sqlite_master WHERE name = 'QuanHeHocPhan'").fetchone():
        for row in conn.execute(
            "SELECT MaMH, MaMHDieuKien, LoaiQuanHe, GhiChu FROM QuanHeHocPhan"
        ):
            existing[(row["MaMH"], row["MaMHDieuKien"], row["LoaiQuanHe"])] = (
                row["GhiChu"] or "Quan hệ học phần synthetic kế thừa từ CTĐT V1.",
                "SYNTHETIC_V1",
                None,
            )
    if conn.execute("SELECT type FROM sqlite_master WHERE name = 'TienQuyet'").fetchone():
        for row in conn.execute("SELECT MaMH, MaMHTQ FROM TienQuyet"):
            existing.setdefault(
                (row["MaMH"], row["MaMHTQ"], "TIEN_QUYET"),
                ("Tiên quyết synthetic kế thừa từ bảng TienQuyet.", "SYNTHETIC_V1", None),
            )

    conn.execute("DROP VIEW IF EXISTS v_dieu_kien_dang_ky_mon_sv")
    conn.execute("DROP VIEW IF EXISTS v_tien_quyet_day_du")
    conn.execute("DROP TABLE IF EXISTS TienQuyet")
    conn.execute("DROP TABLE IF EXISTS QuanHeHocPhan")
    conn.execute("DROP TABLE IF EXISTS CTDT_QuanHeHocPhan")
    conn.execute(
        """
        CREATE TABLE CTDT_QuanHeHocPhan (
            MaCTDT TEXT NOT NULL,
            MaMH TEXT NOT NULL,
            MaMHDieuKien TEXT NOT NULL,
            LoaiQuanHe TEXT NOT NULL
                CHECK (LoaiQuanHe IN ('TIEN_QUYET', 'HOC_TRUOC', 'TUONG_DUONG')),
            Nguon TEXT NOT NULL,
            TrangPDF INTEGER,
            GhiChu TEXT,
            PRIMARY KEY (MaCTDT, MaMH, MaMHDieuKien, LoaiQuanHe),
            FOREIGN KEY (MaCTDT) REFERENCES CTDT(MaCTDT),
            FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH),
            FOREIGN KEY (MaMHDieuKien) REFERENCES MonHoc(MaMH),
            CHECK (MaMH <> MaMHDieuKien)
        )
        """
    )
    conn.execute("CREATE INDEX idx_ctdt_quanhe_mamh ON CTDT_QuanHeHocPhan(MaCTDT, MaMH)")
    conn.execute("CREATE INDEX idx_ctdt_quanhe_dieukien ON CTDT_QuanHeHocPhan(MaCTDT, MaMHDieuKien)")

    valid_courses = {row[0] for row in conn.execute("SELECT MaMH FROM MonHoc")}
    for (ma_mh, condition, relation_type), (note, source, page) in existing.items():
        if ma_mh not in valid_courses or condition not in valid_courses or ma_mh == condition:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO CTDT_QuanHeHocPhan
                (MaCTDT, MaMH, MaMHDieuKien, LoaiQuanHe, Nguon, TrangPDF, GhiChu)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (CTDT_ID, ma_mh, condition, relation_type, source, page, note),
        )

    override_courses = set(PDF_K23_DESCRIPTION_PREREQUISITES) | set(PDF_K23_GRID_PREREQUISITES)
    conn.executemany(
        "DELETE FROM CTDT_QuanHeHocPhan WHERE MaCTDT = ? AND MaMH = ? AND LoaiQuanHe = 'TIEN_QUYET'",
        [(CTDT_ID, ma_mh) for ma_mh in sorted(override_courses)],
    )

    strict_count = 0
    soft_count = 0
    for ma_mh in sorted(override_courses):
        strict_prereqs = PDF_K23_GRID_PREREQUISITES.get(ma_mh)
        if strict_prereqs is None:
            strict_prereqs = PDF_K23_DESCRIPTION_PREREQUISITES.get(ma_mh)
            source = "PDF_K23_COURSE_DESCRIPTION"
            page = None
        else:
            source = "PDF_K23_CURRICULUM_GRID"
            page = 4 if ma_mh in {"MOPR331279E", "NPRO430980E", "ADNT330580E", "ETHA332080E", "SOTE431079E", "MTSE431179E"} else 5
        for condition in strict_prereqs or ():
            if ma_mh not in valid_courses or condition not in valid_courses:
                raise RuntimeError(f"Unknown PDF prerequisite mapping: {ma_mh} <- {condition}")
            relation_type = "TIEN_QUYET"
            target_semester = PDF_K23_SEMESTERS.get(ma_mh)
            condition_semester = PDF_K23_SEMESTERS.get(condition)
            if (
                source == "PDF_K23_COURSE_DESCRIPTION"
                and target_semester is not None
                and condition_semester is not None
                and condition_semester >= target_semester
            ):
                relation_type = "HOC_TRUOC"
            conn.execute(
                """
                INSERT INTO CTDT_QuanHeHocPhan
                    (MaCTDT, MaMH, MaMHDieuKien, LoaiQuanHe, Nguon, TrangPDF, GhiChu)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    CTDT_ID,
                    ma_mh,
                    condition,
                    relation_type,
                    source,
                    page,
                    "Điều kiện cùng học kỳ được lưu như học trước mềm."
                    if relation_type == "HOC_TRUOC"
                    else "Đối chiếu CTĐT CNTT K23.",
                ),
            )
            if relation_type == "TIEN_QUYET":
                strict_count += 1
            else:
                soft_count += 1

        description_prereqs = PDF_K23_DESCRIPTION_PREREQUISITES.get(ma_mh)
        if ma_mh in PDF_K23_GRID_PREREQUISITES and description_prereqs:
            for condition in description_prereqs:
                if condition in PDF_K23_GRID_PREREQUISITES[ma_mh]:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO CTDT_QuanHeHocPhan
                        (MaCTDT, MaMH, MaMHDieuKien, LoaiQuanHe, Nguon, TrangPDF, GhiChu)
                    VALUES (?, ?, ?, 'HOC_TRUOC', 'PDF_K23_COURSE_DESCRIPTION', NULL, ?)
                    """,
                    (CTDT_ID, ma_mh, condition, "Mô tả môn học khác bảng curriculum; lưu như học trước mềm."),
                )
                soft_count += 1

    conn.executescript(
        """
        CREATE VIEW QuanHeHocPhan AS
        SELECT DISTINCT MaMH, MaMHDieuKien, LoaiQuanHe, GhiChu
        FROM CTDT_QuanHeHocPhan;

        CREATE VIEW TienQuyet AS
        SELECT DISTINCT MaMH, MaMHDieuKien AS MaMHTQ
        FROM CTDT_QuanHeHocPhan
        WHERE LoaiQuanHe = 'TIEN_QUYET';

        CREATE VIEW v_tien_quyet_day_du AS
        SELECT
            tq.MaMH,
            mh.TenMH,
            mh.SoTC,
            tq.MaMHTQ,
            mh_tq.TenMH AS TenMHTQ,
            mh_tq.SoTC AS SoTCTQ
        FROM TienQuyet tq
        JOIN MonHoc mh ON tq.MaMH = mh.MaMH
        JOIN MonHoc mh_tq ON tq.MaMHTQ = mh_tq.MaMH;
        """
    )

    conn.execute(
        """
        UPDATE MonHoc
        SET HocPhanTienQuyetText = (
                SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                FROM CTDT_QuanHeHocPhan qh
                JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                WHERE qh.MaMH = MonHoc.MaMH AND qh.LoaiQuanHe = 'TIEN_QUYET'
            ),
            HocPhanHocTruocText = (
                SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                FROM CTDT_QuanHeHocPhan qh
                JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                WHERE qh.MaMH = MonHoc.MaMH AND qh.LoaiQuanHe = 'HOC_TRUOC'
            )
        """
    )
    return {"strict_pdf": strict_count, "soft_pdf": soft_count, "total": conn.execute("SELECT COUNT(*) FROM CTDT_QuanHeHocPhan").fetchone()[0]}


def apply_k23_semester_plan(conn: sqlite3.Connection) -> dict[str, int]:
    valid_courses = {row[0] for row in conn.execute("SELECT MaMH FROM MonHoc")}
    missing = sorted(set(PDF_K23_SEMESTERS) - valid_courses)
    if missing:
        raise RuntimeError(f"PDF K23 semester courses missing from MonHoc: {missing}")
    changed = 0
    for ma_mh, semester in PDF_K23_SEMESTERS.items():
        cur = conn.execute(
            "UPDATE CTDT_MonHoc SET HKGoiY = ? WHERE MaCTDT = ? AND MaMH = ? AND HKGoiY IS NOT ?",
            (semester, CTDT_ID, ma_mh, semester),
        )
        changed += cur.rowcount

    group_ranges = {
        "NHOM01": (3, 3),
        "NHOM02": (2, 3),
        "NHOM03": (5, 6),
        "NHOM04": (6, 8),
        "NHOM05": (1, 1),
    }
    inferred = 0
    for row in conn.execute(
        """
        SELECT MaMH, HKGoiY, MaNhomTC
        FROM CTDT_MonHoc
        WHERE MaCTDT = ? AND MaNhomTC IN ('NHOM01', 'NHOM02', 'NHOM03', 'NHOM04', 'NHOM05')
        ORDER BY MaNhomTC, MaMH
        """,
        (CTDT_ID,),
    ).fetchall():
        if row["MaMH"] in PDF_K23_SEMESTERS:
            continue
        lower, upper = group_ranges[row["MaNhomTC"]]
        current = row["HKGoiY"]
        if current is not None and lower <= int(current) <= upper:
            continue
        prereq_row = conn.execute(
            """
            SELECT MAX(cm.HKGoiY)
            FROM CTDT_QuanHeHocPhan qh
            JOIN CTDT_MonHoc cm
              ON cm.MaCTDT = qh.MaCTDT AND cm.MaMH = qh.MaMHDieuKien
            WHERE qh.MaCTDT = ? AND qh.MaMH = ? AND qh.LoaiQuanHe = 'TIEN_QUYET'
            """,
            (CTDT_ID, row["MaMH"]),
        ).fetchone()[0]
        suggested = max(lower, int(prereq_row) + 1 if prereq_row is not None else lower)
        level_match = re.match(r"^[A-Z]+(\d)", row["MaMH"])
        if row["MaNhomTC"] == "NHOM04" and level_match and int(level_match.group(1)) >= 4:
            suggested = max(suggested, 7)
        suggested = min(suggested, upper)
        conn.execute(
            "UPDATE CTDT_MonHoc SET HKGoiY = ? WHERE MaCTDT = ? AND MaMH = ?",
            (suggested, CTDT_ID, row["MaMH"]),
        )
        inferred += 1

    group_semesters = {"NHOM01": 3, "NHOM02": 2, "NHOM03": 5, "NHOM04": 7, "NHOM05": 1}
    conn.executemany(
        "UPDATE CTDT_NhomTuChon SET HocKyGoiY = ? WHERE MaCTDT = ? AND MaNhomTC = ?",
        [(semester, CTDT_ID, group) for group, semester in group_semesters.items()],
    )
    return {"official_changed": changed, "elective_inferred": inferred}


def soften_noncausal_description_prerequisites(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT qh.MaCTDT, qh.MaMH, qh.MaMHDieuKien
        FROM CTDT_QuanHeHocPhan qh
        JOIN CTDT_MonHoc target
          ON target.MaCTDT = qh.MaCTDT AND target.MaMH = qh.MaMH
        JOIN CTDT_MonHoc required
          ON required.MaCTDT = qh.MaCTDT AND required.MaMH = qh.MaMHDieuKien
        WHERE qh.LoaiQuanHe = 'TIEN_QUYET'
          AND qh.Nguon = 'PDF_K23_COURSE_DESCRIPTION'
          AND required.HKGoiY >= target.HKGoiY
        """
    ).fetchall()
    for row in rows:
        conn.execute(
            """
            UPDATE CTDT_QuanHeHocPhan
            SET LoaiQuanHe = 'HOC_TRUOC',
                GhiChu = 'Mô tả PDF nêu điều kiện cùng/sau học kỳ; lưu như học trước mềm.'
            WHERE MaCTDT = ? AND MaMH = ? AND MaMHDieuKien = ? AND LoaiQuanHe = 'TIEN_QUYET'
            """,
            (row["MaCTDT"], row["MaMH"], row["MaMHDieuKien"]),
        )
    if rows:
        conn.execute(
            """
            UPDATE MonHoc
            SET HocPhanTienQuyetText = (
                    SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                    FROM CTDT_QuanHeHocPhan qh
                    JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                    WHERE qh.MaMH = MonHoc.MaMH AND qh.LoaiQuanHe = 'TIEN_QUYET'
                ),
                HocPhanHocTruocText = (
                    SELECT group_concat(qh.MaMHDieuKien || ' - ' || req.TenMH, '; ')
                    FROM CTDT_QuanHeHocPhan qh
                    JOIN MonHoc req ON req.MaMH = qh.MaMHDieuKien
                    WHERE qh.MaMH = MonHoc.MaMH AND qh.LoaiQuanHe = 'HOC_TRUOC'
                )
            """
        )
    return len(rows)


def rebuild_course_aliases_v3(conn: sqlite3.Connection) -> dict[str, int]:
    old_rows = []
    if conn.execute("SELECT type FROM sqlite_master WHERE name = 'MonHocAlias'").fetchone():
        old_rows = conn.execute("SELECT MaMH, Alias, LoaiAlias, Nguon FROM MonHocAlias").fetchall()
        conn.execute("DROP TABLE MonHocAlias")
    conn.execute(
        """
        CREATE TABLE MonHocAlias (
            AliasID INTEGER PRIMARY KEY AUTOINCREMENT,
            MaMH TEXT NOT NULL,
            Alias TEXT NOT NULL,
            AliasKey TEXT NOT NULL UNIQUE,
            CanonicalText TEXT NOT NULL,
            LoaiAlias TEXT NOT NULL
                CHECK (LoaiAlias IN ('MA_MON', 'MA_MON_RUT_GON', 'TEN_MON', 'VIET_TAT', 'BIEN_THE', 'THU_CONG')),
            Nguon TEXT NOT NULL,
            DoUuTien INTEGER NOT NULL DEFAULT 100,
            YeuCauNguCanh INTEGER NOT NULL DEFAULT 0 CHECK (YeuCauNguCanh IN (0, 1)),
            IsActive INTEGER NOT NULL DEFAULT 1 CHECK (IsActive IN (0, 1)),
            FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH)
        )
        """
    )
    conn.execute("CREATE INDEX idx_monhoc_alias_course ON MonHocAlias(MaMH)")

    courses = {row["MaMH"]: row["TenMH"] for row in conn.execute("SELECT MaMH, TenMH FROM MonHoc")}
    candidates: dict[str, tuple[str, str, str, str, int, int]] = {}
    candidate_sources: dict[str, str] = {}
    ambiguous_generated_keys: set[str] = set()

    def add(ma_mh: str, alias: str, alias_type: str, source: str, priority: int) -> None:
        if ma_mh not in courses:
            return
        key = normalize_alias(alias)
        if not key:
            return
        if key in ambiguous_generated_keys:
            return
        canonical = CANONICAL_COURSE_ALIASES.get(ma_mh, (normalize_alias(courses[ma_mh]), []))[0]
        canonical = normalize_alias(canonical)
        requires_context = int(len(key) <= 2 or key in {"ai", "it", "ml", "os", "se"})
        previous = candidates.get(key)
        record = (ma_mh, alias, canonical, alias_type, priority, requires_context)
        if previous is not None and previous[0] != ma_mh:
            if alias_type == "MA_MON_RUT_GON" and previous[3] == "MA_MON_RUT_GON":
                candidates.pop(key, None)
                candidate_sources.pop(key, None)
                ambiguous_generated_keys.add(key)
                return
            raise RuntimeError(f"Ambiguous course AliasKey {key!r}: {previous[0]} vs {ma_mh}")
        if previous is None or priority > previous[4]:
            candidates[key] = record
            candidate_sources[key] = source

    for ma_mh, title in courses.items():
        add(ma_mh, ma_mh, "MA_MON", "MONHOC", 200)
        prefix = re.match(r"^[A-Za-z]{3,}", ma_mh)
        if prefix:
            add(ma_mh, prefix.group(0), "MA_MON_RUT_GON", "MONHOC", 110)
        add(ma_mh, title, "TEN_MON", "MONHOC", 130)
    for row in old_rows:
        add(row["MaMH"], row["Alias"], "BIEN_THE", row["Nguon"], 90)
    for ma_mh, (canonical, aliases) in CANONICAL_COURSE_ALIASES.items():
        add(ma_mh, canonical, "THU_CONG", "CANONICAL_TRAIN_VOCAB", 180)
        for alias in aliases:
            alias_type = "VIET_TAT" if len(normalize_alias(alias).replace(" ", "")) <= 6 else "BIEN_THE"
            add(ma_mh, alias, alias_type, "CANONICAL_TRAIN_VOCAB", 170)
    for pdf_code, canonical_code in PDF_K23_EQUIVALENT_CODES.items():
        add(canonical_code, pdf_code, "MA_MON", "PDF_K23_EQUIVALENT_CODE", 190)

    stopwords = {"and", "of", "the", "to", "for", "in", "on", "or", "va", "cua"}
    for ma_mh, title in courses.items():
        code_match = re.match(r"^([A-Za-z]+)(.+)$", ma_mh)
        normalized_title = normalize_alias(title)
        cleaned_title = normalize_alias(re.sub(r"\([^)]*\)", " ", title))
        acronym_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", normalized_title)
            if token not in stopwords
        ]
        acronym = "".join(token if token.isdigit() else token[0] for token in acronym_tokens)
        generated: list[tuple[str, str]] = []
        if code_match:
            prefix, suffix = code_match.groups()
            generated.extend(
                [
                    (f"{prefix} {suffix}", "BIEN_THE"),
                    (f"{prefix}-{suffix}", "BIEN_THE"),
                ]
            )
            if suffix.upper().endswith("E"):
                generated.extend(
                    [
                        (f"{prefix}{suffix[:-1]}", "BIEN_THE"),
                        (f"{prefix} {suffix[:-1]}", "BIEN_THE"),
                    ]
                )
            numeric_suffix = suffix[:-1] if suffix.upper().endswith("E") else suffix
            if numeric_suffix.isdigit() and len(numeric_suffix) == 6:
                generated.extend(
                    [
                        (f"{prefix} {numeric_suffix[:3]} {numeric_suffix[3:]}", "BIEN_THE"),
                        (f"{prefix}-{numeric_suffix[:3]}-{numeric_suffix[3:]}", "BIEN_THE"),
                    ]
                )
        if cleaned_title and cleaned_title != normalized_title:
            generated.append((cleaned_title, "BIEN_THE"))
        if len(acronym) >= 2:
            generated.append((acronym, "VIET_TAT"))

        canonical = normalize_alias(CANONICAL_COURSE_ALIASES.get(ma_mh, (normalized_title, []))[0])
        for alias, alias_type in generated:
            current_count = sum(1 for record in candidates.values() if record[2] == canonical)
            if current_count >= 5:
                break
            key = normalize_alias(alias)
            previous = candidates.get(key)
            if key in ambiguous_generated_keys or (previous is not None and previous[0] != ma_mh):
                continue
            add(ma_mh, alias, alias_type, "HUMAN_CODE_OR_ACRONYM_VARIANT", 120)

        current_count = sum(1 for record in candidates.values() if record[2] == canonical)
        if current_count < 5:
            raise RuntimeError(
                f"CanonicalText {canonical!r} for {ma_mh} has only {current_count} usable aliases"
            )

    conn.executemany(
        """
        INSERT INTO MonHocAlias
            (MaMH, Alias, AliasKey, CanonicalText, LoaiAlias, Nguon, DoUuTien, YeuCauNguCanh, IsActive)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        [
            (ma_mh, alias, key, canonical, alias_type, candidate_sources[key], priority, context)
            for key, (ma_mh, alias, canonical, alias_type, priority, context) in sorted(candidates.items())
        ],
    )
    return {"aliases": len(candidates), "canonical_courses": len({record[0] for record in candidates.values()})}


def drop_monhoc_excel_row(conn: sqlite3.Connection) -> bool:
    if not has_column(conn, "MonHoc", "ExcelRow"):
        return False
    conn.execute("ALTER TABLE MonHoc DROP COLUMN ExcelRow")
    return True


def ensure_student_identity_schema(conn: sqlite3.Connection) -> None:
    sinh_vien_columns = {
        "GioiTinh": "TEXT",
        "NgaySinh": "TEXT",
        "NoiSinh": "TEXT",
        "QuocTich": "TEXT",
        "DanToc": "TEXT",
        "TonGiao": "TEXT",
        "CCCD": "TEXT",
        "NgayCapCCCD": "TEXT",
        "NoiCapCCCD": "TEXT",
        "SoDienThoai": "TEXT",
        "EmailCaNhan": "TEXT",
        "DiaChiThuongTru": "TEXT",
        "DiaChiTamTru": "TEXT",
        "LopQuanLy": "TEXT",
        "BacDaoTao": "TEXT",
        "HeDaoTao": "TEXT",
        "LoaiHinhDaoTao": "TEXT",
        "NgayNhapHoc": "TEXT",
    }
    for column_name, definition in sinh_vien_columns.items():
        add_column_if_missing(conn, "SinhVien", column_name, definition)

    tai_khoan_columns = {
        "AnhDaiDienUrl": "TEXT",
        "EmailXacThuc": "TEXT",
        "SoDienThoaiXacThuc": "TEXT",
        "LanDoiMatKhauCuoi": "TEXT",
        "YeuCauDoiMatKhau": "INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, definition in tai_khoan_columns.items():
        add_column_if_missing(conn, "TaiKhoan", column_name, definition)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS SinhVienLienHe (
            MaLienHe TEXT PRIMARY KEY,
            MaSV TEXT NOT NULL,
            QuanHe TEXT NOT NULL,
            HoTen TEXT NOT NULL,
            SoDienThoai TEXT,
            DiaChi TEXT,
            Email TEXT,
            LaLienHeKhanCap INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (MaSV) REFERENCES SinhVien(MaSV)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sinh_vien_lien_he_masv ON SinhVienLienHe(MaSV)")

    conn.execute(
        """
        WITH profile AS (
          SELECT
            sv.MaSV,
            kh.NamNhapHoc,
            COALESCE(n.BacDaoTao, 'Đại học') AS BacDaoTao,
            COALESCE(n.HeDaoTao, 'Chính quy') AS HeDaoTao,
            CAST(substr(sv.MaSV, -2) AS INTEGER) AS seed2,
            CAST(substr(sv.MaSV, -4) AS INTEGER) AS seed4,
            CAST(substr(sv.MaSV, -6) AS INTEGER) AS seed6
          FROM SinhVien sv
          JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
          JOIN Nganh n ON n.MaNganh = kh.MaNganh
        )
        UPDATE SinhVien
        SET
            GioiTinh = CASE WHEN (SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 2 = 0 THEN 'Nam' ELSE 'Nữ' END,
            NgaySinh = printf(
                '%04d-%02d-%02d',
                (SELECT NamNhapHoc - 18 FROM profile WHERE profile.MaSV = SinhVien.MaSV),
                ((SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 12) + 1,
                ((SELECT seed4 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 28) + 1
            ),
            NoiSinh = CASE (SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 6
                WHEN 0 THEN 'TP. Hồ Chí Minh'
                WHEN 1 THEN 'Đồng Nai'
                WHEN 2 THEN 'Bình Dương'
                WHEN 3 THEN 'Long An'
                WHEN 4 THEN 'Tiền Giang'
                ELSE 'Bà Rịa - Vũng Tàu'
            END,
            QuocTich = 'Việt Nam',
            DanToc = CASE WHEN (SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 20 = 0 THEN 'Hoa' ELSE 'Kinh' END,
            TonGiao = CASE WHEN (SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 9 = 0 THEN 'Phật giáo' ELSE 'Không' END,
            CCCD = printf('%012d', CAST(MaSV AS INTEGER)),
            NgayCapCCCD = date(
                printf(
                    '%04d-%02d-%02d',
                    (SELECT NamNhapHoc - 18 FROM profile WHERE profile.MaSV = SinhVien.MaSV),
                    ((SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 12) + 1,
                    ((SELECT seed4 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 28) + 1
                ),
                '+18 years',
                '+30 days'
            ),
            NoiCapCCCD = 'Cục Cảnh sát QLHC về TTXH',
            SoDienThoai = printf('09%08d', (SELECT seed6 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 100000000),
            EmailCaNhan = lower(MaSV || '@gmail.com'),
            DiaChiThuongTru = CASE (SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 6
                WHEN 0 THEN 'TP. Hồ Chí Minh'
                WHEN 1 THEN 'Đồng Nai'
                WHEN 2 THEN 'Bình Dương'
                WHEN 3 THEN 'Long An'
                WHEN 4 THEN 'Tiền Giang'
                ELSE 'Bà Rịa - Vũng Tàu'
            END,
            DiaChiTamTru = 'TP. Hồ Chí Minh',
            LopQuanLy = MaKhoaHoc || '_' || printf('%02d', ((SELECT seed2 FROM profile WHERE profile.MaSV = SinhVien.MaSV) % 6) + 1),
            BacDaoTao = (SELECT BacDaoTao FROM profile WHERE profile.MaSV = SinhVien.MaSV),
            HeDaoTao = (SELECT HeDaoTao FROM profile WHERE profile.MaSV = SinhVien.MaSV),
            LoaiHinhDaoTao = 'Chính quy',
            NgayNhapHoc = printf('%04d-09-05', (SELECT NamNhapHoc FROM profile WHERE profile.MaSV = SinhVien.MaSV))
        """
    )

    conn.execute(
        """
        UPDATE TaiKhoan
        SET
            AnhDaiDienUrl = COALESCE(AnhDaiDienUrl, '/references/ute_logo.png'),
            EmailXacThuc = COALESCE(EmailXacThuc, Email),
            SoDienThoaiXacThuc = COALESCE(
                SoDienThoaiXacThuc,
                (SELECT SoDienThoai FROM SinhVien WHERE SinhVien.MaSV = TaiKhoan.MaSV)
            ),
            LanDoiMatKhauCuoi = COALESCE(LanDoiMatKhauCuoi, ThoiDiemTao),
            YeuCauDoiMatKhau = COALESCE(YeuCauDoiMatKhau, 0)
        """
    )

    conn.execute("DELETE FROM SinhVienLienHe")
    conn.execute(
        """
        INSERT INTO SinhVienLienHe
            (MaLienHe, MaSV, QuanHe, HoTen, SoDienThoai, DiaChi, Email, LaLienHeKhanCap)
        SELECT
            'LH_' || MaSV || '_ME',
            MaSV,
            'ME',
            'Phụ huynh ' || HoTen,
            printf('08%08d', (CAST(substr(MaSV, -6) AS INTEGER) + 1703) % 100000000),
            DiaChiThuongTru,
            NULL,
            1
        FROM SinhVien
        UNION ALL
        SELECT
            'LH_' || MaSV || '_CHA',
            MaSV,
            'CHA',
            'Phụ huynh ' || HoTen,
            printf('03%08d', (CAST(substr(MaSV, -6) AS INTEGER) + 2707) % 100000000),
            DiaChiThuongTru,
            NULL,
            0
        FROM SinhVien
        """
    )


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
    pdf_courses_inserted: int,
    relationship_stats: dict[str, int],
    semester_stats: dict[str, int],
    alias_stats: dict[str, int],
    dropped_monhoc_excel_row: bool,
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
        ("V3_NGUON_CTDT_K23", "data/9.-INFORMATION-TECHNOLOGY_K23-1-1.pdf"),
        ("V3_SO_MON_TU_CHON_BO_SUNG_TU_PDF", str(pdf_courses_inserted)),
        ("V3_SO_HK_GOI_Y_SUA_THEO_PDF", str(semester_stats["official_changed"])),
        ("V3_SO_HK_TU_CHON_SUY_LUAN", str(semester_stats["elective_inferred"])),
        ("V3_SO_QUAN_HE_PDF_TIEN_QUYET", str(relationship_stats["strict_pdf"])),
        ("V3_SO_QUAN_HE_PDF_HOC_TRUOC", str(relationship_stats["soft_pdf"])),
        ("V3_SO_QUAN_HE_HOC_PHAN", str(relationship_stats["total"])),
        ("V3_SO_MON_HOC_ALIAS", str(alias_stats["aliases"])),
        ("V3_DA_XOA_MONHOC_EXCELROW", str(int(dropped_monhoc_excel_row))),
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
            "can bang tin chi DangKy hien tai; doi chieu CTDT K23; hop nhat quan he hoc phan; "
            "canonical hoa alias mon hoc; rebuild view hien tai va dieu kien dang ky.",
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
    if has_column(conn, "MonHoc", "ExcelRow"):
        raise RuntimeError("Validation failed: MonHoc.ExcelRow still exists")
    for object_name in ("QuanHeHocPhan", "TienQuyet"):
        row = conn.execute("SELECT type FROM sqlite_master WHERE name = ?", (object_name,)).fetchone()
        if row is None or row["type"] != "view":
            raise RuntimeError(f"Validation failed: {object_name} must be a compatibility view")
    semester_mismatches = [
        (ma_mh, semester)
        for ma_mh, semester in PDF_K23_SEMESTERS.items()
        if conn.execute(
            "SELECT HKGoiY FROM CTDT_MonHoc WHERE MaCTDT = ? AND MaMH = ?",
            (CTDT_ID, ma_mh),
        ).fetchone()[0]
        != semester
    ]
    if semester_mismatches:
        raise RuntimeError(f"Validation failed for PDF K23 semesters: {semester_mismatches}")

    checks = {
        "foreign_key_check": "PRAGMA foreign_key_check",
        "pdf_prerequisite_semester_order": """
            SELECT qh.MaMH, qh.MaMHDieuKien
            FROM CTDT_QuanHeHocPhan qh
            JOIN CTDT_MonHoc target
              ON target.MaCTDT = qh.MaCTDT AND target.MaMH = qh.MaMH
            JOIN CTDT_MonHoc required
              ON required.MaCTDT = qh.MaCTDT AND required.MaMH = qh.MaMHDieuKien
            WHERE qh.LoaiQuanHe = 'TIEN_QUYET'
              AND qh.Nguon LIKE 'PDF_K23%'
              AND required.HKGoiY >= target.HKGoiY
        """,
        "alias_invalid": """
            SELECT AliasID
            FROM MonHocAlias
            WHERE AliasKey = '' OR CanonicalText = '' OR IsActive NOT IN (0, 1)
        """,
        "alias_key_collision": """
            SELECT AliasKey
            FROM MonHocAlias
            GROUP BY AliasKey
            HAVING COUNT(DISTINCT MaMH) > 1
        """,
        "canonical_alias_coverage": """
            SELECT CanonicalText
            FROM MonHocAlias
            WHERE IsActive = 1
            GROUP BY CanonicalText
            HAVING COUNT(*) < 5
        """,
        "ctdt_missing_hk_goi_y": "SELECT MaCTDT, MaMH FROM CTDT_MonHoc WHERE HKGoiY IS NULL",
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
            examples = [dict(row) for row in rows[:5]]
            raise RuntimeError(f"Validation failed for {name}: {len(rows)} rows; examples={examples}")


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN")
        refresh_system_semesters(conn)
        sync_current_registration_config(conn)
        ensure_student_identity_schema(conn)
        pdf_courses_inserted = ensure_pdf_catalog_courses(conn)
        relationship_stats = rebuild_curriculum_relationships(conn)
        semester_stats = apply_k23_semester_plan(conn)
        softened_description_count = soften_noncausal_description_prerequisites(conn)
        relationship_stats["strict_pdf"] -= softened_description_count
        relationship_stats["soft_pdf"] += softened_description_count
        alias_stats = rebuild_course_aliases_v3(conn)
        dropped_monhoc_excel_row = drop_monhoc_excel_row(conn)
        removed_non_current_count = remove_non_current_registrations(conn)
        filled_hk_goi_y_count = normalize_required_course_suggested_terms(conn)
        normalized_ctdt_credit_count, filled_group_hk_count = normalize_curriculum_requirements(conn)
        additionally_softened_count = soften_noncausal_description_prerequisites(conn)
        relationship_stats["strict_pdf"] -= additionally_softened_count
        relationship_stats["soft_pdf"] += additionally_softened_count
        removed_prereq_count = remove_strict_prerequisite_violations(conn)
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
            pdf_courses_inserted,
            relationship_stats,
            semester_stats,
            alias_stats,
            dropped_monhoc_excel_row,
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
