import XCTest
@testable import Conn

final class NativeObservationStoreTests: XCTestCase {
    func testUniqueIdentifierSurvivesRefChangeWithStableLocator() throws {
        let backend = ObservationSequenceBackend()
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(ref: "other-new", path: [0, 1], role: "AXButton",
                                  title: "Other", identifier: "other"),
            NativeObservationNode(ref: "target-new", path: [0, 0], role: "AXButton",
                                  title: "Target", identifier: "stable.target"),
        ]
        let current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: "target-old",
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )

        let resolved = try result.get()
        XCTAssertEqual(resolved.current.ref, "target-new")
        XCTAssertEqual(resolved.resolution, "full_locator")
    }

    func testSemanticTieDoesNotUseNearestFrameAfterReorder() {
        let backend = ObservationSequenceBackend()
        backend.nodes = [
            NativeObservationNode(ref: "target-old", path: [0], role: "AXButton",
                                  title: "Duplicate", frame: NativeRect(x: 10, y: 10, width: 40, height: 20)),
        ]
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(ref: "one", path: [1], role: "AXButton", title: "Duplicate",
                                  frame: NativeRect(x: 11, y: 10, width: 40, height: 20)),
            NativeObservationNode(ref: "two", path: [2], role: "AXButton", title: "Duplicate",
                                  frame: NativeRect(x: 400, y: 400, width: 40, height: 20)),
        ]
        let current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(snapshotID: baseline.snapshotID, ref: "target-old",
                                       identifier: nil, title: nil, bundleID: baseline.bundleID),
            baseline: baseline,
            current: current
        )

        assertFailure(result, equals: .missingTarget)
    }

    func testSiblingReorderRefusesWithoutAStableLocator() {
        let backend = ObservationSequenceBackend()
        backend.nodes = [
            NativeObservationNode(
                ref: "target-old",
                path: [0, 0],
                role: "AXButton",
                title: "Target",
                siblingSignature: "before"
            ),
        ]
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(
                ref: "target-new",
                path: [0, 2],
                role: "AXButton",
                title: "Target",
                siblingSignature: "after"
            ),
        ]
        let current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: "target-old",
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )

        assertFailure(result, equals: .missingTarget)
    }

    func testRiverDuplicateResolvesByCompleteLocator() throws {
        let backend = ObservationSequenceBackend()
        backend.nodes = riverBaselineNodes()
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = riverCurrentNodes()
        let current = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let resolved = try store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: "top-river-old",
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        ).get()

        XCTAssertEqual(resolved.current.ref, "top-river-new")
        XCTAssertEqual(resolved.resolution, "full_locator")
    }

    func testTwoCompleteLocatorsRemainAmbiguous() {
        let backend = ObservationSequenceBackend()
        backend.nodes = [
            NativeObservationNode(
                ref: "old", path: [0, 0], role: "AXLink", title: "RIVER",
                frame: NativeRect(x: 20, y: 10, width: 50, height: 18),
                supportedActions: ["AXPress"], siblingSignature: "same"
            ),
        ]
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = ["one", "two"].map { ref in
            NativeObservationNode(
                ref: ref, path: [0, 0], role: "AXLink", title: "RIVER",
                frame: NativeRect(x: 20, y: 10, width: 50, height: 18),
                supportedActions: ["AXPress"], siblingSignature: "same"
            )
        }
        let current = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID, ref: "old",
                identifier: nil, title: nil, bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )

        assertFailure(result, equals: .ambiguous)
    }

    func testAnonymousGeometryNeverResolves() {
        let backend = ObservationSequenceBackend()
        backend.nodes = [
            NativeObservationNode(
                ref: "old", path: [0], role: "AXGroup",
                frame: NativeRect(x: 0, y: 0, width: 1280, height: 720)
            ),
        ]
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(
                ref: "new", path: [0], role: "AXGroup",
                frame: NativeRect(x: 0, y: 0, width: 1280, height: 720)
            ),
        ]
        let current = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID, ref: "old",
                identifier: nil, title: nil, bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )

        assertFailure(result, equals: .missingTarget)
    }

    func testAppAndSecureTransitionsRefuse() {
        let backend = ObservationSequenceBackend()
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.bundleID = "com.conn.other"
        var current = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        var result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID, ref: "target-old",
                identifier: nil, title: nil, bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )
        assertFailure(result, equals: .staleApplication)

        backend.bundleID = "com.conn.fixture"
        backend.nodes[0].protectedContent = true
        current = store.observe(
            turnID: "turn", observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID, ref: "target-old",
                identifier: nil, title: nil, bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )
        assertFailure(result, equals: .secureTransition)
    }

    private func riverBaselineNodes() -> [NativeObservationNode] {
        [
            NativeObservationNode(ref: "web-old", path: [0], role: "AXWebArea", title: "Techmeme"),
            NativeObservationNode(
                ref: "header-old", parentRef: "web-old", path: [0, 0],
                role: "AXGroup", description: "header navigation"
            ),
            NativeObservationNode(
                ref: "top-river-old", parentRef: "header-old", path: [0, 0, 2],
                role: "AXLink", title: "RIVER",
                frame: NativeRect(x: 499, y: 211.5, width: 49.5, height: 18),
                supportedActions: ["AXPress"], siblingSignature: "header:2"
            ),
        ]
    }

    private func riverCurrentNodes() -> [NativeObservationNode] {
        [
            NativeObservationNode(ref: "web-new", path: [0], role: "AXWebArea", title: "Techmeme"),
            NativeObservationNode(
                ref: "header-new", parentRef: "web-new", path: [0, 0],
                role: "AXGroup", description: "header navigation"
            ),
            NativeObservationNode(
                ref: "top-river-new", parentRef: "header-new", path: [0, 0, 2],
                role: "AXLink", title: "RIVER",
                frame: NativeRect(x: 499, y: 211.5, width: 49.5, height: 18),
                supportedActions: ["AXPress"], siblingSignature: "header:2"
            ),
            NativeObservationNode(
                ref: "secondary", path: [0, 1], role: "AXGroup",
                description: "secondary navigation"
            ),
            NativeObservationNode(
                ref: "secondary-river", parentRef: "secondary", path: [0, 1, 1],
                role: "AXLink", title: "RIVER",
                frame: NativeRect(x: 1210, y: 1030, width: 49.5, height: 18),
                supportedActions: ["AXPress"], siblingSignature: "secondary:1"
            ),
        ]
    }

    func testSemanticReplacementInAnotherContextRefuses() {
        let backend = ObservationSequenceBackend()
        backend.nodes = [
            NativeObservationNode(
                ref: "target-old",
                path: [0, 0],
                role: "AXButton",
                title: "Target",
                frame: NativeRect(x: 10, y: 10, width: 80, height: 24)
            ),
        ]
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(
                ref: "replacement",
                path: [1, 0],
                role: "AXButton",
                title: "Target",
                frame: NativeRect(x: 300, y: 300, width: 80, height: 24)
            ),
        ]
        let current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: "target-old",
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )

        assertFailure(result, equals: .missingTarget)
    }

    func testPathFallbackRefusesChangedSemanticIdentity() {
        let backend = ObservationSequenceBackend()
        backend.nodes = [
            NativeObservationNode(
                ref: "target-old",
                path: [0, 0],
                role: "AXButton",
                title: "Target",
                identifier: "stable.target",
                frame: NativeRect(x: 10, y: 10, width: 80, height: 24),
                siblingSignature: "same"
            ),
        ]
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(
                ref: "replacement",
                path: [0, 0],
                role: "AXButton",
                title: "Replacement",
                identifier: "different.target",
                frame: NativeRect(x: 10, y: 10, width: 80, height: 24),
                siblingSignature: "same"
            ),
        ]
        let current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )

        let result = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: "target-old",
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        )

        assertFailure(result, equals: .missingTarget)
    }

    func testProcessAndWindowChangesInvalidateTarget() {
        let backend = ObservationSequenceBackend()
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.processIdentity = "fixture-2"
        var current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        var result = store.resolve(
            target: NativeActionTarget(snapshotID: baseline.snapshotID, ref: "target-old",
                                       identifier: nil, title: nil, bundleID: baseline.bundleID),
            baseline: baseline,
            current: current
        )
        assertFailure(result, equals: .staleProcess)

        backend.processIdentity = "fixture-1"
        backend.windowID = 2
        current = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        result = store.resolve(
            target: NativeActionTarget(snapshotID: baseline.snapshotID, ref: "target-old",
                                       identifier: nil, title: nil, bundleID: baseline.bundleID),
            baseline: baseline,
            current: current
        )
        assertFailure(result, equals: .staleWindow)
    }

    private func assertFailure(
        _ result: Result<NativeResolvedTarget, NativeResolutionError>,
        equals expected: NativeResolutionError,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        switch result {
        case .success:
            XCTFail("expected \(expected)", file: file, line: line)
        case .failure(let error):
            XCTAssertEqual(error, expected, file: file, line: line)
        }
    }
}

private final class ObservationSequenceBackend: NativeSemanticBackend, @unchecked Sendable {
    var nodes = [
        NativeObservationNode(ref: "target-old", path: [0, 0], role: "AXButton",
                              title: "Target", identifier: "stable.target"),
        NativeObservationNode(ref: "other-old", path: [0, 1], role: "AXButton",
                              title: "Other", identifier: "other"),
    ]
    var processIdentity = "fixture-1"
    var windowID: UInt32 = 1
    var bundleID = "com.conn.fixture"

    func capture(
        turnID: String,
        observationEpoch: Int,
        query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        var result = NativeCapturedObservation.fixture(
            turnID: turnID,
            observationEpoch: observationEpoch,
            nodes: nodes,
            windowID: windowID
        )
        result.processStartIdentity = processIdentity
        result.bundleID = bundleID
        return result
    }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        NativeDispatchResult(state: .notDispatched, nativeError: "test")
    }
}
