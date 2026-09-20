"""Tests for leanpipe."""
import json
import subprocess
import sys

import pytest
from click.testing import CliRunner

from leanpipe.cli import format_jsonl, main
from leanpipe.filters import (
    BUILTIN_PRESETS,
    FilterRule,
    Plugin,
    apply_plugin,
    filter_text,
    get_builtin_preset,
)


class TestFilterRule:
    def test_compiled_pattern_caching(self):
        from leanpipe.filters import get_compiled_pattern
        p1 = get_compiled_pattern(r"^DEBUG:\s*")
        p2 = get_compiled_pattern(r"^DEBUG:\s*")
        assert p1 is p2
        rule1 = FilterRule("r1", r"^DEBUG:\s*", "drop_line")
        rule2 = FilterRule("r2", r"^DEBUG:\s*", "drop_line")
        assert rule1.compiled is rule2.compiled

    def test_drop_line(self):
        rule = FilterRule("test", r"DEBUG", "drop_line")
        text = "INFO: ok\nDEBUG: noise\nINFO: done"
        plugin = Plugin("test", "test", None, [rule])
        result = apply_plugin(text, plugin)
        assert "DEBUG" not in result
        assert "INFO: ok" in result
        assert "INFO: done" in result

    def test_drop_all_matching(self):
        rule = FilterRule("drop_noise", r"^WARN", "drop_line")
        text = "WARN foo\nWARN bar\nkeep"
        plugin = Plugin("test", "test", None, [rule])
        result = apply_plugin(text, plugin)
        assert result == "keep"

    def test_replace(self):
        rule = FilterRule("redact", r"secret_\w+", "replace", "REDACTED")
        text = "abc secret_key def"
        plugin = Plugin("test", "test", None, [rule])
        result = apply_plugin(text, plugin)
        assert "REDACTED" in result
        assert "secret_" not in result

    def test_keep_does_nothing(self):
        rule = FilterRule("keep", r".*", "keep")
        text = "anything here"
        plugin = Plugin("test", "test", None, [rule])
        result = apply_plugin(text, plugin)
        assert result == "anything here"


class TestBuiltinPresets:
    def test_kubectl_drops_managed_fields(self):
        text = "items:\n- name: foo\n  managedFields:\n  - a: 1\n  - b: 2"
        result = filter_text(text, preset_name="kubectl")
        assert "managedFields" not in result

    def test_kubectl_drops_annotations(self):
        text = "metadata:\n  annotations:\n    note: xyz\n  name: foo"
        result = filter_text(text, preset_name="kubectl")
        assert "annotations" not in result

    def test_kubectl_drops_timestamps(self):
        text = "items:\n- name: foo\n  creationTimestamp: 2024-01-01"
        result = filter_text(text, preset_name="kubectl")
        assert "creationTimestamp" not in result
        assert "items:" in result
        assert "name: foo" in result

    def test_docker_drops_layer_hashes(self):
        text = "abc123def456 Layer 1\nbuild output here"
        result = filter_text(text, preset_name="docker")
        assert "abc123def456" not in result
        assert "build output" in result

    def test_git_drops_diff_headers(self):
        text = "diff --git a/file b/file\nindex 123..456\n+new line\n-old line"
        result = filter_text(text, preset_name="git")
        assert "diff --git" not in result
        assert "index 123..456" not in result
        assert "+new line" in result
        assert "-old line" in result

    def test_npm_strips_deprecation(self):
        text = "added 1 package\nWARN deprecated foo@1.0.0\nall good"
        result = filter_text(text, preset_name="npm")
        assert "deprecated" not in result
        assert "added 1 package" in result

    def test_pytest_strips_passed(self):
        text = "test_foo PASSED\n  ______ some_fixture\nF test_bar FAILED"
        result = filter_text(text, preset_name="pytest")
        assert "PASSED" not in result
        assert "test_bar FAILED" in result

    def test_pytest_strips_dashes(self):
        text = "test_foo PASSED\n__________\ntest_bar PASSED"
        result = filter_text(text, preset_name="pytest")
        assert "__________" not in result


