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
    }

    func summon(chipOpen: Bool = false) {
        cancelScheduledCollapse()
        orderOutTimer?.invalidate()
        orderOutTimer = nil
        let wasHidden = !panel.isVisible
        panel.setFrame(geometry.expandedFrame(chipOpen: chipOpen), display: false)
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
            collapse()
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
            Task { @MainActor in self?.collapse() }
        }
    }

    private func cancelScheduledCollapse() {
        collapseTimer?.invalidate()
        collapseTimer = nil
    }
}
