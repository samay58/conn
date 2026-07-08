import AppKit
import SwiftUI

// `Conn --preview`: the canonical IslandView rendered against a fake AppState
// per state, for design iteration. No daemon, no interference with a live
// session. The cycler steps through all eleven reviewable states (nine phases
// plus toast and chip open); Replay and Collapse drive the same reveal tokens
// IslandController uses live. `Conn --preview --shoot <dir>` writes one PNG
// per state headlessly from an offscreen window, so appearance animations and
// the breath timeline settle before capture.

@MainActor
enum PreviewRunner {
    static func run() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)

        let args = CommandLine.arguments
        if let flag = args.firstIndex(of: "--shoot"), flag + 1 < args.count {
            shoot(to: args[flag + 1])
            exit(0)
        }

        let samples = PreviewSample.makeAll()
        startLevelTimer(samples: samples)

        let hosting = NSHostingView(rootView: IslandPreviewRoot(samples: samples))
        hosting.sizingOptions = [.preferredContentSize]

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1140, height: 690),
                              styleMask: [.titled, .closable],
                              backing: .buffered, defer: false)
        window.title = "Conn island preview"
        window.contentView = hosting
        window.appearance = NSAppearance(named: .aqua)
        if let screen = NSScreen.main {
            let f = screen.visibleFrame
            window.setFrameOrigin(NSPoint(x: f.maxX - 1200, y: f.minY + 40))
        }
        window.orderFrontRegardless()
        app.run()
    }

    // Synthesized mic/playback levels so the waveform moves in the cycler.
    private static func startLevelTimer(samples: [PreviewSample]) {
        var t = 0.0
        Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { _ in
            t += 1.0 / 30.0
            let syllable = max(0, sin(t * 6.2)) * (0.55 + 0.45 * sin(t * 1.7))
            let value = min(0.15 + syllable * 0.75, 1.0)
            Task { @MainActor in
                for sample in samples {
                    sample.state.level = sample.animatedLevel(from: value)
                }
            }
        }
    }

    // Renders each state in an offscreen window, lets the run loop settle so
    // onAppear fades and the breath timeline produce a real frame, then
    // captures a 2x bitmap.
    private static func shoot(to dir: String) {
        let dirURL = URL(fileURLWithPath: dir, isDirectory: true)
        try? FileManager.default.createDirectory(at: dirURL, withIntermediateDirectories: true)

        let samples = PreviewSample.makeAll()
        var written = 0
        for sample in samples {
            sample.state.level = sample.animatedLevel(from: 0.55)

            let size = NSSize(width: 500, height: 240)
            let hosting = NSHostingView(
                rootView: PreviewStage(sample: sample, crosshair: false))
            hosting.frame = NSRect(origin: .zero, size: size)

            let window = NSWindow(
                contentRect: NSRect(x: -3000, y: -3000, width: size.width, height: size.height),
                styleMask: [.borderless], backing: .buffered, defer: false)
            window.contentView = hosting
            window.orderFrontRegardless()
            RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.35))

            guard let rep = NSBitmapImageRep(
                bitmapDataPlanes: nil,
                pixelsWide: Int(size.width) * 2, pixelsHigh: Int(size.height) * 2,
                bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
                colorSpaceName: .calibratedRGB, bytesPerRow: 0, bitsPerPixel: 0)
            else {
                print("shoot: could not allocate bitmap for \(sample.id)")
                continue
            }
            rep.size = size
            hosting.cacheDisplay(in: hosting.bounds, to: rep)
            window.contentView = nil
            window.orderOut(nil)

            let fileURL = dirURL.appendingPathComponent("\(sample.id).png")
            guard let png = rep.representation(using: .png, properties: [:]),
                  (try? png.write(to: fileURL)) != nil else {
                print("shoot: could not write \(fileURL.path)")
                continue
            }
            written += 1
            print("wrote \(fileURL.path)")
        }
        print("\(written)/\(samples.count) states written")
    }
}

@MainActor
final class PreviewSample: Identifiable {
    let id: String
    let title: String
    let note: String
    let state: AppState
    let reveal = IslandReveal()
    let client: DaemonClient

    private init(id: String, title: String, note: String, state: AppState) {
        self.id = id
        self.title = title
        self.note = note
        self.state = state
        // Never connected: send() is a no-op without a socket, so the chip's
        // buttons and ui_ack are inert in the preview.
        self.client = DaemonClient(state: state)
    }

