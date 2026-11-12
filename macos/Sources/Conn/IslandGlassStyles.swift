import AppKit
import SwiftUI

// The notch island's styles, rendered by IslandView whenever
// DesignTokens.islandStyle is not .classic. D (Character) is the live
// default; classic stays selectable from the menu bar; A, B and C are
// preview-only prototypes (`Conn --preview` flips the token live).
//
//   A  Fused: the classic silhouette, square top flush to the notch, but the
//      black body sits inside a thin Liquid Glass rim with a specular hairline
//      along the bottom curve and a faint inner light.
//   B  Floating: a Liquid Glass capsule detached below the notch, adaptive to
//      light and dark, that morphs into a rounded card for content.
//   C  Pill and card: the notch widens sideways into a black pill whose ears
//      carry the waveform and the state; content drops into a smoked glass
//      card beneath it.
//   D  Character: the app icon come alive. A's fused pill in the icon's
//      palette, lime eyes beside a lilac-to-pink voice line, a rim fading
//      to a lilac lower edge, and a wink when a turn lands.
//
// Cards (AppState.card, from the daemon) render in every style; classic's
// tile is ClassicCardTile below.
//
// Performance rules for every style: glass is static per state. Only transform
// and opacity animate (plus B's shape size and corner during a morph, which
// is a layout change, not a glass parameter). No new TimelineViews: the
// waveform and the thinking ellipsis are the existing gated ones.

enum IslandStyle: String, CaseIterable, Identifiable {
    case classic, a, b, c, d

    var id: String { rawValue }

    var title: String {
        switch self {
        case .classic: return "Classic"
        case .a: return "A  Fused"
        case .b: return "B  Floating"
        case .c: return "C  Pill + card"
        case .d: return "D  Character"
        }
    }

    var ink: IslandInk {
        switch self {
        case .b: return .adaptive
        case .d: return .character
        default: return .onDark
        }
    }
}

// MARK: ink

// The colors a surface draws with. On black (A, the C pill, the smoked C
// card) they are the classic palette; on B's adaptive glass they are system
// label colors so the capsule reads in light and dark mode alike.
struct IslandInk {
    var primary: Color
    var secondary: Color
    var hairline: Color
    var well: Color
    var accent: Color
    var approveFill: Color
    var approveText: Color
    var done: Color = DesignTokens.islandGreen
    var attention: Color = DesignTokens.islandAmber
    var voice: Color = DesignTokens.islandAccent
    // The words beside the done check; nil colors them like the check.
    var doneText: Color? = nil
    // Deny's label; nil keeps the secondary text color.
    var secondaryButtonText: Color? = nil

    static var onDark: IslandInk {
        IslandInk(
            primary: DesignTokens.islandText,
            secondary: DesignTokens.islandTextSecondary,
            hairline: Color.white.opacity(0.1),
            well: Color.white.opacity(0.08),
            accent: DesignTokens.islandAccent,
            approveFill: DesignTokens.islandText,
            approveText: DesignTokens.islandBg)
    }

    // Style d, from the icon, with the color kept to the details: lime is
    // live (the eyes, the listening line, the done check), lilac is the voice
    // and fills Approve, hot pink is the eyes asking for you. Text stays
    // white; neutrals are white at fixed alphas so they sit on the black core.
    static var character: IslandInk {
        let text = Color.white.opacity(DesignTokens.characterTextOpacity)
        return IslandInk(
            primary: text,
            secondary: Color.white.opacity(DesignTokens.characterTextSecondaryOpacity),
            hairline: Color.white.opacity(DesignTokens.characterHairlineOpacity),
            well: Color.white.opacity(DesignTokens.characterWellOpacity),
            accent: DesignTokens.iconLime,
            approveFill: DesignTokens.iconLilac,
            approveText: DesignTokens.iconInkBottom,
            done: DesignTokens.iconLime,
            attention: DesignTokens.iconPink,
            voice: DesignTokens.iconLilac,
            doneText: text,
            secondaryButtonText: text)
    }

    static var adaptive: IslandInk {
        IslandInk(
            primary: Color(nsColor: .labelColor),
            secondary: Color(nsColor: .secondaryLabelColor),
            hairline: Color(nsColor: .separatorColor),
            well: Color(nsColor: .labelColor).opacity(0.06),
            accent: adaptiveAccent,
            approveFill: Color(nsColor: .labelColor),
            approveText: Color(nsColor: .textBackgroundColor),
            voice: adaptiveAccent)
    }

    // Lilac on dark glass, the deeper lilac token on light glass.
    private static var adaptiveAccent: Color {
        let deep = DesignTokens.current.glassAccentDeepRGB
        let light = DesignTokens.current.islandAccentRGB
        return Color(nsColor: NSColor(name: nil) { appearance in
            let dark = appearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
            let c = dark ? light : deep
            return NSColor(srgbRed: c.red, green: c.green, blue: c.blue, alpha: 1)
        })
    }

    func color(for tone: IslandTone, speech: Bool) -> Color {
        switch tone {
        case .done: return doneText ?? done
        case .approval: return attention
        case .caution: return DesignTokens.islandAmber
        case .failed: return DesignTokens.islandRed
        case .budget: return DesignTokens.islandGold
        case .listening: return speech ? primary : accent
        case .speaking: return primary
        default: return speech ? primary : secondary
        }
    }

    // The waveform tint on this ink; nil keeps the classic on-black tints.
    func waveformTint(for tone: IslandTone, adaptive: Bool) -> Color? {
        guard adaptive else { return nil }
        switch tone {
        case .listening: return accent
        case .speaking: return primary
        case .done: return DesignTokens.islandGreen
        case .approval, .caution: return DesignTokens.islandAmber
        case .failed: return DesignTokens.islandRed
        case .budget: return DesignTokens.islandGold
        default: return secondary
        }
    }
}

enum IslandTone { case idle, listening, thinking, acting, speaking, done, caution, failed, budget, approval }

// MARK: readout

// What the island says right now, resolved once from AppState with the same
// rules IslandView's caption uses (primary text, speech weight, cost
// visibility), so the three directions differ in form, never in content.
@MainActor
struct IslandReadout {
    let tone: IslandTone
    let text: String
    let isSpeech: Bool
    let runningLabel: String?
    let cost: String?
    let pendingChip: Chip?
    let showsCheck: Bool
    let hasToast: Bool

