from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_synthetic_data import qwen_messages_from_dialogues
from src.business_rules import DEFAULT_DB_PATH
from src.course_glossary import (
    build_system_prompt,
    course_code_aliases_for_validation,
    estimate_prompt_tokens,
    load_course_glossary,
    prompt_metadata,
    prompt_sha256,
    validate_glossary,
)
from src.llm_state_parser import MODEL_COURSE_CODE_ALIASES, SYSTEM_PROMPT


def test_course_glossary_schema_and_db_codes_are_valid() -> None:
    glossary = load_course_glossary()

    assert validate_glossary(glossary, DEFAULT_DB_PATH) == []
    assert len(glossary["entries"]) <= 30
    assert sum(len(entry["forms"]) for entry in glossary["entries"]) <= 80


def test_prompt_is_deterministic_and_within_budget() -> None:
    glossary = load_course_glossary()
    prompt_one = build_system_prompt(glossary)
    prompt_two = build_system_prompt(glossary)

    assert prompt_one == prompt_two
    assert prompt_sha256(glossary) == prompt_metadata(glossary)["prompt_sha256"]
    assert estimate_prompt_tokens(prompt_one) <= 500
    assert "ai da dang ky?" in prompt_one


def test_training_and_inference_use_same_state_prompt() -> None:
    dialogue = {
        "dialogue_id": "unit_glossary",
        "source": "unit",
        "turns": [
            {
                "utterance": "Mon CSDL may tin chi?",
                "intent": "COURSE_INFO_SEARCH",
                "edit_operation": "NEW_QUERY",
                "slots": {"MaMH": "DBSY230184E"},
            }
        ],
    }

    rows = qwen_messages_from_dialogues([dialogue])

    assert SYSTEM_PROMPT == build_system_prompt()
    assert rows[0]["messages"][0]["content"] == SYSTEM_PROMPT
    assert rows[0]["metadata"]["prompt_sha256"] == prompt_metadata()["prompt_sha256"]
    assert rows[0]["metadata"]["glossary_sha256"] == prompt_metadata()["glossary_sha256"]


def test_glossary_hash_matches_eval_metadata() -> None:
    eval_path = Path("data/eval/course_glossary_k23_eval.jsonl")
    first = json.loads(eval_path.read_text(encoding="utf-8").splitlines()[0])
    metadata = prompt_metadata()

    assert first["metadata"]["prompt_version"] == metadata["prompt_version"]
    assert first["metadata"]["prompt_sha256"] == metadata["prompt_sha256"]
    assert first["metadata"]["glossary_version"] == metadata["glossary_version"]
    assert first["metadata"]["glossary_sha256"] == metadata["glossary_sha256"]


def test_validation_aliases_are_derived_from_glossary() -> None:
    aliases = course_code_aliases_for_validation()

    assert MODEL_COURSE_CODE_ALIASES == aliases
    assert aliases["CSDL"] == "DBSY230184E"
    assert aliases["CO SO DU LIEU"] == "DBSY230184E"
    assert aliases["AI"] == "ARIN330585E"


def test_ambiguous_short_forms_require_context_in_glossary() -> None:
    glossary = load_course_glossary()
    ambiguous_forms = {"AI", "ML", "OS", "DS", "NLP", "CLOUD"}
    found = {}
    for entry in glossary["entries"]:
        for form in entry["forms"]:
            if form.upper() in ambiguous_forms:
                found[form.upper()] = bool(entry["requires_course_context"])

    assert found == {form: True for form in ambiguous_forms}
