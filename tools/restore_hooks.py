#!/usr/bin/env python3
"""Put the Claude Code hooks back.

The hooks were removed in favour of the MCP tools. This merges the exact
config that was removed (hooks/disabled-hooks.json) back into
~/.claude/settings.json, skipping any event already wired up.

    python3 tools/restore_hooks.py            # restore all three
    python3 tools/restore_hooks.py StopFailure  # restore just one

StopFailure is the one worth restoring on its own: when a turn dies from an
API error the model cannot call an MCP tool to report it, so that is the one
signal a tool genuinely cannot replace.
"""

import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
BACKUP = PROJECT / "hooks" / "disabled-hooks.json"
SETTINGS = Path.home() / ".claude" / "settings.json"


def main(argv):
    wanted = argv[1:]
    if not BACKUP.exists():
        print(f"no backup at {BACKUP}", file=sys.stderr)
        return 1

    saved = json.loads(BACKUP.read_text()).get("hooks", {})
    if wanted:
        unknown = [w for w in wanted if w not in saved]
        if unknown:
            print(f"unknown event(s): {', '.join(unknown)}; "
                  f"backup has: {', '.join(saved)}", file=sys.stderr)
            return 1
        saved = {k: v for k, v in saved.items() if k in wanted}

    cfg = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    hooks = cfg.setdefault("hooks", {})

    restored, skipped = [], []
    for event, entries in saved.items():
        existing = hooks.setdefault(event, [])
        cmds = {h.get("command") for e in existing for h in e.get("hooks", [])}
        for entry in entries:
            if any(h.get("command") in cmds for h in entry.get("hooks", [])):
                skipped.append(event)
                continue
            existing.append(entry)
            restored.append(event)

    if not hooks:
        cfg.pop("hooks")
    SETTINGS.write_text(json.dumps(cfg, indent=2) + "\n")

    print(f"restored: {', '.join(restored) or '(none)'}")
    if skipped:
        print(f"already present, skipped: {', '.join(skipped)}")
    print("\nOpen /hooks in Claude Code to reload, or restart the session.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
