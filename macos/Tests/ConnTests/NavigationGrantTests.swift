import AppKit
import XCTest
@testable import Conn

final class NavigationGrantTests: XCTestCase {
    @MainActor
    func testNavigationStateChangesOnlyAfterDaemonEcho() {
        let state = AppState()

        XCTAssertFalse(state.navigationGranted)
        XCTAssertFalse(state.navigationSuspended)
        XCTAssertEqual(state.navigationGeneration, 0)
        XCTAssertEqual(state.navigationGuidance, "")

        state.apply([
            "type": "state",
            "navigation": [
                "granted": true,
                "active": true,
                "suspended": false,
                "generation": 7,
                "guidance": "Open the Conn menu and click Navigation control: Off.",
            ],
        ])

        XCTAssertTrue(state.navigationGranted)
        XCTAssertFalse(state.navigationSuspended)
        XCTAssertEqual(state.navigationGeneration, 7)
        XCTAssertEqual(
            state.navigationGuidance,
            "Open the Conn menu and click Navigation control: Off."
        )
        XCTAssertEqual(
            StatusItemController.navigationGuidanceTitle(
                guidance: state.navigationGuidance,
                connected: true,
                granted: false,
                suspended: false
            ),
            state.navigationGuidance
        )
        XCTAssertNil(StatusItemController.navigationGuidanceTitle(
            guidance: state.navigationGuidance,
            connected: true,
            granted: true,
            suspended: false
        ))
    }

    @MainActor
    func testStatusMenuGrantRejectsKeyboardAndProgrammaticActivation() {
        XCTAssertEqual(
            StatusItemController.navigationCommand(
                eventType: .leftMouseUp, currentlyGranted: false
            )?["type"] as? String,
            "navigation_grant"
        )
        XCTAssertEqual(
            StatusItemController.navigationCommand(
                eventType: .leftMouseUp, currentlyGranted: true
            )?["type"] as? String,
            "navigation_revoke"
        )
        XCTAssertEqual(
            StatusItemController.navigationCommand(
                eventType: .leftMouseDown, currentlyGranted: false
            )?["type"] as? String,
            "navigation_grant"
        )
        XCTAssertNil(StatusItemController.navigationCommand(
            eventType: .keyDown, currentlyGranted: false
        ))
        XCTAssertNil(StatusItemController.navigationCommand(
            eventType: nil, currentlyGranted: false
        ))
    }

    func testExecutionInterlockRequiresCurrentConnectionAndGeneration() {
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-a")

        XCTAssertTrue(interlock.accept(
            connectionID: "connection-a", generation: 4, suspended: false
        ))
        XCTAssertEqual(
            interlock.check(connectionID: "connection-a", generation: 4), .allowed
        )
        XCTAssertEqual(
            interlock.check(connectionID: "connection-a", generation: 3), .staleGrant
        )
        XCTAssertEqual(
            interlock.check(connectionID: "connection-b", generation: 4), .staleConnection
        )
    }

    func testOldConnectionCannotApplyStateOrClearSuspension() {
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-old")
        interlock.accept(connectionID: "connection-old", generation: 2, suspended: false)
        interlock.beginConnection("connection-new")
        interlock.suspend()

        XCTAssertFalse(interlock.accept(
            connectionID: "connection-old", generation: 3, suspended: false
        ))
        XCTAssertEqual(
            interlock.check(connectionID: "connection-new", generation: 3), .suspended
        )
    }

    func testLockAndSleepSuspendSynchronously() {
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-a")
        interlock.accept(connectionID: "connection-a", generation: 8, suspended: false)

        interlock.suspend()

        XCTAssertEqual(
            interlock.check(connectionID: "connection-a", generation: 8), .suspended
        )
    }

    func testCompilerEffectClassMatrixIsNarrow() throws {
        let compiler = NativeActionCompiler(applications: NativeApplicationResolver())
        let baseline = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1, nodes: []
        )

        let cases: [(String, [String: Any], NativeEffectClass)] = [
            ("open", [:], .reversibleNavigation),
            ("switch", [:], .reversibleNavigation),
            ("navigate", ["url": "https://example.com"], .reversibleNavigation),
            ("scroll", [:], .reversibleNavigation),
            ("set_text", ["text": "hello", "submit": false], .reversibleNavigation),
            ("set_text", ["text": "hello", "submit": true], .consequential),
            ("clipboard_write", ["text": "hello"], .consequential),
            ("key_chord", ["keys": ["cmd", "t"]], .reversibleNavigation),
            ("key_chord", ["keys": ["find"]], .reversibleNavigation),
            ("key_chord", ["keys": ["return"]], .consequential),
            ("menu", ["menu_path": ["File", "New Note"]], .consequential),
        ]