    init(state: AppState) {
        let chip = state.phase == "awaiting_approval" ? state.pendingChip : nil
        pendingChip = chip
        hasToast = state.toast != nil
        showsCheck = state.showsDoneSuccess
        text = state.islandPrimaryText

        if state.phase == "acting",
           let running = state.chips.first(where: { $0.status == "running" }),
           !running.name.isEmpty {
            runningLabel = ToolLabels.label(for: running.name, preview: running.preview)
        } else {
            runningLabel = nil
        }

        switch state.phase {
        case "idle": tone = .idle
        case "listening": tone = .listening
        case "thinking": tone = .thinking
        case "acting": tone = .acting
        case "speaking": tone = .speaking
        case "awaiting_approval": tone = .approval
        case "failed": tone = .failed
        case "budget_hold": tone = .budget
        case "done":
            if state.showsDoneSuccess {
                tone = .done
            } else {
                tone = state.lastActionOutcome == "dispatch_only" ? .caution : .failed
            }
        default: tone = .thinking
        }

        let speech: Bool
        if state.phase == "budget_hold" {
            speech = false
        } else if state.phase == "done", state.lastActionOutcome != nil {
            speech = false
        } else if state.phase == "speaking" || state.phase == "acting" {
            speech = true
        } else {
            speech = !state.modelLine.isEmpty || !state.userLine.isEmpty
        }
        isSpeech = speech

        if state.spentUSD > 0, !speech, state.toast == nil, chip == nil {
            cost = String(format: state.phase == "budget_hold" ? "$%.2f" : "$%.3f", state.spentUSD)
        } else {
            cost = nil
        }
    }

    var showsEllipsis: Bool { tone == .thinking && !hasToast }
}

// MARK: shared pieces

// One line of state: a check on success, the thinking beat, the running
// connector label, or the primary text.
struct ReadoutLabel: View {
    let readout: IslandReadout
    let ink: IslandInk
    let phase: String
    var size: CGFloat = 13
    // D shows the running label itself, behind the capsule show delay.
    var showsRunning = true

    var body: some View {
        HStack(spacing: 6) {
            if readout.showsCheck {
                Image(systemName: "checkmark")
                    .font(.system(size: size - 2, weight: .bold))
                    .foregroundStyle(ink.done)
            }
            if readout.showsEllipsis {
                ThinkingEllipsis(phase: phase, tint: ink.voice)
            } else if showsRunning, let label = readout.runningLabel, !readout.hasToast {
                Text(label)
                    .font(.system(size: size - 1, weight: .medium))
                    .foregroundStyle(ink.primary)
                    .lineLimit(1)
            } else {
                Text(readout.text)
                    .font(.system(size: readout.isSpeech ? size : size - 1.5,
                                  weight: readout.isSpeech ? .regular : .medium))
                    .foregroundStyle(readout.hasToast
                                     ? ink.secondary
                                     : ink.color(for: readout.tone, speech: readout.isSpeech))
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
    }
}

struct CostLabel: View {
    let cost: String
    let ink: IslandInk
    var budget = false

    var body: some View {
        Text(cost)
            .font(.system(size: 11, weight: .medium))
            .monospacedDigit()
            .foregroundStyle(budget ? DesignTokens.islandGold : ink.secondary)
            .contentTransition(.numericText())
    }
}

// The existing gated waveform, drawn smaller for a smaller slot. The canvas
// draws at the scaled size directly, so the timeline keeps its gate.
struct GlassWaveform: View {
    let meter: VoiceLevelMeter
    let phase: String
    var tint: Color?
    var scale: CGFloat

    var body: some View {
        IslandWaveform(meter: meter, phase: phase, tintOverride: tint, scale: scale)
    }
}

// Button faces for the prototype styles. The Button wrappers live in
// IslandChipView and stay plain-styled: pointer-only, no shortcut, no focus.
struct GlassButtonLabel: View {
    enum Role { case primary, secondary, quiet }
    let title: String
    let role: Role
    let ink: IslandInk
    var settled = false

    var body: some View {
        Text(title)
            .font(.system(size: 12.5, weight: role == .primary ? .semibold : .medium))
            .fixedSize()
            .foregroundStyle(foreground)
            .padding(.horizontal, role == .quiet ? 6 : 14)
            .frame(height: DesignTokens.glassButtonHeight)
            .background(Capsule(style: .continuous).fill(fill))
            .contentShape(Capsule(style: .continuous))
    }

    private var foreground: Color {
        switch role {
        case .primary: return ink.approveText
        case .secondary: return settled ? ink.primary : (ink.secondaryButtonText ?? ink.secondary)
        case .quiet: return ink.secondary
        }
    }

    private var fill: Color {
        switch role {
        case .primary: return settled ? ink.done : ink.approveFill
        case .secondary: return ink.well
        case .quiet: return Color.clear
        }
    }
}

// Press feedback for the glass styles' pointer-only buttons: a slight scale
// while held, nothing else. A ButtonStyle like .plain: no shortcut, no
// default-button role, no focus ring (the panels can never become key).
struct IslandPressStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? DesignTokens.characterPressScale : 1)
            .animation(.easeOut(duration: DesignTokens.characterPressDuration),
                       value: configuration.isPressed)
    }
}

// A single hairline rule, one physical pixel at 2x.
struct Hairline: View {
    let color: Color
    var body: some View {
        Rectangle().fill(color).frame(height: 0.5)
    }
}

// Proposes a child its ideal width up to a cap, so a capsule hugs short text
// and truncates long text instead of overflowing.
struct HugWidth: Layout {
    var minWidth: CGFloat
    var maxWidth: CGFloat

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let child = subviews.first else { return .zero }
        let ideal = child.sizeThatFits(.unspecified)
        let width = min(max(ideal.width, minWidth), maxWidth)
        return child.sizeThatFits(ProposedViewSize(width: width, height: proposal.height))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        subviews.first?.place(at: bounds.origin,
                              proposal: ProposedViewSize(width: bounds.width, height: bounds.height))
    }
}

// Liquid Glass on macOS 26 and later; a system material with a hairline
// below it. `smoke` darkens the glass for white text (direction C's card).
struct GlassSurface<S: Shape>: ViewModifier {
    let shape: S
    var smoke: Double?

    func body(content: Content) -> some View {
        if #available(macOS 26, *) {
            content.glassEffect(glass, in: shape)
        } else {
            content
                .background(shape.fill(smoke == nil ? Material.regularMaterial : Material.ultraThinMaterial))
                .background(shape.fill(Color.black.opacity(smoke ?? 0)))
                .overlay(shape.stroke(Color.white.opacity(DesignTokens.glassRimOpacity), lineWidth: 0.5))
        }
    }

    @available(macOS 26, *)
    private var glass: Glass {
        guard let smoke else { return .regular }
        return .regular.tint(Color.black.opacity(smoke))
    }
}

