import AppKit
import SwiftUI

// `Conn --preview`: the canonical IslandView rendered against a fake AppState
// per state, for design iteration. No daemon, no interference with a live
// session. The cycler steps through every reviewable state (nine phases plus
// toast, chips, and the card states); Replay and Collapse drive the same
// reveal tokens IslandController uses live. The style picker flips every
// sample between classic and the prototype directions (IslandGlassStyles
// .swift), and Morph keeps one island on stage so stepping through states
// shows the transitions between them. `Conn --preview --shoot <dir>` writes
// <style>-<state>.png for every style and state headlessly, plus
// floating-<state>.png: the non-notch fallback panel's Character pill.

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
        let mirror = PreviewSample.mirror()
        startLevelTimer(samples: samples + [mirror])

        let hosting = NSHostingView(rootView: IslandPreviewRoot(samples: samples, mirror: mirror))
        hosting.sizingOptions = [.preferredContentSize]

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1240, height: 760),
                              styleMask: [.titled, .closable],
                              backing: .buffered, defer: false)
        window.title = "Conn island preview"
        window.contentView = hosting
        window.appearance = NSAppearance(named: .aqua)
        if let screen = NSScreen.main {
            let f = screen.visibleFrame
            window.setFrameOrigin(NSPoint(x: f.maxX - 1300, y: f.minY + 40))
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

    // Renders every style and state. Each state is first hosted in an
    // offscreen window so onAppear fades and the timelines run, and so the
    // glass renderer is warm; the PNG itself comes from ImageRenderer, because
    // cacheDisplay drops Liquid Glass (it draws only the plain layer tree).
    private static func shoot(to dir: String) {
        let dirURL = URL(fileURLWithPath: dir, isDirectory: true)
        try? FileManager.default.createDirectory(at: dirURL, withIntermediateDirectories: true)

        let samples = PreviewSample.makeAll()
        let restore = DesignTokens.current.islandStyle
        // A still frame cannot wait out the capsule's show delay, so the
        // shooter renders the capsule as it looks once the delay has passed.
        let restoreDelay = DesignTokens.current.toolCapsuleShowDelay
        DesignTokens.current.toolCapsuleShowDelay = 0
        defer {
            DesignTokens.current.islandStyle = restore
            DesignTokens.current.toolCapsuleShowDelay = restoreDelay
        }
        var written = 0
        // nil is the floating pass: the fallback panel's pill, style D.
        let passes: [IslandStyle?] = IslandStyle.allCases.map { $0 } + [nil]
        for pass in passes {
            DesignTokens.current.islandStyle = pass ?? .d
            for sample in samples {
                sample.state.level = sample.animatedLevel(from: 0.55)
                let stage = PreviewStage(sample: sample, crosshair: false, floating: pass == nil)

                let size = PreviewStage.size
                let hosting = NSHostingView(rootView: stage)
                hosting.frame = NSRect(origin: .zero, size: size)
                let window = NSWindow(
                    contentRect: NSRect(x: -3000, y: -3000, width: size.width, height: size.height),
                    styleMask: [.borderless], backing: .buffered, defer: false)
                window.contentView = hosting
                window.orderFrontRegardless()
                RunLoop.main.run(until: Date(timeIntervalSinceNow: 0.35))

                let renderer = ImageRenderer(content: stage.environment(\.colorScheme, .light))
                renderer.scale = 2
                let image = renderer.cgImage
                window.contentView = nil
                window.orderOut(nil)

                let fileURL = dirURL.appendingPathComponent("\(pass?.rawValue ?? "floating")-\(sample.id).png")
                guard let image,
                      let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]),
                      (try? png.write(to: fileURL)) != nil else {
                    print("shoot: could not write \(fileURL.path)")
                    continue
                }
                written += 1
                print("wrote \(fileURL.path)")
            }
        }
        print("\(written)/\(samples.count * passes.count) states written")
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

    private init(id: String, title: String, note: String, state: AppState, card: IslandCard?) {
        self.id = id
        self.title = title
        self.note = note
        self.state = state
        // Sample cards hold still: no retire timer in the preview.
        if let card { state.setCard(card, retires: false) }
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

    // The morph stage's single island: the selected sample's state is copied
    // into it inside an animation, so the island transitions instead of
    // being replaced.
    static func mirror() -> PreviewSample {
        sample("mirror", "Morph", "one island stepping through states", phase: "listening") { _ in }
    }

    func adopt(_ other: PreviewSample) {
        let o = other.state
        state.phase = o.phase
        state.connected = o.connected
        state.live = o.live
        state.userLine = o.userLine
        state.modelLine = o.modelLine
        state.chips = o.chips
        state.spentUSD = o.spentUSD
        state.toast = o.toast
        state.lastActionOutcome = o.lastActionOutcome
        state.axWarning = o.axWarning
        if let card = o.card {
            state.setCard(card, retires: false)
        } else {
            state.clearCard()
        }
    }

    // The card samples use the daemon's exact wire shapes (src/conn/cards.py).
    private static let draftText = "Hey Alex, the address is 418 Hayes Street, apartment 3B. "
        + "The buzzer is broken, so text me when you're outside and I'll come down."

    private static func reply(_ state: String, title: String) -> IslandCard? {
        IslandCard(wire: [
            "id": "reply:alex", "kind": "reply", "title": title,
            "subtitle": "Alex · Messages", "body": draftText, "state": state,
            "persist": state == "draft" || state == "approve",
        ])
    }

    private static let owedList = IslandCard(wire: [
        "id": "list:people", "kind": "list", "title": "You owe replies",
        "subtitle": "3 people",
        "rows": [
            ["title": "Dana", "detail": "Email · 2d",
             "note": "Can you confirm Thursday's review time?"],
            ["title": "Priya", "detail": "Messages · 5h",
             "note": "Still in for dinner on Saturday?"],
            ["title": "Sam", "detail": "WhatsApp · 1d",
             "note": "Needs your sign-off on the launch notes"],
        ],
        "persist": false,
    ])

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
            sample("acting_connector", "Acting (connector)",
                   "a connector read shows its preview, not its tool name",
                   phase: "acting") {
                $0.connected = true
                $0.live = true
                $0.chips = [Chip(id: "c2", name: "phoenix_today",
                                  preview: "Checking today",
                                  status: "running")]
                $0.spentUSD = 0.018
            },
            sample("chip_capture", "Chip (longest preview)",
                   "a preview at the daemon's full budget",
                   phase: "awaiting_approval") {
                $0.connected = true
                $0.live = true
                $0.chips = [Chip(id: "c4", name: "phoenix_capture",
                                  preview: "Capture: ask Dana about the Acme deck…",
                                  status: "proposed")]
                $0.spentUSD = 0.029
            },
            sample("chip_connector", "Chip (connector write)",
                   "the longest common write preview at the daemon's budget",
                   phase: "awaiting_approval") {
                $0.connected = true
                $0.live = true
                $0.modelLine = "I'll remind you tomorrow at 9."
                $0.chips = [Chip(id: "c3", name: "phoenix_remind",
                                  preview: "Remind tomorrow 9 AM: Call the vet",
                                  status: "proposed")]
                $0.spentUSD = 0.029
            },
            sample("reply_draft", "Card: reply draft",
                   "a persisting draft card with a close button",
                   phase: "speaking", card: reply("draft", title: "Draft")) {
                $0.connected = true
                $0.live = true
                $0.modelLine = "Here's a draft for Alex."
                $0.spentUSD = 0.041
            },
            sample("reply_approve", "Card: reply to send",
                   "the full body above the existing Deny and Approve chip",
                   phase: "awaiting_approval", card: reply("approve", title: "Send this?")) {
                $0.connected = true
                $0.live = true
                $0.chips = [Chip(id: "c5", name: "messages_send",
                                  preview: "Text Alex: the address and buzzer",
                                  status: "proposed")]
                $0.spentUSD = 0.043
            },
            sample("reply_sent", "Card: reply sent",
                   "a settled reply, fading after the short linger",
                   phase: "done", card: reply("sent", title: "Sent")) {
                $0.connected = true
                $0.live = true
                $0.modelLine = "Sent."
                $0.lastActionOutcome = "verified"
                $0.spentUSD = 0.046
            },
            sample("list", "Card: replies owed",
                   "a list card that retires on the next push-to-talk",
                   phase: "speaking", card: owedList) {
                $0.connected = true
                $0.live = true
                $0.modelLine = "Three people are waiting on you."
                $0.spentUSD = 0.038
            },
        ]
    }

    private static func sample(
        _ id: String,
        _ title: String,
        _ note: String,
        phase: String? = nil,
        card: IslandCard? = nil,
        configure: (AppState) -> Void
    ) -> PreviewSample {
        let state = AppState()
        state.phase = phase ?? id
        configure(state)
        return PreviewSample(id: id, title: title, note: note, state: state, card: card)
    }
}

