from __future__ import annotations

import argparse
import hashlib
import random
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import build_ctdt_db as base_builder


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EXCEL_PATH = PROJECT_ROOT / "data" / "CTDT_HCMUTE.xlsx"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "data" / "ctdt_sis.db"
DEFAULT_VIEWS_PATH = PROJECT_ROOT / "data" / "views.sql"

RANDOM_SEED = 20260612
THUAT_TOAN_HASH_MAT_KHAU = "pbkdf2_sha256"
SO_VONG_LAP_HASH_MAT_KHAU = 30_000
SO_TIN_CHI_TOI_DA_MAC_DINH = 28


TRONG_SO_NHOM_HO_SO: Dict[int, Sequence[Tuple[str, float]]] = {
    2022: [
        ("GAN_TOT_NGHIEP", 0.24),
        ("DUNG_TIEN_DO", 0.18),
        ("CAI_THIEN_DIEM", 0.12),
        ("HOC_LAI_NHIEU", 0.12),
        ("ROT_NEN_TANG_CNTT", 0.10),
        ("ROT_DAI_CUONG", 0.08),
        ("THIEU_TIEN_QUYET", 0.06),
        ("TRUNG_LICH", 0.05),
        ("DIEM_TB_THAP", 0.03),
        ("DIEM_TB_CAO", 0.02),
    ],
    2023: [
        ("DUNG_TIEN_DO", 0.24),
        ("ROT_NEN_TANG_CNTT", 0.14),
        ("ROT_DAI_CUONG", 0.12),
        ("THIEU_TIEN_QUYET", 0.12),
        ("HOC_LAI_NHIEU", 0.10),
        ("CAI_THIEN_DIEM", 0.08),
        ("TRUNG_LICH", 0.07),
        ("VUOT_TIN_CHI", 0.05),
        ("DIEM_TB_THAP", 0.04),
        ("DIEM_TB_CAO", 0.04),
    ],
    2024: [
        ("DUNG_TIEN_DO", 0.28),
        ("ROT_DAI_CUONG", 0.16),
        ("ROT_NEN_TANG_CNTT", 0.16),
        ("THIEU_TIEN_QUYET", 0.10),
        ("HOC_LAI_NHIEU", 0.08),
        ("TRUNG_LICH", 0.08),
        ("VUOT_TIN_CHI", 0.05),
        ("DIEM_TB_THAP", 0.05),
        ("DIEM_TB_CAO", 0.04),
    ],
    2025: [
        ("DUNG_TIEN_DO", 0.30),
        ("ROT_DAI_CUONG", 0.20),
        ("ROT_NEN_TANG_CNTT", 0.12),
        ("THIEU_TIEN_QUYET", 0.08),
        ("HOC_LAI_NHIEU", 0.06),
        ("TRUNG_LICH", 0.08),
        ("VUOT_TIN_CHI", 0.04),
        ("DIEM_TB_THAP", 0.06),
        ("DIEM_TB_CAO", 0.06),
    ],
}

GHI_CHU_NHOM_HO_SO = {
    "DUNG_TIEN_DO": "Sinh viên học phần lớn đúng tiến độ gợi ý của chương trình đào tạo.",
    "ROT_DAI_CUONG": "Sinh viên có rớt một số môn đại cương hoặc nền tảng.",
    "ROT_NEN_TANG_CNTT": "Sinh viên có rớt một số môn nền tảng công nghệ thông tin.",
    "THIEU_TIEN_QUYET": "Sinh viên được tạo dữ liệu thiếu tiên quyết để kiểm thử rule đăng ký.",
    "HOC_LAI_NHIEU": "Sinh viên có nhiều lần học lại.",
    "CAI_THIEN_DIEM": "Sinh viên có đăng ký học cải thiện điểm sau khi đã đạt môn.",
    "TRUNG_LICH": "Sinh viên có lịch đăng ký hiện tại dễ phát sinh trùng lịch với lớp mục tiêu.",
    "VUOT_TIN_CHI": "Sinh viên đang gần giới hạn tín chỉ học kỳ.",
    "GAN_TOT_NGHIEP": "Sinh viên đã hoàn thành nhiều môn và gần tốt nghiệp.",
    "DIEM_TB_THAP": "Sinh viên có điểm trung bình thấp và nhiều môn điểm thấp hoặc không đạt.",
    "DIEM_TB_CAO": "Sinh viên có điểm trung bình cao và đạt hầu hết các môn đã học.",
}

GIOI_HAN_TIN_CHI_THEO_NHOM = {
    "DIEM_TB_THAP": 18,
    "ROT_NEN_TANG_CNTT": 22,
    "ROT_DAI_CUONG": 24,
    "HOC_LAI_NHIEU": 24,
    "VUOT_TIN_CHI": 28,
}


