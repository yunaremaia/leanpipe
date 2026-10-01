"""Tests for the noise/signal decision core: block skipping and level gating.

apply_plugin() is the component that decides what is noise and what is signal.
These tests pin the block-skipping state machine and the aggressiveness gate
directly, rather than only through preset-level integration tests.
"""
import pytest

from leanpipe.filters import (
    BUILTIN_PRESETS,
    FilterRule,
    Plugin,
    apply_plugin,
    filter_text,
    get_builtin_preset,
)


def make_plugin(rules, aggressiveness=2):
    """Build a plugin with an explicit aggressiveness for engine-level tests."""
    return Plugin("test", "test", None, rules, aggressiveness=aggressiveness)


class TestSkipBlock:
    """A skip_block rule drops the marker line and every more-indented child."""

    def test_children_are_dropped(self):
        rule = FilterRule("blk", r"^\s+managedFields:", "skip_block")
        text = "metadata:\n  managedFields:\n    - mgr: x\n      f: 1\n  name: foo"
        result = apply_plugin(text, make_plugin([rule]))
        assert "managedFields" not in result
        assert "mgr: x" not in result
        assert "f: 1" not in result
        assert result == "metadata:\n  name: foo"

    def test_dedent_ends_the_block(self):
        """A sibling at the marker's own indent must survive the skip."""
        rule = FilterRule("blk", r"^\s+deep:", "skip_block")
        text = "top\n  deep:\n    a\n    b\n  shallow: c\nend"
        result = apply_plugin(text, make_plugin([rule]))
        assert result == "top\n  shallow: c\nend"

    def test_marker_at_column_zero_still_skips_children(self):
        """Regression: depth 0 is a real depth, not the "not skipping" sentinel.

        Using 0 as the sentinel made a top-level marker drop its own line and
        then leave every child behind.
        """
        rule = FilterRule("blk", r"^metadata:", "skip_block")
        text = "metadata:\n  name: foo\n  uid: x\nspec:\n  a: 1"
        result = apply_plugin(text, make_plugin([rule]))
        assert result == "spec:\n  a: 1"

    def test_zero_indent_block_returns_to_top_level(self):
        rule = FilterRule("blk", r"^block:", "skip_block")
        text = "block:\n  a\n  b\nnext: 1"
        assert apply_plugin(text, make_plugin([rule])) == "next: 1"

    def test_block_at_end_of_input(self):
        rule = FilterRule("blk", r"^\s+trailing:", "skip_block")
        text = "head\n  trailing:\n    a\n    b"
        assert apply_plugin(text, make_plugin([rule])) == "head"

    def test_blank_line_inside_block_is_dropped(self):
        rule = FilterRule("blk", r"^\s+blk:", "skip_block")
        text = "head\n  blk:\n    a\n\n    b\ntail: 1"
        result = apply_plugin(text, make_plugin([rule]))
        assert result == "head\ntail: 1"

    def test_two_blocks_are_skipped_independently(self):
        rule = FilterRule("blk", r"^\s+blk:", "skip_block")
        text = "top\n  blk:\n    a\nmid: 1\n  blk:\n    b\ntail: 2"
        result = apply_plugin(text, make_plugin([rule]))
        assert result == "top\nmid: 1\ntail: 2"


class TestRuleActions:
    def test_first_matching_drop_line_wins(self):
        rules = [
            FilterRule("drop_first", r"DEBUG", "drop_line"),
            FilterRule("drop_second", r"DEBUG", "drop_line"),
        ]
        assert apply_plugin("DEBUG x\nkeep", make_plugin(rules)) == "keep"

    def test_replace_applies_every_occurrence_on_the_line(self):
        rule = FilterRule("redact", r"secret_\w+", "replace", "REDACTED")
        result = apply_plugin("a secret_one b secret_two c", make_plugin([rule]))
        assert result == "a REDACTED b REDACTED c"

    def test_replace_without_replacement_is_a_no_op(self):
        """A replace rule with no replacement cannot rewrite anything."""
        rule = FilterRule("noop", r"foo", "replace", None)
        assert apply_plugin("foo bar", make_plugin([rule])) == "foo bar"

    def test_drop_line_only_drops_matching_lines(self):
        rule = FilterRule("drop", r"^WARN", "drop_line")
        text = "INFO up\nWARN a\nWARN b\nINFO down"
        assert apply_plugin(text, make_plugin([rule])) == "INFO up\nINFO down"

    def test_unmatched_text_is_returned_verbatim(self):
        rule = FilterRule("drop", r"^NEVER_MATCHES", "drop_line")
        text = "alpha\nbeta\ngamma"
        assert apply_plugin(text, make_plugin([rule])) == text

    def test_pattern_is_matched_per_line_with_multiline_flag(self):
        """Rules compile with re.MULTILINE, so ^ anchors to each line."""
        rule = FilterRule("anchored", r"^second", "drop_line")
        result = apply_plugin("first\nsecond\nthird", make_plugin([rule]))
        assert result == "first\nthird"


