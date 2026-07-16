import XCTest
@testable import Conn

/// R3 vertical slices: `create(kind=tab)` and `select_relative` compile from
/// live native affordances with no model-authored menu paths, key chords,
/// refs, or effect predicates. The outcome ceiling stays truthful: menu
/// dispatch without a causal witness is dispatch_only, never verified.
final class SemanticIntentTests: XCTestCase {
    func testCreateTabCompilesFromLiveMenuAffordance() async throws {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))

        let strategies = try XCTUnwrap(plan?["authorized_strategies"] as? [String])
        XCTAssertEqual(strategies, ["ax_menu_action", "live_menu_shortcut"])
        XCTAssertNotNil(plan?["plan_fingerprint"])
        let preview = try XCTUnwrap(plan?["preview"] as? String)
        XCTAssertTrue(preview.localizedCaseInsensitiveContains("new tab"),
                      "preview was \(preview)")
    }

    func testCreateTabWithACollectionWitnessVerifies() async throws {
        let backend = IntentFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])
        XCTAssertEqual(predicates.first?["kind"] as? String,
                       "collection_descendant_role_count_increases")
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])
        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.captureIncludesMenu.first, true)
        XCTAssertEqual(backend.captureIncludesMenu.last, true)
        XCTAssertNil(backend.captureDeadlines.first ?? nil)
        XCTAssertNotNil(backend.captureDeadlines.last ?? nil)
        XCTAssertEqual(receipt["ok"] as? Bool, true)
    }

    func testNestedSafariTabStripWithOneTabBindsTheStableCollection() async throws {
        let backend = IntentFixtureBackend()
        backend.usePersistentNestedTabStripWithOneInitialTab()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])

        XCTAssertEqual(predicates.first?["ref"] as? String, "tab-bar")
    }

    func testCreateTabWitnessAllowsOnlyTheCollectionDescriptionToChange() async throws {
        let backend = IntentFixtureBackend()
        backend.usePersistentNestedTabStripWithOneInitialTab()
        backend.includeDynamicTabDescription = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(receipt["ok"] as? Bool, true)
    }

    func testCreateTabWitnessRefusesChangedCollectionIdentity() async throws {
        let backend = IntentFixtureBackend()
        backend.usePersistentNestedTabStripWithOneInitialTab()
        backend.changeTabCollectionIdentityAfterDispatch = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "no_effect")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testCreateTabCapsAtDispatchOnlyWhenCollectionAppearsAfterDispatch() async throws {
        let backend = IntentFixtureBackend()
        backend.useNestedTabStripWithOneInitialTab()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])
        XCTAssertTrue(predicates.isEmpty)
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testCreateTabDoesNotVerifyAnUnrelatedRadioButton() async throws {
        let backend = IntentFixtureBackend()
        backend.useNestedTabStripWithOneInitialTab()
        backend.onlyAddUnrelatedRadioOnDispatch()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testCreateTabWithoutAResultCollectionCannotVerify() async throws {
        let backend = IntentFixtureBackend()
        backend.includeTabGroup = false
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "tab"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testCreateNoteChoosesTheNoteListAmongMultipleCollections() async throws {
        let backend = IntentFixtureBackend()
        backend.includeNewNoteMenu = true
        backend.includeFolderOutline = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "note"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])
        XCTAssertEqual(predicates.first?["kind"] as? String,
                       "collection_descendant_role_count_increases")
        XCTAssertEqual(predicates.first?["ref"] as? String, "notes-list")
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }

    func testCreateNoteWithTwoNoteListsCapsAtDispatchOnly() async throws {
        let backend = IntentFixtureBackend()
        backend.includeNewNoteMenu = true
        backend.includeSecondNoteList = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "note"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])
        XCTAssertTrue(predicates.isEmpty)
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "dispatch_only")
        XCTAssertEqual(receipt["ok"] as? Bool, false)
    }

    func testVirtualizedNoteListIdentityChangeUsesTargetBoundWitness() async throws {
        let backend = IntentFixtureBackend()
        backend.includeNewNoteMenu = true
        backend.virtualizeNoteListAfterDispatch = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "note"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }

    func testCreateWindowDerivesAWindowCountWitness() async throws {
        let backend = IntentFixtureBackend()
        backend.includeNewWindowMenu = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "window"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])
        XCTAssertEqual(predicates.first?["kind"] as? String, "window_count_delta")
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }

    func testCreateWindowCanVerifyAfterNewWindowTakesFocus() async throws {
        let backend = IntentFixtureBackend()
        backend.includeNewWindowMenu = true
        backend.focusCreatedWindowOnDispatch = true
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "window"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(receipt["ok"] as? Bool, true)
    }

    func testCreateWindowDiscoversLazyMenuAndKeepsItsExactPath() async throws {
        let backend = IntentFixtureBackend()
        backend.useLazyNewWindowMenu()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "window"]))

        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
        let candidates = try XCTUnwrap(plan?["candidates"] as? [[String: Any]])
        XCTAssertEqual(candidates.first?["menu_path"] as? [String],
                       ["Actions", "New Window"])
        XCTAssertEqual(backend.menuDiscoveryCount, 1)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.lastMenuPath, ["Actions", "New Window"])
    }

    func testCreateWindowRefusesAmbiguousLazyMenuPaths() async {
        let backend = IntentFixtureBackend()
        backend.useAmbiguousLazyNewWindowMenus()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "window"]))

        XCTAssertEqual(plan?["outcome"] as? String, "ambiguous")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testPlanDeclaresItsReadAndWitnessSets() async throws {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "next", "kind": "tab"]))

        let readSet = try XCTUnwrap(plan?["read_set"] as? [String])
        XCTAssertFalse(readSet.isEmpty)
    }

    func testCreateWithNoLiveAffordanceRefusesTruthfully() async {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "create", slots: ["kind": "folder"]))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "no_live_affordance")
        XCTAssertEqual(plan?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(plan?["retry_safe"] as? Bool, true)
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testSelectRelativeNextResolvesTheSiblingWithAWitness() async throws {
        let backend = IntentFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "next", "kind": "document"]))
        let predicates = try XCTUnwrap(plan?["predicates"] as? [[String: Any]])
        XCTAssertEqual(predicates.count, 1)
        XCTAssertEqual(predicates[0]["kind"] as? String, "element_attribute_equals")
        XCTAssertEqual(predicates[0]["attribute"] as? String, "selected")
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(receipt["ok"] as? Bool, true)
        XCTAssertEqual(backend.lastDispatchedIdentifier, "notes.row.2")
    }

    func testSelectRelativeAtTheEndRefusesTruthfully() async {
        let backend = IntentFixtureBackend()
        backend.selectLastRow()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "next", "kind": "document"]))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "no_relative_item")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testSelectRelativePreviousResolvesBackwards() async throws {
        let backend = IntentFixtureBackend()
        backend.selectLastRow()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "previous", "kind": "document"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.lastDispatchedIdentifier, "notes.row.1")
    }

    func testSelectRelativeNoteIgnoresSelectedFolderOutline() async throws {
        let backend = IntentFixtureBackend()
        backend.includeFolderOutline = true
        backend.selectLastRow()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "previous", "kind": "note"]))
        XCTAssertEqual(
            plan?["authorized_strategies"] as? [String],
            ["ax_set_selected_rows", "ax_set_selected"]
        )
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.lastDispatchedIdentifier, "notes.row.1")
    }

    func testSelectRelativeNoteRefusesTwoSelectedMultiRowNoteLists() async {
        let backend = IntentFixtureBackend()
        backend.includeSecondNoteList = true
        backend.selectLastRow()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "previous", "kind": "note"]))

        XCTAssertEqual(plan?["outcome"] as? String, "ambiguous")
        XCTAssertEqual(plan?["error"] as? String, "ambiguous_intent")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testSelectRelativeNoteReResolvesAnonymousRowsByDescendantTitle() async throws {
        let backend = IntentFixtureBackend()
        backend.useAnonymousNoteRows()
        backend.selectLastRow()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "previous", "kind": "note"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])
        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.lastDispatchedRef, "row-1")
    }

    func testSelectRelativeTabKindUsesTheTabGroup() async throws {
        let backend = IntentFixtureBackend()
        backend.effectOnDispatch = true
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "select_relative",
            slots: ["relation": "next", "kind": "tab"]))
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        XCTAssertEqual(backend.lastDispatchedIdentifier, "tabs.2")
    }

    func testIntentWithCallerSuppliedPredicatesIsRejected() async {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        var params = intentParams(family: "create", slots: ["kind": "tab"])
        var request = params["request"] as? [String: Any] ?? [:]
        request["desired_effect"] = [
            "mode": "all",
            "predicates": [["kind": "window_title_changes"]],
        ]
        params["request"] = request

        let plan = await engine.prepare(params)

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "intent_rejects_predicates")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testUnknownIntentFamilyRefuses() async {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare(intentParams(
            family: "run_macro", slots: [:]))

        XCTAssertEqual(plan?["outcome"] as? String, "failed")
        XCTAssertEqual(plan?["error"] as? String, "unsupported_intent")
    }

    private func intentParams(
        family: String, slots: [String: String]
    ) -> [String: Any] {
        var payload: [String: Any] = ["family": family]
        for (key, value) in slots { payload[key] = value }
        return [
            "turn_id": "turn-1",
            "response_epoch": 1,
            "observation_epoch": 1,
            "request": [
                "operation": "semantic_intent",
                "payload": payload,
                "risk": "reversible_navigation",
                "timeout_ms": 20,
            ] as [String: Any],
        ]
    }
}

