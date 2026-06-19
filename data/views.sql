-- view dung cho nl2sql
-- giu schema goc gon, nhung cho model hoi tren bang de hon

DROP VIEW IF EXISTS v_tin_chi_dang_ky_sv;
DROP VIEW IF EXISTS v_ket_qua_day_du;
DROP VIEW IF EXISTS v_dang_ky_day_du;
DROP VIEW IF EXISTS v_lop_hoc_phan_day_du;
DROP VIEW IF EXISTS v_lop_hoc_phan_lich;
DROP VIEW IF EXISTS v_tien_quyet_day_du;
DROP VIEW IF EXISTS v_mon_hoc_ctdt;
DROP VIEW IF EXISTS v_sinh_vien_day_du;

-- sinh vien kem nganh, khoa hoc, chuong trinh dao tao
CREATE VIEW v_sinh_vien_day_du AS
SELECT
    sv.MaSV,
    sv.HoTen,
    sv.TrangThai AS TrangThaiSV,
    kh.MaKhoaHoc,
    kh.TenKhoaHoc,
    kh.NamNhapHoc,
    ctdt.MaCTDT,
    ctdt.TenCTDT,
    n.MaNganh,
    n.TenNganh
FROM SinhVien sv
JOIN KhoaHoc kh ON sv.MaKhoaHoc = kh.MaKhoaHoc
JOIN CTDT ctdt ON kh.MaCTDT = ctdt.MaCTDT
JOIN Nganh n ON kh.MaNganh = n.MaNganh;

-- mon hoc theo tung chuong trinh dao tao
CREATE VIEW v_mon_hoc_ctdt AS
SELECT
    mh.MaMH,
    mh.TenMH,
    mh.SoTC,
    ctdt.MaCTDT,
    ctdt.TenCTDT,
    n.MaNganh,
    n.TenNganh,
    ctdt_mh.LoaiYC,
    ctdt_mh.HKGoiY
FROM CTDT_MonHoc ctdt_mh
JOIN MonHoc mh ON ctdt_mh.MaMH = mh.MaMH
JOIN CTDT ctdt ON ctdt_mh.MaCTDT = ctdt.MaCTDT
JOIN Nganh n ON ctdt.MaNganh = n.MaNganh;

-- mon tien quyet, da noi san ten mon
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

-- moi dong la mot buoi hoc cua lop hoc phan
-- view nay hop voi cau hoi loc thu, tiet, buoi, phong, giang vien
CREATE VIEW v_lop_hoc_phan_lich AS
SELECT
    lhp.MaLHP,
    lhp.Nhom,
    lhp.MaMH,
    mh.TenMH,
    mh.SoTC,
    lhp.NamHoc,
    lhp.HocKy,
    lhp.TrangThai AS TrangThaiLHP,
    lhp.SiSoTD,
    lhp.SiSoDK,
    CASE
        WHEN lhp.SiSoTD - lhp.SiSoDK > 0 THEN lhp.SiSoTD - lhp.SiSoDK
        ELSE 0
    END AS SoChoCon,
    CASE
        WHEN lhp.TrangThai = 'MO' AND lhp.SiSoDK < lhp.SiSoTD THEN 1
        ELSE 0
    END AS CoTheDangKy,
    lh.MaLich,
    lh.Thu,
    'thu ' || lh.Thu AS ThuText,
    lh.TietBD,
    lh.TietKT,
    'tiet ' || lh.TietBD || '-' || lh.TietKT AS TietText,
    CASE
        WHEN lh.TietKT <= 6 THEN 'SANG'
        WHEN lh.TietBD >= 7 THEN 'CHIEU'
        ELSE 'KHAC'
    END AS Buoi,
    lh.MaPhong,
    p.DayNha,
    gv.MaGV,
    gv.TenGV
FROM LopHP lhp
JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
LEFT JOIN LichHoc lh ON lhp.MaLHP = lh.MaLHP
LEFT JOIN Phong p ON lh.MaPhong = p.MaPhong
LEFT JOIN PhanCong pc
    ON lhp.MaLHP = pc.MaLHP
   AND pc.VaiTro = 'GIANG_VIEN_CHINH'
LEFT JOIN GiangVien gv ON pc.MaGV = gv.MaGV;

