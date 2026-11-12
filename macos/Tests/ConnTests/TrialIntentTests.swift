import Foundation
import Testing
@testable import Conn

// Native side of the 2026-11-12 voice-trial fixes: page-address evidence for
// direct navigation, a title witness for opening an Obsidian note, and the
// zoom and close-tabs intents lowered from live affordances.

@Suite("Browser URL evidence")
struct BrowserURLEvidenceTests {
    @Test func comparisonKeyIgnoresSchemeHostCaseWWWSlashPortAndFragment() {
        let key = NativeBrowserURL.comparisonKey("https://techmeme.com")
        #expect(key != nil)
        for variant in [
            "http://techmeme.com/",
            "https://WWW.Techmeme.com/",
            "https://www.techmeme.com:443/",
            "https://techmeme.com/#top",
        ] {
            #expect(NativeBrowserURL.comparisonKey(variant) == key, "\(variant)")
        }
        #expect(NativeBrowserURL.comparisonKey("https://techmeme.com/?page=2") != key)
        #expect(NativeBrowserURL.comparisonKey("https://techmeme.com/river") != key)
        #expect(NativeBrowserURL.comparisonKey("https://techmeme.com:8443/") != key)
    }

    @Test func registrableDomainHandlesCountryCodeSecondLevels() {
        #expect(NativeBrowserURL.registrableDomain("news.example.com") == "example.com")
        #expect(NativeBrowserURL.registrableDomain("www.bbc.co.uk") == "bbc.co.uk")
        #expect(NativeBrowserURL.registrableDomain("a.b.example.de") == "example.de")
        #expect(NativeBrowserURL.registrableDomain("127.0.0.1") == "127.0.0.1")
    }

    @Test func exactPageLandsWithoutABaseline() {
        #expect(NativeBrowserURL.navigationLanded(
            expected: "https://techmeme.com/",
            actual: "https://www.techmeme.com/",
            baselineToken: NativeBrowserURL.unboundBaseline
        ))
    }

    @Test func sameDomainRedirectLandsOnlyWhenThePageChanged() {
        let before = NativeBrowserURL.baselineToken("https://example.com/old")
        #expect(NativeBrowserURL.navigationLanded(
            expected: "https://example.com/",
            actual: "https://www.example.com/home",
            baselineToken: before
        ))
        // Still on the page from before the action: nothing landed.
        #expect(!NativeBrowserURL.navigationLanded(
            expected: "https://example.com/",
            actual: "https://example.com/old",
            baselineToken: before
        ))
        // Another app was in front at plan time: a redirect is unprovable.
        #expect(!NativeBrowserURL.navigationLanded(
            expected: "https://example.com/",
            actual: "https://example.com/home",
            baselineToken: NativeBrowserURL.unboundBaseline
        ))
        #expect(!NativeBrowserURL.navigationLanded(
            expected: "https://example.com/",
            actual: "https://example.com/home",
            baselineToken: nil
        ))
    }

    @Test func otherDomainsAndMissingAddressesNeverLand() {
        let none = NativeBrowserURL.baselineToken(nil)
        #expect(!NativeBrowserURL.navigationLanded(
            expected: "https://example.com/", actual: "https://other.example/",
            baselineToken: none))
        #expect(!NativeBrowserURL.navigationLanded(
            expected: "https://example.com/", actual: nil, baselineToken: none))
        #expect(!NativeBrowserURL.navigationLanded(
            expected: "https://example.com/", actual: "about:blank",
            baselineToken: none))
    }

    @Test func webAreaWalkSkipsToolbarsAndEmbeddedFrames() {
        // window ─ toolbar ─ text field (address bar)
        //        └ split ─ tab content ─ group ─ scroll ─ page ─ scroll ─ iframe page
        let tree: [String: (role: String, children: [String])] = [
            "toolbar": ("AXToolbar", ["address"]),
            "address": ("AXTextField", []),
            "split": ("AXSplitGroup", ["content"]),
            "content": ("AXTabGroup", ["group"]),
            "group": ("AXGroup", ["scroll"]),
            "scroll": ("AXScrollArea", ["page"]),
            "page": ("AXWebArea", ["frame-scroll"]),
            "frame-scroll": ("AXScrollArea", ["frame-page"]),
            "frame-page": ("AXWebArea", []),
        ]
        var visited: [String] = []
        let areas = NativeBrowserURL.outermostWebAreas(
            roots: ["toolbar", "split"],
            role: { visited.append($0); return tree[$0]?.role },
            children: { tree[$0]?.children ?? [] }
        )
        #expect(areas == ["page"])
        #expect(!visited.contains("address"))
        #expect(!visited.contains("frame-page"))
    }

    @Test func webAreaWalkIsBoundedAndStopsWhenExpired() {
        let wide = (0..<50).map { "g\($0)" }
        let areas = NativeBrowserURL.outermostWebAreas(
            roots: wide,
            role: { _ in "AXGroup" },
            children: { _ in wide },
            maxVisited: 30
        )
        #expect(areas.isEmpty)
        let expired = NativeBrowserURL.outermostWebAreas(
            roots: ["page"], role: { _ in "AXWebArea" }, children: { _ in [] },
            isExpired: { true }
        )
        #expect(expired.isEmpty)
    }

    @Test func uniqueURLNeedsAgreementAndTreeFallbackDropsNestedFrames() {
        #expect(NativeBrowserURL.uniqueURL([nil, "https://example.com"])
            == "https://example.com/")
        #expect(NativeBrowserURL.uniqueURL(["https://a.example", "https://b.example"]) == nil)
        let nodes = [
            NativeObservationNode(ref: "page", role: "AXWebArea"),
            NativeObservationNode(ref: "box", parentRef: "page", role: "AXGroup"),
            NativeObservationNode(ref: "frame", parentRef: "box", role: "AXWebArea"),
        ]
        #expect(!NativeAXSemanticBackend.hasAncestor(nodes[0], role: "AXWebArea", in: nodes))
        #expect(NativeAXSemanticBackend.hasAncestor(nodes[2], role: "AXWebArea", in: nodes))
    }
}

