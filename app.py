from __future__ import annotations

import inspect
import json
import os
import sqlite3
import time
from pathlib import Path

import pandas as pd
import streamlit as st

from src.business_rules import DEFAULT_DB_PATH
from src.nl2sql_engine import VietnameseNL2SQLEngine
from src.presentation import PresentedResponse, format_vietnamese_number, present_response


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ADAPTER_PATH = PROJECT_ROOT / "models" / "qwen3b-lora-state-tracking"

os.environ.setdefault("NL2SQL_ALLOW_MODEL_DOWNLOAD", "1")


SUGGESTED_QUESTIONS = [
    "Kì này tôi nên đăng ký môn nào?",
    "Cho tôi xem các lớp môn CSDL",
    "Môn CSDL còn lớp buổi sáng không?",
    "Mỗi môn có bao nhiêu lớp?",
    "Tôi đã học những môn gì?",
]

TABLE_LABELS = {
    "SinhVien": "Sinh viên",
    "MonHoc": "Môn học",
    "LopHocPhan": "Lớp học phần",
    "DangKy": "Đăng ký",
    "KetQuaHocTap": "Kết quả học tập",
    "Nganh": "Ngành",
}


def default_parser_mode() -> str:
    return "hybrid" if DEFAULT_ADAPTER_PATH.exists() else "rule"


def make_engine() -> VietnameseNL2SQLEngine:
    kwargs = {
        "db_path": st.session_state.db_path,
        "parser_mode": st.session_state.parser_mode,
        "lora_path": st.session_state.lora_path or None,
        "remote_api_url": st.session_state.remote_api_url or None,
    }
    signature = inspect.signature(VietnameseNL2SQLEngine)
    if "model_only_parser" in signature.parameters and kwargs["parser_mode"] != "rule":
        model_only = bool(st.session_state.get("model_only_parser"))
        kwargs.update(
            {
                "strict_parser": True,
                "model_only_parser": model_only,
                "repair_model_output": True,
            }
        )
    engine = VietnameseNL2SQLEngine(**kwargs)
    if st.session_state.get("active_ma_sv"):
        engine.set_active_student(st.session_state.active_ma_sv)
    return engine


def reset_engine() -> None:
    engine = st.session_state.get("engine")
    if engine is not None:
        engine.close()
    st.session_state.engine = make_engine()
    st.session_state.messages = []


def init_state() -> None:
    st.session_state.setdefault("db_path", str(DEFAULT_DB_PATH))
    st.session_state.setdefault("parser_mode", os.getenv("NL2SQL_PARSER_MODE", default_parser_mode()))
    st.session_state.setdefault("lora_path", str(DEFAULT_ADAPTER_PATH) if DEFAULT_ADAPTER_PATH.exists() else "")
    st.session_state.setdefault("remote_api_url", "")
    st.session_state.setdefault("active_ma_sv", os.getenv("NL2SQL_ACTIVE_MA_SV", "23110001"))
    st.session_state.setdefault("model_only_parser", os.getenv("NL2SQL_MODEL_ONLY", "0") == "1")
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("debug_mode", False)
    st.session_state.setdefault("pending_question", None)
    if "engine" not in st.session_state:
        st.session_state.engine = make_engine()


def is_model_result(result) -> bool:
    return result.parser_source == "qwen" or st.session_state.parser_mode == "rule"


def render_model_failure(error: str | None = None) -> None:
    st.error("Không thể hoàn tất truy vấn này. Vui lòng thử diễn đạt lại câu hỏi.")
    if error and st.session_state.get("debug_mode"):
        with st.expander("Chi tiết lỗi kỹ thuật"):
            st.code(error)


def inject_css() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.6rem; max-width: 1180px; }
        .answer-card {
            border: 1px solid rgba(128, 128, 128, 0.24);
            border-radius: 8px;
            padding: 1rem 1.1rem;
            margin: 0.25rem 0 0.75rem 0;
            background: rgba(128, 128, 128, 0.06);
        }
        .answer-title {
            font-size: 0.95rem;
            font-weight: 650;
            margin-bottom: 0.35rem;
        }
        .answer-value {
            font-size: 2rem;
            font-weight: 750;
            line-height: 1.15;
            margin-bottom: 0.3rem;
        }
        .answer-secondary, .answer-source {
            color: rgba(128, 128, 128, 0.95);
            font-size: 0.9rem;
        }
        .answer-summary { margin: 0.35rem 0 0.75rem 0; }
        div[data-testid="stDownloadButton"] button { width: 100%; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def load_table_stats(db_path: str) -> list[tuple[str, int]]:
    expected_tables = ["SinhVien", "MonHoc", "LopHocPhan", "DangKy", "KetQuaHocTap", "Nganh"]
    try:
        conn = sqlite3.connect(db_path)
        try:
            existing = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                ).fetchall()
            }
            stats = []
            for table in expected_tables:
                if table in existing:
                    count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                    stats.append((TABLE_LABELS.get(table, table), int(count)))
            return stats
        finally:
            conn.close()
    except sqlite3.Error:
        return []


