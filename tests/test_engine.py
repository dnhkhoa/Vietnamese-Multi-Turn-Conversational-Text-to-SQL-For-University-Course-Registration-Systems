from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from src.llm_state_parser import ParsedState, extract_state_from_response, validate_state
from src.nl2sql_engine import VietnameseNL2SQLEngine


@pytest.fixture()
def engine():
    nl2sql = VietnameseNL2SQLEngine()
    try:
        yield nl2sql
    finally:
        nl2sql.close()


def test_course_alias_search(engine: VietnameseNL2SQLEngine) -> None:
    result = engine.ask("Cho tôi xem các lớp môn CSDL")

    assert result.intent == "COURSE_OFFERING_SEARCH"
    assert result.slots["MaMH"] == "DBSY230184E"
    assert not result.dataframe.empty
    assert set(result.dataframe["TenMH"]) == {"Database Systems"}


def test_context_filter_and_change_entity(engine: VietnameseNL2SQLEngine) -> None:
    engine.ask("Cho tôi xem các lớp môn CSDL")
    filtered = engine.ask("Chỉ lấy lớp buổi sáng còn chỗ")
    changed = engine.ask("Đổi sang môn AI")

    assert filtered.edit_operation == "ADD_FILTER"
    assert filtered.slots["MaMH"] == "DBSY230184E"
    assert filtered.slots["Buoi"] == "SANG"
    assert filtered.slots["CoTheDangKy"] == 1
    assert not filtered.dataframe.empty
    assert changed.edit_operation == "CHANGE_ENTITY"
    assert changed.slots["MaMH"] == "ARIN330585E"
    assert changed.slots["Buoi"] == "SANG"


def test_reference_resolution_for_prerequisite(engine: VietnameseNL2SQLEngine) -> None:
    engine.ask("Cho tôi xem các lớp môn AI")
    result = engine.ask("Môn này cần học trước môn gì?")

    assert result.intent == "PREREQUISITE_LOOKUP"
    assert result.edit_operation == "RESOLVE_REFERENCE"
    assert result.slots["MaMH"] == "ARIN330585E"
    assert not result.dataframe.empty
    assert "Data Structures and Algorithms" in set(result.dataframe["TenMHTQ"])


def test_new_student_query_resets_stale_course_context(engine: VietnameseNL2SQLEngine) -> None:
    engine.ask("Cho tôi xem các lớp môn AI")
    result = engine.ask("Sinh viên 23110001 đã đăng ký những lớp nào kỳ 1?")

    assert result.intent == "STUDENT_REGISTRATION_LOOKUP"
    assert result.slots["MaSV"] == "23110001"
    assert "MaMH" not in result.slots
    assert not result.dataframe.empty


def test_eligibility_by_course_returns_reasons_when_no_eligible_class(
    engine: VietnameseNL2SQLEngine,
) -> None:
    result = engine.ask("Sinh viên 23110001 đăng ký được môn NLP không?")

    assert result.intent == "REGISTRATION_ELIGIBILITY_CHECK"
    assert result.slots["MaMH"] == "NLPR431585E"
    assert not result.dataframe.empty
    assert "CoTheDangKy" in result.dataframe.columns
    assert "LyDoKhongDangKy" in result.dataframe.columns


def test_statistics_question_does_not_fuzzy_match_fake_course(
    engine: VietnameseNL2SQLEngine,
) -> None:
    result = engine.ask("Mỗi môn có bao nhiêu lớp?")

    assert result.intent == "AGGREGATION_STATISTICS"
    assert "MaMH" not in result.slots
    assert not result.dataframe.empty
    assert {"MaMH", "TenMH", "SoLopHocPhan"}.issubset(result.dataframe.columns)


def test_limit_edit_on_previous_statistics_query(engine: VietnameseNL2SQLEngine) -> None:
    engine.ask("Mỗi môn có bao nhiêu lớp?")
    result = engine.ask("Lấy 5 môn đầu thôi")

    assert result.intent == "AGGREGATION_STATISTICS"
    assert result.edit_operation == "LIMIT"
    assert result.slots["Limit"] == 5
    assert len(result.dataframe) == 5


def test_engine_connection_can_be_reused_from_streamlit_style_thread() -> None:
    engine = VietnameseNL2SQLEngine()
    try:
        engine.ask("Cho tôi xem các lớp môn CSDL")
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = executor.submit(engine.ask, "Chỉ lấy lớp buổi sáng còn chỗ").result()
    finally:
        engine.close()

    assert result.edit_operation == "ADD_FILTER"
    assert not result.dataframe.empty


