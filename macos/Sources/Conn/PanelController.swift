import AppKit
import Combine
import SwiftUI

private struct PanelWithToast: View {
    @ObservedObject var state: AppState
    let client: DaemonClient

    var body: some View {
        VStack(spacing: 0) {
            PanelView(state: state, client: client)
            if let toast = state.toast {
                Text(toast)
                    .foregroundStyle(Color.inkTertiary)
            }
        }
    }
}

// The non-notch surface. Classic keeps the frozen light panel; every other
// style renders the Character pill floating under the menu bar, cards
// included, with room around it for its shadow.
private struct PanelRoot: View {
    @ObservedObject var state: AppState
    let client: DaemonClient
    @ObservedObject var reveal: IslandReveal
    @ObservedObject private var tokens = DesignTokens.current

    var body: some View {
        if tokens.islandStyle == .classic {
            PanelWithToast(state: state, client: client).panelChrome()
        } else {
            IslandView(state: state, client: client, topInset: 0, reveal: reveal,
                       notchWidth: PanelController.floatingNotchWidth, floating: true)
                .padding(.top, DesignTokens.characterFloatingTopGap)
                .padding(.horizontal, DesignTokens.characterPanelMargin)
                .padding(.bottom, DesignTokens.characterPanelBottomMargin)
        }
    }
}

final class ConnPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class PanelController: ConnSurface {
    private let panel: ConnPanel
    private let hosting: NSHostingView<PanelRoot>
    private let state: AppState
    private let reveal = IslandReveal()
    private let fitter: GlassPanelFitter
    private var subscriptions = Set<AnyCancellable>()
    private var hideTimer: Timer?
    // Read from the token store's emitted value, since @Published fires
    // before the stored property changes.
    private var style = DesignTokens.islandStyle

    static let width: CGFloat = 424
    static let height: CGFloat = 196
    // The floating pill's compact width is sized as if around a notch this
    // wide, so it matches the island on a notch display.
    static let floatingNotchWidth: CGFloat = 200