PREREQUISITES: Sequence[Tuple[str, Sequence[str], str]] = [
    ("PRTE230385E", ["INPR130285E"], "Programming techniques builds on introductory programming."),
    ("DASA230179E", ["PRTE230385E"], "Data structures and algorithms require programming techniques."),
    ("OOPR230279E", ["PRTE230385E"], "OOP requires programming techniques."),
    ("CAAL230180E", ["PRTE230385E"], "Assembly programming requires basic programming skills."),
    ("WIPR230579E", ["OOPR230279E"], "Windows programming uses OOP concepts."),
    ("SOEN330679E", ["OOPR230279E"], "Software engineering needs OOP background."),
    ("DEPA330879E", ["OOPR230279E"], "Design patterns require OOP."),
    ("OOSE330679E", ["OOPR230279E"], "Object-oriented software engineering requires OOP."),
    ("SOTE431079E", ["SOEN330679E"], "Software testing follows software engineering."),
    ("AMHC333179E", ["SOEN330679E"], "Agile methods follow software engineering foundations."),
    ("MTSE431179E", ["SOEN330679E", "OOSE330679E"], "Advanced software engineering topic."),
    ("SOPM431679E", ["SOEN330679E", "PROJ215879E"], "Project management follows software engineering and IT project practice."),
    ("HCIN431979E", ["OOPR230279E"], "HCI benefits from application design and OOP background."),
    ("ESDN432079E", ["SOEN330679E", "HCIN431979E"], "Educational software design combines SE and HCI."),
    ("PROJ212879E", ["PRTE230385E"], "Project 1 requires programming techniques."),
    ("PROJ312979E", ["PROJ212879E", "OOPR230279E"], "Project 2 follows Project 1 and OOP."),
    ("PROJ313079E", ["PROJ312979E", "DBMS330284E"], "Project 3 needs prior project and DBMS knowledge."),
    ("PROJ215879E", ["PRTE230385E", "OOPR230279E"], "IT Project requires programming and OOP."),
    ("POSE431479E", ["OOSE330679E", "SOTE431079E"], "Software engineering project requires OOSE and testing."),
    ("GRPR423279E", ["PROJ312979E"], "Internship requires prior project experience."),
    ("ITIN441085E", ["PROJ313079E"], "Internship requires advanced project experience."),
    ("GRPR471979E", ["PROJ313079E", "GRPR423279E"], "Capstone requires project and internship preparation."),
    ("GRPR401979E", ["PROJ313079E", "GRPR423279E"], "Capstone/special subject requires project and internship preparation."),
    ("DBMS330284E", ["DBSY230184E"], "DBMS follows Database System."),
    ("ADDB331784E", ["DBMS330284E"], "Advanced Database follows DBMS."),
    ("DIDB330584E", ["DBMS330284E"], "Distributed database follows DBMS."),
    ("DBSE431284E", ["DBMS330284E", "INSE330380E"], "Database security combines DBMS and information security."),
    ("DAWH430784E", ["DBMS330284E"], "Data warehouse follows DBMS."),
    ("ISAD330384E", ["DBSY230184E", "OOPR230279E"], "Information system analysis uses DB and OOP."),
    ("MISY430684E", ["ISAD330384E"], "MIS follows information system analysis and design."),
    ("ERPC431984E", ["MISY430684E"], "ERP follows MIS."),
    ("POIS431184E", ["ISAD330384E", "DBMS330284E"], "IS project requires ISAD and DBMS."),
    ("INDS331085E", ["DBSY230184E", "MATH132901E", "PRTE230385E"], "Data science needs DB, statistics, and programming."),
    ("DAMI330484E", ["INDS331085E", "MATH132901E"], "Data mining follows data science and statistics."),
    ("BDES333877E", ["INDS331085E", "DBMS330284E"], "Big data essentials needs data science and DBMS."),
    ("BDAN333977E", ["BDES333877E", "MALE431085E"], "Big data analysis needs big data and ML."),
    ("INRE431084E", ["DASA230179E", "DBSY230184E"], "Information retrieval needs algorithms and DB."),
    ("SEEN431579E", ["INRE431084E", "WEPR330479E"], "Search engine follows IR and web programming."),
    ("MAAI330985E", ["MATH143001E", "MATH132901E"], "AI mathematics requires linear algebra and statistics."),
    ("ARIN330585E", ["DASA230179E", "DIGR230485E", "MATH143001E"], "AI requires algorithms, discrete math, and linear algebra."),
    ("MALE431085E", ["MAAI330985E", "INDS331085E"], "Machine learning follows AI math and data science."),
    ("NLPR431585E", ["MALE431085E", "DASA230179E"], "NLP requires ML and algorithms."),
    ("SPPR330885E", ["MAAI330985E", "DASA230179E"], "Speech processing needs AI math and algorithms."),
    ("DIPR430685E", ["MAAI330985E", "MATH143001E"], "Image processing needs AI math and linear algebra."),
    ("RELE431685E", ["ARIN330585E", "MALE431085E"], "Reinforcement learning follows AI and ML."),
    ("POAI431485E", ["ARIN330585E", "MALE431085E"], "AI project requires AI and ML."),
    ("WEPR330479E", ["OOPR230279E", "DBSY230184E"], "Web programming uses OOP and DB."),
    ("WESE331479E", ["WEPR330479E", "INSE330380E"], "Web security follows web programming and information security."),
    ("MOPR331279E", ["OOPR230279E"], "Mobile programming requires OOP."),
    ("ADMP431879E", ["MOPR331279E"], "Advanced mobile programming follows mobile programming."),
    ("ECOM430984E", ["WEPR330479E", "DBSY230184E"], "E-commerce requires web and DB."),
    ("ADPL331379E", ["OOPR230279E", "DASA230179E"], "Advanced programming language needs OOP and algorithms."),
    ("OPSY330280E", ["CAAL230180E", "PRTE230385E"], "Operating systems need architecture and programming."),
    ("UNOS330680E", ["OPSY330280E"], "Unix OS follows operating systems."),
    ("NEES330380E", ["INIT130185E"], "Networking essentials follows IT introduction."),
    ("DCTE330480E", ["NEES330380E"], "Data communications follows networking essentials."),
    ("ADNT330580E", ["NEES330380E", "DCTE330480E"], "Advanced networking follows networking and data communications."),
    ("CNDE430780E", ["NEES330380E", "DCTE330480E"], "Network design follows networking and data communications."),
    ("NPRO430980E", ["NEES330380E", "OOPR230279E"], "Network programming requires networking and OOP."),
    ("INSE330380E", ["NEES330380E", "OPSY330280E"], "Information security requires networking and OS."),
    ("INSE330379E", ["NEES330380E", "OPSY330280E"], "Information security requires networking and OS."),
    ("NSEC430880E", ["INSE330380E", "NEES330380E"], "Network security follows information security and networking."),
    ("ETHA332080E", ["INSE330380E", "NEES330380E"], "Ethical hacking follows information security and networking."),
    ("DIFO432180E", ["INSE330380E", "OPSY330280E"], "Digital forensics follows information security and OS."),
    ("MAAN431680E", ["INSE330380E", "OPSY330280E"], "Malware analysis follows information security and OS."),
    ("NSMS432280E", ["NSEC430880E"], "Network security monitoring follows network security."),
    ("WISE432380E", ["NSEC430880E", "MOPR331279E"], "Wireless/mobile security follows network security and mobile programming."),
    ("POCN431280E", ["NEES330380E", "NSEC430880E"], "Network project requires networking and network security."),
    ("BCAP433280", ["DASA230179E", "INSE330380E"], "Blockchain requires algorithms and security."),
    ("CLCO332779E", ["NEES330380E", "OPSY330280E"], "Cloud computing requires networking and OS."),
    ("CLCO432779E", ["NEES330380E", "OPSY330280E"], "Cloud computing requires networking and OS."),
    ("CLAD432480E", ["CLCO332779E"], "Cloud administration follows cloud computing."),
    ("IIOT431480E", ["NEES330380E", "EEEN231780E"], "IoT requires networking and basic electronics."),
    ("INOT431780E", ["NEES330380E", "EEEN231780E"], "IoT requires networking and basic electronics."),
    ("AIOT331185E", ["ARIN330585E", "INOT431780E"], "AI for IoT requires AI and IoT."),
    ("ESYS431080E", ["CAAL230180E", "EEEN231780E"], "Embedded systems require architecture and electronics."),
    ("PCOM331285E", ["DASA230179E", "OPSY330280E", "CAAL230180E"], "Parallel computing requires algorithms, OS, and architecture."),
    ("MATH132501E", ["MATH132401E"], "Calculus 2 follows Calculus I."),
    ("MATH132601E", ["MATH132501E"], "Calculus 3 follows Calculus 2."),
    ("MATH122101E", ["MATH132401E"], "Probability follows Calculus I."),
    ("MATH132901E", ["MATH122101E"], "Engineering statistics follows probability."),
    ("PHYS130902E", ["MATH132401E"], "Physics 1 uses Calculus I."),
    ("PHYS111202E", ["PHYS130902E"], "Physics lab follows Physics 1."),
    ("DIGR230485E", ["MATH143001E"], "Discrete math uses algebraic structures."),
    ("PRBE214262E", ["EEEN231780E"], "Electronics practice follows basic electronics."),
    ("ACEN340635E", ["ACEN340535E"], "Academic English 2 follows Academic English 1."),
    ("ACEN440735E", ["ACEN340635E"], "Academic English 3 follows Academic English 2."),
    ("ACEN440835E", ["ACEN440735E"], "Academic English 4 follows Academic English 3."),
    ("COEN140235E", ["COEN140135E"], "Communicative English 2 follows Communicative English 1."),
    ("COEN240335E", ["COEN140235E"], "Communicative English 3 follows Communicative English 2."),
    ("COEN240435E", ["COEN240335E"], "Communicative English 4 follows Communicative English 3."),
    ("TEEN233885E", ["TEEN123785E"], "Technical English 2 follows Technical English 1."),
    ("ENTW611038E", ["ACEN440835E"], "Thesis writing requires advanced academic English."),
    ("LLCT120205E", ["LLCT130105E"], "Political economics follows Marxism-Leninism philosophy."),
    ("LLCT120405E", ["LLCT120205E"], "Scientific socialism follows political economics."),
    ("LLCT120314E", ["LLCT120405E"], "Ho Chi Minh ideology follows scientific socialism."),
    ("LLCT220514E", ["LLCT120314E"], "Party history follows Ho Chi Minh ideology."),
    ("LLCT230214E", ["LLCT120314E"], "Party policy follows Ho Chi Minh ideology."),
    ("PHED110613E", ["PHED110513E"], "Physical Education 2 follows Physical Education 1."),
    ("PHED130715E", ["PHED110613E"], "Physical Education 3 follows Physical Education 2."),
    ("GDQP008032E", ["GDQP008031E"], "Military Education 2 follows Military Education 1."),
    ("GDQP008033E", ["GDQP008032E"], "Military Education 3 follows Military Education 2."),
    ("GDQP110231", ["GDQP110131"], "National defense education 2 follows part 1."),
    ("GDQP110331", ["GDQP110231"], "National defense education 3 follows part 2."),
    ("GDQP110431", ["GDQP110331"], "National defense education 4 follows part 3."),
]


EXTENSION_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE TaiKhoan (
    MaTK TEXT PRIMARY KEY,
    MaSV TEXT UNIQUE,
    Email TEXT NOT NULL UNIQUE,
    MatKhauHash TEXT NOT NULL,
    PasswordSalt TEXT NOT NULL,
    ThuatToanHash TEXT NOT NULL DEFAULT 'pbkdf2_sha256',
    SoVongLapHash INTEGER NOT NULL,
    VaiTro TEXT NOT NULL CHECK (VaiTro IN ('SINH_VIEN', 'NHAN_VIEN', 'QUAN_TRI')),
    TrangThai TEXT NOT NULL CHECK (TrangThai IN ('HOAT_DONG', 'BI_KHOA', 'VO_HIEU_HOA')),
    ThoiDiemTao TEXT NOT NULL,
    LanDangNhapCuoi TEXT,
    FOREIGN KEY (MaSV) REFERENCES SinhVien(MaSV)
);

