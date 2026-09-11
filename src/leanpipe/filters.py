"""Plugin loader and filter engine for leanpipe."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml


@dataclass
class FilterRule:
    """A single filter rule from a plugin."""
    name: str
    pattern: str
    action: str  # "drop_line", "skip_block", "keep", "replace"
    replacement: str | None = None
    compiled: re.Pattern = field(init=False, repr=False)

    def __post_init__(self):
        self.compiled = re.compile(self.pattern, re.MULTILINE)


@dataclass
class Plugin:
    """A filter plugin with multiple rules."""
    name: str
    description: str
    command: str | None  # match specific command, or None for global
    rules: list[FilterRule]
    aggressiveness: int = 1  # 1=conservative, 2=balanced, 3=aggressive


def load_plugin(path: Path) -> Plugin | None:
    """Load a plugin from a YAML file."""
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data:
            return None
        rules = [
            FilterRule(
                name=r.get("name", f"rule_{i}"),
                pattern=r["match"],
                action=r.get("action", "drop_line"),
                replacement=r.get("replacement"),
            )
            for i, r in enumerate(data.get("patterns", []))
        ]
        return Plugin(
            name=data.get("name", path.stem),
            description=data.get("description", ""),
            command=data.get("command"),
            rules=rules,
            aggressiveness=data.get("aggressiveness", 1),
        )
    except Exception as e:
        import warnings
        warnings.warn(f"Failed to load plugin {path}: {e}")
        return None


def discover_plugins() -> list[Plugin]:
    """Discover plugins from standard locations."""
    plugins = []
    dirs = [
        Path.home() / ".config" / "leanpipe" / "plugins",
        Path("/etc/leanpipe/plugins"),
    ]
    # Also check LEANPIPE_PLUGIN_DIR env
    env_dir = os.environ.get("LEANPIPE_PLUGIN_DIR")
    if env_dir:
        dirs.insert(0, Path(env_dir))

    for d in dirs:
        if d.exists():
            for f in sorted(d.glob("*.yaml")):
                p = load_plugin(f)
                if p:
                    plugins.append(p)
    return plugins


def apply_plugin(text: str, plugin: Plugin, level: int = 2) -> str:
    """Apply a plugin's rules to text."""
    if level < plugin.aggressiveness:
        return text

    lines = text.split("\n")
    result = []
    skip_depth = 0

    for line in lines:
        if skip_depth > 0:
            # Check if we're back at top level (less indent)
            stripped = line.lstrip()
            if stripped and len(line) - len(line.lstrip()) <= skip_depth:
                skip_depth = 0
            else:
                continue

        matched = False
        for rule in plugin.rules:
            if rule.compiled.search(line):
                if rule.action == "drop_line":
                    matched = True
                    break
                elif rule.action == "skip_block":
                    skip_depth = len(line) - len(line.lstrip())
                    matched = True
                    break
                elif rule.action == "replace" and rule.replacement is not None:
                    line = rule.compiled.sub(rule.replacement, line)
                # "keep" means don't filter this line
        if not matched:
            result.append(line)

    return "\n".join(result)


# Built-in presets (no plugin files needed)
BUILTIN_PRESETS: dict[str, list[FilterRule]] = {
    "kubectl": [
        FilterRule("drop_managed_fields", r"^\s+managedFields:", "skip_block"),
        FilterRule("drop_annotations", r"^\s+annotations:", "skip_block"),
        FilterRule("drop_timestamps", r"^\s+creationTimestamp:", "drop_line"),
        FilterRule("drop_generation", r"^\s+generation:\s*\d+", "drop_line"),
        FilterRule("drop_resource_version", r"^\s+resourceVersion:", "drop_line"),
        FilterRule("drop_uid", r"^\s+uid:", "drop_line"),
        FilterRule("drop_self_link", r"^\s+selfLink:", "drop_line"),
    ],
    "docker": [
        FilterRule("drop_layer_hashes", r"^[a-f0-9]{12}\s", "drop_line"),
        FilterRule("drop_build_logs", r"^Step \d+/\d+", "drop_line"),
        FilterRule("drop_image_id", r"^\s+Image:\s*sha256:", "drop_line"),
    ],
    "git": [
        FilterRule("drop_diff_headers", r"^diff --git", "drop_line"),
        FilterRule("drop_index_lines", r"^index [a-f0-9]+\.\.[a-f0-9]+", "drop_line"),
    ],
    "pytest": [
        FilterRule("drop_fixture_setup", r"^_+\s*fixture_", "drop_line"),
        FilterRule("drop_passed", r".*\s+PASSED\s*$", "drop_line"),
        FilterRule("drop_dashes", r"^_{3,}\s*$", "drop_line"),
    ],
    "find": [
        FilterRule("default_keep", r".*", "keep"),
    ],
    "ls": [
        FilterRule("drop_permissions", r"^[d-][rwx-]{9}", "drop_line"),
    ],
    "grep": [
        FilterRule("default_keep", r".*", "keep"),
    ],
    "npm": [
        FilterRule("drop_deprecation", r"^\s*WARN\s+deprecated", "drop_line"),
        FilterRule("drop_funding", r"^\s*\$\s*npm\s+fund", "drop_line"),
        FilterRule("drop_notice", r"^\s*notice", "drop_line"),
    ],
    "terraform": [
        FilterRule("drop_drift_details", r"^\s*~", "drop_line"),
    ],
}


def get_builtin_preset(name: str) -> Plugin | None:
    """Get a built-in preset by name."""
    rules = BUILTIN_PRESETS.get(name)
    if rules is None:
        return None
    return Plugin(
        name=name,
        description=f"Built-in preset for {name}",
        command=name,
        rules=rules,
        aggressiveness=2,
    )


def filter_text(text: str, preset_name: str | None = None,
                plugins: list[Plugin] | None = None, level: int = 2) -> str:
    """Filter text using a preset and/or plugins."""
    result = text

    # Apply built-in preset first
    if preset_name:
        preset = get_builtin_preset(preset_name)
        if preset:
            result = apply_plugin(result, preset, level)

    # Apply matching plugins
    if plugins:
        for plugin in plugins:
            if plugin.command is None or plugin.command == preset_name:
                result = apply_plugin(result, plugin, level)

    return result
