import XCTest
@testable import Conn

@MainActor
final class ActionOutcomeRenderingTests: XCTestCase {
    func testBudgetCapUsesRaisedDefaultAndAcceptsDaemonValue() {
        let state = AppState()
        XCTAssertEqual(state.capUSD, 5.0)

        state.apply([
            "type": "hello",
            "cap_usd": 7.5,
        ])

        XCTAssertEqual(state.capUSD, 7.5)
    }

    func testDispatchOnlyNeverRendersDoneOrGreenSuccess() {
        let state = AppState()
        state.modelLine = "The tab is open"
        state.apply([
            "type": "state",
            "phase": "done",
            "connected": true,
            "last_action_outcome": "dispatch_only",
            "ledger": [[
                "call_id": "c1",
                "name": "app_menu",
                "preview": "Open tab",
                "status": "unverified",
            ]],
        ])

        XCTAssertEqual(state.stateLabel, "Sent, not confirmed")
        XCTAssertEqual(state.islandPrimaryText, "Sent, not confirmed")
        XCTAssertFalse(state.actionVerified)
        XCTAssertFalse(state.chips[0].ok)
    }

    func testVerifiedActionRendersDone() {
        let state = AppState()
        state.apply([
            "type": "state",
            "phase": "done",
            "last_action_outcome": "verified",
            "ledger": [],
        ])

        XCTAssertEqual(state.stateLabel, "Done")
        XCTAssertTrue(state.actionVerified)
    }

    func testNoEffectAndAmbiguousRenderDidNotRun() {
        for outcome in ["no_effect", "ambiguous", "failed", "blocked"] {
            let state = AppState()
            state.modelLine = "Done"
            state.apply([
                "type": "state",
                "phase": "done",
                "last_action_outcome": outcome,
                "ledger": [],
            ])
            XCTAssertEqual(state.stateLabel, "Did not run")
            XCTAssertEqual(state.islandPrimaryText, "Did not run")
            XCTAssertFalse(state.actionVerified)
        }
    }
}