// One state rendered on a stand-in desktop: wallpaper, a window, the menu
// bar, and the notch, so glass has something real to refract and every
// direction is judged against the same scene. Classic keeps its live width;
// every style sizes its own height inside the stage.
@MainActor
struct PreviewStage: View {
    let sample: PreviewSample
    var crosshair: Bool
    // The non-notch fallback: the pill floats under the menu bar.
    var floating = false

    static let size = NSSize(width: 560, height: 360)
    private static let notchInset: CGFloat = 30
    private static let notchWidth: CGFloat = 200

    var body: some View {
        ZStack(alignment: .top) {
            PreviewDesktop(notchWidth: floating ? 0 : Self.notchWidth, notchHeight: Self.notchInset)
            if sample.state.phase == "idle" {
                Text("Idle means no Conn window.")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color.white.opacity(0.9))
                    .frame(maxHeight: .infinity, alignment: .bottom)
                    .padding(.bottom, 18)
            } else if floating {
                IslandView(
                    state: sample.state,
                    client: sample.client,
                    topInset: 0,
                    reveal: sample.reveal,
                    notchWidth: Self.notchWidth,
                    floating: true)
                    .padding(.top, Self.notchInset + DesignTokens.characterFloatingTopGap)
            } else if DesignTokens.islandStyle == .classic {
                island
                    .frame(width: Self.notchWidth + 2 * DesignTokens.islandGrowWidth)
            } else {
                island
            }
            if crosshair {
                CrosshairOverlay()
            }
        }
        .frame(width: Self.size.width, height: Self.size.height)
        .clipped()
    }

    private var island: IslandView {
        IslandView(
            state: sample.state,
            client: sample.client,
            topInset: Self.notchInset,
            reveal: sample.reveal,
            notchWidth: Self.notchWidth)
    }
}

