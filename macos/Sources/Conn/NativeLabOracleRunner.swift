import Foundation

enum NativeLabOracleRunner {
    static func run(bundleID: String, expected: String) -> [String: Any] {
        guard NativeAppIdentity.validBundleID(bundleID),
              validExpected(expected) else {
            return [
                "outcome": "failed",
                "reason_code": "invalid_lab_oracle_request",
            ]
        }
        let observation = NativeAXSemanticBackend().capture(
            turnID: "lab-oracle",
            observationEpoch: 1,
            query: NativeObservationQuery(
                bundleID: bundleID,
                maxNodes: 500,
                maxDepth: 16,
                deadlineMs: NativeClock.ms() + 4_000
            )
        )
        return summarize(observation, expected: expected)
    }

    static func runAffordances(bundleID: String, expected: String) -> [String: Any] {
        guard NativeAppIdentity.validBundleID(bundleID),
              validExpected(expected) else {
            return [
                "outcome": "failed",
                "reason_code": "invalid_lab_affordance_request",
            ]
        }
        let observation = NativeAXSemanticBackend().capture(
            turnID: "lab-affordance",
            observationEpoch: 1,
            query: NativeObservationQuery(
                bundleID: bundleID,
                maxNodes: 500,
                maxDepth: 16,
                deadlineMs: NativeClock.ms() + 4_000
            )
        )
        return targetAffordances(observation, expected: expected)
    }

    static func summarize(
        _ observation: NativeCapturedObservation,
        expected: String
    ) -> [String: Any] {
        let expectedKey = normalize(expected)
        let nodes = observation.nodes.filter { !$0.secure }
        let byRef = Dictionary(uniqueKeysWithValues: nodes.map { ($0.ref, $0) })
        var children: [String: [NativeObservationNode]] = [:]
        for node in nodes {
            if let parentRef = node.parentRef {
                children[parentRef, default: []].append(node)
            }
        }

        func directlyMatches(_ node: NativeObservationNode) -> Bool {
            return [node.title, node.description, node.identifier, node.redactedValue]
                .compactMap { $0 }
                .contains { normalize($0) == expectedKey }
        }

        func labelMatches(_ node: NativeObservationNode) -> Bool {
            [node.title, node.description, node.identifier]
                .compactMap { $0 }
                .contains { normalize($0) == expectedKey }
        }

        func relatedMatch(_ node: NativeObservationNode) -> Bool {
            if directlyMatches(node) { return true }
            var ancestorRef = node.parentRef
            var visited: Set<String> = []
            while let ref = ancestorRef, visited.insert(ref).inserted,
                  let ancestor = byRef[ref] {
                if directlyMatches(ancestor) { return true }
                ancestorRef = ancestor.parentRef
            }
            var queue = children[node.ref] ?? []
            visited = []
            while !queue.isEmpty, visited.count < 500 {
                let descendant = queue.removeFirst()
                guard visited.insert(descendant.ref).inserted else { continue }
                if directlyMatches(descendant) { return true }
                queue.append(contentsOf: children[descendant.ref] ?? [])
            }
            return false
        }

        let focusedMatches = nodes.filter {
            $0.focused == true && relatedMatch($0)
        }
        let valueMatches = nodes.filter {
            $0.redactedValue.map { normalize($0) == expectedKey } ?? false
        }
        let expectedValueHash = NativeHash.sha256(expected)
        let valueHashMatches = nodes.filter { $0.valueHash == expectedValueHash }
        let pageStatuses = nodes.compactMap(NativePageStatus.recognizedValue)
            .prefix(4)
        var focusedMatchRoles: [String: Int] = [:]
        for node in focusedMatches {
            focusedMatchRoles[node.role, default: 0] += 1
        }
        var valueMatchRoles: [String: Int] = [:]
        for node in valueMatches {
            valueMatchRoles[node.role, default: 0] += 1
        }
        var valueHashMatchRoles: [String: Int] = [:]
        for node in valueHashMatches {
            valueHashMatchRoles[node.role, default: 0] += 1
        }

        return [
            "schema_version": 1,
            "bundle_id": observation.bundleID ?? "",
            "selected_match_count": nodes.filter {
                $0.selected == true && relatedMatch($0)
            }.count,
            "focused_match_count": focusedMatches.count,
            "focused_match_roles": focusedMatchRoles,
            "value_match_roles": valueMatchRoles,
            "value_hash_match_roles": valueHashMatchRoles,
            "window_title_matches": observation.windowTitle.map {
                normalize($0) == expectedKey
            } ?? false,
            "value_match_count": valueMatches.count,
            "label_match_count": nodes.filter(labelMatches).count,
            "page_statuses": Array(pageStatuses),
        ]
    }

