from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCEL_PATH = PROJECT_ROOT / "data" / "CTDT_HCMUTE.xlsx"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "ctdt.db"
DEFAULT_VIEWS_PATH = PROJECT_ROOT / "data" / "views.sql"

RANDOM_SEED = 20260611
ACADEMIC_YEAR = 2026
MAX_CREDITS_PER_SEMESTER = 28
DEFAULT_CAPACITY = 45

MA_NGANH_CNTT = "10"
MA_CTDT = "CTDT_HCMUTE_CNTT"

CODE_RE = re.compile(r"^[A-Z]{2,6}\d{4,}[A-Z]?$")
COURSE_CODE_IN_TEXT_RE = re.compile(r"\b[A-Z]{2,6}\d{4,}[A-Z]?\b")


@dataclass(frozen=True)
class CourseRow:
    excel_row: int
    stt: str
    ma_mh: str
    ten_mh: str
    ma_nhom_tc: Optional[str]
    ten_nhom_tc: Optional[str]
    loai_yc: str
    hk_goi_y: Optional[int]
    so_tc: int
    so_tiet_lt: int
    so_tiet_th: int
    khoa_bo_mon: str
    hoc_phan_tien_quyet: str
    hoc_phan_hoc_truoc: str
    hoc_phan_tuong_duong: str
    la_mon_dieu_kien: int


@dataclass(frozen=True)
class ElectiveGroup:
    ma_nhom_tc: str
    ten_nhom: str
    so_tc_can_chon: Optional[int]
    tong_tc_cung_cap: Optional[int]
    hoc_ky_goi_y: Optional[int]
    mo_ta: str
    nguon: str


@dataclass(frozen=True)
class NoCodeOption:
    excel_row: int
    ma_nhom_tc: str
    ten_nhom_lua_chon: str
    ten_lua_chon: str
    so_tc: int


@dataclass
class ParsedCurriculum:
    courses: List[CourseRow]
    groups: Dict[str, ElectiveGroup]
    no_code_options: List[NoCodeOption]
    raw_row_count: int


def strip_accents(text: str) -> str:
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def normalize_text(text: Any) -> str:
    text = "" if text is None else str(text)
    text = strip_accents(text).lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def clean_text(value: Any) -> str:
    if pd.isna(value):
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", text)


def as_int(value: Any, default: int = 0) -> int:
    if pd.isna(value):
        return default
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    text = clean_text(value)
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else default


def as_optional_int(value: Any) -> Optional[int]:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return int(round(float(value)))
    text = clean_text(value)
    match = re.search(r"\d+", text)
    return int(match.group(0)) if match else None


def semester_number(label: Optional[str]) -> Optional[int]:
    if not label:
        return None
    match = re.search(r"hoc ky\s*(\d+)", normalize_text(label))
    return int(match.group(1)) if match else None


def semester_key(label: Optional[str]) -> str:
    value = semester_number(label)
    if value is None:
        return "CHUA_PHAN"
    return f"HK{value}"


def parse_group_credit_rule(text: str) -> Tuple[Optional[int], Optional[int]]:
    norm = normalize_text(text)
    match = re.search(r"chon\s*(\d+)\s*/\s*(\d+)\s*tin chi", norm)
    if match:
        return int(match.group(1)), int(match.group(2))
    return None, None


def group_id_from_text(text: str, semester_label: Optional[str]) -> Optional[str]:
    if not text:
        return None
    norm = normalize_text(text)
    match = re.search(r"nhom\s*0?(\d+)", norm)
    if match:
        return f"NHOM{int(match.group(1)):02d}"
    if norm.startswith("tu chon"):
        return f"TU_CHON_CHUNG_{semester_key(semester_label)}"
    return None


def display_group_name(text: str, semester_label: Optional[str]) -> str:
    if text and normalize_text(text) != "tu chon -":
        return text
    if semester_number(semester_label):
        return f"Tự chọn chung {semester_label}"
    return "Tự chọn chung chưa phân học kỳ"


def option_group_id(group_name: str, required_credits: Optional[int]) -> str:
    norm = normalize_text(group_name)
    if "physical education 2" in norm or required_credits == 2:
        return "NHOM01"
    if "general knowledge" in norm or required_credits == 4:
        return "NHOM02"
    if "it core elective" in norm or required_credits == 12:
        return "NHOM03"
    if "specialized" in norm or required_credits == 6:
        return "NHOM04"
    if "physical education 1" in norm or required_credits == 1:
        return "NHOM05"
    slug = re.sub(r"[^A-Z0-9]+", "_", strip_accents(group_name).upper()).strip("_")
    return f"LUA_CHON_{slug[:40] or 'KHONG_MA'}"


def upsert_group(
    groups: Dict[str, ElectiveGroup],
    group: ElectiveGroup,
) -> None:
    existing = groups.get(group.ma_nhom_tc)
    if existing is None:
        groups[group.ma_nhom_tc] = group
        return

    hoc_ky_goi_y = existing.hoc_ky_goi_y
    if hoc_ky_goi_y != group.hoc_ky_goi_y:
        hoc_ky_goi_y = None

    groups[group.ma_nhom_tc] = ElectiveGroup(
        ma_nhom_tc=existing.ma_nhom_tc,
        ten_nhom=existing.ten_nhom if existing.ten_nhom else group.ten_nhom,
        so_tc_can_chon=existing.so_tc_can_chon or group.so_tc_can_chon,
        tong_tc_cung_cap=existing.tong_tc_cung_cap or group.tong_tc_cung_cap,
        hoc_ky_goi_y=hoc_ky_goi_y,
        mo_ta=existing.mo_ta if existing.mo_ta else group.mo_ta,
        nguon="excel_ctdt",
    )