    init(state: AppState, client: DaemonClient, autoReflectPhases: Bool = true) {
        self.state = state

        hosting = NSHostingView(
            rootView: PanelRoot(state: state, client: client, reveal: reveal))
        hosting.frame = NSRect(x: 0, y: 0, width: Self.width, height: Self.height)

        panel = ConnPanel(
            contentRect: NSRect(x: 0, y: 0, width: Self.width, height: Self.height),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        panel.contentView = hosting
        panel.appearance = NSAppearance(named: .aqua)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.hidesOnDeactivate = false
        panel.animationBehavior = .none
        fitter = GlassPanelFitter(panel: panel)
        applyStyleChrome()

        // The panel never takes keyboard focus. Approvals are deliberate
        // clicks; a stolen Return keystroke must not be able to approve
        // an action.

        if autoReflectPhases {
            state.$phase
                .removeDuplicates()
                .sink { [weak self] phase in self?.phaseChanged(phase) }
                .store(in: &subscriptions)

            state.$chips
                .map { $0.contains(where: \.pending) }
                .removeDuplicates()
                .sink { [weak self] pending in if pending { self?.show() } }
                .store(in: &subscriptions)

            // Cards render only in the floating pill: a card summons it, and
            // its retire lets a finished turn hide.
            state.$card
                .map { $0?.id }
                .removeDuplicates()
                .dropFirst()
                .sink { [weak self] id in self?.cardChanged(present: id != nil) }
                .store(in: &subscriptions)
        }

        reveal.$surfaceSize
            .removeDuplicates()
            .sink { [weak self] _ in
                guard let self, self.style != .classic, self.panel.isVisible else { return }
                self.fitter.fit({ [weak self] in self?.glassFrame ?? .zero }, immediately: false)
            }
            .store(in: &subscriptions)

        DesignTokens.current.$islandStyle
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] next in
                guard let self else { return }
                self.style = next
                self.applyStyleChrome()
                if self.panel.isVisible { self.position() }
            }
            .store(in: &subscriptions)
    }

    // Classic sizes itself from its SwiftUI content and wears the window
    // shadow, movable by its background as before. The pill is sized by the
    // controller from its measured surface, draws its own shadow, and stays
    // pinned under the menu bar.
    private func applyStyleChrome() {
        fitter.cancel()
        if style == .classic {
            hosting.sizingOptions = [.preferredContentSize]
            panel.hasShadow = true
            panel.isMovableByWindowBackground = true
        } else {
            hosting.sizingOptions = []
            panel.hasShadow = false
            panel.isMovableByWindowBackground = false
        }
    }

    private var glassFrame: CGRect {
        guard let screen = NSScreen.main else { return panel.frame }
        let visible = screen.visibleFrame
        let measured = reveal.surfaceSize
        let surface = measured.width > 0 && measured.height > 0
            ? measured
            : IslandGeometry.surfaceEstimate(notchHeight: 0)
        let width = surface.width + 2 * DesignTokens.characterPanelMargin
        let height = surface.height + DesignTokens.characterFloatingTopGap
            + DesignTokens.characterPanelBottomMargin
        return NSRect(x: visible.midX - width / 2, y: visible.maxY - height,
                      width: width, height: height)
    }

    func show() {
        hideTimer?.invalidate()
        guard !panel.isVisible || panel.alphaValue < 1 else { return }
        position()
        let frame = panel.frame
        panel.alphaValue = 0
        panel.setFrameOrigin(NSPoint(x: frame.origin.x, y: frame.origin.y + 6))
        panel.orderFrontRegardless()
        if style != .classic { reveal.token &+= 1 }
        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.16
            ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().alphaValue = 1
            panel.animator().setFrameOrigin(frame.origin)
        }
    }

    func hide() {
        hide(after: 0)
    }

    func hide(after delay: TimeInterval) {
        hideTimer?.invalidate()
        hideTimer = Timer.scheduledTimer(withTimeInterval: max(delay, 0.01),
                                         repeats: false) { [weak self] _ in
            Task { @MainActor in self?.fadeOut() }
        }
    }

    func toggle() {
        panel.isVisible ? hide() : show()
    }

    private func fadeOut() {
        guard panel.isVisible else { return }
        fitter.cancel()
        if style != .classic { reveal.collapseToken &+= 1 }
        NSAnimationContext.runAnimationGroup({ ctx in
            ctx.duration = 0.18
            ctx.timingFunction = CAMediaTimingFunction(name: .easeIn)
            panel.animator().alphaValue = 0
        }, completionHandler: { [weak self] in
            Task { @MainActor in
                self?.panel.orderOut(nil)
                self?.panel.alphaValue = 1
            }
        })
    }

    // A card on screen holds the panel up through a finished turn; the
    // card's retire (or its close button) releases it in cardChanged.
    private var holdsForCard: Bool {
        style != .classic && state.card != nil
    }

    private func cardChanged(present: Bool) {
        guard style != .classic else { return }
        if present {
            show()
        } else if ["idle", "done", "failed"].contains(state.phase) {
            hide(after: DesignTokens.cardFadeDuration)
        }
    }

    private func phaseChanged(_ phase: String) {
        switch phase {
        case "listening", "thinking", "acting", "awaiting_approval",
             "speaking", "budget_hold":
            show()
        case "done":
            if !holdsForCard { hide(after: 1.1) }
        case "failed":
            show()
            if !holdsForCard { hide(after: 2.5) }
        case "idle":
            if !holdsForCard { hide(after: 0.35) }
        default:
            break
        }
    }

    private func position() {
        if style != .classic {
            fitter.fit({ [weak self] in self?.glassFrame ?? .zero }, immediately: true)
            return
        }
        guard let screen = NSScreen.main else { return }
        let frame = screen.visibleFrame
        let size = panel.frame.size
        let x = frame.midX - size.width / 2
        let y = frame.maxY - frame.height * 0.18 - size.height
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }
}
