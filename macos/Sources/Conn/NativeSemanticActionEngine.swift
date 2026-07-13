import Foundation

private struct NativeActionPlan {
    var fingerprint: String
    var request: NativeActionRequest
    var baseline: NativeCapturedObservation
    var target: NativeObservationNode?
    var effect: NativeEffectGroup
    var strategies: [NativeActionStrategy]
    var safeTarget: String
    var preview: String
    var createdMs: Int
}

actor NativeSemanticActionEngine {
    private let backend: NativeSemanticBackend
    private let store: NativeObservationStore
    private var plans: [String: NativeActionPlan] = [:]
    private let planLimit = 8
    private let planTTLms = 45_000

    init(backend: NativeSemanticBackend = NativeAXSemanticBackend()) {
        self.backend = backend
        store = NativeObservationStore(backend: backend)
    }

    func perform(op: String, params: [String: Any]) async -> [String: Any]? {
        switch op {
        case "observe": return observe(params)
        case "capability_report": return capabilityReport(params)
        case "prepare_action": return prepare(params)
        case "execute_action": return await execute(params)
        default: return nil
        }
    }

    func observe(_ params: [String: Any]) -> [String: Any] {
        let turnID = params["turn_id"] as? String ?? "system"
        let observationEpoch = params["observation_epoch"] as? Int ?? 0
        prunePlans(turnID: turnID, observationEpoch: observationEpoch)
        let query = NativeObservationQuery.parse(params["query"])
        return store.observe(
            turnID: turnID,
            observationEpoch: observationEpoch,
            query: query
        ).dictionary
    }

    /// Descriptive only: what the current app can do for the bounded intent
    /// families, ranked, epoch-bound, and carrying no dispatch authority.
    /// Python risk policy still gates any plan compiled from it.
    func capabilityReport(_ params: [String: Any]) -> [String: Any] {
        let turnID = params["turn_id"] as? String ?? "system"
        let observationEpoch = params["observation_epoch"] as? Int ?? 0
        prunePlans(turnID: turnID, observationEpoch: observationEpoch)
        let denied = params["denied_bundles"] as? [String] ?? []
        let baseline = store.observe(
            turnID: turnID,
            observationEpoch: observationEpoch,
            query: NativeObservationQuery(
                bundleID: nil, pid: nil, includeMenu: true,
                maxNodes: 500, maxDepth: 16, deniedBundles: Set(denied)
            )
        )
        var candidates: [[String: Any]] = []
        if !baseline.denied {
            for (kind, synonyms) in Self.createKindSynonyms.sorted(by: { $0.key < $1.key }) {
                let wanted = synonyms.map { "new \($0)" }
                let leaves = baseline.nodes.filter { node in
                    node.role == "AXMenuItem"
                        && node.enabled != false
                        && wanted.contains(normalize(node.title))
                }
                guard let leaf = leaves.first else { continue }
                let paths = Set(leaves.map { menuPathTitles(to: $0, in: baseline) })
                var candidate: [String: Any] = [
                    "intent": "create",
                    "kind": kind,
                    "title": leaf.title ?? "",
                    "state": paths.count == 1 ? "unique" : "ambiguous",
                    "strategy_class": "menu",
                    "ceiling": NativeActionOutcome.dispatchOnly.rawValue,
                ]
                if paths.count == 1 {
                    candidate["menu_path"] = menuPathTitles(to: leaf, in: baseline)
                        .split(separator: "\u{1e}").map(String.init)
                }
                candidate.put("shortcut", leaf.menuShortcut)
                candidates.append(candidate)
            }
            for (kind, roles) in Self.selectionParentRoles.sorted(by: { $0.key < $1.key })
            where kind != "item" {
                let collectionRefs = Set(
                    baseline.nodes.filter { roles.contains($0.role) }.map(\.ref))
                let selected = baseline.nodes.filter { node in
                    node.selected == true
                        && node.parentRef.map(collectionRefs.contains) == true
                }
                guard selected.count == 1, let current = selected.first else {
                    continue
                }
                candidates.append([
                    "intent": "select_relative",
                    "kind": kind,
                    "title": current.title ?? "",
                    "state": "unique",
                    "strategy_class": "semantic_selection",
                    "ceiling": NativeActionOutcome.verified.rawValue,
                ])
            }
        }
        return [
            "turn_id": turnID,
            "observation_epoch": observationEpoch,
            "snapshot_id": baseline.snapshotID,
            "bundle_id": baseline.bundleID ?? "",
            "secure": baseline.secure,
            "denied": baseline.denied,
            "supported_intents": ["create", "select_relative"],
            "candidates": Array(candidates.prefix(20)),
        ]
    }

    func prepare(_ params: [String: Any]) -> [String: Any]? {
        guard var request = NativeActionRequest.parse(params) else {
            return failurePlan("invalid_request")
        }
        var intentCandidates: [[String: Any]]?
        var intentWitness: NativeEffectGroup?
        prunePlans(
            turnID: request.turnID,
            observationEpoch: request.observationEpoch
        )
        if let bundleID = request.payload.bundleID {
            guard NativeAppIdentity.validBundleID(bundleID) else {
                return failurePlan("invalid_bundle_id")
            }
            if !bundleID.hasPrefix("com.apple.") {
                guard let teamID = request.payload.teamID else {
                    return failurePlan("missing_team_id")
                }
                guard NativeAppIdentity.validTeamID(teamID) else {
                    return failurePlan("invalid_team_id")
                }
            }
        } else if [.openApp, .switchApp].contains(request.operation) {
            return failurePlan("missing_bundle_id")
        }
        let wantsMenu = request.operation == .menu
            || (request.operation == .semanticIntent
                && request.payload.intentFamily == "create")
        let query = NativeObservationQuery(
            bundleID: operationNeedsTarget(request.operation)
                ? request.target.bundleID : nil,
            pid: nil,
            includeMenu: wantsMenu,
            maxNodes: wantsMenu ? 500 : 300,
            maxDepth: 16,
            deniedBundles: request.deniedBundles
        )
        if let requestedBundle = request.payload.bundleID,
           request.deniedBundles.contains(requestedBundle) {
            return failurePlan("denied_bundle", outcome: .blocked)
        }
        let origin = request.target.snapshotID.flatMap(store.snapshot)
        let baseline = store.observe(
            turnID: request.turnID,
            observationEpoch: request.observationEpoch,
            query: query
        )

        if baseline.denied {
            return failurePlan("denied_bundle", outcome: .blocked)
        }
        if ![.openApp, .switchApp].contains(request.operation),
           request.payload.bundleID != nil,
           !backend.applicationIdentityMatches(request: request, observation: baseline) {
            return failurePlan("app_identity_mismatch", outcome: .blocked)
        }
        if request.operation == .semanticIntent {
            // The intent boundary owns proof selection; a caller-supplied
            // predicate on an intent is a contract violation, not an input.
            guard request.desiredEffect == nil else {
                return failurePlan("intent_rejects_predicates")
            }
            switch lowerSemanticIntent(request: request, baseline: baseline) {
            case .success(let lowered):
                request = lowered.request
                intentCandidates = lowered.candidates
                intentWitness = lowered.witness
            case .failure(let failure): return failure.plan
            }
        }
        if let origin,
           (origin.turnID != request.turnID
               || origin.observationEpoch != request.observationEpoch) {
            return failurePlan("stale_snapshot")
        }
        let target: Result<NativeObservationNode?, NativeResolutionError>
        if request.operation != .menu,
           operationNeedsTarget(request.operation),
           let origin,
           request.target.ref != nil {
            target = store.resolve(
                target: request.target,
                baseline: origin,
                current: baseline
            ).map { $0.current }
        } else {
            target = resolveForPreparation(request: request, baseline: baseline)
        }
        switch target {
        case .failure(let error):
            if operationNeedsTarget(request.operation) {
                return failurePlan(
                    String(describing: error),
                    outcome: error == .ambiguous ? .ambiguous : .failed
                )
            }
        case .success(let node):
            if node?.secure == true {
                return failurePlan("secure_field", outcome: .blocked)
            }
            if request.operation == .setText,
               request.payload.submit,
               let node,
               browserBundle(baseline.bundleID),
               !node.secureStateKnown {
                return failurePlan("secure_state_unknown", outcome: .blocked)
            }
        }

        let targetNode: NativeObservationNode?
        switch target {
        case .success(let node): targetNode = node
        case .failure: targetNode = nil
        }
        let reboundDesired: NativeEffectGroup?
        if let desired = request.desiredEffect, let origin,
           origin.snapshotID != baseline.snapshotID {
            reboundDesired = rebindEffect(desired, from: origin, to: baseline)
            if reboundDesired == nil { return failurePlan("stale_effect_binding") }
        } else {
            reboundDesired = request.desiredEffect
        }
        var effect = reboundDesired ?? intentWitness ?? derivedEffect(
            request: request,
            target: targetNode,
            baseline: baseline
        )
        guard effectBindingsAreValid(effect, in: baseline) else {
            return failurePlan("invalid_effect_predicate")
        }
        if reboundDesired != nil,
           !desiredEffectTargetsAction(effect, request: request, target: targetNode) {
            return failurePlan("invalid_effect_target")
        }
        effect = bindBaselines(effect, in: baseline)
        if evaluate(effect, before: baseline, after: baseline).matched {
            return failurePlan("effect_already_satisfied")
        }
        let strategies = compileStrategies(request: request, target: targetNode)
        guard !strategies.isEmpty else {
            return failurePlan("unsupported_operation")
        }
        let safeTarget = [
            targetNode?.title,
            targetNode?.description,
            request.payload.menuPath.last,
            request.payload.appName,
            request.payload.bundleID,
            request.payload.url,
            request.operation.rawValue,
        ]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty } ?? request.operation.rawValue
        let fingerprint = planFingerprint(
            request: request,
            baseline: baseline,
            target: targetNode,
            effect: effect,
            strategies: strategies
        )
        let preview = previewText(request: request, target: safeTarget)
        let plan = NativeActionPlan(
            fingerprint: fingerprint,
            request: request,
            baseline: baseline,
            target: targetNode,
            effect: effect,
            strategies: strategies,
            safeTarget: safeTarget,
            preview: preview,
            createdMs: NativeClock.ms()
        )
        plans[fingerprint] = plan
        prunePlanLimit()
        return [
            "plan_fingerprint": fingerprint,
            "preview": preview,
            "target": safeTarget,
            "effect": effect.summary,
            "predicates": effect.predicates.map(\.dictionary),
            "effect_mode": effect.mode,
            "authorized_strategies": strategies.map(\.rawValue),
            "risk": request.risk,
            "lane": "semantic",
            "snapshot_id": baseline.snapshotID,
            "observation_id": baseline.observationID,
            "turn_id": request.turnID,
            "response_epoch": request.responseEpoch,
            "observation_epoch": request.observationEpoch,
            "payload_hash": request.payload.hash,
            "before_digest": baseline.digest,
            "timeout_ms": request.timeoutMs,
            "bundle_id": baseline.bundleID ?? "",
            "window_id": baseline.windowID.map { Int($0) } ?? 0,
            "target_role": targetNode?.role ?? "",
            "secure": targetNode?.secure ?? false,
            "denied": baseline.denied,
            "read_set": Array(Set(
                effect.predicates.compactMap(\.ref) + [targetNode?.ref].compactMap { $0 }
            )).sorted(),
        ].merging(
            intentCandidates.map { ["candidates": $0] } ?? [:],
            uniquingKeysWith: { current, _ in current }
        )
    }

    func execute(_ params: [String: Any]) async -> [String: Any] {
        let started = NativeClock.ms()
        guard let fingerprint = params["plan_fingerprint"] as? String,
              let plan = plans.removeValue(forKey: fingerprint) else {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: nil,
                strategy: nil,
                evidence: [evidence("plan", false, "unknown_or_consumed")],
                nativeError: "stale_plan",
                started: started
            )
        }
        guard NativeClock.ms() - plan.createdMs <= planTTLms else {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("plan", false, "expired")],
                nativeError: "stale_plan",
                started: started
            )
        }
        guard params["turn_id"] as? String == plan.request.turnID,
              params["response_epoch"] as? Int == plan.request.responseEpoch,
              params["observation_epoch"] as? Int == plan.request.observationEpoch,
              fingerprint == plan.fingerprint else {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("plan", false, "provenance_mismatch")],
                nativeError: "stale_plan",
                started: started
            )
        }

        let query = NativeObservationQuery(
            bundleID: nil,
            pid: nil,
            includeMenu: plan.request.operation == .menu,
            maxNodes: plan.request.operation == .menu ? 500 : 300,
            maxDepth: 16,
            deniedBundles: plan.request.deniedBundles
        )
        let current = store.observe(
            turnID: plan.request.turnID,
            observationEpoch: plan.request.observationEpoch,
            query: query
        )
        if current.denied {
            return receipt(
                outcome: .blocked,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("bundle_allowed", false, "denied")],
                nativeError: "denied_bundle",
                started: started
            )
        }
        if ![.openApp, .switchApp].contains(plan.request.operation),
           requestBindsApplication(plan.request),
           !backend.applicationIdentityMatches(request: plan.request, observation: current) {
            return receipt(
                outcome: .blocked,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("app_identity", false, "signature_mismatch")],
                nativeError: "app_identity_mismatch",
                started: started
            )
        }
        if requiresStableExecutionContext(plan.request.operation),
           !sameExecutionContext(plan.baseline, current) {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("execution_context", false, "app_or_window_changed")],
                nativeError: "stale_plan",
                started: started
            )
        }
        let preDispatchEffect = evaluate(
            plan.effect,
            before: plan.baseline,
            after: current
        )
        if preDispatchEffect.matched {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: preDispatchEffect.evidence,
                nativeError: "effect_already_satisfied",
                started: started,
                after: current
            )
        }

        let resolved: NativeResolvedTarget?
        if executionNeedsTarget(plan.request.operation), let original = plan.target {
            let resolution = store.resolve(
                target: NativeActionTarget(
                    snapshotID: plan.baseline.snapshotID,
                    ref: original.ref,
                    identifier: original.identifier,
                    title: original.title,
                    bundleID: plan.baseline.bundleID
                ),
                baseline: plan.baseline,
                current: current
            )
            switch resolution {
            case .success(let target):
                if target.current.secure {
                    return receipt(
                        outcome: .blocked,
                        dispatch: .notDispatched,
                        plan: plan,
                        strategy: nil,
                        evidence: [evidence("secure_target", false, "changed_after_approval")],
                        nativeError: "secure_field",
                        started: started
                    )
                }
                if plan.request.operation == .setText,
                   plan.request.payload.submit,
                   browserBundle(current.bundleID),
                   !target.current.secureStateKnown {
                    return receipt(
                        outcome: .blocked,
                        dispatch: .notDispatched,
                        plan: plan,
                        strategy: nil,
                        evidence: [evidence("secure_target", false, "state_became_unknown")],
                        nativeError: "secure_state_unknown",
                        started: started
                    )
                }
                resolved = target
            case .failure(let error):
                let outcome: NativeActionOutcome = error == .ambiguous ? .ambiguous : .failed
                return receipt(
                    outcome: outcome,
                    dispatch: .notDispatched,
                    plan: plan,
                    strategy: nil,
                    evidence: [evidence("target_resolution", false, String(describing: error))],
                    nativeError: "target_\(String(describing: error))",
                    started: started
                )
            }
        } else {
            resolved = nil
        }

        backend.beginEvidenceObservation(request: plan.request, target: resolved)
        var selectedStrategy: NativeActionStrategy?
        var dispatchResult = NativeDispatchResult(state: .notDispatched, nativeError: "no_strategy")
        for (index, strategy) in plan.strategies.prefix(2).enumerated() {
            selectedStrategy = strategy
            dispatchResult = backend.dispatch(
                strategy: strategy,
                request: plan.request,
                target: resolved
            )
            if dispatchResult.state != .notDispatched || index == 1 { break }
        }
        if dispatchResult.state == .possiblyDispatched {
            return receipt(
                outcome: .failed,
                dispatch: .possiblyDispatched,
                plan: plan,
                strategy: selectedStrategy,
                evidence: [evidence("dispatch", false, "uncertain")],
                nativeError: dispatchResult.nativeError,
                started: started
            )
        }
        if dispatchResult.state == .notDispatched {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: selectedStrategy,
                evidence: [evidence("dispatch", false, "rejected_before_effect")],
                nativeError: dispatchResult.nativeError,
                started: started
            )
        }

        if plan.request.operation == .setText, plan.request.payload.submit {
            guard let targetRef = plan.target?.ref,
                  let text = plan.request.payload.text else {
                return receipt(
                    outcome: .blocked,
                    dispatch: .dispatched,
                    plan: plan,
                    strategy: selectedStrategy,
                    evidence: [evidence("text_before_submit", false, "missing_text_target")],
                    nativeError: "submit_precondition_missing",
                    started: started
                )
            }
            var textPlan = plan
            textPlan.effect = NativeEffectGroup(mode: "all", predicates: [
                NativeEffectPredicate(
                    kind: "text_hash_equals",
                    ref: targetRef,
                    expected: NativeHash.sha256(text)
                ),
            ])
            let verificationQuery = verificationQuery(for: plan)
            let textVerification = await verify(plan: textPlan, query: verificationQuery)
            guard textVerification.matched else {
                return receipt(
                    outcome: .noEffect,
                    dispatch: .dispatched,
                    plan: plan,
                    strategy: selectedStrategy,
                    evidence: textVerification.evidence,
                    nativeError: nil,
                    started: started,
                    after: textVerification.after
                )
            }
            guard let submitTarget = revalidatedFocusedTarget(
                for: plan,
                query: verificationQuery
            ) else {
                return receipt(
                    outcome: .failed,
                    dispatch: .dispatched,
                    plan: plan,
                    strategy: selectedStrategy,
                    evidence: [evidence("submit_focus", false, "target_not_focused")],
                    nativeError: "submit_focus_changed",
                    started: started,
                    after: textVerification.after
                )
            }
            var submitRequest = plan.request
            submitRequest.payload.keys = ["return"]
            let submitResult = backend.dispatch(
                strategy: .keyChord,
                request: submitRequest,
                target: submitTarget
            )
            if submitResult.state == .possiblyDispatched {
                return receipt(
                    outcome: .failed,
                    dispatch: .possiblyDispatched,
                    plan: plan,
                    strategy: .keyChord,
                    evidence: textVerification.evidence,
                    nativeError: submitResult.nativeError,
                    started: started,
                    after: textVerification.after
                )
            }
            if submitResult.state == .notDispatched {
                return receipt(
                    outcome: .failed,
                    dispatch: .dispatched,
                    plan: plan,
                    strategy: .keyChord,
                    evidence: textVerification.evidence,
                    nativeError: submitResult.nativeError,
                    started: started,
                    after: textVerification.after
                )
            }
        }

        let verification = await verify(plan: plan, query: verificationQuery(for: plan))
        if plan.effect.predicates.isEmpty {
            return receipt(
                outcome: .dispatchOnly,
                dispatch: .dispatched,
                plan: plan,
                strategy: selectedStrategy,
                evidence: verification.evidence,
                nativeError: nil,
                started: started,
                after: verification.after
            )
        }
        return receipt(
            outcome: verification.matched ? .verified : .noEffect,
            dispatch: .dispatched,
            plan: plan,
            strategy: selectedStrategy,
            evidence: verification.evidence,
            nativeError: nil,
            started: started,
            after: verification.after,
            traceEvidence: verification.traceEvidence
        )
    }

    private func verify(
        plan: NativeActionPlan,
        query: NativeObservationQuery
    ) async -> (
        matched: Bool,
        evidence: [[String: Any]],
        traceEvidence: [[String: Any]],
        after: NativeCapturedObservation
    ) {
        let deadline = NativeClock.ms() + plan.request.timeoutMs
        var latest = store.observe(
            turnID: plan.request.turnID,
            observationEpoch: plan.request.observationEpoch,
            query: query
        )
        var attempt = 0
        var notificationWatermark = latest.notifications.count
        while true {
            if requestBindsApplication(plan.request),
               !backend.applicationIdentityMatches(request: plan.request, observation: latest) {
                let identityEvidence = evidence(
                    "app_identity",
                    false,
                    "signature_mismatch"
                )
                if NativeClock.ms() >= deadline {
                    return (false, [identityEvidence], [identityEvidence], latest)
                }
                try? await Task.sleep(for: verificationBackoff(attempt))
                attempt += 1
                latest = store.observe(
                    turnID: plan.request.turnID,
                    observationEpoch: plan.request.observationEpoch,
                    query: query
                )
                continue
            }
            if requiresStableExecutionContext(plan.request.operation),
               !sameExecutionContext(plan.baseline, latest) {
                let contextEvidence = evidence(
                    "verification_context",
                    false,
                    "app_or_window_changed"
                )
                if NativeClock.ms() >= deadline {
                    return (false, [contextEvidence], [contextEvidence], latest)
                }
                try? await Task.sleep(for: verificationBackoff(attempt))
                attempt += 1
                latest = store.observe(
                    turnID: plan.request.turnID,
                    observationEpoch: plan.request.observationEpoch,
                    query: query
                )
                continue
            }
            let evaluated = evaluate(plan.effect, before: plan.baseline, after: latest)
            if evaluated.matched || NativeClock.ms() >= deadline {
                return (
                    evaluated.matched,
                    evaluated.evidence,
                    evaluated.traceEvidence,
                    latest
                )
            }
            // Targeted reread cadence: adaptive backoff (50, 100, then
            // 200ms) instead of a fixed 25ms full-tree poll. A fresh AX
            // notification is a hint that the effect just landed, so the
            // reread happens almost immediately; the 1ms sleep keeps a
            // suspension point in every iteration so a noisy target app
            // cannot starve the actor's other work.
            if latest.notifications.count == notificationWatermark {
                try? await Task.sleep(for: verificationBackoff(attempt))
                attempt += 1
            } else {
                try? await Task.sleep(for: .milliseconds(1))
            }
            notificationWatermark = latest.notifications.count
            latest = store.observe(
                turnID: plan.request.turnID,
                observationEpoch: plan.request.observationEpoch,
                query: query
            )
        }
    }

    private func verificationBackoff(_ attempt: Int) -> Duration {
        .milliseconds(min(50 << min(attempt, 2), 200))
    }

    private func verificationQuery(for plan: NativeActionPlan) -> NativeObservationQuery {
        NativeObservationQuery(
            bundleID: nil,
            pid: requiresStableExecutionContext(plan.request.operation)
                ? plan.baseline.pid : nil,
            includeMenu: plan.request.operation == .menu,
            maxNodes: plan.request.operation == .menu ? 500 : 300,
            maxDepth: 16,
            deniedBundles: plan.request.deniedBundles
        )
    }

    private func revalidatedFocusedTarget(
        for plan: NativeActionPlan,
        query: NativeObservationQuery
    ) -> NativeResolvedTarget? {
        guard let original = plan.target else { return nil }
        let current = store.observe(
            turnID: plan.request.turnID,
            observationEpoch: plan.request.observationEpoch,
            query: query
        )
        guard sameExecutionContext(plan.baseline, current) else { return nil }
        let resolution = store.resolve(
            target: NativeActionTarget(
                snapshotID: plan.baseline.snapshotID,
                ref: original.ref,
                identifier: original.identifier,
                title: original.title,
                bundleID: plan.baseline.bundleID
            ),
            baseline: plan.baseline,
            current: current
        )
        guard case .success(let target) = resolution else { return nil }
        guard current.focusedElementRef == target.current.ref
                || target.current.focused == true else { return nil }
        return target
    }

    private func evaluate(
        _ group: NativeEffectGroup,
        before: NativeCapturedObservation,
        after: NativeCapturedObservation
    ) -> (matched: Bool, evidence: [[String: Any]], traceEvidence: [[String: Any]]) {
        let results = group.predicates.map { predicate -> (Bool, [String: Any]) in
            let matched = predicateMatches(predicate, before: before, after: after)
            return (matched, evidence(predicate.summary, matched, matched ? "matched" : "not_matched"))
        }
        let stateResults = zip(group.predicates, results)
            .filter { $0.0.kind != "notification" }
            .map(\.1)
        let matched: Bool
        if stateResults.isEmpty {
            matched = false
        } else if group.mode == "any" {
            matched = stateResults.contains(where: { $0.0 })
        } else {
            matched = stateResults.allSatisfy { $0.0 }
        }
        let traceEvidence = results.prefix(3).map { $0.1 }
        let receiptEvidence = matched
            ? stateResults.filter(\.0).prefix(3).map { $0.1 }
            : traceEvidence
        return (matched, receiptEvidence, traceEvidence)
    }

    private func predicateMatches(
        _ predicate: NativeEffectPredicate,
        before: NativeCapturedObservation,
        after: NativeCapturedObservation
    ) -> Bool {
        switch predicate.kind {
        case "frontmost_bundle_equals":
            return after.bundleID == predicate.expected
        case "window_count_delta":
            return after.windowCount - before.windowCount == predicate.expectedDelta
        case "window_title_equals":
            return after.windowTitle == predicate.expected
        case "window_title_changes":
            return after.windowTitle != before.windowTitle
        case "element_exists":
            return findNode(ref: predicate.ref, baseline: before, in: after) != nil
        case "element_disappears":
            return findNode(ref: predicate.ref, baseline: before, in: after) == nil
        case "element_attribute_equals":
            return findNode(ref: predicate.ref, baseline: before, in: after)?
                .attribute(predicate.attribute ?? "value") == predicate.expected
        case "element_attribute_changes":
            guard let baseline = predicate.baseline,
                  let afterValue = findNode(ref: predicate.ref, baseline: before, in: after)?
                    .attribute(predicate.attribute ?? "value") else { return false }
            return afterValue != baseline
        case "element_child_count_increases":
            guard let baselineCount = predicate.baseline.flatMap(Int.init),
                  let collection = findNode(ref: predicate.ref, baseline: before, in: after) else {
                return false
            }
            let afterCount = after.nodes.filter { $0.parentRef == collection.ref }.count
            return afterCount > baselineCount
        case "collection_descendant_role_count_increases":
            guard let baselineCount = predicate.baseline.flatMap(Int.init),
                  let collectionRoles = predicate.expected.map(roleSet),
                  let itemRoles = predicate.attribute.map(roleSet),
                  !collectionRoles.isEmpty, !itemRoles.isEmpty else { return false }
            let afterCount: Int
            if predicate.ref != nil {
                guard let collection = findNode(
                    ref: predicate.ref, baseline: before, in: after
                ) else { return false }
                afterCount = descendantCount(
                    of: collection, itemRoles: itemRoles, in: after)
            } else {
                afterCount = descendantCount(
                    collectionRoles: collectionRoles,
                    itemRoles: itemRoles,
                    in: after
                )
            }
            return afterCount > baselineCount
        case "element_attribute_increases", "element_attribute_decreases":
            guard let beforeValue = predicate.baseline.flatMap(Double.init),
                  let afterValue = findNode(ref: predicate.ref, baseline: before, in: after)?
                    .attribute(predicate.attribute ?? "value").flatMap(Double.init) else {
                return false
            }
            return predicate.kind == "element_attribute_increases"
                ? afterValue > beforeValue : afterValue < beforeValue
        case "focused_element_equals":
            guard let node = findNode(ref: predicate.ref, baseline: before, in: after) else {
                return false
            }
            return node.ref == after.focusedElementRef || node.focused == true
        case "text_contains":
            guard let expected = predicate.expected else { return false }
            return findNode(ref: predicate.ref, baseline: before, in: after)?
                .redactedValue?.contains(expected) == true
        case "text_hash_equals":
            guard let expected = predicate.expected else { return false }
            return findNode(ref: predicate.ref, baseline: before, in: after)?
                .valueHash == expected
        case "clipboard_hash_equals":
            return after.clipboardHash == predicate.expected
        case "notification":
            guard let notification = predicate.notification else { return false }
            return after.notifications.contains(notification)
        default:
            return false
        }
    }

    private func bindBaselines(
        _ group: NativeEffectGroup,
        in snapshot: NativeCapturedObservation
    ) -> NativeEffectGroup {
        var copy = group
        copy.predicates = group.predicates.map { predicate in
            var bound = predicate
            if ["element_attribute_changes", "element_attribute_increases",
                "element_attribute_decreases"].contains(predicate.kind) {
                bound.baseline = findNode(ref: predicate.ref, baseline: snapshot, in: snapshot)?
                    .attribute(predicate.attribute ?? "value")
            }
            if predicate.kind == "element_child_count_increases",
               let ref = predicate.ref {
                bound.baseline = String(
                    snapshot.nodes.filter { $0.parentRef == ref }.count)
            }
            if predicate.kind == "collection_descendant_role_count_increases",
               let collectionRoles = predicate.expected.map(roleSet),
               let itemRoles = predicate.attribute.map(roleSet) {
                if let ref = predicate.ref,
                   let collection = snapshot.nodes.first(where: { $0.ref == ref }) {
                    bound.baseline = String(descendantCount(
                        of: collection, itemRoles: itemRoles, in: snapshot))
                } else if predicate.ref == nil {
                    bound.baseline = String(descendantCount(
                        collectionRoles: collectionRoles,
                        itemRoles: itemRoles,
                        in: snapshot))
                }
            }
            return bound
        }
        return copy
    }

    private func effectBindingsAreValid(
        _ group: NativeEffectGroup,
        in snapshot: NativeCapturedObservation
    ) -> Bool {
        let refKinds = Set([
            "element_exists", "element_disappears", "element_attribute_equals",
            "element_attribute_changes", "element_attribute_increases",
            "element_attribute_decreases", "focused_element_equals",
            "text_contains", "text_hash_equals",
            "element_child_count_increases",
        ])
        let expectedKinds = Set([
            "frontmost_bundle_equals", "window_title_equals",
            "element_attribute_equals", "text_contains", "text_hash_equals",
            "clipboard_hash_equals",
        ])
        let allowedAttributes = Set([
            "value", "axvalue", "title", "axtitle", "enabled", "axenabled",
            "focused", "axfocused", "selected", "axselected", "expanded",
            "axexpanded", "visible",
        ])
        for predicate in group.predicates {
            if predicate.kind == "element_disappears" { return false }
            if refKinds.contains(predicate.kind) {
                guard let ref = predicate.ref,
                      snapshot.nodes.filter({ $0.ref == ref }).count == 1 else { return false }
            }
            if expectedKinds.contains(predicate.kind), predicate.expected == nil { return false }
            if predicate.kind == "window_count_delta", predicate.expectedDelta == nil { return false }
            if predicate.kind.hasPrefix("element_attribute_") {
                guard let attribute = predicate.attribute?.lowercased(),
                      allowedAttributes.contains(attribute) else { return false }
            }
            if predicate.kind == "notification", predicate.notification?.isEmpty != false {
                return false
            }
            if predicate.kind == "collection_descendant_role_count_increases" {
                guard let collectionRoles = predicate.expected.map(roleSet),
                      let itemRoles = predicate.attribute.map(roleSet),
                      !collectionRoles.isEmpty, !itemRoles.isEmpty else { return false }
                if let ref = predicate.ref,
                   snapshot.nodes.filter({ $0.ref == ref }).count != 1 {
                    return false
                }
            }
        }
        return true
    }

    private func roleSet(_ value: String) -> Set<String> {
        Set(value.split(separator: ",").map(String.init).filter { !$0.isEmpty })
    }

    private func descendantCount(
        of collection: NativeObservationNode,
        itemRoles: Set<String>,
        in snapshot: NativeCapturedObservation
    ) -> Int {
        snapshot.nodes.filter {
            itemRoles.contains($0.role)
                && isDescendant($0, of: collection.ref, in: snapshot)
        }.count
    }

    private func descendantCount(
        collectionRoles: Set<String>,
        itemRoles: Set<String>,
        in snapshot: NativeCapturedObservation
    ) -> Int {
        let collectionRefs = Set(snapshot.nodes.filter {
            collectionRoles.contains($0.role)
        }.map(\.ref))
        return snapshot.nodes.filter { node in
            itemRoles.contains(node.role) && collectionRefs.contains { ref in
                isDescendant(node, of: ref, in: snapshot)
            }
        }.count
    }

    private func isDescendant(
        _ node: NativeObservationNode,
        of ancestorRef: String,
        in snapshot: NativeCapturedObservation
    ) -> Bool {
        var parentRef = node.parentRef
        var visited: Set<String> = []
        while let ref = parentRef, visited.insert(ref).inserted {
            if ref == ancestorRef { return true }
            parentRef = snapshot.nodes.first(where: { $0.ref == ref })?.parentRef
        }
        return false
    }

    private func desiredEffectTargetsAction(
        _ group: NativeEffectGroup,
        request: NativeActionRequest,
        target: NativeObservationNode?
    ) -> Bool {
        let statePredicates = group.predicates.filter { $0.kind != "notification" }
        switch request.operation {
        case .openApp, .switchApp:
            guard let bundleID = request.payload.bundleID else { return false }
            return statePredicates.allSatisfy {
                $0.kind == "frontmost_bundle_equals" && $0.expected == bundleID
            }
        case .clipboardWrite:
            guard let text = request.payload.text else { return false }
            let expectedHash = NativeHash.sha256(text)
            return statePredicates.allSatisfy {
                $0.kind == "clipboard_hash_equals" && $0.expected == expectedHash
            }
        case .focusTab, .scroll, .setText, .press:
            guard let target else { return false }
            let targetKinds = Set([
                "element_exists", "element_attribute_equals", "element_attribute_changes",
                "element_attribute_increases", "element_attribute_decreases",
                "focused_element_equals", "text_contains", "text_hash_equals",
            ])
            return group.predicates.allSatisfy {
                ($0.kind == "notification" || targetKinds.contains($0.kind))
                    && $0.ref == target.ref
            }
        case .openURL, .menu, .keyChord, .semanticIntent:
            return false
        }
    }

    private func rebindEffect(
        _ group: NativeEffectGroup,
        from origin: NativeCapturedObservation,
        to current: NativeCapturedObservation
    ) -> NativeEffectGroup? {
        var rebound = group
        var predicates: [NativeEffectPredicate] = []
        for predicate in group.predicates {
            var copy = predicate
            if let ref = predicate.ref {
                let resolution = store.resolve(
                    target: NativeActionTarget(
                        snapshotID: origin.snapshotID,
                        ref: ref,
                        identifier: nil,
                        title: nil,
                        bundleID: origin.bundleID
                    ),
                    baseline: origin,
                    current: current
                )
                guard case .success(let target) = resolution else { return nil }
                copy.ref = target.current.ref
            }
            predicates.append(copy)
        }
        rebound.predicates = predicates
        return rebound
    }

    private func findNode(
        ref: String?,
        baseline: NativeCapturedObservation,
        in snapshot: NativeCapturedObservation
    ) -> NativeObservationNode? {
        guard let ref else { return nil }
        let resolution = store.resolve(
            target: NativeActionTarget(
                snapshotID: baseline.snapshotID,
                ref: ref,
                identifier: nil,
                title: nil,
                bundleID: baseline.bundleID
            ),
            baseline: baseline,
            current: snapshot
        )
        guard case .success(let target) = resolution else { return nil }
        return target.current
    }

    private func resolveForPreparation(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation
    ) -> Result<NativeObservationNode?, NativeResolutionError> {
        guard operationNeedsTarget(request.operation) else { return .success(nil) }
        let candidates: [NativeObservationNode]
        if request.operation == .menu, !request.payload.menuPath.isEmpty {
            candidates = menuCandidates(path: request.payload.menuPath, in: baseline)
        } else if let ref = request.target.ref {
            candidates = baseline.nodes.filter { $0.ref == ref }
        } else if let identifier = request.target.identifier {
            candidates = baseline.nodes.filter { $0.identifier == identifier }
        } else if let title = request.target.title {
            candidates = baseline.nodes.filter {
                ($0.title ?? "").localizedCaseInsensitiveCompare(title) == .orderedSame
            }
        } else if request.operation == .menu,
                  let leaf = request.payload.menuPath.last {
            candidates = baseline.nodes.filter {
                ($0.title ?? "").localizedCaseInsensitiveCompare(leaf) == .orderedSame
            }
        } else {
            return .failure(.missingTarget)
        }
        if candidates.count == 1 { return .success(candidates[0]) }
        return .failure(candidates.isEmpty ? .missingTarget : .ambiguous)
    }

    private func operationNeedsTarget(_ operation: NativeActionOperation) -> Bool {
        switch operation {
        case .focusTab, .scroll, .setText, .press: return true
        case .openApp, .switchApp, .openURL, .clipboardWrite, .menu, .keyChord,
             .semanticIntent:
            return false
        }
    }

    // Generic verb-object grammar for the create family. Kinds are
    // app-agnostic word classes, never bundle-keyed command tables; a kind
    // only compiles when the current app exposes a matching live menu leaf.
    private static let createKindSynonyms: [String: [String]] = [
        "tab": ["tab"],
        "window": ["window"],
        "document": ["document", "file"],
        "note": ["note"],
        "folder": ["folder"],
    ]

    // Collections whose children form a selection for select_relative.
    private static let selectionParentRoles: [String: Set<String>] = [
        "tab": ["AXTabGroup", "AXRadioGroup"],
        "document": ["AXTable", "AXOutline", "AXList", "AXCollection"],
        "note": ["AXTable", "AXOutline", "AXList"],
        "item": ["AXTable", "AXOutline", "AXList", "AXTabGroup",
                 "AXCollection", "AXRadioGroup"],
    ]

    private struct CreateCollectionShape {
        let collectionRoles: Set<String>
        let itemRoles: Set<String>
    }

    private static let createCollectionShapes: [String: CreateCollectionShape] = [
        "tab": CreateCollectionShape(
            collectionRoles: ["AXTabGroup", "AXRadioGroup", "AXOpaqueProviderGroup"],
            itemRoles: ["AXRadioButton"]),
        "note": CreateCollectionShape(
            collectionRoles: ["AXTable", "AXList"],
            itemRoles: ["AXRow"]),
    ]

    private struct IntentLoweringFailure: Error {
        let plan: [String: Any]
    }

    private struct LoweredIntent {
        let request: NativeActionRequest
        let candidates: [[String: Any]]
        var witness: NativeEffectGroup?
    }

    private func lowerSemanticIntent(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation
    ) -> Result<LoweredIntent, IntentLoweringFailure> {
        switch request.payload.intentFamily {
        case "create":
            return lowerCreate(request: request, baseline: baseline)
        case "select_relative":
            return lowerSelectRelative(request: request, baseline: baseline)
        default:
            return .failure(IntentLoweringFailure(plan: failurePlan("unsupported_intent")))
        }
    }

    private func lowerCreate(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation
    ) -> Result<LoweredIntent, IntentLoweringFailure> {
        guard let kind = request.payload.intentKind,
              let synonyms = Self.createKindSynonyms[kind] else {
            return .failure(IntentLoweringFailure(plan: failurePlan("unsupported_intent")))
        }
        let wanted = synonyms.map { "new \($0)" }
        let leaves = baseline.nodes.filter { node in
            node.role == "AXMenuItem"
                && node.enabled != false
                && wanted.contains(normalize(node.title))
        }
        guard let leaf = leaves.first else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_live_affordance")))
        }
        let paths = Set(leaves.map { menuPathTitles(to: $0, in: baseline) })
        guard paths.count == 1 else {
            return .failure(IntentLoweringFailure(plan: failurePlan("ambiguous_intent", outcome: .ambiguous)))
        }
        var lowered = request
        lowered.operation = .menu
        lowered.payload.menuPath = menuPathTitles(to: leaf, in: baseline)
            .split(separator: "\u{1e}").map(String.init)
        let candidates: [[String: Any]] = leaves.map { node in
            var candidate: [String: Any] = [
                "title": node.title ?? "", "role": node.role,
                "strategy_class": "menu",
            ]
            candidate.put("shortcut", node.menuShortcut)
            return candidate
        }
        return .success(LoweredIntent(
            request: lowered,
            candidates: Array(candidates.prefix(20)),
            witness: createWitness(kind: kind, baseline: baseline)
        ))
    }

    /// Causal witness for a create intent: the collection the new item
    /// lands in must grow, or a new window must appear. With neither
    /// available the plan truthfully caps at dispatch_only.
    private func createWitness(
        kind: String,
        baseline: NativeCapturedObservation
    ) -> NativeEffectGroup? {
        if kind == "window" {
            return NativeEffectGroup(mode: "all", predicates: [
                NativeEffectPredicate(kind: "window_count_delta",
                                      expectedDelta: 1),
            ])
        }
        if let shape = Self.createCollectionShapes[kind] {
            let collections = baseline.nodes.filter { node in
                shape.collectionRoles.contains(node.role)
                    && descendantCount(
                        of: node, itemRoles: shape.itemRoles, in: baseline) > 0
            }
            guard collections.count == 1, let collection = collections.first else {
                return nil
            }
            return NativeEffectGroup(mode: "all", predicates: [
                NativeEffectPredicate(
                    kind: "collection_descendant_role_count_increases",
                    ref: collection.ref,
                    attribute: shape.itemRoles.sorted().joined(separator: ","),
                    expected: shape.collectionRoles.sorted().joined(separator: ",")
                ),
            ])
        }
        guard let roles = Self.selectionParentRoles[kind] else { return nil }
        let collections = baseline.nodes.filter { roles.contains($0.role) }
        guard collections.count == 1, let collection = collections.first else {
            return nil
        }
        return NativeEffectGroup(mode: "all", predicates: [
            NativeEffectPredicate(kind: "element_child_count_increases",
                                  ref: collection.ref),
        ])
    }

    private func menuPathTitles(
        to leaf: NativeObservationNode,
        in snapshot: NativeCapturedObservation
    ) -> String {
        var titles: [String] = leaf.title.map { [$0] } ?? []
        var parent = leaf.parentRef
        while let parentRef = parent,
              let ancestor = snapshot.nodes.first(where: { $0.ref == parentRef }) {
            if let title = ancestor.title, !title.isEmpty {
                titles.insert(title, at: 0)
            }
            parent = ancestor.parentRef
        }
        return titles.joined(separator: "\u{1e}")
    }

    private func lowerSelectRelative(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation
    ) -> Result<LoweredIntent, IntentLoweringFailure> {
        guard let relation = request.payload.intentRelation,
              relation == "next" || relation == "previous" else {
            return .failure(IntentLoweringFailure(plan: failurePlan("unsupported_intent")))
        }
        let roles: Set<String>
        if let kind = request.payload.intentKind {
            guard let kindRoles = Self.selectionParentRoles[kind] else {
                return .failure(IntentLoweringFailure(plan: failurePlan("unsupported_intent")))
            }
            roles = kindRoles
        } else {
            roles = Set(Self.selectionParentRoles.values.flatMap { $0 })
        }
        let collectionRefs = Set(
            baseline.nodes.filter { roles.contains($0.role) }.map(\.ref))
        let selected = baseline.nodes.filter { node in
            node.selected == true
                && node.parentRef.map(collectionRefs.contains) == true
        }
        guard selected.count <= 1 else {
            return .failure(IntentLoweringFailure(plan: failurePlan("ambiguous_intent", outcome: .ambiguous)))
        }
        guard let current = selected.first else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_current_selection")))
        }
        let siblings = baseline.nodes.filter {
            $0.parentRef == current.parentRef && $0.role == current.role
        }
        guard let index = siblings.firstIndex(where: { $0.ref == current.ref }) else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_current_selection")))
        }
        let targetIndex = index + (relation == "next" ? 1 : -1)
        guard siblings.indices.contains(targetIndex) else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_relative_item")))
        }
        let sibling = siblings[targetIndex]
        var lowered = request
        lowered.operation = .focusTab
        lowered.target = NativeActionTarget(
            snapshotID: nil,
            ref: sibling.ref,
            identifier: sibling.identifier,
            title: nil,
            bundleID: request.target.bundleID
        )
        let candidates: [[String: Any]] = [[
            "title": sibling.title ?? "", "role": sibling.role,
            "strategy_class": "semantic_selection",
        ]]
        return .success(LoweredIntent(request: lowered, candidates: candidates))
    }

    private func executionNeedsTarget(_ operation: NativeActionOperation) -> Bool {
        operationNeedsTarget(operation)
    }

    private func menuCandidates(
        path: [String],
        in snapshot: NativeCapturedObservation
    ) -> [NativeObservationNode] {
        guard let leaf = path.last else { return [] }
        return snapshot.nodes.filter { node in
            guard normalize(node.title) == normalize(leaf) else { return false }
            var titles: [String] = []
            var parent = node.parentRef
            while let parentRef = parent,
                  let ancestor = snapshot.nodes.first(where: { $0.ref == parentRef }) {
                if let title = ancestor.title, !title.isEmpty { titles.append(normalize(title)) }
                parent = ancestor.parentRef
            }
            let expectedAncestors = path.dropLast().reversed().map(normalize)
            var index = 0
            for title in titles where index < expectedAncestors.count {
                if title == expectedAncestors[index] { index += 1 }
            }
            return index == expectedAncestors.count
        }
    }

    private func normalize(_ value: String?) -> String {
        (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }

    private func derivedEffect(
        request: NativeActionRequest,
        target: NativeObservationNode?,
        baseline: NativeCapturedObservation
    ) -> NativeEffectGroup {
        let predicate: NativeEffectPredicate?
        switch request.operation {
        case .openApp, .switchApp:
            predicate = request.payload.bundleID.map {
                NativeEffectPredicate(kind: "frontmost_bundle_equals", expected: $0)
            }
        case .openURL:
            predicate = nil
        case .clipboardWrite:
            predicate = request.payload.text.map {
                NativeEffectPredicate(kind: "clipboard_hash_equals", expected: NativeHash.sha256($0))
            }
        case .focusTab:
            predicate = target.map {
                NativeEffectPredicate(kind: "element_attribute_equals", ref: $0.ref,
                                      attribute: "selected", expected: "true")
            }
        case .scroll:
            predicate = target.map { target in
                if target.supportedActions.contains("AXScrollToVisible") {
                    return NativeEffectPredicate(
                        kind: "element_attribute_equals",
                        ref: target.ref,
                        attribute: "visible",
                        expected: "true"
                    )
                }
                let decreasing = request.payload.direction == "up"
                    || request.payload.direction == "left"
                return NativeEffectPredicate(
                    kind: decreasing
                        ? "element_attribute_decreases" : "element_attribute_increases",
                    ref: target.ref,
                    attribute: "value"
                )
            }
        case .setText where request.payload.submit:
            predicate = nil
        case .setText:
            predicate = target.flatMap { target in
                request.payload.text.map {
                    NativeEffectPredicate(kind: "text_hash_equals", ref: target.ref,
                                          expected: NativeHash.sha256($0))
                }
            }
        case .press:
            if let target, target.role == "AXCheckBox" || target.role == "AXRadioButton" {
                predicate = NativeEffectPredicate(
                    kind: "element_attribute_changes",
                    ref: target.ref,
                    attribute: "value"
                )
            } else {
                predicate = nil
            }
        case .menu, .keyChord, .semanticIntent:
            predicate = nil
        }
        return NativeEffectGroup(mode: "all", predicates: predicate.map { [$0] } ?? [])
    }

    private func compileStrategies(
        request: NativeActionRequest,
        target: NativeObservationNode?
    ) -> [NativeActionStrategy] {
        switch request.operation {
        case .openApp, .switchApp, .openURL: return [.launchServices]
        case .clipboardWrite: return [.pasteboard]
        case .focusTab:
            var strategies: [NativeActionStrategy] = []
            if target?.settableAttributes.contains("AXSelected") == true {
                strategies.append(.axSetSelected)
            }
            if target?.supportedActions.contains("AXPress") == true {
                strategies.append(.axPress)
            }
            return strategies
        case .scroll:
            var strategies: [NativeActionStrategy] = []
            if target?.supportedActions.contains("AXScrollToVisible") == true {
                strategies.append(.axScrollToVisible)
            }
            if target?.settableAttributes.contains("AXValue") == true,
               let direction = request.payload.direction,
               ["up", "down", "left", "right"].contains(direction),
               let amount = request.payload.amount,
               amount > 0 {
                strategies.append(.axSetValue)
            }
            return strategies
        case .setText:
            guard target?.secure != true else { return [] }
            var strategies: [NativeActionStrategy] = []
            if target?.settableAttributes.contains("AXValue") == true {
                strategies.append(.axSetValue)
            }
            if request.strategyCeiling == "semantic_plus_events" {
                strategies.append(.unicodeText)
            }
            return strategies
        case .press:
            return target?.supportedActions.contains("AXPress") == true ? [.axPress] : []
        case .menu:
            return request.payload.menuPath.isEmpty
                ? [] : [.axMenuAction, .liveMenuShortcut]
        case .keyChord:
            return request.payload.keys.isEmpty ? [] : [.keyChord]
        case .semanticIntent:
            return []  // lowered before planning; unreachable by construction
        }
    }

    private func planFingerprint(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation,
        target: NativeObservationNode?,
        effect: NativeEffectGroup,
        strategies: [NativeActionStrategy]
    ) -> String {
        NativeHash.sha256([
            request.turnID,
            String(request.responseEpoch),
            String(request.observationEpoch),
            baseline.bundleID ?? "",
            baseline.processStartIdentity ?? "",
            String(baseline.windowID ?? 0),
            target?.semanticFingerprint ?? "",
            request.operation.rawValue,
            request.payload.hash,
            effect.summary,
            strategies.map(\.rawValue).joined(separator: ","),
            request.risk,
        ].joined(separator: "\u{1e}"))
    }

    private func previewText(request: NativeActionRequest, target: String) -> String {
        switch request.operation {
        case .openApp: return "Open \(target)"
        case .switchApp: return "Switch to \(target)"
        case .openURL: return "Open the requested location"
        case .clipboardWrite: return "Copy \(request.payload.text?.count ?? 0) characters"
        case .focusTab: return "Focus \(target)"
        case .scroll: return "Scroll \(target)"
        case .setText: return "Enter text in \(target)"
        case .press: return "Press \(target)"
        case .menu: return "Choose \(target)"
        case .keyChord: return "Send the approved shortcut"
        case .semanticIntent: return "Perform the requested action"
        }
    }

    private func failurePlan(
        _ reason: String,
        outcome: NativeActionOutcome = .failed
    ) -> [String: Any] {
        [
            "outcome": outcome.rawValue,
            "ok": false,
            "dispatch_state": NativeDispatchState.notDispatched.rawValue,
            "retry_safe": true,
            "error": reason,
            "lane": "semantic",
        ]
    }

    func preparedPlanCount() -> Int {
        plans.count
    }

    func invalidatePlans() {
        plans.removeAll()
    }

    private func prunePlans(turnID: String, observationEpoch: Int) {
        let now = NativeClock.ms()
        plans = plans.filter {
            $0.value.request.turnID == turnID
                && $0.value.request.observationEpoch == observationEpoch
                && now - $0.value.createdMs <= planTTLms
        }
        prunePlanLimit()
    }

    private func prunePlanLimit() {
        guard plans.count > planLimit else { return }
        for plan in plans.values.sorted(by: { $0.createdMs < $1.createdMs })
            .prefix(plans.count - planLimit) {
            plans.removeValue(forKey: plan.fingerprint)
        }
    }

    private func sameExecutionContext(
        _ baseline: NativeCapturedObservation,
        _ current: NativeCapturedObservation
    ) -> Bool {
        guard baseline.bundleID == current.bundleID,
              baseline.pid == current.pid,
              baseline.processStartIdentity == current.processStartIdentity else {
            return false
        }
        return baseline.windowID == nil || baseline.windowID == current.windowID
    }

    private func requiresStableExecutionContext(
        _ operation: NativeActionOperation
    ) -> Bool {
        switch operation {
        case .focusTab, .scroll, .setText, .press, .menu, .keyChord: return true
        case .openApp, .switchApp, .openURL, .clipboardWrite, .semanticIntent:
            return false
        }
    }

    private func requestBindsApplication(_ request: NativeActionRequest) -> Bool {
        request.payload.bundleID != nil
    }

    private func browserBundle(_ bundleID: String?) -> Bool {
        guard let bundleID else { return false }
        return bundleID == "com.apple.Safari"
            || bundleID == "com.google.Chrome"
            || bundleID.hasPrefix("org.mozilla.firefox")
            || bundleID.hasPrefix("com.microsoft.edgemac")
            || bundleID.hasPrefix("company.thebrowser.Browser")
    }

    private func receipt(
        outcome: NativeActionOutcome,
        dispatch: NativeDispatchState,
        plan: NativeActionPlan?,
        strategy: NativeActionStrategy?,
        evidence: [[String: Any]],
        nativeError: String?,
        started: Int,
        after: NativeCapturedObservation? = nil,
        traceEvidence: [[String: Any]]? = nil
    ) -> [String: Any] {
        var result: [String: Any] = [
            "outcome": outcome.rawValue,
            "ok": outcome == .verified,
            "dispatch_state": dispatch.rawValue,
            "strategy": strategy?.rawValue ?? "none",
            "lane": "semantic",
            "target": plan?.safeTarget ?? "unknown",
            "effect": plan?.effect.summary ?? "none",
            "evidence": Array(evidence.prefix(3)),
            "retry_safe": dispatch == .notDispatched,
            "duration_ms": max(NativeClock.ms() - started, 0),
            "notifications": after?.notifications ?? [],
        ]
        result.put("plan_fingerprint", plan?.fingerprint)
        result.put("before_digest", plan?.baseline.digest)
        result.put("after_digest", after?.digest)
        result.put("native_error", nativeError)
        var traceData: [String: Any] = [
            "notifications": after?.notifications ?? [],
            "authorized_strategies": plan?.strategies.map(\.rawValue) ?? [],
            "selected_strategy": strategy?.rawValue ?? "none",
            "predicate_results": Array((traceEvidence ?? evidence).prefix(3)),
        ]
        traceData.put("plan_fingerprint", plan?.fingerprint)
        traceData.put("before_digest", plan?.baseline.digest)
        traceData.put("after_digest", after?.digest)
        traceData.put("target_fingerprint", plan?.target?.semanticFingerprint)
        traceData.put("native_error", nativeError)
        result["data"] = traceData
        return result
    }

    private func evidence(_ predicate: String, _ matched: Bool, _ detail: String) -> [String: Any] {
        ["predicate": predicate, "matched": matched, "detail": detail]
    }
}