class TestLevelGating:
    """level < aggressiveness must leave the text untouched."""

    def test_level_below_aggressiveness_is_a_passthrough(self):
        text = "metadata:\n  creationTimestamp: x\n  name: foo"
        rule = FilterRule("drop", r"creationTimestamp", "drop_line")
        plugin = make_plugin([rule], aggressiveness=2)
        assert apply_plugin(text, plugin, level=1) == text

    def test_level_equal_to_aggressiveness_applies(self):
        text = "keep\ncreationTimestamp: x"
        rule = FilterRule("drop", r"creationTimestamp", "drop_line")
        plugin = make_plugin([rule], aggressiveness=2)
        assert "creationTimestamp" not in apply_plugin(text, plugin, level=2)

    def test_level_above_aggressiveness_applies(self):
        text = "keep\ncreationTimestamp: x"
        rule = FilterRule("drop", r"creationTimestamp", "drop_line")
        plugin = make_plugin([rule], aggressiveness=2)
        assert "creationTimestamp" not in apply_plugin(text, plugin, level=3)

    @pytest.mark.parametrize("level", [1, 2, 3])
    def test_builtin_presets_use_aggressiveness_two(self, level):
        """Every built-in preset declares aggressiveness 2, so -l 1 is a no-op."""
        text = "metadata:\n  creationTimestamp: x\n  name: foo"
        result = filter_text(text, preset_name="kubectl", level=level)
        if level == 1:
            assert "creationTimestamp" in result
        else:
            assert "creationTimestamp" not in result
            assert "name: foo" in result


class TestBuiltinPresetLookup:
    def test_every_preset_resolves(self):
        for name in BUILTIN_PRESETS:
            preset = get_builtin_preset(name)
            assert preset is not None
            assert preset.name == name
            assert preset.command == name
            assert preset.aggressiveness == 2
            assert preset.rules

    def test_unknown_preset_returns_none(self):
        assert get_builtin_preset("definitely-not-a-preset") is None

    def test_every_preset_rule_compiles(self):
        for name, rules in BUILTIN_PRESETS.items():
            for rule in rules:
                assert rule.compiled is not None, f"{name}/{rule.name}"
                assert rule.action in {"drop_line", "skip_block", "keep", "replace"}

    def test_filter_text_with_unknown_preset_is_unchanged(self):
        text = "alpha\nbeta"
        assert filter_text(text, preset_name="nope") == text


class TestFilterTextPluginMatching:
    """filter_text routes plugins by command: None is global, otherwise exact."""

    def test_global_plugin_applies_without_preset(self):
        plugin = make_plugin([FilterRule("drop", r"^NOISE", "drop_line")])
        plugin.command = None
        assert filter_text("NOISE a\nsignal", plugins=[plugin]) == "signal"

    def test_matching_command_plugin_applies(self):
        plugin = make_plugin([FilterRule("drop", r"^NOISE", "drop_line")])
        plugin.command = "kubectl"
        result = filter_text("NOISE a\nsignal", preset_name="kubectl", plugins=[plugin])
        assert result == "signal"

    def test_non_matching_command_plugin_is_skipped(self):
        plugin = make_plugin([FilterRule("drop", r"^NOISE", "drop_line")])
        plugin.command = "docker"
        text = "NOISE a\nsignal"
        assert filter_text(text, preset_name="kubectl", plugins=[plugin]) == text

    def test_preset_and_plugin_both_apply(self):
        plugin = make_plugin([FilterRule("drop", r"^CUSTOM", "drop_line")])
        plugin.command = "kubectl"
        text = "  creationTimestamp: x\nCUSTOM y\nname: foo"
        result = filter_text(text, preset_name="kubectl", plugins=[plugin])
        assert "creationTimestamp" not in result
        assert "CUSTOM" not in result
        assert "name: foo" in result
