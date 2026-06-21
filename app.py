from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

import pandas as pd
import streamlit as st

from src.business_rules import DEFAULT_DB_PATH
from src.nl2sql_engine import QueryResult, VietnameseNL2SQLEngine


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SIS_DB_PATH = PROJECT_ROOT / "data" / "ctdt_sis_v3.db"
DEFAULT_LORA_CANDIDATES = [
    PROJECT_ROOT / "models" / "qwen3b-nl2sql-state-lora",
    PROJECT_ROOT / "models" / "qwen-nl2sql-state-lora-3b",
    PROJECT_ROOT / "models" / "qwen-nl2sql-state-lora",
]


def default_db_path() -> str:
    configured = os.getenv("NL2SQL_DB_PATH")
    if configured:
        return configured
    if DEFAULT_SIS_DB_PATH.exists():
        return str(DEFAULT_SIS_DB_PATH)
    return str(DEFAULT_DB_PATH)


def default_lora_path() -> str:
    configured = os.getenv("NL2SQL_LORA_PATH")
    if configured:
        return configured
    for candidate in DEFAULT_LORA_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return str(DEFAULT_LORA_CANDIDATES[0])


def read_adapter_base_model(adapter_path: str) -> str | None:
    config_path = Path(adapter_path) / "adapter_config.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    base_model = config.get("base_model_name_or_path")
    return str(base_model) if base_model else None


def default_parser_index(parser_options: Dict[str, str]) -> int:
    requested = os.getenv("NL2SQL_PARSER_MODE", "rule").strip().lower()
    values = list(parser_options.values())
    return values.index(requested) if requested in values else 0


def get_engine(db_path: str, parser_mode: str, lora_path: str, remote_api_url: str) -> VietnameseNL2SQLEngine:
    current_path = st.session_state.get("engine_db_path")
    current_parser_mode = st.session_state.get("engine_parser_mode")
    current_lora_path = st.session_state.get("engine_lora_path")
    current_remote_api_url = st.session_state.get("engine_remote_api_url")
    if (
        "engine" not in st.session_state
        or current_path != db_path
        or current_parser_mode != parser_mode
        or current_lora_path != lora_path
        or current_remote_api_url != remote_api_url
    ):
        old_engine = st.session_state.get("engine")
        if old_engine is not None:
            old_engine.close()
        st.session_state.engine = VietnameseNL2SQLEngine(
            Path(db_path),
            parser_mode=parser_mode,
            lora_path=lora_path if parser_mode == "hybrid" else None,
            remote_api_url=remote_api_url if parser_mode == "remote" else None,
        )
        st.session_state.engine_db_path = db_path
        st.session_state.engine_parser_mode = parser_mode
        st.session_state.engine_lora_path = lora_path
        st.session_state.engine_remote_api_url = remote_api_url
    return st.session_state.engine


def result_to_message(result: QueryResult) -> Dict[str, Any]:
    return {
        "role": "assistant",
        "content": result.message,
        "dataframe": result.dataframe,
        "intent": result.intent,
        "edit_operation": result.edit_operation,
        "slots": result.slots,
        "sql": result.sql,
        "params": result.params,
        "parser_source": result.parser_source,
        "parser_warning": result.parser_warning,
        "warnings": result.warnings,
    }


def render_result(message: Dict[str, Any]) -> None:
    for warning in message.get("warnings", []):
        st.warning(warning)

    df = message.get("dataframe")
    if isinstance(df, pd.DataFrame) and not df.empty:
        st.dataframe(df, use_container_width=True, hide_index=True)

    with st.expander("SQL và trạng thái phân tích", expanded=False):
        st.write(
            {
                "parser_source": message.get("parser_source"),
                "intent": message.get("intent"),
                "edit_operation": message.get("edit_operation"),
                "slots": message.get("slots"),
                "params": message.get("params"),
            }
        )
        sql = message.get("sql")
        if sql:
            st.code(sql, language="sql")


def submit_prompt(prompt: str, engine: VietnameseNL2SQLEngine) -> None:
    st.session_state.messages.append({"role": "user", "content": prompt})
    try:
        result = engine.ask(prompt)
        st.session_state.messages.append(result_to_message(result))
    except Exception as exc:  # keep the chat alive during demos
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": f"Lỗi khi xử lý câu hỏi: {exc}",
                "dataframe": pd.DataFrame(),
                "intent": None,
                "edit_operation": None,
                "slots": {},
                "sql": None,
                "params": {},
                "parser_source": None,
                "parser_warning": None,
                "warnings": [],
            }
        )


def main() -> None:
    st.set_page_config(
        page_title="Vietnamese Multi-Turn NL2SQL",
        page_icon="SQL",
        layout="wide",
    )

    st.title("Context-Aware NL2SQL cho đăng ký môn học")

    with st.sidebar:
        st.header("Phiên làm việc")
        db_path = st.text_input("SQLite DB", value=default_db_path())
        lora_default = default_lora_path()
        parser_options = {
            "Rule-based": "rule",
            "Hybrid Qwen local + fallback": "hybrid",
            "Remote Qwen API + fallback": "remote",
        }
        parser_label = st.selectbox(
            "Parser",
            list(parser_options.keys()),
            index=default_parser_index(parser_options),
        )
        parser_mode = parser_options[parser_label]
        lora_path = st.text_input(
            "Qwen LoRA adapter",
            value=lora_default,
            disabled=parser_mode != "hybrid",
        )
        base_model = read_adapter_base_model(lora_path)
        if parser_mode == "hybrid" and base_model:
            st.caption(f"Adapter base model: {base_model}")
            if "7b" in base_model.lower():
                st.info("Adapter hiện tại là 7B; máy 4GB VRAM nên dùng rule-based/remote hoặc thay bằng adapter 3B.")
        remote_api_url = st.text_input(
            "Remote Qwen API URL",
            value=os.getenv("NL2SQL_QWEN_API_URL", ""),
            disabled=parser_mode != "remote",
            placeholder="https://your-tunnel-url",
        )
        if st.button("Reset hội thoại", use_container_width=True):
            if "engine" in st.session_state:
                st.session_state.engine.reset()
            st.session_state.messages = []

        st.divider()
        st.subheader("Câu mẫu")
        examples = [
            "Cho tôi xem các lớp môn CSDL",
            "Chỉ lấy lớp buổi sáng còn chỗ",
            "Đổi sang môn AI",
            "Môn này cần học trước môn gì?",
            "Sinh viên 23110001 đã đăng ký những lớp nào kỳ 1?",
            "Sinh viên 23110001 đăng ký được môn NLP không?",
            "Mỗi môn có bao nhiêu lớp?",
        ]
        for i, example in enumerate(examples):
            if st.button(example, key=f"example_{i}", use_container_width=True):
                st.session_state.pending_prompt = example

    if "messages" not in st.session_state:
        st.session_state.messages = []

    engine = get_engine(db_path, parser_mode, lora_path, remote_api_url)
    if getattr(engine, "parser_load_error", None):
        st.sidebar.warning(f"Không load được Qwen parser, đang dùng rule-based: {engine.parser_load_error}")

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.write(message["content"])
            if message["role"] == "assistant":
                render_result(message)

    prompt = st.chat_input("Nhập câu hỏi về đăng ký môn học")
    pending_prompt = st.session_state.pop("pending_prompt", None)
    final_prompt = pending_prompt or prompt
    if final_prompt:
        submit_prompt(final_prompt, engine)
        st.rerun()


if __name__ == "__main__":
    main()