// A quiet stand-in desktop. The wallpaper is two muted tones so refraction
// and tint read without the backdrop competing; the window gives the glass
// hard edges and text to bend.
private struct PreviewDesktop: View {
    let notchWidth: CGFloat
    let notchHeight: CGFloat

    private static let lights = [Color(red: 1, green: 0.37, blue: 0.34),
                                 Color(red: 1, green: 0.74, blue: 0.18),
                                 Color(red: 0.16, green: 0.79, blue: 0.25)]

    var body: some View {
        ZStack(alignment: .top) {
            LinearGradient(
                colors: [Color(red: 0.78, green: 0.66, blue: 0.56),
                         Color(red: 0.42, green: 0.50, blue: 0.62)],
                startPoint: .topLeading, endPoint: .bottomTrailing)
            documentWindow
                .offset(x: 70, y: 58)
            menuBar
            UnevenRoundedRectangle(
                topLeadingRadius: 0, bottomLeadingRadius: 9,
                bottomTrailingRadius: 9, topTrailingRadius: 0, style: .continuous)
                .fill(Color.black)
                .frame(width: notchWidth, height: notchHeight)
        }
    }

    private var menuBar: some View {
        HStack(spacing: 16) {
            Image(systemName: "apple.logo")
            Text("Finder").fontWeight(.semibold)
            Text("File")
            Text("Edit")
            Spacer()
            Text("Thu Nov 12  9:41 AM").monospacedDigit()
        }
        .font(.system(size: 12, weight: .medium))
        .foregroundStyle(Color.black.opacity(0.82))
        .padding(.horizontal, 14)
        .frame(height: notchHeight)
        .background(Color.white.opacity(0.42))
    }

