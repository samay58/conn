import SwiftUI

// The canonical island content, hosted live by IslandController. One black
// surface that grows out of the notch: the top edge is square and flush to the
// screen edge (it continues the notch hardware), the bottom corners are
// rounded, and every readable row lives below the physical notch so nothing
// clips into it. Nine machine phases render distinctly per the UX-craft spec.
// Every motion and palette value comes from DesignTokens. Approvals render
// as IslandChipView, whose buttons are pointer-only by construction.

@MainActor
final class IslandReveal: ObservableObject {
    @Published var token = 0
    @Published var collapseToken = 0
    // The scale that maps the current panel frame back onto the bare notch.
    // IslandController updates it on every summon (the chip frame is taller,
    // so its collapsed scale differs); nil falls back to the view's default.
    var collapsedScale: (x: CGFloat, y: CGFloat)?
    // The card tile's measured height, written by IslandView and read by
    // IslandController to grow the panel below the island. 0 with no card.
    @Published var cardHeight: CGFloat = 0
    // A glass style's laid-out size (IslandGlassSurface measures it). The
    // controllers size their panel to it plus shadow room; zero until the
    // first layout.
    @Published var surfaceSize: CGSize = .zero
}

@MainActor
struct IslandView: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    var topInset: CGFloat = 32
    var collapsedScale: (x: CGFloat, y: CGFloat) = (0.6, 0.35)
    @ObservedObject var reveal: IslandReveal
    // The style comes from the token (default D, set live by the menu bar's
    // Island Style); styleOverride pins one for tests. notchWidth sizes the
    // glass styles around the real notch. floating is the non-notch panel.
    var notchWidth: CGFloat = 0
    var styleOverride: IslandStyle? = nil
    var floating = false
    // Observed so a live style switch re-renders the island at once.
    @ObservedObject private var tokens = DesignTokens.current

    @State private var shakeOffset: CGFloat = 0
    @State private var shapeScaleX: CGFloat = 1
    @State private var shapeScaleY: CGFloat = 1
    @State private var contentOpacity: Double = 1
    @State private var exhaleScale: CGFloat = 1
    // The running call whose capsule has outlived the show delay.
    @State private var capsuleCallID: String?

    private var islandShape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: 0,
            bottomLeadingRadius: DesignTokens.islandCornerRadius,
            bottomTrailingRadius: DesignTokens.islandCornerRadius,
            topTrailingRadius: 0,
            style: .continuous)
    }

    var body: some View {
        let style = styleOverride ?? tokens.islandStyle
        if style == .classic && !floating {
            classicBody
        } else {
            IslandGlassSurface(
                style: style, state: state, client: client,
                topInset: topInset, notchWidth: notchWidth,
                reveal: reveal, floating: floating)
        }
    }

    // The island at its fixed height, then the card (if any) as a second
    // black tile below it. The card takes its ideal height and reports it, so
    // the panel grows to fit it rather than squeezing it.
    private var classicBody: some View {
        VStack(spacing: DesignTokens.cardGap) {
            classicIsland
                .frame(height: topInset + DesignTokens.islandContentHeight
                           + (chipShowing ? DesignTokens.chipRowHeight : 0))
            if let card = state.card {
                ClassicCardTile(card: card, onClose: { state.dismissCard() })
                    .fixedSize(horizontal: false, vertical: true)
                    .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { height in
                        reveal.cardHeight = height
                    }
                    .opacity(contentOpacity)
                    .transition(.opacity)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .animation(.easeOut(duration: DesignTokens.cardFadeDuration), value: state.card?.id)
        .onChange(of: state.card == nil) { _, gone in
            if gone { reveal.cardHeight = 0 }
        }
    }

    private var classicIsland: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: topInset)
            belowNotch
                .opacity(contentOpacity)
                .offset(x: shakeOffset)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(islandShape.fill(DesignTokens.islandBg))
        .overlay(
            // The top edge is hardware; the ring wraps sides and bottom only.
            islandShape.strokeBorder(
                DesignTokens.islandAccent.opacity(state.phase == "listening" ? 0.9 : 0),
                lineWidth: 1)
                .mask(Rectangle().padding(.top, 1))
        )
        .clipShape(islandShape)
        .scaleEffect(x: shapeScaleX, y: shapeScaleY, anchor: .top)
        .scaleEffect(exhaleScale, anchor: .top)
        .modifier(IslandBreath(isListening: state.phase == "listening"))
        .animation(.easeInOut(duration: DesignTokens.stateWordCrossfade), value: state.stateLabel)
        .task(id: state.toast) { await autoClearToast() }
        .task(id: runningCallID) { await revealCapsuleAfterDelay() }
        .onChange(of: state.rejectPulse) { _, _ in refusalPulse() }
        .onChange(of: state.phase) { _, phase in
            if phase == "done" && state.showsDoneSuccess { exhale() }
        }
        .onChange(of: reveal.token) { _, _ in breatheOpen() }
        .onChange(of: reveal.collapseToken) { _, _ in breatheClosed() }
    }

    // MARK: below-notch content

    private var chipShowing: Bool {
        state.phase == "awaiting_approval" && state.pendingChip != nil
    }

    private var belowNotch: some View {
        VStack(spacing: 7) {
            VStack(spacing: 6) {
                IslandWaveform(meter: state.meter, phase: state.phase)
                caption
                if let warning = state.axWarning {
                    Text(warning)
                        .font(.system(size: 10.5, weight: .medium))
                        .foregroundStyle(DesignTokens.islandAmber)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: 280)
                }
            }
            .frame(maxHeight: .infinity)
            if state.phase == "awaiting_approval", let chip = state.pendingChip {
                IslandChipView(chip: chip, client: client)
                    .id(chip.id)
                    .transition(.opacity)
            }
        }
        .padding(.horizontal, 18)
        .padding(.top, 7)
        .padding(.bottom, 9)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .animation(.easeOut(duration: DesignTokens.chipOpenDuration), value: chipShowing)
    }

    // A single caption line: primary text plus a compact meta trailing group.
    // Done leads with a green tick in place of a state word (spec state table).
    private var caption: some View {
        HStack(spacing: 6) {
            if state.showsDoneSuccess {
                Image(systemName: "checkmark")
                    .font(.system(size: 10.5, weight: .bold))
                    .foregroundStyle(DesignTokens.islandGreen)
            }
            if state.toast == nil, state.phase == "awaiting_approval",
               let chip = state.pendingChip {
                approvalPreview(chip.preview)
            } else if state.toast == nil, state.phase == "thinking" {
                ThinkingEllipsis(phase: state.phase)
            } else if state.toast == nil, state.phase == "acting",
                      let label = runningToolLabel {
                // A read that answers inside the delay (most connector reads
                // take 0.1 to 0.3 s) never flashes a capsule in and out.
                // A zero delay shows it at once (the preview shooter's stills).
                if capsuleCallID == runningCallID || DesignTokens.toolCapsuleShowDelay <= 0 {
                    toolCapsule(label)
                } else if state.modelLine.isEmpty {
                    ThinkingEllipsis(phase: state.phase)
                } else {
                    primaryText
                }
            } else {
                primaryText
            }
            if showsCost {
                // Two decimals at the cap reads as money. Everywhere
                // else three: sub-cent spend is real information while it counts.
                Text(String(format: state.phase == "budget_hold" ? "$%.2f" : "$%.3f",
                            state.spentUSD))
                    .font(.system(size: 10.5, weight: .medium))
                    .monospacedDigit()
                    .foregroundStyle(state.phase == "budget_hold"
                                     ? DesignTokens.islandGold
                                     : DesignTokens.islandTextSecondary.opacity(0.85))
                    .contentTransition(.numericText())
            }
            if state.phase == "budget_hold" {
                overrideButton
            }
        }
        .frame(maxWidth: 280)
    }

    private var primaryText: some View {
        Text(state.islandPrimaryText)
            .font(.system(size: primaryIsSpeech ? 12.5 : 11,
                          weight: primaryIsSpeech ? .regular : .medium))
            .foregroundStyle(primaryColor)
            .lineLimit(1)
            .truncationMode(.tail)
            .contentTransition(.opacity)
    }

    // Outline against Approve's fill: distinct by construction. Pointer-only
    // like every island control: plain style, no shortcut, nothing focusable.
    private var overrideButton: some View {
        Button {
            client.send(["type": "override_budget"])
        } label: {
            Text("Override once")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(DesignTokens.islandGold)
                .fixedSize()
                .padding(.horizontal, 10)
                .frame(minHeight: DesignTokens.chipButtonMinHeight)
                .overlay(RoundedRectangle(cornerRadius: DesignTokens.overrideCornerRadius)
                    .strokeBorder(DesignTokens.islandGold, lineWidth: 1))
                .contentShape(RoundedRectangle(cornerRadius: DesignTokens.overrideCornerRadius))
        }
        .buttonStyle(.plain)
    }

    // What the click approves, on the full-width caption line: the amber dot
    // marks it as waiting on the user, the words stay primary-white to read.
    private func approvalPreview(_ preview: String) -> some View {
        HStack(spacing: 8) {
            Circle()
                .fill(DesignTokens.islandAmber)
                .frame(width: 5, height: 5)
            Text(preview)
                .font(.system(size: 12.5, weight: .medium))
                .foregroundStyle(DesignTokens.islandText)
                .lineLimit(1)
                // The daemon budgets previews to fit whole; if this ever
                // fires it clips the end, never mid-word in the middle.
                .truncationMode(.tail)
        }
    }

    // The running tool as a quiet capsule, in place of the caption line.
    private func toolCapsule(_ label: String) -> some View {
        Text(label)
            .font(.system(size: 10.5, weight: .medium))
            .foregroundStyle(DesignTokens.islandText)
            .lineLimit(1)
            .padding(.horizontal, DesignTokens.toolChipPaddingH)
            .frame(height: DesignTokens.toolChipHeight)
            .background(Capsule(style: .continuous)
                .fill(Color.white.opacity(DesignTokens.toolChipBgOpacity)))
            .contentTransition(.opacity)
    }

    // MARK: content resolution

    private var runningCallID: String? {
        state.chips.first(where: { $0.status == "running" })?.id
    }

    private func revealCapsuleAfterDelay() async {
        capsuleCallID = nil
        guard let id = runningCallID else { return }
        try? await Task.sleep(for: .seconds(DesignTokens.toolCapsuleShowDelay))
        if !Task.isCancelled { capsuleCallID = id }
    }

    private var runningToolLabel: String? {
        guard let chip = state.chips.first(where: { $0.status == "running" }),
              !chip.name.isEmpty else { return nil }
        return ToolLabels.label(for: chip.name, preview: chip.preview)
    }

    private var primaryIsSpeech: Bool {
        if state.phase == "budget_hold" { return false }
        if state.phase == "done", state.lastActionOutcome != nil { return false }
        if state.phase == "speaking" || state.phase == "acting" { return true }
        return !state.modelLine.isEmpty || !state.userLine.isEmpty
    }

    private var showsCost: Bool {
        // An approval preview gets the whole line; spend shows again after the click.
        state.spentUSD > 0 && !primaryIsSpeech && state.toast == nil && !chipShowing
    }

    // MARK: colors

    private var primaryColor: Color {
        if state.toast != nil { return DesignTokens.islandTextSecondary }
        switch state.phase {
        case "failed": return DesignTokens.islandRed
        case "budget_hold": return DesignTokens.islandGold
        case "awaiting_approval": return DesignTokens.islandAmber
        case "done":
            if state.showsDoneSuccess { return DesignTokens.islandGreen }
            return state.lastActionOutcome == "dispatch_only"
                ? DesignTokens.islandAmber : DesignTokens.islandRed
        case "speaking": return DesignTokens.islandText
        default:
            return primaryIsSpeech ? DesignTokens.islandText : DesignTokens.islandTextSecondary
        }
    }

    // MARK: effects

    // Summon: squash and stretch out of the notch. Width spreads first, height
    // drops in one lead behind it, and each axis rides a spring whose overshoot
    // is set by its token, so the island arrives with mass instead of fading
    // in. Content lags the shape as before.
    private var activeCollapsedScale: (x: CGFloat, y: CGFloat) {
        reveal.collapsedScale ?? collapsedScale
    }

    private func breatheOpen() {
        var reset = Transaction()
        reset.disablesAnimations = true
        withTransaction(reset) {
            shapeScaleX = activeCollapsedScale.x
            shapeScaleY = activeCollapsedScale.y
            contentOpacity = 0
            exhaleScale = 1
        }
        withAnimation(.spring(DesignTokens.summonWidthSpring)) {
            shapeScaleX = 1
        }
        withAnimation(.spring(DesignTokens.summonHeightSpring).delay(DesignTokens.squashWidthLead)) {
            shapeScaleY = 1
        }
        withAnimation(.spring(DesignTokens.summonSpring).delay(DesignTokens.contentStaggerDelay)) {
            contentOpacity = 1
        }
    }

    // Collapse: the summon played backward. Height retreats into the notch
    // first with the content, width narrows back onto the notch rect the same
    // lead behind it.
    private func breatheClosed() {
        withAnimation(.spring(DesignTokens.collapseSpring)) {
            shapeScaleY = activeCollapsedScale.y
            contentOpacity = 0
        }
        withAnimation(.spring(DesignTokens.collapseSpring).delay(DesignTokens.squashWidthLead)) {
            shapeScaleX = activeCollapsedScale.x
        }
    }

    // Exhale on done: one soft contraction, released before the green settle
    // finishes. The island lets the turn go.
    private func exhale() {
        let contraction = DesignTokens.exhaleContraction * DesignTokens.aliveness
        guard contraction > 0 else { return }
        let half = DesignTokens.exhaleDuration / 2
        withAnimation(.easeIn(duration: half)) {
            exhaleScale = 1 - contraction
        }
        Task {
            try? await Task.sleep(for: .seconds(half))
            withAnimation(.easeOut(duration: half)) {
                exhaleScale = 1
            }
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

// Breath while listening: the island's height oscillates on an eased sine,
// anchored to the notch edge, so it pulses quietly while it waits. The
// timeline is paused in every other phase (and whenever aliveness disables
// the amplitude), so no animation timer runs while a chip is open or after
// collapse; the paused flag is the motion-policy guarantee.
private struct IslandBreath: ViewModifier {
    var isListening: Bool

    private var isBreathing: Bool {
        isListening && DesignTokens.breathAmplitude * DesignTokens.aliveness > 0
    }

    func body(content: Content) -> some View {
        TimelineView(.animation(minimumInterval: DesignTokens.breathFrameInterval, paused: !isBreathing)) { context in
            content
                .scaleEffect(x: 1, y: scale(at: context.date.timeIntervalSinceReferenceDate), anchor: .top)
                .animation(.easeOut(duration: DesignTokens.stateWordCrossfade), value: isBreathing)
        }
    }

    private func scale(at t: Double) -> CGFloat {
        guard isBreathing else { return 1 }
        let angle = t / DesignTokens.breathPeriod * 2 * Double.pi
        return 1 + DesignTokens.breathAmplitude * DesignTokens.aliveness * sin(angle)
    }
}

// The thinking beat: the word "thinking" with three trailing dots whose
// opacity sweeps in sequence, one dot leading the next. Color plus motion is
// the signature; no third treatment. The timeline is paused unless the phase
// is thinking and aliveness is on (the third gated timeline in the motion
// policy, after the waveform and the breath); aliveness 0 renders the dots
// static at full opacity.
struct ThinkingEllipsis: View {
    var phase: String
    // nil keeps the signature lilac; the light-glass prototype passes a
    // deeper tone of the same hue.
    var tint: Color? = nil

    // Increments once per timeline tick; the motion-policy test asserts it
    // stays static in every phase but thinking.
    @MainActor static var tickCount = 0

    private var animates: Bool {
        phase == "thinking" && DesignTokens.aliveness > 0
    }

    var body: some View {
        HStack(spacing: 0) {
            Text("thinking")
            if animates {
                TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: !animates)) { context in
                    dots(at: context.date.timeIntervalSinceReferenceDate, ticked: true)
                }
            } else {
                dots(at: 0, ticked: false)
            }
        }
        .font(.system(size: 11, weight: .medium))
        .foregroundStyle(tint ?? DesignTokens.islandAccent)
    }

    private func dots(at t: Double, ticked: Bool) -> some View {
        if ticked { Self.tickCount &+= 1 }
        return HStack(spacing: 0) {
            ForEach(0..<3, id: \.self) { i in
                Text(".")
                    .opacity(opacity(dot: i, at: t))
            }
        }
    }

    private func opacity(dot i: Int, at t: Double) -> Double {
        guard animates else { return 1 }
        let floor = DesignTokens.thinkingDotOpacityFloor
        // One crest travels dot to dot, each trailing the last by a quarter
        // turn: a quiet wave, not a blink. The lag is a shape parameter like
        // the waveform's travel constants; it stays inline by design.
        let angle = t / DesignTokens.thinkingEllipsisPeriod * 2 * .pi - Double(i) * (.pi / 2)
        return floor + (1 - floor) * (0.5 + 0.5 * sin(angle))
    }
}

