from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "ctdt_sis.db"
DEFAULT_OUTPUT_DB = PROJECT_ROOT / "data" / "ctdt_sis_v2.db"


MANUAL_COURSE_ALIASES: dict[str, list[str]] = {
    "INPR130185E": ["nhap mon lap trinh", "lap trinh co ban", "introduction to programming", "inpr"],
    "CALC140101E": ["giai tich", "calculus", "calc"],
    "LIAL140102E": ["dai so tuyen tinh", "linear algebra", "lial"],
    "ACEN140103E": ["tieng anh hoc thuat", "academic english", "anh van", "acen"],
    "PHYS140104E": ["vat ly ky thuat", "engineering physics", "phys"],
    "DASA230179E": ["cau truc du lieu va giai thuat", "ctdlgt", "ctdl", "data structures and algorithms", "dsa"],
    "OOPR230279E": ["lap trinh huong doi tuong", "oop", "object oriented programming"],
    "PROS220301E": ["xac suat thong ke", "probability and statistics", "pros"],
    "DISM230302E": ["toan roi rac", "discrete mathematics", "dism"],
    "DBSY230184E": ["co so du lieu", "csdl", "database systems", "database", "dbsy"],
    "COAR230280E": ["kien truc may tinh", "computer architecture", "coar"],
    "OSYS330281E": ["he dieu hanh", "operating systems", "os", "osys"],
    "NECO330282E": ["mang may tinh", "computer networks", "network", "neco"],
    "DBMS330284E": ["quan tri co so du lieu", "dbms", "database management systems", "quan tri csdl"],
    "WEPR330383E": ["lap trinh web", "web programming", "web", "wepr"],
    "SOEN330384E": ["cong nghe phan mem", "software engineering", "se", "soen"],
    "ARIN330585E": ["tri tue nhan tao", "ai", "artificial intelligence", "arin"],
    "INDS331085E": ["nhap mon khoa hoc du lieu", "data science", "khoa hoc du lieu", "inds"],
    "MALE431085E": ["hoc may", "machine learning", "ml", "male"],
    "NLPR431585E": ["xu ly ngon ngu tu nhien", "nlp", "nlpr", "natural language processing"],
    "DIPR430685E": ["xu ly anh so", "digital image processing", "dip", "dipr"],
    "MOPR331279E": ["lap trinh di dong", "mobile programming", "mobile", "mopr"],
    "CYSE430387E": ["an toan thong tin", "an ninh mang", "cybersecurity", "cyse"],
    "CLCO430986E": ["dien toan dam may", "cloud computing", "cloud", "clco"],
    "DAEN431188E": ["ky thuat du lieu", "data engineering", "daen"],
    "GRPR421201E": ["do an tot nghiep", "graduation project", "grpr"],
}


@dataclass(frozen=True)
class SemesterWindow:
    year: int
    semester: int
    start: date
    end: date
    registration_start: date
    registration_end: date

    @property
    def code(self) -> str:
        return f"{self.year}-{self.semester}"

    @property
    def name(self) -> str:
        return f"Học kỳ {self.semester} năm học {self.year}"

    def status_on(self, today: date) -> str:
        if self.registration_start <= today <= self.registration_end:
            return "DANG_MO_DANG_KY"
        if today < self.registration_start:
            return "SAP_MO"
        return "DA_KET_THUC"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create/update ctdt_sis_v2.db and apply order 1-2 normalization.",
    )
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DB)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recreate output from source before applying migrations.",
    )
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=date.today(),
        help="Date used to calculate the current registration semester, YYYY-MM-DD.",
    )
    return parser.parse_args()


def strip_accents(value: str) -> str:
    value = value.replace("Đ", "D").replace("đ", "d")
    value = unicodedata.normalize("NFD", value)
    return "".join(ch for ch in value if unicodedata.category(ch) != "Mn")


def normalize_text(value: str) -> str:
    value = strip_accents(value).lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_vietnamese_slug(value: str) -> str:
    return " ".join(strip_accents(value).upper().split())


def make_code(value: str, max_length: int = 40) -> str:
    normalized = normalize_vietnamese_slug(value)
    chars = [ch if ch.isalnum() else "_" for ch in normalized]
    code = "".join(chars).strip("_")
    while "__" in code:
        code = code.replace("__", "_")
    return (code[:max_length] or "UNKNOWN").strip("_")