// MARK: cards (shared by every style, classic included)

// The approval preview as a readable line: the amber dot marks it as waiting
// on the user, the words stay primary to read.
struct ApprovalPreview: View {
    let preview: String
    let ink: IslandInk
    var centered = false
    // D drops the dot: its eyes already turn pink while it waits on you.
    var marker = true

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            if marker {
                Circle()
                    .fill(ink.attention)
                    .frame(width: 6, height: 6)
                    .alignmentGuide(.firstTextBaseline) { d in d[.bottom] - 1 }
            }
            Text(preview)
                .font(.system(size: 13.5, weight: .medium))
                .foregroundStyle(ink.primary)
                .lineLimit(2)
                .multilineTextAlignment(centered ? .center : .leading)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: centered ? .center : .leading)
    }
}

// One card's content, styled by ink: a header (list title and count, or the
// reply's recipient line and state word), then rows or the reply body. The
// close button shows on persisting cards except a reply waiting on the chip,
// where closing would read as a decision it is not.
struct IslandCardContent: View {
    let card: IslandCard
    let ink: IslandInk
    var monograms = false
    var wellBody = false
    var onClose: (() -> Void)?

    private var showsClose: Bool {
        card.persist && card.state != "approve" && onClose != nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: card.kind == .reply ? 10 : 4) {
            header
            switch card.kind {
            case .reply: replyBody
            case .list: rows
            }
        }
        .animation(.easeOut(duration: DesignTokens.cardFadeDuration), value: card.state)
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(card.kind == .reply ? card.subtitle : card.title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(ink.primary)
                .lineLimit(1)
            Spacer(minLength: 8)
            Text(card.kind == .reply ? card.title : card.subtitle)
                .font(.system(size: 11.5, weight: .medium))
                .monospacedDigit()
                .foregroundStyle(card.kind == .reply ? stateColor : ink.secondary)
                .lineLimit(1)
                .contentTransition(.opacity)
            if showsClose, let onClose {
                // Pointer-only like every island control: plain style, no
                // shortcut, nothing focusable.
                Button(action: onClose) {
                    Image(systemName: "xmark")
                        .font(.system(size: 8.5, weight: .bold))
                        .foregroundStyle(ink.secondary)
                        .frame(width: DesignTokens.characterCloseSize,
                               height: DesignTokens.characterCloseSize)
                        .background(Circle().fill(ink.well))
                        // The hit area reaches past the drawn circle so a
                        // small target is not a fiddly one; layout ignores it.
                        .contentShape(Rectangle().inset(by: (DesignTokens.characterCloseSize
                                                             - DesignTokens.characterCloseHitSize) / 2))
                }
                .buttonStyle(.plain)
                .alignmentGuide(.firstTextBaseline) { d in d[.bottom] - 4 }
            }
        }
    }

    private var stateColor: Color {
        switch card.state {
        case "approve": return ink.attention
        case "unconfirmed": return DesignTokens.islandAmber
        case "sent": return ink.done
        case "held": return DesignTokens.islandRed
        default: return ink.secondary
        }
    }

    private var replyBody: some View {
        Text(card.body)
            .font(.system(size: 13))
            .lineSpacing(2.5)
            .foregroundStyle(ink.primary)
            .fixedSize(horizontal: false, vertical: true)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(wellBody ? 12 : 0)
            .background(
                RoundedRectangle(cornerRadius: DesignTokens.cardCornerRadius - 4, style: .continuous)
                    .fill(wellBody ? ink.well : Color.clear))
            .opacity(card.isSettledReply ? 0.6 : 1)
    }

    private var rows: some View {
        VStack(alignment: .leading, spacing: 0) {
            ForEach(Array(card.rows.enumerated()), id: \.offset) { index, row in
                if index > 0 {
                    Hairline(color: ink.hairline)
                        .padding(.leading, monograms ? 38 : 0)
                }
                HStack(alignment: .center, spacing: 12) {
                    if monograms {
                        Text(String(row.title.prefix(1)))
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(ink.primary)
                            .frame(width: 26, height: 26)
                            .background(Circle().fill(ink.well))
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(alignment: .firstTextBaseline) {
                            Text(row.title)
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundStyle(ink.primary)
                                .lineLimit(1)
                            Spacer(minLength: 8)
                            Text(row.detail)
                                .font(.system(size: 11, weight: .medium))
                                .monospacedDigit()
                                .foregroundStyle(ink.secondary)
                                .lineLimit(1)
                        }
                        if !row.note.isEmpty {
                            Text(row.note)
                                .font(.system(size: 12))
                                .foregroundStyle(ink.secondary)
                                .lineLimit(1)
                                .truncationMode(.tail)
                        }
                    }
                }
                .padding(.vertical, 7)
            }
        }
    }
}

// Classic's card: a second black tile under the island, the island's width,
// in the island's own palette. Measured so IslandController can grow the
// panel to fit it.
struct ClassicCardTile: View {
    let card: IslandCard
    let onClose: () -> Void

    var body: some View {
        IslandCardContent(card: card, ink: .onDark, onClose: onClose)
            .padding(DesignTokens.cardPadding)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: DesignTokens.cardCornerRadius, style: .continuous)
                    .fill(DesignTokens.islandBg))
    }
}

// MARK: router

// Hosts one style and drives summon and collapse from the same reveal tokens
// IslandController (or, floating, PanelController) bumps. Transform and
// opacity only; reduced motion keeps the fade and drops the scale. It also
// reports the surface's laid-out size, which is what the controllers size
// their panel to: a glass surface sizes itself, the panel only contains it.
@MainActor
struct IslandGlassSurface: View {
    let style: IslandStyle
    @ObservedObject var state: AppState
    let client: DaemonClient
    let topInset: CGFloat
    let notchWidth: CGFloat
    @ObservedObject var reveal: IslandReveal
    // The non-notch fallback: D as a free-floating pill under the menu bar.
    var floating = false

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var shapeOpen: CGFloat = 1
    @State private var contentOpacity: Double = 1
    @State private var shakeOffset: CGFloat = 0

    private var notch: CGFloat { max(notchWidth, 180) }

    var body: some View {
        surface
            .fixedSize(horizontal: false, vertical: true)
            .onGeometryChange(for: CGSize.self) { $0.size } action: { size in
                reveal.surfaceSize = size
            }
            .environment(\.islandContentOpacity, contentOpacity)
            .offset(x: shakeOffset)
            .scaleEffect(x: scale.x, y: scale.y, anchor: .top)
            .opacity(style == .b || floating ? Double(shapeOpen) : 1)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .onChange(of: reveal.token) { _, _ in open() }
            .onChange(of: reveal.collapseToken) { _, _ in close() }
            .onChange(of: state.rejectPulse) { _, _ in refusalPulse() }
            .task(id: state.toast) { await autoClearToast() }
    }

