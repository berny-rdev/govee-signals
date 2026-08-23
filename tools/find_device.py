#!/usr/bin/env python3
"""List every Govee device on the account with its sku + device id.

Run this to fill in GOVEE_DEVICE_SKU / GOVEE_DEVICE_ID in .env:
    python3 tools/find_device.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from govee_client import GoveeClient


def main():
    if not config.API_KEY:
        print(f"GOVEE_API_KEY is not set (looked in {config.ENV_PATH})", file=sys.stderr)
        return 1
    # sku/device are not needed to list devices, so bypass validate().
    devices = GoveeClient(sku="-", device_id="-").list_devices()
    if not devices:
        print("no devices found on this account")
        return 1
    print(f"{'NAME':<24} {'SKU':<10} DEVICE ID")
    for dev in devices:
        print(f"{dev.get('deviceName', '?'):<24} {dev.get('sku', '?'):<10} {dev.get('device', '?')}")
    print("\nCopy the sku + device id of the bulb you want into .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
