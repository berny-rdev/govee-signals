"""Thin wrapper around the Govee Developer API (stdlib only, no deps).

Only what the signals need: read state, set power, set color, set
brightness. Rate limiting and retries are handled here so callers can stay
naive about them.
"""

import json
import logging
import time
import urllib.error
import urllib.request
import uuid

import config

log = logging.getLogger("govee")

DEVICES_PATH = "/router/api/v1/user/devices"
STATE_PATH = "/router/api/v1/device/state"
CONTROL_PATH = "/router/api/v1/device/control"

CAP_ON_OFF = "devices.capabilities.on_off"
CAP_COLOR = "devices.capabilities.color_setting"
CAP_RANGE = "devices.capabilities.range"


class GoveeError(RuntimeError):
    """A Govee API call failed after exhausting retries."""


class DeviceState:
    """Snapshot of the bulb, enough to put it back the way we found it."""

    def __init__(self, power=None, rgb=None, brightness=None, raw=None):
        self.power = power            # True / False / None if unknown
        self.rgb = rgb                # int or None
        self.brightness = brightness  # 1-100 or None
        self.raw = raw or {}

    def __repr__(self):
        return (
            f"DeviceState(power={self.power}, rgb="
            f"{'#%06X' % self.rgb if self.rgb is not None else None}, "
            f"brightness={self.brightness})"
        )


class GoveeClient:
    def __init__(self, api_key=None, sku=None, device_id=None, base_url=None):
        self.api_key = api_key or config.API_KEY
        self.sku = sku or config.DEVICE_SKU
        self.device_id = device_id or config.DEVICE_ID
        self.base_url = (base_url or config.BASE_URL).rstrip("/")
        self._last_call = 0.0

    # -- plumbing ---------------------------------------------------------

    def _throttle(self):
        """Keep at least MIN_CALL_INTERVAL between consecutive calls."""
        elapsed = time.monotonic() - self._last_call
        wait = config.MIN_CALL_INTERVAL - elapsed
        if wait > 0:
            time.sleep(wait)

    def _request(self, path, payload=None, method=None):
        url = self.base_url + path
        method = method or ("POST" if payload is not None else "GET")
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            "Govee-API-Key": self.api_key,
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(1, config.MAX_RETRIES + 1):
            self._throttle()
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=config.REQUEST_TIMEOUT) as resp:
                    self._last_call = time.monotonic()
                    body = json.loads(resp.read().decode("utf-8"))
                    self._log_rate_limits(resp.headers)
                if body.get("code") not in (200, None):
                    raise GoveeError(f"{path}: {body.get('code')} {body.get('message')}")
                return body
            except urllib.error.HTTPError as exc:
                self._last_call = time.monotonic()
                detail = exc.read().decode("utf-8", "replace")[:300]
                last_error = GoveeError(f"{path}: HTTP {exc.code} {detail}")
                # 429 means we are being told to slow down; back off harder.
                sleep_for = config.RETRY_BACKOFF * attempt
                if exc.code == 429:
                    retry_after = exc.headers.get("Retry-After")
                    sleep_for = max(sleep_for, float(retry_after) if retry_after else 5.0)
                elif 400 <= exc.code < 500 and exc.code != 408:
                    raise last_error  # our fault, retrying will not help
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, GoveeError) as exc:
                self._last_call = time.monotonic()
                last_error = exc if isinstance(exc, GoveeError) else GoveeError(f"{path}: {exc}")
                sleep_for = config.RETRY_BACKOFF * attempt

            if attempt < config.MAX_RETRIES:
                log.warning("govee call failed (attempt %d/%d): %s; retrying in %.1fs",
                            attempt, config.MAX_RETRIES, last_error, sleep_for)
                time.sleep(sleep_for)

        raise last_error or GoveeError(f"{path}: failed")

    @staticmethod
    def _log_rate_limits(headers):
        remaining = headers.get("API-RateLimit-Remaining") or headers.get("X-RateLimit-Remaining")
        if remaining is not None:
            try:
                if int(remaining) < 10:
                    log.warning("govee rate limit low: %s remaining", remaining)
            except ValueError:
                pass

    def _payload(self, extra=None):
        payload = {"sku": self.sku, "device": self.device_id}
        if extra:
            payload.update(extra)
        return {"requestId": str(uuid.uuid4()), "payload": payload}

    # -- public API -------------------------------------------------------

    def list_devices(self):
        """All devices on the account. Used by tools/find_device.py."""
        return self._request(DEVICES_PATH, method="GET").get("data", [])

    def get_state(self) -> DeviceState:
        body = self._request(STATE_PATH, self._payload())
        caps = body.get("payload", {}).get("capabilities", [])
        state = DeviceState(raw=body)
        for cap in caps:
            ctype, instance = cap.get("type"), cap.get("instance")
            value = (cap.get("state") or {}).get("value")
            if value is None:
                continue
            if ctype == CAP_ON_OFF and instance == "powerSwitch":
                state.power = bool(int(value))
            elif ctype == CAP_COLOR and instance == "colorRgb":
                state.rgb = int(value)
            elif ctype == CAP_RANGE and instance == "brightness":
                state.brightness = int(value)
        return state

    def _control(self, cap_type, instance, value):
        return self._request(
            CONTROL_PATH,
            self._payload({"capability": {"type": cap_type, "instance": instance, "value": value}}),
        )

    def set_power(self, on: bool):
        return self._control(CAP_ON_OFF, "powerSwitch", 1 if on else 0)

    def set_color(self, rgb_int: int):
        rgb_int = int(rgb_int) & 0xFFFFFF
        return self._control(CAP_COLOR, "colorRgb", rgb_int)

    def set_brightness(self, percent: int):
        percent = max(1, min(100, int(percent)))
        return self._control(CAP_RANGE, "brightness", percent)
