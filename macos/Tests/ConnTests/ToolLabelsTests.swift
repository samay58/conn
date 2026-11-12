import XCTest
@testable import Conn

final class ToolLabelsTests: XCTestCase {
    func testBuiltInToolsUseTheTable() {
        XCTAssertEqual(ToolLabels.label(for: "phoenix_search", preview: "Search vault: bike"), "Searching the vault")
        XCTAssertEqual(ToolLabels.label(for: "browser_navigate"), "Opening page")
        XCTAssertEqual(ToolLabels.label(for: "shortcuts_run", preview: "Run shortcut: Log Water"), "Running shortcut")
    }

    func testConnectorToolsUseTheDaemonPreview() {
        XCTAssertEqual(ToolLabels.label(for: "phoenix_today", preview: "Checking today"), "Checking today")
        XCTAssertEqual(ToolLabels.label(for: "granola_search_meetings", preview: "Searching Granola"), "Searching Granola")
    }

    func testNoPreviewFallsBackToReadableName() {
        XCTAssertEqual(ToolLabels.label(for: "granola_search_meetings", preview: "  "), "granola search meetings")
    }
}