def parse_curriculum(excel_path: Path) -> ParsedCurriculum:
    df = pd.read_excel(excel_path, sheet_name=0, header=0)
    columns = list(df.columns)
    if len(columns) < 11:
        raise ValueError("CTDT sheet does not have the expected 12 columns.")

    stt_col = columns[0]
    code_col = columns[1]
    name_col = columns[2]
    group_col = columns[3]
    credit_col = columns[4]
    lt_col = columns[5]
    th_col = columns[6]
    prereq_col = columns[7]
    prior_col = columns[8]
    equivalent_col = columns[9]
    dept_col = columns[10]

    current_semester: Optional[str] = None
    current_requirement: Optional[str] = None
    current_group_text: Optional[str] = None
    courses: List[CourseRow] = []
    groups: Dict[str, ElectiveGroup] = {}
    no_code_options: List[NoCodeOption] = []

    current_option_group_name: Optional[str] = None
    current_option_required: Optional[int] = None

    for idx, row in df.iterrows():
        excel_row = idx + 2
        stt_text = clean_text(row[stt_col])
        code_text = clean_text(row[code_col])
        name_text = clean_text(row[name_col])
        group_cell_text = clean_text(row[group_col])
        normalized_stt = normalize_text(stt_text)
        normalized_code = normalize_text(code_text)

        if not code_text:
            if normalized_stt.startswith("hoc ky") or normalized_stt.startswith("chua phan"):
                current_semester = stt_text
                current_requirement = None
                current_group_text = None
                current_option_group_name = None
                current_option_required = None
            elif normalized_stt == "bat buoc":
                current_requirement = "BAT_BUOC"
                current_group_text = None
            elif normalized_stt.startswith("tu chon"):
                current_requirement = "TU_CHON"
                current_group_text = stt_text
                ma_nhom_tc = group_id_from_text(stt_text, current_semester)
                if ma_nhom_tc:
                    needed, offered = parse_group_credit_rule(stt_text)
                    upsert_group(
                        groups,
                        ElectiveGroup(
                            ma_nhom_tc=ma_nhom_tc,
                            ten_nhom=display_group_name(stt_text, current_semester),
                            so_tc_can_chon=needed,
                            tong_tc_cung_cap=offered,
                            hoc_ky_goi_y=semester_number(current_semester),
                            mo_ta=stt_text,
                            nguon="excel_ctdt",
                        ),
                    )
            elif normalized_stt.startswith("sv/hv/ncs tich luy"):
                current_option_required = as_optional_int(stt_text)
                current_option_group_name = None
            elif stt_text and as_optional_int(name_text) is not None:
                current_option_group_name = stt_text
                current_option_required = as_optional_int(name_text)
                ma_nhom_tc = option_group_id(current_option_group_name, current_option_required)
                upsert_group(
                    groups,
                    ElectiveGroup(
                        ma_nhom_tc=ma_nhom_tc,
                        ten_nhom=current_option_group_name,
                        so_tc_can_chon=current_option_required,
                        tong_tc_cung_cap=None,
                        hoc_ky_goi_y=None,
                        mo_ta=current_option_group_name,
                        nguon="excel_lua_chon_khong_ma",
                    ),
                )
            continue

        if CODE_RE.match(code_text):
            if current_requirement is None:
                raise ValueError(f"Course row {excel_row} has no requirement context.")

            group_text = current_group_text or group_cell_text
            ma_nhom_tc = group_id_from_text(group_text, current_semester) if current_requirement == "TU_CHON" else None
            ten_nhom_tc = display_group_name(group_text, current_semester) if ma_nhom_tc else None
            if ma_nhom_tc:
                needed, offered = parse_group_credit_rule(group_text)
                upsert_group(
                    groups,
                    ElectiveGroup(
                        ma_nhom_tc=ma_nhom_tc,
                        ten_nhom=ten_nhom_tc or ma_nhom_tc,
                        so_tc_can_chon=needed,
                        tong_tc_cung_cap=offered,
                        hoc_ky_goi_y=semester_number(current_semester),
                        mo_ta=group_text,
                        nguon="excel_ctdt",
                    ),
                )

            courses.append(
                CourseRow(
                    excel_row=excel_row,
                    stt=stt_text,
                    ma_mh=code_text,
                    ten_mh=name_text,
                    ma_nhom_tc=ma_nhom_tc,
                    ten_nhom_tc=ten_nhom_tc,
                    loai_yc=current_requirement,
                    hk_goi_y=semester_number(current_semester),
                    so_tc=as_int(row[credit_col], default=0),
                    so_tiet_lt=as_int(row[lt_col], default=0),
                    so_tiet_th=as_int(row[th_col], default=0),
                    khoa_bo_mon=clean_text(row[dept_col]),
                    hoc_phan_tien_quyet=clean_text(row[prereq_col]),
                    hoc_phan_hoc_truoc=clean_text(row[prior_col]),
                    hoc_phan_tuong_duong=clean_text(row[equivalent_col]),
                    la_mon_dieu_kien=1 if "(*)" in name_text else 0,
                )
            )
            continue

        if normalized_code == "ten lop hoc phan":
            continue

        if current_option_group_name and as_optional_int(name_text) is not None:
            # The bottom "Ten lop hoc phan" sections repeat elective courses
            # that already appear above with official course codes.
            continue

    if not courses:
        raise ValueError(f"No official course rows found in {excel_path}.")

    duplicate_codes = [code for code, count in Counter(course.ma_mh for course in courses).items() if count > 1]
    if duplicate_codes:
        raise ValueError(f"Duplicate course codes in Excel: {duplicate_codes[:10]}")

    return ParsedCurriculum(
        courses=courses,
        groups=groups,
        no_code_options=no_code_options,
        raw_row_count=len(df),
    )


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE Meta (
    Key TEXT PRIMARY KEY,
    Value TEXT NOT NULL
);

CREATE TABLE Nganh (
    MaNganh TEXT PRIMARY KEY,
    TenNganh TEXT NOT NULL,
    BacDaoTao TEXT,
    HeDaoTao TEXT
);

CREATE TABLE KhoaBoMon (
    MaKhoaBM TEXT PRIMARY KEY,
    TenKhoaBM TEXT NOT NULL
);

CREATE TABLE CTDT (
    MaCTDT TEXT PRIMARY KEY,
    MaNganh TEXT NOT NULL,
    TenCTDT TEXT,
    NamAD INTEGER,
    TongTinChiToiThieu INTEGER,
    NguonDuLieu TEXT,
    FOREIGN KEY (MaNganh) REFERENCES Nganh(MaNganh)
);

CREATE TABLE KhoaHoc (
    MaKhoaHoc TEXT PRIMARY KEY,
    TenKhoaHoc TEXT NOT NULL,
    MaNganh TEXT NOT NULL,
    MaCTDT TEXT NOT NULL,
    NamNhapHoc INTEGER NOT NULL,
    FOREIGN KEY (MaNganh) REFERENCES Nganh(MaNganh),
    FOREIGN KEY (MaCTDT) REFERENCES CTDT(MaCTDT)
);

CREATE TABLE SinhVien (
    MaSV TEXT PRIMARY KEY,
    HoTen TEXT NOT NULL,
    MaKhoaHoc TEXT NOT NULL,
    TrangThai TEXT NOT NULL CHECK (TrangThai IN ('DANG_HOC', 'TAM_NGUNG', 'DA_TOT_NGHIEP')),
    FOREIGN KEY (MaKhoaHoc) REFERENCES KhoaHoc(MaKhoaHoc)
);

CREATE TABLE MonHoc (
    MaMH TEXT PRIMARY KEY,
    TenMH TEXT NOT NULL,
    SoTC INTEGER NOT NULL CHECK (SoTC > 0),
    SoTietLT INTEGER NOT NULL DEFAULT 0 CHECK (SoTietLT >= 0),
    SoTietTH INTEGER NOT NULL DEFAULT 0 CHECK (SoTietTH >= 0),
    MaKhoaBM TEXT NOT NULL,
    HocPhanTienQuyetText TEXT,
    HocPhanHocTruocText TEXT,
    HocPhanTuongDuongText TEXT,
    LaMonDieuKien INTEGER NOT NULL DEFAULT 0 CHECK (LaMonDieuKien IN (0, 1)),
    ExcelRow INTEGER,
    FOREIGN KEY (MaKhoaBM) REFERENCES KhoaBoMon(MaKhoaBM)
);

