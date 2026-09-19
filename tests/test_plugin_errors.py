"""Tests for leanpipe plugin error handling."""
import pytest
from pathlib import Path

from leanpipe.filters import load_plugin


def test_load_plugin_invalid_yaml(tmp_path):
    """Plugin loader should raise ValueError for invalid YAML."""
    plugin = tmp_path / "bad.yaml"
    plugin.write_text("name: [unclosed\n  bad: {{")

    with pytest.raises(ValueError, match="Invalid YAML"):
        load_plugin(plugin)


def test_load_plugin_non_object_yaml(tmp_path):
    """Plugin loader should raise ValueError for non-object YAML."""
    plugin = tmp_path / "array.yaml"
    plugin.write_text("- item1\n- item2\n")

    with pytest.raises(ValueError, match="must be a YAML object"):
        load_plugin(plugin)


def test_load_plugin_rule_missing_match(tmp_path):
    """Plugin loader should raise ValueError when rule is missing 'match'."""
    plugin = tmp_path / "no_match.yaml"
    plugin.write_text("name: bad\npatterns:\n  - name: rule1\n    action: drop_line\n")

    with pytest.raises(ValueError, match="missing required 'match'"):
        load_plugin(plugin)


def test_load_plugin_rule_not_mapping(tmp_path):
    """Plugin loader should raise ValueError when rule is not a mapping."""
    plugin = tmp_path / "bad_rule.yaml"
    plugin.write_text("name: bad\npatterns:\n  - just_a_string\n")

    with pytest.raises(ValueError, match="must be a mapping"):
        load_plugin(plugin)


def test_load_plugin_valid(tmp_path):
    """Plugin loader should correctly parse a valid plugin."""
    plugin = tmp_path / "good.yaml"
    plugin.write_text(
        "name: test-plugin\n"
        "description: A test plugin\n"
        "patterns:\n"
        "  - name: drop_debug\n"
        "    match: 'DEBUG'\n"
        "    action: drop_line\n"
    )

    result = load_plugin(plugin)
    assert result is not None
    assert result.name == "test-plugin"
    assert len(result.rules) == 1
    assert result.rules[0].name == "drop_debug"
    assert result.rules[0].pattern == "DEBUG"
