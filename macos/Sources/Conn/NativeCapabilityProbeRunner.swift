import Foundation

enum NativeCapabilityProbeRunner {
    private static let artifactRoot = "/Volumes/My Shared Files/artifacts"
    private struct Query {
        let job: String
        let roles: [String]
        let actions: [String]
        let terms: [String]
        let includeMenu: Bool
    }

    private static let queries = [
        Query(
            job: "control_activation",
            roles: [
                "AXButton", "AXCheckBox", "AXMenuButton", "AXPopUpButton",
                "AXRadioButton", "AXSegmentedControl",
            ],
            actions: ["AXPress"],
            terms: [],
            includeMenu: false
        ),
        Query(
            job: "collection_selection",
            roles: [
                "AXCell", "AXList", "AXOutline", "AXRadioButton", "AXRow",
                "AXTabGroup", "AXTable",
            ],
            actions: [],
            terms: [],
            includeMenu: false
        ),
        Query(
            job: "field_text_entry",
            roles: ["AXComboBox", "AXSearchField", "AXTextArea", "AXTextField"],
            actions: [],
            terms: [],
            includeMenu: false
        ),
        Query(
            job: "menus_overlays",
            roles: ["AXMenuItem"],
            actions: [],
            terms: [],
            includeMenu: true
        ),
        Query(
            job: "document_history",
            roles: ["AXButton", "AXMenuItem"],
            actions: [],
            terms: ["back", "forward", "next", "previous", "today"],
            includeMenu: true
        ),
        Query(
            job: "named_scroll",
            roles: [],
            actions: ["AXScrollToVisible"],
            terms: [],
            includeMenu: false
        ),
    ]

    static func isLabGuest(
        _ environment: [String: String] = ProcessInfo.processInfo.environment,
        fileExists: (String) -> Bool = {
            FileManager.default.fileExists(atPath: $0)
        }
    ) -> Bool {
        environment["CONN_LAB_GUEST"] == "1"
            && environment["CONN_SERVER_PORT"] == "18787"
            && fileExists(BridgeToken.labMarker)
    }

    static func run(
        _ bundleID: String,
        menuKind: String? = nil
    ) async -> [String: Any] {
        guard NativeAppIdentity.validBundleID(bundleID) else {
            return [
                "outcome": "failed",
                "reason_code": "invalid_bundle_id",
            ]
        }
        let engine = NativeSemanticActionEngine()
        var jobs: [String: Any] = [:]
        var appSummary: [String: Any] = [:]
        var epoch = 0
        for query in queries {
            var summaries: [[String: Any]] = []
            for terms in termGroups(for: query.job) {
                epoch += 1
                let observation = await engine.observe([
                    "turn_id": "capability-probe",
                    "observation_epoch": epoch,
                    "query": [
                        "bundle_id": bundleID,
                        "include_menu": query.includeMenu,
                        "max_nodes": 500,
                        "max_depth": 16,
                        "search_terms": terms,
                        "expected_roles": query.roles,
                        "expected_actions": query.actions,
                        "result_limit": 20,
                    ],
                ])
                summaries.append(summarizeObservation(observation))
            }
            let summary = summaries.max {
                ($0["total_match_count"] as? Int ?? 0)
                    < ($1["total_match_count"] as? Int ?? 0)
            } ?? [:]
            jobs[query.job] = summary
            if appSummary.isEmpty {
                appSummary = [
                    "bundle_id": summary["bundle_id"] as? String ?? "",
                    "window_present": summary["window_present"] as? Bool ?? false,
                    "secure": summary["secure"] as? Bool ?? false,
                    "denied": summary["denied"] as? Bool ?? false,
                ]
            }
        }
        let visual = await NativeVisualControl().observe([
            "enabled": true,
            "turn_id": "capability-probe",
            "observation_epoch": epoch + 1,
            "execution_connection_id": "capability-probe",
            "denied_bundles": [],
        ])
        jobs["visual_fallback"] = [
            "available": visual["ok"] as? Bool == true,
            "outcome": visual["outcome"] as? String ?? "failed",
            "reason_code": visual["reason_code"] as? String ?? "",
            "image_bytes": visual["image_bytes"] as? Int ?? 0,
            "pixel_width": visual["pixel_width"] as? Int ?? 0,
            "pixel_height": visual["pixel_height"] as? Int ?? 0,
            "bundle_id": visual["bundle_id"] as? String ?? "",
        ]
        if let menuKind, !menuTitles(for: menuKind).isEmpty {
            jobs["menus_overlays"] = menuObservation(
                bundleID: bundleID,
                kind: menuKind,
                observationEpoch: epoch + 2
            )
        }
        jobs["app_window_selection"] = appSummary
        return [
            "schema_version": 1,
            "jobs": jobs,
        ]
    }