        for (operation, payload, expected) in cases {
            let request = try XCTUnwrap(request(operation: operation, payload: payload))
            XCTAssertEqual(
                compiler.effectClass(request: request, target: nil, baseline: baseline),
                expected,
                operation
            )
        }
    }

    func testDestructiveAndSecureTermsOverrideReversibleRoles() throws {
        let compiler = NativeActionCompiler(applications: NativeApplicationResolver())
        let request = try XCTUnwrap(request(operation: "press"))
        let baseline = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1, nodes: []
        )
        let destructive = NativeObservationNode(
            ref: "delete", role: "AXRadioButton", title: "Delete tab",
            supportedActions: ["AXPress"]
        )
        let secure = NativeObservationNode(
            ref: "password", role: "AXSecureTextField", title: "Play",
            supportedActions: ["AXPress"]
        )

        XCTAssertEqual(
            compiler.effectClass(request: request, target: destructive, baseline: baseline),
            .destructive
        )
        XCTAssertEqual(
            compiler.effectClass(request: request, target: secure, baseline: baseline),
            .secureOrDenied
        )
    }

    func testFixedNavigationKeyRefusesFocusedSecureField() throws {
        let compiler = NativeActionCompiler(applications: NativeApplicationResolver())
        let request = try XCTUnwrap(request(
            operation: "key_chord",
            payload: ["keys": ["space"]]
        ))
        let secure = NativeObservationNode(
            ref: "password",
            role: "AXSecureTextField",
            title: "Password",
            focused: true,
            protectedContent: true
        )
        var baseline = NativeCapturedObservation.fixture(
            turnID: "turn",
            observationEpoch: 1,
            nodes: [secure]
        )
        baseline.focusedElementRef = secure.ref

        XCTAssertEqual(
            compiler.effectClass(request: request, target: nil, baseline: baseline),
            .secureOrDenied
        )
    }

    func testAnonymousControlStaysUnknown() throws {
        let compiler = NativeActionCompiler(applications: NativeApplicationResolver())
        let request = try XCTUnwrap(request(operation: "press"))
        let target = NativeObservationNode(
            ref: "anonymous", role: "AXButton", supportedActions: ["AXPress"]
        )
        let baseline = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1, nodes: [target]
        )

        XCTAssertEqual(
            compiler.effectClass(request: request, target: target, baseline: baseline),
            .unknown
        )
    }

    func testTodayButtonIsReversibleTemporalNavigation() throws {
        let compiler = NativeActionCompiler(applications: NativeApplicationResolver())
        let request = try XCTUnwrap(request(
            operation: "press", payload: ["goal": "Go to today"]
        ))
        let target = NativeObservationNode(
            ref: "today", role: "AXButton", title: "Today",
            supportedActions: ["AXPress"]
        )
        let baseline = NativeCapturedObservation.fixture(
            turnID: "turn", observationEpoch: 1, nodes: [target]
        )

        XCTAssertEqual(
            compiler.effectClass(request: request, target: target, baseline: baseline),
            .reversibleNavigation
        )
    }

    func testChangedGrantGenerationBlocksBeforeNativeDispatch() async throws {
        let backend = SemanticFixtureBackend()
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-a")
        interlock.accept(connectionID: "connection-a", generation: 7, suspended: false)
        let engine = NativeSemanticActionEngine(
            backend: backend, executionInterlock: interlock
        )
        let plan = await engine.prepare(prepareParams(generation: 7))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        interlock.accept(connectionID: "connection-a", generation: 8, suspended: false)
        let receipt = await engine.execute(executeParams(
            fingerprint: fingerprint, generation: 8
        ))

        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["native_error"] as? String, "stale_grant")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testSuspensionBlocksBeforeNativeDispatch() async throws {
        let backend = SemanticFixtureBackend()
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-a")
        interlock.accept(connectionID: "connection-a", generation: 7, suspended: false)
        let engine = NativeSemanticActionEngine(
            backend: backend, executionInterlock: interlock
        )
        let plan = await engine.prepare(prepareParams(generation: 7))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        interlock.suspend()
        let receipt = await engine.execute(executeParams(
            fingerprint: fingerprint, generation: 7
        ))

        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["native_error"] as? String, "execution_suspended")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testFreshMatchingGenerationCanDispatch() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-a")
        interlock.accept(connectionID: "connection-a", generation: 9, suspended: false)
        let engine = NativeSemanticActionEngine(
            backend: backend, executionInterlock: interlock
        )
        let plan = await engine.prepare(prepareParams(generation: 9))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute(executeParams(
            fingerprint: fingerprint, generation: 9
        ))

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.dispatchCount, 1)
    }

    private func request(
        operation: String, payload: [String: Any] = [:]
    ) -> NativeActionRequest? {
        NativeActionRequest.parse([
            "turn_id": "turn",
            "response_epoch": 1,
            "observation_epoch": 1,
            "navigation_generation": 1,
            "execution_connection_id": "connection-a",
            "request": [
                "operation": operation,
                "target": [:],
                "payload": payload,
                "effect_class": "reversible_navigation",
            ],
        ])
    }

    private func prepareParams(generation: Int) -> [String: Any] {
        [
            "turn_id": "turn",
            "response_epoch": 1,
            "observation_epoch": 1,
            "navigation_generation": generation,
            "execution_connection_id": "connection-a",
            "request": [
                "operation": "press",
                "target": ["ref": "immediate"],
                "payload": [:],
                "desired_effect": [
                    "mode": "all",
                    "predicates": [[
                        "kind": "element_attribute_changes",
                        "ref": "immediate",
                        "attribute": "value",
                    ]],
                ],
                "strategy_ceiling": "semantic_only",
            ],
        ]
    }

    private func executeParams(fingerprint: String, generation: Int) -> [String: Any] {
        [
            "plan_fingerprint": fingerprint,
            "turn_id": "turn",
            "response_epoch": 1,
            "observation_epoch": 1,
            "navigation_generation": generation,
            "execution_connection_id": "connection-a",
        ]
    }
}
