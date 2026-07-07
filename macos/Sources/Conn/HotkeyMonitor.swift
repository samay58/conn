import AppKit

final class HotkeyMonitor {
    private var monitors: [Any] = []
    private var held = false
    var onDown: (() -> Void)?
    var onUp: (() -> Void)?

    static let rightOptionKeyCode: UInt16 = 61

    var trusted: Bool { AXIsProcessTrusted() }

    func promptForTrust() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        AXIsProcessTrustedWithOptions(options as CFDictionary)
    }

    func start() {
        let handle: (NSEvent) -> Void = { [weak self] event in
            guard let self, event.keyCode == Self.rightOptionKeyCode else { return }
            let down = event.modifierFlags.contains(.option)
            if down, !self.held {
                self.held = true
                self.onDown?()
            } else if !down, self.held {
                self.held = false
                self.onUp?()
            }
        }
        if let global = NSEvent.addGlobalMonitorForEvents(matching: .flagsChanged,
                                                          handler: handle) {
            monitors.append(global)
        }
        if let local = NSEvent.addLocalMonitorForEvents(matching: .flagsChanged,
                                                        handler: { handle($0); return $0 }) {
            monitors.append(local)
        }
    }
}
