# govee-signals

Flash a Govee smart bulb when Claude Code hits a lifecycle event, then put the
bulb back exactly the way it was.

| Event          | Meaning                                | Signal            |
| -------------- | -------------------------------------- | ----------------- |
| `Notification` | Claude needs your input or a decision   | 🔵 blue ×2        |
| `Stop`         | Task finished cleanly                   | 🟢 green ×2       |
| `StopFailure`  | Turn ended due to an API/runtime error  | 🟣 purple ×2      |

A flash is: on in the signal color → 500 ms → off → 300 ms → repeat once →
restore. The bulb is lit with a *color* command rather than a power command —
on a Govee bulb that applies power and color together, so it comes up already
showing the signal color. Turning power on first would light it in whatever
color it held before, and calls are throttled ~300 ms apart, so that stale
color would be visible for a beat. Restore is **capture-then-restore**, not a
queue: the bulb's power, color, and brightness are read before the flash and
written back after, so a signal never leaves the room in the wrong state. If
the bulb was off it goes back off — and back to remembering the color and
brightness it had, at the cost of one brief blip of light (see below).

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

   `python3 signals.py stop -v` does a single flash with logging on stderr.
   `python3 signals.py --list` prints every known signal and color.

5. **Wire the hooks.** They are already registered in `~/.claude/settings.json`
   under the `Notification`, `Stop`, and `StopFailure` events. Run `/hooks` in
   Claude Code to review, edit, or disable them. If you move this folder, update
   the paths there.

## How it fits together

Each client uses the one mechanism that actually suits it:

| Client | Mechanism | Why |
| --- | --- | --- |
| **Claude Code** (terminal, Desktop app, IDE) | **Hooks only** | A hook is *guaranteed* to fire. A tool call depends on the model choosing to make one. |
| **Claude Desktop chat** | **MCP tools only** | Desktop has no hook mechanism, so tools are the only option. |

Claude Code has **no MCP registration** for this server — `claude mcp list`
shows nothing. Desktop has **no hooks**, because it cannot. Neither client runs
both, so the two mechanisms never double-flash each other.

```
hooks/on_*.sh            Claude Code — fixed lifecycle moments, guaranteed
mcp_server.py            Claude Desktop chat — tool calls, model's judgment
   │
   └─ signals.py         flash_signal(name) / flash_color(rgb, times)
        │                    capture → flash → restore
        ├─ config.py         colors, timing, signal definitions, .env loading
        └─ govee_client.py   get_state / set_power / set_color / set_brightness
```

### Why hooks for Claude Code

Hooks fire mechanically: `Stop` on every turn end, `Notification` on a
permission prompt, `StopFailure` when a turn dies. Nothing depends on the model
noticing it should signal. `StopFailure` in particular *cannot* be done with a
tool — when a turn dies from an API error the model is no longer running and
cannot call anything.

The MCP path for Claude Code was tried and reverted. If you want it back:

```bash
claude mcp add --transport stdio govee-signals --scope user -- \
  python3 /Users/sandyshiff/Desktop/govee-signals/mcp_server.py
```

The `code` profile is kept correct for exactly that case — its
`notify_task_complete` tells Claude *not* to fire at turn end, since the `Stop`
hook already covers it. Running both without that guard double-flashes.

To disable the hooks again, `hooks/disabled-hooks.json` holds the exact config
and `tools/restore_hooks.py` puts it back.

### The MCP server

`mcp_server.py` speaks MCP over **stdio** — it is launched as a subprocess and
nothing listens on a network socket. It exposes four tools:

| Tool | Colour | When Claude should call it |
| ---- | ------ | -------------------------- |
| `notify_decision_needed()` | 🔵 blue | About to ask you something and wait |
| `notify_task_complete()`   | 🟢 green | A milestone landed mid-task (Code) / response finished (Desktop) |
| `notify_error()`           | 🟣 purple | A real blocker needing a human |
| `flash_custom(color, times)` | any | Escape hatch: named colour or hex |

The colours come from `config.SIGNALS`, so changing a signal's colour changes
it for the hook and the tool at once.

### Profiles: `code` vs `desktop`

| | `--profile desktop` (in use) | `--profile code` (default, unused) |
| --- | --- | --- |
| Client | Claude Desktop chat | Claude Code, if ever re-registered |
| Flashes per tool call | **1** | **2** |
| `notify_task_complete` says | *do* signal when you finish — nothing else will | *don't* signal at turn end — the `Stop` hook covers it |

One flash means Desktop; two means a Claude Code hook. Same colours either way,
so the count is the only thing to learn.

The profile is set per registration, so each client gets its own — Claude Code
via `claude mcp add` (no flag, defaults to `code`), Desktop via `args` in
`claude_desktop_config.json`.

## Overlapping flashes

`capture → flash → restore` takes ~6 s and there is no locking, so a signal
that starts while another is mid-flash captures the *first flash* as the
"original" state and restores the bulb to it — leaving the light stuck on in a
signal colour.