@Suite("Open note and navigate witnesses")
struct LaunchWitnessTests {
    @Test func obsidianNoteVerifiesFromTheWindowTitleWithVersion() async throws {
        let backend = TrialFixtureBackend()
        backend.titleAfterOpen = "notebook - phoenix - Obsidian 1.15.1"
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(openNoteParams()))
        #expect(plan["effect"] as? String
            == "all(frontmost_bundle_equals:md.obsidian,window_title_has_prefix:notebook - phoenix - Obsidian)")
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "verified")
        #expect(receipt["ok"] as? Bool == true)
    }

    @Test func aDifferentNoteWithTheSamePrefixDoesNotVerify() async throws {
        let backend = TrialFixtureBackend()
        backend.titleAfterOpen = "notebook2 - phoenix - Obsidian 1.15.1"
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(openNoteParams()))
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "no_effect")
    }

    @Test func noteAlreadyInFrontIsNotSentAgain() async throws {
        let backend = TrialFixtureBackend()
        backend.bundleID = "md.obsidian"
        backend.windowTitle = "notebook - phoenix - Obsidian 1.15.1"
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(openNoteParams()))
        #expect(plan["error"] as? String == "effect_already_satisfied")
        #expect(backend.dispatched.isEmpty)
    }

    @Test func openURLWithoutHarnessHintsStaysDispatchOnly() async throws {
        let backend = TrialFixtureBackend()
        backend.titleAfterOpen = "notebook - phoenix - Obsidian 1.15.1"
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(openNoteParams(hints: false)))
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "dispatch_only")
    }

    @Test func navigationVerifiesARedirectWhenTheBrowserWasInFront() async throws {
        let backend = TrialFixtureBackend()
        backend.bundleID = "com.example.browser"
        backend.urlAfterNavigate = "https://www.example.com/home"
        let engine = NativeSemanticActionEngine(
            backend: backend, applicationResolver: browserResolver())
        let plan = try #require(await engine.prepare(navigateParams()))
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "verified")
    }

    @Test func navigationFromAnotherAppVerifiesOnlyTheSamePage() async throws {
        let exact = TrialFixtureBackend()
        exact.urlAfterNavigate = "https://www.example.com/"
        let engine = NativeSemanticActionEngine(
            backend: exact, applicationResolver: browserResolver())
        let plan = try #require(await engine.prepare(navigateParams()))
        #expect(await execute(engine, plan)["outcome"] as? String == "verified")

        let redirected = TrialFixtureBackend()
        redirected.urlAfterNavigate = "https://example.com/home"
        let other = NativeSemanticActionEngine(
            backend: redirected, applicationResolver: browserResolver())
        let otherPlan = try #require(await other.prepare(navigateParams()))
        #expect(await execute(other, otherPlan)["outcome"] as? String == "no_effect")
    }

    private func openNoteParams(hints: Bool = true) -> [String: Any] {
        var payload: [String: Any] = [
            "url": "obsidian://open?vault=phoenix&file=research/notebook.md",
        ]
        if hints {
            payload["witness_bundle_id"] = "md.obsidian"
            payload["witness_window_title_prefix"] = "notebook - phoenix - Obsidian"
        }
        return trialParams(operation: "open_url", payload: payload)
    }

    private func navigateParams() -> [String: Any] {
        trialParams(operation: "navigate", payload: [
            "url": "https://example.com", "browser_scope": "Fixture Browser",
        ])
    }

    private func browserResolver() -> NativeApplicationResolver {
        NativeApplicationResolver(applications: { [
            NativeInstalledApplication(
                name: "Fixture Browser",
                bundleID: "com.example.browser",
                teamID: "FIXTURE001",
                bundleURL: URL(fileURLWithPath: "/Applications/Fixture Browser.app"),
                identityFingerprint: "fixture-browser-identity",
                handlesHTTP: true
            ),
        ] })
    }
}

