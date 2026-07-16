import XCTest
@testable import ConnActionFixture

final class ActionFixtureTests: XCTestCase {
    func testTruthLogRemainsAppendOnlyAcrossFixtureReset() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let first = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])
        first.record("scene_ready", value: "first")
        let second = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])
        second.record("scene_ready", value: "second")

        XCTAssertEqual(
            second.entries().compactMap { $0["value"] as? String },
            ["first", "second"]
        )
    }

    func testSceneCatalogHasStableDistinctInitialStateDigests() {
        XCTAssertEqual(FixtureScene.allCases.map(\.rawValue), [
            "unique_control",
            "stable_duplicate",
            "genuine_ambiguity",
            "secure_field",
            "lazy_menu",
            "menu_recapture",
            "nested_tabs",
            "notes_collections",
            "delayed_verification",
            "no_effect",
            "opaque_media",
            "stale_window_frame",
            "reordered_siblings",
            "changed_window_app",
            "uncertain_dispatch",
        ])
        let digests = FixtureScene.allCases.map(\.initialStateDigest)

        XCTAssertEqual(Set(digests).count, FixtureScene.allCases.count)
        XCTAssertTrue(digests.allSatisfy { $0.count == 64 })
        for scene in FixtureScene.allCases {
            XCTAssertEqual(
                Set((0..<20).map { _ in scene.initialStateDigest }),
                [scene.initialStateDigest]
            )
        }
    }

    func testSceneSelectionRejectsUnknownNames() {
        XCTAssertEqual(
            FixtureScene.select(
                arguments: ["fixture", "--scene", "opaque_media"],
                environment: [:]
            ),
            .opaqueMedia
        )
        XCTAssertEqual(
            FixtureScene.select(arguments: ["fixture"], environment: [:]),
            .noEffect
        )
        XCTAssertNil(FixtureScene.select(
            arguments: ["fixture"],
            environment: ["CONN_FIXTURE_SCENE": "not_a_scene"]
        ))
    }

    func testSceneReadyTruthBindsNameAndInitialDigest() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let truth = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])

        truth.recordSceneReady(.nestedTabs)

        let entry = truth.entries().last
        XCTAssertEqual(entry?["effect"] as? String, "scene_ready")
        XCTAssertEqual(entry?["scene"] as? String, "nested_tabs")
        XCTAssertEqual(
            entry?["initial_state_digest"] as? String,
            FixtureScene.nestedTabs.initialStateDigest
        )
    }

    @MainActor
    func testSceneViewsExposeTheIntendedNativeShapes() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let truth = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])

        let unique = FixtureController(scene: .uniqueControl, truth: truth)
        let uniqueControl = descendants(of: unique.buildContent())
            .compactMap { $0 as? NSButton }
            .first { $0.accessibilityIdentifier() == "fixture.unique" }
        XCTAssertEqual(
            identifiers(in: unique.buildContent()),
            ["fixture.unique"]
        )
        uniqueControl?.performClick(nil)
        XCTAssertEqual(
            truth.entries().last?["effect"] as? String,
            "control_changed"
        )

        let ambiguous = FixtureController(scene: .genuineAmbiguity, truth: truth)
        let ambiguousViews = descendants(of: ambiguous.buildContent())
        XCTAssertEqual(
            ambiguousViews.compactMap { ($0 as? NSButton)?.title }
                .filter { $0 == "Duplicate" }.count,
            2
        )
        XCTAssertTrue(identifiers(in: ambiguousViews).isEmpty)

        let nested = FixtureController(scene: .nestedTabs, truth: truth)
        XCTAssertTrue(identifiers(in: nested.buildContent()).isSuperset(of: [
            "fixture.tab.collection",
            "fixture.tab.1",
            "fixture.tab.2",
        ]))

        let notes = FixtureController(scene: .notesCollections, truth: truth)
        XCTAssertTrue(identifiers(in: notes.buildContent()).isSuperset(of: [
            "fixture.notes.primary",
            "fixture.notes.secondary",
        ]))

        let opaque = FixtureController(scene: .opaqueMedia, truth: truth)
        let opaqueIDs = identifiers(in: opaque.buildContent())
        XCTAssertTrue(opaqueIDs.contains("fixture.opaque_media"))
        XCTAssertFalse(opaqueIDs.contains("fixture.secure"))
    }

    @MainActor
    func testControllerResetChangesSceneAndRecordsBoundDigest() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let truth = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])
        let controller = FixtureController(scene: .uniqueControl, truth: truth)

        controller.reset(to: .opaqueMedia)

        XCTAssertEqual(controller.scene, .opaqueMedia)
        let reset = truth.entries().last
        XCTAssertEqual(reset?["effect"] as? String, "scene_reset")
        XCTAssertEqual(reset?["scene"] as? String, "opaque_media")
        XCTAssertEqual(
            reset?["initial_state_digest"] as? String,
            FixtureScene.opaqueMedia.initialStateDigest
        )
    }

    func testAccessibilityPressCanReportSuccessWithoutFixtureEffect() throws {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let truth = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])
        let button = NoEffectButton(title: "Reports success, no effect", target: nil, action: nil)

        XCTAssertTrue(button.accessibilityPerformPress())
        XCTAssertTrue(truth.entries().isEmpty)
    }

    func testOpaquePlaybackTargetRecordsIndependentVisualTruth() {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let truth = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])
        let target = OpaquePlaybackTarget(truth: truth)

        target.activate()

        XCTAssertEqual(target.state, "pause")
        XCTAssertEqual(truth.entries().last?["effect"] as? String, "playback_changed")
        XCTAssertEqual(truth.entries().last?["value"] as? String, "pause")
        XCTAssertFalse(target.isAccessibilityElement())
    }

    private func descendants(of root: NSView) -> [NSView] {
        [root] + root.subviews.flatMap(descendants)
    }

    private func identifiers(in root: NSView) -> Set<String> {
        identifiers(in: descendants(of: root))
    }

    private func identifiers(in views: [NSView]) -> Set<String> {
        Set(views.compactMap { view in
            let identifier = view.accessibilityIdentifier()
            return identifier.isEmpty ? nil : identifier
        })
    }
}
