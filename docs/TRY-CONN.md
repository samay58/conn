# Try Conn

Conn is a voice command bar for the Mac. Hold Control and Option, say what you want, and let go. It does small things on the computer, reads your day and your messages, and drafts replies. Anything that sends, closes or changes something waits for you to click Approve on the island at the top of the screen.

This page has two parts: using Conn on the Mac where it is already installed, and setting it up on a second Mac.

## Use it on this Mac

Conn is installed at /Applications/Conn.app and starts from the menu bar. The island at the top of the screen shows what it heard, what it is doing and what it said.

1. Hold Control and Option, speak, then let go.
2. Conn answers in one short sentence. Lists, threads and drafts show on a card under the island.
3. When a card or chip shows Deny and Approve, click one. Nothing waits on the keyboard, and nothing sends without a click.
4. Done means Conn saw the result. "Sent, not confirmed" means it went out but Conn could not check. "Did not run" means nothing happened.

Things to try:

1. "Who do I owe a reply?" shows a list of people waiting, most pressing first.
2. "What's on today?" and "What's on my calendar tomorrow?" show a card.
3. "Reply to Dana" shows a draft in your voice. Say "make it shorter" or "warmer" to change it.
4. "Send it" shows the whole message above Approve. Approve sends it through Messages, or WhatsApp if the draft was for WhatsApp, and Conn checks that it arrived.
5. "Remind me tomorrow at 9 to call the vet" and "Capture: book the dentist" each wait for Approve.
6. "What did we decide in my last meeting with Priya?" searches your meeting notes.
7. "Open Safari and go to techmeme.com", "Zoom out a few times", "Close the first two tabs".
8. "Run my Morning Routine shortcut" runs one of your Apple Shortcuts after you approve it.

What it costs: about 3 cents a command on average. Each session stops itself at $5. The island shows the running total, and `cd ~/conn && PYTHONPATH=src .venv/bin/python -m conn --cost-report` shows what each command cost.

Work stays out. Conn sends what it reads to OpenAI on your personal key, so results that mention your work domain are held back before the model sees them. Wispr stays switched off because its results cannot be filtered that way.

## Set it up on a second Mac

This takes about 20 minutes. You need macOS 14 or newer, Xcode or the Command Line Tools, and Python 3.12 or newer.

1. Get the code and build everything:
   ```
   git clone https://github.com/samay58/conn.git ~/conn
   ~/conn/bootstrap.sh
   ```
   It sets up Python, runs the tests and installs Conn.app. Rerun it after every `git pull`.
2. Make the signing identity once, so permissions survive rebuilds. Open Keychain Access, then Certificate Assistant, then Create a Certificate. Name it `Conn Dev Signing`, choose Self-Signed Root and Code Signing, and set validity to 3650 days. Then run `cd ~/conn/macos && ./make-app.sh install`. If Keychain asks about codesign, choose Always Allow.
3. Put your OpenAI key in place:
   ```
   mkdir -p ~/.config/openai
   pbpaste > ~/.config/openai/key   # with the key on the clipboard
   chmod 600 ~/.config/openai/key
   ```
4. Copy `~/conn/config.local.toml` from the first Mac to the same place on this one (AirDrop is fine). Git never carries it because it holds private paths and accounts. If your home folder or Phoenix folder has a different path here, fix the paths at the top of that file.
5. Make sure Phoenix is on this Mac at the path that file names, with its own `.venv` (Phoenix's setup makes it). Reminders read faster with one extra package: `~/phoenix/.venv/bin/pip install pyobjc-framework-EventKit`.
6. Sign in to the services, one browser page each:
   ```
   cd ~/conn
   PYTHONPATH=src .venv/bin/python -m conn --mcp-login granola
   PYTHONPATH=src .venv/bin/python -m conn --mcp-login superhuman
   ```
   Sign-ins live in this Mac's Keychain and never travel.
7. Open Conn.app and grant what macOS asks for, in System Settings, Privacy and Security:
   1. Microphone, for your voice.
   2. Accessibility, for the hotkey and for acting in apps.
   3. Full Disk Access, so Conn can read Messages and WhatsApp live.
   4. Screen Recording, only if you want Conn to act on things it can only see.
   5. Reminders and Calendars, when the first question about them asks.
8. Check it: `cd ~/conn && PYTHONPATH=src .venv/bin/python -m conn --doctor`. Then hold Control and Option and say "What app am I in?"

## When something is off

1. The island says Reconnecting: Conn restarts its background process by itself. If it stays, quit Conn from the menu bar and open it again.
2. A service "isn't connected right now": run its `--mcp-login` again.
3. Conn can't find a person: it matches names from your messages. Say the name the way it appears there.
4. Something looked wrong: every session leaves a record in `~/conn/data/traces/`. From `~/conn`, `PYTHONPATH=src .venv/bin/python -m conn --cost-report` and `--latency-report` read the newest one.