/// A Safari-and-Notes-shaped surface: one live "New Tab" menu leaf, one tab
/// group, one document list with a selection. No app-specific command data;
/// the engine must discover everything from this tree.
final class IntentFixtureBackend: NativeSemanticBackend, @unchecked Sendable {
    var effectOnDispatch = false
    var bundleID = "com.conn.intentfixture"
    var includeTabGroup = true
    var includeNewWindowMenu = false
    var includeNewNoteMenu = false
    var includeFolderOutline = false
    var includeSecondNoteList = false
    var virtualizeNoteListAfterDispatch = false
    var includeDynamicTabDescription = false
    var changeTabCollectionIdentityAfterDispatch = false
    var focusCreatedWindowOnDispatch = false
    private(set) var captureIncludesMenu: [Bool] = []
    private(set) var captureDeadlines: [Int?] = []
    private(set) var dispatchCount = 0
    private(set) var lastDispatchedIdentifier: String?
    private(set) var lastDispatchedRef: String?
    private(set) var lastMenuPath: [String]?
    private(set) var menuDiscoveryCount = 0
    private var selectedRow = 1
    private var selectedTab = 1
    private var tabCount = 2
    private var noteCount = 2
    private var windowCount = 1
    private var windowID: UInt32 = 7
    private var nestedTabStrip = false
    private var persistentNestedTabStrip = false
    private var createTabOnDispatch = true
    private var addUnrelatedRadioOnDispatch = false
    private var lazyNewWindowMenu = false
    private var menuDiscoveryActive = false
    private var ambiguousLazyNewWindowMenus = false
    private var anonymousNoteRows = false
    private var lazyMenuParentTitle = "Actions"