CREATE TABLE HocKyHeThong (
    MaHocKy TEXT PRIMARY KEY,
    NamHoc INTEGER NOT NULL,
    HocKy INTEGER NOT NULL CHECK (HocKy IN (1, 2)),
    TenHocKy TEXT NOT NULL,
    TrangThai TEXT NOT NULL CHECK (TrangThai IN ('DANG_MO_DANG_KY', 'SAP_MO', 'DA_KET_THUC')),
    DangMoDangKy INTEGER NOT NULL CHECK (DangMoDangKy IN (0, 1)),
    NgayBatDau TEXT,
    NgayKetThuc TEXT,
    UNIQUE (NamHoc, HocKy)
);

CREATE TABLE CauHinhDangKy (
    MaCauHinh TEXT PRIMARY KEY,
    GiaTri TEXT NOT NULL,
    MoTa TEXT
);

CREATE TABLE ThongTinTaoDuLieu (
    MaThongTin TEXT PRIMARY KEY,
    GiaTri TEXT NOT NULL
);

CREATE TABLE QuanHeHocPhan (
    MaMH TEXT NOT NULL,
    MaMHDieuKien TEXT NOT NULL,
    LoaiQuanHe TEXT NOT NULL CHECK (LoaiQuanHe IN ('TIEN_QUYET', 'HOC_TRUOC', 'TUONG_DUONG')),
    GhiChu TEXT,
    PRIMARY KEY (MaMH, MaMHDieuKien, LoaiQuanHe),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH),
    FOREIGN KEY (MaMHDieuKien) REFERENCES MonHoc(MaMH),
    CHECK (MaMH <> MaMHDieuKien)
);

CREATE TABLE KetQuaHocTap (
    KetQuaID INTEGER PRIMARY KEY AUTOINCREMENT,
    MaSV TEXT NOT NULL,
    MaMH TEXT NOT NULL,
    MaLHP TEXT,
    LanHoc INTEGER NOT NULL CHECK (LanHoc > 0),
    NamHoc INTEGER NOT NULL,
    HocKy INTEGER NOT NULL CHECK (HocKy IN (1, 2)),
    DiemQuaTrinh REAL CHECK (DiemQuaTrinh IS NULL OR (DiemQuaTrinh BETWEEN 0 AND 10)),
    DiemThi REAL CHECK (DiemThi IS NULL OR (DiemThi BETWEEN 0 AND 10)),
    DiemTongKet REAL CHECK (DiemTongKet IS NULL OR (DiemTongKet BETWEEN 0 AND 10)),
    DiemChu TEXT,
    DiemHe4 REAL CHECK (DiemHe4 IS NULL OR (DiemHe4 BETWEEN 0 AND 4)),
    KetQua TEXT NOT NULL CHECK (KetQua IN ('DAT', 'KHONG_DAT', 'DANG_HOC', 'RUT_MON', 'CAM_THI')),
    LoaiHoc TEXT NOT NULL CHECK (LoaiHoc IN ('HOC_MOI', 'HOC_LAI', 'CAI_THIEN')),
    GhiChu TEXT,
    ThoiDiemTao TEXT NOT NULL,
    FOREIGN KEY (MaSV) REFERENCES SinhVien(MaSV),
    FOREIGN KEY (MaMH) REFERENCES MonHoc(MaMH),
    FOREIGN KEY (MaLHP) REFERENCES LopHP(MaLHP)
);

CREATE TABLE HoSoHocTapSinhVien (
    MaSV TEXT PRIMARY KEY,
    NhomHoSo TEXT NOT NULL,
    GioiHanTinChi INTEGER NOT NULL DEFAULT 28,
    GPA REAL,
    TinChiTichLuy INTEGER NOT NULL DEFAULT 0,
    SoMonDaDau INTEGER NOT NULL DEFAULT 0,
    SoMonTungRot INTEGER NOT NULL DEFAULT 0,
    SoLanHocLaiCaiThien INTEGER NOT NULL DEFAULT 0,
    TinChiDangKyHienTai INTEGER NOT NULL DEFAULT 0,
    CanhBaoHocVu TEXT,
    GhiChu TEXT,
    FOREIGN KEY (MaSV) REFERENCES SinhVien(MaSV)
);

CREATE INDEX idx_taikhoan_email ON TaiKhoan(Email);
CREATE INDEX idx_quanhe_mamh ON QuanHeHocPhan(MaMH);
CREATE INDEX idx_quanhe_dieukien ON QuanHeHocPhan(MaMHDieuKien);
CREATE INDEX idx_kqht_masv_mamh ON KetQuaHocTap(MaSV, MaMH);
CREATE INDEX idx_kqht_lookup_term ON KetQuaHocTap(MaSV, MaMH, KetQua, NamHoc, HocKy, LanHoc);
CREATE INDEX idx_kqht_status ON KetQuaHocTap(KetQua);
CREATE INDEX idx_hoso_nhom ON HoSoHocTapSinhVien(NhomHoSo);
"""


SIS_VIEWS_SQL = """
DROP VIEW IF EXISTS v_tai_khoan_sinh_vien;
DROP VIEW IF EXISTS v_ket_qua_hoc_tap_sv;
DROP VIEW IF EXISTS v_ket_qua_tot_nhat_sv;
DROP VIEW IF EXISTS v_mon_da_dau_sv;
DROP VIEW IF EXISTS v_mon_da_rot_sv;
DROP VIEW IF EXISTS v_dang_ky_hien_tai_sv;
DROP VIEW IF EXISTS v_tien_do_ctdt_sv;
DROP VIEW IF EXISTS v_dieu_kien_dang_ky_mon_sv;

CREATE VIEW v_tai_khoan_sinh_vien AS
SELECT
    tk.MaTK,
    tk.MaSV,
    sv.HoTen,
    tk.Email,
    tk.VaiTro,
    tk.TrangThai AS TrangThaiTaiKhoan,
    sv.TrangThai AS TrangThaiSV,
    svdd.MaKhoaHoc,
    svdd.TenKhoaHoc,
    svdd.MaCTDT,
    svdd.MaNganh,
    svdd.TenNganh,
    tk.ThoiDiemTao,
    tk.LanDangNhapCuoi
FROM TaiKhoan tk
LEFT JOIN SinhVien sv ON tk.MaSV = sv.MaSV
LEFT JOIN v_sinh_vien_day_du svdd ON tk.MaSV = svdd.MaSV;

CREATE VIEW v_ket_qua_hoc_tap_sv AS
SELECT
    kq.KetQuaID,
    kq.MaSV,
    sv.HoTen,
    hs.NhomHoSo,
    kq.MaMH,
    mh.TenMH,
    mh.SoTC,
    kq.MaLHP,
    kq.LanHoc,
    kq.NamHoc,
    kq.HocKy,
    kq.DiemQuaTrinh,
    kq.DiemThi,
    kq.DiemTongKet,
    kq.DiemChu,
    kq.DiemHe4,
    kq.KetQua,
    kq.LoaiHoc,
    kq.GhiChu
FROM KetQuaHocTap kq
JOIN SinhVien sv ON kq.MaSV = sv.MaSV
JOIN MonHoc mh ON kq.MaMH = mh.MaMH
LEFT JOIN HoSoHocTapSinhVien hs ON kq.MaSV = hs.MaSV;

CREATE VIEW v_ket_qua_tot_nhat_sv AS
WITH ranked AS (
    SELECT
        kq.*,
        mh.SoTC,
        ROW_NUMBER() OVER (
            PARTITION BY kq.MaSV, kq.MaMH
            ORDER BY
                CASE WHEN kq.KetQua = 'DAT' THEN 1 ELSE 0 END DESC,
                COALESCE(kq.DiemTongKet, -1) DESC,
                kq.NamHoc DESC,
                kq.HocKy DESC,
                kq.LanHoc DESC
        ) AS rn
    FROM KetQuaHocTap kq
    JOIN MonHoc mh ON kq.MaMH = mh.MaMH
    WHERE kq.KetQua IN ('DAT', 'KHONG_DAT')
)
SELECT
    r.MaSV,
    sv.HoTen,
    hs.NhomHoSo,
    r.MaMH,
    mh.TenMH,
    r.SoTC,
    r.NamHoc,
    r.HocKy,
    r.LanHoc,
    r.DiemTongKet,
    r.DiemChu,
    r.DiemHe4,
    r.KetQua,
    r.LoaiHoc
FROM ranked r
JOIN SinhVien sv ON r.MaSV = sv.MaSV
JOIN MonHoc mh ON r.MaMH = mh.MaMH
LEFT JOIN HoSoHocTapSinhVien hs ON r.MaSV = hs.MaSV
WHERE r.rn = 1;

CREATE VIEW v_mon_da_dau_sv AS
SELECT *
FROM v_ket_qua_tot_nhat_sv
WHERE KetQua = 'DAT';

