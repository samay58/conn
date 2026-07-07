import SwiftUI

// The canonical island content, hosted live by IslandController. One black
// surface that grows out of the notch: the top edge is square and flush to the
// screen edge (it continues the notch hardware), the bottom corners are
// rounded, and every readable row lives below the physical notch so nothing
// clips into it. Nine machine phases render distinctly per the UX-craft spec.
// Every motion and palette value comes from DesignTokens. The interactive
// approve/deny buttons land in packet I8; this renders the approval preview
// with no keyboard-reachable controls.

@MainActor
final class IslandReveal: ObservableObject {
    @Published var token = 0
}

@MainActor
struct IslandView: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    var topInset: CGFloat = 32
    @ObservedObject var reveal: IslandReveal

    @State private var shakeOffset: CGFloat = 0
    @State private var revealScale: CGFloat = 1
    @State private var revealOpacity: Double = 1

    private var islandShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: 0,
            bottomLeadingRadius: DesignTokens.islandCornerRadius,
            bottomTrailingRadius: DesignTokens.islandCornerRadius,
            topTrailingRadius: 0,
            style: .continuous)
    }

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: topInset)
            belowNotch
                .scaleEffect(x: 1, y: revealScale, anchor: .top)
                .opacity(revealOpacity)
                .offset(x: shakeOffset)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(islandShape.fill(DesignTokens.islandBg))
        .overlay(
            islandShape.strokeBorder(
                DesignTokens.islandAccent.opacity(state.phase == "listening" ? 0.9 : 0),
                lineWidth: 1)
        )
        .clipShape(islandShape)
        .animation(.easeInOut(duration: DesignTokens.stateWordCrossfade), value: state.stateLabel)
        .task(id: state.toast) { await autoClearToast() }
        .onChange(of: state.rejectPulse) { _, _ in refusalPulse() }
        .onChange(of: reveal.token) { _, _ in breatheOpen() }
    }

    // MARK: below-notch content

    private var belowNotch: some View {
        VStack(spacing: 7) {
            VStack(spacing: 6) {
                IslandWaveform(level: state.level, phase: state.phase)
                caption
            }
            .frame(maxHeight: .infinity)
            if state.phase == "awaiting_approval", let chip = state.pendingChip {
                approvalRow(chip)
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 7)
        .padding(.bottom, 9)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    // A single caption line: primary text plus a compact meta trailing group.
    // Done leads with a green tick in place of a state word (spec state table).
    private var caption: some View {
        HStack(spacing: 6) {
            if state.phase == "done" {
                Image(systemName: "checkmark")
                    .font(.system(size: 10.5, weight: .bold))
                    .foregroundStyle(DesignTokens.islandGreen)
            }
            Text(primaryText)
                .font(.system(size: primaryIsSpeech ? 12.5 : 11,
                              weight: primaryIsSpeech ? .regular : .medium))
                .foregroundStyle(primaryColor)
                .lineLimit(1)
                .truncationMode(.tail)
                .contentTransition(.opacity)
            if showsCost {
                Text(String(format: "$%.3f", state.spentUSD))
                    .font(.system(size: 10.5, weight: .medium))
                    .monospacedDigit()
                    .foregroundStyle(state.phase == "budget_hold"
                                     ? DesignTokens.islandRed
                                     : DesignTokens.islandTextSecondary.opacity(0.85))
                    .contentTransition(.numericText())
            }
            if state.phase == "budget_hold" {
                Button {
                    client.send(["type": "override_budget"])
                } label: {
                    Text("override")
                        .font(.system(size: 10.5, weight: .semibold))
                        .foregroundStyle(DesignTokens.islandRed)
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: 280)
    }

    private func approvalRow(_ chip: Chip) -> some View {
        HStack(spacing: 8) {
            Circle().fill(DesignTokens.islandAmber).frame(width: 5, height: 5)
            Text(chip.preview)
                .font(.system(size: 12.5, weight: .medium))
                .foregroundStyle(DesignTokens.islandText)
                .lineLimit(1)
                .truncationMode(.middle)
        }
        .frame(maxWidth: 280)
    }

    // MARK: content resolution

    private var runningTool: String? {
        state.chips.first(where: { $0.status == "running" })?.preview
    }

    private var primaryIsSpeech: Bool {
        if state.phase == "speaking" || state.phase == "acting" { return true }
        return !state.modelLine.isEmpty || !state.userLine.isEmpty
    }

    private var primaryText: String {
        if let toast = state.toast { return toast }
        switch state.phase {
        case "acting":
            if let tool = runningTool { return tool }
            return state.modelLine.isEmpty ? state.stateLabel : state.modelLine
        case "awaiting_approval":
            return state.stateLabel
        case "budget_hold":
            return "cap reached"
        case "speaking":
            return state.modelLine.isEmpty ? state.stateLabel : state.modelLine
        default:
            if !state.modelLine.isEmpty { return state.modelLine }
            if !state.userLine.isEmpty { return state.userLine }
            return state.stateLabel
        }
    }

    private var showsCost: Bool {
        state.spentUSD > 0 && !primaryIsSpeech && state.toast == nil
    }

    // MARK: colors

    private var primaryColor: Color {
        if state.toast != nil { return DesignTokens.islandTextSecondary }
        switch state.phase {
        case "failed", "budget_hold": return DesignTokens.islandRed
        case "awaiting_approval": return DesignTokens.islandAmber
        case "done": return DesignTokens.islandGreen
        case "speaking": return DesignTokens.islandText
        default:
            return primaryIsSpeech ? DesignTokens.islandText : DesignTokens.islandTextSecondary
        }
    }

    // MARK: effects

    private func breatheOpen() {
        var reset = Transaction()
        reset.disablesAnimations = true
        withTransaction(reset) {
            revealScale = 0.94
            revealOpacity = 0
        }
        withAnimation(.spring(DesignTokens.summonSpring)) {
            revealScale = 1
            revealOpacity = 1
        }
    }

    private func refusalPulse() {
        let step = DesignTokens.refusalPulseDuration / Double(DesignTokens.refusalShakeCycles)
        withAnimation(.easeInOut(duration: step)
            .repeatCount(DesignTokens.refusalShakeCycles, autoreverses: true)) {
            shakeOffset = DesignTokens.refusalShakeMagnitude
        }
        Task {
            try? await Task.sleep(for: .seconds(DesignTokens.refusalPulseDuration))
            shakeOffset = 0
        }
    }

    private func autoClearToast() async {
        guard state.toast != nil else { return }
        try? await Task.sleep(for: .seconds(DesignTokens.toastDuration))
        if !Task.isCancelled { state.toast = nil }
    }
}

// A compact island-palette waveform. Animates only while a session is in an
// active phase (listening, thinking, acting, speaking); every other phase
// renders a static low bar set and starts no timer. The full state-gated
// WaveformView rework is packet I7; this keeps the nine states reviewable now.

private struct IslandWaveform: View {
    var level: Double
    var phase: String

    private static let bars = 15
    private static let envelope: [Double] = (0..<bars).map { i in
        let x = (Double(i) - Double(bars - 1) / 2) / (Double(bars) / 2)
        return max(exp(-1.9 * x * x), 0.22)
    }
    private static let phases: [Double] = (0..<bars).map { Double($0) * 1.31 }

    private var animates: Bool {
        phase == "listening" || phase == "thinking" || phase == "acting" || phase == "speaking"
    }

    private var tint: Color {
        switch phase {
        case "listening": return DesignTokens.islandAccent
        case "speaking": return DesignTokens.islandText
        case "failed", "budget_hold": return DesignTokens.islandRed
        case "awaiting_approval": return DesignTokens.islandAmber.opacity(0.5)
        case "done": return DesignTokens.islandGreen
        default: return DesignTokens.islandTextSecondary
        }
    }

    var body: some View {
        if animates {
            TimelineView(.animation(minimumInterval: 1.0 / 60.0)) { context in
                bars(at: context.date.timeIntervalSinceReferenceDate)
            }
        } else {
            bars(at: 0)
        }
    }

    private func bars(at t: Double) -> some View {
        let busy = phase == "thinking" || phase == "acting"
        return HStack(spacing: 3) {
            ForEach(0..<Self.bars, id: \.self) { i in
                let wobble = 0.5 + 0.5 * sin(t * 2.6 + Self.phases[i])
                let amplitude: Double = animates
                    ? (busy ? 0.14 + 0.09 * wobble : max(level, 0.14) * (0.42 + 0.58 * wobble))
                    : 0.05
                let height = 3.0 + 21.0 * Self.envelope[i] * amplitude
                Capsule(style: .continuous)
                    .fill(tint)
                    .frame(width: 3, height: max(height, 3))
            }
        }
        .frame(height: 24)
        .animation(.easeOut(duration: DesignTokens.stateWordCrossfade), value: animates)
    }
}