CREATE TABLE CTDT_NhomTuChon (
    MaCTDT TEXT NOT NULL,
    MaNhomTC TEXT NOT NULL,
    TenNhom TEXT NOT NULL,
    SoTCCanChon INTEGER,
    TongTCCungCap INTEGER,
    HocKyGoiY INTEGER CHECK (HocKyGoiY IS NULL OR HocKyGoiY BETWEEN 1 AND 8),
    MoTa TEXT,
    Nguon TEXT NOT NULL,
    PRIMARY KEY (MaCTDT, MaNhomTC),
    FOREIGN KEY (MaCTDT) REFERENCES CTDT(MaCTDT)
);

CREATE TABLE CTDT_MonHoc (
    MaCTDT TEXT NOT NULL,
    MaMH TEXT NOT NULL,
    LoaiYC TEXT NOT NULL CHECK (LoaiYC IN ('BAT_BUOC', 'TU_CHON')),
    HKGoiY INTEGER CHECK (HKGoiY IS NULL OR HKGoiY BETWEEN 1 AND 8),
    MaNhomTC TEXT,
    TenNhomTC TEXT,
    STTTrongCTDT TEXT,
    ExcelRow INTEGER,
    PRIMARY KEY (MaCTDT, MaMH),
    FOREIGN KEY (MaCTDT) REFERENCES CTDT(MaCTDT),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH),
    FOREIGN KEY (MaCTDT, MaNhomTC) REFERENCES CTDT_NhomTuChon(MaCTDT, MaNhomTC)
);

CREATE TABLE CTDT_LuaChonKhongMa (
    LuaChonID INTEGER PRIMARY KEY,
    MaCTDT TEXT NOT NULL,
    MaNhomTC TEXT NOT NULL,
    TenNhomLuaChon TEXT NOT NULL,
    TenLuaChon TEXT NOT NULL,
    SoTC INTEGER NOT NULL CHECK (SoTC > 0),
    ExcelRow INTEGER,
    FOREIGN KEY (MaCTDT, MaNhomTC) REFERENCES CTDT_NhomTuChon(MaCTDT, MaNhomTC)
);

CREATE TABLE TienQuyet (
    MaMH TEXT NOT NULL,
    MaMHTQ TEXT NOT NULL,
    PRIMARY KEY (MaMH, MaMHTQ),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH),
    FOREIGN KEY (MaMHTQ) REFERENCES MonHoc(MaMH),
    CHECK (MaMH <> MaMHTQ)
);

CREATE TABLE KetQua (
    MaSV TEXT NOT NULL,
    MaMH TEXT NOT NULL,
    NamHoc INTEGER,
    HocKy INTEGER CHECK (HocKy IN (1, 2)),
    KetQua TEXT NOT NULL CHECK (KetQua IN ('DAT', 'KHONG_DAT')),
    PRIMARY KEY (MaSV, MaMH),
    FOREIGN KEY (MaSV) REFERENCES SinhVien(MaSV),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH)
);

CREATE TABLE LopHP (
    MaLHP TEXT PRIMARY KEY,
    MaMH TEXT NOT NULL,
    NamHoc INTEGER NOT NULL,
    HocKy INTEGER NOT NULL CHECK (HocKy IN (1, 2)),
    Nhom TEXT NOT NULL,
    SiSoTD INTEGER NOT NULL CHECK (SiSoTD > 0),
    SiSoDK INTEGER NOT NULL DEFAULT 0 CHECK (SiSoDK >= 0),
    TrangThai TEXT NOT NULL CHECK (TrangThai IN ('MO', 'DONG', 'DAY', 'HUY')),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH),
    UNIQUE (MaMH, NamHoc, HocKy, Nhom)
);

CREATE TABLE DangKy (
    MaSV TEXT NOT NULL,
    MaLHP TEXT NOT NULL,
    TGDK TEXT,
    PRIMARY KEY (MaSV, MaLHP),
    FOREIGN KEY (MaSV) REFERENCES SinhVien(MaSV),
    FOREIGN KEY (MaLHP) REFERENCES LopHP(MaLHP)
);

CREATE TABLE Phong (
    MaPhong TEXT PRIMARY KEY,
    DayNha TEXT
);

CREATE TABLE LichHoc (
    MaLich TEXT PRIMARY KEY,
    MaLHP TEXT NOT NULL,
    MaPhong TEXT NOT NULL,
    Thu INTEGER NOT NULL CHECK (Thu BETWEEN 2 AND 7),
    TietBD INTEGER NOT NULL CHECK (TietBD BETWEEN 1 AND 12),
    TietKT INTEGER NOT NULL CHECK (TietKT BETWEEN 1 AND 12),
    FOREIGN KEY (MaLHP) REFERENCES LopHP(MaLHP),
    FOREIGN KEY (MaPhong) REFERENCES Phong(MaPhong),
    CHECK (TietBD <= TietKT)
);

CREATE TABLE GiangVien (
    MaGV TEXT PRIMARY KEY,
    TenGV TEXT NOT NULL,
    MaKhoaBM TEXT,
    FOREIGN KEY (MaKhoaBM) REFERENCES KhoaBoMon(MaKhoaBM)
);

CREATE TABLE PhanCong (
    MaLHP TEXT NOT NULL,
    MaGV TEXT NOT NULL,
    VaiTro TEXT NOT NULL CHECK (VaiTro IN ('GIANG_VIEN_CHINH', 'TRO_GIANG', 'HUONG_DAN_LAB')),
    PRIMARY KEY (MaLHP, MaGV, VaiTro),
    FOREIGN KEY (MaLHP) REFERENCES LopHP(MaLHP),
    FOREIGN KEY (MaGV) REFERENCES GiangVien(MaGV)
);

CREATE INDEX idx_monhoc_ten ON MonHoc(TenMH);
CREATE INDEX idx_monhoc_khoa ON MonHoc(MaKhoaBM);
CREATE INDEX idx_ctdt_monhoc_hk ON CTDT_MonHoc(HKGoiY);
CREATE INDEX idx_ctdt_monhoc_loai ON CTDT_MonHoc(LoaiYC);
CREATE INDEX idx_ctdt_monhoc_nhom ON CTDT_MonHoc(MaNhomTC);
CREATE INDEX idx_sinhvien_khoahoc ON SinhVien(MaKhoaHoc);
CREATE INDEX idx_lophp_mamh ON LopHP(MaMH);
CREATE INDEX idx_lichhoc_lophp ON LichHoc(MaLHP);
CREATE INDEX idx_dangky_masv ON DangKy(MaSV);
CREATE INDEX idx_dangky_malhp ON DangKy(MaLHP);
CREATE INDEX idx_ketqua_masv ON KetQua(MaSV);
CREATE INDEX idx_ketqua_mamh ON KetQua(MaMH);
"""


EXTRA_VIEWS_SQL = """
DROP VIEW IF EXISTS v_ctdt_hcmute_mon_hoc;
DROP VIEW IF EXISTS v_ctdt_nhom_tu_chon;

