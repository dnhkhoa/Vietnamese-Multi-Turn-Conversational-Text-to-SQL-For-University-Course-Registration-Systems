from __future__ import annotations

import hashlib
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "ctdt_sis_v3.db"
CURRICULUM_XLSX_PATH = PROJECT_ROOT / "data" / "CTDT_HCMUTE.xlsx"
PORTAL_HTML_PATH = PROJECT_ROOT / "hcmute_online_portal_clone.html"


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def verify_password(account: sqlite3.Row, password: str) -> bool:
    algorithm = account["ThuatToanHash"]
    if algorithm != "pbkdf2_sha256":
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        str(account["PasswordSalt"]).encode("utf-8"),
        int(account["SoVongLapHash"]),
    ).hex()
    return digest == account["MatKhauHash"]


def mask_citizen_id(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    if len(text) <= 4:
        return text
    return "*" * (len(text) - 4) + text[-4:]


def get_student_payload(ma_sv: str) -> dict[str, Any] | None:
    with connect_db() as conn:
        row = conn.execute(
            """
            SELECT
                sv.MaSV,
                sv.HoTen,
                sv.TrangThai AS TrangThaiSV,
                sv.MaKhoaHoc,
                sv.GioiTinh,
                sv.NgaySinh,
                sv.NoiSinh,
                sv.QuocTich,
                sv.DanToc,
                sv.TonGiao,
                sv.CCCD,
                sv.NgayCapCCCD,
                sv.NoiCapCCCD,
                sv.SoDienThoai,
                sv.EmailCaNhan,
                sv.DiaChiThuongTru,
                sv.DiaChiTamTru,
                sv.LopQuanLy,
                sv.BacDaoTao,
                sv.HeDaoTao,
                sv.LoaiHinhDaoTao,
                sv.NgayNhapHoc,
                kh.TenKhoaHoc,
                ct.MaCTDT,
                ct.TenCTDT,
                n.MaNganh,
                n.TenNganh,
                tk.Email,
                tk.AnhDaiDienUrl,
                tk.EmailXacThuc,
                tk.SoDienThoaiXacThuc,
                hs.NhomHoSo,
                hs.GPA,
                hs.TinChiTichLuy,
                hs.TinChiDangKyHienTai,
                hs.GioiHanTinChi,
                hs.CanhBaoHocVu,
                hs.GhiChu,
                ct.TongTinChiToiThieu
            FROM SinhVien sv
            JOIN KhoaHoc kh ON kh.MaKhoaHoc = sv.MaKhoaHoc
            JOIN CTDT ct ON ct.MaCTDT = kh.MaCTDT
            JOIN Nganh n ON n.MaNganh = ct.MaNganh
            LEFT JOIN TaiKhoan tk ON tk.MaSV = sv.MaSV
            LEFT JOIN HoSoHocTapSinhVien hs ON hs.MaSV = sv.MaSV
            WHERE sv.MaSV = :ma_sv
            """,
            {"ma_sv": ma_sv},
        ).fetchone()
        contacts = [
            dict(contact)
            for contact in conn.execute(
                """
                SELECT QuanHe, HoTen, SoDienThoai, DiaChi, Email, LaLienHeKhanCap
                FROM SinhVienLienHe
                WHERE MaSV = :ma_sv
                ORDER BY LaLienHeKhanCap DESC, QuanHe
                """,
                {"ma_sv": ma_sv},
            ).fetchall()
        ]
    if row is None:
        return None
    data = dict(row)
    data["LienHe"] = contacts
    required_credits = data.get("TongTinChiToiThieu") or 0
    accumulated_credits = data.get("TinChiTichLuy") or 0
    data["PhanTramTinChiHoanThanh"] = round(accumulated_credits * 100 / required_credits, 2) if required_credits else 0
    data["CCCDMasked"] = mask_citizen_id(data.get("CCCD"))
    data["DiaChi"] = data.get("DiaChiTamTru") or data.get("DiaChiThuongTru")
    data["ImageUrl"] = data.get("AnhDaiDienUrl")
    data.update(
        {
            "LoaiNguoiHoc": "SV/HV/NCS",
            "TrangThaiHienThi": "Còn học" if data.get("TrangThaiSV") == "DANG_HOC" else data.get("TrangThaiSV"),
            "NoiDangKyKhaiSinh": data.get("NoiSinh"),
        }
    )
    return data


def login(username: str, password: str) -> dict[str, Any]:
    with connect_db() as conn:
        account = conn.execute(
            """
            SELECT *
            FROM TaiKhoan
            WHERE (MaSV = :username OR Email = :username)
              AND VaiTro = 'SINH_VIEN'
              AND TrangThai = 'HOAT_DONG'
            LIMIT 1
            """,
            {"username": username},
        ).fetchone()
        if account is None or not verify_password(account, password):
            return {"ok": False, "error": "INVALID_CREDENTIALS"}
        ma_sv = account["MaSV"]
    student = get_student_payload(ma_sv)
    return {"ok": True, "student": student}


def notifications() -> list[dict[str, str]]:
    return [
        {
            "title": "Thông báo đăng ký dự lễ tốt nghiệp dành cho nghiên cứu sinh, học viên cao học tốt nghiệp tháng 7/2026 trở về trước và sinh viên đại học chính quy, vừa học vừa làm tốt nghiệp tháng 3,4,5/2026",
            "sender": "PDT_Bùi Thị Quỳnh",
            "time": "17/06/2026 15:15:27",
        },
        {
            "title": "Thông báo Công nhận chứng chỉ tiếng Anh Cambridge xét đạt chuẩn đầu ra ngoại ngữ.",
            "sender": "PDT_Bùi Thị Quỳnh",
            "time": "03/06/2026 15:21:41",
        },
        {
            "title": "Phòng Đào tạo thông báo về việc Sinh viên có tên trong danh sách dự kiến được công nhận tốt nghiệp đại học chính quy đợt 3 năm học 2025-2026 lần 2",
            "sender": "PDT_Bùi Thị Quỳnh",
            "time": "20/05/2026 17:03:05",
        },
        {
            "title": "THÔNG BÁO về việc rút học phần qua mạng học kỳ 2 năm học 2025 - 2026",
            "sender": "PDT_Nguyễn Thị Bích Hồng",
            "time": "15/05/2026 17:21:33",
        },
    ]


def curriculum_from_excel() -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError:
        return curriculum_from_db()

    workbook = openpyxl.load_workbook(CURRICULUM_XLSX_PATH, read_only=True, data_only=True)
    sheet = workbook["CTDT"]
    rows: list[dict[str, Any]] = []
    current_group = ""
    current_requirement = ""
    course_index = 0
    for values in sheet.iter_rows(min_row=5, values_only=True):
        first = str(values[0]).strip() if values[0] is not None else ""
        code = str(values[1]).strip() if values[1] is not None else ""
        name = str(values[2]).strip() if values[2] is not None else ""
        if first and not code and not name:
            current_group = first
            rows.append({"type": "group", "label": first})
            continue
        if first in {"Bắt buộc", "Tự chọn"} and not code:
            current_requirement = first
            rows.append({"type": "requirement", "label": first})
            continue
        if not code or not name:
            continue
        course_index += 1
        rows.append(
            {
                "type": "course",
                "index": course_index,
                "group": current_group,
                "requirement": current_requirement or "Bắt buộc",
                "code": code,
                "name": name,
                "electiveGroup": values[3],
                "credits": values[4],
                "lectureHours": values[5],
                "practiceHours": values[6],
                "prerequisite": values[7],
                "prior": values[8],
                "equivalent": values[9],
                "department": values[10],
                "outline": values[11],
            }
        )
    return rows


def curriculum_from_db() -> list[dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                MaMH AS code,
                TenMH AS name,
                SoTC AS credits,
                SoTietLT AS lectureHours,
                SoTietTH AS practiceHours,
                LoaiYC AS requirement,
                HKGoiY AS suggestedTerm,
                TenNhomTC AS electiveGroup,
                HocPhanTienQuyetText AS prerequisite,
                HocPhanHocTruocText AS prior,
                HocPhanTuongDuongText AS equivalent,
                TenKhoaBM AS department
            FROM v_ctdt_hcmute_mon_hoc
            ORDER BY COALESCE(HKGoiY, 0), ExcelRow
            """
        ).fetchall()
    payload = [{"type": "group", "label": "Chưa phân học kỳ"}, {"type": "requirement", "label": "Bắt buộc"}]
    for index, row in enumerate(rows, start=1):
        item = dict(row)
        item.update({"type": "course", "index": index})
        payload.append(item)
    return payload


def marks(ma_sv: str) -> list[dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                MaMH AS code,
                TenMH AS name,
                SoTC AS credits,
                NamHoc AS year,
                HocKy AS semester,
                LanHoc AS attempt,
                DiemTongKet AS score10,
                DiemHe4 AS score4,
                DiemChu AS letter,
                KetQua AS result,
                LoaiHoc AS studyType,
                GhiChu AS note
            FROM v_ket_qua_hoc_tap_sv
            WHERE MaSV = :ma_sv
            ORDER BY NamHoc, HocKy, TenMH, LanHoc
            """,
            {"ma_sv": ma_sv},
        ).fetchall()
    return [dict(row) for row in rows]


def current_offerings() -> list[dict[str, Any]]:
    with connect_db() as conn:
        rows = conn.execute(
            """
            SELECT
                MaLHP AS id,
                MaMH AS code,
                TenMH AS name,
                Nhom AS groupCode,
                SoTC AS credits,
                NamHoc AS year,
                HocKy AS semester,
                TrangThaiLHP AS status,
                LichHocText AS schedule,
                TenGV AS teacher
            FROM v_lop_hoc_phan_day_du
            WHERE NamHoc = 2026 AND HocKy = 2
            ORDER BY MaLHP
            LIMIT 50
            """
        ).fetchall()
    return [dict(row) for row in rows]


class PortalHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/portal"}:
            self.send_bytes(PORTAL_HTML_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if parsed.path == "/references/ute_logo.png":
            self.send_bytes((PROJECT_ROOT / "references" / "ute_logo.png").read_bytes(), "image/png")
            return
        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return
        if parsed.path == "/api/notifications":
            self.send_json({"items": notifications()})
            return
        if parsed.path == "/api/curriculum":
            self.send_json({"items": curriculum_from_excel()})
            return
        if parsed.path == "/api/marks":
            params = parse_qs(parsed.query)
            ma_sv = params.get("ma_sv", [""])[0]
            self.send_json({"items": marks(ma_sv)})
            return
        if parsed.path == "/api/offerings":
            self.send_json({"items": current_offerings()})
            return
        if parsed.path == "/api/student":
            params = parse_qs(parsed.query)
            ma_sv = params.get("ma_sv", [""])[0]
            student = get_student_payload(ma_sv)
            if student is None:
                self.send_json({"ok": False, "error": "STUDENT_NOT_FOUND"}, status=404)
                return
            self.send_json({"ok": True, "student": student})
            return
        self.send_json({"ok": False, "error": "NOT_FOUND"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/login":
            self.send_json({"ok": False, "error": "NOT_FOUND"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "INVALID_JSON"}, status=400)
            return
        username = str(body.get("username", "")).strip()
        password = str(body.get("password", ""))
        result = login(username, password)
        self.send_json(result, status=200 if result.get("ok") else 401)

    def send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, content_type: str, status: int = 200) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8765), PortalHandler)
    print("HCMUTE portal clone: http://127.0.0.1:8765")
    server.serve_forever()


if __name__ == "__main__":
    main()
