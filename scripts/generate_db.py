from __future__ import annotations

import argparse
import random
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# cau hinh

DEFAULT_SEED = 42
DEFAULT_VIEWS_PATH = Path(__file__).resolve().with_name("views.sql")

ACADEMIC_YEAR = 2026
ADMISSION_YEAR = 2023
COHORT_SHORT = "23"
EDU_SYSTEM_CODE = "1"  # 1 = he dai hoc chinh quy

N_STUDENTS = 2000
N_COURSES = 40
N_OFFERINGS_TARGET = 240
N_LECTURERS = 30

MAX_CREDITS_PER_SEMESTER = 28
CLASS_CAPACITY = 40

# dang ky khong co cot trang thai
# co dong la da dang ky, khong co dong la chua dang ky

MAJORS = [
    # ma nganh, ten tat, ten day du, ti le
    ("10", "CNTT", "Cong nghe thong tin", 0.40),
    ("19", "KMT", "Cong nghe ky thuat may tinh", 0.20),
    ("46", "CDT", "Cong nghe ky thuat co dien tu", 0.15),
    ("51", "DTD", "Cong nghe ky thuat dieu khien va tu dong hoa", 0.15),
    ("41", "DVT", "Cong nghe ky thuat dien tu, truyen thong", 0.10),
]

STUDENT_STATUS_WEIGHTS = [
    ("DANG_HOC", 0.97),
    ("TAM_NGUNG", 0.03),
]

OFFERING_STATUS_WEIGHTS = [
    ("MO", 0.60),
    ("DAY", 0.20),
    ("DONG", 0.15),
    ("HUY", 0.05),
]

RESULT_WEIGHTS = [
    ("DAT", 0.85),
    ("KHONG_DAT", 0.15),
]

REQUIREMENT_WEIGHTS = [
    ("BAT_BUOC", 0.47),
    ("TU_CHON", 0.53),
]

# cac block tiet hay gap
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
]

DAYS_OF_WEEK = [2, 3, 4, 5, 6, 7]  # thu 2 -> thu 7

# bang gio tham khao, khong luu vao db
PERIOD_TIMES = {
    1: "07:30-08:15",
    2: "08:15-09:00",
    3: "09:00-09:45",
    4: "10:00-10:45",
    5: "10:45-11:30",
    6: "11:30-12:15",
    7: "12:45-13:30",
    8: "13:30-14:15",
    9: "14:15-15:00",
    10: "15:15-16:00",
    11: "16:00-16:45",
    12: "16:45-17:30",
}


# danh sach mon hoc
# ma mon theo dang 4 chu cai + so + E

COURSES = [
    # ma mon, ten mon, so tin chi, hk goi y, nhom
    ("INPR130185E", "Introduction to Programming", 3, 1, "common"),
    ("CALC140101E", "Calculus", 4, 1, "common"),
    ("LIAL140102E", "Linear Algebra", 4, 1, "common"),
    ("ACEN140103E", "Academic English", 4, 1, "common"),
    ("PHYS140104E", "Engineering Physics", 4, 2, "common"),
    ("DASA230179E", "Data Structures and Algorithms", 3, 2, "common"),
    ("OOPR230279E", "Object-Oriented Programming", 3, 2, "common"),
    ("PROS220301E", "Probability and Statistics", 2, 3, "common"),
    ("DISM230302E", "Discrete Mathematics", 3, 3, "common"),
    ("DBSY230184E", "Database Systems", 3, 3, "it"),
    ("COAR230280E", "Computer Architecture", 3, 3, "it"),
    ("OSYS330281E", "Operating Systems", 3, 4, "it"),
    ("NECO330282E", "Computer Networks", 3, 4, "it"),
    ("DBMS330284E", "Database Management Systems", 3, 4, "it"),
    ("WEPR330383E", "Web Programming", 3, 4, "it"),
    ("SOEN330384E", "Software Engineering", 3, 5, "it"),
    ("ARIN330585E", "Artificial Intelligence", 3, 5, "ai"),
    ("INDS331085E", "Introduction to Data Science", 3, 5, "ai"),
    ("MALE431085E", "Machine Learning", 3, 6, "ai"),
    ("NLPR431585E", "Natural Language Processing", 3, 6, "ai"),
    ("DIPR430685E", "Digital Image Processing", 3, 6, "ai"),
    ("MOPR331279E", "Mobile Programming", 3, 6, "it"),
    ("CYSE430387E", "Cybersecurity", 3, 6, "it"),
    ("CLCO430986E", "Cloud Computing", 3, 7, "it"),
    ("DAEN431188E", "Data Engineering", 3, 7, "ai"),
    ("GRPR421201E", "Graduation Project", 2, 8, "project"),

    ("CIRC130401E", "Electric Circuits", 3, 2, "electronics"),
    ("ELDE230402E", "Electronic Devices", 3, 3, "electronics"),
    ("DIEL330403E", "Digital Electronics", 3, 4, "electronics"),
    ("SIGN330404E", "Signals and Systems", 3, 4, "electronics"),
    ("COMM430405E", "Communication Systems", 3, 5, "electronics"),
    ("EMBE330406E", "Embedded Systems", 3, 5, "electronics"),
    ("IOTP431486E", "IoT Programming", 3, 6, "electronics"),

    ("MECH130501E", "Engineering Mechanics", 3, 2, "mechatronics"),
    ("CAME230502E", "CAD/CAM Engineering", 3, 3, "mechatronics"),
    ("ROBO330503E", "Robotics", 3, 5, "mechatronics"),
    ("MACH330504E", "Machine Elements", 3, 4, "mechatronics"),

    ("CONT330601E", "Control Theory", 3, 4, "automation"),
    ("PLCS330602E", "PLC Systems", 3, 5, "automation"),
    ("AUTO430603E", "Automation Systems", 3, 6, "automation"),
]


