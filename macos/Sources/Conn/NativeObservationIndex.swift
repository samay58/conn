import Foundation

struct NativeObservationCandidate {
    var ref: String
    var label: String
    var role: String
    var subrole: String?
    var supportedActions: [String]
    var ancestorTrail: [String]
    var siblingIndex: Int?
    var siblingCount: Int?
    var windowRelativeFrame: NativeRect?
    var score: Int
    var scoreReasons: [String]
    var descriptor: [String: Any]

    var dictionary: [String: Any] {
        var result: [String: Any] = [
            "ref": ref,
            "label": label,
            "role": role,
            "supported_actions": supportedActions,
            "ancestor_trail": ancestorTrail,
            "score": score,
            "score_reasons": scoreReasons,
            "descriptor": descriptor,
        ]
        result.put("subrole", subrole)
        result.put("sibling_index", siblingIndex)
        result.put("sibling_count", siblingCount)
        result.put("window_relative_frame", windowRelativeFrame?.dictionary)
        return result
    }
}

struct NativeCandidateResult {
    static let modelByteLimit = 16_384

    var observation: NativeCapturedObservation
    var candidates: [NativeObservationCandidate]
    var totalMatchCount: Int
    var truncated: Bool
    var byteLimit: Int
    var serializedBytes: Int

    var dictionary: [String: Any] {
        let candidateDictionaries = candidates.map(\.dictionary)
        let candidateBytes = NativeObservationIndex.serializedSize(candidateDictionaries)
        var result: [String: Any] = [
            "snapshot_id": observation.snapshotID,
            "observation_id": observation.observationID,
            "turn_id": observation.turnID,
            "observation_epoch": observation.observationEpoch,
            "candidate_count": candidates.count,
            "total_match_count": totalMatchCount,
            "candidate_bytes": candidateBytes,
            "candidate_byte_limit": byteLimit,
            "truncated": truncated,
            "candidates": candidateDictionaries,
            "secure": observation.secure,
            "denied": observation.denied,
        ]
        result.put("bundle_id", observation.bundleID)
        result.put("pid", observation.pid.map { Int($0) })
        result.put("app_name", observation.appName)
        result.put("window_id", observation.windowID.map { Int($0) })
        result.put("window_title", observation.windowTitle.map { String($0.prefix(160)) })
        result.put("window_frame", observation.windowFrame?.dictionary)
        return result
    }
}

struct NativeObservationIndex {
    func candidates(
        in observation: NativeCapturedObservation,
        query: NativeObservationQuery
    ) -> NativeCandidateResult {
        guard !observation.denied,
              query.scope != .descendant || query.ancestorRef != nil else {
            return result(observation: observation, matches: [], query: query)
        }
        let nodesByRef = Dictionary(uniqueKeysWithValues: observation.nodes.map { ($0.ref, $0) })
        let unsorted: [NativeObservationCandidate] = observation.nodes.compactMap {
            node -> NativeObservationCandidate? in
            guard !node.secure,
                  scopeIncludes(
                      node, query: query, observation: observation, nodesByRef: nodesByRef
                  ),
                  query.expectedRoles.isEmpty || query.expectedRoles.contains(node.role),
                  query.expectedActions.isSubset(of: Set(node.supportedActions)),
                  query.includeMenu || !hasMenuAncestor(node, nodesByRef: nodesByRef),
                  let label = candidateLabel(
                    node,
                    query: query,
                    focusedElementRef: observation.focusedElementRef,
                    nodesByRef: nodesByRef,
                    nodes: observation.nodes
                  ) else { return nil }

            let match = score(node, label: label, query: query)
            guard match.matched else { return nil }
            let siblings = observation.nodes.filter { $0.parentRef == node.parentRef }
                .sorted(by: pathOrder)
            let siblingIndex = siblings.firstIndex(where: { $0.ref == node.ref }).map { $0 + 1 }
            let trail = ancestorTrail(node, nodesByRef: nodesByRef)
            let display = trail.first.map { "\(label) in \($0)" } ?? label
            let relativeFrame = windowRelativeFrame(
                node, observation: observation, nodesByRef: nodesByRef
            )
            let supportedActions = modelSafeActions(node.supportedActions)
            var descriptor: [String: Any] = [
                "label": label,
                "role": node.role,
                "supported_actions": supportedActions,
                "ancestor_trail": trail,
                "display": display,
            ]
            descriptor.put("subrole", node.subrole)
            descriptor.put("sibling_index", siblingIndex)
            descriptor.put("sibling_count", siblings.isEmpty ? nil : siblings.count)
            return NativeObservationCandidate(
                ref: node.ref,
                label: label,
                role: node.role,
                subrole: node.subrole,
                supportedActions: supportedActions,
                ancestorTrail: trail,
                siblingIndex: siblingIndex,
                siblingCount: siblings.isEmpty ? nil : siblings.count,
                windowRelativeFrame: relativeFrame,
                score: match.score,
                scoreReasons: match.reasons,
                descriptor: descriptor
            )
        }
        let paths = Dictionary(uniqueKeysWithValues: observation.nodes.map { ($0.ref, $0.path) })
        let matches = unsorted.sorted { lhsCandidate, rhsCandidate in
            if lhsCandidate.score != rhsCandidate.score {
                return lhsCandidate.score > rhsCandidate.score
            }
            let lhsPath = paths[lhsCandidate.ref] ?? []
            let rhsPath = paths[rhsCandidate.ref] ?? []
            if lhsPath != rhsPath { return lhsPath.lexicographicallyPrecedes(rhsPath) }
            return lhsCandidate.ref < rhsCandidate.ref
        }
        return result(observation: observation, matches: matches, query: query)
    }

