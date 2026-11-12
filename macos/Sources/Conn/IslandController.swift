import AppKit
import Combine
import SwiftUI

final class IslandPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class IslandController: ConnSurface {
    private let panel: IslandPanel
    private let state: AppState
    private let geometry: IslandGeometry
    private let reveal = IslandReveal()
    private var subscriptions = Set<AnyCancellable>()
    private var collapseTimer: Timer?
    private var orderOutTimer: Timer?
    private var isCollapsing = false
    private var chipOpen = false

    init(state: AppState, client: DaemonClient, geometry: IslandGeometry) {
        self.state = state
        self.geometry = geometry

        let hosting = NSHostingView(rootView: IslandView(
            state: state,
            client: client,
            topInset: geometry.notchHeight,
            collapsedScale: geometry.collapsedScale(),
            reveal: reveal))
        hosting.wantsLayer = true
        hosting.layer?.backgroundColor = NSColor.clear.cgColor

        let frame = geometry.expandedFrame(chipOpen: false)
        panel = IslandPanel(
            contentRect: frame,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        panel.contentView = hosting
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.level = .screenSaver
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = false
        panel.hidesOnDeactivate = false
        panel.animationBehavior = .none

        // The island never takes keyboard focus (enforced by IslandPanel's
        // canBecomeKey / canBecomeMain overrides above). Approvals are
        // deliberate clicks; a stolen Return keystroke must not be able to
        // approve an action.

        state.$phase
            .removeDuplicates()
            .sink { [weak self] phase in self?.apply(phase: phase) }
            .store(in: &subscriptions)

        // T2 grant preflight: a lane going dark summons the island long
        // enough to read the warning, then retreats; mid-session it rides
        // the already-open island. Same dwell as a failure banner.
        state.$axWarning
            .removeDuplicates()
            .compactMap { $0 }
            .sink { [weak self] _ in
                guard let self else { return }
                self.summon()
                if self.state.phase == "idle" {
                    self.scheduleCollapse(after: DesignTokens.failedCollapseDelay)
                }
            }
            .store(in: &subscriptions)

        // Cards: a card arriving summons the island (even after the turn
        // ended); its measured height grows the panel; a card leaving lets a
        // finished turn collapse, which phase-driven collapses wait for while
        // a card is on screen.
        state.$card
            .map { $0?.id }
            .removeDuplicates()
            .dropFirst()
            .sink { [weak self] id in self?.cardChanged(present: id != nil) }
            .store(in: &subscriptions)
        reveal.$cardHeight
            .removeDuplicates()
            .sink { [weak self] _ in
                guard let self, self.panel.isVisible, !self.isCollapsing else { return }
                self.summon(chipOpen: self.chipOpen)
            }
            .store(in: &subscriptions)
    }

    private var cardHeight: CGFloat {
        state.card == nil ? 0 : reveal.cardHeight
    }

    private func cardChanged(present: Bool) {
        if present {
            summon(chipOpen: chipOpen)
        } else if ["idle", "done", "failed"].contains(state.phase) {
            collapse()
        } else if panel.isVisible {
            summon(chipOpen: chipOpen)
        }
    }

    // Phase-driven collapses hold while a card is showing; the card's own
    // retire (or its close button) releases them through cardChanged.
    private func collapseUnlessCard() {
        guard state.card == nil else { return }
        collapse()
    }

    func summon(chipOpen: Bool = false) {
        cancelScheduledCollapse()
        orderOutTimer?.invalidate()
        orderOutTimer = nil
        let wasHidden = !panel.isVisible
        self.chipOpen = chipOpen
        let target = geometry.expandedFrame(chipOpen: chipOpen, cardHeight: cardHeight)
        reveal.collapsedScale = geometry.collapsedScale(chipOpen: chipOpen)
        if !wasHidden && !isCollapsing && panel.frame != target {
            // Mid-session frame change: the chip row opening or closing. The
            // shape grows and retreats on the chip-open curve, matching the
            // row's SwiftUI layout animation inside IslandView.
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = DesignTokens.chipOpenDuration
                ctx.timingFunction = CAMediaTimingFunction(name: .easeOut)
                panel.animator().setFrame(target, display: true)
            }
        } else {
            panel.setFrame(target, display: false)
        }
        panel.orderFrontRegardless()
        // Replay the breathe-open only when the island arrives from the notch
        // (or was mid-retreat), not on every in-session phase tick.
        if wasHidden || isCollapsing {
            isCollapsing = false
            reveal.token &+= 1
        }
    }

    func show() {
        summon()
    }

    func collapse() {
        cancelScheduledCollapse()
        guard panel.isVisible, !isCollapsing else { return }
        isCollapsing = true
        reveal.collapseToken &+= 1
        // The retreat is staggered (height first, width one lead behind), so
        // the panel stays up until the trailing width spring has settled too.
        orderOutTimer = Timer.scheduledTimer(
            withTimeInterval: DesignTokens.collapseSpring.settlingDuration + DesignTokens.squashWidthLead,
            repeats: false
        ) { [weak self] _ in
            Task { @MainActor in
                guard let self, self.isCollapsing else { return }
                self.isCollapsing = false
                self.panel.orderOut(nil)
            }
        }
    }

    func hide() {
        collapse()
    }

    func apply(phase: String) {
        switch phase {
        case "idle":
            collapseUnlessCard()
        case "awaiting_approval":
            summon(chipOpen: true)
        case "done":
            summon()
            scheduleCollapse(after: DesignTokens.doneSettleDuration + DesignTokens.doneCollapseDelay)
        case "failed":
            summon()
            scheduleCollapse(after: DesignTokens.failedCollapseDelay)
        case "listening", "thinking", "acting", "speaking", "budget_hold":
            summon()
        default:
            break
        }
    }

    private func scheduleCollapse(after delay: TimeInterval) {
        cancelScheduledCollapse()
        collapseTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            Task { @MainActor in self?.collapseUnlessCard() }
        }
    }

    private func cancelScheduledCollapse() {
        collapseTimer?.invalidate()
        collapseTimer = nil
    }
}
