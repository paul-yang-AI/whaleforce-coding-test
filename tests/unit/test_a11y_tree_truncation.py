"""L1: compress_a11y respects max_chars and preserves focus_hint."""

import pytest

from task1_agent.agent.dom_serialize import compress_a11y


@pytest.mark.unit
def test_short_tree_unchanged() -> None:
    tree = "short a11y content"
    assert compress_a11y(tree, max_chars=12000) == tree


@pytest.mark.unit
def test_long_tree_truncated_to_max_chars() -> None:
    tree = "x" * 50000
    result = compress_a11y(tree, max_chars=12000)
    assert len(result) <= 12000


@pytest.mark.unit
def test_focus_hint_preserved_in_output() -> None:
    prefix = "a" * 20000
    target = "SUBMIT_BUTTON_ROLE"
    suffix = "b" * 20000
    tree = prefix + target + suffix
    result = compress_a11y(tree, max_chars=12000, focus_hint=target)
    assert len(result) <= 12000
    assert target in result


@pytest.mark.unit
def test_dict_tree_serialized() -> None:
    tree = {"role": "button", "name": "Submit", "children": [{"role": "text", "value": "OK"}]}
    result = compress_a11y(tree, max_chars=12000)
    assert "Submit" in result
    assert len(result) <= 12000


@pytest.mark.unit
def test_large_dict_tree_truncated() -> None:
    tree = [{"role": "item", "name": f"node_{i}", "text": "x" * 200} for i in range(200)]
    result = compress_a11y(tree, max_chars=12000)
    assert len(result) <= 12000


@pytest.mark.unit
def test_default_max_chars_is_12000() -> None:
    tree = "y" * 50000
    result = compress_a11y(tree)
    assert len(result) <= 12000