    private func result(
        observation: NativeCapturedObservation,
        matches: [NativeObservationCandidate],
        query: NativeObservationQuery
    ) -> NativeCandidateResult {
        let total = matches.count
        var selected = Array(matches.prefix(query.resultLimit))
        var truncated = selected.count < total
        var output = NativeCandidateResult(
            observation: observation,
            candidates: selected,
            totalMatchCount: total,
            truncated: truncated,
            byteLimit: NativeCandidateResult.modelByteLimit,
            serializedBytes: 0
        )
        while !selected.isEmpty,
              Self.serializedSize(output.dictionary) > output.byteLimit {
            selected.removeLast()
            truncated = true
            output.candidates = selected
            output.truncated = truncated
        }
        output.serializedBytes = Self.serializedSize(output.dictionary)
        return output
    }

    private func modelSafeActions(_ actions: [String]) -> [String] {
        var seen = Set<String>()
        return actions.filter { action in
            guard action.hasPrefix("AX"),
                  (3...64).contains(action.utf8.count),
                  action.utf8.dropFirst(2).allSatisfy({
                      ($0 >= 48 && $0 <= 57)
                          || ($0 >= 65 && $0 <= 90)
                          || ($0 >= 97 && $0 <= 122)
                          || $0 == 95
                  }),
                  seen.insert(action).inserted
            else { return false }
            return true
        }.prefix(16).map { $0 }
    }

    private func score(
        _ node: NativeObservationNode,
        label: String,
        query: NativeObservationQuery
    ) -> (matched: Bool, score: Int, reasons: [String]) {
        let normalizedLabel = normalize(label)
        let fields: [(String, String, Int)] = [
            ("label_contains", normalizedLabel, 35),
            ("title_contains", normalize(node.title), 30),
            ("description_contains", normalize(node.description), 20),
            ("identifier_contains", normalize(node.identifier), 16),
            ("value_contains", normalize(node.redactedValue), 8),
        ]
        var value = 0
        var reasons: [String] = []
        for rawTerm in query.searchTerms {
            let term = normalize(rawTerm)
            let hits = fields.filter { $0.1.contains(term) }
            guard !hits.isEmpty else { return (false, 0, []) }
            if normalizedLabel == term {
                value += 100
                reasons.append("label_exact")
            }
            for hit in hits {
                value += hit.2
                reasons.append(hit.0)
            }
        }
        if !query.expectedRoles.isEmpty {
            value += 10
            reasons.append("role_match")
        }
        if !query.expectedActions.isEmpty {
            value += 8 * query.expectedActions.count
            reasons.append("action_match")
        }
        if node.focused == true || node.selected == true {
            value += 4
            reasons.append("current_state")
        }
        if node.visible == true { value += 2 }
        if node.enabled == true { value += 1 }
        if query.searchTerms.isEmpty { reasons.append("named_candidate") }
        return (true, value, Array(Set(reasons)).sorted())
    }

    private func scopeIncludes(
        _ node: NativeObservationNode,
        query: NativeObservationQuery,
        observation: NativeCapturedObservation,
        nodesByRef: [String: NativeObservationNode]
    ) -> Bool {
        switch query.scope {
        case .currentApp:
            return true
        case .currentWindow:
            guard let focused = observation.focusedWindowRef else { return true }
            return node.ref == focused || isDescendant(node, of: focused, nodesByRef: nodesByRef)
        case .descendant:
            guard let ancestor = query.ancestorRef else { return false }
            return isDescendant(node, of: ancestor, nodesByRef: nodesByRef)
        }
    }

    private func isDescendant(
        _ node: NativeObservationNode,
        of ancestorRef: String,
        nodesByRef: [String: NativeObservationNode]
    ) -> Bool {
        var parent = node.parentRef
        var visited: Set<String> = []
        while let ref = parent, visited.insert(ref).inserted {
            if ref == ancestorRef { return true }
            parent = nodesByRef[ref]?.parentRef
        }
        return false
    }

