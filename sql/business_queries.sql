-- sql nghiep vu phuc tap cho phase 6
-- cac query dung named parameter kieu :ma_sv, :ma_lhp

-- 1. mon tien quyet sinh vien con thieu cho mot mon
-- params: :ma_sv, :ma_mh
WITH missing_prerequisites AS (
    SELECT
        tq.MaMH,
        tq.TenMH,
        tq.MaMHTQ,
        tq.TenMHTQ
    FROM v_tien_quyet_day_du tq
    LEFT JOIN KetQua kq
        ON kq.MaSV = :ma_sv
       AND kq.MaMH = tq.MaMHTQ
       AND kq.KetQua = 'DAT'
    WHERE tq.MaMH = :ma_mh
      AND kq.MaMH IS NULL
)
SELECT * FROM missing_prerequisites;

-- 2. lop dang ky hien tai bi trung lich voi lop muc tieu
-- params: :ma_sv, :ma_lhp
WITH target AS (
    SELECT
        lhp.MaLHP,
        lhp.MaMH,
        lhp.NamHoc,
        lhp.HocKy
    FROM LopHP lhp
    WHERE lhp.MaLHP = :ma_lhp
)
SELECT DISTINCT
    dk.MaSV,
    cur.MaLHP AS MaLHPDangKy,
    cur.MaMH AS MaMHDangKy,
    cur.TenMH AS TenMHDangKy,
    cur.Nhom AS NhomDangKy,
    cur.Thu AS ThuTrung,
    cur.TietBD AS TietBDDangKy,
    cur.TietKT AS TietKTDangKy,
    tgt.TietBD AS TietBDMucTieu,
    tgt.TietKT AS TietKTMucTieu,
    cur.MaPhong AS MaPhongDangKy,
    tgt.MaPhong AS MaPhongMucTieu
FROM DangKy dk
JOIN v_lop_hoc_phan_lich cur ON dk.MaLHP = cur.MaLHP
JOIN LopHP cur_lhp ON cur.MaLHP = cur_lhp.MaLHP
JOIN target t
JOIN v_lop_hoc_phan_lich tgt ON t.MaLHP = tgt.MaLHP
WHERE dk.MaSV = :ma_sv
  AND cur.MaLHP <> :ma_lhp
  AND cur_lhp.NamHoc = t.NamHoc
  AND cur_lhp.HocKy = t.HocKy
  AND cur.Thu = tgt.Thu
  AND cur.TietBD <= tgt.TietKT
  AND cur.TietKT >= tgt.TietBD;

-- 3. sinh vien da dang ky lop khac cua cung mon trong cung hoc ky chua
-- params: :ma_sv, :ma_lhp
WITH target AS (
    SELECT MaLHP, MaMH, NamHoc, HocKy
    FROM LopHP
    WHERE MaLHP = :ma_lhp
)
SELECT
    dk.MaSV,
    lhp.MaLHP,
    lhp.MaMH,
    mh.TenMH,
    lhp.NamHoc,
    lhp.HocKy,
    lhp.Nhom
FROM DangKy dk
JOIN LopHP lhp ON dk.MaLHP = lhp.MaLHP
JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
JOIN target t
WHERE dk.MaSV = :ma_sv
  AND lhp.MaLHP <> t.MaLHP
  AND lhp.MaMH = t.MaMH
  AND lhp.NamHoc = t.NamHoc
  AND lhp.HocKy = t.HocKy;

-- 4. tong tin chi da dang ky cua sinh vien trong hoc ky cua lop muc tieu
-- params: :ma_sv, :ma_lhp
WITH target AS (
    SELECT NamHoc, HocKy
    FROM LopHP
    WHERE MaLHP = :ma_lhp
)
SELECT
    :ma_sv AS MaSV,
    t.NamHoc,
    t.HocKy,
    COALESCE(SUM(mh.SoTC), 0) AS TongTinChiDangKy
FROM target t
LEFT JOIN DangKy dk ON dk.MaSV = :ma_sv
LEFT JOIN LopHP lhp
    ON dk.MaLHP = lhp.MaLHP
   AND lhp.NamHoc = t.NamHoc
   AND lhp.HocKy = t.HocKy