    func animatedLevel(from value: Double) -> Double {
        switch state.phase {
        case "listening": return value
        case "speaking": return value * 0.8
        case "thinking", "acting": return 0.18
        default: return 0
        }
    }

    static func makeAll() -> [PreviewSample] {
        [
            sample("idle", "Idle", "no island is visible") { _ in },
            sample("listening", "Listening", "accent ring, live mic level") {
                $0.connected = true
                $0.live = true
                $0.userLine = "find the transformer paper notes"
                $0.spentUSD = 0.012
            },
            sample("thinking", "Thinking", "quiet breath while the model works") {
                $0.connected = true
                $0.live = true
                $0.userLine = "send Alex the address"
                $0.spentUSD = 0.014
            },
            sample("acting", "Acting", "running tool name is visible") {
                $0.connected = true
                $0.live = true
                $0.chips = [Chip(id: "c0", name: "phoenix_search",
                                  preview: "Search Phoenix: transformer paper",
                                  status: "running")]
                $0.spentUSD = 0.021
            },
            sample("awaiting_approval", "Awaiting approval",
                   "approval treatment before the ledger lands (defensive render)") {
                $0.connected = true
                $0.live = true
                $0.spentUSD = 0.034
            },
            sample("speaking", "Speaking", "playback level in white") {
                $0.connected = true
                $0.live = true
                $0.modelLine = "Top hit is the welcome email from June 22."
                $0.spentUSD = 0.027
            },
            sample("done", "Done", "green settle before collapse") {
                $0.connected = true
                $0.live = true
                $0.modelLine = "Copied."
                $0.spentUSD = 0.031
            },
            sample("failed", "Failed", "reconnect is visible") {
                $0.connected = false
                $0.modelLine = "Trying a fresh session."
                $0.spentUSD = 0.031
            },
            sample("budget_hold", "Budget hold", "hard cap with one override target") {
                $0.connected = true
                $0.live = true
                $0.spentUSD = 1.000
            },
            sample("toast", "Toast", "daemon toast replaces the state line",
                   phase: "thinking") {
                $0.connected = true
                $0.live = true
                $0.toast = "Receipt saved"
                $0.modelLine = "Still thinking."
                $0.spentUSD = 0.044
            },
            sample("chip", "Chip open", "live Deny and Approve inside the island",
                   phase: "awaiting_approval") {
                $0.connected = true
                $0.live = true
                $0.modelLine = "I can copy that to your clipboard."
                $0.chips = [Chip(id: "c1", name: "clipboard_set",
                                  preview: "Copy to clipboard",
                                  status: "proposed")]
                $0.spentUSD = 0.034
            },
        ]
    }

    private static func sample(
        _ id: String,
        _ title: String,
        _ note: String,
        phase: String? = nil,
        configure: (AppState) -> Void
    ) -> PreviewSample {
        let state = AppState()
        state.phase = phase ?? id
        configure(state)
        return PreviewSample(id: id, title: title, note: note, state: state)
    }
}

// One state rendered on the stage backdrop: the canonical IslandView at its
// live proportions, or the idle placeholder. The crosshair marks the stage
// center for the optical-alignment check (the waveform must center on it).
@MainActor
struct PreviewStage: View {
    let sample: PreviewSample
    var crosshair: Bool

    private static let notchInset: CGFloat = 30

    private var chipOpen: Bool {
        sample.state.phase == "awaiting_approval" && sample.state.pendingChip != nil
    }

    var body: some View {
        ZStack(alignment: .top) {
            PreviewBackdropColor()
            if sample.state.phase == "idle" {
                IdlePreview()
                    .frame(maxHeight: .infinity)
            } else {
                IslandView(
                    state: sample.state,
                    client: sample.client,
                    topInset: Self.notchInset,
                    reveal: sample.reveal)
                .frame(width: 316,
                       height: Self.notchInset + DesignTokens.islandContentHeight
                           + (chipOpen ? DesignTokens.chipRowHeight : 0))
            }
            if crosshair {
                CrosshairOverlay()
            }
        }
        .frame(width: 500, height: 240)
        .clipped()
    }
}