    private func hasMenuAncestor(
        _ node: NativeObservationNode,
        nodesByRef: [String: NativeObservationNode]
    ) -> Bool {
        if ["AXMenuBar", "AXMenu", "AXMenuItem"].contains(node.role) { return true }
        var parent = node.parentRef
        while let ref = parent, let ancestor = nodesByRef[ref] {
            if ["AXMenuBar", "AXMenu", "AXMenuItem"].contains(ancestor.role) { return true }
            parent = ancestor.parentRef
        }
        return false
    }

    private func safeLabel(_ node: NativeObservationNode) -> String? {
        for value in [node.title, node.description, node.identifier] {
            if let value = value?.trimmingCharacters(in: .whitespacesAndNewlines),
               !value.isEmpty {
                return String(value.prefix(160))
            }
        }
        return nil
    }

    private func candidateLabel(
        _ node: NativeObservationNode,
        query: NativeObservationQuery,
        focusedElementRef: String?,
        nodesByRef: [String: NativeObservationNode],
        nodes: [NativeObservationNode]
    ) -> String? {
        if let label = safeLabel(node), query.searchTerms.isEmpty
            || labelMatchesQuery(label, terms: query.searchTerms) {
            return label
        }
        let fieldRoles = ["AXComboBox", "AXSearchField", "AXTextArea", "AXTextField"]
        if fieldRoles.contains(node.role), !query.searchTerms.isEmpty,
           let value = node.redactedValue,
           labelMatchesQuery(value, terms: query.searchTerms) {
            return String(query.searchTerms.joined(separator: " ").prefix(160))
        }
        guard node.focused == true || node.ref == focusedElementRef,
              fieldRoles.contains(node.role) else { return nil }

        var relatedLabels: [String] = []
        var parentRef = node.parentRef
        var visited: Set<String> = []
        while let ref = parentRef, visited.count < 20,
              visited.insert(ref).inserted,
              let parent = nodesByRef[ref] {
            if parent.role == "AXWindow" { break }
            if let label = safeLabel(parent) { relatedLabels.append(label) }
            parentRef = parent.parentRef
        }

        var frontier = nodes.filter { $0.parentRef == node.ref }
        visited = []
        for _ in 0..<20 where !frontier.isEmpty {
            relatedLabels.append(contentsOf: frontier.compactMap(safeLabel))
            let refs = Set(frontier.map(\.ref))
            visited.formUnion(refs)
            frontier = nodes.filter {
                $0.parentRef.map(refs.contains) == true
                    && !visited.contains($0.ref)
            }
        }
        if query.searchTerms.isEmpty { return relatedLabels.first }
        let matching = relatedLabels.filter {
            labelMatchesQuery($0, terms: query.searchTerms)
        }
        let exact = matching.filter { label in
            let normalized = normalize(label)
            return query.searchTerms.contains { normalize($0) == normalized }
        }
        let values = exact.isEmpty ? matching : exact
        let unique = Dictionary(grouping: values, by: normalize)
        guard unique.count == 1 else { return nil }
        return unique.values.first?.first
    }

    private func labelMatchesQuery(_ label: String, terms: [String]) -> Bool {
        let normalized = normalize(label)
        return terms.allSatisfy { normalized.contains(normalize($0)) }
    }

    private func ancestorTrail(
        _ node: NativeObservationNode,
        nodesByRef: [String: NativeObservationNode]
    ) -> [String] {
        var result: [String] = []
        var parent = node.parentRef
        while let ref = parent, let ancestor = nodesByRef[ref], result.count < 4 {
            if let label = safeLabel(ancestor) {
                result.append(String(label.prefix(80)))
            }
            parent = ancestor.parentRef
        }
        return result
    }

    private func windowRelativeFrame(
        _ node: NativeObservationNode,
        observation: NativeCapturedObservation,
        nodesByRef: [String: NativeObservationNode]
    ) -> NativeRect? {
        guard var frame = node.frame else { return nil }
        var windowFrame = observation.windowFrame
        var parent = node.parentRef
        while let ref = parent, let ancestor = nodesByRef[ref] {
            if ancestor.role == "AXWindow", let frame = ancestor.frame {
                windowFrame = frame
                break
            }
            parent = ancestor.parentRef
        }
        if let windowFrame {
            frame.x -= windowFrame.x
            frame.y -= windowFrame.y
        }
        return frame
    }

    private func normalize(_ value: String?) -> String {
        (value ?? "").trimmingCharacters(in: .whitespacesAndNewlines).folding(
            options: [.caseInsensitive, .diacriticInsensitive], locale: .current
        )
    }

    private func pathOrder(
        _ lhs: NativeObservationNode,
        _ rhs: NativeObservationNode
    ) -> Bool {
        if lhs.path != rhs.path { return lhs.path.lexicographicallyPrecedes(rhs.path) }
        return lhs.ref < rhs.ref
    }

    static func serializedSize(_ value: Any) -> Int {
        (try? JSONSerialization.data(
            withJSONObject: value, options: [.sortedKeys]
        ).count) ?? Int.max
    }
}
