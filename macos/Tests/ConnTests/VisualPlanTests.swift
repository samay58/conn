import XCTest
@testable import Conn

final class VisualPlanTests: XCTestCase {
    func testOnlyActionableAccessibilityHitCanVetoVisualGrounding() {
        XCTAssertNil(ScreenCaptureVisualProvider.actionableLabel(
            actionNames: [],
            values: ["Conn Action Fixture: opaque_media", nil]
        ))
        XCTAssertEqual(
            ScreenCaptureVisualProvider.actionableLabel(
                actionNames: ["AXPress"],
                values: ["Send", "Submit control"]
            ),
            "Send"
        )
    }

    func testAccessiblePlayCompilesToAXPress() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare([
            "turn_id": "turn-1",
            "response_epoch": 1,
            "observation_epoch": 1,
            "request": [
                "operation": "activate",
                "target": ["ref": "immediate"],
                "payload": ["goal": "Play video"],
                "risk": "act_low",
            ],
        ])

        XCTAssertEqual(plan?["authorized_strategies"] as? [String], ["ax_press"])
    }

    func testGroundedPlayDispatchesOnceAndCapsAtDispatchOnlyWithoutWitness() async throws {
        let provider = VisualFixtureProvider()
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-1")
        XCTAssertTrue(interlock.accept(
            connectionID: "connection-1", generation: 3, suspended: false
        ))
        let control = NativeVisualControl(provider: provider, executionInterlock: interlock)
        let capture = await control.observe(observeParams())
        let captureID = try XCTUnwrap(capture["capture_id"] as? String)
        let prepared = await control.prepareVisual(
            prepareParams(captureID: captureID)
        )
        let fingerprint = try XCTUnwrap(prepared["plan_fingerprint"] as? String)

        let receipt = await control.executeVisual([
            "plan_fingerprint": fingerprint,
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(provider.dispatchCount, 1)
        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "dispatched")
        XCTAssertEqual(receipt["reason_code"] as? String, "no_trustworthy_witness")
    }

    func testChangedWindowFrameRefusesBeforeInput() async throws {
        let provider = VisualFixtureProvider()
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-1")
        XCTAssertTrue(interlock.accept(
            connectionID: "connection-1", generation: 3, suspended: false
        ))
        let control = NativeVisualControl(provider: provider, executionInterlock: interlock)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(
            prepareParams(captureID: try XCTUnwrap(capture["capture_id"] as? String))
        )
        provider.frame = NativeRect(x: 10, y: 20, width: 700, height: 450)

        let receipt = await control.executeVisual([
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(provider.dispatchCount, 0)
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["reason_code"] as? String, "visual_plan_stale")
    }

    func testConflictingAccessibleHitRefusesBeforeInput() async throws {
        let provider = VisualFixtureProvider()
        provider.hitLabel = "Send"
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-1")
        XCTAssertTrue(interlock.accept(
            connectionID: "connection-1", generation: 3, suspended: false
        ))
        let control = NativeVisualControl(provider: provider, executionInterlock: interlock)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(
            prepareParams(captureID: try XCTUnwrap(capture["capture_id"] as? String))
        )

        let receipt = await control.executeVisual([
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(provider.dispatchCount, 0)
        XCTAssertEqual(receipt["reason_code"] as? String, "visual_hit_test_conflict")
    }

    func testExpiredGrantRefusesBeforeInput() async throws {
        let provider = VisualFixtureProvider()
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-1")
        XCTAssertTrue(interlock.accept(
            connectionID: "connection-1", generation: 3, suspended: false
        ))
        let control = NativeVisualControl(provider: provider, executionInterlock: interlock)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(
            prepareParams(captureID: try XCTUnwrap(capture["capture_id"] as? String))
        )
        interlock.suspend()

        let receipt = await control.executeVisual([
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(provider.dispatchCount, 0)
        XCTAssertEqual(receipt["reason_code"] as? String, "navigation_suspended")
    }

    func testPointConversionSupportsNegativeDisplayOrigins() {
        let point = NativeVisualGrounding.point(
            region: NativeRect(x: 0.25, y: 0.2, width: 0.5, height: 0.4),
            windowFrame: NativeRect(x: -1200, y: 100, width: 800, height: 600)
        )

        XCTAssertEqual(point.x, -800)
        XCTAssertEqual(point.y, 340)
    }

    func testPlayToPauseAccessibleStateCanVerifyVisualDispatch() async throws {
        let provider = VisualFixtureProvider()
        provider.hitLabels = ["Play", "Pause"]
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-1")
        XCTAssertTrue(interlock.accept(
            connectionID: "connection-1", generation: 3, suspended: false
        ))
        let control = NativeVisualControl(provider: provider, executionInterlock: interlock)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(
            prepareParams(captureID: try XCTUnwrap(capture["capture_id"] as? String))
        )

        let receipt = await control.executeVisual([
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(receipt["ok"] as? Bool, true)
    }

    func testPossibleDispatchCannotReplayTheVisualPlan() async throws {
        let provider = VisualFixtureProvider()
        provider.dispatchResult = NativeDispatchResult(
            state: .possiblyDispatched, nativeError: "post_failed"
        )
        let interlock = NativeExecutionInterlock()
        interlock.beginConnection("connection-1")
        XCTAssertTrue(interlock.accept(
            connectionID: "connection-1", generation: 3, suspended: false
        ))
        let control = NativeVisualControl(provider: provider, executionInterlock: interlock)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(
            prepareParams(captureID: try XCTUnwrap(capture["capture_id"] as? String))
        )
        let params: [String: Any] = [
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ]

        let first = await control.executeVisual(params)
        let second = await control.executeVisual(params)

        XCTAssertEqual(first["dispatch_state"] as? String, "possibly_dispatched")
        XCTAssertEqual(second["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(provider.dispatchCount, 1)
    }

    func testVisualPredispatchDeadlineSendsNoInput() async throws {
        let provider = VisualFixtureProvider()
        provider.recaptureDelayMs = 20
        let control = NativeVisualControl(provider: provider)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(prepareParams(
            captureID: try XCTUnwrap(capture["capture_id"] as? String),
            timeoutMs: 10
        ))

        let receipt = await control.executeVisual([
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(provider.dispatchCount, 0)
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["reason_code"] as? String, "native_transaction_timeout")
    }

    func testVisualPostInputDeadlineIsFinalAndPossiblyDispatched() async throws {
        let provider = VisualFixtureProvider()
        provider.dispatchDelayMs = 20
        let control = NativeVisualControl(provider: provider)
        let capture = await control.observe(observeParams())
        let prepared = await control.prepareVisual(prepareParams(
            captureID: try XCTUnwrap(capture["capture_id"] as? String),
            timeoutMs: 10
        ))

        let receipt = await control.executeVisual([
            "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
        ])

        XCTAssertEqual(provider.dispatchCount, 1)
        XCTAssertEqual(receipt["dispatch_state"] as? String, "possibly_dispatched")
        XCTAssertEqual(receipt["reason_code"] as? String, "native_transaction_timeout")
    }

    func testEveryPointerKindHasOneBoundedEventSequence() {
        XCTAssertEqual(NativePointerInput.primaryClick.eventCount, 2)
        XCTAssertEqual(NativePointerInput.doubleClick.eventCount, 4)
        XCTAssertEqual(NativePointerInput.rightClick.eventCount, 2)
        XCTAssertEqual(NativePointerInput.scroll.eventCount, 1)
    }

    func testVisualEffectClassUsesCompilerPolicy() async throws {
        let provider = VisualFixtureProvider()
        let control = NativeVisualControl(provider: provider)
        let capture = await control.observe(observeParams())
        let captureID = try XCTUnwrap(capture["capture_id"] as? String)

        let seek = await control.prepareVisual(
            prepareParams(captureID: captureID, goal: "Seek video", label: "Timeline")
        )
        let delete = await control.prepareVisual(
            prepareParams(captureID: captureID, goal: "Delete video", label: "Delete")
        )

        XCTAssertEqual(seek["effect_class"] as? String, "reversible_navigation")
        XCTAssertEqual(delete["effect_class"] as? String, "destructive")
    }

    func testCompilerSelectsBoundedPointerSequenceFromGoal() async throws {
        for (goal, expected) in [
            ("Double click video", NativePointerInput.doubleClick),
            ("Open context menu with right click", .rightClick),
            ("Scroll down", .scroll),
        ] {
            let provider = VisualFixtureProvider()
            let control = NativeVisualControl(provider: provider)
            let capture = await control.observe(observeParams())
            let prepared = await control.prepareVisual(prepareParams(
                captureID: try XCTUnwrap(capture["capture_id"] as? String),
                goal: goal,
                label: "Video"
            ))

            _ = await control.executeVisual([
                "plan_fingerprint": try XCTUnwrap(prepared["plan_fingerprint"] as? String),
                "navigation_generation": 3,
                "execution_connection_id": "connection-1",
            ])

            XCTAssertEqual(provider.lastInput, expected)
            XCTAssertEqual(provider.dispatchCount, 1)
        }
    }

    private func observeParams() -> [String: Any] {
        [
            "enabled": true,
            "turn_id": "turn-1",
            "observation_epoch": 7,
            "execution_connection_id": "connection-1",
        ]
    }

    private func prepareParams(
        captureID: String,
        goal: String = "Play video",
        label: String = "Play",
        timeoutMs: Int = 1200
    ) -> [String: Any] {
        [
            "turn_id": "turn-1",
            "response_epoch": 2,
            "observation_epoch": 7,
            "navigation_generation": 3,
            "execution_connection_id": "connection-1",
            "request": [
                "operation": "activate",
                "visual_enabled": true,
                "timeout_ms": timeoutMs,
                "payload": [
                    "goal": goal,
                    "visual_grounding": [
                        "capture_id": captureID,
                        "region": ["x": 0.25, "y": 0.2, "width": 0.5, "height": 0.4],
                        "label": label,
                        "confidence": 0.95,
                    ],
                ],
            ],
        ]
    }
}
