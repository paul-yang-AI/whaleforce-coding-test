import pytest

from shared_harness.sec_ui import sec_result_matches_context


@pytest.mark.unit
def test_sec_result_matches_context_same_manifest() -> None:
    assert sec_result_matches_context(
        source="manifest",
        accession="0000950170-24-087843",
        result_source="manifest",
        result_accession="0000950170-24-087843",
    )


@pytest.mark.unit
def test_sec_result_matches_context_rejects_wrong_tab() -> None:
    assert not sec_result_matches_context(
        source="manifest",
        accession="0000950170-24-087843",
        result_source="custom",
        result_accession="0000950170-24-087843",
    )


@pytest.mark.unit
def test_sec_result_matches_context_rejects_wrong_accession() -> None:
    assert not sec_result_matches_context(
        source="manifest",
        accession="0000050863-25-000009",
        result_source="manifest",
        result_accession="0000950170-24-087843",
    )