def major_code_from_name(name: str) -> str:
    normalized = normalize_vietnamese_slug(name)
    if "CONG NGHE THONG TIN" in normalized:
        return "CNTT"
    words = [word for word in normalized.split() if word]
    initials = "".join(word[0] for word in words)
    return initials[:20] or make_code(name, max_length=20)


def semester_windows(year: int) -> list[SemesterWindow]:
    return [
        SemesterWindow(
            year=year,
            semester=1,
            start=date(year, 1, 5),
            end=date(year, 5, 31),
            registration_start=date(year - 1, 12, 1),
            registration_end=date(year, 1, 31),
        ),
        SemesterWindow(
            year=year,
            semester=2,
            start=date(year, 8, 17),
            end=date(year, 12, 31),
            registration_start=date(year, 6, 1),
            registration_end=date(year, 9, 15),
        ),
    ]


def choose_current_registration_term(today: date) -> SemesterWindow:
    candidates = [
        window
        for year in range(today.year - 1, today.year + 2)
        for window in semester_windows(year)
    ]
    open_terms = [
        window
        for window in candidates
        if window.registration_start <= today <= window.registration_end
    ]
    if open_terms:
        return sorted(open_terms, key=lambda item: item.registration_start)[0]

    future_terms = [window for window in candidates if today < window.registration_start]
    if future_terms:
        return sorted(future_terms, key=lambda item: item.registration_start)[0]

    return sorted(candidates, key=lambda item: item.registration_start)[-1]


def ensure_output_db(source: Path, output: Path, force: bool) -> None:
    if not source.exists():
        raise FileNotFoundError(f"Source DB not found: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if force or not output.exists():
        shutil.copy2(source, output)


def fetch_required_tables(conn: sqlite3.Connection, tables: Iterable[str]) -> None:
    existing = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'",
        )
    }
    missing = sorted(set(tables) - existing)
    if missing:
        raise RuntimeError(f"Missing required tables: {', '.join(missing)}")


def normalize_departments(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT MaKhoaBM, TenKhoaBM FROM KhoaBoMon").fetchall()
    for old_code, name in rows:
        new_code = make_code(name)
        if new_code == old_code:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO KhoaBoMon (MaKhoaBM, TenKhoaBM) VALUES (?, ?)",
            (new_code, name),
        )
        conn.execute("UPDATE MonHoc SET MaKhoaBM = ? WHERE MaKhoaBM = ?", (new_code, old_code))
        conn.execute("UPDATE GiangVien SET MaKhoaBM = ? WHERE MaKhoaBM = ?", (new_code, old_code))
        conn.execute("DELETE FROM KhoaBoMon WHERE MaKhoaBM = ?", (old_code,))


def normalize_majors(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT MaNganh, TenNganh, BacDaoTao, HeDaoTao FROM Nganh",
    ).fetchall()
    for old_code, name, degree, program_type in rows:
        new_code = major_code_from_name(name)
        if new_code == old_code:
            continue
        conn.execute(
            """
            INSERT OR IGNORE INTO Nganh (MaNganh, TenNganh, BacDaoTao, HeDaoTao)
            VALUES (?, ?, ?, ?)
            """,
            (new_code, name, degree, program_type),
        )
        conn.execute("UPDATE CTDT SET MaNganh = ? WHERE MaNganh = ?", (new_code, old_code))
        conn.execute("UPDATE KhoaHoc SET MaNganh = ? WHERE MaNganh = ?", (new_code, old_code))
        conn.execute("DELETE FROM Nganh WHERE MaNganh = ?", (old_code,))