    @ViewBuilder private var surface: some View {
        if floating {
            CharacterIsland(state: state, client: client, topInset: 0,
                            notchWidth: notch, attached: false)
        } else {
            switch style {
            case .a:
                FusedIsland(state: state, client: client, topInset: topInset,
                            notchWidth: notch)
            case .b:
                FloatingIsland(state: state, client: client, topInset: topInset)
            case .d:
                CharacterIsland(state: state, client: client, topInset: topInset,
                                notchWidth: notch)
            case .c, .classic:
                PillCardIsland(state: state, client: client, topInset: topInset,
                               notchWidth: notch)
            }
        }
    }

    // Collapsed transform per style: A, C and D retreat into the notch they
    // grow from (D maps its measured size back onto the notch rect); B and
    // the floating pill, which never touch the notch, shrink and fade in place.
    private var scale: (x: CGFloat, y: CGFloat) {
        if reduceMotion { return (1, 1) }
        let p = shapeOpen
        let collapsed: (x: CGFloat, y: CGFloat)
        if floating {
            let s = DesignTokens.characterFloatingCollapsedScale
            collapsed = (s, s)
        } else {
            switch style {
            case .d: collapsed = notchScale
            case .a: collapsed = (0.6, 0.35)
            case .b: collapsed = (0.9, 0.9)
            default: collapsed = (notch / (notch + 2 * DesignTokens.glassEarWidth), 1)
            }
        }
        return (collapsed.x + (1 - collapsed.x) * p, collapsed.y + (1 - collapsed.y) * p)
    }

    private var notchScale: (x: CGFloat, y: CGFloat) {
        let size = reveal.surfaceSize
        guard size.width > 0, size.height > 0, topInset > 0 else { return (0.6, 0.35) }
        return (min(notch / size.width, 1), min(topInset / size.height, 1))
    }

    private func open() {
        var reset = Transaction()
        reset.disablesAnimations = true
        withTransaction(reset) {
            shapeOpen = 0
            contentOpacity = 0
        }
        withAnimation(.spring(DesignTokens.summonSpring)) {
            shapeOpen = 1
        }
        withAnimation(.easeOut(duration: DesignTokens.glassEnterDuration)
            .delay(DesignTokens.contentStaggerDelay)) {
            contentOpacity = 1
        }
    }

    private func close() {
        withAnimation(.spring(DesignTokens.collapseSpring)) {
            shapeOpen = 0
            contentOpacity = 0
        }
    }

    // A refused action nudges the whole surface sideways, as classic does.
    private func refusalPulse() {
        guard !reduceMotion else { return }
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

    // Classic clears the daemon toast from its own view; the glass styles
    // need the same timer or a toast would stay up for the session.
    private func autoClearToast() async {
        guard state.toast != nil else { return }
        try? await Task.sleep(for: .seconds(DesignTokens.toastDuration))
        if !Task.isCancelled { state.toast = nil }
    }
}

private struct IslandContentOpacityKey: EnvironmentKey {
    static let defaultValue: Double = 1
}

extension EnvironmentValues {
    var islandContentOpacity: Double {
        get { self[IslandContentOpacityKey.self] }
        set { self[IslandContentOpacityKey.self] = newValue }
    }
}

// MARK: A  Fused

// The classic silhouette with material depth. The black body is inset by the
// rim width on the sides and bottom; the gap is real Liquid Glass, so the
// rim picks up whatever the desktop shows at the island's edge while the top
// stays flush, unbroken hardware black. A card does not detach: the same
// body grows downward and the card reads below a hairline, then the
// approval buttons, so the full text sits above the decision.
@MainActor
struct FusedIsland: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    let topInset: CGFloat
    let notchWidth: CGFloat

    @Environment(\.islandContentOpacity) private var contentOpacity

    private var readout: IslandReadout { IslandReadout(state: state) }
    private var expanded: Bool { state.card != nil || readout.pendingChip != nil }
    private var ink: IslandInk { .onDark }

    private var shape: UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: 0,
            bottomLeadingRadius: DesignTokens.glassFusedCornerRadius,
            bottomTrailingRadius: DesignTokens.glassFusedCornerRadius,
            topTrailingRadius: 0,
            style: .continuous)
    }

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: topInset)
            content
                .opacity(contentOpacity)
                .padding(.horizontal, 20)
                .padding(.top, 8)
                .padding(.bottom, expanded ? 16 : 12)
        }
        .frame(width: expanded ? DesignTokens.glassFusedWidth
                               : notchWidth + 2 * DesignTokens.islandGrowWidth)
        .background(FusedBody(shape: shape))
        .animation(.spring(DesignTokens.glassMorphSpring), value: expanded)
        .animation(.easeOut(duration: DesignTokens.cardFadeDuration), value: state.card?.id)
    }

    private var content: some View {
        VStack(spacing: 12) {
            if let chip = readout.pendingChip {
                ApprovalPreview(preview: chip.preview, ink: ink, centered: state.card == nil)
                    .padding(.top, 4)
            } else {
                VStack(spacing: 8) {
                    IslandWaveform(meter: state.meter, phase: state.phase)
                    caption
                }
                .frame(minHeight: 50)
            }
            if let card = state.card {
                Hairline(color: ink.hairline)
                IslandCardContent(card: card, ink: ink, onClose: { state.dismissCard() })
                    .transition(.opacity)
            }
            if let chip = readout.pendingChip {
                IslandChipView(chip: chip, client: client, style: .a,
                               centered: state.card == nil)
                    .id(chip.id)
            }
        }
    }

    private var caption: some View {
        HStack(spacing: 8) {
            if let label = readout.runningLabel, !readout.hasToast {
                // The running connector as an etched capsule: well fill plus
                // a hairline, so it reads as a status object, not a button.
                Text(label)
                    .font(.system(size: 11.5, weight: .medium))
                    .foregroundStyle(ink.primary)
                    .padding(.horizontal, 10)
                    .frame(height: 22)
                    .background(Capsule(style: .continuous).fill(ink.well))
                    .overlay(Capsule(style: .continuous).strokeBorder(ink.hairline, lineWidth: 0.5))
            } else {
                ReadoutLabel(readout: readout, ink: ink, phase: state.phase)
            }
            if let cost = readout.cost {
                CostLabel(cost: cost, ink: ink, budget: readout.tone == .budget)
            }
        }
        .frame(maxWidth: 290)
    }
}

