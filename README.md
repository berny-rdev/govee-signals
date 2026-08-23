# govee-signals

Flash a Govee smart bulb when Claude Code hits a lifecycle event, then put the
bulb back exactly the way it was.

| Event          | Meaning                                | Signal            |
| -------------- | -------------------------------------- | ----------------- |
| `Notification` | Claude needs your input or a decision   | 🟡 yellow ×2      |
| `Stop`         | Task finished cleanly                   | 🔵 blue ×2        |
| `StopFailure`  | Turn ended due to an API/runtime error  | 🔴 red ×2         |

A flash is: on in the signal color → 500 ms → off → 300 ms → repeat once →
restore. Restore is **capture-then-restore**, not a queue: the bulb's power,
color, and brightness are read before the flash and written back after, so a
signal never leaves the room in the wrong state. If the bulb was off it goes
back off.

Python 3.8+, standard library only. No `pip install`.

## Setup

1. **Get an API key** — Govee Home app → Profile → Settings → Apply for API Key.
   It arrives by email.

2. **Create `.env`:**

   ```bash
   cd ~/Desktop/govee-signals
   cp .env.example .env
   ```

3. **Find your bulb** and paste its sku + device id into `.env`:

   ```bash
   python3 tools/find_device.py
   ```

4. **Test it** without waiting for a real Claude Code event:

   ```bash
   python3 test_signals.py            # all three signals, in order
   python3 test_signals.py stop       # just one
   python3 test_signals.py yellow     # any color from config.COLORS
   python3 test_signals.py --state    # print current bulb state
   python3 test_signals.py --devices  # list devices on the account
   ```

   `python3 signal.py stop -v` does a single flash with logging on stderr.
   `python3 signal.py --list` prints every known signal and color.

5. **Wire the hooks.** They are already registered in `~/.claude/settings.json`
   under the `Notification`, `Stop`, and `StopFailure` events. Run `/hooks` in
   Claude Code to review, edit, or disable them. If you move this folder, update
   the paths there.

## How it fits together

```
hooks/on_*.sh          thin shell wrappers, one per event
   └─ signal.py        flash_signal(name): capture → flash → restore
        ├─ config.py       colors, timing, signal definitions, .env loading
        └─ govee_client.py get_state / set_power / set_color / set_brightness
```

`config.py` loads `.env` explicitly from the project directory, so the hooks
work regardless of what environment Claude Code launches them in — nothing
depends on your shell having already exported the keys.

The hook scripts launch `signal.py` detached with `nohup` and exit `0`
immediately. A slow network or an unreachable bulb can never delay or fail a
turn. Failures land in `govee-signals.log` (gitignored) instead of your
terminal.

## Adding a new signal type

Everything a signal needs is declarative. To add one:

1. **Pick a color** — add it to `COLORS` in `config.py` if it isn't there:

   ```python
   COLORS = {..., "orange": 0xFF6000}
   ```

2. **Define the signal** in `SIGNALS`:

   ```python
   SIGNALS = {
       ...,
       "subagent_stop": {
           "color": "orange",
           "flashes": 3,          # per-signal, doesn't have to be 2
           "description": "A subagent finished",
       },
   }
   ```

3. **Add a hook script** — copy an existing one and change the signal name:

   ```bash
   sed 's/"stop"/"subagent_stop"/' hooks/on_stop.sh > hooks/on_subagent_stop.sh
   chmod +x hooks/on_subagent_stop.sh
   ```

4. **Register it** with `/hooks` in Claude Code (or add it to
   `~/.claude/settings.json` alongside the others).

Test it right away with `python3 test_signals.py subagent_stop` — no Claude Code
event needed.

Claude Code's other hook events include `SubagentStop`, `SessionStart`,
`SessionEnd`, `PreCompact`, `PostCompact`, and `UserPromptSubmit`.

### Beyond flashing

`signal.py` deliberately keeps the *what* (a signal's color and count, in
`config.py`) separate from the *how* (`_flash`) and the *transport*
(`govee_client.py`). A new presentation — a fade, a pulse, a color sweep —
is a new function next to `_flash`, selected by a key in the signal spec. A
second device is a second `GoveeClient` instance; nothing in the client is a
module-level singleton.

## Rate limits

Govee rate-limits the developer API. The client enforces a 300 ms floor between
consecutive calls (`MIN_CALL_INTERVAL`), retries up to 3 times with linear
backoff, honors `Retry-After` on HTTP 429, and does not retry other 4xx
responses (a bad key or device id won't get better by asking again). It warns
into the log when the remaining-request header drops below 10.

One flash costs 5 calls: 1 state read, 3 to light it, 1+ to restore.

## Files

| Path                | Purpose                                              |
| ------------------- | ---------------------------------------------------- |
| `.env`              | Real credentials. **Gitignored — never commit.**     |
| `.env.example`      | Template with placeholders. Safe to commit.          |
| `config.py`         | Colors, timing, signal definitions, `.env` loading.  |
| `govee_client.py`   | Govee API wrapper: throttling, retries, state parse. |
| `signal.py`         | `flash_signal()` + CLI. The capture/flash/restore.   |
| `test_signals.py`   | Manual test harness.                                 |
| `tools/find_device.py` | Lists account devices with sku + id.              |
| `hooks/on_*.sh`     | One wrapper per Claude Code event.                   |
| `govee-signals.log` | Runtime log. Gitignored.                             |

## Committing this to git

`.env` is in `.gitignore` and is the only file holding secrets — every other
file is safe to commit. Before the first push, confirm:

```bash
git check-ignore -v .env      # should print the .gitignore rule
git status --short            # .env must NOT appear
```

If you ever commit `.env` by accident, rotate the key in the Govee app —
removing it from git history is not enough once it's pushed.

## Troubleshooting

- **Nothing flashes on a real event** — check `govee-signals.log`. If it's
  empty the hook isn't firing: open `/hooks` in Claude Code to reload config.
- **`missing required config`** — `.env` is absent or a key is blank. `config.py`
  names the path it looked in.
- **`HTTP 401`** — bad or expired API key.
- **`HTTP 429`** — rate limited. The client backs off on its own; raise
  `MIN_CALL_INTERVAL` in `config.py` if it keeps happening.
- **Bulb ends up in the wrong state** — two signals overlapping. v1 handles each
  flash in isolation by design; the second capture reads the first flash's
  intermediate state. Rare in practice since events are seconds apart.
