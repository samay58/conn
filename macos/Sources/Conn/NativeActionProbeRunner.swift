import AppKit

enum NativeActionProbeRunner {
    private static let applications: [String: (
        name: String, bundleID: String, teamID: String?
    )] = [
        "fixture": ("ConnActionFixture", "com.conn.ActionFixture", nil),
        "terminal": ("Terminal", "com.apple.Terminal", nil),
        "safari": ("Safari", "com.apple.Safari", nil),
        "chrome": ("Google Chrome", "com.google.Chrome", nil),
        "notes": ("Notes", "com.apple.Notes", nil),
        "obsidian": ("Obsidian", "md.obsidian", "6JSW4SJWN9"),
    ]

    static func run(_ name: String) async -> [String: Any] {
        guard let application = applications[name.lowercased()] else {
            return [
                "probe": name,
                "outcome": "failed",
                "independent_verdict": "unsupported_probe",
            ]
        }
        if name.lowercased() == "fixture" {
            return await runFixture(application: application)
        }
        return await runAppProbe(name: name, application: application)
    }

    private static func runAppProbe(
        name: String,
        application: (name: String, bundleID: String, teamID: String?)
    ) async -> [String: Any] {
        let engine = NativeSemanticActionEngine()
        let turnID = "probe-\(UUID().uuidString)"
        var payload: [String: Any] = [
            "app_name": application.name,
            "bundle_id": application.bundleID,
        ]
        if let teamID = application.teamID { payload["team_id"] = teamID }
        let plan = await engine.prepare([
            "turn_id": turnID,
            "response_epoch": 1,
            "observation_epoch": 1,
            "request": [
                "operation": "open",
                "target": [:],
                "payload": payload,
                "risk": "navigation",
                "strategy_ceiling": "semantic_only",
                "timeout_ms": 4000,
            ],
        ])
        guard let fingerprint = plan?["plan_fingerprint"] as? String else {
            return [
                "probe": name,
                "requested_effect": "Frontmost app is \(application.name)",
                "outcome": plan?["outcome"] as? String ?? "failed",
                "independent_verdict": "not_dispatched",
                "detail": plan ?? [:],
            ]
        }
        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": turnID,
            "response_epoch": 1,
            "observation_epoch": 1,
        ])
        let frontmost = visibleFrontmostBundleID()
        return [
            "probe": name,
            "requested_effect": "Frontmost app is \(application.name)",
            "engine_outcome": receipt["outcome"] as? String ?? "failed",
            "independent_verdict": frontmost == application.bundleID ? "matched" : "not_matched",
            "independent_bundle_id": frontmost ?? "none",
            "independent_source": "window_server_top_visible_window",
            "latency_ms": receipt["duration_ms"] as? Int ?? 0,
            "strategy": receipt["strategy"] as? String ?? "none",
            "evidence": receipt["evidence"] as? [[String: Any]] ?? [],
            "retry_safe": receipt["retry_safe"] as? Bool ?? false,
        ]
    }

    static func frontmostVisibleOwnerPID(
        from windows: [[String: Any]],
        eligiblePIDs: Set<pid_t>? = nil
    ) -> pid_t? {
        for window in windows {
            let layer = (window[kCGWindowLayer as String] as? NSNumber)?.intValue
            let alpha = (window[kCGWindowAlpha as String] as? NSNumber)?.doubleValue
            let onScreen = window[kCGWindowIsOnscreen as String] as? Bool
            let bounds = window[kCGWindowBounds as String] as? [String: Any]
            let width = (bounds?["Width"] as? NSNumber)?.doubleValue ?? 0
            let height = (bounds?["Height"] as? NSNumber)?.doubleValue ?? 0
            guard layer == 0, alpha.map({ $0 > 0 }) ?? true,
                  onScreen != false, width > 1, height > 1,
                  let pid = (window[kCGWindowOwnerPID as String] as? NSNumber)?.int32Value
            else { continue }
            if let eligiblePIDs, !eligiblePIDs.contains(pid) { continue }
            return pid
        }
        return nil
    }

    private static func visibleFrontmostBundleID() -> String? {
        let regularApplications = NSWorkspace.shared.runningApplications.filter {
            $0.activationPolicy == .regular
        }
        let eligiblePIDs = Set(regularApplications.map(\.processIdentifier))
        guard let windows = CGWindowListCopyWindowInfo(
            [.optionOnScreenOnly, .excludeDesktopElements],
            kCGNullWindowID
        ) as? [[String: Any]],
              let pid = frontmostVisibleOwnerPID(
                from: windows, eligiblePIDs: eligiblePIDs
              ),
              let app = NSRunningApplication(processIdentifier: pid) else { return nil }
        return app.bundleIdentifier
    }

    private static func runFixture(
        application: (name: String, bundleID: String, teamID: String?)
    ) async -> [String: Any] {
        guard let running = NSRunningApplication
            .runningApplications(withBundleIdentifier: application.bundleID).first,
              running.activate(options: [.activateAllWindows]) else {
            return [
                "probe": "fixture",
                "outcome": "failed",
                "independent_verdict": "fixture_not_running",
            ]
        }
        try? await Task.sleep(for: .milliseconds(150))
        let engine = NativeSemanticActionEngine()
        let turnID = "probe-\(UUID().uuidString)"
        let observation = await engine.observe([
            "turn_id": turnID,
            "observation_epoch": 1,
            "query": [
                "search_terms": ["fixture.no_effect"],
                "expected_roles": ["AXButton"],
                "expected_actions": ["AXPress"],
                "max_nodes": 500,
                "max_depth": 16,
            ],
        ])
        let candidates = observation["candidates"] as? [[String: Any]] ?? []
        guard candidates.count == 1,
              let targetRef = candidates[0]["ref"] as? String,
              let snapshotID = observation["snapshot_id"] as? String else {
            return [
                "probe": "fixture",
                "outcome": "failed",
                "independent_verdict": "fixture_target_not_observed",
                "bundle_id": observation["bundle_id"] as? String ?? "unknown",
                "candidate_count": candidates.count,
            ]
        }
        let plan = await engine.prepare([
            "turn_id": turnID,
            "response_epoch": 1,
            "observation_epoch": 1,
            "request": [
                "operation": "press",
                "target": ["snapshot_id": snapshotID, "ref": targetRef],
                "payload": [:],
                "desired_effect": [
                    "mode": "all",
                    "predicates": [[
                        "kind": "element_attribute_changes",
                        "ref": targetRef,
                        "attribute": "value",
                    ]],
                ],
                "risk": "navigation",
                "strategy_ceiling": "semantic_only",
                "timeout_ms": 500,
            ],
        ])
        guard let fingerprint = plan?["plan_fingerprint"] as? String else {
            return [
                "probe": "fixture",
                "outcome": plan?["outcome"] as? String ?? "failed",
                "independent_verdict": "not_dispatched",
                "detail": plan ?? [:],
            ]
        }
        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": turnID,
            "response_epoch": 1,
            "observation_epoch": 1,
        ])
        return [
            "probe": "fixture",
            "requested_effect": "No-effect fixture button value changes",
            "engine_outcome": receipt["outcome"] as? String ?? "failed",
            "latency_ms": receipt["duration_ms"] as? Int ?? 0,
            "strategy": receipt["strategy"] as? String ?? "none",
            "evidence": receipt["evidence"] as? [[String: Any]] ?? [],
            "retry_safe": receipt["retry_safe"] as? Bool ?? false,
            "truth_log_required": true,
        ]
    }

    static func printJSON(_ record: [String: Any]) {
        guard let data = try? JSONSerialization.data(
            withJSONObject: record,
            options: [.sortedKeys]
        ), let text = String(data: data, encoding: .utf8) else { return }
        print(text)
    }
}