# ma nganh -> nhom mon phu hop
MAJOR_GROUPS = {
    "10": {"common", "it", "ai", "project"},
    "19": {"common", "it", "electronics", "project"},
    "46": {"common", "mechatronics", "electronics", "automation", "project"},
    "51": {"common", "automation", "electronics", "it", "project"},
    "41": {"common", "electronics", "it", "project"},
}

# tien quyet khai bao tay, moi mon toi da 1 mon
PREREQUISITES = {
    "DASA230179E": "INPR130185E",
    "OOPR230279E": "INPR130185E",
    "DBSY230184E": "INPR130185E",
    "DBMS330284E": "DBSY230184E",
    "WEPR330383E": "OOPR230279E",
    "MOPR331279E": "OOPR230279E",
    "SOEN330384E": "OOPR230279E",
    "ARIN330585E": "DASA230179E",
    "INDS331085E": "PROS220301E",
    "MALE431085E": "PROS220301E",
    "NLPR431585E": "MALE431085E",
    "DIPR430685E": "MALE431085E",
    "DAEN431188E": "DBMS330284E",
    "CYSE430387E": "NECO330282E",
    "CLCO430986E": "OSYS330281E",
    "ELDE230402E": "CIRC130401E",
    "DIEL330403E": "ELDE230402E",
    "SIGN330404E": "DIEL330403E",
    "COMM430405E": "SIGN330404E",
    "EMBE330406E": "DIEL330403E",
    "IOTP431486E": "EMBE330406E",
    "CAME230502E": "MECH130501E",
    "MACH330504E": "MECH130501E",
    "ROBO330503E": "CONT330601E",
    "PLCS330602E": "CONT330601E",
    "AUTO430603E": "PLCS330602E",
}


# sinh ten gia lap

SURNAME_WEIGHTS = [
    ("Nguyen", 0.35),
    ("Tran", 0.12),
    ("Le", 0.10),
    ("Pham", 0.08),
    ("Hoang", 0.03),
    ("Huynh", 0.03),
    ("Phan", 0.05),
    ("Vu", 0.05),
    ("Vo", 0.04),
    ("Dang", 0.04),
    ("Bui", 0.04),
    ("Do", 0.04),
    ("Duong", 0.03),
]

MALE_MIDDLES = ["Van", "Minh", "Quoc", "Huu", "Gia", "Duc", "Thanh", "Anh", "Tuan", "Hoang"]
FEMALE_MIDDLES = ["Thi", "Ngoc", "Bich", "Kieu", "My", "Phuong", "Thanh", "Thuy", "Minh", "Bao"]
MALE_GIVEN = ["An", "Khang", "Nam", "Huy", "Duc", "Minh", "Phuc", "Dat", "Long", "Quan", "Tuan", "Khoa", "Bao", "Son"]
FEMALE_GIVEN = ["Anh", "Linh", "Trang", "Nhi", "Thao", "Vy", "Han", "Ngan", "Tram", "My", "Tien", "Quyen", "Thu", "Mai"]


# ham phu tro

def weighted_choice(items: Sequence[Tuple[str, float]]) -> str:
    labels = [x[0] for x in items]
    weights = [x[1] for x in items]
    return random.choices(labels, weights=weights, k=1)[0]


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start <= b_end and a_end >= b_start