CREATE VIEW v_ctdt_hcmute_mon_hoc AS
SELECT
    ctdt_mh.MaCTDT,
    ctdt.TenCTDT,
    n.MaNganh,
    n.TenNganh,
    mh.MaMH,
    mh.TenMH,
    mh.SoTC,
    mh.SoTietLT,
    mh.SoTietTH,
    mh.LaMonDieuKien,
    kb.TenKhoaBM,
    ctdt_mh.LoaiYC,
    ctdt_mh.HKGoiY,
    ctdt_mh.MaNhomTC,
    COALESCE(ntc.TenNhom, ctdt_mh.TenNhomTC) AS TenNhomTC,
    ntc.SoTCCanChon,
    ntc.TongTCCungCap,
    mh.HocPhanTienQuyetText,
    mh.HocPhanHocTruocText,
    mh.HocPhanTuongDuongText,
    ctdt_mh.ExcelRow
FROM CTDT_MonHoc ctdt_mh
JOIN CTDT ctdt ON ctdt_mh.MaCTDT = ctdt.MaCTDT
JOIN Nganh n ON ctdt.MaNganh = n.MaNganh
JOIN MonHoc mh ON ctdt_mh.MaMH = mh.MaMH
JOIN KhoaBoMon kb ON mh.MaKhoaBM = kb.MaKhoaBM
LEFT JOIN CTDT_NhomTuChon ntc
    ON ctdt_mh.MaCTDT = ntc.MaCTDT
   AND ctdt_mh.MaNhomTC = ntc.MaNhomTC;

CREATE VIEW v_ctdt_nhom_tu_chon AS
SELECT
    ntc.MaCTDT,
    ntc.MaNhomTC,
    ntc.TenNhom,
    ntc.SoTCCanChon,
    ntc.TongTCCungCap,
    ntc.HocKyGoiY,
    ntc.MoTa,
    (
        SELECT COUNT(*)
        FROM CTDT_MonHoc ctdt_mh
        WHERE ctdt_mh.MaCTDT = ntc.MaCTDT
          AND ctdt_mh.MaNhomTC = ntc.MaNhomTC
    ) AS SoHocPhanCoMa,
    (
        SELECT COALESCE(SUM(mh.SoTC), 0)
        FROM CTDT_MonHoc ctdt_mh
        JOIN MonHoc mh ON ctdt_mh.MaMH = mh.MaMH
        WHERE ctdt_mh.MaCTDT = ntc.MaCTDT
          AND ctdt_mh.MaNhomTC = ntc.MaNhomTC
    ) AS TongTinChiHocPhanCoMa,
    (
        SELECT COUNT(*)
        FROM CTDT_LuaChonKhongMa lc
        WHERE lc.MaCTDT = ntc.MaCTDT
          AND lc.MaNhomTC = ntc.MaNhomTC
    ) AS SoLuaChonKhongMa
FROM CTDT_NhomTuChon ntc
ORDER BY ntc.MaNhomTC;
"""


SURNAME_WEIGHTS = [
    ("Nguyễn", 0.35),
    ("Trần", 0.12),
    ("Lê", 0.10),
    ("Phạm", 0.08),
    ("Hoàng", 0.04),
    ("Huỳnh", 0.04),
    ("Phan", 0.05),
    ("Vũ", 0.05),
    ("Võ", 0.04),
    ("Đặng", 0.04),
    ("Bùi", 0.04),
    ("Đỗ", 0.03),
    ("Dương", 0.02),
]

MALE_MIDDLES = ["Văn", "Minh", "Quốc", "Hữu", "Gia", "Đức", "Thanh", "Anh", "Tuấn", "Hoàng"]
FEMALE_MIDDLES = ["Thị", "Ngọc", "Bích", "Kiều", "Mỹ", "Phương", "Thanh", "Thùy", "Minh", "Bảo"]
MALE_GIVEN = ["An", "Khang", "Nam", "Huy", "Đức", "Minh", "Phúc", "Đạt", "Long", "Quân", "Tuấn", "Khoa", "Bảo", "Sơn"]
FEMALE_GIVEN = ["Anh", "Linh", "Trang", "Nhi", "Thảo", "Vy", "Hân", "Ngân", "Trâm", "Mỹ", "Tiên", "Quyên", "Thu", "Mai"]

LESSON_BLOCKS = [
    (1, 3),
    (1, 4),
    (1, 5),
    (2, 4),
    (5, 6),
    (7, 8),
    (7, 10),
    (7, 11),
    (8, 10),
    (10, 12),
]
DAYS_OF_WEEK = [2, 3, 4, 5, 6, 7]


def weighted_choice(rng: random.Random, items: Sequence[Tuple[str, float]]) -> str:
    labels = [item[0] for item in items]
    weights = [item[1] for item in items]
    return rng.choices(labels, weights=weights, k=1)[0]


def fake_name(rng: random.Random) -> str:
    surname = weighted_choice(rng, SURNAME_WEIGHTS)
    is_female = rng.random() < 0.48
    middle = rng.choice(FEMALE_MIDDLES if is_female else MALE_MIDDLES)
    given = rng.choice(FEMALE_GIVEN if is_female else MALE_GIVEN)
    if rng.random() < 0.07:
        extra = rng.choice(FEMALE_GIVEN if is_female else MALE_GIVEN)
        if extra != given:
            given = f"{given} {extra}"
    return f"{surname} {middle} {given}"


def make_student_id(cohort_year: int, index: int) -> str:
    if index > 999:
        raise ValueError("Student index exceeds 3-digit suffix.")
    return f"{str(cohort_year)[-2:]}1{MA_NGANH_CNTT}{index:03d}"


def department_id(name: str) -> str:
    slug = strip_accents(name).upper()
    slug = re.sub(r"[^A-Z0-9]+", "_", slug).strip("_")
    return slug[:40] or "UNKNOWN"


def insert_catalog(conn: sqlite3.Connection, parsed: ParsedCurriculum, excel_path: Path) -> None:
    conn.execute(
        """
        INSERT INTO Nganh (MaNganh, TenNganh, BacDaoTao, HeDaoTao)
        VALUES (?, ?, ?, ?)
        """,
        (MA_NGANH_CNTT, "Công nghệ thông tin", "Đại học", "Chính quy"),
    )
    min_elective_credits = sum(
        group.so_tc_can_chon or 0
        for group in parsed.groups.values()
        if group.ma_nhom_tc.startswith("NHOM")
    )
    required_credits = sum(course.so_tc for course in parsed.courses if course.loai_yc == "BAT_BUOC")
    conn.execute(
        """
        INSERT INTO CTDT
            (MaCTDT, MaNganh, TenCTDT, NamAD, TongTinChiToiThieu, NguonDuLieu)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            MA_CTDT,
            MA_NGANH_CNTT,
            "Chương trình đào tạo HCMUTE - Công nghệ thông tin",
            2023,
            required_credits + min_elective_credits,
            str(excel_path),
        ),
    )

    departments = sorted({course.khoa_bo_mon for course in parsed.courses})
    for name in departments:
        conn.execute(
            "INSERT INTO KhoaBoMon (MaKhoaBM, TenKhoaBM) VALUES (?, ?)",
            (department_id(name), name),
        )

    for group in sorted(parsed.groups.values(), key=lambda item: item.ma_nhom_tc):
        conn.execute(
            """
            INSERT INTO CTDT_NhomTuChon
                (MaCTDT, MaNhomTC, TenNhom, SoTCCanChon, TongTCCungCap, HocKyGoiY, MoTa, Nguon)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                MA_CTDT,
                group.ma_nhom_tc,
                group.ten_nhom,
                group.so_tc_can_chon,
                group.tong_tc_cung_cap,
                group.hoc_ky_goi_y,
                group.mo_ta,
                group.nguon,
            ),
        )

    for course in parsed.courses:
        conn.execute(
            """
            INSERT INTO MonHoc
                (
                    MaMH, TenMH, SoTC, SoTietLT, SoTietTH, MaKhoaBM,
                    HocPhanTienQuyetText, HocPhanHocTruocText, HocPhanTuongDuongText,
                    LaMonDieuKien, ExcelRow
                )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                course.ma_mh,
                course.ten_mh,
                course.so_tc,
                course.so_tiet_lt,
                course.so_tiet_th,
                department_id(course.khoa_bo_mon),
                course.hoc_phan_tien_quyet,
                course.hoc_phan_hoc_truoc,
                course.hoc_phan_tuong_duong,
                course.la_mon_dieu_kien,
                course.excel_row,
            ),
        )
        conn.execute(
            """
            INSERT INTO CTDT_MonHoc
                (MaCTDT, MaMH, LoaiYC, HKGoiY, MaNhomTC, TenNhomTC, STTTrongCTDT, ExcelRow)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                MA_CTDT,
                course.ma_mh,
                course.loai_yc,
                course.hk_goi_y,
                course.ma_nhom_tc,
                course.ten_nhom_tc,
                course.stt,
                course.excel_row,
            ),
        )

    for idx, option in enumerate(parsed.no_code_options, start=1):
        conn.execute(
            """
            INSERT INTO CTDT_LuaChonKhongMa
                (LuaChonID, MaCTDT, MaNhomTC, TenNhomLuaChon, TenLuaChon, SoTC, ExcelRow)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                idx,
                MA_CTDT,
                option.ma_nhom_tc,
                option.ten_nhom_lua_chon,
                option.ten_lua_chon,
                option.so_tc,
                option.excel_row,
            ),
        )

    known_codes = {course.ma_mh for course in parsed.courses}
    for course in parsed.courses:
        for text in [course.hoc_phan_tien_quyet, course.hoc_phan_hoc_truoc]:
            for prereq_code in COURSE_CODE_IN_TEXT_RE.findall(text or ""):
                if prereq_code in known_codes and prereq_code != course.ma_mh:
                    conn.execute(
                        "INSERT OR IGNORE INTO TienQuyet (MaMH, MaMHTQ) VALUES (?, ?)",
                        (course.ma_mh, prereq_code),
                    )

    conn.commit()


