"""Tests for leanpipe plugin loading and discovery."""
import pytest

from leanpipe.filters import discover_plugins, load_plugin


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


def test_load_plugin_empty_file_returns_none(tmp_path):
    """An empty plugin file yields no plugin rather than an error."""
    plugin = tmp_path / "empty.yaml"
    plugin.write_text("")

    assert load_plugin(plugin) is None


def test_load_plugin_null_patterns_is_a_valid_empty_plugin(tmp_path):
    """A bare `patterns:` key is equivalent to `patterns: []`.

    Both forms, and omitting the key entirely, describe a plugin with no rules
    and are all accepted. What must never happen is a TypeError escaping
    load_plugin: enumerate(None) used to break that contract, so the loader
    advertised ValueError for malformed plugins but raised TypeError here.
    """
    plugin = tmp_path / "null_patterns.yaml"
    plugin.write_text("name: bare\npatterns:\n")

    result = load_plugin(plugin)
    assert result is not None
    assert result.name == "bare"
    assert result.rules == []


def test_load_plugin_patterns_not_a_list(tmp_path):
    """A scalar `patterns:` value is rejected with the documented error type."""
    plugin = tmp_path / "scalar_patterns.yaml"
    plugin.write_text("name: broken\npatterns: DEBUG\n")

    with pytest.raises(ValueError, match="must be a list"):
        load_plugin(plugin)


def test_load_plugin_missing_patterns_key_defaults_empty(tmp_path):
    """Omitting `patterns` entirely is valid and yields a ruleless plugin."""
    plugin = tmp_path / "no_patterns.yaml"
    plugin.write_text("name: harmless\ndescription: nothing to strip\n")

    result = load_plugin(plugin)
    assert result is not None
    assert result.name == "harmless"
    assert result.rules == []


def test_load_plugin_defaults(tmp_path):
    """Unspecified fields fall back to documented defaults."""
    plugin = tmp_path / "minimal.yaml"
    plugin.write_text("patterns:\n  - match: 'DEBUG'\n    action: drop_line\n")

    result = load_plugin(plugin)
    assert result is not None
    # Name defaults to the file stem, rule name to its index.
    assert result.name == "minimal"
    assert result.rules[0].name == "rule_0"
    assert result.command is None
    assert result.aggressiveness == 1
    assert result.description == ""


def test_load_plugin_reads_aggressiveness_and_command(tmp_path):
    plugin = tmp_path / "scoped.yaml"
    plugin.write_text(
        "name: scoped\n"
        "command: kubectl\n"
        "aggressiveness: 3\n"
        "patterns:\n"
        "  - match: 'DEBUG'\n"
        "    action: drop_line\n"
    )

    result = load_plugin(plugin)
    assert result is not None
    assert result.command == "kubectl"
    assert result.aggressiveness == 3


def test_load_plugin_replace_keeps_replacement(tmp_path):
    plugin = tmp_path / "redact.yaml"
    plugin.write_text(
        "patterns:\n"
        "  - match: 'secret_\\\\w+'\n"
        "    action: replace\n"
        "    replacement: 'REDACTED'\n"
    )

    result = load_plugin(plugin)
    assert result is not None
    assert result.rules[0].replacement == "REDACTED"


class TestDiscoverPlugins:
    def test_env_dir_is_searched(self, tmp_path, monkeypatch):
        (tmp_path / "one.yaml").write_text(
            "name: from-env\npatterns:\n  - match: 'DEBUG'\n    action: drop_line\n"
        )
        monkeypatch.setenv("LEANPIPE_PLUGIN_DIR", str(tmp_path))

        found = discover_plugins()
        assert [p.name for p in found] == ["from-env"]

    def test_only_yaml_files_are_loaded(self, tmp_path, monkeypatch):
        (tmp_path / "good.yaml").write_text("name: kept\npatterns: []\n")
        (tmp_path / "ignored.yml").write_text("name: skipped\npatterns: []\n")
        (tmp_path / "notes.txt").write_text("not a plugin")
        monkeypatch.setenv("LEANPIPE_PLUGIN_DIR", str(tmp_path))

        assert [p.name for p in discover_plugins()] == ["kept"]

    def test_missing_dir_yields_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LEANPIPE_PLUGIN_DIR", str(tmp_path / "does-not-exist"))

        assert discover_plugins() == []

    def test_plugins_are_sorted_by_filename(self, tmp_path, monkeypatch):
        for name in ("b", "a", "c"):
            (tmp_path / f"{name}.yaml").write_text(f"name: {name}\npatterns: []\n")
        monkeypatch.setenv("LEANPIPE_PLUGIN_DIR", str(tmp_path))

        assert [p.name for p in discover_plugins()] == ["a", "b", "c"]

    def test_empty_plugin_files_are_skipped(self, tmp_path, monkeypatch):
        (tmp_path / "a.yaml").write_text("")
        (tmp_path / "b.yaml").write_text("name: real\npatterns: []\n")
        monkeypatch.setenv("LEANPIPE_PLUGIN_DIR", str(tmp_path))

        assert [p.name for p in discover_plugins()] == ["real"]