def schedules_conflict(
    schedules_a: Sequence[Tuple[int, int, int]],
    schedules_b: Sequence[Tuple[int, int, int]],
) -> bool:
    """moi lich co dang (Thu, TietBD, TietKT)."""
    for day_a, start_a, end_a in schedules_a:
        for day_b, start_b, end_b in schedules_b:
            if day_a == day_b and overlaps(start_a, end_a, start_b, end_b):
                return True
    return False


def normalize_ratio_counts(total: int, ratios: Sequence[Tuple[str, float]]) -> Dict[str, int]:
    raw = [(code, total * ratio) for code, ratio in ratios]
    counts = {code: int(value) for code, value in raw}
    remainder = total - sum(counts.values())

    # chia phan du theo phan thap phan lon nhat
    fractions = sorted(
        [(code, value - int(value)) for code, value in raw],
        key=lambda x: x[1],
        reverse=True,
    )
    for i in range(remainder):
        counts[fractions[i % len(fractions)][0]] += 1
    return counts


def make_student_id(major_code: str, index: int) -> str:
    if index > 999:
        raise ValueError(
            f"Student index {index} exceeds 3-digit format for major {major_code}. "
            "Increase suffix width if needed."
        )
    return f"{COHORT_SHORT}{EDU_SYSTEM_CODE}{major_code}{index:03d}"


def make_fake_name() -> str:
    surname = weighted_choice(SURNAME_WEIGHTS)
    is_female = random.random() < 0.48

    # mot it ten co ho ghep
    compound_surname = random.random() < 0.06
    if compound_surname:
        second_surname = random.choice(["Huynh", "Tran", "Le", "Pham", "Nguyen", "Phan"])
        if second_surname != surname:
            surname = f"{surname} {second_surname}"

    if is_female:
        middle = random.choice(FEMALE_MIDDLES)
        given = random.choice(FEMALE_GIVEN)
    else:
        middle = random.choice(MALE_MIDDLES)
        given = random.choice(MALE_GIVEN)

    # thinh thoang tao ten kep
    if random.random() < 0.08:
        extra = random.choice(FEMALE_GIVEN if is_female else MALE_GIVEN)
        if extra != given:
            given = f"{given} {extra}"

    return f"{surname} {middle} {given}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# schema sqlite

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS PhanCong;
DROP TABLE IF EXISTS GiangVien;
DROP TABLE IF EXISTS LichHoc;
DROP TABLE IF EXISTS Phong;
DROP TABLE IF EXISTS DangKy;
DROP TABLE IF EXISTS LopHP;
DROP TABLE IF EXISTS KetQua;
DROP TABLE IF EXISTS TienQuyet;
DROP TABLE IF EXISTS CTDT_MonHoc;
DROP TABLE IF EXISTS MonHoc;
DROP TABLE IF EXISTS SinhVien;
DROP TABLE IF EXISTS KhoaHoc;
DROP TABLE IF EXISTS CTDT;
DROP TABLE IF EXISTS Nganh;

CREATE TABLE Nganh (
    MaNganh TEXT PRIMARY KEY,
    TenNganh TEXT NOT NULL
);

CREATE TABLE CTDT (
    MaCTDT TEXT PRIMARY KEY,
    MaNganh TEXT NOT NULL,
    TenCTDT TEXT,
    NamAD INTEGER,
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
    SoTC INTEGER NOT NULL CHECK (SoTC > 0)
);

CREATE TABLE CTDT_MonHoc (
    MaCTDT TEXT NOT NULL,
    MaMH TEXT NOT NULL,
    LoaiYC TEXT NOT NULL CHECK (LoaiYC IN ('BAT_BUOC', 'TU_CHON')),
    HKGoiY INTEGER CHECK (HKGoiY BETWEEN 1 AND 8),
    PRIMARY KEY (MaCTDT, MaMH),
    FOREIGN KEY (MaCTDT) REFERENCES CTDT(MaCTDT),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH)
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
    TenGV TEXT NOT NULL
);

CREATE TABLE PhanCong (
    MaLHP TEXT NOT NULL,
    MaGV TEXT NOT NULL,
    VaiTro TEXT NOT NULL CHECK (VaiTro IN ('GIANG_VIEN_CHINH', 'TRO_GIANG', 'HUONG_DAN_LAB')),
    PRIMARY KEY (MaLHP, MaGV, VaiTro),
    FOREIGN KEY (MaLHP) REFERENCES LopHP(MaLHP),
    FOREIGN KEY (MaGV) REFERENCES GiangVien(MaGV)
);

