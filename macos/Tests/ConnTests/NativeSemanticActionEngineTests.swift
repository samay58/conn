import XCTest
@testable import Conn

final class NativeSemanticActionEngineTests: XCTestCase {
    func testDispatchSuccessWithoutEffectIsNotVerified() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let observation = await engine.observe([
            "turn_id": "turn-1",
            "observation_epoch": 1,
        ])
        let snapshotID = try XCTUnwrap(observation["snapshot_id"] as? String)
        let plan = await engine.prepare([
            "turn_id": "turn-1",
            "response_epoch": 1,
            "observation_epoch": 1,
            "request": [
                "operation": "press",
                "target": ["snapshot_id": snapshotID, "ref": "no-effect"],
                "desired_effect": [
                    "mode": "all",
                    "predicates": [[
                        "kind": "element_attribute_changes",
                        "ref": "no-effect",
                        "attribute": "value",
                    ]],
                ],
                "risk": "local_mutation",
                "timeout_ms": 20,
            ],
        ])
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1",
            "response_epoch": 1,
            "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "no_effect")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "dispatched")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
        XCTAssertEqual(receipt["retry_safe"] as? Bool, false)
    }

    func testObservedEffectProducesVerifiedReceipt() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "press",
            target: ["ref": "immediate"],
            effect: changeEffect
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(receipt["ok"] as? Bool, true)
        XCTAssertEqual(receipt["dispatch_state"] as? String, "dispatched")
    }

    func testEffectAlreadySatisfiedRefusesBeforeDispatch() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["ref": "immediate"],
            effect: [
                "mode": "all",
                "predicates": [[
                    "kind": "element_exists",
                    "ref": "immediate",
                ]],
            ]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "effect_already_satisfied")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertNil(plan?["plan_fingerprint"])
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testDesiredEffectCannotVerifyUnrelatedElement() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["ref": "no-effect"],
            effect: [
                "mode": "all",
                "predicates": [[
                    "kind": "element_attribute_equals",
                    "ref": "status",
                    "attribute": "value",
                    "expected": "changed",
                ]],
            ]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "invalid_effect_target")
        XCTAssertNil(plan?["plan_fingerprint"])
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testTargetRefCannotDisguiseGlobalPredicate() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["ref": "no-effect"],
            effect: [
                "mode": "all",
                "predicates": [[
                    "kind": "window_count_delta",
                    "ref": "no-effect",
                    "delta": 1,
                ]],
            ]
        ))

        XCTAssertEqual(plan?["error"] as? String, "invalid_effect_target")
        XCTAssertNil(plan?["plan_fingerprint"])
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testVerifiedAnyReceiptContainsOnlySupportingEvidence() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["ref": "immediate"],
            effect: [
                "mode": "any",
                "predicates": [
                    [
                        "kind": "element_attribute_changes",
                        "ref": "immediate",
                        "attribute": "value",
                    ],
                    [
                        "kind": "element_attribute_equals",
                        "ref": "immediate",
                        "attribute": "value",
                        "expected": "never",
                    ],
                ],
            ]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)
        let evidence = try XCTUnwrap(receipt["evidence"] as? [[String: Any]])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertFalse(evidence.isEmpty)
        XCTAssertTrue(evidence.allSatisfy { $0["matched"] as? Bool == true })
    }

    func testNamedActionRejectsUntrustedExactBundleIdentity() async {
        let backend = SemanticFixtureBackend()
        backend.identityMatches = false
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "focus_tab",
            target: ["ref": "tab"],
            effect: nil,
            payload: [
                "bundle_id": "com.conn.fixture",
                "team_id": "TESTTEAM01",
            ]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "blocked")
        XCTAssertEqual(plan?["error"] as? String, "app_identity_mismatch")
        XCTAssertNil(plan?["plan_fingerprint"])
    }

    func testDerivedChangePredicateRemainsDispatchable() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["ref": "checkbox"],
            effect: nil
        ))

        XCTAssertNotNil(plan?["plan_fingerprint"])
        XCTAssertEqual(
            plan?["effect"] as? String,
            "all(element_attribute_changes:checkbox:value)"
        )
    }

    func testEffectSatisfiedAfterApprovalRefusesBeforeDispatch() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "press",
            target: ["ref": "immediate"],
            effect: changeEffect
        )
        backend.simulateImmediateEffect()

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "failed")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["native_error"] as? String, "effect_already_satisfied")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testPossiblyDispatchedNeverFallsBack() async throws {
        let backend = SemanticFixtureBackend()
        backend.dispatchResults = [
            NativeDispatchResult(state: .possiblyDispatched, nativeError: "kAXErrorCannotComplete"),
            NativeDispatchResult(state: .dispatched, nativeError: nil),
        ]
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "focus_tab",
            target: ["ref": "tab"],
            effect: selectedEffect
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "failed")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "possibly_dispatched")
        XCTAssertEqual(receipt["retry_safe"] as? Bool, false)
        XCTAssertEqual(backend.dispatchCount, 1)
    }

    func testOneFallbackRunsOnlyAfterProvenNonDispatch() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        backend.dispatchResults = [
            NativeDispatchResult(state: .notDispatched, nativeError: "unsupported"),
            NativeDispatchResult(state: .dispatched, nativeError: nil),
        ]
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "focus_tab",
            target: ["ref": "tab"],
            effect: selectedEffect
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.dispatchCount, 2)
    }

    func testPlanProvenanceMismatchRefusesBeforeDispatch() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "press",
            target: ["ref": "immediate"],
            effect: changeEffect
        )

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-2",
            "response_epoch": 1,
            "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "failed")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["retry_safe"] as? Bool, true)
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testDuplicateSemanticTargetIsAmbiguousBeforeDispatch() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["title": "Duplicate"],
            effect: changeEffect
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "ambiguous")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertNil(plan?["plan_fingerprint"])
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testSecureTextTargetIsBlockedBeforeDispatch() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "secure"],
            effect: [
                "mode": "all",
                "predicates": [[
                    "kind": "text_contains",
                    "ref": "secure",
                    "expected": "secret",
                ]],
            ],
            payload: ["text": "secret"]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "blocked")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testTargetBecomingSecureAfterApprovalBlocksBeforeDispatch() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "text"],
            effect: nil,
            payload: ["text": "hello"]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
        backend.textProtected = true

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "blocked")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testBrowserTargetBecomingSecurityUnknownBlocksBeforeSubmit() async throws {
        let backend = SemanticFixtureBackend()
        backend.bundleID = "com.apple.Safari"
        backend.textProtected = false
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "text"],
            effect: nil,
            payload: ["text": "hello", "submit": true]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
        backend.textProtected = nil

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "blocked")
        XCTAssertEqual(receipt["native_error"] as? String, "secure_state_unknown")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testReplacementAfterDispatchCannotVerifyApprovedTarget() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        backend.replaceImmediateAfterDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "press",
            target: ["ref": "immediate"],
            effect: changeEffect
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "no_effect")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testProtectedContentTextTargetIsBlockedBeforeDispatch() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "protected-text"],
            effect: changeEffect,
            payload: ["text": "secret"]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "blocked")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testBrowserSubmitBlocksWhenSecureStateIsUnknown() async {
        let backend = SemanticFixtureBackend()
        backend.bundleID = "com.apple.Safari"
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "text"],
            effect: changeEffect,
            payload: ["text": "hello", "submit": true]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "blocked")
        XCTAssertEqual(plan?["error"] as? String, "secure_state_unknown")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testRawKeyChordIsDispatchOnlyWithoutEffectEvidence() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "key_chord",
            target: [:],
            effect: nil,
            payload: ["keys": ["cmd", "t"]]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testAppScopedActionsRefuseAfterWindowChanges() async throws {
        for operation in ["invoke_menu", "key_chord"] {
            let backend = SemanticFixtureBackend()
            let engine = NativeSemanticActionEngine(backend: backend)
            let payload: [String: Any] = operation == "invoke_menu"
                ? ["menu_path": ["Actions", "Lazy New Window"]]
                : ["keys": ["cmd", "t"]]
            let plan = await engine.prepare(makePrepareParams(
                operation: operation,
                target: [:],
                effect: nil,
                payload: payload
            ))
            let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
            backend.windowID = 2

            let receipt = await execute(engine: engine, fingerprint: fingerprint)

            XCTAssertEqual(receipt["outcome"] as? String, "failed")
            XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
            XCTAssertEqual(backend.dispatchCount, 0)
        }
    }

    func testMenuPreparationDoesNotOpenMenus() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "invoke_menu",
            target: [:],
            effect: nil,
            payload: ["menu_path": ["Actions", "Lazy New Window"]]
        ))

        XCTAssertNotNil(plan?["plan_fingerprint"])
        XCTAssertEqual(backend.menuPreparationCount, 0)
    }

    func testPreparedPlanStoreIsBoundedAndNewTurnInvalidatesOldPlans() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        for index in 0..<20 {
            _ = await engine.prepare(makePrepareParams(
                operation: "open_url",
                target: [:],
                effect: nil,
                payload: ["url": "https://example.com/\(index)"]
            ))
        }
        let boundedCount = await engine.preparedPlanCount()
        XCTAssertLessThanOrEqual(boundedCount, 8)

        _ = await engine.observe([
            "turn_id": "turn-2",
            "observation_epoch": 2,
        ])
        let invalidatedCount = await engine.preparedPlanCount()
        XCTAssertEqual(invalidatedCount, 0)
    }

    func testDispatchProgressNeverReturnsNotDispatchedAfterMutation() {
        var progress = NativeDispatchProgress()
        XCTAssertEqual(progress.failure("before").state, .notDispatched)
        progress.markDispatched()
        XCTAssertEqual(progress.failure("after").state, .possiblyDispatched)
    }

    func testUnknownAXFailureIsPossiblyDispatched() {
        let result = NativeAXSemanticBackend.classifyDispatchError(.failure)

        XCTAssertEqual(result.state, .possiblyDispatched)
        XCTAssertEqual(result.nativeError, "AXError(-25200)")
    }

    func testExplicitUnsupportedAXActionIsNotDispatched() {
        let result = NativeAXSemanticBackend.classifyDispatchError(.actionUnsupported)

        XCTAssertEqual(result.state, .notDispatched)
        XCTAssertEqual(result.nativeError, "AXError(-25206)")
    }

    func testAppNameWithoutExpectedBundleIsRejected() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "open",
            target: [:],
            effect: nil,
            payload: ["app_name": "Fixture"]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "missing_bundle_id")
        XCTAssertNil(plan?["plan_fingerprint"])
    }

    func testExpectedBundleCannotBeOverriddenByConflictingAppName() async {
        let backend = SemanticFixtureBackend()
        backend.bundleID = "com.other.frontmost"
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "open",
            target: [:],
            effect: nil,
            payload: [
                "app_name": "Fixture",
                "bundle_id": "com.conn.fixture",
                "team_id": "TESTTEAM01",
            ]
        ))

        XCTAssertEqual(plan?["effect"] as? String,
                       "all(frontmost_bundle_equals:com.conn.fixture)")
    }

    func testThirdPartyAppRequiresExpectedSigningTeam() async {
        let backend = SemanticFixtureBackend()
        backend.bundleID = "com.other.frontmost"
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "open",
            target: [:],
            effect: nil,
            payload: ["bundle_id": "com.conn.fixture"]
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "missing_team_id")
        XCTAssertNil(plan?["plan_fingerprint"])
    }

    func testCodeSigningRequirementBindsBundleAndSigner() {
        XCTAssertEqual(
            NativeAXSemanticBackend.codeSigningRequirement(
                bundleID: "com.apple.Safari",
                teamID: nil
            ),
            "anchor apple and identifier \"com.apple.Safari\""
        )
        XCTAssertEqual(
            NativeAXSemanticBackend.codeSigningRequirement(
                bundleID: "com.example.App",
                teamID: "ABCDE12345"
            ),
            "anchor apple generic and identifier \"com.example.App\" "
                + "and certificate leaf[subject.OU] = \"ABCDE12345\""
        )
        XCTAssertNil(NativeAXSemanticBackend.codeSigningRequirement(
            bundleID: "com.example.App",
            teamID: nil
        ))
        XCTAssertNil(NativeAXSemanticBackend.codeSigningRequirement(
            bundleID: "com.example.\" or true",
            teamID: "ABCDE12345"
        ))
    }

    func testSubmitWaitsForVerifiedText() async throws {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "text"],
            effect: nil,
            payload: ["text": "hello", "submit": true]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "no_effect")
        XCTAssertEqual(backend.dispatchCount, 1, "submit must not run before text verifies")
    }

    func testSubmitRunsAfterTextVerificationAndReturnsDispatchOnly() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "set_text",
            target: ["ref": "text"],
            effect: nil,
            payload: ["text": "hello", "submit": true]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(backend.dispatchCount, 2)
    }

    func testMenuPathIsPreparedAsOneDispatchOnlyNativeTransaction() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "invoke_menu",
            target: [:],
            effect: nil,
            payload: ["menu_path": ["Actions", "Lazy New Window"]]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(plan?["target"] as? String, "Lazy New Window")
        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(backend.dispatchCount, 1)
    }

    func testClipboardWriteVerifiesReadbackHash() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "clipboard_write",
            target: [:],
            effect: nil,
            payload: ["text": "bounded clipboard text"]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(receipt["strategy"] as? String, "pasteboard")
    }

    func testTabFocusVerifiesSelectedState() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "focus_tab",
            target: ["ref": "tab"],
            effect: selectedEffect
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }

    func testDuplicateTabTitleRefusesBeforeDispatch() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "focus_tab",
            target: ["title": "Duplicate tab"],
            effect: selectedEffect
        ))

        XCTAssertEqual(plan?["outcome"] as? String, "ambiguous")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testScrollToVisibleUsesViewportEvidenceWithoutValueFallback() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "scroll",
            target: ["ref": "scroll"],
            effect: nil,
            payload: [:]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        XCTAssertEqual(
            plan?["effect"] as? String,
            "all(element_attribute_equals:scroll:visible:true)"
        )
        XCTAssertEqual(
            plan?["authorized_strategies"] as? [String],
            ["ax_scroll_to_visible"]
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }

    func testDirectionalScrollMayUseValueFallbackOnlyWithDirectionAndAmount() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let directionOnly = await engine.prepare(makePrepareParams(
            operation: "scroll",
            target: ["ref": "scroll"],
            effect: nil,
            payload: ["direction": "down"]
        ))
        let directionalAmount = await engine.prepare(makePrepareParams(
            operation: "scroll",
            target: ["ref": "scroll"],
            effect: nil,
            payload: ["direction": "down", "amount": 2.0]
        ))

        XCTAssertEqual(
            directionOnly?["authorized_strategies"] as? [String],
            ["ax_scroll_to_visible"]
        )
        XCTAssertEqual(
            directionalAmount?["authorized_strategies"] as? [String],
            ["ax_scroll_to_visible", "ax_set_value"]
        )
    }

    func testNotificationWithoutTargetedStateEvidenceCannotVerify() async throws {
        let backend = SemanticFixtureBackend()
        backend.notifications = ["AXValueChanged"]
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "press",
            target: ["ref": "immediate"],
            effect: [
                "mode": "all",
                "predicates": [[
                    "kind": "notification",
                    "ref": "immediate",
                    "notification": "AXValueChanged",
                ]],
            ]
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "no_effect")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testNotificationCannotSatisfyAnyGroupWithoutStateEvidence() async throws {
        let backend = SemanticFixtureBackend()
        backend.notifications = ["AXValueChanged"]
        let engine = NativeSemanticActionEngine(backend: backend)
        let fingerprint = try await prepare(
            engine: engine,
            operation: "press",
            target: ["ref": "no-effect"],
            effect: [
                "mode": "any",
                "predicates": [
                    [
                        "kind": "notification",
                        "ref": "no-effect",
                        "notification": "AXValueChanged",
                    ],
                    [
                        "kind": "element_attribute_equals",
                        "ref": "no-effect",
                        "attribute": "value",
                        "expected": "true",
                    ],
                ],
            ]
        )

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "no_effect")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testDeniedBundleBlocksBeforeDispatch() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        var params = makePrepareParams(
            operation: "press",
            target: ["ref": "immediate"],
            effect: changeEffect
        )
        var request = params["request"] as! [String: Any]
        request["denied_bundles"] = ["com.conn.fixture"]
        params["request"] = request

        let plan = await engine.prepare(params)

        XCTAssertEqual(plan?["outcome"] as? String, "blocked")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testFreeFormEffectPredicateIsRejected() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(makePrepareParams(
            operation: "press",
            target: ["ref": "immediate"],
            effect: [
                "mode": "all",
                "predicates": [["kind": "looks_good_to_me", "expected": true]],
            ]
        ))

        XCTAssertEqual(plan?["error"] as? String, "invalid_request")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testPythonNullDesiredEffectUsesDerivedPredicate() async {
        let backend = SemanticFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        var params = makePrepareParams(
            operation: "clipboard_write",
            target: [:],
            effect: nil,
            payload: ["text": "hello"]
        )
        var request = params["request"] as! [String: Any]
        request["desired_effect"] = NSNull()
        request["target"] = NSNull()
        params["request"] = request

        let plan = await engine.prepare(params)

        XCTAssertNotNil(plan?["plan_fingerprint"] as? String)
        XCTAssertEqual(plan?["effect"] as? String,
                       "all(clipboard_hash_equals:\(NativeHash.sha256("hello")))")
    }

    func testAppSwitchVerifiesResolvedFrontmostBundle() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        backend.bundleID = "com.other.frontmost"
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(makePrepareParams(
            operation: "switch",
            target: [:],
            effect: nil,
            payload: [
                "app_name": "Fixture",
                "bundle_id": "com.conn.fixture",
                "team_id": "TESTTEAM01",
            ]
        ))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await execute(engine: engine, fingerprint: fingerprint)

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }

    func testSimulatedThousandTransactionAcceptanceSeam() async throws {
        let backend = SemanticFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        var verified = 0
        var falseVerified = 0
        var ambiguousRefusals = 0
        var observationLatencies: [Int] = []
        var transactionLatencies: [Int] = []

        for index in 0..<1000 {
            let observation = await engine.observe([
                "turn_id": "turn-\(index)",
                "observation_epoch": 1,
            ])
            observationLatencies.append(observation["duration_ms"] as? Int ?? 0)
            let target: [String: Any]
            if index >= 990 {
                target = ["title": "Duplicate"]
            } else if index >= 980 {
                target = ["ref": "no-effect"]
            } else {
                target = ["ref": "immediate"]
            }
            let params = makePrepareParams(
                operation: "press",
                target: target,
                effect: changeEffect(ref: index >= 980 ? "no-effect" : "immediate"),
                turnID: "turn-\(index)"
            )
            guard let plan = await engine.prepare(params) else {
                XCTFail("plan missing at \(index)")
                continue
            }
            if index >= 990 {
                if plan["outcome"] as? String == "ambiguous" {
                    ambiguousRefusals += 1
                }
                continue
            }
            let fingerprint = try XCTUnwrap(plan["plan_fingerprint"] as? String)
            let receipt = await engine.execute([
                "plan_fingerprint": fingerprint,
                "turn_id": "turn-\(index)",
                "response_epoch": 1,
                "observation_epoch": 1,
            ])
            transactionLatencies.append(receipt["duration_ms"] as? Int ?? 0)
            let outcome = receipt["outcome"] as? String
            if outcome == "verified" { verified += 1 }
            if index >= 980, outcome == "verified" { falseVerified += 1 }
        }

        XCTAssertEqual(verified, 980)
        XCTAssertEqual(falseVerified, 0)
        XCTAssertEqual(ambiguousRefusals, 10)
        XCTAssertEqual(backend.wrongTargetCount, 0)
        XCTAssertLessThanOrEqual(percentile95(observationLatencies), 150)
        XCTAssertLessThanOrEqual(percentile95(transactionLatencies), 800)
    }

    private var changeEffect: [String: Any] {
        changeEffect(ref: "immediate")
    }

    private func changeEffect(ref: String) -> [String: Any] {
        [
            "mode": "all",
            "predicates": [[
                "kind": "element_attribute_changes",
                "ref": ref,
                "attribute": "value",
            ]],
        ]
    }

    private var selectedEffect: [String: Any] {
        [
            "mode": "all",
            "predicates": [[
                "kind": "element_attribute_equals",
                "ref": "tab",
                "attribute": "selected",
                "expected": true,
            ]],
        ]
    }

    private func prepare(
        engine: NativeSemanticActionEngine,
        operation: String,
        target: [String: Any],
        effect: [String: Any]
    ) async throws -> String {
        let plan = await engine.prepare(makePrepareParams(
            operation: operation,
            target: target,
            effect: effect
        ))
        return try XCTUnwrap(plan?["plan_fingerprint"] as? String)
    }

    private func execute(
        engine: NativeSemanticActionEngine,
        fingerprint: String
    ) async -> [String: Any] {
        await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1",
            "response_epoch": 1,
            "observation_epoch": 1,
        ])
    }

    private func makePrepareParams(
        operation: String,
        target: [String: Any],
        effect: [String: Any]?,
        payload: [String: Any] = [:],
        turnID: String = "turn-1"
    ) -> [String: Any] {
        var request: [String: Any] = [
            "operation": operation,
            "target": target,
            "payload": payload,
            "risk": "local_mutation",
            "strategy_ceiling": "semantic_plus_events",
            "timeout_ms": 10,
        ]
        if let effect { request["desired_effect"] = effect }
        return [
            "turn_id": turnID,
            "response_epoch": 1,
            "observation_epoch": 1,
            "request": request,
        ]
    }

    private func percentile95(_ values: [Int]) -> Int {
        guard !values.isEmpty else { return 0 }
        let sorted = values.sorted()
        return sorted[min(Int(Double(sorted.count) * 0.95), sorted.count - 1)]
    }
}

