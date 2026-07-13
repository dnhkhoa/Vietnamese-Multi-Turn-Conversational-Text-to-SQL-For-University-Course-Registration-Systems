from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from src.nl2sql_engine import VietnameseNL2SQLEngine


PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "ctdt_sis_v3.db"
CURRICULUM_XLSX_PATH = PROJECT_ROOT / "data" / "CTDT_HCMUTE.xlsx"
PORTAL_HTML_PATH = PROJECT_ROOT / "hcmute_online_portal_clone.html"
PORTAL_CSS_PATH = PROJECT_ROOT / "style.css"
DEFAULT_LORA_PATH = PROJECT_ROOT / "models" / "qwen3b-lora-state-tracking"
_CHAT_ENGINE: VietnameseNL2SQLEngine | None = None


def get_chat_engine() -> VietnameseNL2SQLEngine:
    global _CHAT_ENGINE
    if _CHAT_ENGINE is None:
        parser_mode = os.getenv("NL2SQL_PARSER_MODE", "hybrid")
        lora_path = Path(os.getenv("NL2SQL_LORA_PATH", str(DEFAULT_LORA_PATH)))
        _CHAT_ENGINE = VietnameseNL2SQLEngine(
            DB_PATH,
            parser_mode=parser_mode,
            lora_path=lora_path if parser_mode == "hybrid" else None,
            remote_api_url=os.getenv("NL2SQL_QWEN_API_URL"),
        )
    return _CHAT_ENGINE


def dataframe_payload(df: Any) -> list[dict[str, Any]]:
    if df is None or getattr(df, "empty", True):
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def normalize_question_text(text: str) -> str:
    replacements = str.maketrans(
        {
            "à": "a",
            "á": "a",
            "ả": "a",
            "ã": "a",
            "ạ": "a",
            "ă": "a",
            "ằ": "a",
            "ắ": "a",
            "ẳ": "a",
            "ẵ": "a",
            "ặ": "a",
            "â": "a",
            "ầ": "a",
            "ấ": "a",
            "ẩ": "a",
            "ẫ": "a",
            "ậ": "a",
            "đ": "d",
            "è": "e",
            "é": "e",
            "ẻ": "e",
            "ẽ": "e",
            "ẹ": "e",
            "ê": "e",
            "ề": "e",
            "ế": "e",
            "ể": "e",
            "ễ": "e",
            "ệ": "e",
            "ì": "i",
            "í": "i",
            "ỉ": "i",
            "ĩ": "i",
            "ị": "i",
            "ò": "o",
            "ó": "o",
            "ỏ": "o",
            "õ": "o",
            "ọ": "o",
            "ô": "o",
            "ồ": "o",
            "ố": "o",
            "ổ": "o",
            "ỗ": "o",
            "ộ": "o",
            "ơ": "o",
            "ờ": "o",
            "ớ": "o",
            "ở": "o",
            "ỡ": "o",
            "ợ": "o",
            "ù": "u",
            "ú": "u",
            "ủ": "u",
            "ũ": "u",
            "ụ": "u",
            "ư": "u",
            "ừ": "u",
            "ứ": "u",
            "ử": "u",
            "ữ": "u",
            "ự": "u",
            "ỳ": "y",
            "ý": "y",
            "ỷ": "y",
            "ỹ": "y",
            "ỵ": "y",
        }
    )
    return re.sub(r"\s+", " ", text.lower().translate(replacements)).strip()


def question_needs_current_student(question: str) -> bool:
    norm = normalize_question_text(question)
    if re.search(r"(?<!\d)\d{8}(?!\d)", norm):
        return False
    first_person = any(marker in norm for marker in [" toi ", " cua toi", " minh ", " cua minh", " em ", " cua em"])
    student_task = any(
        marker in norm
        for marker in [
            "da hoc",
            "ket qua",
            "khong dat",
            "chua dat",
            "rot",
            "truot",
            "da dang ky",
            "dang ky bao nhieu tin chi",
            "tong tin chi",
            "ho so hoc tap",
            "tien do hoc tap",
            "canh bao hoc vu",
        ]
    )
    return first_person and student_task


def chat_answer(question: str, student_id: str | None = None) -> dict[str, Any]:
    engine = get_chat_engine()
    effective_question = question
    if student_id and question_needs_current_student(question):
        effective_question = f"{question} của sinh viên {student_id}"
    result = engine.ask(effective_question)
    return {
        "ok": True,
        "answer": result.message,
        "rows": dataframe_payload(result.dataframe),
        "intent": result.intent,
        "edit_operation": result.edit_operation,
        "slots": result.slots,
        "sql": result.sql,
        "params": result.params,
        "parser_source": result.parser_source,
        "parser_warning": result.parser_warning,
        "warnings": result.warnings,
    }


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
    return []


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
                CASE
                    WHEN GhiChu = 'Nhập từ bảng KetQua tổng hợp'
                      OR GhiChu = 'Đăng ký hiện tại'
                      OR GhiChu LIKE 'Bổ sung kết quả học lại đạt để cân bằng dữ liệu nợ môn v3%'
                    THEN NULL
                    ELSE GhiChu
                END AS note
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
        if parsed.path == "/style.css":
            self.send_bytes(PORTAL_CSS_PATH.read_bytes(), "text/css; charset=utf-8")
            return
        if parsed.path == "/assets/ute_logo.png":
            self.send_bytes((PROJECT_ROOT / "assets" / "ute_logo.png").read_bytes(), "image/png")
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
        if parsed.path not in {"/api/login", "/api/chat"}:
            self.send_json({"ok": False, "error": "NOT_FOUND"}, status=404)
            return
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8")
        try:
            body = json.loads(raw or "{}")
        except json.JSONDecodeError:
            self.send_json({"ok": False, "error": "INVALID_JSON"}, status=400)
            return
        if parsed.path == "/api/chat":
            question = str(body.get("question", "")).strip()
            student_id = str(body.get("student_id", "")).strip()
            if not question:
                self.send_json({"ok": False, "error": "QUESTION_REQUIRED"}, status=400)
                return
            try:
                self.send_json(chat_answer(question, student_id=student_id or None))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, status=500)
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
