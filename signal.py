#!/usr/bin/env python3
"""Capture -> flash -> restore.

flash_signal("stop") reads the bulb's current state, flashes it in the
signal color, then puts it back exactly how it was. If the bulb was off it
goes back off; if it was on it gets its color and brightness back.

Usage:
    python3 signal.py stop          # a configured signal
    python3 signal.py yellow        # an ad-hoc color from config.COLORS
    python3 signal.py --list
"""

import argparse
import logging
import sys
import time

import config
from govee_client import DeviceState, GoveeClient, GoveeError

log = logging.getLogger("signal")


def setup_logging(verbose=False):
    handlers = [logging.FileHandler(config.LOG_PATH, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler(sys.stderr))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def flash_signal(name: str, client: GoveeClient = None) -> bool:
    """Flash the bulb for signal (or color) `name`. Returns True on success.

    Never raises: a smart bulb being unreachable must not break the hook
    that called us.
    """
    try:
        config.validate()
        spec = config.resolve_signal(name)
    except (RuntimeError, KeyError) as exc:
        log.error("cannot run signal %r: %s", name, exc)
        return False

    client = client or GoveeClient()
    log.info("signal=%s color=%s rgb=#%06X", name, spec["color"], spec["rgb"])

    original = _capture(client)
    try:
        _flash(client, spec["rgb"], spec["flashes"])
    except GoveeError as exc:
        log.error("flash failed: %s", exc)
        return False
    finally:
        _restore(client, original)
    return True


def _capture(client) -> DeviceState:
    """Read the pre-flash state. A failure here is survivable: we fall back
    to leaving the bulb off, which is the safer of the two guesses."""
    try:
        state = client.get_state()
        log.info("captured %r", state)
        return state
    except GoveeError as exc:
        log.warning("could not read state, will restore to off: %s", exc)
        return DeviceState()


def _flash(client, rgb: int, count: int):
    """On/off `count` times in `rgb`.

    Color and brightness are set once up front rather than every cycle --
    the bulb keeps them across a power toggle, and every call we skip is
    one less against the Govee rate limit.
    """
    client.set_power(True)
    client.set_color(rgb)
    client.set_brightness(config.FLASH_BRIGHTNESS)
    for i in range(count):
        if i > 0:
            client.set_power(True)
        time.sleep(config.FLASH_ON_SECONDS)
        client.set_power(False)
        if i < count - 1:
            time.sleep(config.FLASH_OFF_SECONDS)


def _restore(client, original: DeviceState):
    try:
        if not original.power:
            client.set_power(False)
            log.info("restored: off")
            return
        if original.rgb is not None:
            client.set_color(original.rgb)
        if original.brightness is not None:
            client.set_brightness(original.brightness)
        client.set_power(True)
        log.info("restored %r", original)
    except GoveeError as exc:
        log.error("restore failed: %s", exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Flash the Govee bulb for a signal.")
    parser.add_argument("signal", nargs="?", help="signal name (stop, notification, stop_failure) or color")
    parser.add_argument("--list", action="store_true", help="list known signals and colors")
    parser.add_argument("-v", "--verbose", action="store_true", help="also log to stderr")
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if args.list:
        print("Signals:")
        for key, spec in config.SIGNALS.items():
            print(f"  {key:<14} {spec['color']:<8} #{config.COLORS[spec['color']]:06X}  {spec['description']}")
        print("Colors:")
        for key, rgb in config.COLORS.items():
            print(f"  {key:<14} #{rgb:06X}")
        return 0

    if not args.signal:
        parser.error("a signal name is required (or use --list)")

    return 0 if flash_signal(args.signal) else 1


if __name__ == "__main__":
    sys.exit(main())