    func selectLastRow() {
        selectedRow = 2
    }

    func useAnonymousNoteRows() {
        anonymousNoteRows = true
    }

    func useNestedTabStripWithOneInitialTab() {
        nestedTabStrip = true
        tabCount = 1
    }

    func usePersistentNestedTabStripWithOneInitialTab() {
        nestedTabStrip = true
        persistentNestedTabStrip = true
        tabCount = 1
    }

    func onlyAddUnrelatedRadioOnDispatch() {
        effectOnDispatch = true
        createTabOnDispatch = false
        addUnrelatedRadioOnDispatch = true
    }

    func useLazyNewWindowMenu() {
        lazyNewWindowMenu = true
        includeNewWindowMenu = true
    }

    func useAmbiguousLazyNewWindowMenus() {
        useLazyNewWindowMenu()
        ambiguousLazyNewWindowMenus = true
    }

    func capture(
        turnID: String, observationEpoch: Int, query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        captureIncludesMenu.append(query.includeMenu)
        captureDeadlines.append(query.deadlineMs)
        var nodes = [
            NativeObservationNode(ref: "menu-bar", role: "AXMenuBar"),
            NativeObservationNode(
                ref: "file-menu", parentRef: "menu-bar", role: "AXMenuBarItem",
                title: "File", supportedActions: ["AXPress"]),
            NativeObservationNode(
                ref: "new-tab", parentRef: "file-menu", role: "AXMenuItem",
                title: "New Tab", enabled: true,
                supportedActions: ["AXPress"], menuShortcut: ["cmd", "t"]),
            NativeObservationNode(
                ref: "new-private", parentRef: "file-menu", role: "AXMenuItem",
                title: "New Private Window", enabled: true,
                supportedActions: ["AXPress"]),
        ]
        if includeNewWindowMenu && (!lazyNewWindowMenu || menuDiscoveryActive) {
            let parentRef = lazyNewWindowMenu
                ? "menu-\(lazyMenuParentTitle.lowercased())" : "file-menu"
            nodes.append(NativeObservationNode(
                ref: "new-window",
                parentRef: parentRef,
                role: "AXMenuItem",
                title: "New Window", enabled: true,
                supportedActions: ["AXPress"]))
        }
        if lazyNewWindowMenu {
            nodes.append(NativeObservationNode(
                ref: "menu-\(lazyMenuParentTitle.lowercased())",
                parentRef: "menu-bar",
                role: "AXMenuBarItem", title: lazyMenuParentTitle,
                supportedActions: ["AXPress"]))
        }
        if includeNewNoteMenu {
            nodes.append(NativeObservationNode(
                ref: "new-note", parentRef: "file-menu", role: "AXMenuItem",
                title: "New Note", enabled: true,
                supportedActions: ["AXPress"], menuShortcut: ["cmd", "n"]))
        }
        if includeTabGroup {
            nodes.append(NativeObservationNode(
                ref: "tab-group", path: [0], role: "AXTabGroup",
                description: includeDynamicTabDescription
                    ? "Browser tabs, \(tabCount) tabs" : nil))
            let tabParent: String
            let tabParentPath: [Int]
            if nestedTabStrip {
                nodes.append(NativeObservationNode(
                    ref: "browser-window", path: [1], role: "AXWindow",
                    title: includeDynamicTabDescription
                        ? "Selected tab \(tabCount)" : "Selected tab"))
                nodes.append(NativeObservationNode(
                    ref: "tab-content", parentRef: "tab-group", path: [0, 0],
                    role: "AXScrollArea"))
                tabParent = "tab-bar"
                tabParentPath = [1]
                if tabCount > 1 || persistentNestedTabStrip {
                    nodes.append(NativeObservationNode(
                        ref: tabParent, parentRef: "browser-window",
                        path: tabParentPath,
                        role: "AXOpaqueProviderGroup",
                        description: includeDynamicTabDescription
                            ? "Tab bar, \(tabCount) tabs" : nil,
                        identifier: (
                            changeTabCollectionIdentityAfterDispatch
                                && dispatchCount > 0
                        )
                            ? "ReplacementTabBar"
                            : "TabBar?isSeparate=false"))
                }
            } else {
                tabParent = "tab-group"
                tabParentPath = [0]
            }
            if !nestedTabStrip || tabCount > 1 || persistentNestedTabStrip {
                for index in 1...tabCount {
                    nodes.append(NativeObservationNode(
                        ref: "tab-\(index)", parentRef: tabParent,
                        path: tabParentPath + [index - 1],
                        role: "AXRadioButton",
                        title: index == 1 ? "First" : "Second",
                        identifier: "tabs.\(index)",
                        selected: selectedTab == index,
                        supportedActions: ["AXPress"],
                        settableAttributes: ["AXSelected"]))
                }
            }
        }
        let notesListRef = virtualizeNoteListAfterDispatch && dispatchCount > 0
            ? "notes-list-v2" : "notes-list"
        nodes.append(NativeObservationNode(
            ref: notesListRef, path: [2], role: "AXTable"))
        for index in 1...noteCount {
            nodes.append(NativeObservationNode(
                ref: "row-\(index)", parentRef: notesListRef, path: [2, index - 1],
                role: "AXRow", title: index == 1 ? "Groceries" : "Ideas",
                identifier: anonymousNoteRows ? nil : "notes.row.\(index)",
                selected: selectedRow == index,
                settableAttributes: ["AXSelected"]))
            if anonymousNoteRows {
                nodes[nodes.count - 1].title = nil
                nodes.append(NativeObservationNode(
                    ref: "row-\(index)-title",
                    parentRef: "row-\(index)",
                    path: [2, index - 1, 0],
                    role: "AXStaticText",
                    title: index == 1 ? "Groceries" : "Ideas"
                ))
            }
        }
        if includeFolderOutline {
            nodes.append(NativeObservationNode(
                ref: "folders", path: [3], role: "AXOutline"))
            nodes.append(NativeObservationNode(
                ref: "folder-row", parentRef: "folders", path: [3, 0],
                role: "AXRow", title: "Folder", selected: true))
            nodes.append(NativeObservationNode(
                ref: "folder-row-2", parentRef: "folders", path: [3, 1],
                role: "AXRow", title: "Recently Deleted"))
        }
        if includeSecondNoteList {
            nodes.append(NativeObservationNode(
                ref: "other-notes", path: [4], role: "AXTable"))
            nodes.append(NativeObservationNode(
                ref: "other-row-1", parentRef: "other-notes", path: [4, 0],
                role: "AXRow", title: "Other", selected: true))
            nodes.append(NativeObservationNode(
                ref: "other-row-2", parentRef: "other-notes", path: [4, 1],
                role: "AXRow", title: "Another"))
        }
        if addUnrelatedRadioOnDispatch && dispatchCount > 0 {
            nodes.append(NativeObservationNode(
                ref: "unrelated-radio", path: [5], role: "AXRadioButton",
                title: "Unrelated"))
        }
        var observation = NativeCapturedObservation.fixture(
            turnID: turnID,
            observationEpoch: observationEpoch,
            nodes: nodes,
            bundleID: bundleID,
            windowID: windowID
        )
        observation.windowCount = windowCount
        return observation
    }

