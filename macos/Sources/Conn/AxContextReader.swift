import AppKit
import ApplicationServices

/// Answers the daemon's ax_read requests (S2). TCC binds Accessibility to
/// the binary: the grant lives on Conn.app, not on the python daemon it
/// spawns, so the app performs the read and ships the result back over the
/// websocket. Reads are passive AX queries; no Conn surface takes focus.
enum AxContextReader {
    /// Cap per-request AX messaging so a hung target app cannot stall the
    /// read past the daemon's bridge timeout.
    private static let axMessagingTimeoutSeconds: Float = 1.0

    static func read() -> [String: Any] {
        guard let app = frontmostRegularApp() else {
            return payload(app: nil, bundleId: nil, windowTitle: nil,
                           selectedText: nil, trusted: AXIsProcessTrusted())
        }
        let name = app.localizedName
        let bundleId = app.bundleIdentifier
        guard AXIsProcessTrusted() else {
            return payload(app: name, bundleId: bundleId, windowTitle: nil,
                           selectedText: nil, trusted: false)
        }
        let element = AXUIElementCreateApplication(app.processIdentifier)
        AXUIElementSetMessagingTimeout(element, axMessagingTimeoutSeconds)
        return payload(app: name, bundleId: bundleId,
                       windowTitle: focusedWindowTitle(of: element),
                       selectedText: selectedText(of: element),
                       trusted: true)
    }

    /// The app pumps a real runloop, so NSWorkspace is fresh here; the
    /// activation-policy filter still applies so accessory overlays (the
    /// Kaku class) never win.
    private static func frontmostRegularApp() -> NSRunningApplication? {
        if let app = NSWorkspace.shared.frontmostApplication,
           app.activationPolicy == .regular {
            return app
        }
        return NSWorkspace.shared.runningApplications.first {
            $0.isActive && $0.activationPolicy == .regular
        }
    }

    private static func focusedWindowTitle(of element: AXUIElement) -> String? {
        guard let window = copyAttribute(element, kAXFocusedWindowAttribute) else { return nil }
        let windowElement = unsafeDowncast(window, to: AXUIElement.self)
        return copyAttribute(windowElement, kAXTitleAttribute) as? String
    }

    private static func selectedText(of element: AXUIElement) -> String? {
        guard let focused = copyAttribute(element, kAXFocusedUIElementAttribute) else { return nil }
        let focusedElement = unsafeDowncast(focused, to: AXUIElement.self)
        guard let text = copyAttribute(focusedElement, kAXSelectedTextAttribute) as? String,
              !text.isEmpty else { return nil }
        return String(text.prefix(2000))
    }

    private static func copyAttribute(_ element: AXUIElement, _ attribute: String) -> AnyObject? {
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(element, attribute as CFString, &value) == .success else {
            return nil
        }
        return value
    }

    static func payload(app: String?, bundleId: String?, windowTitle: String?,
                        selectedText: String?, trusted: Bool) -> [String: Any] {
        [
            "app": app ?? NSNull(),
            "bundle_id": bundleId ?? NSNull(),
            "window_title": windowTitle ?? NSNull(),
            "selected_text": selectedText ?? NSNull(),
            "accessibility": trusted ? "granted" : "not_granted",
        ]
    }
}
