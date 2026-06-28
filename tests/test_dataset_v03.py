from scripts.build_dataset_v03 import deduplicate, stratified_dialogue_split, update_history


def _row(row_id: str, dialogue_id: str, source: str, signature: str) -> dict:
    return {
        "id": row_id,
        "dialogue_id": dialogue_id,
        "source": source,
        "_signature": signature,
    }


def test_v03_history_keeps_distinct_recent_entities() -> None:
    history = {"MaMH": [], "MaSV": [], "MaLHP": [], "MaNganh": []}
    history = update_history(history, {"MaMH": "DBSY230184E", "MaSV": "23110001"})
    history = update_history(history, {"MaMH": "ARIN330585E", "MaSV": "23110001"})

    assert history["MaMH"] == ["DBSY230184E", "ARIN330585E"]
    assert history["MaSV"] == ["23110001"]


def test_v03_deduplicates_exact_examples_globally() -> None:
    kept, dropped = deduplicate(
        [
            _row("a", "d1", "source", "same"),
            _row("b", "d2", "source", "same"),
            _row("c", "d2", "source", "different"),
        ]
    )

    assert [row["id"] for row in kept] == ["a", "c"]
    assert dropped == [{"id": "b", "duplicate_of": "a"}]


def test_v03_split_keeps_each_dialogue_in_one_partition() -> None:
    rows = [
        _row(f"r{index}", f"dialogue_{index}", "source", f"sig_{index}")
        for index in range(20)
    ]
    assignments = stratified_dialogue_split(rows, seed=42, dev_ratio=0.1, test_ratio=0.1)

    assert set(assignments.values()) == {"train", "dev", "test"}
    assert len(assignments) == 20