    func captureMenuForPreparation(
        request: NativeActionRequest,
        query: NativeObservationQuery,
        matchingTitles: Set<String>
    ) -> [NativeCapturedObservation] {
        menuDiscoveryCount += 1
        menuDiscoveryActive = true
        defer { menuDiscoveryActive = false }
        let first = capture(
            turnID: request.turnID,
            observationEpoch: request.observationEpoch,
            query: query
        )
        guard ambiguousLazyNewWindowMenus else { return [first] }
        lazyMenuParentTitle = "Window"
        defer { lazyMenuParentTitle = "Actions" }
        return [first, capture(
            turnID: request.turnID,
            observationEpoch: request.observationEpoch,
            query: query
        )]
    }

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool { true }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        dispatchCount += 1
        lastDispatchedIdentifier = target?.current.identifier
        lastDispatchedRef = target?.current.ref
        lastMenuPath = request.payload.menuPath
        guard effectOnDispatch else {
            return NativeDispatchResult(state: .dispatched, nativeError: nil)
        }
        if strategy == .axMenuAction || strategy == .liveMenuShortcut {
            let leaf = request.payload.menuPath.last ?? ""
            if leaf == "New Tab" && createTabOnDispatch { tabCount += 1 }
            if leaf == "New Note" { noteCount += 1 }
            if leaf == "New Window" { windowCount += 1 }
            if leaf == "New Window" && focusCreatedWindowOnDispatch {
                windowID += 1
            }
        }
        switch target?.current.identifier {
        case "tabs.2": selectedTab = 2
        case "tabs.1": selectedTab = 1
        case "notes.row.2": selectedRow = 2
        case "notes.row.1": selectedRow = 1
        default: break
        }
        if anonymousNoteRows {
            switch target?.current.ref {
            case "row-2": selectedRow = 2
            case "row-1": selectedRow = 1
            default: break
            }
        }
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }
}

