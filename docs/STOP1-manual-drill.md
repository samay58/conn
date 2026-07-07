# STOP 1 manual drill (deferred Phase 0 reliability gate)

Only Samay can run this: hands on the real hotkey and live API. Fill the RESULT
lines and this gate closes. Everything else in Phases 0/1 is already green.

## Setup

```bash
cd /Users/samaydhawan/phoenix/01-active/projects/conn
export OPENAI_API_KEY=...        # daemon-side only; never in config or logs
```

Two surfaces. Drills 1-4 use the daemon + console. Drills 5-6 use the app.

## Surface A: daemon + console (drills 1-4)

```bash
PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m conn
# browser: http://127.0.0.1:8787 ; hold Space to talk
```

### Drill 1: five real commands

Hold Space, speak, release. Five times. Suggested: "what app am I in", "find the
transformer paper note in my vault and open it", "switch to Chrome", "search my
vault for morocco", "copy this to the clipboard".

- WATCH: pill walks listening to thinking to acting to speaking to done; trace +
  cost line update; footer receipt grows.
- PASS IF: all five complete, every tool result is real (no claim before the
  chip/result), session cost stays under ~$0.25.
- RESULT: __________  (cost $____; anything that lied about completing?)

### Drill 2: wifi-kill mid-turn

Start a command, and while it is thinking/speaking, toggle wifi OFF.

- WATCH: console pill.
- PASS IF: pill shows Reconnecting (failed) within ~1 second, not a silent hang.
- RESULT: __________  (seconds to Reconnecting: ____)

### Drill 3: PTT during thinking  [PARTIAL TODAY]

Start a command; while it is thinking, tap Space again.

- KNOWN GAP: the visible refusal pulse is an island behavior that ships Phase 2
  (I6). Today `reject_input` only fires over the WebSocket; it is NOT in the
  trace and the console does not render it.
- HOW TO CONFIRM TODAY: browser devtools, Network, WS, click the socket, Messages
  tab; tapping during thinking should push a frame `{"type":"reject_input",
  "reason":"thinking"}`. That proves the daemon rejected it correctly.
- PASS IF: the reject_input frame appears (and the turn is NOT interrupted).
- RESULT: __________  (frame seen? y/n)

### Drill 4: latency report

After the session, read the newest trace.

```bash
ls -t data/traces/2026-07-06/*.jsonl | head -1
PYTHONPATH=src /Users/samaydhawan/phoenix/.venv/bin/python -m conn --latency-report data/traces/2026-07-06/<newest>.jsonl
```

- WATCH: six spans print with budget pass/fail.
- EXPECT: all six fill (client acks shipped in I4 for the console). If
  keydown_to_listening_ms or proposal_to_chip_ms is `n/a`, the client did not
  stamp ui_ack; note it.
- PASS IF: the four daemon spans (release-to-token, release-to-tool,
  stop-to-silence, and one ack span) are real numbers, none absurd.
- RESULT: paste the six lines here:
  ```
  __________
  ```

Kill the manual daemon before Surface B:
```bash
kill $(lsof -ti :8787)
```

## Surface B: the app (drills 5-6)

```bash
cd macos && ./make-app.sh && open Conn.app
# hold Right Option to talk (needs Input Monitoring + Accessibility on Conn.app)
```

### Drill 5: zombie adoption

Wedge the app-launched daemon, then relaunch the app.

```bash
kill -STOP $(lsof -ti :8787)     # suspend, do not kill
curl -s 127.0.0.1:8787/healthz   # note session/phase before (may hang if suspended; ctrl-C)
# quit Conn.app, reopen it
curl -s 127.0.0.1:8787/healthz   # note session/phase after
```

- PASS IF: after relaunch, healthz answers with a fresh session (the app
  terminated the wedged daemon and spawned a new one), not the suspended one.
- RESULT: __________  (before phase_age_s: ____; after: fresh? y/n)

### Drill 6: daemon log file

After the app launches its daemon:

```bash
ls -la data/logs/daemon-2026-07-06.log
```

- PASS IF: today's log file exists and has content (the wedge tracebacks of Jul 5
  would now be captured here).
- RESULT: __________

### Bonus (island shell, Phase 1): typing continuity

While the island shell is showing over the notch (key-down), type in another app.

- PASS IF: zero keystrokes lost; the island never steals focus.
- RESULT: __________

## Verdict

- STOP 1 closes when drills 1, 2, 4, 5, 6 pass and drill 3's WS frame is
  confirmed. Any FAIL becomes a defect packet before the project closes.
- OVERALL: __________
