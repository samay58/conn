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

    func testASecondResponseReplacesTheFirstLine() {
        let state = AppState()
        state.apply(["type": "transcript_delta", "text": "Opening Safari ", "starts_response": true])
        state.apply(["type": "transcript_delta", "text": "now.", "starts_response": false])
        XCTAssertEqual(state.modelLine, "Opening Safari now.")
        state.apply(["type": "transcript_delta", "text": "Done.", "starts_response": true])
        XCTAssertEqual(state.modelLine, "Done.")
        // An older daemon without the flag still appends.
        state.apply(["type": "transcript_delta", "text": " Safari is open."])
        XCTAssertEqual(state.modelLine, "Done. Safari is open.")
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