/// R4: the capability report is descriptive, bounded, epoch-bound, and can
/// never authorize or dispatch anything (it carries no plan fingerprint).
final class CapabilityReportTests: XCTestCase {
    func testReportListsRankedCreateAndSelectCandidates() async throws {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let maybeReport = await engine.perform(
            op: "capability_report",
            params: ["turn_id": "turn-1", "observation_epoch": 3])
        let report = try XCTUnwrap(maybeReport)

        XCTAssertEqual(report["turn_id"] as? String, "turn-1")
        XCTAssertEqual(report["observation_epoch"] as? Int, 3)
        let candidates = try XCTUnwrap(report["candidates"] as? [[String: Any]])
        XCTAssertFalse(candidates.isEmpty)
        XCTAssertLessThanOrEqual(candidates.count, 20)
        let families = Set(candidates.compactMap { $0["intent"] as? String })
        XCTAssertTrue(families.contains("create"))
        XCTAssertTrue(families.contains("select_relative"))
        let create = try XCTUnwrap(candidates.first {
            $0["intent"] as? String == "create" && $0["kind"] as? String == "tab"
        })
        XCTAssertEqual(create["ceiling"] as? String, "dispatch_only")
        XCTAssertEqual(create["menu_path"] as? [String], ["File", "New Tab"])
        XCTAssertEqual(create["shortcut"] as? [String], ["cmd", "t"])
        let select = try XCTUnwrap(candidates.first {
            $0["intent"] as? String == "select_relative"
                && $0["kind"] as? String == "tab"
        })
        XCTAssertEqual(select["ceiling"] as? String, "verified")
        XCTAssertNil(report["plan_fingerprint"],
                     "a report can never carry dispatch authority")
        XCTAssertEqual(backend.dispatchCount, 0)
    }

