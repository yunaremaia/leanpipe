"""CLI entry point for leanpipe."""
from __future__ import annotations

import json
import subprocess
import sys

import click

from leanpipe.filters import discover_plugins, filter_text


def format_jsonl(opportunities: list[dict]) -> str:
    """Format opportunities as JSON Lines."""
    lines = []
    for opp in opportunities:
        lines.append(json.dumps(opp))
    return "\n".join(lines)


def run_command(cmd: list[str], stdin_text: str | None = None) -> tuple[str, int]:
    """Run a command and capture stdout+stderr."""
    try:
        result = subprocess.run(
            cmd,
            input=stdin_text,
            capture_output=True,
            text=True,
        )
        output = result.stdout + result.stderr
        return output, result.returncode
    except FileNotFoundError:
        return f"Command not found: {cmd[0]}", 127
    except Exception as e:
        return str(e), 1


@click.group()
@click.version_option()
def main():
    """leanpipe — CLI output filter for AI agents."""


@main.command()
@click.argument("preset", required=False)
@click.option("--level", "-l", type=int, default=2, help="Aggressiveness 1-3")
@click.option("--json", "json_output", is_flag=True, help="Output JSON {output, saved}")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "jsonl"], case_sensitive=False),
    default=None,
    help="Output format: text, json, jsonl",
)
@click.option("--jsonl", is_flag=True, help="Output JSON Lines (shorthand for --format jsonl)")
@click.option("--plugins", is_flag=True, help="Load user plugins too")
def filter(preset, level, json_output, output_format, jsonl, plugins):
    """Filter stdin through a preset. Usage: <command> | leanpipe filter kubectl"""
    text = sys.stdin.read()
    plugin_list = discover_plugins() if plugins else None
    result = filter_text(text, preset_name=preset, plugins=plugin_list, level=level)

    fmt = output_format.lower() if output_format else None
    if jsonl or fmt == "jsonl":
        records = [
            {"line": i + 1, "content": line}
            for i, line in enumerate(result.splitlines())
        ]
        if records:
            click.echo(format_jsonl(records))
    elif json_output or fmt == "json":
        saved = len(text) - len(result)
        click.echo(json.dumps({"output": result, "saved_chars": saved, "saved_pct": round(saved / max(len(text), 1) * 100, 1)}))
    else:
        click.echo(result, nl=False)


@main.command(context_settings={"ignore_unknown_options": True})
@click.argument("command", nargs=-1, required=True)
@click.option("--preset", "-p", help="Preset to apply")
@click.option("--level", "-l", type=int, default=2, help="Aggressiveness 1-3")
@click.option("--json", "json_output", is_flag=True, help="Output JSON {output, saved, exit_code}")
@click.option(
    "--format",
    "-f",
    "output_format",
    type=click.Choice(["text", "json", "jsonl"], case_sensitive=False),
    default=None,
    help="Output format: text, json, jsonl",
)
@click.option("--jsonl", is_flag=True, help="Output JSON Lines (shorthand for --format jsonl)")
@click.option("--plugins", is_flag=True, help="Load user plugins too")
@click.pass_context
def run(ctx, command, preset, level, json_output, output_format, jsonl, plugins):
    """Run a command and filter output. Usage: leanpipe run -- git status"""
    output, exit_code = run_command(list(command))
    plugin_list = discover_plugins() if plugins else None

    # Auto-detect preset from command if not specified
    if not preset and command:
        preset = command[0]

    result = filter_text(output, preset_name=preset, plugins=plugin_list, level=level)

    fmt = output_format.lower() if output_format else None
    if jsonl or fmt == "jsonl":
        records = [
            {"line": i + 1, "content": line}
            for i, line in enumerate(result.splitlines())
        ]
        if records:
            click.echo(format_jsonl(records))
    elif json_output or fmt == "json":
        saved = len(output) - len(result)
        click.echo(json.dumps({
            "output": result,
            "exit_code": exit_code,
            "saved_chars": saved,
            "saved_pct": round(saved / max(len(output), 1) * 100, 1),
        }))
    else:
        click.echo(result, nl=False)
    sys.exit(exit_code)


@main.command()
def presets():
    """List built-in presets."""
    from leanpipe.filters import BUILTIN_PRESETS
    for name, rules in BUILTIN_PRESETS.items():
        click.echo(f"{name:12s}  {len(rules)} rules")


@main.command()
def plugins():
    """List discovered plugins."""
    discovered = discover_plugins()
    if not discovered:
        click.echo("No plugins found. Put .yaml files in ~/.config/leanpipe/plugins/")
        return
    for p in discovered:
        click.echo(f"{p.name:20s}  {len(p.rules)} rules  {p.description}")


if __name__ == "__main__":
    main()