CREATE VIEW v_mon_da_rot_sv AS
SELECT DISTINCT
    kq.MaSV,
    sv.HoTen,
    hs.NhomHoSo,
    kq.MaMH,
    mh.TenMH,
    mh.SoTC,
    MIN(kq.NamHoc) AS NamHocRotDauTien,
    MIN(kq.HocKy) AS HocKyRotDauTien,
    COUNT(*) AS SoLanRot
FROM KetQuaHocTap kq
JOIN SinhVien sv ON kq.MaSV = sv.MaSV
JOIN MonHoc mh ON kq.MaMH = mh.MaMH
LEFT JOIN HoSoHocTapSinhVien hs ON kq.MaSV = hs.MaSV
WHERE kq.KetQua = 'KHONG_DAT'
GROUP BY kq.MaSV, sv.HoTen, hs.NhomHoSo, kq.MaMH, mh.TenMH, mh.SoTC;

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
              AND (kq.NamHoc < lhp.NamHoc OR (kq.NamHoc = lhp.NamHoc AND kq.HocKy < lhp.HocKy))
        ) THEN 'CAI_THIEN'
        WHEN EXISTS (
            SELECT 1
            FROM KetQuaHocTap kq
            WHERE kq.MaSV = dk.MaSV
              AND kq.MaMH = lhp.MaMH
              AND kq.KetQua = 'KHONG_DAT'
              AND (kq.NamHoc < lhp.NamHoc OR (kq.NamHoc = lhp.NamHoc AND kq.HocKy < lhp.HocKy))
        ) THEN 'HOC_LAI'
        ELSE 'HOC_MOI'
    END AS LoaiDangKy
FROM DangKy dk
JOIN SinhVien sv ON dk.MaSV = sv.MaSV
JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
LEFT JOIN HoSoHocTapSinhVien hs ON dk.MaSV = hs.MaSV
WHERE lhp.NamHoc = 2026;

CREATE VIEW v_tien_do_ctdt_sv AS
SELECT
    sv.MaSV,
    sv.HoTen,
    hs.NhomHoSo,
    svdd.MaKhoaHoc,
    svdd.TenKhoaHoc,
    svdd.MaCTDT,
    svdd.TenCTDT,
    ctdt.TongTinChiToiThieu,
    COALESCE(SUM(CASE WHEN best.KetQua = 'DAT' THEN mh.SoTC ELSE 0 END), 0) AS TinChiTichLuy,
    COUNT(CASE WHEN best.KetQua = 'DAT' THEN 1 END) AS SoMonDaDau,
    COUNT(CASE WHEN best.KetQua = 'KHONG_DAT' THEN 1 END) AS SoMonChuaDat,
    ROUND(
        100.0 * COALESCE(SUM(CASE WHEN best.KetQua = 'DAT' THEN mh.SoTC ELSE 0 END), 0)
        / NULLIF(ctdt.TongTinChiToiThieu, 0),
        2
    ) AS PhanTramTinChiHoanThanh
