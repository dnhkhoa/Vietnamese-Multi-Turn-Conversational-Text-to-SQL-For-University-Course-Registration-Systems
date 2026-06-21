from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pandas as pd


ResponseType = Literal["scalar", "table", "chart", "dashboard", "report", "clarification", "error", "empty"]


@dataclass(frozen=True)
class PresentedResponse:
    response_type: ResponseType
    title: str
    summary: str
    primary_value: str | None = None
    secondary_value: str | None = None
    result_dataframe: pd.DataFrame | None = None
    chart: Any | None = None
    source_text: str | None = None
    filter_text: str | None = None
    raw_columns: tuple[str, ...] = ()


COLUMN_LABELS: dict[str, str] = {
    "total_duration_seconds": "Tổng thời gian downtime",
    "duration_seconds": "Thời lượng",
    "machine_name": "Máy",
    "loss_name": "Nguyên nhân tổn thất",
    "loss_group": "Nhóm tổn thất",
    "record_count": "Số lần ghi nhận",
    "MaSV": "Mã sinh viên",
    "HoTen": "Họ tên",
    "MaNganh": "Mã ngành",
    "TenNganh": "Ngành",
    "MaCTDT": "Mã CTĐT",
    "MaMH": "Mã môn",
    "TenMH": "Tên môn học",
    "TenMHTQ": "Môn tiên quyết",
    "MaMHTQ": "Mã môn tiên quyết",
    "MaLHP": "Mã lớp học phần",
    "Nhom": "Nhóm",
    "NamHoc": "Năm học",
    "HocKy": "Học kỳ",
    "SoTC": "Số tín chỉ",
    "SoTinChi": "Số tín chỉ",
    "TrangThaiLHP": "Trạng thái lớp",
    "TrangThaiSV": "Trạng thái sinh viên",
    "CoTheDangKy": "Có thể đăng ký",
    "LyDoKhongDangKy": "Lý do không đăng ký",
    "SoLopHocPhan": "Số lớp học phần",
    "SoLopConCho": "Số lớp còn chỗ",
    "TongSoChoCon": "Tổng số chỗ còn",
    "SoChoCon": "Số chỗ còn",
    "SiSoDK": "Sĩ số đăng ký",
    "SiSoTD": "Sĩ số tối đa",
    "Thu": "Thứ",
    "Buoi": "Buổi",
    "TietBD": "Tiết bắt đầu",
    "TietKT": "Tiết kết thúc",
    "MaPhong": "Phòng",
    "DayNha": "Dãy nhà",
    "TGDK": "Thời gian đăng ký",
    "DiemTongKet": "Điểm tổng kết",
    "DiemHe4": "Điểm hệ 4",
    "KetQua": "Kết quả",
    "SoSinhVienDangKy": "Số sinh viên đăng ký",
    "SoSinhVienKhongDat": "Số sinh viên không đạt",
    "TongTinChiDangKy": "Tổng tín chỉ đăng ký",
    "TinChiHienTai": "Tín chỉ hiện tại",
    "TinChiSauDangKy": "Tín chỉ sau đăng ký",
    "SoMonTienQuyetThieu": "Số môn tiên quyết thiếu",
    "SoLopTrungLich": "Số lớp trùng lịch",
    "SoLopCungMonDaDangKy": "Số lớp cùng môn đã đăng ký",
    "SoLopDaDangKy": "Số lớp đã đăng ký",
    "SoMonDaDangKy": "Số môn đã đăng ký",
    "TrangThaiGoiY": "Trạng thái gợi ý",
    "LyDoGoiY": "Lý do gợi ý",
}


def format_vietnamese_number(value: Any, decimals: int = 2) -> str:
    number = _coerce_number(value)
    if number is None:
        return "Không xác định"
    decimals = max(0, min(decimals, 2))
    if float(number).is_integer():
        decimals = 0
    formatted = f"{number:,.{decimals}f}"
    if decimals:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def format_duration(seconds: Any) -> dict[str, str | None]:
    value = _coerce_number(seconds)
    if value is None or value < 0:
        return {"primary": "Không xác định", "secondary": None}

    total_seconds = int(round(value))
    if total_seconds < 60:
        return {"primary": f"{format_vietnamese_number(total_seconds, 0)} giây", "secondary": None}

    minutes, sec = divmod(total_seconds, 60)
    if total_seconds < 3600:
        return {"primary": f"{minutes} phút {sec} giây", "secondary": None}

    hours, minute = divmod(minutes, 60)
    if total_seconds < 86400:
        return {"primary": f"{hours} giờ {minute} phút", "secondary": None}

    days, hour = divmod(hours, 24)
    primary_hours = format_vietnamese_number(value / 3600, 2)
    return {
        "primary": f"{primary_hours} giờ",
        "secondary": f"{days} ngày {hour} giờ {minute} phút {sec} giây",
    }


def humanize_column_name(column: str, catalog_labels: dict[str, str] | None = None) -> str:
    labels = catalog_labels or {}
    if column in labels:
        return labels[column]
    if column in COLUMN_LABELS:
        return COLUMN_LABELS[column]

    words = re.sub(r"[_\-]+", " ", str(column)).strip()
    if not words:
        return str(column)
    return words[:1].upper() + words[1:]


