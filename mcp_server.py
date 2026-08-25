#!/usr/bin/env python3
"""MCP server exposing the Govee bulb as tools Claude can call mid-task.

This is additive to the hooks in hooks/. Both go through the same
flash_signal() in signals.py -- the hooks fire at fixed lifecycle moments,
these tools fire whenever Claude judges them useful.

Runs over stdio, launched as a subprocess. Nothing listens on a socket.
"""

import logging
import sys
from pathlib import Path

# Import the project modules by absolute path, so the server works no matter
# what directory it is launched from.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import signals
from govee_client import GoveeClient

from mcp.server.fastmcp import FastMCP

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
    """Run a configured signal and describe the outcome for the model."""
    try:
        spec = config.resolve_signal(signal_name)
    except KeyError as exc:
        return f"Error: {exc}"
    ok = signals.flash_signal(signal_name, client=_client)
    colour = f"{spec['color']} (#{spec['rgb']:06X})"
    if ok:
        return f"Flashed the light {colour} {spec['flashes']}x, then restored it."
    return (
        f"Could not flash the light {colour} -- the bulb may be unreachable. "
        f"See {config.LOG_PATH}. This does not affect your task; carry on."
    )


@mcp.tool()
def notify_decision_needed() -> str:
    """Flash the user's light to tell them you need their input.

    Call this the moment you realise you are about to stop and wait on the
    user: before asking a question, presenting a choice, or requesting a
    permission you expect them to have to approve. Call it BEFORE you ask,
    so the light and the question arrive together.

    This is most valuable on long or background work, where the user has
    looked away and would not otherwise notice that you have stopped. It is
    the single most useful tool here -- an unnoticed question can stall a
    task for a long time.

    Do NOT call it for a question you are about to answer yourself, or in a
    quick back-and-forth where the user is clearly already watching.
    """
    return _fire("notification")


@mcp.tool()
def notify_task_complete() -> str:
    """Flash the user's light to signal that a milestone is finished.

    A hook already flashes this colour automatically whenever a turn ends,
    so do NOT call this simply because you are about to finish replying --
    that would double-flash for no reason.

    Call it instead when a meaningful milestone lands part-way through a
    long task and the user would want to know now rather than at the end:
    a lengthy build or test suite passing, a migration completing, a
    long-running job finishing while other work continues.
    """
    return _fire("stop")


@mcp.tool()
def notify_error() -> str:
    """Flash the user's light to signal that something has gone wrong.

    Call this when you hit a genuine blocker the user will want to know
    about promptly: a build or deploy that fails, a test suite that breaks,
    an unrecoverable error, or a situation where you cannot proceed without
    them.

    Do NOT call it for routine errors you are about to handle yourself -- a
    failing command you will retry, an expected lint warning, a file you
    will simply create. Reserve it for "this needs a human".
    """
    return _fire("stop_failure")


@mcp.tool()
def flash_custom(color: str, times: int = 2) -> str:
    """Flash the light in an arbitrary colour. Escape hatch for anything the
    three fixed signals do not cover.

    Prefer notify_decision_needed / notify_task_complete / notify_error when
    one of them fits -- their colours are the ones the user has learned to
    read at a glance. Use this only for a genuinely different meaning, or
    when the user explicitly asks for a specific colour.

    Args:
        color: A named colour (yellow, blue, red, green, purple, white) or a
            hex string such as "#FF00FF" / "FF00FF".
        times: How many on/off cycles, 1-10. Defaults to 2.
    """
    times = max(1, min(10, int(times)))
    key = color.strip().lower().lstrip("#")

    rgb = None
    if key in config.COLORS:
        rgb = config.COLORS[key]
        label = key
    else:
        try:
            rgb = int(key, 16)
        except ValueError:
            known = ", ".join(sorted(config.COLORS))
            return f"Error: unknown colour {color!r}. Use one of: {known}, or a hex value like #FF00FF."
        if not 0 <= rgb <= 0xFFFFFF:
            return f"Error: {color!r} is out of range; a colour must be between #000000 and #FFFFFF."
        label = f"#{rgb:06X}"

    log.info("flash_custom color=%s rgb=#%06X times=%d", label, rgb, times)
    if signals.flash_color(rgb, times, client=_client):
        return f"Flashed the light {label} {times}x, then restored it."
    return (
        f"Could not flash the light {label} -- the bulb may be unreachable. "
        f"See {config.LOG_PATH}. This does not affect your task; carry on."
    )


if __name__ == "__main__":
    log.info("govee-signals MCP server starting (device %s / %s)",
             config.DEVICE_SKU, config.DEVICE_ID)
    mcp.run(transport="stdio")