CREATE INDEX idx_sinhvien_khoahoc ON SinhVien(MaKhoaHoc);
CREATE INDEX idx_lophp_mamh ON LopHP(MaMH);
CREATE INDEX idx_lichhoc_lophp ON LichHoc(MaLHP);
CREATE INDEX idx_dangky_masv ON DangKy(MaSV);
CREATE INDEX idx_dangky_malhp ON DangKy(MaLHP);
CREATE INDEX idx_ketqua_masv ON KetQua(MaSV);
CREATE INDEX idx_ketqua_mamh ON KetQua(MaMH);
"""


# sinh du lieu

def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def apply_views(conn: sqlite3.Connection, views_path: Path) -> None:
    if not views_path.exists():
        raise FileNotFoundError(f"Views SQL not found: {views_path}")

    conn.executescript(views_path.read_text(encoding="utf-8"))
    conn.commit()


def insert_majors_curricula_cohorts(conn: sqlite3.Connection) -> Dict[str, str]:
    """tra ve major_code -> ma ctdt."""
    major_to_ctdt = {}

    for ma_nganh, short, ten_nganh, _ratio in MAJORS:
        conn.execute(
            "INSERT INTO Nganh (MaNganh, TenNganh) VALUES (?, ?)",
            (ma_nganh, ten_nganh),
        )

        ma_ctdt = f"CTDT_{short}_K23"
        major_to_ctdt[ma_nganh] = ma_ctdt
        conn.execute(
            """
            INSERT INTO CTDT (MaCTDT, MaNganh, TenCTDT, NamAD)
            VALUES (?, ?, ?, ?)
            """,
            (ma_ctdt, ma_nganh, f"Chuong trinh dao tao {ten_nganh} K23", ADMISSION_YEAR),
        )

        ma_khoahoc = f"K23_{short}"
        conn.execute(
            """
            INSERT INTO KhoaHoc (MaKhoaHoc, TenKhoaHoc, MaNganh, MaCTDT, NamNhapHoc)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ma_khoahoc, f"{short} K23", ma_nganh, ma_ctdt, ADMISSION_YEAR),
        )

    conn.commit()
    return major_to_ctdt


def insert_students(conn: sqlite3.Connection) -> Dict[str, List[str]]:
    """tra ve major_code -> danh sach ma sv."""
    major_ratios = [(code, ratio) for code, _short, _name, ratio in MAJORS]
    counts = normalize_ratio_counts(N_STUDENTS, major_ratios)

    major_to_short = {code: short for code, short, _name, _ratio in MAJORS}
    students_by_major: Dict[str, List[str]] = defaultdict(list)

    for major_code, count in counts.items():
        ma_khoahoc = f"K23_{major_to_short[major_code]}"
        for idx in range(1, count + 1):
            ma_sv = make_student_id(major_code, idx)
            ho_ten = make_fake_name()
            trang_thai = weighted_choice(STUDENT_STATUS_WEIGHTS)

            conn.execute(
                """
                INSERT INTO SinhVien (MaSV, HoTen, MaKhoaHoc, TrangThai)
                VALUES (?, ?, ?, ?)
                """,
                (ma_sv, ho_ten, ma_khoahoc, trang_thai),
            )
            students_by_major[major_code].append(ma_sv)

    conn.commit()
    return students_by_major


def insert_courses(conn: sqlite3.Connection) -> Dict[str, dict]:
    course_info = {}
    for ma_mh, ten_mh, so_tc, hk_goi_y, group in COURSES[:N_COURSES]:
        conn.execute(
            "INSERT INTO MonHoc (MaMH, TenMH, SoTC) VALUES (?, ?, ?)",
            (ma_mh, ten_mh, so_tc),
        )
        course_info[ma_mh] = {
            "TenMH": ten_mh,
            "SoTC": so_tc,
            "HKGoiY": hk_goi_y,
            "group": group,
        }
    conn.commit()
    return course_info