    func testReportContainsNoPlanFingerprintsInCandidates() async throws {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let maybeReport = await engine.perform(
            op: "capability_report",
            params: ["turn_id": "turn-1", "observation_epoch": 1])
        let report = try XCTUnwrap(maybeReport)

        let candidates = try XCTUnwrap(report["candidates"] as? [[String: Any]])
        for candidate in candidates {
            XCTAssertNil(candidate["plan_fingerprint"])
        }
    }

    func testIntentPlanRecordsRankedCandidates() async throws {
        let backend = IntentFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)

        let plan = await engine.prepare([
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
            "request": [
                "operation": "semantic_intent",
                "payload": ["family": "create", "kind": "tab"],
                "risk": "reversible_navigation",
                "timeout_ms": 20,
            ] as [String: Any],
        ])

        let candidates = try XCTUnwrap(plan?["candidates"] as? [[String: Any]])
        XCTAssertEqual(candidates.count, 1)
        XCTAssertEqual(candidates[0]["title"] as? String, "New Tab")
    }
}

/// R5: verification rereads with adaptive backoff instead of a fixed 25ms
/// full-tree poll. A delayed valid effect still verifies, with far fewer
/// recaptures.
final class AdaptiveVerificationTests: XCTestCase {
    func testDelayedEffectVerifiesWithBoundedRecaptures() async throws {
        let backend = DelayedEffectBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let observation = await engine.observe([
            "turn_id": "turn-1", "observation_epoch": 1,
        ])
        _ = observation
        let plan = await engine.prepare([
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
            "request": [
                "operation": "press",
                "target": ["ref": "delayed"],
                "risk": "local_mutation",
                "timeout_ms": 1500,
            ] as [String: Any],
        ])
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)
        let capturesBefore = backend.captureCount

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
        let verificationCaptures = backend.captureCount - capturesBefore
        XCTAssertLessThanOrEqual(
            verificationCaptures, 8,
            "adaptive backoff must not poll the tree every 25ms")
    }
}

