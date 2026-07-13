import XCTest
@testable import Conn

final class NativeObservationStoreTests: XCTestCase {
    func testUniqueIdentifierSurvivesRefAndSiblingReorder() throws {
        let backend = ObservationSequenceBackend()
        let store = NativeObservationStore(backend: backend)
        let baseline = store.observe(
            turnID: "turn",
            observationEpoch: 1,
            query: NativeObservationQuery.parse(nil)
        )
        backend.nodes = [
            NativeObservationNode(ref: "other-new", path: [0, 0], role: "AXButton",
                                  title: "Other", identifier: "other"),
            NativeObservationNode(ref: "target-new", path: [0, 1], role: "AXButton",
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
        XCTAssertEqual(resolved.resolution, "identifier")
    }

    func testSemanticTieRefusesInsteadOfUsingNearestFrame() {
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

        assertFailure(result, equals: .ambiguous)
    }

    func testSemanticIdentitySurvivesSiblingReorderWithoutIdentifier() throws {
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

        let resolved = try store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: "target-old",
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: current
        ).get()

        XCTAssertEqual(resolved.current.ref, "target-new")
        XCTAssertEqual(resolved.resolution, "semantic_fingerprint")
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
