import XCTest
@testable import Conn

@MainActor
final class DaemonLossStateTests: XCTestCase {
    func testDaemonLossShowsReconnectingAndDropsStaleChips() {
        let state = AppState()
        state.apply([
            "type": "state",
            "phase": "awaiting_approval",
            "connected": true,
            "ledger": [[
                "call_id": "c1", "name": "browser_open",
                "preview": "Open example.com", "status": "proposed",
            ]],
        ])
        state.userLine = "open example"
        state.modelLine = "Opening"
        state.toast = "Receipt saved"
        state.level = 0.6
        state.navigationGranted = true
        XCTAssertNotNil(state.pendingChip)

        state.markDaemonLost()

        XCTAssertEqual(state.phase, "failed")
        XCTAssertFalse(state.connected)
        XCTAssertTrue(state.chips.isEmpty)
        XCTAssertNil(state.pendingChip)
        XCTAssertNil(state.toast)
        XCTAssertEqual(state.level, 0)
        XCTAssertFalse(state.navigationGranted)
        XCTAssertEqual(state.islandPrimaryText, "Reconnecting")
    }

    func testNextDaemonStateReplacesTheLossPhase() {
        let state = AppState()
        state.markDaemonLost()
        state.apply(["type": "state", "phase": "idle", "connected": true])
        XCTAssertEqual(state.phase, "idle")
        XCTAssertTrue(state.connected)
    }
}
