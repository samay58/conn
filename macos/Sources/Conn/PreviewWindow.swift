import AppKit
import SwiftUI

// `Conn --preview`: deterministic render of the island states for design
// iteration. No daemon, no interference with a live session.

@MainActor
enum PreviewRunner {
    static func run() {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)

        let samples = PreviewSample.makeAll()

        var t = 0.0
        Timer.scheduledTimer(withTimeInterval: 1.0 / 30.0, repeats: true) { _ in
            t += 1.0 / 30.0
            let syllable = max(0, sin(t * 6.2)) * (0.55 + 0.45 * sin(t * 1.7))
            let value = min(0.15 + syllable * 0.75, 1.0)
            Task { @MainActor in
                for sample in samples {
                    switch sample.state.phase {
                    case "listening":
                        sample.state.level = value
                    case "speaking":
                        sample.state.level = value * 0.8
                    case "thinking", "acting":
                        sample.state.level = 0.18
                    default:
                        sample.state.level = 0
                    }
                }
            }
        }

        let hosting = NSHostingView(rootView: IslandPreviewRoot(samples: samples))
        hosting.sizingOptions = [.preferredContentSize]

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 820, height: 690),
                              styleMask: [.titled, .closable],
                              backing: .buffered, defer: false)
        window.title = "Conn island preview"
        window.contentView = hosting
        window.appearance = NSAppearance(named: .aqua)
        if let screen = NSScreen.main {
            let f = screen.visibleFrame
            window.setFrameOrigin(NSPoint(x: f.maxX - 880, y: f.minY + 40))
        }
        window.orderFrontRegardless()
        app.run()
    }
}

private struct PreviewSample: Identifiable {
    let id: String
    let title: String
    let note: String
    let state: AppState

    @MainActor
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
            sample("acting", "Acting", "tool name is visible") {
                $0.connected = true
                $0.live = true
                $0.modelLine = "Searching the vault."
                $0.spentUSD = 0.021
            },
            sample("awaiting_approval", "Awaiting approval", "chip row opens inside the island") {
                $0.connected = true
                $0.live = true
                $0.modelLine = "I can copy that to your clipboard."
                $0.chips = [Chip(id: "c1", preview: "Copy 29 characters to clipboard",
                                  status: "proposed")]
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
                $0.modelLine = "$ cap reached."
                $0.spentUSD = 1.000
            },
            sample("thinking", "Toast", "daemon toast replaces the state line") {
                $0.connected = true
                $0.live = true
                $0.toast = "Receipt saved"
                $0.modelLine = "Still thinking."
                $0.spentUSD = 0.044
            },
        ]
    }

    @MainActor
    private static func sample(
        _ phase: String,
        _ title: String,
        _ note: String,
        configure: (AppState) -> Void
    ) -> PreviewSample {
        let state = AppState()
        state.phase = phase
        configure(state)
        return PreviewSample(id: "\(phase)-\(title)", title: title, note: note, state: state)
    }
}

@MainActor
private struct IslandPreviewRoot: View {
    let samples: [PreviewSample]
    @State private var index = 1
    @State private var replaySeed = 0
    @State private var replayVisible = true

    private var selected: PreviewSample { samples[index] }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            HStack(alignment: .top, spacing: 24) {
                mainStage
                stateList
            }
        }
        .padding(28)
        .background(PreviewBackdrop())
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Conn island preview")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
                Text("State, one line, cost, chip when needed. The old panel is not part of this loop.")
                    .font(.system(size: 13))
                    .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
            }
            Spacer()
            controls
        }
    }

    private var controls: some View {
        HStack(spacing: 8) {
            Button("Previous") { move(-1) }
            Button("Replay") { replay() }
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
                IslandPreviewSurface(
                    state: selected.state,
                    replaySeed: replaySeed,
                    isVisible: replayVisible
                )
                    .padding(.top, 10)
                    .id(selected.id)
            }
            .frame(width: 500, height: 300)

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
        replayVisible = true
    }

    private func replay() {
        withAnimation(.easeOut(duration: DesignTokens.chipOpenDuration)) {
            replaySeed += 1
            replayVisible = true
        }

        let phase = selected.state.phase
        let seed = replaySeed
        let delay: TimeInterval?
        switch phase {
        case "done":
            delay = DesignTokens.doneSettleDuration + DesignTokens.doneCollapseDelay
        case "failed":
            delay = DesignTokens.failedCollapseDelay
        default:
            delay = nil
        }
        guard let delay else { return }
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) {
            guard seed == replaySeed, selected.state.phase == phase else { return }
            withAnimation(.easeOut(duration: DesignTokens.chipOpenDuration)) {
                replayVisible = false
            }
        }
    }
}

@MainActor
private struct IslandPreviewSurface: View {
    @ObservedObject var state: AppState
    let replaySeed: Int
    let isVisible: Bool

    private var line: String {
        if !state.modelLine.isEmpty { return state.modelLine }
        if !state.userLine.isEmpty { return state.userLine }
        switch state.phase {
        case "listening": return "Listening."
        case "thinking": return "Thinking."
        case "acting": return "Using the current tool."
        case "speaking": return "Speaking."
        case "done": return "Done."
        case "failed": return "Reconnecting."
        case "budget_hold": return "$ cap reached."
        default: return ""
        }
    }

    private var chipOpen: Bool {
        state.phase == "awaiting_approval" || state.pendingChip != nil
    }

    // Mirrors IslandView's live silhouette: square top flush to the notch,
    // rounded bottom, all content in the lane below the notch.
    private static let notch: CGFloat = 30

