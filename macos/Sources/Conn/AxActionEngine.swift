import AppKit
import ApplicationServices

/// Answers the daemon's ax_action requests (T4). TCC binds grants to the
/// binary, so the app, which holds the Accessibility grant, posts the key
/// chords and presses the menu items the daemon's python identity cannot.
/// The daemon publishes ax_action, this engine performs it, DaemonClient
/// ships back ax_action_result. Only computer_hotkey and app_menu ride this
/// lane; the grounded lane (snapshot, click, type) stays daemon-side.
enum AxActionEngine {
    private static let axMessagingTimeoutSeconds: Float = 1.0

    /// Mirrors the daemon's MODIFIER_FLAGS table in tools/ax_input.py.
    static let modifierFlags: [String: CGEventFlags] = [
        "cmd": .maskCommand,
        "shift": .maskShift,
        "alt": .maskAlternate,
        "ctrl": .maskControl,
    ]

    /// Mirrors the daemon's KEYCODES table in tools/ax_input.py; the two
    /// lanes must accept the same combos or fallback behavior diverges.
    static let keyCodes: [String: CGKeyCode] = [
        "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E, "f": 0x03,
        "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26, "k": 0x28, "l": 0x25,
        "m": 0x2E, "n": 0x2D, "o": 0x1F, "p": 0x23, "q": 0x0C, "r": 0x0F,
        "s": 0x01, "t": 0x11, "u": 0x20, "v": 0x09, "w": 0x0D, "x": 0x07,
        "y": 0x10, "z": 0x06,
        "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
        "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
        "return": 0x24, "tab": 0x30, "space": 0x31, "escape": 0x35,
        "delete": 0x33, "up": 0x7E, "down": 0x7D, "left": 0x7B, "right": 0x7C,
    ]

    /// Returns the result payload for ax_action_result, nil on failure or
    /// unknown op (the daemon treats nil as lane failure and reports it;
    /// it never silently retries on the other lane).
    static func perform(op: String, params: [String: Any]) -> Any? {
        switch op {
        case "posting_capability":
            return AXIsProcessTrusted()
        case "key_chord":
            guard let keys = params["keys"] as? [String] else { return nil }
            return postKeyChord(keys) ? true : nil
        case "press_menu_path":
            guard let pid = params["pid"] as? Int,
                  let titles = params["titles"] as? [String] else { return nil }
            return pressMenuPath(pid: pid_t(pid), titles: titles)
        case "menu_tree":
            guard let pid = params["pid"] as? Int else { return nil }
            let maxDepth = params["max_depth"] as? Int ?? 8
            return menuTree(pid: pid_t(pid), maxDepth: maxDepth)
        default:
            return nil
        }
    }

    // MARK: key chords

    static func chord(from keys: [String]) -> (CGKeyCode, CGEventFlags)? {
        var flags: CGEventFlags = []
        var primary: CGKeyCode?
        for key in keys {
            if let modifier = modifierFlags[key] {
                flags.insert(modifier)
            } else if let code = keyCodes[key], primary == nil {
                primary = code
            } else {
                return nil
            }
        }
        guard let code = primary else { return nil }
        return (code, flags)
    }

    private static func postKeyChord(_ keys: [String]) -> Bool {
        guard AXIsProcessTrusted(), let (code, flags) = chord(from: keys) else { return false }
        guard let down = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false)
        else { return false }
        down.flags = flags
        up.flags = flags
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return true
    }

    // MARK: menus

    private static func pressMenuPath(pid: pid_t, titles: [String]) -> Bool {
        guard AXIsProcessTrusted(), let menuBar = menuBarElement(pid: pid) else { return false }
        var element = menuBar
        for title in titles {
            guard let match = children(of: element).first(where: { self.title(of: $0) == title })
            else { return false }
            element = match
        }
        return AXUIElementPerformAction(element, kAXPressAction as CFString) == .success
    }

    private static func menuTree(pid: pid_t, maxDepth: Int) -> [String: Any]? {
        guard AXIsProcessTrusted(), let menuBar = menuBarElement(pid: pid) else { return nil }
        return serialize(menuBar, depth: maxDepth)
    }

    private static func serialize(_ element: AXUIElement, depth: Int) -> [String: Any] {
        var node: [String: Any] = ["title": title(of: element) ?? ""]
        if depth > 0 {
            node["children"] = children(of: element).map { serialize($0, depth: depth - 1) }
        }
        return node
    }

    private static func menuBarElement(pid: pid_t) -> AXUIElement? {
        let app = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(app, axMessagingTimeoutSeconds)
        guard let bar = copyAttribute(app, kAXMenuBarAttribute) else { return nil }
        return unsafeDowncast(bar, to: AXUIElement.self)
    }

    private static func children(of element: AXUIElement) -> [AXUIElement] {
        guard let value = copyAttribute(element, kAXChildrenAttribute) as? [AnyObject] else {
            return []
        }
        return value.map { unsafeDowncast($0, to: AXUIElement.self) }
    }

    private static func title(of element: AXUIElement) -> String? {
        copyAttribute(element, kAXTitleAttribute) as? String
    }

    private static func copyAttribute(_ element: AXUIElement, _ attribute: String) -> AnyObject? {
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else {
            return nil
        }
        return value
    }
}
