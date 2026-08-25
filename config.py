"""Central configuration for govee-signals.

Everything that a new signal type might need to change lives here:
colors, timing, and the signal -> presentation mapping. Adding a new
signal should not require touching govee_client.py or signals.py.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
LOG_PATH = PROJECT_ROOT / "govee-signals.log"


def load_env(path: Path = ENV_PATH) -> None:
    """Load KEY=VALUE pairs from .env into os.environ.

    Hooks are launched by Claude Code with a bare environment, so we never
    assume the shell already exported these. Existing env vars win, which
    makes it easy to override a value for a one-off test.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


load_env()

# --- Credentials / device -------------------------------------------------

API_KEY = os.environ.get("GOVEE_API_KEY", "")
DEVICE_SKU = os.environ.get("GOVEE_DEVICE_SKU", "")
DEVICE_ID = os.environ.get("GOVEE_DEVICE_ID", "")

BASE_URL = os.environ.get("GOVEE_BASE_URL", "https://openapi.api.govee.com")

# --- Colors ---------------------------------------------------------------
# Govee wants colorRgb as a single integer (0xRRGGBB in decimal).

COLORS = {
    "yellow": 0xFFD000,
    "blue": 0x0064FF,
    "red": 0xFF0000,
    "green": 0x00FF00,
    "purple": 0x8000FF,
    "white": 0xFFFFFF,
}

# --- Timing ---------------------------------------------------------------

FLASH_COUNT = 2           # how many on/off cycles make up one signal
FLASH_ON_SECONDS = 0.5    # bulb held on during a flash
FLASH_OFF_SECONDS = 0.3   # gap between flashes

MIN_CALL_INTERVAL = 0.3   # enforced spacing between any two Govee API calls
REQUEST_TIMEOUT = 10.0    # seconds before an HTTP call is considered dead
MAX_RETRIES = 3           # attempts per call before giving up
RETRY_BACKOFF = 1.5       # seconds, multiplied by attempt number

FLASH_BRIGHTNESS = 100    # brightness used during the flash itself (percent)

# A Govee bulb remembers its color/brightness across a power cycle, and the
# only way to write them is with the bulb lit. So restoring the pre-flash
# color of a bulb that was OFF costs one extra blip of light before it goes
# back off. True = the bulb's remembered state is left exactly as found;
# False = it ends off but remembering the signal color.
RESTORE_COLOR_WHEN_OFF = True

# --- Signals --------------------------------------------------------------
# The extension point. A signal maps a Claude Code lifecycle event to a
# visual presentation. To add a new signal type: add an entry here and drop
# a matching script in hooks/.

SIGNALS = {
    "notification": {
        "color": "blue",
        "flashes": FLASH_COUNT,
        "description": "Claude needs your input or a decision",
    },
    "stop": {
        "color": "green",
        "flashes": FLASH_COUNT,
        "description": "Task finished cleanly",
    },
    "stop_failure": {
        "color": "purple",
        "flashes": FLASH_COUNT,
        "description": "Turn ended due to an API/runtime error",
    },
}


def resolve_signal(name: str) -> dict:
    """Accept either a signal name ('stop') or a raw color name ('blue')."""
    key = name.strip().lower().replace("-", "_")
    if key in SIGNALS:
        spec = dict(SIGNALS[key])
        spec["rgb"] = COLORS[spec["color"]]
        return spec
    if key in COLORS:
        return {
            "color": key,
            "rgb": COLORS[key],
            "flashes": FLASH_COUNT,
            "description": f"ad-hoc {key} flash",
        }
    known = sorted(set(SIGNALS) | set(COLORS))
    raise KeyError(f"unknown signal or color {name!r}; known: {', '.join(known)}")


def validate() -> None:
    missing = [
        name
        for name, value in (
            ("GOVEE_API_KEY", API_KEY),
            ("GOVEE_DEVICE_SKU", DEVICE_SKU),
            ("GOVEE_DEVICE_ID", DEVICE_ID),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            f"missing required config: {', '.join(missing)} "
            f"(expected in {ENV_PATH})"
        )
