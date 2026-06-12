# Vietnamese Multi-Turn Conversational Text-to-SQL

Dataset and baseline code for Vietnamese multi-turn Text-to-SQL in a university course registration domain.

## Enhanced state-tracking dataset

The current enhanced dataset is generated from `data/course_registration.db`, which includes student profiles, curricula, prerequisites, registrations, and academic results.

Key files:

- `data/state_tracking_eval_v02.jsonl`: flattened state-tracking/evaluation rows. Each row has `previous_state`, `user_question`, `expected_state`, `gold_sql`, `gold_params`, and `expected_result`.
- `data/qwen_state_tracking_train_v02.jsonl`: chat/SFT format for state tracking.
- `data/synthetic_eval_v02.jsonl`: enriched synthetic multi-turn dialogues with baseline SQL/result metadata.
- `data/manual_labeled_eval_v02.jsonl`: curated harder multi-turn dialogues.

Regenerate:

```powershell
python scripts\generate_synthetic_data.py --target-turns 5000 --manual-turns 1000 --output data\synthetic_eval_v02.jsonl --manual-output data\manual_labeled_eval_v02.jsonl --qwen-output data\qwen_state_tracking_train_v02.jsonl --state-eval-output data\state_tracking_eval_v02.jsonl --expected-result-max-rows 30
```
