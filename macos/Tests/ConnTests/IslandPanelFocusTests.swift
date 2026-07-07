import AppKit
import XCTest
@testable import Conn

// The island never takes keyboard focus, in any state. This pins the panel
// class overrides and the style mask the spec requires; the pointer-only
// approval invariant depends on both (a stray Return keystroke must have no
// window to land in).
@MainActor
final class IslandPanelFocusTests: XCTestCase {
    func testIslandPanelNeverBecomesKeyOrMain() {
        let panel = IslandPanel(
            contentRect: NSRect(x: 0, y: 0, width: 320, height: 100),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: true)
        XCTAssertFalse(panel.canBecomeKey)
        XCTAssertFalse(panel.canBecomeMain)
        XCTAssertTrue(panel.styleMask.contains(.nonactivatingPanel))
        XCTAssertTrue(panel.styleMask.contains(.borderless))
    }
}