FROM SinhVien sv
JOIN v_sinh_vien_day_du svdd ON sv.MaSV = svdd.MaSV
JOIN CTDT ctdt ON svdd.MaCTDT = ctdt.MaCTDT
LEFT JOIN HoSoHocTapSinhVien hs ON sv.MaSV = hs.MaSV
LEFT JOIN v_ket_qua_tot_nhat_sv best ON sv.MaSV = best.MaSV
LEFT JOIN MonHoc mh ON best.MaMH = mh.MaMH
GROUP BY
    sv.MaSV, sv.HoTen, hs.NhomHoSo, svdd.MaKhoaHoc, svdd.TenKhoaHoc,
    svdd.MaCTDT, svdd.TenCTDT, ctdt.TongTinChiToiThieu;

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
            FROM TienQuyet tq
            WHERE tq.MaMH = lhp.MaMH
              AND NOT EXISTS (
                  SELECT 1
                  FROM KetQua kq
                  WHERE kq.MaSV = sv.MaSV
                    AND kq.MaMH = tq.MaMHTQ
                    AND kq.KetQua = 'DAT'
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


def weighted_choice(rng: random.Random, items: Sequence[Tuple[str, float]]) -> str:
    labels = [item[0] for item in items]
    weights = [item[1] for item in items]
    return rng.choices(labels, weights=weights, k=1)[0]


def log_step(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def scalar(conn: sqlite3.Connection, sql: str, params: Tuple[Any, ...] = ()) -> int:
    return int(conn.execute(sql, params).fetchone()[0])


def hash_default_password(ma_sv: str, seed: int) -> Tuple[str, str]:
    password = f"Sv@{ma_sv}".encode("utf-8")
    salt = hashlib.sha256(f"{seed}:hcmute-sis:{ma_sv}".encode("utf-8")).hexdigest()[:32]
    digest = hashlib.pbkdf2_hmac("sha256", password, salt.encode("utf-8"), SO_VONG_LAP_HASH_MAT_KHAU)
    return salt, digest.hex()


def grade_to_letter(score: Optional[float]) -> Tuple[Optional[str], Optional[float]]:
    if score is None:
        return None, None
    if score >= 9.0:
        return "A+", 4.0
    if score >= 8.5:
        return "A", 4.0
    if score >= 8.0:
        return "B+", 3.5
    if score >= 7.0:
        return "B", 3.0
    if score >= 6.5:
        return "C+", 2.5
    if score >= 5.5:
        return "C", 2.0
    if score >= 5.0:
        return "D", 1.0
    return "F", 0.0


def generated_grade(rng: random.Random, ket_qua: str, profile: str, improved: bool = False) -> Tuple[float, float, float, str, float]:
    if ket_qua == "DAT":
        if profile == "DIEM_TB_CAO":
            total = rng.uniform(8.0, 9.8)
        elif profile == "DIEM_TB_THAP":
            total = rng.uniform(5.0, 6.4)
        elif improved:
            total = rng.uniform(7.2, 9.2)
        else:
            total = rng.uniform(5.2, 8.8)
    else:
        if profile == "DIEM_TB_THAP":
            total = rng.uniform(1.5, 4.6)
        else:
            total = rng.uniform(2.5, 4.9)

    process_score = min(10.0, max(0.0, total + rng.uniform(-0.8, 0.8)))
    exam_score = min(10.0, max(0.0, (total - 0.4 * process_score) / 0.6))
    letter, point4 = grade_to_letter(total)
    assert letter is not None and point4 is not None
    return round(process_score, 1), round(exam_score, 1), round(total, 1), letter, point4


def course_term(conn: sqlite3.Connection, ma_mh: str, nam_nhap_hoc: int) -> Tuple[int, int]:
    row = conn.execute("SELECT HKGoiY FROM CTDT_MonHoc WHERE MaMH = ?", (ma_mh,)).fetchone()
    hk_goi_y = row["HKGoiY"] if row else None
    if hk_goi_y is None:
        hk_goi_y = 5
    nam_hoc = nam_nhap_hoc + max(0, (int(hk_goi_y) - 1) // 2)
    nam_hoc = min(nam_hoc, base_builder.ACADEMIC_YEAR - 1)
    hoc_ky = 1 if int(hk_goi_y) % 2 == 1 else 2
    return nam_hoc, hoc_ky


def next_attempt(conn: sqlite3.Connection, ma_sv: str, ma_mh: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(LanHoc), 0) + 1 FROM KetQuaHocTap WHERE MaSV = ? AND MaMH = ?",
        (ma_sv, ma_mh),
    ).fetchone()
    return int(row[0])


def insert_completed_attempt(
    conn: sqlite3.Connection,
    rng: random.Random,
    ma_sv: str,
    ma_mh: str,
    nam_hoc: int,
    hoc_ky: int,
    ket_qua: str,
    loai_hoc: str,
    profile: str,
    ghi_chu: str,
    improved: bool = False,
) -> None:
    diem_qt, diem_thi, diem_tk, diem_chu, diem_he4 = generated_grade(rng, ket_qua, profile, improved=improved)
    conn.execute(
        """
        INSERT INTO KetQuaHocTap
            (
                MaSV, MaMH, MaLHP, LanHoc, NamHoc, HocKy,
                DiemQuaTrinh, DiemThi, DiemTongKet, DiemChu, DiemHe4,
                KetQua, LoaiHoc, GhiChu, ThoiDiemTao
            )
        VALUES (?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ma_sv,
            ma_mh,
            next_attempt(conn, ma_sv, ma_mh),
            nam_hoc,
            hoc_ky,
            diem_qt,
            diem_thi,
            diem_tk,
            diem_chu,
            diem_he4,
            ket_qua,
            loai_hoc,
            ghi_chu,
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def remove_completed_history(conn: sqlite3.Connection, ma_sv: str, ma_mh: str) -> None:
    conn.execute(
        """
        DELETE FROM KetQuaHocTap
        WHERE MaSV = ?
          AND MaMH = ?
          AND KetQua IN ('DAT', 'KHONG_DAT')
        """,
        (ma_sv, ma_mh),
    )


def setup_sis_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(EXTENSION_SCHEMA_SQL)
    conn.commit()


def insert_auth_accounts(conn: sqlite3.Connection, seed: int) -> None:
    created_at = datetime.now().isoformat(timespec="seconds")
    rows = conn.execute("SELECT MaSV FROM SinhVien ORDER BY MaSV").fetchall()
    accounts = []
    for row in rows:
        ma_sv = row["MaSV"]
        salt, password_hash = hash_default_password(ma_sv, seed)
        accounts.append(
            (
                f"TK_{ma_sv}",
                ma_sv,
                f"{ma_sv.lower()}@hcmute.edu.vn",
                password_hash,
                salt,
                THUAT_TOAN_HASH_MAT_KHAU,
                SO_VONG_LAP_HASH_MAT_KHAU,
                created_at,
            )
        )
    conn.executemany(
        """
        INSERT INTO TaiKhoan
            (
                MaTK, MaSV, Email, MatKhauHash, PasswordSalt, ThuatToanHash,
                SoVongLapHash, VaiTro, TrangThai, ThoiDiemTao, LanDangNhapCuoi
            )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'SINH_VIEN', 'HOAT_DONG', ?, NULL)
        """,
        accounts,
    )
    conn.commit()


def insert_semester_config(conn: sqlite3.Connection) -> None:
    semesters = [
        ("2026-1", 2026, 1, "Hoc ky 1 nam hoc 2026", "DANG_MO_DANG_KY", 1, "2026-01-05", "2026-05-31"),
        ("2026-2", 2026, 2, "Hoc ky 2 nam hoc 2026", "DANG_MO_DANG_KY", 1, "2026-08-17", "2026-12-31"),
    ]
    conn.executemany(
        """
        INSERT INTO HocKyHeThong
            (MaHocKy, NamHoc, HocKy, TenHocKy, TrangThai, DangMoDangKy, NgayBatDau, NgayKetThuc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        semesters,
    )
    conn.executemany(
        "INSERT INTO CauHinhDangKy (MaCauHinh, GiaTri, MoTa) VALUES (?, ?, ?)",
        [
            ("SO_TIN_CHI_TOI_DA_MAC_DINH", str(SO_TIN_CHI_TOI_DA_MAC_DINH), "Số tín chỉ tối đa mặc định trong một học kỳ."),
            ("CHO_PHEP_HOC_LAI_CAI_THIEN", "1", "Cho phép sinh viên học lại môn đã đạt để cải thiện điểm."),
            ("TEN_MIEN_EMAIL_SINH_VIEN", "hcmute.edu.vn", "Tên miền email sinh viên."),
        ],
    )
    conn.commit()


def insert_prerequisites(conn: sqlite3.Connection) -> None:
    valid_codes = {row["MaMH"] for row in conn.execute("SELECT MaMH FROM MonHoc")}
    missing: List[str] = []
    for ma_mh, prereqs, _ghi_chu in PREREQUISITES:
        if ma_mh not in valid_codes:
            missing.append(ma_mh)
            continue
        for ma_tq in prereqs:
            if ma_tq not in valid_codes:
                missing.append(ma_tq)
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO QuanHeHocPhan (MaMH, MaMHDieuKien, LoaiQuanHe, GhiChu)
                VALUES (?, ?, 'TIEN_QUYET', ?)
                """,
                (ma_mh, ma_tq, "Tiên quyết theo thiết kế CTĐT V1 của hệ thống."),
            )
            conn.execute(
                "INSERT OR IGNORE INTO TienQuyet (MaMH, MaMHTQ) VALUES (?, ?)",
                (ma_mh, ma_tq),
            )
    if missing:
        raise RuntimeError(f"Prerequisite course codes not found: {sorted(set(missing))}")
    conn.commit()


def viet_hoa_du_lieu_ctdt_bo_sung(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        UPDATE CTDT_NhomTuChon
        SET Nguon = CASE Nguon
            WHEN 'excel_ctdt' THEN 'TAP_TIN_EXCEL_CTDT'
            WHEN 'excel_lua_chon_khong_ma' THEN 'TAP_TIN_EXCEL_LUA_CHON_KHONG_MA'
            ELSE Nguon
        END
        """
    )
    conn.commit()


def bo_bang_lua_chon_khong_ma_duplicate(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_ctdt_nhom_tu_chon;
        DROP TABLE IF EXISTS CTDT_LuaChonKhongMa;

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
            0 AS SoLuaChonKhongMa
        FROM CTDT_NhomTuChon ntc
        ORDER BY ntc.MaNhomTC;
        """
    )
    conn.commit()


def assign_student_profiles(conn: sqlite3.Connection, rng: random.Random) -> Dict[str, str]:
    rows = conn.execute(
        """
        SELECT sv.MaSV, kh.NamNhapHoc
        FROM SinhVien sv
        JOIN KhoaHoc kh ON sv.MaKhoaHoc = kh.MaKhoaHoc
        ORDER BY sv.MaSV
        """
    ).fetchall()
    forced_profiles = list(GHI_CHU_NHOM_HO_SO)
    profiles: Dict[str, str] = {}
    for index, row in enumerate(rows):
        ma_sv = row["MaSV"]
        nam_nhap_hoc = int(row["NamNhapHoc"])
        if index < len(forced_profiles):
            profile = forced_profiles[index]
        else:
            profile = weighted_choice(rng, TRONG_SO_NHOM_HO_SO.get(nam_nhap_hoc, TRONG_SO_NHOM_HO_SO[2024]))
        profiles[ma_sv] = profile
        credit_limit = GIOI_HAN_TIN_CHI_THEO_NHOM.get(profile, SO_TIN_CHI_TOI_DA_MAC_DINH)
        warning = "CANH_BAO" if profile in {"DIEM_TB_THAP", "HOC_LAI_NHIEU"} else None
        conn.execute(
            """
            INSERT INTO HoSoHocTapSinhVien
                (MaSV, NhomHoSo, GioiHanTinChi, CanhBaoHocVu, GhiChu)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ma_sv, profile, credit_limit, warning, GHI_CHU_NHOM_HO_SO[profile]),
        )
    conn.commit()
    return profiles


def populate_detailed_results(conn: sqlite3.Connection, rng: random.Random, profiles: Dict[str, str]) -> None:
    base_rows = conn.execute(
        """
        SELECT kq.MaSV, kq.MaMH, kq.NamHoc, kq.HocKy, kq.KetQua
        FROM KetQua kq
        ORDER BY kq.MaSV, kq.MaMH
        """
    ).fetchall()
    created_at = datetime.now().isoformat(timespec="seconds")
    for row in base_rows:
        ma_sv = row["MaSV"]
        profile = profiles.get(ma_sv, "DUNG_TIEN_DO")
        ket_qua = row["KetQua"]
        diem_qt, diem_thi, diem_tk, diem_chu, diem_he4 = generated_grade(rng, ket_qua, profile)
        conn.execute(
            """
            INSERT INTO KetQuaHocTap
                (
                    MaSV, MaMH, MaLHP, LanHoc, NamHoc, HocKy,
                    DiemQuaTrinh, DiemThi, DiemTongKet, DiemChu, DiemHe4,
                    KetQua, LoaiHoc, GhiChu, ThoiDiemTao
                )
            VALUES (?, ?, NULL, 1, ?, ?, ?, ?, ?, ?, ?, ?, 'HOC_MOI', 'Nhập từ bảng KetQua tổng hợp', ?)
            """,
            (
                ma_sv,
                row["MaMH"],
                row["NamHoc"] or 2025,
                row["HocKy"] or 1,
                diem_qt,
                diem_thi,
                diem_tk,
                diem_chu,
                diem_he4,
                ket_qua,
                created_at,
            ),
        )
    conn.commit()


