import XCTest
@testable import Conn

final class NativeTransactionExecutorTests: XCTestCase {
    func testMissingOrConsumedPlanReturnsFinalNotDispatchedReceipt() async {
        let backend = SemanticFixtureBackend()
        let store = NativeObservationStore(backend: backend)
        let compiler = NativeActionCompiler(
            applications: NativeApplicationResolver()
        )
        let evaluator = NativeEffectEvaluator(store: store)
        let executor = NativeTransactionExecutor(
            backend: backend,
            store: store,
            compiler: compiler,
            evaluator: evaluator,
            executionInterlock: nil
        )

        let receipt = await executor.execute([
            "plan_fingerprint": "consumed",
        ], plan: nil)

        XCTAssertEqual(receipt["outcome"] as? String, "failed")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["reason_code"] as? String, "stale_plan")
        XCTAssertEqual(receipt["retry_safe"] as? Bool, true)
    }

    func testFocusedFindWitnessRequiresOneUniqueNonsecureFindField() {
        let evaluator = NativeEffectEvaluator(
            store: NativeObservationStore(backend: SemanticFixtureBackend())
        )
        let predicate = NativeEffectPredicate(
            kind: "unique_focused_find_field_appears"
        )
        let before = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1, nodes: []
        )
        let searchLabel = NativeObservationNode(
            ref: "search-label", role: "AXGroup", title: "Search"
        )
        let search = NativeObservationNode(
            ref: "search", parentRef: searchLabel.ref, role: "AXTextField",
            focused: true
        )
        var after = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1, nodes: [searchLabel, search]
        )
        after.focusedElementRef = search.ref
        let bound = evaluator.bindBaselines(
            NativeEffectGroup(mode: "all", predicates: [predicate]),
            in: before
        )

        XCTAssertEqual(bound.predicates.first?.baseline, "0")
        XCTAssertTrue(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: after
        ))

        let duplicate = NativeObservationNode(
            ref: "other", role: "AXSearchField", focused: true
        )
        var ambiguous = after
        ambiguous.nodes.append(duplicate)
        XCTAssertFalse(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: ambiguous
        ))

        let secure = NativeObservationNode(
            ref: "password", role: "AXSecureTextField", focused: true,
            protectedContent: true
        )
        var protected = after
        protected.nodes = [secure]
        protected.focusedElementRef = secure.ref
        XCTAssertFalse(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: protected
        ))

        let unknownText = NativeObservationNode(
            ref: "unknown", role: "AXTextField", title: "Notes", focused: true
        )
        var unknown = after
        unknown.nodes = [unknownText]
        unknown.focusedElementRef = unknownText.ref
        XCTAssertFalse(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: unknown
        ))
    }

    func testPageStatusWitnessRequiresOneChangedStatusBeforeAndAfter() {
        let evaluator = NativeEffectEvaluator(
            store: NativeObservationStore(backend: SemanticFixtureBackend())
        )
        let predicate = NativeEffectPredicate(
            kind: "unique_page_status_changes", expected: "next"
        )
        let before = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1,
            nodes: [NativeObservationNode(
                ref: "page-status-before", role: "AXStaticText",
                redactedValue: "Page 1 of 3", valueType: "string"
            )]
        )
        let changed = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1,
            nodes: [NativeObservationNode(
                ref: "page-status-after", role: "AXStaticText",
                redactedValue: "Page 2 of 3", valueType: "string"
            )]
        )
        let bound = evaluator.bindBaselines(
            NativeEffectGroup(mode: "all", predicates: [predicate]),
            in: before
        )

        XCTAssertTrue(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: changed
        ))

        var unchanged = changed
        unchanged.nodes[0].redactedValue = "Page 1 of 3"
        XCTAssertFalse(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: unchanged
        ))

        var wrongDirection = changed
        wrongDirection.nodes[0].redactedValue = "Page 0 of 3"
        let pageTwo = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1,
            nodes: [NativeObservationNode(
                ref: "page-status-before", role: "AXStaticText",
                redactedValue: "Page 2 of 3", valueType: "string"
            )]
        )
        wrongDirection.nodes[0].redactedValue = "Page 1 of 3"
        let pageTwoBound = evaluator.bindBaselines(
            NativeEffectGroup(mode: "all", predicates: [predicate]),
            in: pageTwo
        )
        XCTAssertFalse(evaluator.predicateMatches(
            pageTwoBound.predicates[0], before: pageTwo, after: wrongDirection
        ))

        var totalOnly = changed
        totalOnly.nodes[0].redactedValue = "Page 1 of 4"
        XCTAssertFalse(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: totalOnly
        ))

        var ambiguous = changed
        ambiguous.nodes.append(NativeObservationNode(
            ref: "other-status", role: "AXStaticText",
            redactedValue: "Page 3 of 3", valueType: "string"
        ))
        XCTAssertFalse(evaluator.predicateMatches(
            bound.predicates[0], before: before, after: ambiguous
        ))
    }
}