// The fused body's layers, all static: the glass rim (or a quiet white rim
// before macOS 26), the black body inset inside it, a faint lift of light at
// the bottom, and a specular hairline that brightens toward the bottom curve
// and is gone before it reaches the notch.
struct FusedBody: View {
    let shape: UnevenRoundedRectangle

    var body: some View {
        let rim = DesignTokens.glassRimWidth
        ZStack {
            rimLayer
            shape.fill(DesignTokens.islandBg)
                .padding([.horizontal, .bottom], rim)
            shape.fill(LinearGradient(
                colors: [Color.white.opacity(0), Color.white.opacity(DesignTokens.glassInnerLightOpacity)],
                startPoint: UnitPoint(x: 0.5, y: 0.45), endPoint: .bottom))
                .padding([.horizontal, .bottom], rim)
            shape.strokeBorder(LinearGradient(
                colors: [Color.white.opacity(0), Color.white.opacity(DesignTokens.glassRimOpacity)],
                startPoint: UnitPoint(x: 0.5, y: 0.25), endPoint: .bottom), lineWidth: 0.75)
                .padding([.horizontal, .bottom], rim)
        }
    }

    @ViewBuilder private var rimLayer: some View {
        if #available(macOS 26, *) {
            Color.clear.glassEffect(.regular, in: shape)
        } else {
            shape.fill(Color.white.opacity(DesignTokens.glassRimOpacity / 2))
        }
    }
}

// MARK: B  Floating

// A Liquid Glass capsule a few points below the notch, never touching it.
// One glass shape for every state: compact states hug their line, a card or
// an approval morphs the same shape into a rounded card, and the header row
// stays put so the eye has an anchor through the morph. Adaptive: light
// glass with label-colored text in light mode, dark glass in dark mode.
@MainActor
struct FloatingIsland: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    let topInset: CGFloat

    @Environment(\.islandContentOpacity) private var contentOpacity

    private var readout: IslandReadout { IslandReadout(state: state) }
    private var expanded: Bool { state.card != nil || readout.pendingChip != nil }
    private var ink: IslandInk { .adaptive }

    private var shape: RoundedRectangle {
        RoundedRectangle(
            cornerRadius: expanded ? DesignTokens.glassCardCornerRadius
                                   : DesignTokens.glassCapsuleHeight / 2,
            style: .continuous)
    }

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: topInset + DesignTokens.glassNotchGap)
            glassBody
        }
    }

    private var glassBody: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
                .frame(height: DesignTokens.glassCapsuleHeight)
            if expanded {
                VStack(alignment: .leading, spacing: 12) {
                    if let chip = readout.pendingChip, state.card == nil {
                        ApprovalPreview(preview: chip.preview, ink: ink)
                    }
                    if let card = state.card {
                        IslandCardContent(card: card, ink: ink, monograms: true, wellBody: true,
                                          onClose: { state.dismissCard() })
                    }
                    if let chip = readout.pendingChip {
                        IslandChipView(chip: chip, client: client, style: .b)
                            .id(chip.id)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 16)
                .transition(.opacity)
            }
        }
        .opacity(contentOpacity)
        .modifier(WidthRule(expanded: expanded))
        .modifier(GlassSurface(shape: shape))
        .animation(.spring(DesignTokens.glassMorphSpring), value: expanded)
        .animation(.easeOut(duration: DesignTokens.cardFadeDuration), value: state.card?.id)
    }

    // The header keeps the live state even when a card is open: the waveform
    // and the spoken line (or the approval word) stay where they were.
    private var header: some View {
        HStack(spacing: 10) {
            GlassWaveform(meter: state.meter, phase: state.phase,
                          tint: ink.waveformTint(for: readout.tone, adaptive: true),
                          scale: 0.66)
            if readout.pendingChip != nil {
                Text("Needs your approval")
                    .font(.system(size: 12.5, weight: .semibold))
                    .foregroundStyle(ink.primary)
                    .lineLimit(1)
            } else {
                ReadoutLabel(readout: readout, ink: ink, phase: state.phase)
            }
            Spacer(minLength: 0)
            if let cost = readout.cost {
                CostLabel(cost: cost, ink: ink, budget: readout.tone == .budget)
            }
        }
        .padding(.horizontal, 16)
    }
}

// B's width rule: compact states hug their content between a floor and a
// cap; expanded states take the fixed card width so text wraps predictably.
private struct WidthRule: ViewModifier {
    let expanded: Bool

    func body(content: Content) -> some View {
        if expanded {
            content.frame(width: DesignTokens.glassCardWidth)
        } else {
            HugWidth(minWidth: 220, maxWidth: 380) { content }
        }
    }
}

// MARK: C  Pill and card