@Suite("Zoom intent")
struct ZoomIntentTests {
    @Test func zoomOutLowersOntoTheLiveMenuLeafAndRepeatsInOneTransaction() async throws {
        let backend = TrialFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(zoomParams("out", steps: 3)))
        #expect(plan["preview"] as? String == "Zoom out 3 steps")
        #expect(plan["effect_class"] as? String == "reversible_navigation")
        #expect(plan["authorized_strategies"] as? [String]
            == ["ax_menu_action", "live_menu_shortcut"])

        let receipt = await execute(engine, plan)
        // No app exposes a trustworthy zoom level, so the ceiling is honest.
        #expect(receipt["outcome"] as? String == "dispatch_only")
        #expect(receipt["dispatch_state"] as? String == "dispatched")
        #expect(backend.dispatched == Array(repeating: "menu:View>Zoom Out", count: 3))
    }

    @Test func resetUsesActualSizeOnce() async throws {
        let backend = TrialFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(zoomParams("reset", steps: 4)))
        #expect(plan["preview"] as? String == "Reset zoom")
        #expect(plan["effect_class"] as? String == "reversible_navigation")
        _ = await execute(engine, plan)
        #expect(backend.dispatched == ["menu:View>Actual Size"])
    }

    @Test func aDisabledLeafReportsTheLimitWithoutSending() async throws {
        let backend = TrialFixtureBackend()
        backend.zoomOutEnabled = false
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(zoomParams("out", steps: 1)))
        #expect(plan["error"] as? String == "zoom_limit_reached")
        #expect(backend.dispatched.isEmpty)
    }

    @Test func anAppWithoutZoomMenuHasNoAffordance() async throws {
        let backend = TrialFixtureBackend()
        backend.includeZoomMenu = false
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(zoomParams("in", steps: 2)))
        #expect(plan["error"] as? String == "no_live_affordance")
    }

    @Test func stepsOutsideTheBoundAreRefused() async throws {
        let engine = NativeSemanticActionEngine(backend: TrialFixtureBackend())
        let plan = try #require(await engine.prepare(zoomParams("in", steps: 9)))
        #expect(plan["error"] as? String == "unsupported_intent")
    }

    @Test func aStepThatFailsMidRunIsReportedAsPartialNeverRetried() async throws {
        let backend = TrialFixtureBackend()
        backend.failDispatchNumber = 2
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(zoomParams("out", steps: 3)))
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "failed")
        #expect(receipt["reason_code"] as? String == "partial_dispatch")
        #expect(receipt["dispatch_state"] as? String == "dispatched")
        #expect(receipt["retry_safe"] as? Bool == false)
        // The first step went out; the refused second stopped the run.
        #expect(backend.dispatched == ["menu:View>Zoom Out"])
    }

    private func zoomParams(_ direction: String, steps: Int) -> [String: Any] {
        trialParams(operation: "semantic_intent", payload: [
            "family": "zoom", "direction": direction, "steps": steps,
        ])
    }
}