def insert_curriculum_courses(
    conn: sqlite3.Connection,
    major_to_ctdt: Dict[str, str],
    course_info: Dict[str, dict],
) -> Dict[str, List[str]]:
    """tra ve CTDT -> danh sach ma mon."""
    ctdt_courses: Dict[str, List[str]] = {}

    for major_code, ma_ctdt in major_to_ctdt.items():
        groups = MAJOR_GROUPS[major_code]

        selected = [
            ma_mh for ma_mh, info in course_info.items()
            if info["group"] in groups
        ]

        # neu ctdt thieu mon thi lay them mon tu nhom khac
        min_courses = min(30, len(course_info))
        if len(selected) < min_courses:
            remaining = [c for c in course_info if c not in selected]
            random.shuffle(remaining)
            selected.extend(remaining[: min_courses - len(selected)])

        # moi ctdt giu khoang 30-35 mon
        random.shuffle(selected)
        selected = selected[: random.randint(30, min(35, len(selected)))]

        # co mon sau thi phai co mon tien quyet
        selected_set = set(selected)
        changed = True
        while changed:
            changed = False
            for course, prereq in PREREQUISITES.items():
                if course in selected_set and prereq in course_info and prereq not in selected_set:
                    selected_set.add(prereq)
                    changed = True

        selected = sorted(selected_set, key=lambda c: course_info[c]["HKGoiY"])
        ctdt_courses[ma_ctdt] = selected

        for ma_mh in selected:
            loai_yc = weighted_choice(REQUIREMENT_WEIGHTS)
            hk_goi_y = course_info[ma_mh]["HKGoiY"]
            conn.execute(
                """
                INSERT OR IGNORE INTO CTDT_MonHoc (MaCTDT, MaMH, LoaiYC, HKGoiY)
                VALUES (?, ?, ?, ?)
                """,
                (ma_ctdt, ma_mh, loai_yc, hk_goi_y),
            )

    conn.commit()
    return ctdt_courses


def insert_prerequisites(conn: sqlite3.Connection, course_info: Dict[str, dict]) -> None:
    for ma_mh, ma_mhtq in PREREQUISITES.items():
        if ma_mh in course_info and ma_mhtq in course_info:
            conn.execute(
                "INSERT OR IGNORE INTO TienQuyet (MaMH, MaMHTQ) VALUES (?, ?)",
                (ma_mh, ma_mhtq),
            )
    conn.commit()


def insert_rooms(conn: sqlite3.Connection) -> List[str]:
    rooms = []

    # phong A2-A5: A2-101A ... A5-404B
    for building in ["A2", "A3", "A4", "A5"]:
        for floor in range(1, 5):
            for room in range(1, 5):
                for suffix in ["A", "B"]:
                    ma_phong = f"{building}-{floor}{room:02d}{suffix}"
                    rooms.append(ma_phong)
                    conn.execute(
                        "INSERT INTO Phong (MaPhong, DayNha) VALUES (?, ?)",
                        (ma_phong, building),
                    )

    # phong F1: F1-101 ... F1-709
    for floor in range(1, 8):
        for room in range(1, 10):
            ma_phong = f"F1-{floor}{room:02d}"
            rooms.append(ma_phong)
            conn.execute(
                "INSERT INTO Phong (MaPhong, DayNha) VALUES (?, ?)",
                (ma_phong, "F1"),
            )

    conn.commit()
    return rooms


def insert_lecturers(conn: sqlite3.Connection) -> List[str]:
    lecturer_ids = []
    for idx in range(1, N_LECTURERS + 1):
        ma_gv = f"GV{idx:03d}"
        ten_gv = make_fake_name()
        lecturer_ids.append(ma_gv)
        conn.execute(
            "INSERT INTO GiangVien (MaGV, TenGV) VALUES (?, ?)",
            (ma_gv, ten_gv),
        )
    conn.commit()
    return lecturer_ids