    static func summarizeObservation(_ observation: [String: Any]) -> [String: Any] {
        let candidates = observation["candidates"] as? [[String: Any]] ?? []
        var roles: [String: Int] = [:]
        var actions: [String: Int] = [:]
        for candidate in candidates {
            if let role = candidate["role"] as? String, !role.isEmpty {
                roles[role, default: 0] += 1
            }
            for action in candidate["supported_actions"] as? [String] ?? []
            where !action.isEmpty {
                actions[action, default: 0] += 1
            }
        }
        return [
            "bundle_id": observation["bundle_id"] as? String ?? "",
            "window_present": observation["window_id"] is Int,
            "candidate_count": observation["candidate_count"] as? Int ?? 0,
            "total_match_count": observation["total_match_count"] as? Int ?? 0,
            "truncated": observation["truncated"] as? Bool ?? false,
            "secure": observation["secure"] as? Bool ?? false,
            "denied": observation["denied"] as? Bool ?? false,
            "roles": roles,
            "actions": actions,
        ]
    }

    static func termGroups(for job: String) -> [[String]] {
        guard let query = queries.first(where: { $0.job == job }) else { return [] }
        return query.terms.isEmpty ? [[]] : query.terms.map { [$0] }
    }

    static func requiredActions(for job: String) -> [String] {
        queries.first(where: { $0.job == job })?.actions ?? []
    }

    static func menuTitles(for kind: String) -> [String] {
        [
            "document": ["new document", "new file"],
            "folder": ["new folder"],
            "note": ["new note"],
            "tab": ["new tab"],
            "window": ["new window"],
        ][kind] ?? []
    }

    private static func menuObservation(
        bundleID: String,
        kind: String,
        observationEpoch: Int
    ) -> [String: Any] {
        let titles = Set(menuTitles(for: kind))
        guard !titles.isEmpty,
              let request = NativeActionRequest.parse([
                  "turn_id": "capability-probe",
                  "observation_epoch": observationEpoch,
                  "request": [
                      "operation": "semantic_intent",
                      "target": [:],
                      "payload": ["family": "create", "kind": kind],
                      "risk": "navigation",
                      "strategy_ceiling": "semantic_only",
                      "timeout_ms": 4000,
                  ],
              ]) else {
            return emptyCandidateSummary(bundleID: bundleID)
        }
        let backend = NativeAXSemanticBackend()
        let observations = backend.captureMenuForPreparation(
            request: request,
            query: NativeObservationQuery(
                bundleID: bundleID,
                includeMenu: true,
                maxNodes: 500,
                maxDepth: 16
            ),
            matchingTitles: titles
        )
        let matches = observations.flatMap(\.nodes).filter {
            guard $0.role == "AXMenuItem", $0.enabled != false else { return false }
            let title = ($0.title ?? "")
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .folding(
                    options: [.caseInsensitive, .diacriticInsensitive],
                    locale: .current
                )
            return titles.contains(title)
        }
        var actions: [String: Int] = [:]
        for match in matches {
            for action in match.supportedActions {
                actions[action, default: 0] += 1
            }
        }
        return [
            "bundle_id": bundleID,
            "candidate_count": min(matches.count, 20),
            "total_match_count": matches.count,
            "truncated": matches.count > 20,
            "secure": observations.contains(where: \.secure),
            "denied": observations.contains(where: \.denied),
            "roles": matches.isEmpty ? [:] : ["AXMenuItem": matches.count],
            "actions": actions,
        ]
    }

    private static func emptyCandidateSummary(bundleID: String) -> [String: Any] {
        [
            "bundle_id": bundleID,
            "candidate_count": 0,
            "total_match_count": 0,
            "truncated": false,
            "secure": false,
            "denied": false,
            "roles": [:],
            "actions": [:],
        ]
    }

    static func validOutputPath(_ path: String) -> Bool {
        guard path.count <= 512, !path.contains("\0") else { return false }
        let url = URL(fileURLWithPath: path).standardizedFileURL
        return url.deletingLastPathComponent().path == artifactRoot
            && url.pathExtension == "json"
            && url.lastPathComponent.hasPrefix("capability-")
    }

    static func writeJSON(_ record: [String: Any], to path: String) -> Bool {
        guard validOutputPath(path),
              JSONSerialization.isValidJSONObject(record),
              let data = try? JSONSerialization.data(
                  withJSONObject: record,
                  options: [.sortedKeys]
              ) else { return false }
        do {
            try data.write(to: URL(fileURLWithPath: path), options: .atomic)
            return true
        } catch {
            return false
        }
    }
}
