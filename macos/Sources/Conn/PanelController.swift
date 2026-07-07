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

final class ConnPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

@MainActor
final class PanelController: ConnSurface {
    private let panel: ConnPanel
    private let state: AppState
    private var subscriptions = Set<AnyCancellable>()
    private var hideTimer: Timer?

    static let width: CGFloat = 424
    static let height: CGFloat = 196

    init(state: AppState, client: DaemonClient, autoReflectPhases: Bool = true) {
        self.state = state

        let hosting = NSHostingView(
            rootView: PanelWithToast(state: state, client: client).panelChrome())
        hosting.sizingOptions = [.preferredContentSize]
        hosting.frame = NSRect(x: 0, y: 0, width: Self.width, height: Self.height)

        panel = ConnPanel(
            contentRect: NSRect(x: 0, y: 0, width: Self.width, height: Self.height),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        panel.contentView = hosting
        panel.appearance = NSAppearance(named: .aqua)
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary]
        panel.isMovableByWindowBackground = true
        panel.hidesOnDeactivate = false
        panel.animationBehavior = .none

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
        }
    }

    func show() {
        hideTimer?.invalidate()
        guard !panel.isVisible || panel.alphaValue < 1 else { return }
        position()
        let frame = panel.frame
        panel.alphaValue = 0
        panel.setFrameOrigin(NSPoint(x: frame.origin.x, y: frame.origin.y + 6))
        panel.orderFrontRegardless()
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

    private func phaseChanged(_ phase: String) {
        switch phase {
        case "listening", "thinking", "acting", "awaiting_approval",
             "speaking", "budget_hold":
            show()
        case "done":
            hide(after: 1.1)
        case "failed":
            show()
            hide(after: 2.5)
        case "idle":
            hide(after: 0.35)
        default:
            break
        }
    }

    private func position() {
        guard let screen = NSScreen.main else { return }
        let frame = screen.visibleFrame
        let size = panel.frame.size
        let x = frame.midX - size.width / 2
        let y = frame.maxY - frame.height * 0.18 - size.height
        panel.setFrameOrigin(NSPoint(x: x, y: y))
    }
}