Splitting the mechanisms cut most of the exposure: Claude Code fires hooks and
never tools, Desktop fires tools and never hooks, so the two cannot collide
over the same event. What remains is two *concurrent Claude Code sessions* —
a terminal one and one inside the Desktop app — whose `Stop` hooks can land
within the same ~6 s window. If that becomes a nuisance, an `fcntl.flock`
around `flash_color()` fixes it.

> **Claude Code inside the Desktop app is still Claude Code.** It reads
> `~/.claude/settings.json`, so the hooks fire normally and you get the usual
> double flashes. The `desktop` profile is only for plain Desktop *chat*
> conversations, which are a different thing running in the same window.

Tool descriptions are the only thing steering when Claude calls these, so edit
the `*_DESC` strings in `mcp_server.py` if it over- or under-calls.

**Registered with Claude Code** at user scope, so it is available in every
project:

```bash
claude mcp add --transport stdio govee-signals --scope user -- \
  python3 /Users/sandyshiff/Desktop/govee-signals/mcp_server.py
claude mcp list      # govee-signals: ... - ✔ Connected
```

Which profile a server came up in is recorded in the log on every start:

```
INFO mcp: govee-signals MCP server starting (profile=desktop, device H6008 / ...)
```

(The parser uses `add_help=False` so an unrecognised flag can never crash a
client's server launch — which also means `--help` is silently ignored rather
than printing usage.)

`/mcp` inside a session lists the tools. **Registered with Claude Desktop** via
`~/Library/Application Support/Claude/claude_desktop_config.json`, which points
at an absolute interpreter path because Desktop does not inherit your shell's
`PATH`. Restart Desktop after changing it.

> **Why `signals.py` and not `signal.py`:** the module used to be `signal.py`,
> which shadows Python's stdlib `signal` for anything launched from this
> directory. `anyio` — which the MCP SDK depends on — does
> `from signal import Signals`, so the SDK could not import at all. Renaming
> fixed it. Do not name a module in here after a stdlib module.

`config.py` loads `.env` explicitly from the project directory, so the hooks
work regardless of what environment Claude Code launches them in — nothing
depends on your shell having already exported the keys.

The hook scripts launch `signals.py` detached with `nohup` and exit `0`
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

`signals.py` deliberately keeps the *what* (a signal's color and count, in
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

One flash costs 8-9 calls: 1 state read, 5 to run the two cycles, and 2-3 to
restore.

## The blip, and `RESTORE_COLOR_WHEN_OFF`

A Govee bulb remembers its color and brightness across a power cycle, and the
only way to write them is with the bulb lit. So a signal fired while the bulb
is **off** ends with one brief blip in the original color before it switches
back off — that blip is what stops the bulb from remembering the *signal*
color and coming up blue (or red, or yellow) the next time you switch it on
from the Govee app.

That is the default, and it makes the off-case restore lossless: power, color,
and brightness all come back exactly as found. Set `RESTORE_COLOR_WHEN_OFF =
False` in `config.py` to drop the blip and accept the remembered signal color
instead.

The blip is kept as short as possible: brightness is handed back during the
*last lit cycle of the flash itself* rather than during the restore, so the
restore only needs one lit call (~0.7 s) instead of two (~2.3 s, long enough to
read as a third flash). The cost is a barely-visible dim at the tail of the
final flash.

**The blip shows your bulb's resting color**, so the signal colors deliberately
avoid it. This bulb rests on red, which is why red is not used by any signal —
otherwise a successful task would read green, green, red and look like
success-then-error. If you change the resting color in the Govee app, check it
against the table above.

## Which notifications flash

Claude Code fires a `Notification` for several things, and the hook's `matcher`
is regex-matched against the event's `notification_type`. Ours is:

```
permission_prompt|worker_permission_prompt|agent_needs_input
```

so the bulb only flashes blue when Claude genuinely wants something. The one
that matters most to exclude is `idle_prompt` — Claude Code fires it 60 s after
*every* turn ends, so without the matcher you get a yellow flash a minute after
every completed task with nothing pending. Other types you could add:
`agent_completed`, `elicitation_response`, `auth_success`, `computer_use_enter`,
`computer_use_exit`, `push_notification`, `quota_auto_resume_fired`.

## Files

| Path                | Purpose                                              |
| ------------------- | ---------------------------------------------------- |
| `.env`              | Real credentials. **Gitignored — never commit.**     |
| `.env.example`      | Template with placeholders. Safe to commit.          |
| `config.py`         | Colors, timing, signal definitions, `.env` loading.  |
| `govee_client.py`   | Govee API wrapper: throttling, retries, state parse. |
| `signals.py`        | `flash_signal()` / `flash_color()` + CLI.            |
| `mcp_server.py`     | MCP server exposing the light as tools.              |
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