@Suite("Close tabs intent")
struct CloseTabsIntentTests {
    @Test func firstTwoTabsCloseInOneApprovedPlanAndVerify() async throws {
        let backend = TrialFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "first", count: 2)))
        #expect(plan["preview"] as? String == "Close 2 tabs: Alpha, Beta")
        #expect(plan["effect_class"] as? String == "consequential")
        #expect(plan["authorized_strategies"] as? [String] == ["ax_press"])
        #expect(plan["effect"] as? String
            == "all(collection_items_removed:tab-bar:AXRadioButton:alpha\u{1f}beta:2)")

        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "verified")
        #expect(backend.dispatched == ["press:close-1", "press:close-2"])
        #expect(backend.tabs.map(\.title) == ["Gamma", "Delta"])
    }

    @Test func aNamedTabClosesByItsTitle() async throws {
        let backend = TrialFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(name: "gam")))
        #expect(plan["preview"] as? String == "Close tab: Gamma")
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "verified")
        #expect(backend.dispatched == ["press:close-3"])
    }

    @Test func anAmbiguousNameAsksInsteadOfGuessing() async throws {
        let backend = TrialFixtureBackend()
        backend.tabs[1].title = "Alpha"
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(name: "alpha")))
        #expect(plan["outcome"] as? String == "ambiguous")
        #expect((plan["candidates"] as? [[String: Any]])?.count == 2)
    }

    @Test func closingEveryTabIsRefusedBecauseItWouldCloseTheWindow() async throws {
        let backend = TrialFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "last", count: 4)))
        #expect(plan["outcome"] as? String == "blocked")
        #expect(plan["error"] as? String == "would_close_window")
        #expect(backend.dispatched.isEmpty)
    }

    @Test func tooFewTabsIsAPlainFailure() async throws {
        let backend = TrialFixtureBackend()
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "first", count: 5)))
        #expect(plan["error"] as? String == "not_enough_tabs")
    }

    @Test func theCurrentTabFallsBackToTheAppsCloseTabMenu() async throws {
        let backend = TrialFixtureBackend()
        backend.closeButtons = false
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "current")))
        #expect(plan["preview"] as? String == "Close tab: Beta")
        #expect(plan["effect_class"] as? String == "consequential")
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "verified")
        #expect(backend.dispatched == ["menu:File>Close Tab"])
    }

    @Test func aBackgroundTabWithoutACloseButtonIsNotGuessedAt() async throws {
        let backend = TrialFixtureBackend()
        backend.closeButtons = false
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "first", count: 1)))
        #expect(plan["error"] as? String == "no_live_affordance")
    }

    @Test func closingTheWrongTabDoesNotVerify() async throws {
        let backend = TrialFixtureBackend()
        backend.closeWrongTab = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "first", count: 1)))
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "no_effect")
    }

    @Test func aDuplicateTitleMustLoseExactlyTheApprovedCount() async throws {
        let backend = TrialFixtureBackend()
        backend.tabs[2].title = "Alpha"
        // Two tabs do close, one of them the other "Alpha", but not Beta.
        backend.closeWrongTab = true
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "first", count: 2)))
        let receipt = await execute(engine, plan)
        #expect(receipt["outcome"] as? String == "no_effect")
    }

    @Test func secondCloseFailingIsPartialAndNotRetryable() async throws {
        let backend = TrialFixtureBackend()
        backend.failDispatchNumber = 2
        let engine = NativeSemanticActionEngine(backend: backend)
        let plan = try #require(await engine.prepare(closeParams(position: "first", count: 2)))
        let receipt = await execute(engine, plan)
        #expect(receipt["reason_code"] as? String == "partial_dispatch")
        #expect(receipt["retry_safe"] as? Bool == false)
    }

    @Test func closeWordingNoLongerMakesOrdinaryPressesSafe() {
        // Only the close_tabs family is consequential; any other "Close"
        // press keeps the destructive class that navigation refuses.
        let compiler = NativeActionCompiler(applications: NativeApplicationResolver(
            applications: { [] }))
        let baseline = NativeCapturedObservation.fixture(
            turnID: "t", observationEpoch: 1, nodes: [])
        var request = try! #require(NativeActionRequest.parse(trialParams(
            operation: "press", payload: [:])))
        let button = NativeObservationNode(
            ref: "b", role: "AXButton", title: "Close Window",
            supportedActions: ["AXPress"])
        #expect(compiler.effectClass(
            request: request, target: button, baseline: baseline) == .destructive)
        // A raw request naming the family on the wire claims nothing.
        request.payload.intentFamily = "close_tabs"
        #expect(compiler.effectClass(
            request: request, target: button, baseline: baseline) == .destructive)
        request.loweredIntentFamily = "close_tabs"
        #expect(compiler.effectClass(
            request: request, target: button, baseline: baseline) == .consequential)
    }

    private func closeParams(
        position: String? = nil, count: Int? = nil, name: String? = nil
    ) -> [String: Any] {
        var payload: [String: Any] = ["family": "close_tabs"]
        if let position { payload["position"] = position }
        if let count { payload["count"] = count }
        if let name { payload["target_name"] = name }
        return trialParams(operation: "semantic_intent", payload: payload)
    }
}