// The notch widens sideways into a black pill at notch height, Dynamic
// Island style: waveform in the left ear, state in the right, nothing under
// the camera. Anything worth reading drops into a smoked glass card below,
// which enters and leaves on its own while the pill stays put.
@MainActor
struct PillCardIsland: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    let topInset: CGFloat
    let notchWidth: CGFloat

    @Environment(\.islandContentOpacity) private var contentOpacity
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private var readout: IslandReadout { IslandReadout(state: state) }
    private var ink: IslandInk { .onDark }

    private enum Drop: Equatable { case none, line, content }

    private var drop: Drop {
        if state.card != nil || readout.pendingChip != nil { return .content }
        if readout.hasToast || readout.tone == .speaking { return .line }
        if readout.tone == .failed, !state.modelLine.isEmpty { return .line }
        return .none
    }

    var body: some View {
        VStack(spacing: DesignTokens.cardGap) {
            pill
            if drop != .none {
                cardView
                    .transition(cardTransition)
            }
        }
        .animation(.easeOut(duration: DesignTokens.glassEnterDuration), value: drop)
        .animation(.easeOut(duration: DesignTokens.cardFadeDuration), value: state.card?.id)
    }

    private var cardTransition: AnyTransition {
        if reduceMotion { return .opacity }
        return .opacity
            .combined(with: .offset(y: -8))
            .combined(with: .scale(scale: 0.97, anchor: .top))
    }

    // MARK: pill

    private var pill: some View {
        HStack(spacing: 0) {
            leftEar
                .frame(width: DesignTokens.glassEarWidth)
            Color.clear.frame(width: notchWidth)
            rightEar
                .frame(width: DesignTokens.glassEarWidth)
        }
        .frame(height: topInset)
        .opacity(contentOpacity)
        .background(
            UnevenRoundedRectangle(
                topLeadingRadius: 0,
                bottomLeadingRadius: DesignTokens.glassPillCornerRadius,
                bottomTrailingRadius: DesignTokens.glassPillCornerRadius,
                topTrailingRadius: 0,
                style: .continuous)
                .fill(DesignTokens.islandBg))
    }

    private var leftEar: some View {
        HStack {
            GlassWaveform(meter: state.meter, phase: state.phase, tint: nil, scale: 0.62)
            Spacer(minLength: 0)
        }
        .padding(.leading, 16)
    }

    private var rightEar: some View {
        HStack(spacing: 5) {
            Spacer(minLength: 0)
            earStatus
        }
        .padding(.trailing, 16)
    }

    @ViewBuilder private var earStatus: some View {
        switch readout.tone {
        case .thinking:
            ThinkingEllipsis(phase: state.phase)
        case .acting:
            Text(readout.runningLabel ?? "Working")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(ink.primary)
                .lineLimit(1)
        case .listening:
            earWord("Listening", DesignTokens.islandAccent)
        case .approval:
            Circle().fill(DesignTokens.islandAmber).frame(width: 5, height: 5)
            earWord("Approve?", DesignTokens.islandAmber)
        case .done:
            Image(systemName: "checkmark")
                .font(.system(size: 10, weight: .bold))
                .foregroundStyle(DesignTokens.islandGreen)
            earWord(state.modelLine.isEmpty ? "Done" : readout.text, DesignTokens.islandGreen)
        case .budget:
            CostLabel(cost: readout.cost ?? "", ink: ink, budget: true)
        default:
            earWord(state.stateLabel, ink.color(for: readout.tone, speech: false))
        }
    }

    private func earWord(_ word: String, _ color: Color) -> some View {
        Text(word)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(color)
            .lineLimit(1)
    }

    // MARK: card

    private var cardShape: RoundedRectangle {
        RoundedRectangle(cornerRadius: drop == .line ? DesignTokens.glassCapsuleHeight / 2
                                                     : DesignTokens.glassCardCornerRadius,
                         style: .continuous)
    }

    private var cardView: some View {
        cardContent
            .opacity(contentOpacity)
            .frame(width: DesignTokens.glassCardWidth)
            .environment(\.colorScheme, .dark)
            .modifier(GlassSurface(shape: cardShape, smoke: DesignTokens.glassSmokeOpacity))
    }

    @ViewBuilder private var cardContent: some View {
        switch drop {
        case .line:
            Text(readout.text)
                .font(.system(size: 13.5))
                .foregroundStyle(readout.tone == .failed ? DesignTokens.islandRed : ink.primary)
                .lineLimit(2)
                .multilineTextAlignment(.center)
                .frame(maxWidth: .infinity)
                .padding(.horizontal, 18)
                .frame(minHeight: DesignTokens.glassCapsuleHeight)
        case .content:
            VStack(alignment: .leading, spacing: 12) {
                if let chip = readout.pendingChip, state.card == nil {
                    ApprovalPreview(preview: chip.preview, ink: ink)
                }
                if let card = state.card {
                    IslandCardContent(card: card, ink: ink, monograms: true,
                                      onClose: { state.dismissCard() })
                }
                if let chip = readout.pendingChip {
                    IslandChipView(chip: chip, client: client, style: .c)
                        .id(chip.id)
                }
            }
            .padding(16)
        case .none:
            EmptyView()
        }
    }
}


// MARK: D  Character

// The app icon come alive, and the live default. The island is the icon's
// black pill hanging from the notch: a black core whose top is the notch
// hardware, a thin glass rim that the desktop shows through, a hairline sheen
// running to the icon's lilac lower edge, and a soft shadow. Two lime eyes
// sit beside the voice line: lime while listening, the lilac-to-pink line
// while Conn speaks, pink eyes when it needs you, and one eye winks shut when
// a turn lands. Personality lives in those few details; text stays white and
// system-set. Every state is static; the wink is one transform and opacity
// change, and nothing ticks but the existing gated waveform.
//
// `attached: false` is the non-notch fallback: the same pill floating under
// the menu bar with all four corners round and the icon's full rim.
@MainActor
struct CharacterIsland: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    let topInset: CGFloat
    let notchWidth: CGFloat
    var attached = true

    @Environment(\.islandContentOpacity) private var contentOpacity
    // The running call whose capsule has outlived the show delay, as in
    // classic: a read that answers inside the delay never flashes a capsule.
    // A zero delay shows it at once (the preview shooter relies on that).
    @State private var capsuleCallID: String?

    private var readout: IslandReadout { IslandReadout(state: state) }
    private var expanded: Bool { state.card != nil || readout.pendingChip != nil }
    private var ink: IslandInk { .character }

    private var width: CGFloat {
        expanded ? DesignTokens.characterExpandedWidth
                 : notchWidth + 2 * DesignTokens.islandGrowWidth
    }

    private var mood: CharacterEyes.Mood {
        switch readout.tone {
        case .listening, .speaking: return .awake
        case .thinking, .acting, .idle: return .focused
        case .done: return .wink
        case .approval: return .alert
        case .failed, .caution, .budget: return .low
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            Color.clear.frame(height: attached ? topInset : 0)
            content
                .opacity(contentOpacity)
                .padding(.horizontal, DesignTokens.characterPaddingH)
                .padding(.top, attached ? DesignTokens.characterPaddingTop
                                        : DesignTokens.characterPaddingBottom)
                .padding(.bottom, DesignTokens.characterPaddingBottom)
        }
        .frame(width: width)
        .background(CharacterBody(attached: attached, topInset: topInset))
        .environment(\.colorScheme, .dark)
        .animation(.spring(DesignTokens.glassMorphSpring), value: expanded)
        .animation(.easeOut(duration: DesignTokens.cardFadeDuration), value: state.card?.id)
        .task(id: runningCallID) { await revealCapsuleAfterDelay() }
    }

    private var content: some View {
        VStack(spacing: DesignTokens.characterSectionGap) {
            VStack(spacing: DesignTokens.characterCaptionGap) {
                VoiceLine(meter: state.meter, phase: state.phase, tone: readout.tone, mood: mood)
                if let chip = readout.pendingChip {
                    ApprovalPreview(preview: chip.preview, ink: ink,
                                    centered: state.card == nil, marker: false)
                } else {
                    caption
                }
                if let warning = state.axWarning {
                    Text(warning)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(DesignTokens.islandAmber)
                        .lineLimit(1)
                        .truncationMode(.tail)
                        .frame(maxWidth: DesignTokens.characterCaptionMaxWidth)
                }
            }
            if let card = state.card {
                Hairline(color: ink.hairline)
                IslandCardContent(card: card, ink: ink, monograms: true, wellBody: true,
                                  onClose: { state.dismissCard() })
                    .transition(.opacity)
            }
            if let chip = readout.pendingChip {
                IslandChipView(chip: chip, client: client, style: .d,
                               centered: state.card == nil)
                    .id(chip.id)
            }
        }
    }

    private var caption: some View {
        HStack(spacing: 8) {
            if let label = readout.runningLabel, !readout.hasToast {
                if capsuleCallID == runningCallID || DesignTokens.toolCapsuleShowDelay <= 0 {
                    runningCapsule(label)
                } else if state.modelLine.isEmpty {
                    ThinkingEllipsis(phase: state.phase, tint: ink.voice)
                } else {
                    ReadoutLabel(readout: readout, ink: ink, phase: state.phase,
                                 showsRunning: false)
                }
            } else {
                ReadoutLabel(readout: readout, ink: ink, phase: state.phase,
                             showsRunning: false)
            }
            if let cost = readout.cost {
                CostLabel(cost: cost, ink: ink, budget: readout.tone == .budget)
            }
            if state.phase == "budget_hold" {
                overrideButton
            }
        }
        .frame(maxWidth: DesignTokens.characterCaptionMaxWidth)
    }

    // The running connector as a quiet status object: a well and a
    // hairline, never a fill that reads as a button.
    private func runningCapsule(_ label: String) -> some View {
        Text(label)
            .font(.system(size: 11.5, weight: .medium))
            .foregroundStyle(ink.primary)
            .lineLimit(1)
            .padding(.horizontal, DesignTokens.characterCapsulePaddingH)
            .frame(height: DesignTokens.characterCapsuleHeight)
            .background(Capsule(style: .continuous).fill(ink.well))
            .overlay(Capsule(style: .continuous).strokeBorder(ink.hairline, lineWidth: 0.5))
            .transition(.opacity)
    }

    // Outline against Approve's fill, as in classic: distinct by construction.
    // Pointer-only like every island control.
    private var overrideButton: some View {
        Button {
            client.send(["type": "override_budget"])
        } label: {
            Text("Override once")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(DesignTokens.islandGold)
                .fixedSize()
                .padding(.horizontal, DesignTokens.characterCapsulePaddingH)
                .frame(height: DesignTokens.characterOverrideHeight)
                .overlay(Capsule(style: .continuous)
                    .strokeBorder(DesignTokens.islandGold, lineWidth: 0.75))
                .contentShape(Capsule(style: .continuous))
        }
        .buttonStyle(IslandPressStyle())
    }

    private var runningCallID: String? {
        state.chips.first(where: { $0.status == "running" })?.id
    }

    private func revealCapsuleAfterDelay() async {
        capsuleCallID = nil
        guard let id = runningCallID else { return }
        try? await Task.sleep(for: .seconds(DesignTokens.toolCapsuleShowDelay))
        if !Task.isCancelled { capsuleCallID = id }
    }
}