/// A checkbox whose value flips 350ms after dispatch, measured on the wall
/// clock: the old fixed 25ms loop recaptured ~14 times before seeing it.
final class DelayedEffectBackend: NativeSemanticBackend, @unchecked Sendable {
    private(set) var captureCount = 0
    private var dispatchedAt: Date?

    func capture(
        turnID: String, observationEpoch: Int, query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        captureCount += 1
        let effectLanded = dispatchedAt.map {
            Date().timeIntervalSince($0) > 0.35
        } ?? false
        let nodes = [
            NativeObservationNode(
                ref: "delayed", role: "AXCheckBox", title: "Delayed",
                identifier: "fixture.delayed",
                redactedValue: effectLanded ? "true" : "false",
                valueType: "boolean", enabled: true,
                supportedActions: ["AXPress"]),
        ]
        return NativeCapturedObservation.fixture(
            turnID: turnID, observationEpoch: observationEpoch,
            nodes: nodes, bundleID: "com.conn.delayed", windowID: 3)
    }

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool { true }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        dispatchedAt = Date()
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }
}

/// A target app that emits a fresh AX notification on every capture: the
/// verification fast path must keep yielding and still terminate.
final class NoisyNotificationBackend: NativeSemanticBackend, @unchecked Sendable {
    private(set) var captureCount = 0
    private var dispatched = false

    func capture(
        turnID: String, observationEpoch: Int, query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        captureCount += 1
        let effectLanded = dispatched && captureCount > 6
        let nodes = [
            NativeObservationNode(
                ref: "noisy", role: "AXCheckBox", title: "Noisy",
                identifier: "fixture.noisy",
                redactedValue: effectLanded ? "true" : "false",
                valueType: "boolean", enabled: true,
                supportedActions: ["AXPress"]),
        ]
        var observation = NativeCapturedObservation.fixture(
            turnID: turnID, observationEpoch: observationEpoch,
            nodes: nodes, bundleID: "com.conn.noisy", windowID: 5)
        observation.notifications = Array(
            repeating: "AXValueChanged", count: min(captureCount, 32))
        return observation
    }

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool { true }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        dispatched = true
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }
}

final class NoisyNotificationVerificationTests: XCTestCase {
    func testGrowingNotificationsStillVerifyAndTerminate() async throws {
        let backend = NoisyNotificationBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = await engine.prepare([
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
            "request": [
                "operation": "press",
                "target": ["ref": "noisy"],
                "risk": "local_mutation",
                "timeout_ms": 1500,
            ] as [String: Any],
        ])
        let fingerprint = try XCTUnwrap(plan?["plan_fingerprint"] as? String)

        let receipt = await engine.execute([
            "plan_fingerprint": fingerprint,
            "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
        ])

        XCTAssertEqual(receipt["outcome"] as? String, "verified")
    }
}
