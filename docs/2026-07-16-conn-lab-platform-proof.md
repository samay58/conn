# Conn Lab platform proof

Recorded 2026-07-16. This is the L0 gate for the disposable macOS lab.

## Frozen starting state

- Branch: `main`
- Commit: `75e138c4c70ea2f3e658875faeddb4c81d2fb0eb`
- Working tree at entry: 57 modified paths and 25 untracked paths
- Entry dirty diff SHA-256:
  `04d51c39df3997e2f253c89721194c505a86b63618bb5fb67cf053ee65d59daf`
- Host: macOS 27.0 beta, build `26A5378n`
- Installed host Conn binary SHA-256:
  `521481887bb9ebe5988923df93ccbd5a5332724a15f97c7dc1b305b1eec6cc9f`
- No host Conn process or listener on port 8787 or 18787 was present.

The Python baseline passed 644 tests with three intentional deselections and
two dependency warnings. The suite took 5.01 seconds. A second run passed the
same 644 tests in 4.56 seconds. Before and after the second run, the real
`data/` tree held 1,467 files, 6,264,653 bytes, with manifest SHA-256
`16c126682c228d5d8a53ae78e60745cd224734d77bce3257b35019f83ad360fe`.
The suite created no real data artifact.

The harness eval passed 14 of 14. Its artifact is
`data/evals/2026-07-15/results-1784173459.json`. The Swift baseline passed 205
tests with no failures in 12.205 seconds. The release build completed and was
signed with `Conn Dev Signing`.

## Pinned guest

- Tart: 2.32.1
- Base image:
  `ghcr.io/cirruslabs/macos-tahoe-base@sha256:a8e1c8305758643f513fdccdd829c2243687c60791083dea42f73f0b7aeb435c`
- Guest: macOS 26.5, build `25F71`
- Guest shape: 4 CPUs, 12,288 MB memory, 80 GB disk, 1,440 by 900 point display
- Golden VM: `conn-lab-golden`
- Golden Conn binary SHA-256:
  `94fc5d54a21721bee4aa843e14f96d3b00812f5beaff11c8447fd2668f2e18c2`

The guest booted without graphics, accepted commands through the Tart guest
agent, launched an Aqua application, reached the internet, refused a write to
the repository mount, and accepted a write to the dedicated artifact mount.
Audio and clipboard sharing were disabled.

Softnet 0.19.0 is installed but not activated. L0 and every successful L1
through L8 run used Tart's default NAT. Softnet needs root SUID or passwordless
sudo, so it is optional and disabled by default. It is not a release gate.

## Capability evidence

| Capability | Result | Evidence |
|---|---|---|
| LaunchServices app launch | Passed | Raw executable launch could not use the TCC grant. LaunchServices launch did. The runner must preserve this path. |
| Signed app bridge | Passed | The rebuilt app attached to the authenticated Python bridge in the guest. |
| Accessibility observation and dispatch | Passed | The fixture probe selected `fixture.no_effect`, dispatched one `AXPress`, and returned `no_effect` in 713 ms. The independent truth log contained only `fixture_ready`, so it did not false verify. |
| ScreenCaptureKit | Passed | A headless clone captured Calculator at 460 by 816 pixels. The JPEG was 55,400 bytes with SHA-256 `9b87223349a3aa9b093afc787484e6f9a2b2d659b51216e98837f386c480dc8e`. |
| Capture privacy | Passed | Conn surfaces were excluded. The stored probe contains dimensions and hashes, not the data URL or JPEG bytes. |
| TCC persistence | Passed | Accessibility and Screen Recording remained authorized after replacing Conn.app with a newly rebuilt binary carrying the same signing identity. No second click was needed. |
| Clone reset | Passed | A marker written in the first disposable clone was absent from the second clone created from the golden image. |
| Headless use after bootstrap | Passed | The second disposable clone retained both TCC grants and completed ScreenCaptureKit capture without a graphical VM window. |
| Pointer and keyboard transport | Partly passed | The one-time graphical bootstrap accepted pointer and keyboard input. The real action probe exercised production Accessibility dispatch. Headless production coordinate and key dispatch remain an L3 vertical-loop gate. |

The fixture window contains a secure field. Visual observation correctly
refused that window as `secure_surface`. Calculator provided the non-secure
capture proof.

## Host isolation

The repository was mounted read-only. Only `data/lab-runs/l0-probe/` was
mounted read-write. The guest could not change the host clipboard. No host
Conn process or listener on port 8787 or 18787 appeared after L0.

The one-time TCC setup used a graphical VM and therefore involved deliberate
human pointer and keyboard input. It is not evidence that an automated run
leaves host focus and pointer position unchanged. L7 must measure those values
around a headless suite.

## L0 conclusion

The platform can run the production Accessibility, ScreenCaptureKit, signed
bridge, and verified-action paths inside a disposable headless macOS guest.
The next packet may build orchestration around this measured path. Live
headless coordinate and keyboard dispatch through Conn remained the next
platform gate at L0.