// The pill's layers, all static per state: a shadow drawn only outside the
// shape; a glass rim (Liquid Glass on macOS 26, a behind-window material
// before it) that the black core sits inside; attached, a black band over the
// notch so the screen edge stays hardware; and a hairline sheen that runs to
// a lilac lower edge. The core's lower part lets a little of the glass
// through, which is where the island picks up the desktop's light.
struct CharacterBody: View {
    var attached: Bool
    var topInset: CGFloat

    private var radius: CGFloat { DesignTokens.characterCornerRadius }
    private var rim: CGFloat { DesignTokens.characterRimWidth }
    private var rimEdges: Edge.Set { attached ? [.horizontal, .bottom] : .all }

    private func pill(_ r: CGFloat) -> UnevenRoundedRectangle {
        UnevenRoundedRectangle(
            topLeadingRadius: attached ? 0 : r,
            bottomLeadingRadius: r,
            bottomTrailingRadius: r,
            topTrailingRadius: attached ? 0 : r,
            style: .continuous)
    }

    var body: some View {
        let outer = pill(radius)
        // Nested radius: the core's corners sit the rim's width inside.
        let inner = pill(radius - rim)
        ZStack(alignment: .top) {
            CharacterShadow(shape: outer)
            CharacterGlass(shape: outer)
            inner.fill(core).padding(rimEdges, rim)
            if attached {
                notchBand
            }
            inner.strokeBorder(sheen, lineWidth: DesignTokens.characterSheenWidth)
                .padding(rimEdges, rim)
                .mask(sheenMask)
        }
    }

    private var core: LinearGradient {
        LinearGradient(
            stops: [.init(color: Color.black, location: 0),
                    .init(color: Color.black, location: 0.5),
                    .init(color: DesignTokens.characterBodyBottom
                        .opacity(DesignTokens.characterCoreBottomOpacity), location: 1)],
            startPoint: .top, endPoint: .bottom)
    }

    // Covers the rim beside the notch and fades it in just below, so the top
    // edge reads as one piece of hardware with the notch.
    private var notchBand: some View {
        VStack(spacing: 0) {
            Color.black.frame(height: topInset)
            LinearGradient(colors: [Color.black, Color.black.opacity(0)],
                           startPoint: .top, endPoint: .bottom)
                .frame(height: DesignTokens.characterTopFade)
        }
    }

    // The icon's rim: white along the top (floating only), faint down the
    // sides, lilac at the lower edge.
    private var sheen: LinearGradient {
        let top = attached ? 0 : DesignTokens.characterSheenTopOpacity
        return LinearGradient(
            stops: [.init(color: Color.white.opacity(top), location: 0),
                    .init(color: Color.white.opacity(DesignTokens.characterSheenSideOpacity),
                          location: 0.45),
                    .init(color: DesignTokens.iconLilac
                        .opacity(DesignTokens.characterSheenLilacOpacity), location: 1)],
            startPoint: .top, endPoint: .bottom)
    }

    @ViewBuilder private var sheenMask: some View {
        if attached {
            VStack(spacing: 0) {
                Color.clear.frame(height: topInset)
                LinearGradient(colors: [Color.clear, Color.black],
                               startPoint: .top, endPoint: .bottom)
                    .frame(height: DesignTokens.characterTopFade)
                Color.black
            }
        } else {
            Color.black
        }
    }
}

// The rim's material. Liquid Glass where the OS has it; before macOS 26 a
// behind-window HUD material, which (unlike SwiftUI's Material in a
// borderless panel) reliably samples the desktop. Both carry a dark tint so
// the rim reads as dark glass, not a colored outline.
struct CharacterGlass: View {
    let shape: UnevenRoundedRectangle

