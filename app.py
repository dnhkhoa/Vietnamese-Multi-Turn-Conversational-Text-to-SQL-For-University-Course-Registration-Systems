from __future__ import annotations

import inspect
import json
import os
from pathlib import Path

import streamlit as st

from src.business_rules import DEFAULT_DB_PATH
from src.nl2sql_engine import VietnameseNL2SQLEngine


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_ADAPTER_PATH = PROJECT_ROOT / "viedu-unsloth-local" / "outputs" / "adapters" / "colab_unsloth_qwen3b_lora"

os.environ.setdefault("NL2SQL_ALLOW_MODEL_DOWNLOAD", "1")


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
    if "model_only_parser" in signature.parameters:
        kwargs.update(
            {
                "strict_parser": True,
                "model_only_parser": True,
                "repair_model_output": False,
            }
        )
    return VietnameseNL2SQLEngine(**kwargs)


def reset_engine() -> None:
    engine = st.session_state.get("engine")
    if engine is not None:
        engine.close()
    st.session_state.engine = make_engine()
    st.session_state.messages = []


def init_state() -> None:
    st.session_state.setdefault("db_path", str(DEFAULT_DB_PATH))
    st.session_state.setdefault("parser_mode", default_parser_mode())
    st.session_state.setdefault("lora_path", str(DEFAULT_ADAPTER_PATH) if DEFAULT_ADAPTER_PATH.exists() else "")
    st.session_state.setdefault("remote_api_url", "")
    st.session_state.setdefault("messages", [])
    if "engine" not in st.session_state:
        st.session_state.engine = make_engine()


def is_model_result(result) -> bool:
    return result.parser_source == "qwen"


def render_model_failure(error: str | None = None) -> None:
    st.error("MODEL FAILED")
    st.write("Model không parse được câu này. App đang ở chế độ model-only nên không hiển thị kết quả rule fallback.")
    if error:
        st.code(error)


def render_result(item: dict) -> None:
    if item.get("model_error"):
        render_model_failure(item["model_error"])
        return

    st.success("MODEL OK")
    if item.get("message"):
        st.write(item["message"])
    if item.get("warnings"):
        st.warning("\n".join(item["warnings"]))
    elif item.get("parser_warning"):
        st.warning(item["parser_warning"])

    st.caption("Result")
    st.dataframe(item["data"], use_container_width=True, hide_index=True)

    with st.expander("SQL"):
        st.code(item.get("sql") or "-- no SQL generated", language="sql")
    with st.expander("State"):
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
    st.set_page_config(page_title="Vietnamese Course Registration Chatbot", layout="wide")
    init_state()

    st.title("Course Registration Chatbot")
    st.caption("Model-only evaluation mode")

    with st.sidebar:
        st.subheader("Runtime")
        db_path = st.text_input("Database", value=st.session_state.db_path)
        parser_mode = st.selectbox(
            "Parser",
            options=["hybrid", "remote", "rule"],
            index=["hybrid", "remote", "rule"].index(st.session_state.parser_mode)
            if st.session_state.parser_mode in {"hybrid", "remote", "rule"}
            else 0,
        )
        lora_path = st.text_input("LoRA adapter", value=st.session_state.lora_path)
        remote_api_url = st.text_input("Remote API", value=st.session_state.remote_api_url)

        if st.button("Reload", use_container_width=True):
            st.session_state.db_path = db_path
            st.session_state.parser_mode = parser_mode
            st.session_state.lora_path = lora_path
            st.session_state.remote_api_url = remote_api_url
            reset_engine()
            st.rerun()

        st.divider()
        st.write("Chỉ kết quả từ Qwen parser được hiển thị.")
        st.write("Rule fallback bị ẩn để không làm sai lệch đánh giá model.")

    for item in st.session_state.messages:
        with st.chat_message("user"):
            st.write(item["question"])
        with st.chat_message("assistant"):
            render_result(item)

    question = st.chat_input("Nhập câu hỏi")
    if not question:
        return

    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        try:
            result = st.session_state.engine.ask(question)
            if not is_model_result(result):
                parser_warning = result.parser_warning or f"parser_source={result.parser_source}"
                item = {"question": question, "model_error": parser_warning}
                st.session_state.engine.reset()
            else:
                item = result_to_item(question, result)
        except Exception as exc:
            item = {"question": question, "model_error": str(exc)}
            st.session_state.engine.reset()

        render_result(item)
        st.session_state.messages.append(item)


if __name__ == "__main__":
    main()
