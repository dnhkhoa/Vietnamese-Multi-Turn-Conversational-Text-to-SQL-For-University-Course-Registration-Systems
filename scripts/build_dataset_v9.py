from __future__ import annotations

import argparse
import collections
import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_synthetic_data import (
    generate_manual_labeled_dialogues,
    generate_synthetic_dialogues,
    load_catalog,
    write_jsonl,
)
from scripts.generate_v04_augmentation import generate as generate_targeted_dialogues
from scripts.generate_v04_augmentation import write_jsonl as write_targeted_jsonl


DEFAULT_DB = PROJECT_ROOT / "data" / "ctdt_sis_v3.db"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "v9"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild dataset v9 from the current CTDT/SIS database snapshot")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=20260621)
    parser.add_argument("--synthetic-turns", type=int, default=8000)
    parser.add_argument("--manual-style-turns", type=int, default=2000)
    parser.add_argument("--targeted-dialogues-per-family", type=int, default=180)
    args = parser.parse_args()

    db_path = args.db.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(db_path)

    synthetic = generate_synthetic_dialogues(args.synthetic_turns, args.seed, catalog)
    manual_style = generate_manual_labeled_dialogues(args.manual_style_turns, args.seed, catalog)
    targeted = generate_targeted_dialogues(
        db_path,
        args.seed,
        args.targeted_dialogues_per_family,
        version="v9",
    )

    synthetic_path = output_dir / "source_synthetic_v9.jsonl"
    manual_path = output_dir / "source_manual_style_v9.jsonl"
    targeted_path = output_dir / "source_targeted_natural_v9.jsonl"
    write_jsonl(synthetic_path, synthetic)
    write_jsonl(manual_path, manual_style)
    write_targeted_jsonl(targeted_path, targeted)

    source_dialogues = [*synthetic, *manual_style, *targeted]
    source_lengths = dict(
        sorted(collections.Counter(len(item.get("turns") or []) for item in source_dialogues).items())
    )
    config = {
        "version": "v9",
        "seed": args.seed,
        "database": str(db_path.relative_to(PROJECT_ROOT)),
        "synthetic_target_turns": args.synthetic_turns,
        "manual_style_target_turns": args.manual_style_turns,
        "targeted_dialogues_per_family": args.targeted_dialogues_per_family,
        "source_dialogues": len(source_dialogues),
        "source_turns": sum(len(item.get("turns") or []) for item in source_dialogues),
        "source_dialogue_length_distribution": source_lengths,
    }
    (output_dir / "build_config_v9.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "build_dataset_v03.py"),
            "--version",
            "v9",
            "--db",
            str(db_path),
            "--output-dir",
            str(output_dir),
            "--seed",
            str(args.seed),
            "--inputs",
            str(synthetic_path),
            str(manual_path),
            str(targeted_path),
        ]
    )
    run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "run_dataset_quality_checks.py"),
            "--version",
            "v9",
            "--data-dir",
            str(output_dir),
            "--db",
            str(db_path),
        ]
    )
    print(json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