    private var documentWindow: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 7) {
                ForEach(0..<Self.lights.count, id: \.self) { i in
                    Circle().fill(Self.lights[i]).frame(width: 11, height: 11)
                }
                Spacer()
                Text("Launch notes")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color.black.opacity(0.7))
                Spacer()
            }
            .padding(.horizontal, 12)
            .frame(height: 30)
            VStack(alignment: .leading, spacing: 9) {
                Text("Launch notes, week of November 16")
                    .font(.system(size: 17, weight: .bold))
                Text("Ship the onboarding rewrite behind the flag on Tuesday. Pricing page copy needs one more pass before it goes live.")
                Text("Open questions: the migration window, who owns support macros, and whether the beta list gets the email first.")
                Text("Owners: rollout, notes, support.")
            }
            .font(.system(size: 13))
            .foregroundStyle(Color.black.opacity(0.78))
            .padding(.horizontal, 18)
            .padding(.top, 10)
            Spacer(minLength: 0)
        }
        .frame(width: 400, height: 320)
        .background(RoundedRectangle(cornerRadius: 12, style: .continuous).fill(Color.white))
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
    let mirror: PreviewSample
    @State private var index = 1
    @State private var crosshair = false
    @State private var morph = false
    // Observing the token store re-renders the staged island on every
    // inspector edit, so palette and personality changes land live.
    @ObservedObject private var tokens = DesignTokens.current

    private var selected: PreviewSample { samples[index] }
    private var staged: PreviewSample { morph ? mirror : selected }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            HStack(alignment: .top, spacing: 24) {
                mainStage
                stateList
                InspectorView(
                    tokens: tokens,
                    replay: { staged.reveal.token &+= 1 },
                    collapse: { staged.reveal.collapseToken &+= 1 })
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
        VStack(alignment: .trailing, spacing: 8) {
            Picker("Style", selection: $tokens.islandStyle) {
                ForEach(IslandStyle.allCases) { style in
                    Text(style.title).tag(style)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 420)
            HStack(spacing: 8) {
                Toggle("Morph", isOn: $morph)
                    .toggleStyle(.checkbox)
                    .onChange(of: morph) { _, on in
                        if on { mirror.adopt(selected) }
                    }
                Toggle("Crosshair", isOn: $crosshair)
                    .toggleStyle(.checkbox)
                Button("Previous") { move(-1) }
                Button("Replay") { staged.reveal.token &+= 1 }
                Button("Collapse") { staged.reveal.collapseToken &+= 1 }
                Button("Next") { move(1) }
            }
            .buttonStyle(.bordered)
        }
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
                PreviewStage(sample: staged, crosshair: crosshair)
                    .padding(.top, 10)
                    .id(morph ? "mirror" : selected.id + tokens.islandStyle.rawValue)
            }
            .frame(width: 580, height: 380)

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
                    select(sampleIndex)
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
        select((index + delta + samples.count) % samples.count)
    }

    // With Morph on, the one staged island adopts the new state inside the
    // morph spring, so the transition plays instead of a cut.
    private func select(_ next: Int) {
        index = next
        guard morph else { return }
        withAnimation(.spring(DesignTokens.glassMorphSpring)) {
            mirror.adopt(samples[next])
        }
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
