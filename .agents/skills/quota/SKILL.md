---
name: quota
description: Check AI subscription quota/usage across Claude (Max), Gemini (Antigravity/agy), and ChatGPT (Codex) — weekly and 5-hour windows, reset times, and pace vs. a linear burn. Use when the user asks how much quota/usage/limit is left, when a limit resets, whether they're burning too fast, which provider has headroom for a big job, or why the quota dashboard/timer isn't updating.
---

# AI subscription quota

Tool: `~/git/personal-utils/quota/quota.py` (stdlib-only Python, no deps).
A systemd user timer (`quota-collect.timer`) refreshes it every 15 minutes
into `~/git/personal-utils/quota/data/latest.json`, so reading the cache is
almost always enough.

If the script is missing on this machine, say so — `personal-utils` isn't
cloned everywhere — rather than guessing numbers.

## Reading usage

```sh
Q=~/git/personal-utils/quota/quota.py
python3 $Q show --cached          # human report from cache, no network (instant)
python3 $Q show --cached --json   # same, machine-readable — prefer this for answering
python3 $Q                        # live poll if cache is older than 120s (~2-5s)
python3 $Q refresh                # force a live poll of all three providers
```

Start from `show --cached --json`. Check `collected_at`: if it's older than
~30 min the timer is probably not running (see Troubleshooting), so do a
`refresh` before answering.

## Interpreting the JSON

`providers.{gemini,claude,chatgpt}` each carry:

- `status` / `error` — `ok` or an error string; report errors verbatim.
- `weekly`, `session` (5-hour) — `used_percent`, `reset_at` (UTC ISO),
  `elapsed_percent` (how far through the window), `pace_delta_percent`
  (= used − elapsed; negative means under an even burn rate) and
  `pace_status` (`under` / `warm` > +5 / `hot` > +15 or ≥ 95% used).
- `extra_windows` — model-scoped limits (e.g. Claude "Weekly Scoped (Fable)",
  Gemini "Claude and GPT models").
- `details` — Claude 7-day per-surface breakdown and extra-usage state;
  ChatGPT free reset credits.

Convert reset times to the user's local time (America/Los_Angeles) when
reporting. Lead with the answer to their question (e.g. "Claude: 32% of the
week left, resets Mon 1 PM"), not the whole table.

`session: null` is normal, not a bug: the Claude usage API currently returns
`five_hour: null` on this plan, and Codex Pro reports only a weekly window.
Unused Gemini extra windows report a reset of "now + window length"; that
countdown is meaningless until the window is actually used.

## Troubleshooting

```sh
systemctl --user list-timers 'quota*'
journalctl --user -u quota-collect.service -n 40 --no-pager
~/git/personal-utils/quota/install-timer.sh            # (re)install the timer
~/git/personal-utils/quota/install-timer.sh --serve    # + web UI on 127.0.0.1:8070
```

- Claude: reads `~/.claude/.credentials.json`; a 401 triggers an automatic
  OAuth refresh. Persistent failures usually mean re-login in Claude Code.
- ChatGPT: tries the `codex` app server, then the wham HTTP API, then the
  local rollout logs. A plan label ending in `(cached rollout)` means the live
  paths failed and the numbers may be stale.
- Gemini: needs the `agy` binary on PATH (or a known install dir).

Optional config lives in `~/.config/quota-dash.env` or `~/.env`:
`QUOTA_PUSH_TARGET` (push snapshots to the VPS, e.g. `agent-host`) and
`QUOTA_DASH_PASSWORD` (required for a non-loopback web UI).
