import Foundation

struct NativeActionPlan {
    static let ttlMs = 45_000

    var fingerprint: String
    var request: NativeActionRequest
    var baseline: NativeCapturedObservation
    var target: NativeObservationNode?
    var effect: NativeEffectGroup
    var strategies: [NativeActionStrategy]
    var safeTarget: String
    var preview: String
    var createdMs: Int
    var effectClass: NativeEffectClass
}

final class NativeEffectEvaluator {
    private let store: NativeObservationStore

    init(store: NativeObservationStore) {
        self.store = store
    }

    private func evidence(
        _ predicate: String,
        _ matched: Bool,
        _ detail: String
    ) -> [String: Any] {
        ["predicate": predicate, "matched": matched, "detail": detail]
    }

    func evaluate(
        _ group: NativeEffectGroup,
        before: NativeCapturedObservation,
        after: NativeCapturedObservation
    ) -> (matched: Bool, evidence: [[String: Any]], traceEvidence: [[String: Any]]) {
        let results = group.predicates.map { predicate -> (Bool, [String: Any]) in
            let matched = predicateMatches(predicate, before: before, after: after)
            var result = evidence(
                predicate.summary,
                matched,
                matched ? "matched" : "not_matched"
            )
            result["baseline"] = predicateMeasurement(
                predicate, snapshot: before, baseline: before
            )
            result["current"] = predicateMeasurement(
                predicate, snapshot: after, baseline: before
            )
            result["match_rule"] = predicate.kind
            return (matched, result)
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

    func predicateMeasurement(
        _ predicate: NativeEffectPredicate,
        snapshot: NativeCapturedObservation,
        baseline: NativeCapturedObservation
    ) -> String {
        switch predicate.kind {
        case "frontmost_bundle_equals": return snapshot.bundleID ?? "none"
        case "document_url_equals": return snapshot.documentURL.map(NativeHash.sha256) ?? "none"
        case "window_count_delta": return String(snapshot.windowCount)
        case "window_title_equals", "window_title_changes":
            return snapshot.windowTitle.map(NativeHash.sha256) ?? "none"
        case "element_exists", "element_disappears":
            return findNode(ref: predicate.ref, baseline: baseline, in: snapshot) == nil
                ? "absent" : "present"
        case "element_attribute_equals", "element_attribute_changes",
             "element_attribute_increases", "element_attribute_decreases":
            return findNode(ref: predicate.ref, baseline: baseline, in: snapshot)?
                .attribute(predicate.attribute ?? "value") ?? "unavailable"
        case "element_child_count_increases":
            guard let collection = findNode(
                ref: predicate.ref, baseline: baseline, in: snapshot
            ) else { return "unavailable" }
            return String(snapshot.nodes.filter { $0.parentRef == collection.ref }.count)
        case "collection_descendant_role_count_increases":
            guard let itemRoles = predicate.attribute.map(roleSet) else {
                return "unavailable"
            }
            if let collection = findCollectionNode(
                ref: predicate.ref, baseline: baseline, in: snapshot
            ) {
                return String(descendantCount(
                    of: collection, itemRoles: itemRoles, in: snapshot
                ))
            }
            guard let collectionRoles = predicate.expected.map(roleSet) else {
                return "unavailable"
            }
            return String(descendantCount(
                collectionRoles: collectionRoles,
                itemRoles: itemRoles,
                in: snapshot
            ))
        case "focused_element_equals":
            guard let node = findNode(
                ref: predicate.ref, baseline: baseline, in: snapshot
            ) else { return "absent" }
            return node.ref == snapshot.focusedElementRef || node.focused == true
                ? "focused" : "not_focused"
        case "text_contains", "text_hash_equals":
            return findNode(ref: predicate.ref, baseline: baseline, in: snapshot)?
                .valueHash ?? "unavailable"
        case "clipboard_hash_equals": return snapshot.clipboardHash ?? "none"
        case "notification":
            guard let notification = predicate.notification else { return "unavailable" }
            return snapshot.notifications.contains(notification) ? "present" : "absent"
        default: return "unavailable"
        }
    }

    func predicateMatches(
        _ predicate: NativeEffectPredicate,
        before: NativeCapturedObservation,
        after: NativeCapturedObservation
    ) -> Bool {
        switch predicate.kind {
        case "frontmost_bundle_equals":
            return after.bundleID == predicate.expected
        case "document_url_equals":
            return after.documentURL.flatMap(NativeActionCompiler.normalizeBrowserURL)
                == predicate.expected
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
                guard let collection = findCollectionNode(
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

    func bindBaselines(
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

    func effectBindingsAreValid(
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

    func roleSet(_ value: String) -> Set<String> {
        Set(value.split(separator: ",").map(String.init).filter { !$0.isEmpty })
    }

    func descendantCount(
        of collection: NativeObservationNode,
        itemRoles: Set<String>,
        in snapshot: NativeCapturedObservation
    ) -> Int {
        snapshot.nodes.filter {
            itemRoles.contains($0.role)
                && isDescendant($0, of: collection.ref, in: snapshot)
        }.count
    }

    func descendantCount(
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

    func isDescendant(
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

    func desiredEffectTargetsAction(
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
        case .openURL, .navigate, .menu, .keyChord, .semanticIntent:
            return false
        }
    }

    func rebindEffect(
        _ group: NativeEffectGroup,
        from origin: NativeCapturedObservation,
        to current: NativeCapturedObservation
    ) -> NativeEffectGroup? {
        var rebound = group
        var predicates: [NativeEffectPredicate] = []
        for predicate in group.predicates {
            var copy = predicate
            if let ref = predicate.ref {
                let resolution = store.resolveWitness(
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

    func findNode(
        ref: String?,
        baseline: NativeCapturedObservation,
        in snapshot: NativeCapturedObservation
    ) -> NativeObservationNode? {
        guard let ref else { return nil }
        let resolution = store.resolveWitness(
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

    func findCollectionNode(
        ref: String?,
        baseline: NativeCapturedObservation,
        in snapshot: NativeCapturedObservation
    ) -> NativeObservationNode? {
        guard let ref else { return nil }
        let resolution = store.resolveCollectionWitness(
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
}

struct NativeTransactionExecutor {
    private let backend: NativeSemanticBackend
    private let store: NativeObservationStore
    private let compiler: NativeActionCompiler
    private let evaluator: NativeEffectEvaluator
    private let executionInterlock: NativeExecutionInterlock?

    init(
        backend: NativeSemanticBackend,
        store: NativeObservationStore,
        compiler: NativeActionCompiler,
        evaluator: NativeEffectEvaluator,
        executionInterlock: NativeExecutionInterlock?
    ) {
        self.backend = backend
        self.store = store
        self.compiler = compiler
        self.evaluator = evaluator
        self.executionInterlock = executionInterlock
    }

    func execute(
        _ params: [String: Any],
        plan: NativeActionPlan?
    ) async -> [String: Any] {
        let started = NativeClock.ms()
        guard let plan else {
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
        let fingerprint = params["plan_fingerprint"] as? String ?? ""
        guard NativeClock.ms() - plan.createdMs <= NativeActionPlan.ttlMs else {
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
        let deadline = started + plan.request.timeoutMs
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
        if executionInterlock != nil,
           (params["navigation_generation"] as? Int != plan.request.navigationGeneration
            || params["execution_connection_id"] as? String
                != plan.request.executionConnectionID) {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("navigation_grant", false, "generation_changed")],
                nativeError: "stale_grant",
                started: started
            )
        }

        let query = NativeObservationQuery(
            bundleID: nil,
            pid: nil,
            includeMenu: plan.request.operation == .menu,
            maxNodes: plan.request.operation == .menu ? 500 : 300,
            maxDepth: 16,
            deniedBundles: plan.request.deniedBundles,
            deadlineMs: deadline
        )
        let current = store.observe(
            turnID: plan.request.turnID,
            observationEpoch: plan.request.observationEpoch,
            query: query
        )
        if NativeClock.ms() >= deadline {
            return receipt(
                outcome: .failed,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("deadline", false, "expired_before_dispatch")],
                nativeError: "native_transaction_timeout",
                started: started,
                after: current
            )
        }
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
        if ![.openApp, .switchApp, .navigate].contains(plan.request.operation),
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
        if plan.request.operation == .keyChord,
           let reason = compiler.keyFocusRefusal(current) {
            return receipt(
                outcome: .blocked,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("secure_focus", false, reason)],
                nativeError: reason,
                started: started
            )
        }
        let preDispatchEffect = evaluator.evaluate(
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
                    bundleID: plan.baseline.bundleID,
                    descendantKey: plan.request.target.descendantKey
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
                   compiler.isInstalledBrowser(current.bundleID),
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
                let outcome: NativeActionOutcome
                if error == .ambiguous {
                    outcome = .ambiguous
                } else if error == .secureTransition {
                    outcome = .blocked
                } else {
                    outcome = .failed
                }
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

        if let binding = plan.request.applicationBinding,
           !backend.applicationBindingMatches(binding) {
            return receipt(
                outcome: .blocked,
                dispatch: .notDispatched,
                plan: plan,
                strategy: nil,
                evidence: [evidence("app_identity", false, "changed_after_plan")],
                nativeError: "app_identity_mismatch",
                started: started
            )
        }

        backend.beginEvidenceObservation(request: plan.request, target: resolved)
        var selectedStrategy: NativeActionStrategy?
        var dispatchResult = NativeDispatchResult(state: .notDispatched, nativeError: "no_strategy")
        for (index, strategy) in plan.strategies.prefix(2).enumerated() {
            if NativeClock.ms() >= deadline {
                return receipt(
                    outcome: .failed,
                    dispatch: .notDispatched,
                    plan: plan,
                    strategy: selectedStrategy,
                    evidence: [evidence("deadline", false, "expired_before_dispatch")],
                    nativeError: "native_transaction_timeout",
                    started: started,
                    after: current
                )
            }
            if let refusal = executionRefusal(plan: plan, dispatch: .notDispatched, started: started) {
                return refusal
            }
            selectedStrategy = strategy
            dispatchResult = backend.dispatch(
                strategy: strategy,
                request: plan.request,
                target: resolved
            )
            if dispatchResult.state != .notDispatched || index == 1 { break }
        }
        if dispatchResult.state != .notDispatched, NativeClock.ms() >= deadline {
            return receipt(
                outcome: .failed,
                dispatch: .possiblyDispatched,
                plan: plan,
                strategy: selectedStrategy,
                evidence: [evidence("deadline", false, "expired_after_dispatch")],
                nativeError: "native_transaction_timeout",
                started: started,
                after: current
            )
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
            let verificationQuery = verificationQuery(
                for: plan,
                deadline: deadline
            )
            let textVerification = await verify(
                plan: textPlan, query: verificationQuery, deadline: deadline
            )
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
            if let refusal = executionRefusal(plan: plan, dispatch: .dispatched, started: started) {
                return refusal
            }
            if NativeClock.ms() >= deadline {
                return receipt(
                    outcome: .failed,
                    dispatch: .possiblyDispatched,
                    plan: plan,
                    strategy: selectedStrategy,
                    evidence: textVerification.evidence,
                    nativeError: "native_transaction_timeout",
                    started: started,
                    after: textVerification.after
                )
            }
            let submitResult = backend.dispatch(
                strategy: .keyChord,
                request: submitRequest,
                target: submitTarget
            )
            if NativeClock.ms() >= deadline {
                return receipt(
                    outcome: .failed,
                    dispatch: .possiblyDispatched,
                    plan: plan,
                    strategy: .keyChord,
                    evidence: textVerification.evidence,
                    nativeError: "native_transaction_timeout",
                    started: started,
                    after: textVerification.after
                )
            }
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

        let verification = await verify(
            plan: plan,
            query: verificationQuery(for: plan, deadline: deadline),
            deadline: deadline
        )
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
        if plan.request.operation == .navigate,
           verification.after.bundleID == plan.request.payload.bundleID,
           verification.after.documentURL == nil {
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
        query: NativeObservationQuery,
        deadline: Int
    ) async -> (
        matched: Bool,
        evidence: [[String: Any]],
        traceEvidence: [[String: Any]],
        after: NativeCapturedObservation
    ) {
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
               !verificationContextMatches(plan: plan, current: latest) {
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
            let evaluated = evaluator.evaluate(plan.effect, before: plan.baseline, after: latest)
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

    private func verificationQuery(
        for plan: NativeActionPlan,
        deadline: Int
    ) -> NativeObservationQuery {
        NativeObservationQuery(
            bundleID: nil,
            pid: requiresStableExecutionContext(plan.request.operation)
                ? plan.baseline.pid : nil,
            includeMenu: plan.request.operation == .menu,
            maxNodes: plan.request.operation == .menu ? 500 : 300,
            maxDepth: 16,
            deniedBundles: plan.request.deniedBundles,
            deadlineMs: deadline
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
                bundleID: plan.baseline.bundleID,
                descendantKey: plan.request.target.descendantKey
            ),
            baseline: plan.baseline,
            current: current
        )
        guard case .success(let target) = resolution else { return nil }
        guard current.focusedElementRef == target.current.ref
                || target.current.focused == true else { return nil }
        return target
    }

    private func executionNeedsTarget(_ operation: NativeActionOperation) -> Bool {
        switch operation {
        case .focusTab, .scroll, .setText, .press: return true
        case .openApp, .switchApp, .openURL, .navigate, .clipboardWrite, .menu,
             .keyChord, .semanticIntent:
            return false
        }
    }

    private func executionRefusal(
        plan: NativeActionPlan,
        dispatch: NativeDispatchState,
        started: Int
    ) -> [String: Any]? {
        guard let executionInterlock else { return nil }
        let check = executionInterlock.check(
            connectionID: plan.request.executionConnectionID,
            generation: plan.request.navigationGeneration
        )
        guard check != .allowed else { return nil }
        let reason: String
        switch check {
        case .suspended: reason = "execution_suspended"
        case .staleConnection: reason = "stale_execution_connection"
        case .staleGrant: reason = "stale_grant"
        case .allowed: return nil
        }
        return receipt(
            outcome: .failed,
            dispatch: dispatch,
            plan: plan,
            strategy: nil,
            evidence: [evidence("navigation_grant", false, reason)],
            nativeError: reason,
            started: started
        )
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

    private func verificationContextMatches(
        plan: NativeActionPlan,
        current: NativeCapturedObservation
    ) -> Bool {
        let permitsCreatedWindow = plan.request.operation == .menu
            && plan.request.payload.intentFamily == "create"
            && plan.request.payload.intentKind == "window"
            && plan.effect.predicates.count == 1
            && plan.effect.predicates[0].kind == "window_count_delta"
        guard permitsCreatedWindow else {
            return sameExecutionContext(plan.baseline, current)
        }
        return plan.baseline.bundleID == current.bundleID
            && plan.baseline.pid == current.pid
            && plan.baseline.processStartIdentity == current.processStartIdentity
    }

    private func requiresStableExecutionContext(
        _ operation: NativeActionOperation
    ) -> Bool {
        switch operation {
        case .focusTab, .scroll, .setText, .press, .menu, .keyChord: return true
        case .openApp, .switchApp, .openURL, .navigate, .clipboardWrite, .semanticIntent:
            return false
        }
    }

    private func requestBindsApplication(_ request: NativeActionRequest) -> Bool {
        request.payload.bundleID != nil
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
        result.put("reason_code", NativeReasonCode.value(
            outcome: outcome,
            nativeError: nativeError
        ))
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

extension NativeTransactionExecutor {
    static func executeVisual(
        _ params: [String: Any],
        plan: NativeVisualPlan?,
        provider: NativeVisualCaptureProvider,
        executionInterlock: NativeExecutionInterlock?
    ) async -> [String: Any] {
        let started = NativeClock.ms()
        guard let plan else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_plan_missing", plan: nil, started: started
            )
        }
        let deadline = started + plan.timeoutMs
        let generation = params["navigation_generation"] as? Int ?? -1
        let connectionID = params["execution_connection_id"] as? String ?? ""
        guard generation == plan.generation, connectionID == plan.connectionID else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_plan_stale", plan: plan, started: started
            )
        }
        if let executionInterlock {
            switch executionInterlock.check(
                connectionID: connectionID, generation: generation
            ) {
            case .allowed: break
            case .suspended:
                return visualReceipt(
                    outcome: "blocked", dispatch: .notDispatched,
                    reason: "navigation_suspended", plan: plan, started: started
                )
            case .staleConnection:
                return visualReceipt(
                    outcome: "failed", dispatch: .notDispatched,
                    reason: "app_connection_changed", plan: plan, started: started
                )
            case .staleGrant:
                return visualReceipt(
                    outcome: "failed", dispatch: .notDispatched,
                    reason: "navigation_lease_stale", plan: plan, started: started
                )
            }
        }
        guard NativeClock.ms() <= plan.capture.expiresMs else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_plan_stale", plan: plan, started: started
            )
        }
        let current: NativeVisualSource
        do {
            current = try await provider.capture(
                deniedBundles: plan.capture.deniedBundles
            )
        } catch let error as NativeVisualCaptureError {
            let reason: String
            switch error {
            case .secureSurface: reason = "secure_surface"
            case .deniedBundle: reason = "denied_bundle"
            case .screenRecordingDenied: reason = "screen_recording_denied"
            default: reason = "visual_plan_stale"
            }
            return visualReceipt(
                outcome: "blocked", dispatch: .notDispatched,
                reason: reason, plan: plan, started: started
            )
        } catch {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_plan_stale", plan: plan, started: started
            )
        }
        guard NativeClock.ms() < deadline else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "native_transaction_timeout", plan: plan, started: started
            )
        }
        guard Self.sameTarget(plan.capture.source, current) else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_plan_stale", plan: plan, started: started
            )
        }
        let point = NativeVisualGrounding.point(
            region: plan.grounding.region,
            windowFrame: current.windowFrame
        )
        guard point.x >= current.windowFrame.x,
              point.y >= current.windowFrame.y,
              point.x <= current.windowFrame.x + current.windowFrame.width,
              point.y <= current.windowFrame.y + current.windowFrame.height else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_point_out_of_bounds", plan: plan, started: started
            )
        }
        let beforeLabel = provider.accessibleLabel(at: point)
        if let beforeLabel,
           !Self.labelsAgree(beforeLabel, plan.grounding.label) {
            return visualReceipt(
                outcome: "blocked", dispatch: .notDispatched,
                reason: "visual_hit_test_conflict", plan: plan, started: started
            )
        }
        if let executionInterlock,
           executionInterlock.check(
               connectionID: connectionID, generation: generation
           ) != .allowed {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "visual_plan_stale", plan: plan, started: started
            )
        }
        guard NativeClock.ms() < deadline else {
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: "native_transaction_timeout", plan: plan, started: started
            )
        }
        let dispatch = provider.dispatch(input: plan.input, at: point)
        if dispatch.state != .notDispatched, NativeClock.ms() >= deadline {
            return visualReceipt(
                outcome: "failed", dispatch: .possiblyDispatched,
                reason: "native_transaction_timeout", plan: plan, started: started
            )
        }
        switch dispatch.state {
        case .notDispatched:
            return visualReceipt(
                outcome: "failed", dispatch: .notDispatched,
                reason: dispatch.nativeError ?? "native_input_failed",
                plan: plan, started: started
            )
        case .possiblyDispatched:
            return visualReceipt(
                outcome: "failed", dispatch: .possiblyDispatched,
                reason: dispatch.nativeError ?? "visual_dispatch_uncertain",
                plan: plan, started: started
            )
        case .dispatched:
            let afterLabel = provider.accessibleLabel(at: point)
            if Self.playbackTransition(beforeLabel, afterLabel) {
                return visualReceipt(
                    outcome: "verified", dispatch: .dispatched,
                    reason: nil, plan: plan, started: started, matched: true
                )
            }
            return visualReceipt(
                outcome: "dispatch_only", dispatch: .dispatched,
                reason: "no_trustworthy_witness", plan: plan, started: started
            )
        }
    }

    private static func visualReceipt(
        outcome: String,
        dispatch: NativeDispatchState,
        reason: String?,
        plan: NativeVisualPlan?,
        started: Int,
        matched: Bool = false
    ) -> [String: Any] {
        var result: [String: Any] = [
            "outcome": outcome,
            "ok": outcome == "verified",
            "dispatch_state": dispatch.rawValue,
            "strategy": "visual_coordinate_press",
            "lane": "visual",
            "target": plan.map { "\($0.grounding.label) in current window" } ?? "current window",
            "effect": plan.map { "\($0.grounding.label) state changes" } ?? "none",
            "evidence": [[
                "predicate": "target_bound_state_transition",
                "matched": matched,
                "detail": matched ? "playback_label_changed" : (reason ?? "not_matched"),
            ]],
            "retry_safe": dispatch == .notDispatched,
            "duration_ms": max(NativeClock.ms() - started, 0),
            "data": [
                "authorized_strategies": ["visual_coordinate_press"],
                "capture_id": plan?.capture.captureID ?? "",
                "input": plan?.input.rawValue ?? "",
            ],
        ]
        result.put("plan_fingerprint", plan?.fingerprint)
        result.put("reason_code", reason)
        return result
    }

    private static func sameTarget(
        _ baseline: NativeVisualSource, _ current: NativeVisualSource
    ) -> Bool {
        baseline.bundleID == current.bundleID
            && baseline.windowID == current.windowID
            && baseline.windowFrame.distance(to: current.windowFrame) <= 2
            && abs(baseline.scale - current.scale) <= 0.01
            && current.excludedConnSurfaces
    }

    private static func labelsAgree(_ accessible: String, _ visual: String) -> Bool {
        let left = words(accessible)
        let right = words(visual)
        return !left.isEmpty && !right.isEmpty && !left.isDisjoint(with: right)
    }

    private static func playbackTransition(_ before: String?, _ after: String?) -> Bool {
        guard let before, let after else { return false }
        let first = words(before)
        let second = words(after)
        return (first.contains("play") && second.contains("pause"))
            || (first.contains("pause") && second.contains("play"))
    }

    private static func words(_ text: String) -> Set<String> {
        Set(text.lowercased().split {
            !$0.isLetter && !$0.isNumber
        }.map(String.init))
    }
}