def present_response(
    question: str,
    dataframe: pd.DataFrame | None,
    message: str | None = None,
    *,
    source_text: str | None = None,
    filter_text: str | None = None,
    catalog_labels: dict[str, str] | None = None,
) -> PresentedResponse:
    if dataframe is None or dataframe.empty:
        return PresentedResponse(
            response_type="empty",
            title="Không có dữ liệu",
            summary="Không tìm thấy dữ liệu phù hợp với điều kiện đã chọn.",
            source_text=source_text,
            filter_text=filter_text,
        )

    raw_columns = tuple(str(column) for column in dataframe.columns)
    if _is_scalar_result(dataframe):
        column = raw_columns[0]
        value = dataframe.iloc[0, 0]
        if _is_duration_column(column):
            duration = format_duration(value)
            secondary = f"Tương đương {duration['secondary']}." if duration["secondary"] else None
            return PresentedResponse(
                response_type="scalar",
                title=humanize_column_name(column, catalog_labels),
                summary=_summary_without_question(message) or "Kết quả tổng hợp đã sẵn sàng.",
                primary_value=duration["primary"],
                secondary_value=secondary,
                source_text=source_text,
                filter_text=filter_text,
                raw_columns=raw_columns,
            )

        return PresentedResponse(
            response_type="scalar",
            title=humanize_column_name(column, catalog_labels),
            summary=_summary_without_question(message) or "Kết quả tổng hợp đã sẵn sàng.",
            primary_value=format_cell(column, value),
            source_text=source_text,
            filter_text=filter_text,
            raw_columns=raw_columns,
        )

    display_df = format_dataframe_for_display(dataframe, catalog_labels)
    summary = _table_summary(dataframe, message)
    return PresentedResponse(
        response_type="table",
        title=_table_title(raw_columns),
        summary=_remove_question_text(summary, question),
        result_dataframe=display_df,
        source_text=source_text,
        filter_text=filter_text,
        raw_columns=raw_columns,
    )


def format_dataframe_for_display(
    dataframe: pd.DataFrame,
    catalog_labels: dict[str, str] | None = None,
) -> pd.DataFrame:
    display_df = dataframe.copy()
    for column in display_df.columns:
        display_df[column] = display_df[column].map(lambda value, col=column: format_cell(str(col), value))
    display_df = display_df.rename(
        columns={column: humanize_column_name(str(column), catalog_labels) for column in display_df.columns}
    )
    return display_df


def format_cell(column: str, value: Any) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if _is_duration_column(column):
        return format_duration(value)["primary"] or ""
    if isinstance(value, bool):
        return "Có" if value else "Không"
    if str(column) == "CoTheDangKy":
        return "Có" if str(value) in {"1", "True", "true"} else "Không"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return format_vietnamese_number(value)
    return str(value)


def download_artifact_exists(path: str | Path | None) -> bool:
    if not path:
        return False
    return Path(path).exists()


def _table_summary(dataframe: pd.DataFrame, message: str | None) -> str:
    top_summary = _top_n_summary(dataframe)
    if top_summary:
        return top_summary
    clean_message = _summary_without_question(message)
    if clean_message:
        return clean_message
    return f"Tìm thấy {format_vietnamese_number(len(dataframe), 0)} kết quả phù hợp."


def _top_n_summary(dataframe: pd.DataFrame) -> str | None:
    if dataframe.empty:
        return None
    numeric_columns = [
        column
        for column in dataframe.columns
        if pd.api.types.is_numeric_dtype(dataframe[column]) and not _looks_like_id_column(str(column))
    ]
    text_columns = [
        column
        for column in dataframe.columns
        if column not in numeric_columns and not _looks_like_id_column(str(column))
    ]
    if not numeric_columns or not text_columns or len(dataframe) < 2:
        return None

    metric_col = numeric_columns[-1]
    name_col = text_columns[0]
    top_row = dataframe.sort_values(metric_col, ascending=False).iloc[0]
    metric_label = humanize_column_name(str(metric_col)).lower()
    return f"{top_row[name_col]} có {metric_label} cao nhất: {format_cell(str(metric_col), top_row[metric_col])}."


def _table_title(columns: tuple[str, ...]) -> str:
    if any(column in columns for column in ("MaLHP", "TenMH", "Nhom")):
        return "Danh sách lớp học phần"
    if any(column in columns for column in ("MaSV", "HoTen")):
        return "Danh sách sinh viên"
    if any(column in columns for column in ("MaMH", "TenMH")):
        return "Danh sách môn học"
    return "Kết quả tra cứu"


def _is_scalar_result(dataframe: pd.DataFrame) -> bool:
    return dataframe.shape == (1, 1)


def _is_duration_column(column: str) -> bool:
    normalized = column.lower()
    return normalized.endswith("duration_seconds") or normalized in {"duration_seconds", "total_duration_seconds"}


def _looks_like_id_column(column: str) -> bool:
    normalized = column.lower()
    return column.startswith("Ma") or normalized.endswith("_id") or normalized == "id"


def _summary_without_question(message: str | None) -> str | None:
    if not message:
        return None
    return re.sub(r'Kết quả cho câu hỏi\s*["“].*?["”]\s*:?\s*', "", message, flags=re.IGNORECASE).strip() or None


def _remove_question_text(summary: str, question: str) -> str:
    if not question:
        return summary
    normalized_summary = _normalize_text(summary)
    normalized_question = _normalize_text(question)
    if normalized_question and normalized_question in normalized_summary:
        return "Kết quả đã được tổng hợp từ dữ liệu phù hợp."
    return summary


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"[^a-zA-Z0-9]+", " ", text).strip().lower()
    return text


def _coerce_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number