    private var previewShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: 0,
            bottomLeadingRadius: DesignTokens.islandCornerRadius,
            bottomTrailingRadius: DesignTokens.islandCornerRadius,
            topTrailingRadius: 0,
            style: .continuous)
    }

    private var primaryIsSpeech: Bool {
        state.phase == "speaking" || state.phase == "acting"
            || !state.modelLine.isEmpty || !state.userLine.isEmpty
    }

    var body: some View {
        if state.phase == "idle" {
            IdlePreview()
        } else if !isVisible {
            CollapsedPreview()
        } else {
            VStack(spacing: 0) {
                Color.clear.frame(height: Self.notch)
                VStack(spacing: 7) {
                    VStack(spacing: 6) {
                        PreviewWaveform(level: state.level, phase: state.phase)
                        caption
                    }
                    .frame(maxHeight: .infinity)
                    if let chip = state.pendingChip {
                        approvalRow(chip)
                    }
                }
                .padding(.horizontal, 18)
                .padding(.top, 7)
                .padding(.bottom, 9)
                .frame(maxHeight: .infinity)
            }
            .frame(width: 316,
                   height: Self.notch + DesignTokens.islandContentHeight
                       + (chipOpen ? DesignTokens.chipRowHeight : 0))
            .background(previewShape.fill(DesignTokens.islandBg))
            .overlay(
                previewShape.strokeBorder(
                    state.phase == "listening" ? DesignTokens.islandAccent.opacity(0.9) : .clear,
                    lineWidth: 1)
            )
            .clipShape(previewShape)
            .scaleEffect(replaySeed.isMultiple(of: 2) ? 1 : 0.992)
            .animation(.easeInOut(duration: DesignTokens.stateWordCrossfade),
                       value: state.stateLabel)
            .animation(.easeOut(duration: DesignTokens.chipOpenDuration),
                       value: chipOpen)
        }
    }

    private var caption: some View {
        HStack(spacing: 6) {
            if state.phase == "done" {
                Image(systemName: "checkmark")
                    .font(.system(size: 10.5, weight: .bold))
                    .foregroundStyle(DesignTokens.islandGreen)
            }
            Text(state.toast ?? line)
                .font(.system(size: primaryIsSpeech ? 12.5 : 11,
                              weight: primaryIsSpeech ? .regular : .medium))
                .foregroundStyle(captionColor)
                .lineLimit(1)
                .truncationMode(.tail)
                .contentTransition(.opacity)
            if state.spentUSD > 0 && !primaryIsSpeech && state.toast == nil {
                Text(String(format: "$%.3f", state.spentUSD))
                    .font(.system(size: 10.5, weight: .medium))
                    .monospacedDigit()
                    .foregroundStyle(state.phase == "budget_hold"
                                     ? DesignTokens.islandRed
                                     : DesignTokens.islandTextSecondary.opacity(0.85))
            }
            if state.phase == "budget_hold" {
                Text("override")
                    .font(.system(size: 10.5, weight: .semibold))
                    .foregroundStyle(DesignTokens.islandRed)
            }
        }
        .frame(maxWidth: 280)
    }

    private var captionColor: Color {
        if state.toast != nil { return DesignTokens.islandTextSecondary }
        switch state.phase {
        case "failed", "budget_hold": return DesignTokens.islandRed
        case "awaiting_approval": return DesignTokens.islandAmber
        case "done": return DesignTokens.islandGreen
        case "speaking": return DesignTokens.islandText
        default: return primaryIsSpeech ? DesignTokens.islandText : DesignTokens.islandTextSecondary
        }
    }

    private func approvalRow(_ chip: Chip) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(DesignTokens.islandAmber)
                .frame(width: 5, height: 5)
            Text(chip.preview)
                .font(.system(size: 12.5, weight: .medium))
                .foregroundStyle(DesignTokens.islandText)
                .lineLimit(1)
                .truncationMode(.middle)
            Spacer(minLength: 8)
            Text("Deny")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(DesignTokens.islandTextSecondary)
            Text("Approve")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(DesignTokens.islandBg)
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(
                    RoundedRectangle(cornerRadius: 6, style: .continuous)
                        .fill(DesignTokens.islandText)
                )
        }
        .frame(maxWidth: 280)
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

private struct CollapsedPreview: View {
    var body: some View {
        VStack(spacing: 10) {
            Capsule(style: .continuous)
                .fill(Color.black.opacity(0.88))
                .frame(width: 172, height: 28)
            Text("Collapsed back into the notch.")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(Color.black.opacity(0.50))
        }
        .frame(width: 390, height: 132)
    }
}

private struct PreviewWaveform: View {
    var level: Double
    var phase: String

    private static let bars = 13
    private static let envelope: [Double] = (0..<bars).map { i in
        let x = (Double(i) - Double(bars - 1) / 2) / (Double(bars) / 2)
        return max(exp(-2.0 * x * x), 0.24)
    }

    private var tint: Color {
        switch phase {
        case "listening": return DesignTokens.islandAccent
        case "speaking": return DesignTokens.islandText
        case "failed", "budget_hold": return DesignTokens.islandRed
        case "awaiting_approval": return DesignTokens.islandAmber.opacity(0.45)
        default: return DesignTokens.islandTextSecondary
        }
    }

    var body: some View {
        HStack(spacing: 4) {
            ForEach(0..<Self.bars, id: \.self) { i in
                let base = phase == "awaiting_approval" ? 0.03 : max(level, 0.08)
                let height = 4.0 + 24.0 * Self.envelope[i] * base
                Capsule(style: .continuous)
                    .fill(tint)
                    .frame(width: 4, height: max(height, 4))
            }
        }
        .frame(height: 30)
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
        case "failed", "budget_hold": return DesignTokens.islandRed
        default: return DesignTokens.islandTextSecondary
        }
    }
}

private struct PreviewBackdrop: View {
    var body: some View {
        Color(red: 0.96, green: 0.95, blue: 0.92)
    }
}