private func trialParams(operation: String, payload: [String: Any]) -> [String: Any] {
    [
        "turn_id": "turn-1",
        "response_epoch": 1,
        "observation_epoch": 1,
        "request": [
            "operation": operation,
            "payload": payload,
            "risk": "act_low",
            "timeout_ms": 250,
        ] as [String: Any],
    ]
}

private func execute(
    _ engine: NativeSemanticActionEngine, _ plan: [String: Any]
) async -> [String: Any] {
    await engine.execute([
        "plan_fingerprint": plan["plan_fingerprint"] as? String ?? "",
        "turn_id": "turn-1", "response_epoch": 1, "observation_epoch": 1,
    ])
}

/// A browser-and-notes-shaped app: a View menu with zoom leaves, a File menu
/// with Close Tab, one tab strip whose tabs carry their own close buttons,
/// and launch-services effects for opening a note or a page.
final class TrialFixtureBackend: NativeSemanticBackend, @unchecked Sendable {
    struct Tab { var id: Int; var title: String }

    var bundleID = "com.conn.trialfixture"
    var windowTitle = "Fixture"
    var documentURL: String?
    var titleAfterOpen: String?
    var urlAfterNavigate: String?
    var includeZoomMenu = true
    var zoomOutEnabled = true
    var closeButtons = true
    var closeWrongTab = false
    var failDispatchNumber: Int?
    var tabs: [Tab] = [
        Tab(id: 1, title: "Alpha"), Tab(id: 2, title: "Beta"),
        Tab(id: 3, title: "Gamma"), Tab(id: 4, title: "Delta"),
    ]
    var selectedID = 2
    private(set) var dispatched: [String] = []

