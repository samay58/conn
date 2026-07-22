import Foundation
import Testing
@testable import Conn

@Suite("Native capability probe")
struct NativeCapabilityProbeRunnerTests {
    @Test("Probe runs only inside the marked lab guest")
    func labGuestBoundary() {
        let marker = { (path: String) in path == BridgeToken.labMarker }
        #expect(NativeCapabilityProbeRunner.isLabGuest([
            "CONN_LAB_GUEST": "1",
            "CONN_SERVER_PORT": "18787",
        ], fileExists: marker))
        #expect(!NativeCapabilityProbeRunner.isLabGuest([
            "CONN_LAB_GUEST": "1",
            "CONN_SERVER_PORT": "18787",
        ], fileExists: { _ in false }))
        #expect(!NativeCapabilityProbeRunner.isLabGuest([
            "CONN_LAB_GUEST": "1",
            "CONN_SERVER_PORT": "8787",
        ], fileExists: marker))
        #expect(!NativeCapabilityProbeRunner.isLabGuest([:], fileExists: marker))
    }

    @Test("Probe refuses an invalid explicit bundle identity")
    func invalidBundleRefuses() async {
        let result = await NativeCapabilityProbeRunner.run("../../private")

        #expect(result["outcome"] as? String == "failed")
        #expect(result["reason_code"] as? String == "invalid_bundle_id")
    }

    @Test("Probe output stays inside the lab artifact mount")
    func outputPathIsBounded() {
        #expect(NativeCapabilityProbeRunner.validOutputPath(
            "/Volumes/My Shared Files/artifacts/capability-finder.json"
        ))
        #expect(!NativeCapabilityProbeRunner.validOutputPath(
            "/Users/admin/private.json"
        ))
        #expect(!NativeCapabilityProbeRunner.validOutputPath(
            "/Volumes/My Shared Files/artifacts/../private.json"
        ))
    }

    @Test("History terms are measured separately and menus do not require AXPress")
    func queryContractMatchesPlatformShapes() {
        #expect(NativeCapabilityProbeRunner.termGroups(
            for: "document_history"
        ) == [["back"], ["forward"], ["next"], ["previous"], ["today"]])
        #expect(NativeCapabilityProbeRunner.requiredActions(
            for: "menus_overlays"
        ).isEmpty)
        #expect(NativeCapabilityProbeRunner.menuTitles(for: "tab") == [
            "new tab"
        ])
        #expect(NativeCapabilityProbeRunner.menuTitles(for: "unknown").isEmpty)
    }

    @Test("Observation summaries exclude labels and descriptors")
    func summaryExcludesPrivateCandidateContent() throws {
        let summary = NativeCapabilityProbeRunner.summarizeObservation([
            "bundle_id": "com.apple.finder",
            "window_id": 42,
            "candidate_count": 2,
            "total_match_count": 2,
            "truncated": false,
            "secure": false,
            "denied": false,
            "candidates": [
                [
                    "label": "Private Project",
                    "role": "AXButton",
                    "supported_actions": ["AXPress"],
                    "descriptor": ["display": "/Users/admin/Private"],
                ],
                [
                    "label": "Another Secret",
                    "role": "AXButton",
                    "supported_actions": ["AXPress", "AXShowMenu"],
                ],
            ],
        ])

        #expect(summary["bundle_id"] as? String == "com.apple.finder")
        #expect(summary["window_present"] as? Bool == true)
        #expect(summary["candidate_count"] as? Int == 2)
        #expect((summary["roles"] as? [String: Int]) == ["AXButton": 2])
        #expect((summary["actions"] as? [String: Int]) == [
            "AXPress": 2,
            "AXShowMenu": 1,
        ])
        let data = try JSONSerialization.data(withJSONObject: summary)
        let text = String(decoding: data, as: UTF8.self)
        #expect(!text.contains("Private"))
        #expect(!text.contains("Secret"))
        #expect(!text.contains("/Users"))
    }
}
