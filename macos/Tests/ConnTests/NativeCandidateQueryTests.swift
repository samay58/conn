import XCTest
@testable import Conn

final class NativeCandidateQueryTests: XCTestCase {
    func testQueryParserCarriesEveryBoundedField() {
        let query = NativeObservationQuery.parse([
            "bundle_id": "org.mozilla.firefox",
            "pid": 42,
            "search": "play video",
            "search_terms": ["play", "video"],
            "expected_roles": ["AXButton"],
            "expected_actions": ["AXPress"],
            "scope": "descendant",
            "ancestor_ref": "player",
            "result_limit": 99,
            "include_menu": true,
            "denied_bundles": ["com.apple.keychainaccess"],
        ])

        XCTAssertEqual(query.bundleID, "org.mozilla.firefox")
        XCTAssertEqual(query.pid, 42)
        XCTAssertEqual(query.searchTerms, ["play", "video"])
        XCTAssertEqual(query.expectedRoles, Set(["AXButton"]))
        XCTAssertEqual(query.expectedActions, Set(["AXPress"]))
        XCTAssertEqual(query.scope, .descendant)
        XCTAssertEqual(query.ancestorRef, "player")
        XCTAssertEqual(query.resultLimit, 20)
        XCTAssertTrue(query.includeMenu)
        XCTAssertEqual(query.deniedBundles, Set(["com.apple.keychainaccess"]))
    }

    func testSearchRanksNamedMatchesAndReturnsNoTree() async throws {
        let backend = CandidateBackend(nodes: [
            NativeObservationNode(
                ref: "window", path: [0], role: "AXWindow", title: "Video"
            ),
            NativeObservationNode(
                ref: "pause", parentRef: "window", path: [0, 0],
                role: "AXButton", title: "Pause video",
                supportedActions: ["AXPress"]
            ),
            NativeObservationNode(
                ref: "other", parentRef: "window", path: [0, 1],
                role: "AXButton", title: "Share",
                supportedActions: ["AXPress"]
            ),
        ])
        let engine = NativeSemanticActionEngine(backend: backend)

        let rawResponse = await engine.perform(op: "observe", params: [
            "turn_id": "turn",
            "observation_epoch": 3,
            "query": ["search_terms": ["pause", "video"]],
        ])
        let response = try XCTUnwrap(rawResponse)

        XCTAssertNil(response["nodes"])
        let candidates = try XCTUnwrap(response["candidates"] as? [[String: Any]])
        XCTAssertEqual(candidates.count, 1)
        XCTAssertEqual(candidates[0]["ref"] as? String, "pause")
        XCTAssertEqual(candidates[0]["label"] as? String, "Pause video")
        XCTAssertFalse((candidates[0]["score_reasons"] as? [String] ?? []).isEmpty)
        let descriptor = try XCTUnwrap(candidates[0]["descriptor"] as? [String: Any])
        XCTAssertEqual(descriptor["display"] as? String, "Pause video in Video")
    }

    func testRoleActionAndDescendantFiltersCompose() {
        let observation = candidateObservation(nodes: [
            NativeObservationNode(ref: "left", path: [0], role: "AXGroup", title: "Left"),
            NativeObservationNode(ref: "right", path: [1], role: "AXGroup", title: "Right"),
            NativeObservationNode(
                ref: "play", parentRef: "left", path: [0, 0], role: "AXButton",
                title: "Play", supportedActions: ["AXPress"]
            ),
            NativeObservationNode(
                ref: "wrong-action", parentRef: "left", path: [0, 1], role: "AXButton",
                title: "Play", supportedActions: ["AXShowMenu"]
            ),
            NativeObservationNode(
                ref: "wrong-scope", parentRef: "right", path: [1, 0], role: "AXButton",
                title: "Play", supportedActions: ["AXPress"]
            ),
        ])
        let result = NativeObservationIndex().candidates(
            in: observation,
            query: NativeObservationQuery.parse([
                "search_terms": ["play"],
                "expected_roles": ["AXButton"],
                "expected_actions": ["AXPress"],
                "scope": "descendant",
                "ancestor_ref": "left",
            ])
        )

        XCTAssertEqual(result.candidates.map(\.ref), ["play"])
    }

    func testAnonymousFallbackReturnsExplicitZeroMatches() {
        let nodes = (0..<34).map { index in
            NativeObservationNode(
                ref: "group-\(index)", path: [index], role: "AXGroup",
                frame: NativeRect(x: 0, y: 0, width: 1280, height: 720)
            )
        }
        let result = NativeObservationIndex().candidates(
            in: candidateObservation(nodes: nodes),
            query: NativeObservationQuery.parse(["search_terms": ["play"]])
        )

        XCTAssertTrue(result.candidates.isEmpty)
        XCTAssertEqual(result.dictionary["candidate_count"] as? Int, 0)
    }

    func testCandidateCountAndSerializedBytesStayBounded() {
        let nodes = (0..<80).map { index in
            NativeObservationNode(
                ref: "button-\(index)", path: [index], role: "AXButton",
                title: "Play video \(index) " + String(repeating: "x", count: 2_000),
                supportedActions: ["AXPress"]
            )
        }
        let result = NativeObservationIndex().candidates(
            in: candidateObservation(nodes: nodes),
            query: NativeObservationQuery.parse([
                "search_terms": ["play"], "result_limit": 20,
            ])
        )

        XCTAssertLessThanOrEqual(result.candidates.count, 20)
        XCTAssertLessThanOrEqual(result.serializedBytes, result.byteLimit)
        XCTAssertTrue(result.truncated)
    }

    func testCandidateDropsPlatformActionsOutsideModelWireGrammar() throws {
        let result = NativeObservationIndex().candidates(
            in: candidateObservation(nodes: [
                NativeObservationNode(
                    ref: "editor", role: "AXTextArea", title: "conn lab seed",
                    supportedActions: [
                        "AXConfirm", "AX Text Operation", "AXPress", "AX",
                    ]
                ),
            ]),
            query: NativeObservationQuery.parse([
                "search_terms": ["conn", "lab", "seed"],
                "expected_roles": ["AXTextArea"],
            ])
        )

        let candidate = try XCTUnwrap(result.candidates.first)
        XCTAssertEqual(candidate.supportedActions, ["AXConfirm", "AXPress"])
        let descriptor = try XCTUnwrap(
            candidate.descriptor["supported_actions"] as? [String]
        )
        XCTAssertEqual(descriptor, ["AXConfirm", "AXPress"])
    }

    private func candidateObservation(
        nodes: [NativeObservationNode]
    ) -> NativeCapturedObservation {
        NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 3, nodes: nodes
        )
    }
}

private final class CandidateBackend: NativeSemanticBackend {
    let nodes: [NativeObservationNode]

    init(nodes: [NativeObservationNode]) {
        self.nodes = nodes
    }

    func capture(
        turnID: String,
        observationEpoch: Int,
        query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        NativeCapturedObservation.fixture(
            turnID: turnID,
            observationEpoch: observationEpoch,
            nodes: nodes
        )
    }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        NativeDispatchResult(state: .notDispatched, nativeError: nil)
    }
}
