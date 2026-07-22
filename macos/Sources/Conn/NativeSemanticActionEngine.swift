import Foundation

actor NativeSemanticActionEngine {
    private let backend: NativeSemanticBackend
    private let store: NativeObservationStore
    private let observationIndex = NativeObservationIndex()
    private let compiler: NativeActionCompiler
    private let effectEvaluator: NativeEffectEvaluator
    private let transactionExecutor: NativeTransactionExecutor
    private let executionInterlock: NativeExecutionInterlock?
    private var plans: [String: NativeActionPlan] = [:]
    private let planLimit = 8

    init(
        backend: NativeSemanticBackend = NativeAXSemanticBackend(),
        applicationResolver: NativeApplicationResolver = NativeApplicationResolver(),
        executionInterlock: NativeExecutionInterlock? = nil
    ) {
        self.backend = backend
        let store = NativeObservationStore(backend: backend)
        let compiler = NativeActionCompiler(applications: applicationResolver)
        let evaluator = NativeEffectEvaluator(store: store)
        self.store = store
        self.compiler = compiler
        effectEvaluator = evaluator
        transactionExecutor = NativeTransactionExecutor(
            backend: backend,
            store: store,
            compiler: compiler,
            evaluator: evaluator,
            executionInterlock: executionInterlock
        )
        self.executionInterlock = executionInterlock
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
        let observation = store.observe(
            turnID: turnID,
            observationEpoch: observationEpoch,
            query: query
        )
        return observationIndex.candidates(
            in: observation, query: query
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
        let origin = request.target.snapshotID.flatMap(store.snapshot)
        var baseline = store.observe(
            turnID: request.turnID,
            observationEpoch: request.observationEpoch,
            query: query
        )

        if baseline.denied {
            return failurePlan("denied_bundle", outcome: .blocked)
        }
        switch compiler.bindApplication(request: request, baseline: baseline) {
        case .success(let bound): request = bound
        case .failure(let failure):
            var plan = failurePlan(failure.reason, outcome: failure.outcome)
            if !failure.candidates.isEmpty {
                plan["candidates"] = failure.candidates.map(\.dictionary)
            }
            return plan
        }
        if let bundleID = request.payload.bundleID {
            guard NativeAppIdentity.validBundleID(bundleID) else {
                return failurePlan("invalid_bundle_id")
            }
            if !bundleID.hasPrefix("com.apple."),
               request.payload.teamID.map(NativeAppIdentity.validTeamID) != true {
                return failurePlan("app_identity_unproven", outcome: .blocked)
            }
        }
        if let requestedBundle = request.payload.bundleID,
           request.deniedBundles.contains(requestedBundle) {
            return failurePlan("denied_bundle", outcome: .blocked)
        }
        if ![.openApp, .switchApp, .navigate].contains(request.operation),
           request.payload.bundleID != nil,
           !backend.applicationIdentityMatches(request: request, observation: baseline) {
            return failurePlan("app_identity_mismatch", outcome: .blocked)
        }
        if request.operation == .semanticIntent,
           request.payload.intentFamily == "create",
           let kind = request.payload.intentKind,
           let synonyms = Self.createKindSynonyms[kind] {
            let wanted = Set(synonyms.map { "new \($0)" })
            let hasAffordance = baseline.nodes.contains {
                $0.role == "AXMenuItem"
                    && $0.enabled != false
                    && wanted.contains(normalize($0.title))
            }
            if !hasAffordance {
                let discoveries = store.observeMenuForPreparation(
                request: request,
                query: query,
                matchingTitles: wanted
                )
                let matching = discoveries.flatMap { observation in
                    observation.nodes.compactMap { node -> (
                        NativeCapturedObservation, NativeObservationNode, String
                    )? in
                        guard node.role == "AXMenuItem",
                              node.enabled != false,
                              wanted.contains(normalize(node.title)) else {
                            return nil
                        }
                        return (
                            observation,
                            node,
                            menuPathTitles(to: node, in: observation)
                        )
                    }
                }
                let paths = Set(matching.map(\.2))
                if paths.count > 1 {
                    return failurePlan("ambiguous_intent", outcome: .ambiguous)
                }
                guard let discovered = matching.first?.0 else {
                    return failurePlan("no_live_affordance")
                }
                guard discovered.bundleID == baseline.bundleID,
                      discovered.pid == baseline.pid,
                      discovered.processStartIdentity == baseline.processStartIdentity,
                      discovered.windowID == baseline.windowID,
                      !discovered.denied else {
                    return failurePlan("stale_plan")
                }
                baseline = discovered
            }
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
               compiler.isInstalledBrowser(baseline.bundleID),
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
            reboundDesired = effectEvaluator.rebindEffect(desired, from: origin, to: baseline)
            if reboundDesired == nil { return failurePlan("stale_effect_binding") }
        } else {
            reboundDesired = request.desiredEffect
        }
        var effect = reboundDesired ?? intentWitness
            ?? compiler.navigationEffect(request)
            ?? derivedEffect(
            request: request,
            target: targetNode,
            baseline: baseline
        )
        guard effectEvaluator.effectBindingsAreValid(effect, in: baseline) else {
            return failurePlan("invalid_effect_predicate")
        }
        if reboundDesired != nil,
           !effectEvaluator.desiredEffectTargetsAction(effect, request: request, target: targetNode) {
            return failurePlan("invalid_effect_target")
        }
        effect = effectEvaluator.bindBaselines(effect, in: baseline)
        if effectEvaluator.evaluate(effect, before: baseline, after: baseline).matched {
            return failurePlan("effect_already_satisfied")
        }
        let strategies = compileStrategies(request: request, target: targetNode)
        guard !strategies.isEmpty else {
            return failurePlan(
                request.payload.intentFamily == "select_named"
                    ? "no_live_affordance" : "unsupported_operation"
            )
        }
        let safeTarget = [
            targetNode?.title,
            targetNode?.description,
            semanticIntentTarget(request.payload),
            request.payload.menuPath.last,
            request.payload.appName,
            request.payload.intentName,
            request.payload.bundleID,
            request.payload.url,
            request.operation.rawValue,
        ]
            .compactMap { $0?.trimmingCharacters(in: .whitespacesAndNewlines) }
            .first { !$0.isEmpty } ?? request.operation.rawValue
        let effectClass = compiler.effectClass(
            request: request, target: targetNode, baseline: baseline
        )
        let fingerprint = planFingerprint(
            request: request,
            baseline: baseline,
            target: targetNode,
            effect: effect,
            strategies: strategies,
            effectClass: effectClass
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
            createdMs: NativeClock.ms(),
            effectClass: effectClass
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
            "effect_class": effectClass.rawValue,
            "navigation_generation": request.navigationGeneration,
            "lane": "semantic",
            "snapshot_id": baseline.snapshotID,
            "observation_id": baseline.observationID,
            "turn_id": request.turnID,
            "response_epoch": request.responseEpoch,
            "observation_epoch": request.observationEpoch,
            "payload_hash": request.payload.hash,
            "before_digest": baseline.digest,
            "timeout_ms": request.timeoutMs,
            "bundle_id": request.payload.bundleID ?? baseline.bundleID ?? "",
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
        let fingerprint = params["plan_fingerprint"] as? String
        let plan = fingerprint.flatMap { plans.removeValue(forKey: $0) }
        return await transactionExecutor.execute(params, plan: plan)
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
        case .openApp, .switchApp, .openURL, .navigate, .clipboardWrite, .menu, .keyChord,
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
        "note": ["AXTable", "AXList"],
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
        case "select_named":
            return lowerSelectNamed(request: request, baseline: baseline)
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
        let matches = baseline.nodes.filter { node in
            node.role == "AXMenuItem"
                && node.enabled != false
                && wanted.contains(normalize(node.title))
        }
        guard !matches.isEmpty else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_live_affordance")))
        }
        var resolved: [(intent: NativeObservationNode, dispatch: NativeObservationNode)] = []
        for match in matches {
            let descendants = baseline.nodes.filter { node in
                node.role == "AXMenuItem"
                    && node.enabled != false
                    && NativeObservationStore.isDescendant(
                        node, of: match.ref, in: baseline
                    )
            }
            if match.menuShortcut != nil || descendants.isEmpty {
                resolved.append((match, match))
                continue
            }
            let defaults = descendants.filter { $0.menuShortcut != nil }
            guard defaults.count <= 1 else {
                return .failure(IntentLoweringFailure(plan: failurePlan(
                    "ambiguous_intent", outcome: .ambiguous
                )))
            }
            guard let defaultLeaf = defaults.first else {
                return .failure(IntentLoweringFailure(
                    plan: failurePlan("no_live_affordance")
                ))
            }
            resolved.append((match, defaultLeaf))
        }
        let paths = Set(resolved.map {
            menuPathTitles(to: $0.dispatch, in: baseline)
        })
        guard paths.count == 1 else {
            return .failure(IntentLoweringFailure(plan: failurePlan("ambiguous_intent", outcome: .ambiguous)))
        }
        var lowered = request
        lowered.operation = .menu
        lowered.payload.menuPath = menuPathTitles(
            to: resolved[0].dispatch, in: baseline
        )
            .split(separator: "\u{1e}").map(String.init)
        let candidates: [[String: Any]] = resolved.map { nodes in
            let path = menuPathTitles(to: nodes.dispatch, in: baseline)
                .split(separator: "\u{1e}").map(String.init)
            var candidate: [String: Any] = [
                "title": nodes.intent.title ?? "", "role": nodes.dispatch.role,
                "strategy_class": "menu",
                "menu_path": path,
            ]
            candidate.put("shortcut", nodes.dispatch.menuShortcut)
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
                    && effectEvaluator.descendantCount(
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

    private func semanticIntentTarget(_ payload: NativeActionPayload) -> String? {
        guard payload.intentFamily == "create",
              let kind = payload.intentKind?.trimmingCharacters(
                  in: .whitespacesAndNewlines
              ), !kind.isEmpty else { return nil }
        return "New \(kind.prefix(1).capitalized)\(kind.dropFirst())"
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
        var selected = baseline.nodes.filter { node in
            node.selected == true
                && node.parentRef.map(collectionRefs.contains) == true
        }
        if request.payload.intentKind == "note" {
            selected = selected.filter { node in
                guard let parentRef = node.parentRef else { return false }
                return baseline.nodes.filter {
                    $0.parentRef == parentRef && $0.role == node.role
                }.count > 1
            }
        }
        guard selected.count <= 1 else {
            return .failure(IntentLoweringFailure(plan: failurePlan("ambiguous_intent", outcome: .ambiguous)))
        }
        guard let current = selected.first else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_current_selection")))
        }
        guard let collectionRef = current.parentRef else {
            return .failure(IntentLoweringFailure(
                plan: failurePlan("no_current_selection")
            ))
        }
        let siblings = NativeObservationStore.selectionPeers(
            matching: current,
            collectionRef: collectionRef,
            in: baseline
        )
        guard let index = siblings.firstIndex(where: { $0.ref == current.ref }) else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_current_selection")))
        }
        let targetIndex = index + (relation == "next" ? 1 : -1)
        guard siblings.indices.contains(targetIndex) else {
            return .failure(IntentLoweringFailure(plan: failurePlan("no_relative_item")))
        }
        let sibling = siblings[targetIndex]
        let siblingNamed = [sibling.title, sibling.description, sibling.identifier]
            .contains { value in
                !(value ?? "").trimmingCharacters(
                    in: .whitespacesAndNewlines
                ).isEmpty
            }
        let structuralPeerTarget = sibling.frame != nil
            && siblings.allSatisfy { $0.frame != nil }
        let descendantKey = siblingNamed || structuralPeerTarget ? nil
            : NativeObservationStore.descendantSemanticKey(
                of: sibling, in: baseline
            )
        if !siblingNamed && !structuralPeerTarget {
            guard let descendantKey else {
                return .failure(IntentLoweringFailure(
                    plan: failurePlan("no_stable_target")
                ))
            }
            let matchingKeys = siblings.filter {
                NativeObservationStore.descendantSemanticKey(
                    of: $0, in: baseline
                ) == descendantKey
            }
            guard matchingKeys.count == 1 else {
                return .failure(IntentLoweringFailure(
                    plan: failurePlan(
                        "ambiguous_intent",
                        outcome: .ambiguous
                    )
                ))
            }
        }
        var lowered = request
        lowered.operation = .focusTab
        lowered.target = NativeActionTarget(
            snapshotID: nil,
            ref: sibling.ref,
            identifier: sibling.identifier,
            title: nil,
            bundleID: request.target.bundleID,
            descendantKey: descendantKey
        )
        let candidates: [[String: Any]] = [[
            "title": sibling.title ?? "", "role": sibling.role,
            "strategy_class": "semantic_selection",
        ]]
        return .success(LoweredIntent(request: lowered, candidates: candidates))
    }

    private func lowerSelectNamed(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation
    ) -> Result<LoweredIntent, IntentLoweringFailure> {
        guard let rawName = request.payload.intentName else {
            return .failure(IntentLoweringFailure(
                plan: failurePlan("unsupported_intent")
            ))
        }
        let name = normalize(rawName)
        guard !name.isEmpty else {
            return .failure(IntentLoweringFailure(
                plan: failurePlan("unsupported_intent")
            ))
        }
        let roles: Set<String>
        if let kind = request.payload.intentKind {
            guard let kindRoles = Self.selectionParentRoles[kind] else {
                return .failure(IntentLoweringFailure(
                    plan: failurePlan("unsupported_intent")
                ))
            }
            roles = kindRoles
        } else {
            roles = Set(Self.selectionParentRoles.values.flatMap { $0 })
        }
        let collectionRefs = Set(
            baseline.nodes.filter { roles.contains($0.role) }.map(\.ref)
        )
        let selectableRoles: Set<String> = [
            "AXCell", "AXGroup", "AXRadioButton", "AXRow", "AXTab",
        ]
        let candidates = baseline.nodes.filter { node in
            guard selectableRoles.contains(node.role),
                  node.parentRef.map(collectionRefs.contains) == true else {
                return false
            }
            if [node.title, node.description, node.identifier]
                .contains(where: { normalize($0) == name }) {
                return true
            }
            return baseline.nodes.contains { descendant in
                NativeObservationStore.isDescendant(
                    descendant, of: node.ref, in: baseline
                ) && !descendant.secure
                    && [
                        descendant.title,
                        descendant.description,
                        descendant.redactedValue,
                    ]
                        .contains(where: { normalize($0) == name })
            }
        }
        guard candidates.count == 1, let candidate = candidates.first else {
            return .failure(IntentLoweringFailure(plan: failurePlan(
                candidates.isEmpty ? "no_live_affordance" : "ambiguous_intent",
                outcome: candidates.isEmpty ? .failed : .ambiguous
            )))
        }
        let target: NativeObservationNode
        let witness: NativeEffectGroup?
        if candidate.role == "AXGroup" {
            let focusable = baseline.nodes.filter {
                NativeObservationStore.isDescendant(
                    $0, of: candidate.ref, in: baseline
                ) && !$0.secure
                    && $0.settableAttributes.contains("AXFocused")
            }
            guard focusable.count == 1, let child = focusable.first else {
                return .failure(IntentLoweringFailure(
                    plan: failurePlan("no_live_affordance")
                ))
            }
            target = child
            witness = NativeEffectGroup(mode: "all", predicates: [])
        } else {
            target = candidate
            witness = nil
        }
        var lowered = request
        lowered.operation = .focusTab
        lowered.target = NativeActionTarget(
            snapshotID: nil,
            ref: target.ref,
            identifier: target.identifier,
            title: nil,
            bundleID: request.target.bundleID,
            descendantKey: NativeObservationStore.descendantSemanticKey(
                of: target, in: baseline
            )
        )
        return .success(LoweredIntent(
            request: lowered,
            candidates: [[
                "title": rawName,
                "role": target.role,
                "strategy_class": "semantic_selection",
            ]],
            witness: witness
        ))
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
        case .navigate:
            predicate = nil
        case .clipboardWrite:
            predicate = request.payload.text.map {
                NativeEffectPredicate(kind: "clipboard_hash_equals", expected: NativeHash.sha256($0))
            }
        case .focusTab:
            predicate = target.flatMap { target in
                if request.payload.intentFamily == "select_relative",
                   let parentRef = target.parentRef {
                    let siblings = baseline.nodes.filter {
                        $0.parentRef == parentRef && $0.role == target.role
                    }
                    guard siblings.contains(where: {
                        $0.ref == target.ref
                    }) else { return nil }
                    return NativeEffectPredicate(
                        kind: "collection_selected_peer_index_changes_by_one",
                        ref: parentRef,
                        attribute: target.role,
                        expected: request.payload.intentRelation
                    )
                }
                if target.selected != nil
                    || target.settableAttributes.contains("AXSelected")
                    || target.role == "AXRow" {
                    return NativeEffectPredicate(
                        kind: "element_attribute_equals",
                        ref: target.ref,
                        attribute: "selected",
                        expected: "true"
                    )
                }
                let title = (target.title ?? "").trimmingCharacters(
                    in: .whitespacesAndNewlines
                )
                return title.isEmpty ? nil : NativeEffectPredicate(
                    kind: "window_title_equals",
                    expected: title
                )
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
        case .keyChord where ["pageup", "pagedown", "left", "right"].contains(
            request.payload.keys.first ?? ""
        ) && request.payload.keys.count == 1:
            predicate = uniquePageStatusNode(in: baseline).map { _ in
                let key = request.payload.keys[0]
                return NativeEffectPredicate(
                    kind: "unique_page_status_changes",
                    expected: ["pagedown", "right"].contains(key)
                        ? "next" : "previous"
                )
            }
        case .keyChord where request.payload.keys == ["find"]:
            predicate = NativeEffectPredicate(
                kind: "unique_focused_find_field_appears"
            )
        case .menu, .keyChord, .semanticIntent:
            predicate = nil
        }
        return NativeEffectGroup(mode: "all", predicates: predicate.map { [$0] } ?? [])
    }

    private func uniquePageStatusNode(
        in baseline: NativeCapturedObservation
    ) -> NativeObservationNode? {
        let matches = baseline.nodes.filter {
            NativePageStatus.recognizedValue($0) != nil
        }
        return matches.count == 1 ? matches[0] : nil
    }

    private func compileStrategies(
        request: NativeActionRequest,
        target: NativeObservationNode?
    ) -> [NativeActionStrategy] {
        switch request.operation {
        case .openApp, .switchApp, .openURL, .navigate: return [.launchServices]
        case .clipboardWrite: return [.pasteboard]
        case .focusTab:
            var strategies: [NativeActionStrategy] = []
            if request.payload.intentFamily == "select_relative",
               target?.role == "AXRow" {
                return [.semanticRowKeySelect]
            }
            if target?.settableAttributes.contains("AXSelected") == true {
                strategies.append(.axSetSelected)
            }
            if target?.role == "AXRow" {
                strategies.append(.axSetSelectedRows)
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
        strategies: [NativeActionStrategy],
        effectClass: NativeEffectClass
    ) -> String {
        NativeHash.sha256([
            request.turnID,
            String(request.responseEpoch),
            String(request.observationEpoch),
            baseline.bundleID ?? "",
            baseline.processStartIdentity ?? "",
            String(baseline.windowID ?? 0),
            target?.semanticFingerprint ?? "",
            request.target.descendantKey ?? "",
            request.operation.rawValue,
            request.payload.hash,
            request.applicationBinding?.identityFingerprint ?? "",
            request.applicationBinding?.bundleURL.standardizedFileURL.path ?? "",
            effect.summary,
            strategies.map(\.rawValue).joined(separator: ","),
            request.risk,
            effectClass.rawValue,
            String(request.navigationGeneration),
            request.executionConnectionID,
        ].joined(separator: "\u{1e}"))
    }

    private func previewText(request: NativeActionRequest, target: String) -> String {
        switch request.operation {
        case .openApp: return "Open \(target)"
        case .switchApp: return "Switch to \(target)"
        case .openURL: return "Open the requested location"
        case .navigate: return "Open the requested location"
        case .clipboardWrite: return "Copy \(request.payload.text?.count ?? 0) characters"
        case .focusTab:
            return request.payload.intentFamily == "select_named"
                ? "Select \(target)" : "Focus \(target)"
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
            "reason_code": reason,
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
                && now - $0.value.createdMs <= NativeActionPlan.ttlMs
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


}