def enforce_profile_scenarios(conn: sqlite3.Connection, rng: random.Random, profiles: Dict[str, str]) -> None:
    student_year = {
        row["MaSV"]: int(row["NamNhapHoc"])
        for row in conn.execute(
            """
            SELECT sv.MaSV, kh.NamNhapHoc
            FROM SinhVien sv
            JOIN KhoaHoc kh ON sv.MaKhoaHoc = kh.MaKhoaHoc
            """
        )
    }
    scenario_fail_courses = {
        "ROT_DAI_CUONG": ["MATH132401E", "MATH132501E", "MATH143001E", "PHYS130902E", "ACEN340535E"],
        "ROT_NEN_TANG_CNTT": ["INPR130285E", "PRTE230385E", "DASA230179E", "OOPR230279E", "DBSY230184E"],
        "THIEU_TIEN_QUYET": ["DBSY230184E", "MATH132901E", "MAAI330985E", "INSE330380E"],
        "DIEM_TB_THAP": ["INPR130285E", "MATH132401E", "DBSY230184E", "OOPR230279E", "NEES330380E"],
    }
    retake_courses = ["INPR130285E", "PRTE230385E", "DASA230179E", "DBSY230184E", "OOPR230279E", "MATH132401E"]
    improvement_courses = ["INPR130285E", "PRTE230385E", "DBSY230184E", "OOPR230279E", "WEPR330479E", "DBMS330284E"]
    graduation_courses = [
        "INPR130285E",
        "PRTE230385E",
        "DASA230179E",
        "OOPR230279E",
        "DBSY230184E",
        "DBMS330284E",
        "SOEN330679E",
        "PROJ312979E",
        "PROJ313079E",
    ]

    for ma_sv, profile in profiles.items():
        nam_nhap_hoc = student_year[ma_sv]
        if profile in scenario_fail_courses:
            for ma_mh in rng.sample(scenario_fail_courses[profile], k=min(2, len(scenario_fail_courses[profile]))):
                remove_completed_history(conn, ma_sv, ma_mh)
                nam_hoc, hoc_ky = course_term(conn, ma_mh, nam_nhap_hoc)
                insert_completed_attempt(
                    conn,
                    rng,
                    ma_sv,
                    ma_mh,
                    nam_hoc,
                    hoc_ky,
                    "KHONG_DAT",
                    "HOC_MOI",
                    profile,
                    GHI_CHU_NHOM_HO_SO[profile],
                )

        if profile == "HOC_LAI_NHIEU":
            for ma_mh in rng.sample(retake_courses, k=4):
                remove_completed_history(conn, ma_sv, ma_mh)
                nam_hoc, hoc_ky = course_term(conn, ma_mh, nam_nhap_hoc)
                insert_completed_attempt(
                    conn, rng, ma_sv, ma_mh, nam_hoc, hoc_ky, "KHONG_DAT", "HOC_MOI", profile, "Kịch bản học lại - lần đầu không đạt"
                )
                insert_completed_attempt(
                    conn,
                    rng,
                    ma_sv,
                    ma_mh,
                    min(nam_hoc + 1, base_builder.ACADEMIC_YEAR - 1),
                    hoc_ky,
                    "DAT",
                    "HOC_LAI",
                    profile,
                    "Kịch bản học lại - lần sau đạt",
                    improved=True,
                )

        if profile == "CAI_THIEN_DIEM":
            for ma_mh in rng.sample(improvement_courses, k=3):
                remove_completed_history(conn, ma_sv, ma_mh)
                nam_hoc, hoc_ky = course_term(conn, ma_mh, nam_nhap_hoc)
                insert_completed_attempt(
                    conn, rng, ma_sv, ma_mh, nam_hoc, hoc_ky, "DAT", "HOC_MOI", profile, "Lần học đầu đã đạt"
                )
                insert_completed_attempt(
                    conn,
                    rng,
                    ma_sv,
                    ma_mh,
                    min(nam_hoc + 1, base_builder.ACADEMIC_YEAR - 1),
                    hoc_ky,
                    "DAT",
                    "CAI_THIEN",
                    profile,
                    "Học cải thiện điểm",
                    improved=True,
                )

        if profile == "GAN_TOT_NGHIEP":
            for ma_mh in graduation_courses:
                passed = conn.execute(
                    """
                    SELECT 1
                    FROM KetQuaHocTap
                    WHERE MaSV = ?
                      AND MaMH = ?
                      AND KetQua = 'DAT'
                    LIMIT 1
                    """,
                    (ma_sv, ma_mh),
                ).fetchone()
                if passed:
                    continue
                nam_hoc, hoc_ky = course_term(conn, ma_mh, nam_nhap_hoc)
                insert_completed_attempt(
                    conn, rng, ma_sv, ma_mh, nam_hoc, hoc_ky, "DAT", "HOC_MOI", profile, "Bổ sung môn đã đạt cho sinh viên gần tốt nghiệp"
                )

    conn.commit()


def add_current_study_attempts(conn: sqlite3.Connection) -> None:
    created_at = datetime.now().isoformat(timespec="seconds")
    conn.executescript(
        """
        DROP TABLE IF EXISTS temp.tmp_current_reg;
        DROP TABLE IF EXISTS temp.tmp_current_max_attempt;
        DROP TABLE IF EXISTS temp.tmp_current_prior;

        CREATE TEMP TABLE tmp_current_reg AS
        SELECT
            dk.MaSV,
            lhp.MaMH,
            dk.MaLHP,
            lhp.NamHoc,
            lhp.HocKy,
            ROW_NUMBER() OVER (
                PARTITION BY dk.MaSV, lhp.MaMH
                ORDER BY lhp.NamHoc, lhp.HocKy, dk.MaLHP
            ) AS rn
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP;

        CREATE INDEX tmp_current_reg_key ON tmp_current_reg(MaSV, MaMH);

        CREATE TEMP TABLE tmp_current_max_attempt AS
        SELECT MaSV, MaMH, MAX(LanHoc) AS MaxLanHoc
        FROM KetQuaHocTap
        GROUP BY MaSV, MaMH;

        CREATE INDEX tmp_current_max_attempt_key ON tmp_current_max_attempt(MaSV, MaMH);

        CREATE TEMP TABLE tmp_current_prior AS
        SELECT
            reg.MaSV,
            reg.MaMH,
            reg.MaLHP,
            MAX(CASE WHEN kq.KetQua = 'DAT' THEN 1 ELSE 0 END) AS HasPassed,
            MAX(CASE WHEN kq.KetQua = 'KHONG_DAT' THEN 1 ELSE 0 END) AS HasFailed
        FROM tmp_current_reg reg
        LEFT JOIN KetQuaHocTap kq
          ON kq.MaSV = reg.MaSV
         AND kq.MaMH = reg.MaMH
         AND kq.KetQua IN ('DAT', 'KHONG_DAT')
         AND (kq.NamHoc < reg.NamHoc OR (kq.NamHoc = reg.NamHoc AND kq.HocKy < reg.HocKy))
        GROUP BY reg.MaSV, reg.MaMH, reg.MaLHP;

        CREATE INDEX tmp_current_prior_key ON tmp_current_prior(MaSV, MaMH, MaLHP);
        """
    )
    conn.execute(
        """
        INSERT INTO KetQuaHocTap
            (
                MaSV, MaMH, MaLHP, LanHoc, NamHoc, HocKy,
                DiemQuaTrinh, DiemThi, DiemTongKet, DiemChu, DiemHe4,
                KetQua, LoaiHoc, GhiChu, ThoiDiemTao
            )
        SELECT
            reg.MaSV,
            reg.MaMH,
            reg.MaLHP,
            COALESCE(max_attempt.MaxLanHoc, 0) + reg.rn AS LanHoc,
            reg.NamHoc,
            reg.HocKy,
            NULL,
            NULL,
            NULL,
            NULL,
            NULL,
            'DANG_HOC',
            CASE
                WHEN COALESCE(prior.HasPassed, 0) > 0 THEN 'CAI_THIEN'
                WHEN COALESCE(prior.HasFailed, 0) > 0 THEN 'HOC_LAI'
                ELSE 'HOC_MOI'
            END AS LoaiHoc,
            'Đăng ký hiện tại',
            ?
        FROM tmp_current_reg reg
        LEFT JOIN tmp_current_max_attempt max_attempt
          ON reg.MaSV = max_attempt.MaSV
         AND reg.MaMH = max_attempt.MaMH
        LEFT JOIN tmp_current_prior prior
          ON reg.MaSV = prior.MaSV
         AND reg.MaMH = prior.MaMH
         AND reg.MaLHP = prior.MaLHP
        """,
        (created_at,),
    )
    conn.executescript(
        """
        DROP TABLE IF EXISTS temp.tmp_current_reg;
        DROP TABLE IF EXISTS temp.tmp_current_max_attempt;
        DROP TABLE IF EXISTS temp.tmp_current_prior;
        """
    )
    conn.commit()