LEFT JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
GROUP BY t.NamHoc, t.HocKy;

-- 5. kiem tra tong hop: sinh vien co dang ky duoc mot lop hoc phan khong
-- params: :ma_sv, :ma_lhp, :max_credits
WITH target AS (
    SELECT
        lhp.MaLHP,
        lhp.MaMH,
        mh.TenMH,
        mh.SoTC,
        lhp.NamHoc,
        lhp.HocKy,
        lhp.Nhom,
        lhp.TrangThai,
        lhp.SiSoTD,
        lhp.SiSoDK,
        CASE
            WHEN lhp.SiSoTD - lhp.SiSoDK > 0 THEN lhp.SiSoTD - lhp.SiSoDK
            ELSE 0
        END AS SoChoCon
    FROM LopHP lhp
    JOIN MonHoc mh ON lhp.MaMH = mh.MaMH
    WHERE lhp.MaLHP = :ma_lhp
),
student AS (
    SELECT MaSV, HoTen, TrangThai AS TrangThaiSV
    FROM SinhVien
    WHERE MaSV = :ma_sv
),
exact_registration AS (
    SELECT COUNT(*) AS cnt
    FROM DangKy
    WHERE MaSV = :ma_sv
      AND MaLHP = :ma_lhp
),
missing_prereq AS (
    SELECT COUNT(*) AS cnt
    FROM target t
    JOIN TienQuyet tq ON t.MaMH = tq.MaMH
    LEFT JOIN KetQua kq
        ON kq.MaSV = :ma_sv
       AND kq.MaMH = tq.MaMHTQ
       AND kq.KetQua = 'DAT'
    WHERE kq.MaMH IS NULL
),
schedule_conflicts AS (
    SELECT COUNT(DISTINCT dk.MaLHP) AS cnt
    FROM target t
    JOIN v_lop_hoc_phan_lich tgt ON t.MaLHP = tgt.MaLHP
    JOIN DangKy dk ON dk.MaSV = :ma_sv
    JOIN LopHP cur_lhp
        ON dk.MaLHP = cur_lhp.MaLHP
       AND cur_lhp.NamHoc = t.NamHoc
       AND cur_lhp.HocKy = t.HocKy
    JOIN v_lop_hoc_phan_lich cur ON dk.MaLHP = cur.MaLHP
    WHERE cur.MaLHP <> t.MaLHP
      AND cur.Thu = tgt.Thu
      AND cur.TietBD <= tgt.TietKT
      AND cur.TietKT >= tgt.TietBD
),
same_course AS (
    SELECT COUNT(*) AS cnt
    FROM target t
    JOIN DangKy dk ON dk.MaSV = :ma_sv
    JOIN LopHP cur_lhp
        ON dk.MaLHP = cur_lhp.MaLHP
       AND cur_lhp.MaMH = t.MaMH
       AND cur_lhp.NamHoc = t.NamHoc
       AND cur_lhp.HocKy = t.HocKy
    WHERE cur_lhp.MaLHP <> t.MaLHP
),
credit_load AS (
    SELECT COALESCE(SUM(mh.SoTC), 0) AS credits
    FROM target t
    LEFT JOIN DangKy dk ON dk.MaSV = :ma_sv
    LEFT JOIN LopHP cur_lhp
        ON dk.MaLHP = cur_lhp.MaLHP
       AND cur_lhp.NamHoc = t.NamHoc
       AND cur_lhp.HocKy = t.HocKy
    LEFT JOIN MonHoc mh ON cur_lhp.MaMH = mh.MaMH
)
SELECT
    :ma_sv AS MaSV,
    student.HoTen,
    student.TrangThaiSV,
    t.MaLHP,
    t.MaMH,
    t.TenMH,
    t.NamHoc,
    t.HocKy,
    t.Nhom,
    t.SoTC,
    t.TrangThai AS TrangThaiLHP,
    t.SiSoDK,
    t.SiSoTD,
    t.SoChoCon,
    credit_load.credits AS TinChiHienTai,
    credit_load.credits + t.SoTC AS TinChiSauDangKy,
    missing_prereq.cnt AS SoMonTienQuyetThieu,
    schedule_conflicts.cnt AS SoLopTrungLich,
    same_course.cnt AS SoLopCungMonDaDangKy,
    exact_registration.cnt AS DaDangKyLopNay,
    CASE
        WHEN student.MaSV IS NULL THEN 0
        WHEN student.TrangThaiSV <> 'DANG_HOC' THEN 0
        WHEN exact_registration.cnt > 0 THEN 0
        WHEN t.TrangThai <> 'MO' THEN 0
        WHEN t.SoChoCon <= 0 THEN 0
        WHEN missing_prereq.cnt > 0 THEN 0
        WHEN schedule_conflicts.cnt > 0 THEN 0
        WHEN same_course.cnt > 0 THEN 0
        WHEN credit_load.credits + t.SoTC > :max_credits THEN 0
        ELSE 1
    END AS CoTheDangKy,
    TRIM(
        CASE WHEN student.MaSV IS NULL THEN 'SINH_VIEN_KHONG_TON_TAI; ' ELSE '' END ||
        CASE WHEN student.TrangThaiSV <> 'DANG_HOC' THEN 'SINH_VIEN_KHONG_DANG_HOC; ' ELSE '' END ||
        CASE WHEN exact_registration.cnt > 0 THEN 'DA_DANG_KY_LOP_NAY; ' ELSE '' END ||
        CASE WHEN t.TrangThai <> 'MO' THEN 'LOP_KHONG_MO; ' ELSE '' END ||
        CASE WHEN t.SoChoCon <= 0 THEN 'LOP_HET_CHO; ' ELSE '' END ||
        CASE WHEN missing_prereq.cnt > 0 THEN 'THIEU_TIEN_QUYET; ' ELSE '' END ||
        CASE WHEN schedule_conflicts.cnt > 0 THEN 'TRUNG_LICH; ' ELSE '' END ||
        CASE WHEN same_course.cnt > 0 THEN 'DA_DANG_KY_MON_NAY; ' ELSE '' END ||
        CASE WHEN credit_load.credits + t.SoTC > :max_credits THEN 'VUOT_TIN_CHI; ' ELSE '' END
    ) AS LyDoKhongDangKy