-- moi dong la mot lop hoc phan, lich hoc duoc gom thanh chuoi
-- view nay hop voi cau hoi xem danh sach lop
CREATE VIEW v_lop_hoc_phan_day_du AS
SELECT
    lhp.MaLHP,
    lhp.Nhom,
    lhp.MaMH,
    mh.TenMH,
    mh.SoTC,
    lhp.NamHoc,
    lhp.HocKy,
    lhp.TrangThai AS TrangThaiLHP,
    lhp.SiSoTD,
    lhp.SiSoDK,
    CASE
        WHEN lhp.SiSoTD - lhp.SiSoDK > 0 THEN lhp.SiSoTD - lhp.SiSoDK
        ELSE 0
    END AS SoChoCon,
    CASE
        WHEN lhp.TrangThai = 'MO' AND lhp.SiSoDK < lhp.SiSoTD THEN 1
        ELSE 0
    END AS CoTheDangKy,
    (
        SELECT GROUP_CONCAT(
            'thu ' || lh.Thu
            || ' tiet ' || lh.TietBD || '-' || lh.TietKT
            || ' phong ' || lh.MaPhong,
            '; '
        )
        FROM LichHoc lh
        WHERE lh.MaLHP = lhp.MaLHP
    ) AS LichHocText,
    (
        SELECT GROUP_CONCAT(DISTINCT
            CASE
                WHEN lh.TietKT <= 6 THEN 'SANG'
                WHEN lh.TietBD >= 7 THEN 'CHIEU'
                ELSE 'KHAC'
            END
        )
        FROM LichHoc lh
        WHERE lh.MaLHP = lhp.MaLHP
    ) AS BuoiText,
    (
        SELECT GROUP_CONCAT(DISTINCT 'thu ' || lh.Thu)
        FROM LichHoc lh
        WHERE lh.MaLHP = lhp.MaLHP
    ) AS ThuText,
    (
        SELECT GROUP_CONCAT(DISTINCT gv.TenGV)
        FROM PhanCong pc
        JOIN GiangVien gv ON pc.MaGV = gv.MaGV
        WHERE pc.MaLHP = lhp.MaLHP
          AND pc.VaiTro = 'GIANG_VIEN_CHINH'
    ) AS TenGV
FROM LopHP lhp
JOIN MonHoc mh ON lhp.MaMH = mh.MaMH;

-- dang ky da noi san sinh vien va lop hoc phan
CREATE VIEW v_dang_ky_day_du AS
SELECT
    dk.MaSV,
    sv.HoTen,
    sv.TrangThaiSV,
    sv.MaNganh,
    sv.TenNganh,
    sv.MaKhoaHoc,
    sv.TenKhoaHoc,
    sv.MaCTDT,
    dk.MaLHP,
    lhp.Nhom,
    lhp.MaMH,
    lhp.TenMH,
    lhp.SoTC,
    lhp.NamHoc,
    lhp.HocKy,
    lhp.TrangThaiLHP,
    lhp.SiSoTD,
    lhp.SiSoDK,
    lhp.SoChoCon,
    lhp.CoTheDangKy,
    lhp.LichHocText,
    lhp.BuoiText,
    lhp.ThuText,
    lhp.TenGV,
    dk.TGDK
FROM DangKy dk
JOIN v_sinh_vien_day_du sv ON dk.MaSV = sv.MaSV
JOIN v_lop_hoc_phan_day_du lhp ON dk.MaLHP = lhp.MaLHP;

-- ket qua hoc tap da noi san sinh vien va mon hoc
CREATE VIEW v_ket_qua_day_du AS
SELECT
    kq.MaSV,
    sv.HoTen,
    sv.TrangThaiSV,
    sv.MaNganh,
    sv.TenNganh,
    sv.MaKhoaHoc,
    sv.TenKhoaHoc,
    sv.MaCTDT,
    kq.MaMH,
    mh.TenMH,
    mh.SoTC,
    kq.NamHoc,
    kq.HocKy,
    kq.KetQua
FROM KetQua kq
JOIN v_sinh_vien_day_du sv ON kq.MaSV = sv.MaSV
JOIN MonHoc mh ON kq.MaMH = mh.MaMH;

-- tong tin chi sinh vien da dang ky theo nam hoc, hoc ky
CREATE VIEW v_tin_chi_dang_ky_sv AS
SELECT
    MaSV,
    HoTen,
    MaNganh,
    TenNganh,
    MaKhoaHoc,
    TenKhoaHoc,
    MaCTDT,
    NamHoc,
    HocKy,
    COUNT(DISTINCT MaLHP) AS SoLopDaDangKy,
    COUNT(DISTINCT MaMH) AS SoMonDaDangKy,
    SUM(SoTC) AS TongTinChiDangKy
FROM v_dang_ky_day_du
GROUP BY
    MaSV,
    HoTen,
    MaNganh,
    TenNganh,
    MaKhoaHoc,
    TenKhoaHoc,
    MaCTDT,
    NamHoc,
    HocKy;
