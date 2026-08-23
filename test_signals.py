#!/usr/bin/env python3
"""Manual test harness -- trigger flashes on demand, no Claude Code needed.

    python3 test_signals.py            # every configured signal, in order
    python3 test_signals.py stop        # just one
    python3 test_signals.py --state     # print current bulb state and exit
    python3 test_signals.py --devices   # list devices on the account
"""

import argparse
import sys
import time

import config
import signal as signal_mod  # this project's signal.py, not the stdlib module
from govee_client import GoveeClient, GoveeError

PAUSE_BETWEEN = 2.0  # breathing room so you can tell the flashes apart


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("signals", nargs="*", help="signal or color names (default: all signals)")
    parser.add_argument("--state", action="store_true", help="print current bulb state and exit")
    parser.add_argument("--devices", action="store_true", help="list account devices and exit")
    args = parser.parse_args(argv)

    signal_mod.setup_logging(verbose=True)

    try:
        config.validate()
    except RuntimeError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1

    client = GoveeClient()

    if args.devices:
        for dev in client.list_devices():
            print(f"{dev.get('deviceName','?'):<24} {dev.get('sku','?'):<10} {dev.get('device','?')}")
        return 0

    if args.state:
        try:
            print(client.get_state())
        except GoveeError as exc:
            print(f"could not read state: {exc}", file=sys.stderr)
            return 1
        return 0

    names = args.signals or list(config.SIGNALS)
    print(f"device {config.DEVICE_SKU} / {config.DEVICE_ID}")
    try:
        print(f"state before: {client.get_state()}")
    except GoveeError as exc:
        print(f"warning: could not read state: {exc}")

    failures = 0
    for i, name in enumerate(names):
        try:
            spec = config.resolve_signal(name)
        except KeyError as exc:
            print(f"skipping: {exc}")
            failures += 1
            continue
        print(f"\n[{i+1}/{len(names)}] {name} -> {spec['color']} "
              f"(#{spec['rgb']:06X}) x{spec['flashes']}")
        ok = signal_mod.flash_signal(name, client=client)
        print("  ok" if ok else "  FAILED (see govee-signals.log)")
        failures += 0 if ok else 1
        if i < len(names) - 1:
            time.sleep(PAUSE_BETWEEN)

    try:
        print(f"\nstate after: {client.get_state()}")
    except GoveeError:
        pass
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