def insert_offerings(
    conn: sqlite3.Connection,
    course_info: Dict[str, dict],
) -> List[str]:
    offering_ids = []
    offering_count = 0

    # tao deu lhp cho moi mon trong 2 hoc ky
    # 40 mon * 2 hoc ky * 3 nhom = 240 lhp
    for ma_mh in course_info.keys():
        for hoc_ky in [1, 2]:
            n_groups = 3
            for group_no in range(1, n_groups + 1):
                offering_count += 1
                ma_lhp = f"LHP{ACADEMIC_YEAR}{hoc_ky}{offering_count:04d}"
                nhom = f"{group_no:02d}"

                trang_thai = weighted_choice(OFFERING_STATUS_WEIGHTS)
                conn.execute(
                    """
                    INSERT INTO LopHP (MaLHP, MaMH, NamHoc, HocKy, Nhom, SiSoTD, SiSoDK, TrangThai)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (ma_lhp, ma_mh, ACADEMIC_YEAR, hoc_ky, nhom, CLASS_CAPACITY, 0, trang_thai),
                )
                offering_ids.append(ma_lhp)

    conn.commit()
    return offering_ids


def insert_schedules(
    conn: sqlite3.Connection,
    offering_ids: List[str],
    rooms: List[str],
) -> Dict[str, List[Tuple[int, int, int]]]:
    """tra ve offering_id -> [(Thu, TietBD, TietKT), ...]."""
    offering_schedules: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)

    # tranh trung phong gio, khac phong thi duoc
    room_schedules: Dict[str, List[Tuple[int, int, int]]] = defaultdict(list)

    schedule_id = 0

    for ma_lhp in offering_ids:
        # phan lon lhp hoc 2 buoi/tuan, mot so hoc 1 buoi
        n_sessions = 2 if random.random() < 0.80 else 1
        used_days = set()

        for _ in range(n_sessions):
            assigned = False

            for _attempt in range(300):
                thu = random.choice(DAYS_OF_WEEK)
                if thu in used_days and n_sessions > 1:
                    continue

                tiet_bd, tiet_kt = random.choice(LESSON_BLOCKS)
                room = random.choice(rooms)

                candidate = (thu, tiet_bd, tiet_kt)
                room_conflict = any(
                    existing_day == thu and overlaps(tiet_bd, tiet_kt, existing_start, existing_end)
                    for existing_day, existing_start, existing_end in room_schedules[room]
                )

                if not room_conflict:
                    schedule_id += 1
                    ma_lich = f"LICH{schedule_id:05d}"
                    conn.execute(
                        """
                        INSERT INTO LichHoc (MaLich, MaLHP, MaPhong, Thu, TietBD, TietKT)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (ma_lich, ma_lhp, room, thu, tiet_bd, tiet_kt),
                    )
                    room_schedules[room].append(candidate)
                    offering_schedules[ma_lhp].append(candidate)
                    used_days.add(thu)
                    assigned = True
                    break

            if not assigned:
                # fallback neu thu phong qua lau ma khong gan duoc
                schedule_id += 1
                ma_lich = f"LICH{schedule_id:05d}"
                thu = random.choice(DAYS_OF_WEEK)
                tiet_bd, tiet_kt = random.choice(LESSON_BLOCKS)
                room = random.choice(rooms)
                conn.execute(
                    """
                    INSERT INTO LichHoc (MaLich, MaLHP, MaPhong, Thu, TietBD, TietKT)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (ma_lich, ma_lhp, room, thu, tiet_bd, tiet_kt),
                )
                offering_schedules[ma_lhp].append((thu, tiet_bd, tiet_kt))

    conn.commit()
    return offering_schedules


def insert_teaching_assignments(
    conn: sqlite3.Connection,
    offering_ids: List[str],
    lecturer_ids: List[str],
) -> None:
    for ma_lhp in offering_ids:
        ma_gv = random.choice(lecturer_ids)
        conn.execute(
            """
            INSERT INTO PhanCong (MaLHP, MaGV, VaiTro)
            VALUES (?, ?, 'GIANG_VIEN_CHINH')
            """,
            (ma_lhp, ma_gv),
        )
    conn.commit()


def get_student_curriculum_map(conn: sqlite3.Connection) -> Dict[str, str]:
    rows = conn.execute(
        """
        SELECT sv.MaSV, kh.MaCTDT
        FROM SinhVien sv
        JOIN KhoaHoc kh ON sv.MaKhoaHoc = kh.MaKhoaHoc
        """
    ).fetchall()
    return {ma_sv: ma_ctdt for ma_sv, ma_ctdt in rows}


def insert_results(
    conn: sqlite3.Connection,
    course_info: Dict[str, dict],
) -> None:
    """sinh ket qua hoc tap cho sinh vien K23."""
    student_to_ctdt = get_student_curriculum_map(conn)

    ctdt_courses = defaultdict(list)
    for ma_ctdt, ma_mh, hk_goi_y in conn.execute(
        "SELECT MaCTDT, MaMH, HKGoiY FROM CTDT_MonHoc"
    ):
        ctdt_courses[ma_ctdt].append((ma_mh, hk_goi_y))

    for ma_sv, ma_ctdt in student_to_ctdt.items():
        for ma_mh, hk_goi_y in ctdt_courses[ma_ctdt]:
            if hk_goi_y is None:
                continue

            # k23 den 2026 thuong da hoc cac mon hk 1-5
            if hk_goi_y <= 5:
                attempt_prob = 0.88
            elif hk_goi_y == 6:
                attempt_prob = 0.28
            else:
                attempt_prob = 0.08

            if random.random() < attempt_prob:
                ket_qua = weighted_choice(RESULT_WEIGHTS)

                # nam hoc va hoc ky bam theo hk goi y
                nam_hoc = 2023 + max(0, (hk_goi_y - 1) // 2)
                hoc_ky = 1 if hk_goi_y % 2 == 1 else 2

                conn.execute(
                    """
                    INSERT OR REPLACE INTO KetQua (MaSV, MaMH, NamHoc, HocKy, KetQua)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (ma_sv, ma_mh, nam_hoc, hoc_ky, ket_qua),
                )

    conn.commit()