// Humanized, present-progressive labels for the acting capsule. This map is
// copy, not geometry, so it lives beside the view that renders it. Every
// executable tool in the daemon registry has an entry; unmapped names fall
// back to their words.
enum ToolLabels {
    private static let labels: [String: String] = [
        "computer_get_context": "Reading context",
        "computer_screenshot": "Taking a screenshot",
        "computer_ax_snapshot": "Reading the screen",
        "app_open": "Opening app",
        "app_switch": "Switching apps",
        "app_focus_tab": "Focusing tab",
        "app_menu": "Using the menu",
        "browser_search": "Searching the web",
        "phoenix_search": "Searching the vault",
        "phoenix_open_note": "Opening note",
        "clipboard_set": "Copying to clipboard",
        "wait_for_user": "Waiting for you",
        "computer_click": "Clicking",
        "computer_type_text": "Typing text",
        "computer_scroll": "Scrolling",
        "computer_hotkey": "Pressing keys",
        "computer_key": "Pressing a key",
        "computer_create": "Creating",
        "computer_select": "Selecting",
        "computer_select_relative": "Moving selection",
        "computer_activate": "Pressing",
        "computer_visual_observe": "Looking at the screen",
        "browser_navigate": "Opening page",
        "shortcuts_list": "Checking shortcuts",
        "shortcuts_run": "Running shortcut",
    ]

    // Built-in tools use the table. Anything else (connector tools, named in
    // the user's config) uses the daemon's preview, which is written to be read
    // ("Checking today", "Searching Granola"), never the raw tool name.
    static func label(for name: String, preview: String = "") -> String {
        if let known = labels[name] { return known }
        let trimmed = preview.trimmingCharacters(in: .whitespaces)
        return trimmed.isEmpty ? name.replacingOccurrences(of: "_", with: " ") : trimmed
    }
}

// The island waveform lives in WaveformView.swift as of packet I7; the view
// here consumes it unchanged.