def render_sidebar() -> None:
    with st.sidebar:
        st.subheader("Trạng thái hệ thống")
        active_ma_sv = st.text_input("Mã sinh viên đang dùng", value=st.session_state.active_ma_sv)
        st.caption(f"Parser: {st.session_state.parser_mode}")
        model_name = Path(st.session_state.lora_path).name if st.session_state.lora_path else "Rule parser"
        st.caption(f"Model: {model_name}")

        st.divider()
        st.subheader("Dữ liệu đã nạp")
        db_path = Path(st.session_state.db_path)
        st.caption(db_path.name)
        with st.expander("Xem đường dẫn đầy đủ"):
            st.code(str(db_path))

        for table_name, count in load_table_stats(st.session_state.db_path):
            st.write(f"{table_name}: {format_vietnamese_number(count, 0)} bản ghi")

        st.divider()
        col_reload, col_clear = st.columns(2)
        with col_reload:
            if st.button("Nạp lại", use_container_width=True):
                st.session_state.active_ma_sv = active_ma_sv.strip()
                reset_engine()
                st.rerun()
        with col_clear:
            if st.button("Xóa chat", use_container_width=True):
                st.session_state.messages = []
                st.rerun()

        st.divider()
        st.session_state.debug_mode = st.toggle(
            "Chế độ debug",
            value=st.session_state.debug_mode,
            help="Hiển thị SQL, state và lỗi kỹ thuật.",
        )
        if st.session_state.debug_mode and st.session_state.parser_mode != "rule":
            st.caption(
                "Hybrid đang cho phép rule fallback để demo ổn định. Đặt NL2SQL_MODEL_ONLY=1 nếu cần đánh giá model-only."
            )


def render_result(item: dict) -> None:
    if item.get("model_error"):
        render_model_failure(item["model_error"])
        return

    presented = present_response(
        item["question"],
        item["data"],
        item.get("message"),
        source_text=Path(st.session_state.db_path).name,
        filter_text=build_filter_text(item),
    )
    render_presented_response(presented, item)

    if item.get("warnings"):
        st.warning("\n".join(item["warnings"]))
    elif item.get("parser_warning"):
        st.warning(item["parser_warning"])

    render_technical_details(item)


def render_presented_response(presented: PresentedResponse, item: dict) -> None:
    if presented.response_type == "empty":
        st.info(presented.summary)
        render_source_line(presented)
        return

    if presented.response_type == "scalar":
        secondary = f'<div class="answer-secondary">{presented.secondary_value}</div>' if presented.secondary_value else ""
        source = f'<div class="answer-source">Nguồn: {presented.source_text}</div>' if presented.source_text else ""
        st.markdown(
            f"""
            <div class="answer-card">
              <div class="answer-title">{presented.title}</div>
              <div class="answer-value">{presented.primary_value}</div>
              {secondary}
              {source}
            </div>
            """,
            unsafe_allow_html=True,
        )
        if presented.summary:
            st.markdown(f'<div class="answer-summary">{presented.summary}</div>', unsafe_allow_html=True)
        render_download_buttons(item, presented)
        return

    st.subheader(presented.title)
    if presented.summary:
        st.markdown(f'<div class="answer-summary">{presented.summary}</div>', unsafe_allow_html=True)
    if presented.result_dataframe is not None:
        st.dataframe(
            presented.result_dataframe.head(100),
            use_container_width=True,
            hide_index=True,
            height=min(420, 72 + 36 * min(len(presented.result_dataframe), 9)),
        )
    render_source_line(presented)
    render_download_buttons(item, presented)


def render_source_line(presented: PresentedResponse) -> None:
    parts = []
    if presented.source_text:
        parts.append(f"Nguồn: {presented.source_text}")
    if presented.filter_text:
        parts.append(f"Bộ lọc: {presented.filter_text}")
    if parts:
        st.caption(" · ".join(parts))


def build_filter_text(item: dict) -> str | None:
    slots = item.get("slots") or {}
    visible_slots = {
        key: value
        for key, value in slots.items()
        if key in {"MaSV", "MaMH", "TenMH", "MaLHP", "HocKy", "NamHoc", "Buoi", "Thu", "Limit"}
        and value not in (None, "")
    }
    if not visible_slots:
        return None
    return ", ".join(f"{key}={value}" for key, value in visible_slots.items())