    func capture(
        turnID: String, observationEpoch: Int, query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        var nodes = [
            NativeObservationNode(ref: "menu-bar", path: [0], role: "AXMenuBar"),
            NativeObservationNode(
                ref: "file-menu", parentRef: "menu-bar", path: [0, 0],
                role: "AXMenuBarItem", title: "File", supportedActions: ["AXPress"]),
            NativeObservationNode(
                ref: "close-tab-menu", parentRef: "file-menu", path: [0, 0, 0],
                role: "AXMenuItem", title: "Close Tab", enabled: true,
                supportedActions: ["AXPress"], menuShortcut: ["cmd", "w"]),
            NativeObservationNode(
                ref: "window", path: [1], role: "AXWindow", title: windowTitle),
            NativeObservationNode(
                ref: "tab-bar", parentRef: "window", path: [1, 0],
                role: "AXOpaqueProviderGroup", identifier: "TabBar"),
        ]
        if includeZoomMenu {
            nodes.append(NativeObservationNode(
                ref: "view-menu", parentRef: "menu-bar", path: [0, 1],
                role: "AXMenuBarItem", title: "View", supportedActions: ["AXPress"]))
            for (index, title) in ["Actual Size", "Zoom In", "Zoom Out"].enumerated() {
                nodes.append(NativeObservationNode(
                    ref: title, parentRef: "view-menu", path: [0, 1, index],
                    role: "AXMenuItem", title: title,
                    enabled: title == "Zoom Out" ? zoomOutEnabled : true,
                    supportedActions: ["AXPress"]))
            }
        }
        for (index, tab) in tabs.enumerated() {
            nodes.append(NativeObservationNode(
                ref: "tab-\(tab.id)", parentRef: "tab-bar", path: [1, 0, index],
                role: "AXRadioButton", title: tab.title,
                selected: tab.id == selectedID, supportedActions: ["AXPress"]))
            if closeButtons {
                nodes.append(NativeObservationNode(
                    ref: "close-\(tab.id)", parentRef: "tab-\(tab.id)",
                    path: [1, 0, index, 0], role: "AXButton",
                    description: "Close Tab", supportedActions: ["AXPress"]))
            }
        }
        var observation = NativeCapturedObservation.fixture(
            turnID: turnID, observationEpoch: observationEpoch,
            nodes: nodes, bundleID: bundleID, windowID: 9)
        observation.windowTitle = windowTitle
        observation.documentURL = documentURL
        return observation
    }

    func applicationIdentityMatches(
        request: NativeActionRequest, observation: NativeCapturedObservation
    ) -> Bool { true }

    func applicationBindingMatches(_ binding: NativeApplicationBinding) -> Bool { true }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        if dispatched.count + 1 == failDispatchNumber {
            return NativeDispatchResult(state: .notDispatched, nativeError: "fixture_refused")
        }
        switch strategy {
        case .launchServices:
            dispatched.append("launch")
            if request.operation == .openURL, let title = titleAfterOpen {
                bundleID = "md.obsidian"
                windowTitle = title
            }
            if request.operation == .navigate, let bundle = request.payload.bundleID {
                bundleID = bundle
                documentURL = urlAfterNavigate
            }
        case .axMenuAction, .liveMenuShortcut:
            dispatched.append("menu:" + request.payload.menuPath.joined(separator: ">"))
            if request.payload.menuPath.last == "Close Tab" {
                removeTab(id: selectedID)
            }
        case .axPress:
            let ref = target?.current.ref ?? "none"
            dispatched.append("press:\(ref)")
            if let id = Int(ref.replacingOccurrences(of: "close-", with: "")) {
                removeTab(id: id)
            }
        default:
            dispatched.append(strategy.rawValue)
        }
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }

    private func removeTab(id: Int) {
        let victim = closeWrongTab ? tabs.last { $0.id != id }?.id ?? id : id
        tabs.removeAll { $0.id == victim }
        if victim == selectedID, let first = tabs.first { selectedID = first.id }
    }
}
