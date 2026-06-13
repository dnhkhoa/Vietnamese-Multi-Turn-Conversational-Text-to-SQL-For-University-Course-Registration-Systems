# Advisor Gap Dataset v03

This package adds advisor-oriented state-tracking data for model-only parsing.

## Outputs

- Train dialogues: `data\advisor_gap_train_dialogues_v03.jsonl`
- Eval dialogues: `data\advisor_gap_eval_dialogues_v03.jsonl`
- Train Qwen state tracking: `data\qwen_state_tracking_advisor_gap_train_v03.jsonl`
- Eval with gold SQL/result: `data\state_tracking_advisor_gap_eval_v03.jsonl`
- Quality report: `data\advisor_gap_quality_report_v03.json`

## Train Summary

```json
{
  "rows": 960,
  "sources": {
    "advisor_recommendation_train_v03": 240,
    "advisor_studied_context_train_v03": 240,
    "advisor_current_term_train_v03": 240,
    "advisor_context_switch_train_v03": 240
  },
  "intents": {
    "COURSE_RECOMMENDATION": 420,
    "STUDENT_INFO_LOOKUP": 180,
    "STUDENT_RESULT_LOOKUP": 180,
    "COURSE_OFFERING_SEARCH": 120,
    "CURRICULUM_COURSE_SEARCH": 60
  },
  "edit_operations": {
    "CHANGE_INTENT": 420,
    "NEW_QUERY": 240,
    "ADD_FILTER": 120,
    "REPLACE_FILTER": 60,
    "RESOLVE_REFERENCE": 60,
    "LIMIT": 60
  },
  "slots": {
    "MaSV": 840,
    "HocKy": 600,
    "NamHoc": 540,
    "LoaiYC": 120,
    "TrangThaiLHP": 120,
    "KetQua": 60,
    "Limit": 60
  },
  "with_previous_state": 720,
  "duplicate_question_count": 567,
  "duplicate_full_input_count": 0
}
```

## Eval Summary

```json
{
  "rows": 320,
  "missing_gold": 0,
  "truncated_results": 0,
  "row_count_by_intent": {
    "COURSE_OFFERING_SEARCH": {
      "count": 40,
      "zero": 0,
      "min": 50,
      "max": 50,
      "avg": 50.0
    },
    "COURSE_RECOMMENDATION": {
      "count": 140,
      "zero": 0,
      "min": 3,
      "max": 10,
      "avg": 8.73
    },
    "CURRICULUM_COURSE_SEARCH": {
      "count": 20,
      "zero": 0,
      "min": 5,
      "max": 5,
      "avg": 5.0
    },
    "STUDENT_INFO_LOOKUP": {
      "count": 60,
      "zero": 0,
      "min": 1,
      "max": 1,
      "avg": 1.0
    },
    "STUDENT_RESULT_LOOKUP": {
      "count": 60,
      "zero": 0,
      "min": 12,
      "max": 27,
      "avg": 22.08
    }
  }
}
```

## Leakage Check

```json
{
  "question_overlap_count": 0,
  "question_overlap_examples": []
}
```

## Existing Dataset Overlap Check

```json
{
  "existing_question_count": 7930,
  "new_train_overlap_count": 0,
  "new_train_overlap_examples": [],
  "new_eval_overlap_count": 0,
  "new_eval_overlap_examples": []
}
```

## Contract Note

The dataset intentionally introduces `COURSE_RECOMMENDATION`.
Production parser/backend must support this intent before merging the files into the main training set.