    static func runTarget(bundleID: String, expected: String) -> [String: Any] {
        guard NativeAppIdentity.validBundleID(bundleID),
              validExpected(expected) else {
            return [
                "outcome": "failed",
                "reason_code": "invalid_lab_target_request",
            ]
        }
        let observation = NativeAXSemanticBackend().capture(
            turnID: "lab-target",
            observationEpoch: 1,
            query: NativeObservationQuery(
                bundleID: bundleID,
                maxNodes: 500,
                maxDepth: 16,
                deadlineMs: NativeClock.ms() + 4_000
            )
        )
        return target(observation, expected: expected)
    }

    static func target(
        _ observation: NativeCapturedObservation,
        expected: String
    ) -> [String: Any] {
        let expectedKey = normalize(expected)
        let matches = observation.nodes.filter { node in
            guard !node.secure,
                  node.supportedActions.contains("AXPress"),
                  node.frame != nil else { return false }
            return [node.title, node.description, node.identifier]
                .compactMap { $0 }
                .contains { normalize($0) == expectedKey }
        }
        return [
            "schema_version": 1,
            "bundle_id": observation.bundleID ?? "",
            "match_count": matches.count,
            "frame": matches.count == 1
                ? matches[0].frame!.dictionary : NSNull(),
        ]
    }

    static func targetAffordances(
        _ observation: NativeCapturedObservation,
        expected: String
    ) -> [String: Any] {
        let expectedKey = normalize(expected)
        let nodes = observation.nodes.filter { !$0.secure }
        let byRef = Dictionary(uniqueKeysWithValues: nodes.map { ($0.ref, $0) })
        var children: [String: [NativeObservationNode]] = [:]
        for node in nodes {
            if let parentRef = node.parentRef {
                children[parentRef, default: []].append(node)
            }
        }

        func directlyMatches(_ node: NativeObservationNode) -> Bool {
            if node.valueHash == NativeHash.sha256(expected) {
                return true
            }
            return [node.title, node.description, node.identifier, node.redactedValue]
                .compactMap { $0 }
                .contains { normalize($0) == expectedKey }
        }

        func relatedMatch(_ node: NativeObservationNode) -> Bool {
            if directlyMatches(node) { return true }
            var queue = children[node.ref] ?? []
            var visited: Set<String> = []
            while !queue.isEmpty, visited.count < 500 {
                let descendant = queue.removeFirst()
                guard visited.insert(descendant.ref).inserted else { continue }
                if directlyMatches(descendant) { return true }
                queue.append(contentsOf: children[descendant.ref] ?? [])
            }
            return false
        }

        let targetRoles: Set<String> = [
            "AXCell", "AXGroup", "AXRadioButton", "AXRow", "AXTab",
        ]
        let namedMatches = nodes.filter {
            targetRoles.contains($0.role) && relatedMatch($0)
        }
        let structuralMatches = nodes.filter { node in
            guard ["AXCell", "AXRow"].contains(node.role),
                  let parentRef = node.parentRef,
                  let parent = byRef[parentRef],
                  ["AXList", "AXTable"].contains(parent.role) else {
                return false
            }
            return nodes.filter {
                $0.parentRef == parentRef && $0.role == node.role
            }.count > 1
        }
        let candidates = namedMatches.isEmpty ? structuralMatches : namedMatches
        let matches = candidates.prefix(4).map { node -> [String: Any] in
            let parent = node.parentRef.flatMap { byRef[$0] }
            return [
                "role": node.role,
                "selected": node.selected ?? false,
                "selected_known": node.selected != nil,
                "focused": node.focused ?? false,
                "focused_known": node.focused != nil,
                "supported_actions": safeNames(node.supportedActions),
                "settable_attributes": safeNames(node.settableAttributes),
                "parent_role": parent?.role ?? "",
                "parent_supported_actions": safeNames(
                    parent?.supportedActions ?? []
                ),
                "parent_settable_attributes": safeNames(
                    parent?.settableAttributes ?? []
                ),
                "frame": node.frame?.dictionary ?? NSNull(),
            ]
        }
        return [
            "schema_version": 1,
            "bundle_id": observation.bundleID ?? "",
            "match_count": matches.count,
            "matches": Array(matches),
        ]
    }

    private static func validExpected(_ value: String) -> Bool {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && trimmed.count <= 160 && !trimmed.contains("\0")
    }

    private static func normalize(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).folding(
            options: [.caseInsensitive, .diacriticInsensitive],
            locale: .current
        )
    }

    private static func safeNames(_ values: [String]) -> [String] {
        Array(Set(values.filter {
            $0.hasPrefix("AX") && $0.count <= 64
        })).sorted().prefix(16).map { $0 }
    }
}