final class SemanticFixtureBackend: NativeSemanticBackend, @unchecked Sendable {
    private var status = "baseline"
    private var immediateValue = "false"
    private var tabSelected = false
    private var text = ""
    private var submitted = false
    private var windowCount = 1
    private var scrollValue = 0.0
    private var scrollVisible = false
    private var clipboardHash: String?
    var notifications: [String] = []
    var effectOnDispatch = false
    var dispatchResults: [NativeDispatchResult] = []
    var bundleID = "com.conn.fixture"
    var windowID: UInt32 = 1
    var identityMatches = true
    var textProtected: Bool?
    var replaceImmediateAfterDispatch = false
    private(set) var dispatchCount = 0
    private(set) var wrongTargetCount = 0
    private(set) var menuPreparationCount = 0

    func simulateImmediateEffect() {
        immediateValue = "changed-externally"
    }

    func capture(turnID: String, observationEpoch: Int, query: NativeObservationQuery) -> NativeCapturedObservation {
        let replacedImmediate = replaceImmediateAfterDispatch && dispatchCount > 0
        var nodes = [
            NativeObservationNode(
                ref: "immediate",
                path: replacedImmediate ? [9, 0] : [0, 0],
                role: "AXButton",
                title: "Immediate",
                identifier: "fixture.immediate",
                redactedValue: immediateValue,
                valueType: "boolean",
                enabled: true,
                frame: replacedImmediate
                    ? NativeRect(x: 400, y: 400, width: 80, height: 24)
                    : NativeRect(x: 10, y: 10, width: 80, height: 24),
                supportedActions: ["AXPress"]
            ),
            NativeObservationNode(ref: "no-effect", role: "AXButton", title: "No effect", identifier: "fixture.no_effect", redactedValue: "false", valueType: "boolean", enabled: true, supportedActions: ["AXPress"]),
            NativeObservationNode(ref: "status", role: "AXStaticText", title: "Status", identifier: "fixture.status", redactedValue: status, valueType: "string"),
            NativeObservationNode(ref: "tab", role: "AXRadioButton", title: "Second tab", identifier: "fixture.tab", selected: tabSelected, supportedActions: ["AXPress"], settableAttributes: ["AXSelected"]),
            NativeObservationNode(ref: "checkbox", role: "AXCheckBox", title: "Check", identifier: "fixture.checkbox", redactedValue: "false", valueType: "boolean", supportedActions: ["AXPress"]),
            NativeObservationNode(ref: "protected-text", role: "AXTextField", title: "Protected", identifier: "fixture.protected", focused: true, settableAttributes: ["AXValue"], protectedContent: true),
            NativeObservationNode(ref: "submitted", role: "AXStaticText", title: "Submitted", identifier: "fixture.submitted", redactedValue: String(submitted), valueType: "boolean"),
            NativeObservationNode(ref: "duplicate-1", role: "AXButton", title: "Duplicate", identifier: "fixture.duplicate.1", supportedActions: ["AXPress"]),
            NativeObservationNode(ref: "duplicate-2", role: "AXButton", title: "Duplicate", identifier: "fixture.duplicate.2", supportedActions: ["AXPress"]),
            NativeObservationNode(ref: "secure", role: "AXSecureTextField", title: "Password", identifier: "fixture.secure", settableAttributes: ["AXValue"]),
            NativeObservationNode(ref: "menu-bar", role: "AXMenuBar"),
            NativeObservationNode(ref: "actions-menu", parentRef: "menu-bar", role: "AXMenuBarItem", title: "Actions", identifier: "fixture.menu.actions", supportedActions: ["AXPress"]),
            NativeObservationNode(ref: "lazy-menu-item", parentRef: "actions-menu", role: "AXMenuItem", title: "Lazy New Window", identifier: "fixture.menu.new_window", enabled: true, supportedActions: ["AXPress"], menuShortcut: ["cmd", "n"]),
            NativeObservationNode(ref: "scroll", role: "AXScrollBar", title: "Scroll", identifier: "fixture.scroll", redactedValue: String(scrollValue), valueType: "number", visible: scrollVisible, supportedActions: ["AXScrollToVisible"], settableAttributes: ["AXValue"]),
            NativeObservationNode(ref: "duplicate-tab-1", role: "AXRadioButton", title: "Duplicate tab", identifier: "fixture.tab.duplicate.1", selected: false, supportedActions: ["AXPress"]),
            NativeObservationNode(ref: "duplicate-tab-2", role: "AXRadioButton", title: "Duplicate tab", identifier: "fixture.tab.duplicate.2", selected: false, supportedActions: ["AXPress"]),
        ]
        if !submitted {
            nodes.append(NativeObservationNode(
                ref: "text",
                role: "AXTextField",
                title: "Text",
                identifier: "fixture.text",
                redactedValue: text,
                valueType: "string",
                focused: true,
                settableAttributes: ["AXValue"],
                protectedContent: textProtected
            ))
        }
        var observation = NativeCapturedObservation.fixture(
            turnID: turnID,
            observationEpoch: observationEpoch,
            nodes: nodes,
            bundleID: bundleID,
            windowID: windowID
        )
        observation.windowCount = windowCount
        observation.clipboardHash = clipboardHash
        observation.notifications = notifications
        if query.deniedBundles.contains(bundleID) {
            observation.denied = true
            observation.nodes = []
        }
        return observation
    }