def render_download_buttons(item: dict, presented: PresentedResponse) -> None:
    data = item.get("data")
    if data is None or getattr(data, "empty", True):
        return

    display_df = presented.result_dataframe if presented.result_dataframe is not None else pd.DataFrame([{
        presented.title: presented.primary_value,
        "Ghi chú": presented.secondary_value or "",
    }])
    html = display_df.to_html(index=False, border=0)
    csv = display_df.to_csv(index=False).encode("utf-8-sig")
    key_base = item.get("turn_id", f"{abs(hash((item.get('question'), item.get('sql'))))}")
    col_html, col_csv, _ = st.columns([1, 1, 4])
    with col_html:
        st.download_button(
            "Tải báo cáo HTML",
            data=html,
            file_name="ket_qua_tra_cuu.html",
            mime="text/html",
            use_container_width=True,
            key=f"html-{key_base}",
        )
    with col_csv:
        st.download_button(
            "Tải kết quả CSV",
            data=csv,
            file_name="ket_qua_tra_cuu.csv",
            mime="text/csv",
            use_container_width=True,
            key=f"csv-{key_base}",
        )


def render_technical_details(item: dict) -> None:
    with st.expander("Xem dữ liệu chi tiết"):
        data = item["data"]
        if data is None or (getattr(data, "empty", False) and len(getattr(data, "columns", [])) == 0):
            st.info("Không có bảng kết quả để hiển thị.")
        else:
            st.dataframe(data.head(100), use_container_width=True, hide_index=True)

        if st.session_state.get("debug_mode"):
            st.divider()
            st.caption("SQL")
            st.code(item.get("sql") or "-- no SQL generated", language="sql")
            st.caption("State")
            st.json(
                {
                    "intent": item["intent"],
                    "edit_operation": item["edit_operation"],
                    "parser_source": item["parser_source"],
                    "slots": item["slots"],
                    "params": item["params"],
                }
            )


def result_to_item(question: str, result) -> dict:
    return {
        "turn_id": len(st.session_state.messages),
        "question": question,
        "message": result.message,
        "warnings": result.warnings,
        "parser_warning": result.parser_warning,
        "data": result.dataframe,
        "sql": result.sql,
        "intent": result.intent,
        "edit_operation": result.edit_operation,
        "parser_source": result.parser_source,
        "slots": json.loads(json.dumps(result.slots, ensure_ascii=False)),
        "params": json.loads(json.dumps(result.params, ensure_ascii=False)),
    }


def main() -> None:
    st.set_page_config(page_title="Trợ lý đăng ký học phần", layout="wide")
    init_state()
    inject_css()

    st.title("Trợ lý đăng ký học phần")
    st.caption("Tra cứu lớp học phần, điều kiện đăng ký, kết quả học tập và gợi ý môn học từ dữ liệu nội bộ.")

    render_sidebar()

    if not st.session_state.messages:
        st.write("Câu hỏi gợi ý")
        cols = st.columns(len(SUGGESTED_QUESTIONS))
        for index, question in enumerate(SUGGESTED_QUESTIONS):
            with cols[index]:
                if st.button(question, use_container_width=True):
                    st.session_state.pending_question = question
                    st.rerun()

    for item in st.session_state.messages:
        with st.chat_message("user"):
            st.write(item["question"])
        with st.chat_message("assistant"):
            render_result(item)

    question = st.session_state.pending_question or st.chat_input("Nhập câu hỏi về đăng ký học phần")
    if not question:
        return
    st.session_state.pending_question = None

    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        start_time = time.perf_counter()
        try:
            with st.status("Đang phân tích dữ liệu...", expanded=True) as status:
                st.write("Đang hiểu câu hỏi.")
                active_ma_sv = st.session_state.get("active_ma_sv") or None
                st.write("Đang truy vấn dữ liệu.")
                result = st.session_state.engine.ask(question, ma_sv=active_ma_sv)
                st.write("Đang tạo kết quả.")
                elapsed = time.perf_counter() - start_time
                status.update(
                    label=f"Hoàn tất trong {format_vietnamese_number(elapsed, 1)} giây",
                    state="complete",
                    expanded=False,
                )
            if not is_model_result(result):
                parser_warning = result.parser_warning or f"parser_source={result.parser_source}"
                item = {"turn_id": len(st.session_state.messages), "question": question, "model_error": parser_warning}
                st.session_state.engine.reset()
            else:
                item = result_to_item(question, result)
        except Exception as exc:
            item = {"turn_id": len(st.session_state.messages), "question": question, "model_error": str(exc)}
            st.session_state.engine.reset()

        render_result(item)
        st.session_state.messages.append(item)


if __name__ == "__main__":
    main()