    var body: some View {
        let tint = Color.black.opacity(DesignTokens.characterGlassTintOpacity)
        if #available(macOS 26, *) {
            Color.clear.glassEffect(.regular.tint(tint), in: shape)
        } else {
            BehindWindowMaterial()
                .clipShape(shape)
                .overlay(shape.fill(tint))
        }
    }
}

// The shadow without the body: a black fill casting a soft shadow, with the
// shape itself cut back out, so the glass rim above samples the desktop and
// not a dark smear under it.
struct CharacterShadow: View {
    let shape: UnevenRoundedRectangle

    var body: some View {
        let radius = DesignTokens.characterShadowRadius
        shape.fill(Color.black)
            .shadow(color: Color.black.opacity(DesignTokens.characterShadowOpacity),
                    radius: radius, x: 0, y: DesignTokens.characterShadowY)
            .mask {
                ZStack {
                    Rectangle().padding(-radius * 3)
                    shape.fill(Color.black).blendMode(.destinationOut)
                }
                .compositingGroup()
            }
            .allowsHitTesting(false)
    }
}

// NSVisualEffectView pinned active: the island's panels never become key,
// so the default follow-the-window state would render the flat inactive
// material forever.
struct BehindWindowMaterial: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = .hudWindow
        view.blendingMode = .behindWindow
        view.state = .active
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {}
}

// Two lime eyes in the icon's proportions, set wide. Awake: open. Focused: narrowed (a vertical scale, not a new shape).
// Wink: the right eye closes into the icon's arc. Alert: pink. Low: dimmed.
// Changes ride one short ease-out. While awake, the voice line's engine
// drives three small live values: openness (a blink at a speech pause),
// lift (Conn's own voice raises them a hair), and glance (the user's voice
// draws them toward the line). All three are transforms only.
struct CharacterEyes: View {
    enum Mood: Equatable { case awake, focused, wink, alert, low }
    let mood: Mood
    var openness: Double = 1
    var lift: CGFloat = 0
    var glance: CGFloat = 0

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var winkClosed = false

    private var color: Color {
        switch mood {
        case .awake, .wink: return DesignTokens.iconLime
        case .focused: return DesignTokens.iconLime.opacity(DesignTokens.characterFocusedEyeOpacity)
        case .alert: return DesignTokens.iconPink
        case .low: return Color.white.opacity(DesignTokens.characterLowEyeOpacity)
        }
    }

    var body: some View {
        HStack(spacing: DesignTokens.characterEyeGap) {
            eye
            ZStack {
                eye
                    .scaleEffect(x: 1, y: winkClosed ? 0.15 : 1)
                    .opacity(winkClosed ? 0 : 1)
                WinkArc()
                    .stroke(color, style: StrokeStyle(lineWidth: DesignTokens.characterWinkStroke,
                                                      lineCap: .round))
                    .frame(width: DesignTokens.characterWinkWidth,
                           height: DesignTokens.characterWinkHeight)
                    .scaleEffect(winkClosed ? 1 : DesignTokens.characterWinkRestScale)
                    .opacity(winkClosed ? 1 : 0)
            }
            .frame(width: DesignTokens.characterEyeWidth)
        }
        .frame(height: DesignTokens.characterEyeHeight)
        .offset(x: glance, y: -lift)
        .animation(.easeOut(duration: DesignTokens.characterWinkDuration), value: mood)
        .onAppear { winkClosed = mood == .wink }
        .onChange(of: mood) { _, next in
            if reduceMotion {
                winkClosed = next == .wink
            } else {
                withAnimation(.easeOut(duration: DesignTokens.characterWinkDuration)) {
                    winkClosed = next == .wink
                }
            }
        }
        .accessibilityHidden(true)
    }

    private var eye: some View {
        Capsule(style: .continuous)
            .fill(color)
            .frame(width: DesignTokens.characterEyeWidth, height: DesignTokens.characterEyeHeight)
            .scaleEffect(x: 1, y: (mood == .focused ? DesignTokens.characterFocusedEyeScale : 1)
                                  * CGFloat(min(max(openness, 0), 1)))
    }
}

// The icon's wink: a shallow upward arc.
struct WinkArc: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.maxY),
                          control: CGPoint(x: rect.midX, y: rect.minY - rect.height * 0.6))
        return path
    }
}

// The face: the eyes and the gated waveform at a finer scale on one
// timeline, recolored by mood: lime while the user speaks, the icon's
// lilac-to-pink gradient while Conn speaks, quieter lilac while it works.
// Outside the live phases the line rests dimmed, so the idle line recedes;
// the eyes never dim with it.
struct VoiceLine: View {
    let meter: VoiceLevelMeter
    let phase: String
    let tone: IslandTone
    var mood: CharacterEyes.Mood = .awake

    private var live: Bool {
        ["listening", "thinking", "acting", "speaking"].contains(phase)
    }

    var body: some View {
        IslandWaveform(meter: meter, phase: phase, tintOverride: Self.tint(for: tone),
                       gradient: Self.gradient(for: tone),
                       scale: DesignTokens.characterVoiceScale,
                       lineOpacity: live ? 1 : DesignTokens.characterRestingVoiceOpacity,
                       face: mood)
            .accessibilityHidden(true)
    }

    static func gradient(for tone: IslandTone) -> [Color]? {
        tone == .speaking ? [DesignTokens.iconLilac, DesignTokens.iconPink] : nil
    }

    static func tint(for tone: IslandTone) -> Color {
        switch tone {
        case .listening, .done: return DesignTokens.iconLime
        case .failed: return DesignTokens.islandRed
        case .budget: return DesignTokens.islandGold
        case .thinking, .acting:
            return DesignTokens.iconLilac.opacity(DesignTokens.characterFocusedEyeOpacity)
        default: return DesignTokens.iconLilac
        }
    }
}

// The live style preference: the menu bar's Island Style choice, persisted so
// a relaunch keeps it. Only the shipped styles are selectable; a stored
// prototype or unknown value falls back to the compiled default.
enum IslandStylePreference {
    static let defaultsKey = "islandStyle"
    static let selectable: [IslandStyle] = [.d, .classic]

    static func load(_ defaults: UserDefaults = .standard) -> IslandStyle? {
        guard let raw = defaults.string(forKey: defaultsKey),
              let style = IslandStyle(rawValue: raw),
              selectable.contains(style) else { return nil }
        return style
    }

    static func save(_ style: IslandStyle, _ defaults: UserDefaults = .standard) {
        defaults.set(style.rawValue, forKey: defaultsKey)
    }
}