    func captureMenuForPreparation(
        request: NativeActionRequest,
        query: NativeObservationQuery
    ) -> NativeCapturedObservation? {
        menuPreparationCount += 1
        return capture(
            turnID: request.turnID,
            observationEpoch: request.observationEpoch,
            query: query
        )
    }

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool { identityMatches }

    func dispatch(strategy: NativeActionStrategy, request: NativeActionRequest, target: NativeResolvedTarget?) -> NativeDispatchResult {
        dispatchCount += 1
        if let target,
           !["fixture.immediate", "fixture.no_effect", "fixture.tab", "fixture.text"]
            .contains(target.current.identifier ?? "") {
            wrongTargetCount += 1
        }
        let result = dispatchResults.isEmpty
            ? NativeDispatchResult(state: .dispatched, nativeError: nil)
            : dispatchResults.removeFirst()
        guard result.state == .dispatched, effectOnDispatch else { return result }
        if strategy == .launchServices, let requestedBundleID = request.payload.bundleID {
            bundleID = requestedBundleID
        } else if strategy == .keyChord {
            submitted = true
        } else if strategy == .pasteboard {
            clipboardHash = request.payload.text.map(NativeHash.sha256)
        } else if request.operation == .scroll {
            if strategy == .axScrollToVisible {
                scrollVisible = true
            } else if let direction = request.payload.direction,
                      let amount = request.payload.amount {
                scrollValue += direction == "up" || direction == "left" ? -amount : amount
            }
        } else if strategy == .axMenuAction {
            windowCount += 1
        } else if target?.current.identifier == "fixture.immediate" {
            immediateValue = "changed-\(dispatchCount)"
        } else if target?.current.identifier == "fixture.tab" {
            tabSelected = true
        } else if target?.current.identifier == "fixture.text" {
            text = request.payload.text ?? ""
        }
        return result
    }
}