def rebuild_ket_qua_summary(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM KetQua")
    conn.execute(
        """
        INSERT INTO KetQua (MaSV, MaMH, NamHoc, HocKy, KetQua)
        WITH ranked AS (
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
                        COALESCE(DiemTongKet, -1) DESC,
                        NamHoc DESC,
                        HocKy DESC,
                        LanHoc DESC
                ) AS rn
            FROM KetQuaHocTap
            WHERE KetQua IN ('DAT', 'KHONG_DAT')
        )
        SELECT MaSV, MaMH, NamHoc, HocKy, KetQua
        FROM ranked
        WHERE rn = 1
        """
    )
    conn.commit()


def update_student_profile_metrics(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS temp.tmp_best_kq;
        DROP TABLE IF EXISTS temp.tmp_pass_agg;
        DROP TABLE IF EXISTS temp.tmp_fail_agg;
        DROP TABLE IF EXISTS temp.tmp_repeat_agg;
        DROP TABLE IF EXISTS temp.tmp_current_credit_agg;

        CREATE TEMP TABLE tmp_best_kq AS
        WITH ranked AS (
            SELECT
                kq.MaSV,
                kq.MaMH,
                mh.SoTC,
                kq.DiemHe4,
                kq.KetQua,
                ROW_NUMBER() OVER (
                    PARTITION BY kq.MaSV, kq.MaMH
                    ORDER BY
                        CASE WHEN kq.KetQua = 'DAT' THEN 1 ELSE 0 END DESC,
                        COALESCE(kq.DiemTongKet, -1) DESC,
                        kq.NamHoc DESC,
                        kq.HocKy DESC,
                        kq.LanHoc DESC
                ) AS rn
            FROM KetQuaHocTap kq
            JOIN MonHoc mh ON kq.MaMH = mh.MaMH
            WHERE kq.KetQua IN ('DAT', 'KHONG_DAT')
        )
        SELECT MaSV, MaMH, SoTC, DiemHe4, KetQua
        FROM ranked
        WHERE rn = 1;

        CREATE INDEX tmp_best_kq_masv ON tmp_best_kq(MaSV);

        CREATE TEMP TABLE tmp_pass_agg AS
        SELECT
            MaSV,
            COUNT(*) AS SoMonDaDau,
            SUM(SoTC) AS TinChiTichLuy,
            ROUND(SUM(COALESCE(DiemHe4, 0) * SoTC) / NULLIF(SUM(SoTC), 0), 2) AS GPA
        FROM tmp_best_kq
        WHERE KetQua = 'DAT'
        GROUP BY MaSV;

        CREATE TEMP TABLE tmp_fail_agg AS
        SELECT MaSV, COUNT(DISTINCT MaMH) AS SoMonTungRot
        FROM KetQuaHocTap
        WHERE KetQua = 'KHONG_DAT'
        GROUP BY MaSV;

        CREATE TEMP TABLE tmp_repeat_agg AS
        SELECT MaSV, COUNT(*) AS SoLanHocLaiCaiThien
        FROM KetQuaHocTap
        WHERE LoaiHoc IN ('HOC_LAI', 'CAI_THIEN')
        GROUP BY MaSV;

        CREATE TEMP TABLE tmp_current_credit_agg AS
        SELECT dk.MaSV, COALESCE(SUM(mh.SoTC), 0) AS TinChiDangKyHienTai
        FROM DangKy dk
        JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
        JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
        WHERE lhp.NamHoc = 2026
        GROUP BY dk.MaSV;

        UPDATE HoSoHocTapSinhVien
        SET GPA = (SELECT GPA FROM tmp_pass_agg WHERE tmp_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV),
            TinChiTichLuy = COALESCE((SELECT TinChiTichLuy FROM tmp_pass_agg WHERE tmp_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            SoMonDaDau = COALESCE((SELECT SoMonDaDau FROM tmp_pass_agg WHERE tmp_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            SoMonTungRot = COALESCE((SELECT SoMonTungRot FROM tmp_fail_agg WHERE tmp_fail_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            SoLanHocLaiCaiThien = COALESCE((SELECT SoLanHocLaiCaiThien FROM tmp_repeat_agg WHERE tmp_repeat_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            TinChiDangKyHienTai = COALESCE((SELECT TinChiDangKyHienTai FROM tmp_current_credit_agg WHERE tmp_current_credit_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0),
            CanhBaoHocVu = CASE
                WHEN (SELECT GPA FROM tmp_pass_agg WHERE tmp_pass_agg.MaSV = HoSoHocTapSinhVien.MaSV) < 2.0 THEN 'CANH_BAO_DIEM_TB_THAP'
                WHEN COALESCE((SELECT SoMonTungRot FROM tmp_fail_agg WHERE tmp_fail_agg.MaSV = HoSoHocTapSinhVien.MaSV), 0) >= 5 THEN 'CANH_BAO_NO_MON'
                ELSE CanhBaoHocVu
            END;

        DROP TABLE IF EXISTS temp.tmp_best_kq;
        DROP TABLE IF EXISTS temp.tmp_pass_agg;
        DROP TABLE IF EXISTS temp.tmp_fail_agg;
        DROP TABLE IF EXISTS temp.tmp_repeat_agg;
        DROP TABLE IF EXISTS temp.tmp_current_credit_agg;
        """
    )
    conn.commit()


def apply_sis_views(conn: sqlite3.Connection) -> None:
    conn.executescript(SIS_VIEWS_SQL)
    conn.commit()


def update_meta(conn: sqlite3.Connection, seed: int) -> None:
    doi_ten_meta = {
        "source_excel": "DUONG_DAN_EXCEL_NGUON",
        "generated_at": "THOI_DIEM_TAO_CTDT",
        "builder": "SCRIPT_TAO_CTDT",
        "random_seed": "SEED_NGAU_NHIEN_CTDT",
        "raw_excel_rows": "SO_DONG_EXCEL_THO",
        "official_course_rows": "SO_MON_HOC_CO_MA",
        "elective_group_count": "SO_NHOM_TU_CHON",
        "no_code_option_count": "SO_LUA_CHON_KHONG_MA",
    }
    for key, value in conn.execute("SELECT Key, Value FROM Meta"):
        conn.execute(
            "INSERT OR REPLACE INTO ThongTinTaoDuLieu (MaThongTin, GiaTri) VALUES (?, ?)",
            (doi_ten_meta.get(key, key.upper()), value),
        )

    thong_tin_sis = {
        "SCRIPT_TAO_SIS": "scripts/build_ctdt_sis_db.py",
        "THOI_DIEM_TAO_SIS": datetime.now().isoformat(timespec="seconds"),
        "SEED_NGAU_NHIEN_SIS": str(seed),
        "THUAT_TOAN_HASH_MAT_KHAU": THUAT_TOAN_HASH_MAT_KHAU,
        "SO_VONG_LAP_HASH_MAT_KHAU": str(SO_VONG_LAP_HASH_MAT_KHAU),
        "DINH_DANG_MAT_KHAU_MAC_DINH": "Sv@[MSSV]",
        "CHO_PHEP_HOC_LAI_CAI_THIEN": "1",
        "SO_CAP_TIEN_QUYET_V1": str(scalar(conn, "SELECT COUNT(*) FROM TienQuyet")),
    }
    for key, value in thong_tin_sis.items():
        conn.execute("INSERT OR REPLACE INTO ThongTinTaoDuLieu (MaThongTin, GiaTri) VALUES (?, ?)", (key, value))

    conn.execute("DROP TABLE IF EXISTS Meta")
    conn.commit()


def validate_prerequisite_graph(conn: sqlite3.Connection) -> List[str]:
    graph: Dict[str, List[str]] = {}
    for row in conn.execute("SELECT MaMH, MaMHTQ FROM TienQuyet"):
        graph.setdefault(row["MaMH"], []).append(row["MaMHTQ"])

    errors: List[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, path: List[str]) -> None:
        if node in visiting:
            cycle = path[path.index(node) :] + [node] if node in path else path + [node]
            errors.append("Prerequisite cycle: " + " -> ".join(cycle))
            return
        if node in visited:
            return
        visiting.add(node)
        for nxt in graph.get(node, []):
            dfs(nxt, path + [nxt])
        visiting.remove(node)
        visited.add(node)

    for node in list(graph):
        dfs(node, [node])
    return errors


def validate_sis_database(conn: sqlite3.Connection) -> List[str]:
    errors: List[str] = []
    fk_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_errors:
        errors.append(f"Foreign key errors: {fk_errors[:5]}")

    student_count = scalar(conn, "SELECT COUNT(*) FROM SinhVien")
    account_count = scalar(conn, "SELECT COUNT(*) FROM TaiKhoan WHERE VaiTro = 'SINH_VIEN'")
    if account_count != student_count:
        errors.append(f"Student account count mismatch: students={student_count}, accounts={account_count}")

    plaintext_like = scalar(
        conn,
        "SELECT COUNT(*) FROM TaiKhoan WHERE MatKhauHash LIKE 'Sv@%' OR PasswordSalt LIKE 'Sv@%'",
    )
    if plaintext_like:
        errors.append("Password material appears to contain plaintext default password.")

    prereq_pairs = scalar(conn, "SELECT COUNT(*) FROM TienQuyet")
    if prereq_pairs < 90:
        errors.append(f"Too few prerequisite pairs inserted: {prereq_pairs}")

    detail_count = scalar(conn, "SELECT COUNT(*) FROM KetQuaHocTap")
    if detail_count <= scalar(conn, "SELECT COUNT(*) FROM KetQua"):
        errors.append("Detailed study-result table is not richer than KetQua summary.")

    current_count = scalar(conn, "SELECT COUNT(*) FROM KetQuaHocTap WHERE KetQua = 'DANG_HOC'")
    if current_count != scalar(conn, "SELECT COUNT(*) FROM DangKy"):
        errors.append(f"Current study attempts mismatch DangKy rows: current={current_count}")

    for profile in GHI_CHU_NHOM_HO_SO:
        count = scalar(conn, "SELECT COUNT(*) FROM HoSoHocTapSinhVien WHERE NhomHoSo = ?", (profile,))
        if count == 0:
            errors.append(f"Missing student profile group: {profile}")

    errors.extend(validate_prerequisite_graph(conn))
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        errors.append(f"Integrity check failed: {integrity}")
    return errors


def build_summary(conn: sqlite3.Connection) -> Dict[str, Any]:
    tables = [
        "SinhVien",
        "TaiKhoan",
        "HoSoHocTapSinhVien",
        "MonHoc",
        "QuanHeHocPhan",
        "TienQuyet",
        "KetQua",
        "KetQuaHocTap",
        "LopHP",
        "DangKy",
    ]
    status_rows = conn.execute(
        """
        SELECT KetQua, COUNT(*) AS SoDong
        FROM KetQuaHocTap
        GROUP BY KetQua
        ORDER BY KetQua
        """
    ).fetchall()
    profile_rows = conn.execute(
        """
        SELECT NhomHoSo, COUNT(*) AS SoSinhVien
        FROM HoSoHocTapSinhVien
        GROUP BY NhomHoSo
        ORDER BY SoSinhVien DESC, NhomHoSo
        """
    ).fetchall()
    prereq_top = conn.execute(
        """
        SELECT tq.MaMH, mh.TenMH, COUNT(*) AS SoTienQuyet
        FROM TienQuyet tq
        JOIN MonHoc mh ON tq.MaMH = mh.MaMH
        GROUP BY tq.MaMH, mh.TenMH
        ORDER BY SoTienQuyet DESC, tq.MaMH
        LIMIT 10
        """
    ).fetchall()
    sample_students = [row["MaSV"] for row in conn.execute("SELECT MaSV FROM SinhVien ORDER BY MaSV LIMIT 25")]
    eligibility_counts: Counter[int] = Counter()
    for ma_sv in sample_students:
        rows = conn.execute(
            """
            SELECT CoTheDangKy, COUNT(*) AS SoDong
            FROM v_dieu_kien_dang_ky_mon_sv
            WHERE MaSV = ?
              AND TrangThaiLHP IN ('MO', 'DAY')
            GROUP BY CoTheDangKy
            """,
            (ma_sv,),
        ).fetchall()
        for row in rows:
            eligibility_counts[int(row["CoTheDangKy"])] += int(row["SoDong"])
    return {
        "row_counts": {table: scalar(conn, f"SELECT COUNT(*) FROM {table}") for table in tables},
        "study_result_status": [dict(row) for row in status_rows],
        "profile_distribution": [dict(row) for row in profile_rows],
        "top_prerequisite_courses": [dict(row) for row in prereq_top],
        "eligibility_distribution_sample": [
            {"CoTheDangKy": key, "SoDong": eligibility_counts[key]}
            for key in sorted(eligibility_counts, reverse=True)
        ],
        "sample_accounts": [
            dict(row)
            for row in conn.execute(
                """
                SELECT MaSV, Email, VaiTro, TrangThaiTaiKhoan, NhomHoSo
                FROM v_tai_khoan_sinh_vien
                LEFT JOIN HoSoHocTapSinhVien USING (MaSV)
                ORDER BY MaSV
                LIMIT 5
                """
            )
        ],
    }


def print_summary(summary: Dict[str, Any], output_path: Path) -> None:
    print(f"SIS database generated: {output_path}")
    print("\n=== Row counts ===")
    for table, count in summary["row_counts"].items():
        print(f"{table:24s} {count}")
    print("\n=== Study-result status ===")
    for row in summary["study_result_status"]:
        print(f"{row['KetQua']:10s} {row['SoDong']}")
    print("\n=== Student profile distribution ===")
    for row in summary["profile_distribution"]:
        print(f"{row['NhomHoSo']:22s} {row['SoSinhVien']}")
    print("\n=== Eligibility distribution sample ===")
    for row in summary["eligibility_distribution_sample"]:
        print(f"CoTheDangKy={row['CoTheDangKy']} {row['SoDong']}")
    print("\n=== Top prerequisite-heavy courses ===")
    for row in summary["top_prerequisite_courses"]:
        print(f"{row['MaMH']:12s} {row['SoTienQuyet']} {row['TenMH']}")
    print("\n=== Sample student accounts ===")
    for row in summary["sample_accounts"]:
        print(row)


def extend_database(conn: sqlite3.Connection, seed: int) -> Dict[str, Any]:
    rng = random.Random(seed)
    log_step("setup_sis_schema")
    setup_sis_schema(conn)
    log_step("insert_auth_accounts")
    insert_auth_accounts(conn, seed)
    log_step("insert_semester_config")
    insert_semester_config(conn)
    log_step("insert_prerequisites")
    insert_prerequisites(conn)
    log_step("viet_hoa_du_lieu_ctdt_bo_sung")
    viet_hoa_du_lieu_ctdt_bo_sung(conn)
    log_step("bo_bang_lua_chon_khong_ma_duplicate")
    bo_bang_lua_chon_khong_ma_duplicate(conn)
    log_step("assign_student_profiles")
    profiles = assign_student_profiles(conn, rng)
    log_step("populate_detailed_results")
    populate_detailed_results(conn, rng, profiles)
    log_step("enforce_profile_scenarios")
    enforce_profile_scenarios(conn, rng, profiles)
    log_step("add_current_study_attempts")
    add_current_study_attempts(conn)
    log_step("rebuild_ket_qua_summary")
    rebuild_ket_qua_summary(conn)
    log_step("update_student_profile_metrics")
    update_student_profile_metrics(conn)
    log_step("apply_sis_views")
    apply_sis_views(conn)
    log_step("update_meta")
    update_meta(conn, seed)
    log_step("validate_sis_database")
    errors = validate_sis_database(conn)
    if errors:
        raise RuntimeError("SIS database validation failed:\n" + "\n".join(f"- {error}" for error in errors))
    log_step("build_summary")
    return build_summary(conn)


def create_database(
    excel_path: Path,
    output_path: Path,
    views_path: Path,
    seed: int,
    force: bool = False,
) -> Dict[str, Any]:
    if output_path.exists() and not force:
        raise FileExistsError(f"Refusing to overwrite existing database: {output_path}")
    if output_path.exists() and force:
        output_path.unlink()

    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp_path.exists():
        temp_path.unlink()

    log_step("build_base_ctdt_database")
    base_builder.create_database(
        excel_path=excel_path,
        output_path=temp_path,
        views_path=views_path,
        seed=base_builder.RANDOM_SEED,
    )
    log_step("extend_base_database")

    conn = sqlite3.connect(temp_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")
    try:
        summary = extend_database(conn, seed)
        conn.commit()
    finally:
        conn.close()

    temp_path.replace(output_path)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ctdt_sis.db with auth, student profiles, prerequisites, and SIS views.")
    parser.add_argument("--excel", type=Path, default=DEFAULT_EXCEL_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--views", type=Path, default=DEFAULT_VIEWS_PATH)
    parser.add_argument("--seed", type=int, default=RANDOM_SEED)
    parser.add_argument("--force", action="store_true", help="Overwrite output if it already exists.")
    args = parser.parse_args()

    summary = create_database(
        excel_path=args.excel,
        output_path=args.output,
        views_path=args.views,
        seed=args.seed,
        force=args.force,
    )
    print_summary(summary, args.output)


if __name__ == "__main__":
    main()