def insert_cohorts_and_students(conn: sqlite3.Connection, rng: random.Random) -> None:
    cohorts = {
        2022: 260,
        2023: 520,
        2024: 520,
        2025: 420,
    }
    for year in cohorts:
        ma_khoa_hoc = f"K{str(year)[-2:]}_CNTT"
        conn.execute(
            """
            INSERT INTO KhoaHoc (MaKhoaHoc, TenKhoaHoc, MaNganh, MaCTDT, NamNhapHoc)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ma_khoa_hoc, f"CNTT K{str(year)[-2:]}", MA_NGANH_CNTT, MA_CTDT, year),
        )
        for index in range(1, cohorts[year] + 1):
            if year <= 2022:
                status = weighted_choice(rng, [("DANG_HOC", 0.90), ("TAM_NGUNG", 0.04), ("DA_TOT_NGHIEP", 0.06)])
            else:
                status = weighted_choice(rng, [("DANG_HOC", 0.96), ("TAM_NGUNG", 0.04)])
            conn.execute(
                """
                INSERT INTO SinhVien (MaSV, HoTen, MaKhoaHoc, TrangThai)
                VALUES (?, ?, ?, ?)
                """,
                (make_student_id(year, index), fake_name(rng), ma_khoa_hoc, status),
            )
    conn.commit()


def insert_rooms(conn: sqlite3.Connection) -> List[str]:
    rooms: List[str] = []
    for building in ["A1", "A2", "A3", "A4", "A5"]:
        for floor in range(1, 6):
            for room in range(1, 7):
                ma_phong = f"{building}-{floor}{room:02d}"
                rooms.append(ma_phong)
                conn.execute("INSERT INTO Phong (MaPhong, DayNha) VALUES (?, ?)", (ma_phong, building))
    for building in ["B1", "C1", "F1"]:
        for floor in range(1, 8):
            for room in range(1, 8):
                ma_phong = f"{building}-{floor}{room:02d}"
                rooms.append(ma_phong)
                conn.execute("INSERT INTO Phong (MaPhong, DayNha) VALUES (?, ?)", (ma_phong, building))
    conn.commit()
    return rooms


def insert_instructors(conn: sqlite3.Connection, rng: random.Random) -> Dict[str, List[str]]:
    instructors_by_dept: Dict[str, List[str]] = defaultdict(list)
    departments = conn.execute("SELECT MaKhoaBM, TenKhoaBM FROM KhoaBoMon ORDER BY TenKhoaBM").fetchall()
    instructor_index = 1
    for ma_khoa_bm, _ten_khoa_bm in departments:
        count = 8 if ma_khoa_bm == department_id("Công nghệ Thông tin") else 4
        for _ in range(count):
            ma_gv = f"GV{instructor_index:03d}"
            instructor_index += 1
            conn.execute(
                "INSERT INTO GiangVien (MaGV, TenGV, MaKhoaBM) VALUES (?, ?, ?)",
                (ma_gv, fake_name(rng), ma_khoa_bm),
            )
            instructors_by_dept[ma_khoa_bm].append(ma_gv)
    conn.commit()
    return instructors_by_dept


def course_semesters(hk_goi_y: Optional[int]) -> List[int]:
    if hk_goi_y is None:
        return [1, 2]
    return [1 if hk_goi_y % 2 == 1 else 2]


def section_group_count(loai_yc: str, dept_name: str, credits: int, hk_goi_y: Optional[int]) -> int:
    if hk_goi_y is None and loai_yc == "TU_CHON":
        return 1
    if "Công nghệ Thông tin" in dept_name and credits >= 3:
        return 3 if loai_yc == "BAT_BUOC" else 2
    if loai_yc == "BAT_BUOC":
        return 2
    return 1


def insert_offerings(conn: sqlite3.Connection, rng: random.Random) -> List[str]:
    rows = conn.execute(
        """
        SELECT mh.MaMH, mh.SoTC, mh.SoTietTH, mh.MaKhoaBM, kb.TenKhoaBM,
               ctdt_mh.LoaiYC, ctdt_mh.HKGoiY
        FROM MonHoc mh
        JOIN CTDT_MonHoc ctdt_mh ON mh.MaMH = ctdt_mh.MaMH
        JOIN KhoaBoMon kb ON mh.MaKhoaBM = kb.MaKhoaBM
        ORDER BY COALESCE(ctdt_mh.HKGoiY, 99), ctdt_mh.LoaiYC, mh.MaMH
        """
    ).fetchall()
    offering_ids: List[str] = []
    counter = 0
    for ma_mh, so_tc, so_tiet_th, _ma_khoa_bm, ten_khoa_bm, loai_yc, hk_goi_y in rows:
        for hoc_ky in course_semesters(hk_goi_y):
            n_groups = section_group_count(loai_yc, ten_khoa_bm, int(so_tc), hk_goi_y)
            for group_no in range(1, n_groups + 1):
                counter += 1
                ma_lhp = f"LHP{ACADEMIC_YEAR}{hoc_ky}{counter:04d}"
                capacity = DEFAULT_CAPACITY
                if so_tiet_th and so_tiet_th > 0:
                    capacity = 35
                if "Giáo dục thể chất" in ten_khoa_bm or "GDQP" in ma_mh:
                    capacity = 55
                status = weighted_choice(rng, [("MO", 0.68), ("DAY", 0.15), ("DONG", 0.12), ("HUY", 0.05)])
                conn.execute(
                    """
                    INSERT INTO LopHP (MaLHP, MaMH, NamHoc, HocKy, Nhom, SiSoTD, SiSoDK, TrangThai)
                    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
                    """,
                    (ma_lhp, ma_mh, ACADEMIC_YEAR, hoc_ky, f"{group_no:02d}", capacity, status),
                )
                offering_ids.append(ma_lhp)
    conn.commit()
    return offering_ids


def overlaps(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return start_a <= end_b and end_a >= start_b


def schedules_conflict(
    schedules_a: Sequence[Tuple[int, int, int]],
    schedules_b: Sequence[Tuple[int, int, int]],
) -> bool:
    for day_a, start_a, end_a in schedules_a:
        for day_b, start_b, end_b in schedules_b:
            if day_a == day_b and overlaps(start_a, end_a, start_b, end_b):
                return True
    return False


def insert_schedules(
    conn: sqlite3.Connection,
    rng: random.Random,
    offering_ids: Sequence[str],
    rooms: Sequence[str],
) -> Dict[str, List[Tuple[int, int, int]]]:
    offering_info = {
        row[0]: {"HocKy": row[1], "SoTC": row[2], "SoTietTH": row[3]}
        for row in conn.execute(
            """
            SELECT lhp.MaLHP, lhp.HocKy, mh.SoTC, mh.SoTietTH
            FROM LopHP lhp
            JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
            """
        )
    }
    room_schedules: Dict[Tuple[str, int], List[Tuple[int, int, int]]] = defaultdict(list)
    offering_schedules: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)
    schedule_id = 0

    for ma_lhp in offering_ids:
        info = offering_info[ma_lhp]
        n_sessions = 2 if info["SoTC"] >= 3 and info["SoTietTH"] > 0 else 1
        used_days = set()
        for _ in range(n_sessions):
            assigned = False
            for _attempt in range(500):
                thu = rng.choice(DAYS_OF_WEEK)
                if thu in used_days and n_sessions > 1:
                    continue
                tiet_bd, tiet_kt = rng.choice(LESSON_BLOCKS)
                room = rng.choice(rooms)
                key = (room, info["HocKy"])
                conflict = any(
                    day == thu and overlaps(tiet_bd, tiet_kt, start, end)
                    for day, start, end in room_schedules[key]
                )
                if conflict:
                    continue
                schedule_id += 1
                ma_lich = f"LICH{schedule_id:05d}"
                conn.execute(
                    """
                    INSERT INTO LichHoc (MaLich, MaLHP, MaPhong, Thu, TietBD, TietKT)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ma_lich, ma_lhp, room, thu, tiet_bd, tiet_kt),
                )
                room_schedules[key].append((thu, tiet_bd, tiet_kt))
                offering_schedules[ma_lhp].append((thu, tiet_bd, tiet_kt))
                used_days.add(thu)
                assigned = True
                break
            if not assigned:
                raise RuntimeError(f"Cannot assign schedule for {ma_lhp}")
    conn.commit()
    return offering_schedules