class TestFilterText:
    def test_no_preset_returns_unchanged(self):
        text = "hello world"
        result = filter_text(text, preset_name=None)
        assert result == text

    def test_unknown_preset_returns_unchanged(self):
        text = "hello world"
        result = filter_text(text, preset_name="nonexistent")
        assert result == text

    def test_empty_text(self):
        assert filter_text("", preset_name="kubectl") == ""


class TestCLI:
    runner = CliRunner()

    def test_presets_command(self):
        result = self.runner.invoke(main, ["presets"])
        assert result.exit_code == 0
        assert "kubectl" in result.output

    def test_filter_kubectl(self):
        text = "metadata:\n  name: foo\n  creationTimestamp: 2024\nitems:\n- a: 1"
        result = self.runner.invoke(main, ["filter", "kubectl"], input=text)
        assert result.exit_code == 0
        assert "creationTimestamp" not in result.output
        assert "name: foo" in result.output

    def test_filter_json_output(self):
        text = "items:\n- name: foo\n  managedFields: x"
        result = self.runner.invoke(main, ["filter", "kubectl", "--json"], input=text)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "output" in data
        assert "saved_chars" in data
        assert "saved_pct" in data

    def test_jsonl_output(self):
        text = "items:\n- name: foo\n  managedFields: x\n- name: bar"
        result = self.runner.invoke(main, ["filter", "kubectl", "--format", "jsonl"], input=text)
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().splitlines() if line]
        assert len(lines) >= 2
        for line in lines:
            data = json.loads(line)
            assert isinstance(data, dict)
            assert "line" in data
            assert "content" in data
            assert "managedFields" not in data["content"]

    def test_jsonl_streaming(self):
        import io
        text = "line 1\nline 2\nline 3\n"
        result = self.runner.invoke(main, ["filter", "--format", "jsonl"], input=text)
        assert result.exit_code == 0
        stream = io.StringIO(result.output)
        streamed_records = []
        for line in stream:
            line_str = line.strip()
            if line_str:
                parsed = json.loads(line_str)
                streamed_records.append(parsed)
        assert len(streamed_records) == 3
        assert [r["content"] for r in streamed_records] == ["line 1", "line 2", "line 3"]
        assert [r["line"] for r in streamed_records] == [1, 2, 3]

    def test_filter_jsonl_flag(self):
        text = "entry1\nentry2"
        result = self.runner.invoke(main, ["filter", "--jsonl"], input=text)
        assert result.exit_code == 0
        lines = [line for line in result.output.strip().splitlines() if line]
        assert len(lines) == 2
        assert json.loads(lines[0])["content"] == "entry1"
        assert json.loads(lines[1])["content"] == "entry2"

    def test_format_jsonl_function(self):
        opportunities = [
            {"id": 1, "title": "Opportunity 1"},
            {"id": 2, "title": "Opportunity 2"},
        ]
        output = format_jsonl(opportunities)
        lines = output.splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == opportunities[0]
        assert json.loads(lines[1]) == opportunities[1]

    @pytest.mark.skipif(sys.platform == "win32", reason="echo is a shell built-in on Windows")
    def test_run_command(self):
        result = self.runner.invoke(main, ["run", "--", "echo", "hello"])
        assert result.exit_code == 0
        assert "hello" in result.output

    @pytest.mark.skipif(sys.platform == "win32", reason="echo is a shell built-in on Windows")
    def test_run_with_preset(self):
        result = self.runner.invoke(main, ["run", "--preset", "kubectl", "--", "echo", "metadata:\n  creationTimestamp: x\n  name: foo"])
        assert result.exit_code == 0
        assert "creationTimestamp" not in result.output
        assert "name: foo" in result.output

    def test_plugins_empty(self):
        result = self.runner.invoke(main, ["plugins"])
        assert result.exit_code == 0

    def test_filter_no_preset(self):
        text = "hello world"
        result = self.runner.invoke(main, ["filter"], input=text)
        assert result.exit_code == 0
        assert result.output == text