def offering_target_enrollment(status: str) -> int:
    if status == "DAY":
        return CLASS_CAPACITY
    if status == "MO":
        return random.randint(12, CLASS_CAPACITY - 4)
    return 0  # dong/huy


def insert_registrations(
    conn: sqlite3.Connection,
    offering_schedules: Dict[str, List[Tuple[int, int, int]]],
) -> None:
    """sinh dang ky, khong cho trung lich tung sinh vien."""
    # nap cac bang tra cuu
    student_rows = conn.execute(
        """
        SELECT sv.MaSV, kh.MaCTDT
        FROM SinhVien sv
        JOIN KhoaHoc kh ON sv.MaKhoaHoc = kh.MaKhoaHoc
        WHERE sv.TrangThai = 'DANG_HOC'
        """
    ).fetchall()
    students = [row[0] for row in student_rows]
    student_to_ctdt = {row[0]: row[1] for row in student_rows}

    ctdt_to_students: Dict[str, List[str]] = defaultdict(list)
    for ma_sv, ma_ctdt in student_to_ctdt.items():
        ctdt_to_students[ma_ctdt].append(ma_sv)

    ctdt_course_set: Dict[str, set] = defaultdict(set)
    for ma_ctdt, ma_mh in conn.execute("SELECT MaCTDT, MaMH FROM CTDT_MonHoc"):
        ctdt_course_set[ma_ctdt].add(ma_mh)

    course_credits = {
        ma_mh: so_tc for ma_mh, so_tc in conn.execute("SELECT MaMH, SoTC FROM MonHoc")
    }

    offerings = conn.execute(
        """
        SELECT MaLHP, MaMH, HocKy, TrangThai
        FROM LopHP
        ORDER BY RANDOM()
        """
    ).fetchall()

    # theo doi rieng tung sinh vien
    student_sem_schedules: Dict[Tuple[str, int], List[Tuple[int, int, int]]] = defaultdict(list)
    student_sem_credits: Dict[Tuple[str, int], int] = defaultdict(int)
    student_sem_courses: Dict[Tuple[str, int], set] = defaultdict(set)

    registration_time_base = datetime(2026, 1, 5, 8, 0, 0)

    for ma_lhp, ma_mh, hoc_ky, trang_thai in offerings:
        target = offering_target_enrollment(trang_thai)
        if target <= 0:
            continue

        # ung vien la sv co mon nay trong ctdt
        candidate_students = []
        for ma_ctdt, student_ids in ctdt_to_students.items():
            if ma_mh in ctdt_course_set[ma_ctdt]:
                candidate_students.extend(student_ids)

        random.shuffle(candidate_students)

        inserted = 0
        credits = course_credits[ma_mh]
        sched = offering_schedules.get(ma_lhp, [])

        for ma_sv in candidate_students:
            key = (ma_sv, hoc_ky)

            if ma_mh in student_sem_courses[key]:
                continue

            if student_sem_credits[key] + credits > MAX_CREDITS_PER_SEMESTER:
                continue

            if schedules_conflict(student_sem_schedules[key], sched):
                continue

            tgdk = registration_time_base + timedelta(
                days=random.randint(0, 45),
                minutes=random.randint(0, 600),
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

        # lop day khong du si so thi ha ve mo
        if trang_thai == "DAY" and inserted < CLASS_CAPACITY:
            conn.execute(
                "UPDATE LopHP SET TrangThai = 'MO' WHERE MaLHP = ?",
                (ma_lhp,),
            )

    # cap nhat si so dang ky
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

    # chuan hoa trang thai day/mo
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


# kiem tra va in tom tat

def scalar(conn: sqlite3.Connection, sql: str, params: Tuple = ()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def validate_database(conn: sqlite3.Connection) -> List[str]:
    errors = []

    # khoa ngoai
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        errors.append(f"Foreign key errors: {fk_errors[:5]}")

    # si so dang ky
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

    # lop dong/huy khong duoc co dang ky
    invalid_status_regs = conn.execute(
        """
        SELECT COUNT(*)
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        WHERE lhp.TrangThai IN ('DONG', 'HUY')
        """
    ).fetchone()[0]
    if invalid_status_regs:
        errors.append(f"Registrations in DONG/HUY offerings: {invalid_status_regs}")

    # moi lhp can 1 giang vien chinh
    no_main_lecturer = conn.execute(
        """
        SELECT COUNT(*)
        FROM LopHP lhp
        WHERE NOT EXISTS (
            SELECT 1
            FROM PhanCong pc
            WHERE pc.MaLHP = lhp.MaLHP
              AND pc.VaiTro = 'GIANG_VIEN_CHINH'
        )
        """
    ).fetchone()[0]
    if no_main_lecturer:
        errors.append(f"Offerings without GIANG_VIEN_CHINH: {no_main_lecturer}")

    # trung lich theo tung sinh vien
    # chi tinh trong cung nam hoc va hoc ky
    conflict_count = conn.execute(
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
        """
    ).fetchone()[0]
    if conflict_count:
        errors.append(f"Student-level schedule conflicts: {conflict_count}")

    # khong trung phong gio trong cung nam hoc va hoc ky
    room_conflicts = conn.execute(
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
        """
    ).fetchone()[0]
    if room_conflicts:
        errors.append(f"Room-time conflicts: {room_conflicts}")

    return errors


def print_summary(conn: sqlite3.Connection) -> None:
    tables = [
        "Nganh", "CTDT", "KhoaHoc", "SinhVien", "MonHoc",
        "CTDT_MonHoc", "TienQuyet", "KetQua", "LopHP",
        "DangKy", "Phong", "LichHoc", "GiangVien", "PhanCong",
    ]

    print("\n=== ROW COUNTS ===")
    for table in tables:
        count = scalar(conn, f"SELECT COUNT(*) FROM {table}")
        print(f"{table:15s}: {count}")

    print("\n=== LopHP TrangThai ===")
    for status, count in conn.execute(
        "SELECT TrangThai, COUNT(*) FROM LopHP GROUP BY TrangThai ORDER BY TrangThai"
    ):
        print(f"{status:5s}: {count}")

    print("\n=== KetQua distribution ===")
    for result, count in conn.execute(
        "SELECT KetQua, COUNT(*) FROM KetQua GROUP BY KetQua ORDER BY KetQua"
    ):
        print(f"{result:10s}: {count}")

    print("\n=== DangKy per semester ===")
    for hoc_ky, count in conn.execute(
        """
        SELECT lhp.HocKy, COUNT(*)
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        GROUP BY lhp.HocKy
        ORDER BY lhp.HocKy
        """
    ):
        print(f"HK{hoc_ky}: {count}")

    print("\n=== Sample students ===")
    for row in conn.execute("SELECT * FROM SinhVien LIMIT 5"):
        print(row)

    print("\n=== Sample offerings ===")
    for row in conn.execute("SELECT * FROM LopHP LIMIT 5"):
        print(row)


def generate_database(
    output_path: Path,
    seed: int = DEFAULT_SEED,
    views_path: Optional[Path] = DEFAULT_VIEWS_PATH,
) -> None:
    random.seed(seed)
    ensure_parent(output_path)

    if output_path.exists():
        output_path.unlink()

    conn = sqlite3.connect(output_path)
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        create_schema(conn)

        major_to_ctdt = insert_majors_curricula_cohorts(conn)
        insert_students(conn)
        course_info = insert_courses(conn)
        insert_curriculum_courses(conn, major_to_ctdt, course_info)
        insert_prerequisites(conn, course_info)
        rooms = insert_rooms(conn)
        lecturer_ids = insert_lecturers(conn)
        offering_ids = insert_offerings(conn, course_info)
        offering_schedules = insert_schedules(conn, offering_ids, rooms)
        insert_teaching_assignments(conn, offering_ids, lecturer_ids)
        insert_results(conn, course_info)
        insert_registrations(conn, offering_schedules)

        errors = validate_database(conn)
        print_summary(conn)

        print("\n=== VALIDATION ===")
        if errors:
            print("FAILED")
            for err in errors:
                print(f"- {err}")
            raise RuntimeError("Database validation failed.")
        else:
            print("PASSED")

        if views_path is not None:
            apply_views(conn, views_path)
            print(f"\nViews applied from: {views_path.resolve()}")

        print(f"\nDatabase generated at: {output_path.resolve()}")

    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=str,
        default="data/course_registration.db",
        help="Output SQLite database path.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for reproducible generation.",
    )
    parser.add_argument(
        "--views",
        type=str,
        default=str(DEFAULT_VIEWS_PATH),
        help="Views SQL path to apply after data generation.",
    )
    parser.add_argument(
        "--skip-views",
        action="store_true",
        help="Skip applying views.sql.",
    )
    args = parser.parse_args()

    views_path = None if args.skip_views else Path(args.views)
    generate_database(Path(args.output), seed=args.seed, views_path=views_path)


if __name__ == "__main__":
    main()