def insert_teaching_assignments(
    conn: sqlite3.Connection,
    rng: random.Random,
    offering_ids: Sequence[str],
    instructors_by_dept: Dict[str, List[str]],
) -> None:
    dept_by_offering = {
        row[0]: row[1]
        for row in conn.execute(
            """
            SELECT lhp.MaLHP, mh.MaKhoaBM
            FROM LopHP lhp
            JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
            """
        )
    }
    all_instructors = [ma_gv for values in instructors_by_dept.values() for ma_gv in values]
    for ma_lhp in offering_ids:
        choices = instructors_by_dept.get(dept_by_offering[ma_lhp]) or all_instructors
        conn.execute(
            """
            INSERT INTO PhanCong (MaLHP, MaGV, VaiTro)
            VALUES (?, ?, 'GIANG_VIEN_CHINH')
            """,
            (ma_lhp, rng.choice(choices)),
        )
    conn.commit()


def completed_curriculum_semester(cohort_year: int) -> int:
    if cohort_year <= 2022:
        return 8
    if cohort_year == 2023:
        return 6
    if cohort_year == 2024:
        return 4
    return 2


def insert_results(conn: sqlite3.Connection, rng: random.Random) -> None:
    courses = conn.execute(
        """
        SELECT ctdt_mh.MaMH, ctdt_mh.LoaiYC, ctdt_mh.HKGoiY
        FROM CTDT_MonHoc ctdt_mh
        """
    ).fetchall()
    students = conn.execute(
        """
        SELECT sv.MaSV, kh.NamNhapHoc
        FROM SinhVien sv
        JOIN KhoaHoc kh ON sv.MaKhoaHoc = kh.MaKhoaHoc
        """
    ).fetchall()
    for ma_sv, nam_nhap_hoc in students:
        completed_sem = completed_curriculum_semester(int(nam_nhap_hoc))
        for ma_mh, loai_yc, hk_goi_y in courses:
            if hk_goi_y is None:
                attempt_prob = 0.18 if int(nam_nhap_hoc) <= 2023 else 0.08
            elif int(hk_goi_y) <= completed_sem:
                attempt_prob = 0.92 if loai_yc == "BAT_BUOC" else 0.38
            else:
                attempt_prob = 0.03
            if rng.random() >= attempt_prob:
                continue
            if hk_goi_y is None:
                nam_hoc = min(ACADEMIC_YEAR - 1, int(nam_nhap_hoc) + rng.randint(1, 3))
                hoc_ky = rng.choice([1, 2])
            else:
                nam_hoc = int(nam_nhap_hoc) + max(0, (int(hk_goi_y) - 1) // 2)
                hoc_ky = 1 if int(hk_goi_y) % 2 == 1 else 2
            ket_qua = weighted_choice(rng, [("DAT", 0.86), ("KHONG_DAT", 0.14)])
            conn.execute(
                """
                INSERT OR REPLACE INTO KetQua (MaSV, MaMH, NamHoc, HocKy, KetQua)
                VALUES (?, ?, ?, ?, ?)
                """,
                (ma_sv, ma_mh, nam_hoc, hoc_ky, ket_qua),
            )
    conn.commit()


def offering_target_enrollment(rng: random.Random, status: str, capacity: int) -> int:
    if status == "DAY":
        return capacity
    if status == "MO":
        return rng.randint(max(12, capacity // 3), max(13, capacity - 5))
    return 0


def insert_registrations(
    conn: sqlite3.Connection,
    rng: random.Random,
    offering_schedules: Dict[str, List[Tuple[int, int, int]]],
) -> None:
    student_rows = conn.execute(
        """
        SELECT sv.MaSV
        FROM SinhVien sv
        WHERE sv.TrangThai = 'DANG_HOC'
        """
    ).fetchall()
    students = [row[0] for row in student_rows]
    course_credits = {row[0]: row[1] for row in conn.execute("SELECT MaMH, SoTC FROM MonHoc")}
    offerings = conn.execute(
        """
        SELECT MaLHP, MaMH, HocKy, TrangThai, SiSoTD
        FROM LopHP
        ORDER BY RANDOM()
        """
    ).fetchall()
    student_sem_schedules: Dict[Tuple[str, int], List[Tuple[int, int, int]]] = defaultdict(list)
    student_sem_credits: Dict[Tuple[str, int], int] = defaultdict(int)
    student_sem_courses: Dict[Tuple[str, int], set] = defaultdict(set)
    registration_time_base = datetime(ACADEMIC_YEAR, 1, 4, 8, 0, 0)

    for ma_lhp, ma_mh, hoc_ky, trang_thai, capacity in offerings:
        target = offering_target_enrollment(rng, trang_thai, int(capacity))
        if target <= 0:
            continue
        candidates = list(students)
        rng.shuffle(candidates)
        inserted = 0
        credits = int(course_credits[ma_mh])
        sched = offering_schedules.get(ma_lhp, [])
        for ma_sv in candidates:
            key = (ma_sv, int(hoc_ky))
            if ma_mh in student_sem_courses[key]:
                continue
            if student_sem_credits[key] + credits > MAX_CREDITS_PER_SEMESTER:
                continue
            if schedules_conflict(student_sem_schedules[key], sched):
                continue
            tgdk = registration_time_base + timedelta(
                days=rng.randint(0, 50),
                minutes=rng.randint(0, 720),
            )
            conn.execute(
                """
                INSERT OR IGNORE INTO DangKy (MaSV, MaLHP, TGDK)
                VALUES (?, ?, ?)
                """,
                (ma_sv, ma_lhp, tgdk.isoformat(sep=" ")),
            )
            student_sem_schedules[key].extend(sched)
            student_sem_credits[key] += credits
            student_sem_courses[key].add(ma_mh)
            inserted += 1
            if inserted >= target:
                break
        if trang_thai == "DAY" and inserted < capacity:
            conn.execute("UPDATE LopHP SET TrangThai = 'MO' WHERE MaLHP = ?", (ma_lhp,))

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
    conn.commit()


def apply_views(conn: sqlite3.Connection, views_path: Path) -> None:
    conn.executescript(views_path.read_text(encoding="utf-8"))
    conn.executescript(EXTRA_VIEWS_SQL)
    conn.commit()


def insert_meta(conn: sqlite3.Connection, parsed: ParsedCurriculum, excel_path: Path, seed: int) -> None:
    meta = {
        "source_excel": str(excel_path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "builder": "scripts/build_ctdt_db.py",
        "random_seed": str(seed),
        "raw_excel_rows": str(parsed.raw_row_count),
        "official_course_rows": str(len(parsed.courses)),
        "elective_group_count": str(len(parsed.groups)),
        "no_code_option_count": str(len(parsed.no_code_options)),
    }
    for key, value in meta.items():
        conn.execute("INSERT INTO Meta (Key, Value) VALUES (?, ?)", (key, value))
    conn.commit()


def scalar(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def validate_database(conn: sqlite3.Connection, parsed: ParsedCurriculum) -> List[str]:
    errors: List[str] = []
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        errors.append(f"Foreign key errors: {fk_errors[:5]}")

    expected_courses = len(parsed.courses)
    actual_courses = scalar(conn, "SELECT COUNT(*) FROM MonHoc")
    actual_ctdt_courses = scalar(conn, "SELECT COUNT(*) FROM CTDT_MonHoc")
    if actual_courses != expected_courses or actual_ctdt_courses != expected_courses:
        errors.append(
            f"Course count mismatch: expected={expected_courses}, MonHoc={actual_courses}, CTDT_MonHoc={actual_ctdt_courses}"
        )

    expected_options = len(parsed.no_code_options)
    actual_options = scalar(conn, "SELECT COUNT(*) FROM CTDT_LuaChonKhongMa")
    if actual_options != expected_options:
        errors.append(f"No-code option mismatch: expected={expected_options}, actual={actual_options}")

    mismatches = conn.execute(
        """
        SELECT lhp.MaLHP, lhp.SiSoDK, COUNT(dk.MaSV) AS ThucTe
        FROM LopHP lhp
        LEFT JOIN DangKy dk ON lhp.MaLHP = dk.MaLHP
        GROUP BY lhp.MaLHP
        HAVING lhp.SiSoDK <> COUNT(dk.MaSV)
        """
    ).fetchall()
    if mismatches:
        errors.append(f"SiSoDK mismatches: {mismatches[:5]}")

    invalid_status_regs = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        WHERE lhp.TrangThai IN ('DONG', 'HUY')
        """,
    )
    if invalid_status_regs:
        errors.append(f"Registrations in DONG/HUY offerings: {invalid_status_regs}")

    no_main_lecturer = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM LopHP lhp
        WHERE NOT EXISTS (
            SELECT 1
            FROM PhanCong pc
            WHERE pc.MaLHP = lhp.MaLHP
              AND pc.VaiTro = 'GIANG_VIEN_CHINH'
        )
        """,
    )
    if no_main_lecturer:
        errors.append(f"Offerings without GIANG_VIEN_CHINH: {no_main_lecturer}")

    student_conflicts = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM DangKy dk1
        JOIN DangKy dk2
          ON dk1.MaSV = dk2.MaSV
         AND dk1.MaLHP < dk2.MaLHP
        JOIN LopHP hp1 ON dk1.MaLHP = hp1.MaLHP
        JOIN LopHP hp2 ON dk2.MaLHP = hp2.MaLHP
        JOIN LichHoc l1 ON dk1.MaLHP = l1.MaLHP
        JOIN LichHoc l2 ON dk2.MaLHP = l2.MaLHP
        WHERE hp1.NamHoc = hp2.NamHoc
          AND hp1.HocKy = hp2.HocKy
          AND l1.Thu = l2.Thu
          AND l1.TietBD <= l2.TietKT
          AND l1.TietKT >= l2.TietBD
        """,
    )
    if student_conflicts:
        errors.append(f"Student-level schedule conflicts: {student_conflicts}")

    room_conflicts = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM LichHoc l1
        JOIN LichHoc l2
          ON l1.MaPhong = l2.MaPhong
         AND l1.MaLich < l2.MaLich
        JOIN LopHP hp1 ON l1.MaLHP = hp1.MaLHP
        JOIN LopHP hp2 ON l2.MaLHP = hp2.MaLHP
        WHERE hp1.NamHoc = hp2.NamHoc
          AND hp1.HocKy = hp2.HocKy
          AND l1.Thu = l2.Thu
          AND l1.TietBD <= l2.TietKT
          AND l1.TietKT >= l2.TietBD
        """,
    )
    if room_conflicts:
        errors.append(f"Room-time conflicts: {room_conflicts}")

    return errors


def build_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    tables = [
        "Nganh",
        "KhoaBoMon",
        "CTDT",
        "KhoaHoc",
        "SinhVien",
        "MonHoc",
        "CTDT_MonHoc",
        "CTDT_NhomTuChon",
        "TienQuyet",
        "KetQua",
        "LopHP",
        "DangKy",
        "Phong",
        "LichHoc",
        "GiangVien",
        "PhanCong",
    ]
    summary: Dict[str, Any] = {
        "row_counts": {table: scalar(conn, f"SELECT COUNT(*) FROM {table}") for table in tables},
        "courses_by_semester": [
            dict(row)
            for row in conn.execute(
                """
                SELECT COALESCE(CAST(HKGoiY AS TEXT), 'CHUA_PHAN') AS HocKy, COUNT(*) AS SoMon
                FROM CTDT_MonHoc
                GROUP BY COALESCE(CAST(HKGoiY AS TEXT), 'CHUA_PHAN')
                ORDER BY CASE WHEN HKGoiY IS NULL THEN 0 ELSE HKGoiY END
                """
            )
        ],
        "courses_by_requirement": [
            dict(row)
            for row in conn.execute(
                """
                SELECT LoaiYC, COUNT(*) AS SoMon, SUM(mh.SoTC) AS TongTinChiNeuHocTatCa
                FROM CTDT_MonHoc ctdt_mh
                JOIN MonHoc mh ON ctdt_mh.MaMH = mh.MaMH
                GROUP BY LoaiYC
                ORDER BY LoaiYC
                """
            )
        ],
        "elective_groups": [
            dict(row)
            for row in conn.execute(
                """
                SELECT MaNhomTC, TenNhom, SoTCCanChon, TongTCCungCap, SoHocPhanCoMa, SoLuaChonKhongMa
                FROM v_ctdt_nhom_tu_chon
                ORDER BY MaNhomTC
                """
            )
        ],
        "offering_status": [
            dict(row)
            for row in conn.execute(
                "SELECT TrangThai, COUNT(*) AS SoLop FROM LopHP GROUP BY TrangThai ORDER BY TrangThai"
            )
        ],
        "sample_courses": [
            dict(row)
            for row in conn.execute(
                """
                SELECT MaMH, TenMH, SoTC, SoTietLT, SoTietTH, TenKhoaBM, LoaiYC, HKGoiY, MaNhomTC
                FROM v_ctdt_hcmute_mon_hoc
                ORDER BY COALESCE(HKGoiY, 0), LoaiYC, MaMH
                LIMIT 12
                """
            )
        ],
    }
    return summary


def create_database(
    excel_path: Path,
    output_path: Path,
    views_path: Path,
    seed: int,
) -> Dict[str, Any]:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {output_path}")
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")
    if not views_path.exists():
        raise FileNotFoundError(f"views.sql not found: {views_path}")

    parsed = parse_curriculum(excel_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    rng = random.Random(seed)
    conn = sqlite3.connect(temp_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.executescript(SCHEMA_SQL)
        insert_meta(conn, parsed, excel_path, seed)
        insert_catalog(conn, parsed, excel_path)
        insert_cohorts_and_students(conn, rng)
        rooms = insert_rooms(conn)
        instructors_by_dept = insert_instructors(conn, rng)
        offering_ids = insert_offerings(conn, rng)
        offering_schedules = insert_schedules(conn, rng, offering_ids, rooms)
        insert_teaching_assignments(conn, rng, offering_ids, instructors_by_dept)
        insert_results(conn, rng)
        insert_registrations(conn, rng, offering_schedules)
        apply_views(conn, views_path)

        errors = validate_database(conn, parsed)
        if errors:
            raise RuntimeError("Database validation failed:\n" + "\n".join(f"- {error}" for error in errors))
        summary = build_summary(conn)
        conn.commit()
    finally:
        conn.close()

    temp_path.replace(output_path)
    return summary


def print_summary(summary: Dict[str, Any], output_path: Path) -> None:
    print(f"Database generated: {output_path}")
    print("\n=== Row counts ===")
    for table, count in summary["row_counts"].items():
        print(f"{table:24s} {count}")

    print("\n=== Courses by semester ===")
    for row in summary["courses_by_semester"]:
        print(f"{row['HocKy']:10s} {row['SoMon']}")

    print("\n=== Courses by requirement ===")
    for row in summary["courses_by_requirement"]:
        print(f"{row['LoaiYC']:10s} {row['SoMon']} courses | {row['TongTinChiNeuHocTatCa']} credits if all counted")

    print("\n=== Elective groups ===")
    for row in summary["elective_groups"]:
        print(
            f"{row['MaNhomTC']:22s} choose={row['SoTCCanChon']} "
            f"offered={row['TongTCCungCap']} coded={row['SoHocPhanCoMa']} no_code={row['SoLuaChonKhongMa']}"
        )

    print("\n=== Offering status ===")
    for row in summary["offering_status"]:
        print(f"{row['TrangThai']:5s} {row['SoLop']}")

    print("\n=== Sample courses ===")
    for row in summary["sample_courses"]:
        print(json.dumps(row, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a HCMUTE CTDT SQLite database without overwriting the old DB.")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--views", type=Path, default=DEFAULT_VIEWS_PATH)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    args = parser.parse_args()

    summary = create_database(
        excel_path=args.excel,
        output_path=args.output,
        views_path=args.views,
        seed=args.seed,
    )
    print_summary(summary, args.output)


if __name__ == "__main__":
    main()
