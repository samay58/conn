import XCTest
@testable import Conn

// The card rules from the daemon's wire contract (src/conn/cards.py): a
// "card" message shows a card, the same id replaces it in place, card_clear
// removes it, a non-persisting card retires on the next push-to-talk or after
// cardLinger (plus reading time per row), a verified send after the shorter
// cardSettledLinger, and a persisting card stays until replaced, cleared, or
// closed locally.
@MainActor
final class IslandCardTests: XCTestCase {
    private func cardMessage(_ id: String, kind: String = "list", state: String = "",
                             persist: Bool = false, rows: Int = 2) -> [String: Any] {
        [
            "type": "card",
            "card": [
                "id": id, "kind": kind, "title": "Waiting on you", "subtitle": "\(rows) people",
                "rows": (0..<rows).map { ["title": "Person \($0)", "detail": "Email · 2d", "note": "Ask \($0)"] },
                "body": "Hey, here is the text.", "state": state, "persist": persist,
            ] as [String: Any],
        ]
    }

    private func phase(_ name: String) -> [String: Any] {
        ["type": "state", "phase": name]
    }

    // Shrinks the lingers for the duration of a test; the store is shared
    // process state, so restore on exit.
    private func withLingers(_ linger: Double, settled: Double, _ body: () async throws -> Void) async rethrows {
        let store = DesignTokens.current
        let old = (store.cardLinger, store.cardSettledLinger, store.cardLingerPerRow)
        store.cardLinger = linger
        store.cardSettledLinger = settled
        store.cardLingerPerRow = 0
        defer { (store.cardLinger, store.cardSettledLinger, store.cardLingerPerRow) = old }
        try await body()
    }

    private func spin(_ seconds: Double) async {
        try? await Task.sleep(for: .seconds(seconds))
    }

    func testCardMessageShowsAParsedCard() {
        let state = AppState()
        state.apply(cardMessage("list:people", rows: 3))
        XCTAssertEqual(state.card?.id, "list:people")
        XCTAssertEqual(state.card?.kind, .list)
        XCTAssertEqual(state.card?.rows.count, 3)
        XCTAssertEqual(state.card?.rows.first?.detail, "Email · 2d")
    }

    func testMalformedCardIsIgnored() {
        let state = AppState()
        state.apply(["type": "card", "card": ["id": "x", "kind": "poster", "title": "t"]])
        XCTAssertNil(state.card)
        state.apply(["type": "card", "card": ["kind": "list", "title": "no id"]])
        XCTAssertNil(state.card)
    }

    func testRowsAreCappedAtEight() {
        let state = AppState()
        state.apply(cardMessage("list:today", rows: 12))
        XCTAssertEqual(state.card?.rows.count, IslandCard.maxRows)
        XCTAssertEqual(IslandCard.maxRows, 8)
    }

    func testSameIdReplacesInPlace() {
        let state = AppState()
        state.apply(cardMessage("reply", kind: "reply", state: "draft", persist: true))
        state.apply(cardMessage("reply", kind: "reply", state: "approve", persist: true))
        XCTAssertEqual(state.card?.id, "reply")
        XCTAssertEqual(state.card?.state, "approve")
    }

    func testCardClearRemovesTheCard() {
        let state = AppState()
        state.apply(cardMessage("reply", kind: "reply", state: "draft", persist: true))
        state.apply(["type": "card_clear"])
        XCTAssertNil(state.card)
    }

    func testPushToTalkRetiresOnlyNonPersistingCards() {
        let state = AppState()
        state.apply(phase("speaking"))
        state.apply(cardMessage("list:people"))
        state.apply(phase("listening"))
        XCTAssertNil(state.card, "a non-persisting card retires on the next push-to-talk")

        state.apply(phase("speaking"))
        state.apply(cardMessage("reply", kind: "reply", state: "draft", persist: true))
        state.apply(phase("listening"))
        XCTAssertEqual(state.card?.id, "reply", "a persisting card survives push-to-talk")
    }

    func testDismissIsLocal() {
        let state = AppState()
        state.apply(cardMessage("reply", kind: "reply", state: "draft", persist: true))
        state.dismissCard()
        XCTAssertNil(state.card)
    }

    func testNonPersistingCardRetiresAfterLinger() async {
        await withLingers(0.05, settled: 0.05) {
            let state = AppState()
            state.apply(cardMessage("list:people"))
            XCTAssertNotNil(state.card)
            await spin(0.25)
            XCTAssertNil(state.card)
        }
    }

    func testPersistingCardOutlivesTheLinger() async {
        await withLingers(0.05, settled: 0.05) {
            let state = AppState()
            state.apply(cardMessage("reply", kind: "reply", state: "draft", persist: true))
            await spin(0.25)
            XCTAssertEqual(state.card?.id, "reply")
        }
    }

    func testSettledReplyUsesTheShorterLinger() async {
        await withLingers(5, settled: 0.05) {
            let state = AppState()
            state.apply(cardMessage("reply", kind: "reply", state: "sent", persist: false))
            XCTAssertTrue(state.card?.isSettledReply ?? false)
            await spin(0.25)
            XCTAssertNil(state.card, "a verified send fades after the short linger")
        }
    }

    func testAFailedSendStaysLongEnoughToRead() async {
        await withLingers(5, settled: 0.05) {
            for outcome in ["held", "unconfirmed"] {
                let state = AppState()
                state.apply(cardMessage("reply", kind: "reply", state: outcome, persist: false))
                await spin(0.25)
                XCTAssertEqual(state.card?.state, outcome, "not sent and not confirmed are news, not a glance")
            }
        }
    }

    func testAListEarnsReadingTimePerRow() {
        let state = AppState()
        state.apply(cardMessage("list:people", rows: 2))
        let short = state.card?.linger ?? 0
        state.apply(cardMessage("list:people", rows: 8))
        XCTAssertGreaterThan(state.card?.linger ?? 0, short)
    }


    func testAReplacedCardKeepsItsOwnTimer() async {
        await withLingers(0.15, settled: 0.15) {
            let state = AppState()
            state.apply(cardMessage("list:people"))
            await spin(0.1)
            // The replacement persists: the first card's timer must not clear it.
            state.apply(cardMessage("reply", kind: "reply", state: "draft", persist: true))
            await spin(0.3)
            XCTAssertEqual(state.card?.id, "reply")
        }
    }

    func testDaemonLossClearsTheCard() {
        let state = AppState()
        state.apply(cardMessage("reply", kind: "reply", state: "approve", persist: true))
        state.markDaemonLost()
        XCTAssertNil(state.card)
    }
}
