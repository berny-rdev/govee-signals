#!/usr/bin/env python3
"""MCP server exposing the Govee bulb as tools Claude can call mid-task.

This is additive to the hooks in hooks/. Both go through the same
flash_color() in signals.py -- the hooks fire at fixed lifecycle moments,
these tools fire whenever Claude judges them useful.

Runs over stdio, launched as a subprocess. Nothing listens on a socket.

Two profiles, because the two clients need genuinely different advice:

  --profile code     (default) Claude Code. A Stop hook already flashes when
                     a turn ends, so the tools must NOT duplicate it. Two
                     flashes, matching the hooks.

  --profile desktop  Claude Desktop chat, which has no hooks at all. Nothing
                     fires automatically, so here the model IS told to signal
                     when it finishes a long response. One flash, to stay
                     light and to be distinguishable from a hook's double.

The profile is set per registration (Claude Code via `claude mcp add`,
Desktop via claude_desktop_config.json), so each client gets its own.
"""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import signals
from govee_client import GoveeClient

from mcp.server.fastmcp import FastMCP

# Parsed at import time: the tool descriptions and flash_custom's default
# argument are both built from it below, before the decorators run.
_parser = argparse.ArgumentParser(add_help=False)
_parser.add_argument("--profile", choices=("code", "desktop"), default="code")
_args, _ = _parser.parse_known_args()
PROFILE = _args.profile
IS_DESKTOP = PROFILE == "desktop"
DEFAULT_TIMES = config.DESKTOP_FLASH_COUNT if IS_DESKTOP else config.FLASH_COUNT

# Log to file, never stdout: stdout is the MCP wire protocol and anything
# stray on it corrupts the session.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(config.LOG_PATH, encoding="utf-8")],
    force=True,
)
log = logging.getLogger("mcp")

mcp = FastMCP("govee-signals")

# One client for the process, so its rate-limit throttle is shared across
# every tool call rather than each call starting with a fresh budget.
_client = GoveeClient()


def _fire(signal_name: str) -> str:
    """Run a configured signal at this profile's flash count."""
    try:
        spec = config.resolve_signal(signal_name)
    except KeyError as exc:
        return f"Error: {exc}"
    times = DEFAULT_TIMES
    log.info("tool=%s profile=%s color=%s rgb=#%06X times=%d",
             signal_name, PROFILE, spec["color"], spec["rgb"], times)
    colour = f"{spec['color']} (#{spec['rgb']:06X})"
    if signals.flash_color(spec["rgb"], times, client=_client):
        return f"Flashed the light {colour} {times}x, then restored it."
    return (
        f"Could not flash the light {colour} -- the bulb may be unreachable. "
        f"See {config.LOG_PATH}. This does not affect your task; carry on."
    )


# --- tool descriptions, per profile ---------------------------------------
# These are the ONLY thing steering when Claude calls these tools, so they
# are written as instructions rather than documentation.

_N = DEFAULT_TIMES
_TIMES = "once" if _N == 1 else f"{_N} times"

DECISION_DESC = f"""Flash the user's light {_TIMES} to tell them you need their input.

Call this the moment you realise you are about to stop and wait on the user:
before asking a question, presenting a choice, or requesting a permission you
expect them to approve. Call it BEFORE you ask, so the light and the question
arrive together.

This is most valuable when the user has probably looked away -- long work, or
a reply they have been waiting on. It is the single most useful tool here: an
unnoticed question can stall things for a long time.

Do NOT call it for a question you are about to answer yourself, or in a quick
back-and-forth where the user is clearly already watching."""

if IS_DESKTOP:
    COMPLETE_DESC = f"""Flash the user's light {_TIMES} in green to signal that you have finished responding.

Nothing here flashes automatically, so this is the only way the user learns
you are done without watching the window.

Call it as the very last thing you do, when your response took long enough
that the user plausibly looked away: a lengthy analysis or piece of writing, a
multi-step task, anything involving several tool calls or a long wait.

Do NOT call it after a short conversational reply that came back in a couple
of seconds -- the user is still watching, and the flash is just noise."""
else:
    COMPLETE_DESC = f"""Flash the user's light {_TIMES} to signal that a milestone is finished.

A hook already flashes this colour automatically whenever a turn ends, so do
NOT call this simply because you are about to finish replying -- that would
double-flash for no reason.

Call it instead when a meaningful milestone lands part-way through a long task
and the user would want to know now rather than at the end: a lengthy build or
test suite passing, a migration completing, a long-running job finishing while
other work continues."""

ERROR_DESC = f"""Flash the user's light {_TIMES} to signal that something has gone wrong.

Call this when you hit a genuine blocker the user will want to know about
promptly: a build or deploy that fails, a test suite that breaks, an
unrecoverable error, or a situation where you cannot proceed without them.

Do NOT call it for routine errors you are about to handle yourself -- a
failing command you will retry, an expected lint warning, a file you will
simply create. Reserve it for "this needs a human"."""

CUSTOM_DESC = f"""Flash the light in an arbitrary colour. Escape hatch for anything the three
fixed signals do not cover.

Prefer notify_decision_needed / notify_task_complete / notify_error when one of
them fits -- their colours are the ones the user has learned to read at a
glance. Use this only for a genuinely different meaning, or when the user
explicitly asks for a specific colour.

Args:
    color: A named colour (yellow, blue, red, green, purple, white) or a hex
        string such as "#FF00FF" / "FF00FF".
    times: How many on/off cycles, 1-10. Defaults to {_N}."""


@mcp.tool(description=DECISION_DESC)
def notify_decision_needed() -> str:
    return _fire("notification")


@mcp.tool(description=COMPLETE_DESC)
def notify_task_complete() -> str:
    return _fire("stop")


@mcp.tool(description=ERROR_DESC)
def notify_error() -> str:
    return _fire("stop_failure")


@mcp.tool(description=CUSTOM_DESC)
def flash_custom(color: str, times: int = DEFAULT_TIMES) -> str:
    times = max(1, min(10, int(times)))
    key = color.strip().lower().lstrip("#")

    if key in config.COLORS:
        rgb, label = config.COLORS[key], key
    else:
        try:
            rgb = int(key, 16)
        except ValueError:
            known = ", ".join(sorted(config.COLORS))
            return f"Error: unknown colour {color!r}. Use one of: {known}, or a hex value like #FF00FF."
        if not 0 <= rgb <= 0xFFFFFF:
            return f"Error: {color!r} is out of range; a colour must be between #000000 and #FFFFFF."
        label = f"#{rgb:06X}"

    log.info("flash_custom profile=%s color=%s rgb=#%06X times=%d", PROFILE, label, rgb, times)
    if signals.flash_color(rgb, times, client=_client):
        return f"Flashed the light {label} {times}x, then restored it."
    return (
        f"Could not flash the light {label} -- the bulb may be unreachable. "
        f"See {config.LOG_PATH}. This does not affect your task; carry on."
    )


if __name__ == "__main__":
    log.info("govee-signals MCP server starting (profile=%s, device %s / %s)",
             PROFILE, config.DEVICE_SKU, config.DEVICE_ID)
    mcp.run(transport="stdio")