def upsert_registration_config(conn: sqlite3.Connection, current_term: SemesterWindow) -> None:
    rows = [
        ("NAM_HOC_HIEN_TAI", str(current_term.year), "Năm học/kế hoạch đăng ký hiện tại của hệ thống."),
        ("HOC_KY_HIEN_TAI", str(current_term.semester), "Học kỳ đăng ký hiện tại của hệ thống."),
        ("MA_HOC_KY_HIEN_TAI", current_term.code, "Mã học kỳ đăng ký hiện tại của hệ thống."),
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


def upsert_semesters(conn: sqlite3.Connection, today: date) -> None:
    current_term = choose_current_registration_term(today)
    for window in semester_windows(current_term.year):
        status = window.status_on(today)
        is_registration_open = 1 if status == "DANG_MO_DANG_KY" else 0
        conn.execute(
            """
            INSERT INTO HocKyHeThong
                (MaHocKy, NamHoc, HocKy, TenHocKy, TrangThai, DangMoDangKy, NgayBatDau, NgayKetThuc)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(MaHocKy) DO UPDATE SET
                NamHoc = excluded.NamHoc,
                HocKy = excluded.HocKy,
                TenHocKy = excluded.TenHocKy,
                TrangThai = excluded.TrangThai,
                DangMoDangKy = excluded.DangMoDangKy,
                NgayBatDau = excluded.NgayBatDau,
                NgayKetThuc = excluded.NgayKetThuc
            """,
            (
                window.code,
                window.year,
                window.semester,
                window.name,
                status,
                is_registration_open,
                window.start.isoformat(),
                window.end.isoformat(),
            ),
        )
    upsert_registration_config(conn, current_term)


def relativize_source_path(value: str) -> str:
    path = Path(value)
    if not path.is_absolute():
        return value.replace("\\", "/")
    try:
        return path.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def normalize_metadata(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT GiaTri FROM ThongTinTaoDuLieu WHERE MaThongTin = 'DUONG_DAN_EXCEL_NGUON'",
    ).fetchone()
    if row:
        conn.execute(
            """
            UPDATE ThongTinTaoDuLieu
            SET GiaTri = ?
            WHERE MaThongTin = 'DUONG_DAN_EXCEL_NGUON'
            """,
            (relativize_source_path(row[0]),),
        )

    rows = [
        ("PHIEN_BAN_CSDL", "ctdt_sis_v2"),
        ("THOI_DIEM_CHUAN_HOA_NEN", datetime.now().isoformat(timespec="seconds")),
        ("NOI_DUNG_CHUAN_HOA_NEN", "KhoaBoMon,Nganh,CauHinhDangKy,HocKyHeThong,ThongTinTaoDuLieu"),
    ]
    conn.executemany(
        """
        INSERT INTO ThongTinTaoDuLieu (MaThongTin, GiaTri)
        VALUES (?, ?)
        ON CONFLICT(MaThongTin) DO UPDATE SET GiaTri = excluded.GiaTri
        """,
        rows,
    )


def normalize_curricula(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT MaCTDT, NguonDuLieu FROM CTDT").fetchall()
    for ma_ctdt, source_path in rows:
        required_credits = conn.execute(
            """
            SELECT COALESCE(SUM(mh.SoTC), 0)
            FROM CTDT_MonHoc ctdt_mh
            JOIN MonHoc mh ON ctdt_mh.MaMH = mh.MaMH
            WHERE ctdt_mh.MaCTDT = ?
              AND ctdt_mh.LoaiYC = 'BAT_BUOC'
            """,
            (ma_ctdt,),
        ).fetchone()[0]
        minimum_elective_credits = conn.execute(
            """
            SELECT COALESCE(SUM(SoTCCanChon), 0)
            FROM CTDT_NhomTuChon
            WHERE MaCTDT = ?
            """,
            (ma_ctdt,),
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE CTDT
            SET TongTinChiToiThieu = ?,
                NguonDuLieu = ?
            WHERE MaCTDT = ?
            """,
            (
                required_credits + minimum_elective_credits,
                relativize_source_path(source_path or ""),
                ma_ctdt,
            ),
        )

    upsert_metadata(
        conn,
        [
            ("CACH_TINH_TONG_TIN_CHI_TOI_THIEU", "Tin chi bat buoc + tong SoTCCanChon cua cac nhom tu chon."),
        ],
    )


def normalize_elective_groups(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT MaCTDT, MaNhomTC, TenNhom, SoTCCanChon, HocKyGoiY
        FROM CTDT_NhomTuChon
        ORDER BY MaCTDT, MaNhomTC
        """
    ).fetchall()
    for ma_ctdt, ma_nhom, ten_nhom, so_tc_can_chon, hoc_ky_goi_y in rows:
        offered_credits = conn.execute(
            """
            SELECT COALESCE(SUM(mh.SoTC), 0)
            FROM CTDT_MonHoc ctdt_mh
            JOIN MonHoc mh ON ctdt_mh.MaMH = mh.MaMH
            WHERE ctdt_mh.MaCTDT = ?
              AND ctdt_mh.MaNhomTC = ?
            """,
            (ma_ctdt, ma_nhom),
        ).fetchone()[0]
        offered_courses = conn.execute(
            """
            SELECT COUNT(*)
            FROM CTDT_MonHoc
            WHERE MaCTDT = ?
              AND MaNhomTC = ?
            """,
            (ma_ctdt, ma_nhom),
        ).fetchone()[0]

        if so_tc_can_chon is None:
            normalized_name = ten_nhom
            description = f"Nhóm tự chọn gồm {offered_courses} học phần, tổng {offered_credits} tín chỉ."
        else:
            normalized_name = f"Tự chọn {ma_nhom} (chọn {so_tc_can_chon}/{offered_credits} tín chỉ)"
            description = (
                f"Sinh viên chọn tối thiểu {so_tc_can_chon} tín chỉ "
                f"trong {offered_courses} học phần, tổng {offered_credits} tín chỉ."
            )
        if hoc_ky_goi_y:
            description += f" Gợi ý học kỳ {hoc_ky_goi_y}."

        conn.execute(
            """
            UPDATE CTDT_NhomTuChon
            SET TenNhom = ?,
                TongTCCungCap = ?,
                MoTa = ?,
                Nguon = 'EXCEL_CTDT'
            WHERE MaCTDT = ?
              AND MaNhomTC = ?
            """,
            (normalized_name, offered_credits or None, description, ma_ctdt, ma_nhom),
        )


def normalize_curriculum_courses(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE CTDT_MonHoc
        SET TenNhomTC = (
                SELECT ntc.TenNhom
                FROM CTDT_NhomTuChon ntc
                WHERE ntc.MaCTDT = CTDT_MonHoc.MaCTDT
                  AND ntc.MaNhomTC = CTDT_MonHoc.MaNhomTC
            )
        WHERE MaNhomTC IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE CTDT_MonHoc
        SET STTTrongCTDT = NULL
        WHERE STTTrongCTDT IS NOT NULL
          AND TRIM(STTTrongCTDT) = ''
        """
    )


def prerequisite_text(conn: sqlite3.Connection, ma_mh: str, relation_type: str) -> str | None:
    rows = conn.execute(
        """
        SELECT qh.MaMHDieuKien, mh.TenMH
        FROM QuanHeHocPhan qh
        JOIN MonHoc mh ON qh.MaMHDieuKien = mh.MaMH
        WHERE qh.MaMH = ?
          AND qh.LoaiQuanHe = ?
        ORDER BY qh.MaMHDieuKien
        """,
        (ma_mh, relation_type),
    ).fetchall()
    if not rows:
        return None
    return "; ".join(f"{code} - {name}" for code, name in rows)


def normalize_courses(conn: sqlite3.Connection) -> None:
    for (ma_mh,) in conn.execute("SELECT MaMH FROM MonHoc ORDER BY MaMH").fetchall():
        conn.execute(
            """
            UPDATE MonHoc
            SET HocPhanTienQuyetText = ?,
                HocPhanHocTruocText = ?,
                HocPhanTuongDuongText = ?
            WHERE MaMH = ?
            """,
            (
                prerequisite_text(conn, ma_mh, "TIEN_QUYET"),
                prerequisite_text(conn, ma_mh, "HOC_TRUOC"),
                prerequisite_text(conn, ma_mh, "TUONG_DUONG"),
                ma_mh,
            ),
        )

    conn.execute(
        """
        UPDATE MonHoc
        SET LaMonDieuKien = CASE
            WHEN TenMH LIKE '%(*)%' THEN 1
            ELSE 0
        END
        """
    )
    upsert_metadata(
        conn,
        [
            ("DINH_NGHIA_LA_MON_DIEU_KIEN", "1 neu ten hoc phan co dau (*) va thuong la hoc phan dieu kien/khong tinh nhu mon chuyen nganh."),
        ],
    )


def alias_candidates(ma_mh: str, ten_mh: str) -> set[tuple[str, str]]:
    aliases: set[tuple[str, str]] = {
        (ma_mh, "MA_MON"),
        (ma_mh.lower(), "MA_MON"),
        (normalize_text(ten_mh), "TEN_MON_KHONG_DAU"),
    }
    cleaned_name = re.sub(r"\(\*\)", "", ten_mh).strip()
    if cleaned_name != ten_mh:
        aliases.add((normalize_text(cleaned_name), "TEN_MON_KHONG_DAU"))

    prefix = re.match(r"^[A-Za-z]+", ma_mh)
    if prefix and len(prefix.group(0)) >= 3:
        aliases.add((prefix.group(0).lower(), "MA_MON_RUT_GON"))

    for alias in MANUAL_COURSE_ALIASES.get(ma_mh, []):
        aliases.add((normalize_text(alias), "THU_CONG"))
    return {(alias, alias_type) for alias, alias_type in aliases if alias}


def rebuild_course_aliases(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS MonHocAlias (
            MaMH TEXT NOT NULL,
            Alias TEXT NOT NULL,
            AliasNormalized TEXT NOT NULL,
            LoaiAlias TEXT NOT NULL CHECK (LoaiAlias IN ('MA_MON', 'MA_MON_RUT_GON', 'TEN_MON_KHONG_DAU', 'THU_CONG')),
            Nguon TEXT NOT NULL,
            PRIMARY KEY (MaMH, AliasNormalized),
            FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH)
        )
        """
    )
    conn.execute("DELETE FROM MonHocAlias")
    rows = conn.execute("SELECT MaMH, TenMH FROM MonHoc ORDER BY MaMH").fetchall()
    for ma_mh, ten_mh in rows:
        for alias, alias_type in alias_candidates(ma_mh, ten_mh):
            normalized = normalize_text(alias)
            conn.execute(
                """
                INSERT OR IGNORE INTO MonHocAlias
                    (MaMH, Alias, AliasNormalized, LoaiAlias, Nguon)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ma_mh, alias, normalized, alias_type, "MIGRATION_V2_ORDER2"),
            )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_monhoc_alias_norm ON MonHocAlias(AliasNormalized)")


def upsert_metadata(conn: sqlite3.Connection, rows: Iterable[tuple[str, str]]) -> None:
    conn.executemany(
        """
        INSERT INTO ThongTinTaoDuLieu (MaThongTin, GiaTri)
        VALUES (?, ?)
        ON CONFLICT(MaThongTin) DO UPDATE SET GiaTri = excluded.GiaTri
        """,
        list(rows),
    )


def normalize_catalog(conn: sqlite3.Connection) -> None:
    normalize_curricula(conn)
    normalize_elective_groups(conn)
    normalize_courses(conn)
    normalize_curriculum_courses(conn)
    rebuild_course_aliases(conn)
    upsert_metadata(
        conn,
        [
            ("THOI_DIEM_CHUAN_HOA_CATALOG_CTDT", datetime.now().isoformat(timespec="seconds")),
            ("NOI_DUNG_CHUAN_HOA_CATALOG_CTDT", "CTDT,CTDT_NhomTuChon,MonHoc,CTDT_MonHoc,MonHocAlias"),
        ],
    )


def migrate(output: Path, today: date) -> None:
    required_tables = [
        "KhoaBoMon",
        "Nganh",
        "CauHinhDangKy",
        "HocKyHeThong",
        "ThongTinTaoDuLieu",
        "CTDT",
        "CTDT_NhomTuChon",
        "MonHoc",
        "CTDT_MonHoc",
        "KhoaHoc",
        "GiangVien",
        "QuanHeHocPhan",
    ]
    conn = sqlite3.connect(output)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        fetch_required_tables(conn, required_tables)
        conn.execute("BEGIN")
        normalize_departments(conn)
        normalize_majors(conn)
        upsert_semesters(conn, today)
        normalize_metadata(conn)
        normalize_catalog(conn)
        fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_errors:
            raise RuntimeError(f"Foreign key check failed: {fk_errors}")
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
    ensure_output_db(source, output, args.force)
    migrate(output, args.today)
    print(f"Order 1-2 normalization applied: {output}")
    print(f"Date used for semester calculation: {args.today.isoformat()}")


if __name__ == "__main__":
    main()