private struct CrosshairOverlay: View {
    var body: some View {
        GeometryReader { proxy in
            let center = CGPoint(x: proxy.size.width / 2, y: proxy.size.height / 2)
            Path { p in
                p.move(to: CGPoint(x: center.x, y: 0))
                p.addLine(to: CGPoint(x: center.x, y: proxy.size.height))
                p.move(to: CGPoint(x: 0, y: center.y))
                p.addLine(to: CGPoint(x: proxy.size.width, y: center.y))
            }
            .stroke(Color(red: 0.85, green: 0.25, blue: 0.25).opacity(0.6), lineWidth: 1)
        }
        .allowsHitTesting(false)
    }
}

@MainActor
private struct IslandPreviewRoot: View {
    let samples: [PreviewSample]
    @State private var index = 1
    @State private var crosshair = false
    // Observing the token store re-renders the staged island on every
    // inspector edit, so palette and personality changes land live.
    @ObservedObject private var tokens = DesignTokens.current

    private var selected: PreviewSample { samples[index] }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            HStack(alignment: .top, spacing: 24) {
                mainStage
                stateList
                InspectorView(
                    tokens: tokens,
                    replay: { selected.reveal.token &+= 1 },
                    collapse: { selected.reveal.collapseToken &+= 1 })
            }
        }
        .padding(28)
        .background(PreviewBackdropColor())
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Conn island preview")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
                Text("The canonical IslandView against a fake state per phase. Replay drives the live reveal tokens.")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
            }
            Spacer()
            controls
        }
    }

    private var controls: some View {
        HStack(spacing: 8) {
            Toggle("Crosshair", isOn: $crosshair)
                .toggleStyle(.checkbox)
            Button("Previous") { move(-1) }
            Button("Replay") { selected.reveal.token &+= 1 }
            Button("Collapse") { selected.reveal.collapseToken &+= 1 }
            Button("Next") { move(1) }
        }
        .buttonStyle(.bordered)
    }

    private var mainStage: some View {
        VStack(alignment: .leading, spacing: 14) {
            ZStack(alignment: .top) {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .fill(Color.white.opacity(0.70))
                    .overlay(
                        RoundedRectangle(cornerRadius: 10, style: .continuous)
                            .strokeBorder(Color.black.opacity(0.06), lineWidth: 1)
                    )
                PreviewStage(sample: selected, crosshair: crosshair)
                    .padding(.top, 10)
                    .id(selected.id)
            }
            .frame(width: 520, height: 300)

            VStack(alignment: .leading, spacing: 4) {
                Text(selected.title)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
                Text(selected.note)
                    .font(.system(size: 13))
                    .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
            }
        }
    }

    private var stateList: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(samples.indices, id: \.self) { sampleIndex in
                let sample = samples[sampleIndex]
                Button {
                    index = sampleIndex
                } label: {
                    HStack(spacing: 10) {
                        PreviewDot(state: sample.state)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(sample.title)
                                .font(.system(size: 12.5, weight: .medium))
                            Text(sample.state.stateLabel)
                                .font(.system(size: 11))
                                .foregroundStyle(Color(red: 0.46, green: 0.43, blue: 0.38))
                        }
                        Spacer()
                    }
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(sampleIndex == index ? Color.black.opacity(0.08) : Color.white.opacity(0.38))
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .frame(width: 230)
    }

    private func move(_ delta: Int) {
        index = (index + delta + samples.count) % samples.count
    }
}

private struct IdlePreview: View {
    var body: some View {
        VStack(spacing: 10) {
            Capsule(style: .continuous)
                .fill(Color.black.opacity(0.88))
                .frame(width: 172, height: 28)
            Text("Idle means no Conn window.")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color.black.opacity(0.50))
        }
        .frame(width: 390, height: 132)
    }
}

private struct PreviewDot: View {
    @ObservedObject var state: AppState

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 8, height: 8)
    }

    private var color: Color {
        switch state.phase {
        case "idle": return Color.black.opacity(0.30)
        case "listening": return DesignTokens.islandAccent
        case "awaiting_approval": return DesignTokens.islandAmber
        case "done": return DesignTokens.islandGreen
        case "failed": return DesignTokens.islandRed
        case "budget_hold": return DesignTokens.islandGold
        default: return DesignTokens.islandTextSecondary
        }
    }
}

private struct PreviewBackdropColor: View {
    var body: some View {
        Color(red: 0.96, green: 0.95, blue: 0.92)
    }
}
