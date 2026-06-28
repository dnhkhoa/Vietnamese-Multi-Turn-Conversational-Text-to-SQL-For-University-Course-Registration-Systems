from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.llm_state_parser import QwenStateParser, RemoteStateParser, StateParserError


DEFAULT_EVAL_FILE = PROJECT_ROOT / "data" / "eval" / "course_glossary_k23_eval.jsonl"
DEFAULT_OUTPUT = PROJECT_ROOT / "outputs" / "eval" / "course_glossary_model_eval.json"


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def same_expected_slots(expected_slots: Dict[str, Any], predicted_slots: Dict[str, Any]) -> bool:
    for key, expected_value in expected_slots.items():
        if predicted_slots.get(key) != expected_value:
            return False
    return True


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(rows)
    total = len(rows)
    with_ma_mh = [row for row in rows if row["expected_state"].get("slots", {}).get("MaMH")]
    negative = [row for row in rows if row.get("metadata", {}).get("forbid_ma_mh")]
    regression = [row for row in rows if row.get("category") == "regression_no_abbreviation"]

    def ratio(num: int, den: int) -> float:
        return round(num / den, 4) if den else 0.0

    ma_mh_correct = sum(row["predicted_state"].get("slots", {}).get("MaMH") == row["expected_state"]["slots"]["MaMH"] for row in with_ma_mh)
    joint_correct = sum(
        row["predicted_state"].get("intent") == row["expected_state"].get("intent")
        and row["predicted_state"].get("edit_operation") == row["expected_state"].get("edit_operation")
        and same_expected_slots(row["expected_state"].get("slots", {}), row["predicted_state"].get("slots", {}))
        for row in rows
    )
    edit_correct = sum(
        row["predicted_state"].get("edit_operation") == row["expected_state"].get("edit_operation")
        for row in rows
    )
    false_maps = sum(bool(row["predicted_state"].get("slots", {}).get("MaMH")) for row in negative)
    regression_joint = sum(
        row["predicted_state"].get("intent") == row["expected_state"].get("intent")
        and row["predicted_state"].get("edit_operation") == row["expected_state"].get("edit_operation")
        and same_expected_slots(row["expected_state"].get("slots", {}), row["predicted_state"].get("slots", {}))
        for row in regression
    )
    return {
        "total": total,
        "ma_mh_cases": len(with_ma_mh),
        "ma_mh_exact_accuracy": ratio(ma_mh_correct, len(with_ma_mh)),
        "joint_state_exact_match": ratio(joint_correct, total),
        "edit_operation_accuracy": ratio(edit_correct, total),
        "negative_cases": len(negative),
        "false_mapping_rate": ratio(false_maps, len(negative)),
        "regression_no_abbreviation_cases": len(regression),
        "regression_joint_state_exact_match": ratio(regression_joint, len(regression)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-file", type=Path, default=DEFAULT_EVAL_FILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--adapter-dir", type=Path)
    parser.add_argument("--remote-api-url")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    if bool(args.adapter_dir) == bool(args.remote_api_url):
        raise SystemExit("Pass exactly one of --adapter-dir or --remote-api-url.")

    try:
        parser_impl = (
            QwenStateParser(args.adapter_dir)
            if args.adapter_dir
            else RemoteStateParser(str(args.remote_api_url))
        )
    except Exception as exc:
        raise SystemExit(
            "Could not initialize real Qwen/LoRA parser. This is a blocker for model evaluation, "
            f"not a passing result: {exc}"
        ) from exc

    rows = load_jsonl(args.eval_file)
    if args.limit:
        rows = rows[: args.limit]

    evaluated = []
    for item in rows:
        try:
            parsed = parser_impl.parse(item["utterance"], item.get("previous_state", {}))
            predicted = parsed.as_dict()
            error = None
        except StateParserError as exc:
            predicted = {"intent": None, "edit_operation": None, "slots": {}}
            error = str(exc)
        evaluated.append({**item, "predicted_state": predicted, "error": error})

    report = {
        "eval_file": str(args.eval_file),
        "parser": "local_qwen_lora" if args.adapter_dir else "remote_qwen",
        "adapter_dir": str(args.adapter_dir) if args.adapter_dir else None,
        "remote_api_url": args.remote_api_url,
        "metrics": summarize(evaluated),
        "rows": evaluated,
    }
    write_json(args.output, report)
    print(json.dumps(report["metrics"], ensure_ascii=False, indent=2, sort_keys=True))
    print(f"Wrote report to {args.output}")


if __name__ == "__main__":
    main()
