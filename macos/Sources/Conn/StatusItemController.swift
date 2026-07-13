import AppKit
import Combine

@MainActor
final class StatusItemController: NSObject, NSMenuDelegate {
    private let item: NSStatusItem
    private let state: AppState
    private let client: DaemonClient
    private let hotkey: HotkeyMonitor
    private let panelProvider: () -> PanelController
    private var subscriptions = Set<AnyCancellable>()

    init(state: AppState, client: DaemonClient, hotkey: HotkeyMonitor,
         panelProvider: @escaping () -> PanelController) {
        self.state = state
        self.client = client
        self.hotkey = hotkey
        self.panelProvider = panelProvider
        self.item = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        super.init()

        item.button?.image = NSImage(systemSymbolName: "waveform",
                                     accessibilityDescription: "Conn")
        item.menu = buildMenu()

        state.$phase
            .removeDuplicates()
            .sink { [weak self] phase in self?.reflect(phase) }
            .store(in: &subscriptions)
    }

    private func reflect(_ phase: String) {
        let symbol: String
        switch phase {
        case "listening": symbol = "waveform.circle.fill"
        case "thinking", "acting": symbol = "waveform.circle"
        case "awaiting_approval": symbol = "exclamationmark.circle"
        case "failed", "budget_hold": symbol = "exclamationmark.triangle"
        default: symbol = "waveform"
        }
        item.button?.image = NSImage(systemSymbolName: symbol,
                                     accessibilityDescription: "Conn: \(phase)")
    }

    private func buildMenu() -> NSMenu {
        let menu = NSMenu()
        menu.delegate = self

        let status = NSMenuItem(title: "Conn", action: nil, keyEquivalent: "")
        status.tag = 1
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(.separator())

        menu.addItem(makeItem("Show Panel", #selector(showPanel), "p"))
        menu.addItem(makeItem("New Session", #selector(newSession), "n"))
        menu.addItem(makeItem("Stop (Belay)", #selector(stop), "."))
        menu.addItem(.separator())

        let trust = makeItem("Enable Global Hotkey…", #selector(enableHotkey), "")
        trust.tag = 2
        menu.addItem(trust)
        let binding = NSMenuItem(
            title: "Push-to-Talk Key",
            action: nil,
            keyEquivalent: ""
        )
        binding.tag = 3
        let choices = NSMenu()
        for choice in HotkeyMonitor.Binding.allCases {
            let choiceItem = makeItem(choice.title, #selector(selectHotkey), "")
            choiceItem.representedObject = choice.rawValue
            choices.addItem(choiceItem)
        }
        binding.submenu = choices
        menu.addItem(binding)
        menu.addItem(makeItem("Open Console", #selector(openConsole), ""))
        menu.addItem(makeItem("Report Last Command", #selector(reportLastCommand), "r"))
        menu.addItem(.separator())
        menu.addItem(makeItem("Quit Conn", #selector(quit), "q"))
        return menu
    }

    private func makeItem(_ title: String, _ action: Selector,
                          _ key: String) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        return item
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        let mode = state.live ? "live" : "demo"
        let conn = state.connected ? mode : "daemon offline"
        menu.item(withTag: 1)?.title =
            "Conn \(conn) · \(state.stateLabel) · $\(String(format: "%.3f", state.spentUSD))"
        menu.item(withTag: 2)?.isHidden = AXIsProcessTrusted()
        menu.item(withTag: 3)?.title = "Push-to-Talk Key: \(hotkey.binding.title)"
        for item in menu.item(withTag: 3)?.submenu?.items ?? [] {
            item.state = item.representedObject as? String == hotkey.binding.rawValue
                ? .on : .off
        }
    }

    @objc private func showPanel() { panelProvider().show() }
    @objc private func newSession() { client.send(["type": "new_session"]) }
    @objc private func stop() { client.send(["type": "stop"]) }

    @objc private func enableHotkey() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        AXIsProcessTrustedWithOptions(options as CFDictionary)
    }

    @objc private func selectHotkey(_ sender: NSMenuItem) {
        guard let raw = sender.representedObject as? String,
              let binding = HotkeyMonitor.Binding(rawValue: raw) else { return }
        hotkey.setBinding(binding)
    }

    @objc private func openConsole() {
        NSWorkspace.shared.open(URL(string: "http://127.0.0.1:8787")!)
    }

    @objc private func reportLastCommand() {
        client.send(["type": "report_last_command"])
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }
}
