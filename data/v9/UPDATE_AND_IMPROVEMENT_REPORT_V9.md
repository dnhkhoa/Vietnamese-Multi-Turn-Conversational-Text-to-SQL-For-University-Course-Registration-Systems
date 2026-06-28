# Dataset v9 — update and improvement report

Date: 2026-06-21  
Database: `data/ctdt_sis_v3.db`  
Database SHA-256: `e010a09da2d584f0d008d3d6e23fca70e3ac1a1e2b17290011e410cdad75290c`  
Database size: 35,209,216 bytes  
Seed: `20260621`

## Purpose

V9 is a clean dataset snapshot generated from the currently incomplete `ctdt_sis_v3.db`. It is designed to be rebuilt when that database is completed without manually editing labels, SQL, expected rows, or split files.

V9 does not reuse v04 gold results. Course codes, student IDs, offerings, prerequisites, curriculum data, and result hashes are read or regenerated from the v3 database snapshot.

## One-command update

```powershell
python scripts\build_dataset_v9.py
```

The command performs the following operations:

1. Reads the current database catalog.
2. Regenerates base synthetic and manual-style source dialogues.
3. Regenerates targeted natural/variable-length dialogues.
4. Builds bounded `entity_history` for multi-turn references.
5. Removes global exact duplicates.
6. Splits by `dialogue_id`, stratified by source.
7. Balances the default training split.
8. Regenerates SQL and business-rule expected results.
9. Executes held-out SQL against the current database.
10. Runs semantic validation and evaluator oracle self-tests.
11. Records the database path, size, and SHA-256 in the audit.

If the completed database changes or removes required core views, the build fails instead of silently creating inconsistent data.

## Source generation

| Source metric | Result |
|---|---:|
| Source dialogues | 3,020 |
| Source turns | 13,603 |
| Base synthetic target turns | 8,000 |
| Manual-style target turns | 2,000 |
| Targeted dialogue families | 4 × 180 |
| Source dialogue lengths | 2–8 turns |

The targeted source adds course offering, course information, credit summary, and aggregation examples using conversational Vietnamese, abbreviated wording, omitted accents, follow-up references, entity changes, filter removal, and limit operations.

## Fixes retained from older dataset versions

### Leakage and duplicates

- Exact duplicate rows: `0`.
- Train/dev overlap: `0`.
- Train/test overlap: `0`.
- Dev/test overlap: `0`.
- The split unit is `dialogue_id`; turns from one dialogue cannot cross partitions.

### Multi-turn history

- `entity_history` is included in model inputs.
- Unrecoverable long-range references: `0`.
- History is bounded to the eight most recent distinct entities per entity type.

### SQL and expected results

- Returned SQL includes every applied `LIMIT`.
- Empty SQL results preserve column schemas.
- Result hashes use order-independent row multisets, preventing false mismatches when SQL ordering contains ties.
- Held-out SQL validation: `1,661/1,661` passed.

### Semantic validation

The gate checks label schema, required slots, entity membership, entity provenance, ranges, read-only SQL, parameter binding, business-rule markers, hashes, IDs, and turn IDs.

- Full dataset: 10,500 rows, `0` errors and `0` warnings.
- Dev: 1,035 rows, `0` errors and `0` warnings.
- Test: 1,069 rows, `0` errors and `0` warnings.

### Template and intent improvements

- Retained targeted-natural examples: 2,670.
- Input dialogue lengths cover 2 through 8 turns.
- The balanced training maximum/minimum intent ratio is at most 2.5.
- Near-identical exact prompt/state pairs produced during generation are removed before splitting.

## Final v9 artifacts

| Artifact | Rows |
|---|---:|
| Balanced train | 7,378 |
| Full train | 8,396 |
| Dev | 1,035 |
| Test | 1,069 |
| Test SQL | 861 |
| Test business rule | 208 |
| Total deduplicated examples | 10,500 |

## Quality-gate results

- Duplicate rows: `0`.
- Cross-split overlap: `0`.
- Unrecoverable history: `0`.
- Semantic errors/warnings: `0/0`.
- Gold refresh failures: `0/10,500`.
- Held-out SQL failures: `0/1,661`.
- Oracle state exact match: `1.0` over 1,069 test rows.
- Oracle SQL execution accuracy: `1.0` over 861 SQL rows.
- Oracle business-rule result accuracy: `1.0` over 208 rows.

Oracle results validate the evaluator and dataset consistency; they are not model accuracy scores.

## Problems found and fixed during v9

1. Only a small subset of v04 entities exists in v3, so v04 gold could not be reused. V9 regenerates all entities and gold from v3.
2. One SQL query had tied ordering and produced a false hash mismatch across connections. Result hashes and execution comparison now use order-independent row multisets.
3. The v3 snapshot is incomplete. The audit records its fingerprint so results from different database snapshots cannot be confused.
4. Existing template sources remain repetitive. Targeted 2–8 turn dialogue families were added, followed by global deduplication.

## Remaining limitations

- The current v3 database is incomplete, so v9 must be rebuilt after database completion.
- Data remains synthetic/manual-style rather than independently collected from real users.
- The older base dialogue generator remains template-heavy despite targeted augmentation.
- Labels and SQL are checked automatically but have not all been independently reviewed by human annotators.
- The existing Qwen adapter has not been retrained or evaluated on v9.

## Evidence files

- `build_config_v9.json`: generation parameters and source counts.
- `dataset_audit_v9.json`: database fingerprint, distributions, leakage, gold, and semantic audit.
- `quality_gate_v9.json`: final gate and evaluator oracle results.
- `semantic_audit_v9.json`: full semantic validation.
- `split_manifest_v9.json`: dialogue-to-split assignments.
- `dropped_duplicates_v9.jsonl`: duplicate provenance.