def test_curriculum_followup_with_suggested_semester(engine: VietnameseNL2SQLEngine) -> None:
    engine.ask("Ngành CNTT có những môn bắt buộc nào?")
    result = engine.ask("Chỉ học kỳ 5")

    assert result.intent == "CURRICULUM_COURSE_SEARCH"
    assert result.edit_operation == "ADD_FILTER"
    assert result.slots["MaNganh"] == "10"
    assert result.slots["LoaiYC"] == "BAT_BUOC"
    assert result.slots["HocKy"] == 5


def test_reverse_prerequisite_question(engine: VietnameseNL2SQLEngine) -> None:
    result = engine.ask("Môn nào yêu cầu học CSDL trước?")

    assert result.intent == "PREREQUISITE_LOOKUP"
    assert result.slots["MaMH"] == "DBSY230184E"
    assert result.slots["PrereqDirection"] == "REQUIRED_BY"
    assert not result.dataframe.empty
    assert set(result.dataframe["MaMHTQ"]) == {"DBSY230184E"}


def test_course_name_does_not_pollute_major_slots(engine: VietnameseNL2SQLEngine) -> None:
    result = engine.ask("Có bao nhiêu sinh viên đăng ký môn Mạng máy tính?")

    assert result.intent == "AGGREGATION_STATISTICS"
    assert result.slots["MaMH"] == "NECO330282E"
    assert "MaNganh" not in result.slots
    assert not result.dataframe.empty


class FakeStateParser:
    def __init__(self, state: ParsedState | Exception):
        self.state = state

    def parse(self, utterance: str, previous_state: dict) -> ParsedState:
        if isinstance(self.state, Exception):
            raise self.state
        return self.state


def test_hybrid_parser_uses_valid_external_state() -> None:
    parser = FakeStateParser(
        ParsedState(
            intent="COURSE_OFFERING_SEARCH",
            edit_operation="NEW_QUERY",
            slots={"MaMH": "DBSY230184E"},
        )
    )
    engine = VietnameseNL2SQLEngine(state_parser=parser, parser_mode="hybrid")
    try:
        result = engine.ask("cau mo ho nhung parser da hieu la CSDL")
    finally:
        engine.close()

    assert result.parser_source == "qwen"
    assert result.intent == "COURSE_OFFERING_SEARCH"
    assert result.slots["MaMH"] == "DBSY230184E"
    assert result.slots["TenMH"] == "Database Systems"
    assert not result.dataframe.empty


def test_hybrid_parser_falls_back_to_rules_when_external_state_fails() -> None:
    parser = FakeStateParser(RuntimeError("bad json"))
    engine = VietnameseNL2SQLEngine(state_parser=parser, parser_mode="hybrid")
    try:
        result = engine.ask("Cho tôi xem các lớp môn CSDL")
    finally:
        engine.close()

    assert result.parser_source == "rule_fallback"
    assert result.intent == "COURSE_OFFERING_SEARCH"
    assert result.slots["MaMH"] == "DBSY230184E"
    assert result.parser_warning == "bad json"


def test_remote_parser_accepts_external_intent_aliases() -> None:
    state = validate_state(
        {
            "intent": "SEARCH_COURSE_REGISTRATION",
            "edit_operation": "SEARCH",
            "slots": {"ma_mh": "DBSY230184E"},
        }
    )

    assert state.intent == "COURSE_OFFERING_SEARCH"
    assert state.edit_operation == "NEW_QUERY"
    assert state.slots["MaMH"] == "DBSY230184E"


def test_remote_parser_repairs_observed_qwen_aliases() -> None:
    state = validate_state(
        {
            "intent": "COURSE_SEARCH",
            "edit_operation": "CHANGE_COURSE_ID",
            "slots": {"MaMH": "CSCL", "time_of_day": "morning", "available_only": True},
        }
    )

    assert state.intent == "COURSE_OFFERING_SEARCH"
    assert state.edit_operation == "CHANGE_ENTITY"
    assert state.slots["MaMH"] == "DBSY230184E"
    assert state.slots["Buoi"] == "SANG"
    assert state.slots["CoTheDangKy"] == 1


def test_remote_parser_accepts_legacy_filter_response() -> None:
    state_obj, _ = extract_state_from_response(
        {
            "question": "Cho tôi xem các lớp môn CSDL",
            "raw": "{\"filter\": {\"MaMH\": \"CT430101E\"}, \"sort\": \"MaLH\"}",
            "parsed": {"filter": {"MaMH": "CT430101E"}, "sort": "MaLH"},
        }
    )
    state = validate_state(state_obj)

    assert state.intent == "COURSE_OFFERING_SEARCH"
    assert state.edit_operation == "NEW_QUERY"
    assert state.slots["MaMH"] == "DBSY230184E"