FROM target t
LEFT JOIN student ON 1 = 1
CROSS JOIN exact_registration
CROSS JOIN missing_prereq
CROSS JOIN schedule_conflicts
CROSS JOIN same_course
CROSS JOIN credit_load;

-- 6. cac lop cung mon co the dang ky thay cho lop muc tieu
-- params: :ma_sv, :ma_lhp, :max_credits
WITH target_course AS (
    SELECT MaMH, NamHoc, HocKy
    FROM LopHP
    WHERE MaLHP = :ma_lhp
),
candidate AS (
    SELECT lhp.MaLHP
    FROM LopHP lhp
    JOIN target_course t
        ON lhp.MaMH = t.MaMH
       AND lhp.NamHoc = t.NamHoc
       AND lhp.HocKy = t.HocKy
    WHERE lhp.MaLHP <> :ma_lhp
      AND lhp.TrangThai = 'MO'
      AND lhp.SiSoDK < lhp.SiSoTD
)
SELECT
    c.MaLHP,
    v.TenMH,
    v.Nhom,
    v.SoTC,
    v.SoChoCon,
    v.LichHocText,
    v.TenGV
FROM candidate c
JOIN v_lop_hoc_phan_day_du v ON c.MaLHP = v.MaLHP
WHERE NOT EXISTS (
    SELECT 1
    FROM DangKy dk
    JOIN LopHP cur_lhp ON dk.MaLHP = cur_lhp.MaLHP
    JOIN v_lop_hoc_phan_lich cur ON dk.MaLHP = cur.MaLHP
    JOIN v_lop_hoc_phan_lich tgt ON c.MaLHP = tgt.MaLHP
    JOIN target_course t
    WHERE dk.MaSV = :ma_sv
      AND cur_lhp.NamHoc = t.NamHoc
      AND cur_lhp.HocKy = t.HocKy
      AND cur.Thu = tgt.Thu
      AND cur.TietBD <= tgt.TietKT
      AND cur.TietKT >= tgt.TietBD
)
ORDER BY v.SoChoCon DESC, v.Nhom ASC;
