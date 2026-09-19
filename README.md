# leanpipe

**CLI output filter for AI agents — strip noise, keep signal, save tokens.**

```
kubectl get pods -o yaml | leanpipe filter kubectl
```

AI coding agents waste tokens on verbose CLI output. A single `kubectl get -o yaml` or `git diff` can burn 10k+ tokens. `leanpipe` sits in between, stripping noise and passing only what matters.

## Install

```bash
pip install leanpipe
# or
uv tool install leanpipe
```

## Quick Start

### Pipe mode
```bash
kubectl get pods -o yaml | leanpipe filter kubectl
git diff | leanpipe filter git
pytest -v 2>&1 | leanpipe filter pytest
```

### Run mode
```bash
leanpipe run -- git status
leanpipe run --preset kubectl -- kubectl describe pod my-pod
```

### Aggressiveness levels
```bash
| leanpipe filter kubectl -l 1  # conservative
| leanpipe filter kubectl -l 2  # balanced (default)
| leanpipe filter kubectl -l 3  # aggressive
```

## Built-in Presets

| Preset | What it strips | Use case |
|--------|---------------|----------|
| `kubectl` | managedFields, annotations, timestamps, generation, uid | Agent needs status, not K8s internals |
| `docker` | layer hashes, build step noise | Agent sees container state, not build noise |
| `git` | diff headers, index lines | Agent focuses on actual changes |
| `pytest` | fixture setup dashes, PASSED lines | Agent sees failures only |
| `npm` | deprecation warnings, funding notices | Agent sees install results |
| `find`, `ls` | permissions, sizes (unless kept) | Agent sees paths |
| `grep` | extra context beyond match | Agent sees matching lines |

## Custom Plugins

```yaml
# ~/.config/leanpipe/plugins/terraform.yaml
name: terraform
description: "Strip drift details"
patterns:
  - name: "Drop changed lines"
    match: "^\\s*~"
    action: drop_line
```

```bash
leanpipe run --preset terraform -- terraform plan
```

## JSON & Streaming Output (CI/agent consumption)

```bash
| leanpipe filter kubectl --json
# {"output": "...", "saved_chars": 12000, "saved_pct": 87.5}

| leanpipe filter kubectl --format jsonl
# {"line": 1, "content": "items:"}
# {"line": 2, "content": "- name: my-pod"}
```

## Validation

Inspired by [lowfat](https://github.com/zdk/lowfat) (Rust), which saved 91.8% of tokens in personal use. `leanpipe` brings the same pattern to Python — where AI agents (Claude Code, Codex, OpenCode, Hermes) most commonly run.

## License

MIT
