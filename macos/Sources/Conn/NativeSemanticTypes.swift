import Foundation
import CryptoKit

enum NativeActionOperation: String, CaseIterable {
    case openApp = "open"
    case switchApp = "switch"
    case openURL = "open_url"
    case navigate
    case clipboardWrite = "clipboard_write"
    case focusTab = "focus_tab"
    case scroll
    case setText = "set_text"
    case press
    case menu = "invoke_menu"
    case keyChord = "key_chord"
    // Bounded semantic intent: the caller names a goal (create a tab, select
    // the next document); the engine lowers it onto one of the operations
    // above from live affordances before any plan exists.
    case semanticIntent = "semantic_intent"

    init?(wireValue: String) {
        let aliases: [String: Self] = [
            "app_open": .openApp,
            "app_switch": .switchApp,
            "clipboard_set": .clipboardWrite,
            "tab_focus": .focusTab,
            "type_text": .setText,
            "element_press": .press,
            "menu": .menu,
            "app_menu": .menu,
            "hotkey": .keyChord,
            "computer_hotkey": .keyChord,
            "activate": .press,
        ]
        if let alias = aliases[wireValue] {
            self = alias
        } else {
            self.init(rawValue: wireValue)
        }
    }
}

enum NativeActionStrategy: String, Codable {
    case launchServices = "launch_services"
    case pasteboard
    case axPress = "ax_press"
    case axSetValue = "ax_set_value"
    case axSetSelected = "ax_set_selected"
    case axSetSelectedRows = "ax_set_selected_rows"
    case semanticRowKeySelect = "semantic_row_key_select"
    case axScrollToVisible = "ax_scroll_to_visible"
    case axMenuAction = "ax_menu_action"
    case liveMenuShortcut = "live_menu_shortcut"
    case unicodeText = "unicode_text"
    case keyChord = "key_chord"
}

enum NativeDispatchState: String {
    case notDispatched = "not_dispatched"
    case possiblyDispatched = "possibly_dispatched"
    case dispatched
}

enum NativeActionOutcome: String {
    case verified
    case dispatchOnly = "dispatch_only"
    case noEffect = "no_effect"
    case blocked
    case ambiguous
    case failed
}

enum NativeEffectClass: String, Equatable {
    case reversibleNavigation = "reversible_navigation"
    case consequential
    case destructive
    case secureOrDenied = "secure_or_denied"
    case unknown
}

struct NativeRect: Equatable {
    var x: Double
    var y: Double
    var width: Double
    var height: Double

    var dictionary: [String: Any] {
        ["x": x, "y": y, "width": width, "height": height]
    }

    func distance(to other: Self) -> Double {
        abs(x - other.x) + abs(y - other.y)
            + abs(width - other.width) + abs(height - other.height)
    }
}

struct NativeObservationNode: Equatable {
    var ref: String
    var parentRef: String?
    var path: [Int]
    var role: String
    var subrole: String?
    var title: String?
    var description: String?
    var identifier: String?
    var redactedValue: String?
    var valueHash: String?
    var valueType: String?
    var enabled: Bool?
    var focused: Bool?
    var selected: Bool?
    var expanded: Bool?
    var visible: Bool?
    var frame: NativeRect?
    var displayID: UInt32?
    var supportedActions: [String]
    var settableAttributes: [String]
    var siblingSignature: String?
    var menuShortcut: [String]?
    var protectedContent: Bool?

    init(
        ref: String,
        parentRef: String? = nil,
        path: [Int] = [],
        role: String,
        subrole: String? = nil,
        title: String? = nil,
        description: String? = nil,
        identifier: String? = nil,
        redactedValue: String? = nil,
        valueHash: String? = nil,
        valueType: String? = nil,
        enabled: Bool? = nil,
        focused: Bool? = nil,
        selected: Bool? = nil,
        expanded: Bool? = nil,
        visible: Bool? = nil,
        frame: NativeRect? = nil,
        displayID: UInt32? = nil,
        supportedActions: [String] = [],
        settableAttributes: [String] = [],
        siblingSignature: String? = nil,
        menuShortcut: [String]? = nil,
        protectedContent: Bool? = nil
    ) {
        self.ref = ref
        self.parentRef = parentRef
        self.path = path
        self.role = role
        self.subrole = subrole
        self.title = title
        self.description = description
        self.identifier = identifier
        self.redactedValue = redactedValue
        self.valueHash = valueHash ?? redactedValue.map(NativeHash.sha256)
        self.valueType = valueType
        self.enabled = enabled
        self.focused = focused
        self.selected = selected
        self.expanded = expanded
        self.visible = visible
        self.frame = frame
        self.displayID = displayID
        self.supportedActions = supportedActions.sorted()
        self.settableAttributes = settableAttributes.sorted()
        self.siblingSignature = siblingSignature
        self.menuShortcut = menuShortcut
        self.protectedContent = protectedContent
    }

    var secure: Bool {
        role == "AXSecureTextField"
            || subrole == "AXSecureTextField"
            || protectedContent == true
    }

    var secureStateKnown: Bool {
        role == "AXSecureTextField"
            || subrole == "AXSecureTextField"
            || protectedContent != nil
    }

    var semanticFingerprint: String {
        NativeHash.sha256([
            role,
            subrole ?? "",
            title ?? "",
            description ?? "",
            identifier ?? "",
            supportedActions.joined(separator: ","),
        ].joined(separator: "\u{1f}"))
    }

    func attribute(_ name: String) -> String? {
        switch name.lowercased() {
        case "value", "axvalue": return redactedValue
        case "title", "axtitle": return title
        case "enabled", "axenabled": return enabled.map(String.init)
        case "focused", "axfocused": return focused.map(String.init)
        case "selected", "axselected": return selected.map(String.init)
        case "expanded", "axexpanded": return expanded.map(String.init)
        case "visible": return visible.map(String.init)
        default: return nil
        }
    }

    var dictionary: [String: Any] {
        var result: [String: Any] = [
            "ref": ref,
            "path": path,
            "role": role,
            "supported_actions": supportedActions,
            "settable_attributes": settableAttributes,
            "secure": secure,
            "fingerprint": semanticFingerprint,
        ]
        result.put("parent_ref", parentRef)
        result.put("subrole", subrole)
        result.put("title", title)
        result.put("description", description)
        result.put("identifier", identifier)
        result.put("value", valueType == "string" && redactedValue != nil
                   ? "<redacted>" : redactedValue)
        result.put("value_type", valueType)
        result.put("enabled", enabled)
        result.put("focused", focused)
        result.put("selected", selected)
        result.put("expanded", expanded)
        result.put("visible", visible)
        result.put("frame", frame?.dictionary)
        result.put("display_id", displayID.map { Int($0) })
        result.put("sibling_signature", siblingSignature)
        result.put("menu_shortcut", menuShortcut)
        return result
    }
}

enum NativePageStatus {
    static func pageAndTotal(
        _ node: NativeObservationNode
    ) -> (page: Int, total: Int)? {
        guard node.role == "AXStaticText",
              let value = node.redactedValue else { return nil }
        return pageAndTotal(value)
    }

    static func pageAndTotal(_ value: String) -> (page: Int, total: Int)? {
        let parts = value.split(separator: " ")
        guard parts.count == 4,
              parts[0].localizedCaseInsensitiveCompare("page") == .orderedSame,
              parts[2].localizedCaseInsensitiveCompare("of") == .orderedSame,
              let page = Int(parts[1]),
              let total = Int(parts[3]),
              page >= 1, total >= page else { return nil }
        return (page, total)
    }

    static func recognizedValue(_ node: NativeObservationNode) -> String? {
        guard let value = node.redactedValue,
              pageAndTotal(node) != nil else { return nil }
        return value
    }
}

struct NativeCapturedObservation {
    var snapshotID: String
    var observationID: String
    var turnID: String
    var observationEpoch: Int
    var monotonicMs: Int
    var bundleID: String?
    var pid: Int32?
    var processStartIdentity: String?
    var appName: String?
    var windowID: UInt32?
    var windowTitle: String?
    var windowFrame: NativeRect?
    var documentURL: String?
    var focusedWindowRef: String?
    var focusedElementRef: String?
    var nodes: [NativeObservationNode]
    var secure: Bool
    var denied: Bool
    var windowCount: Int
    var clipboardHash: String?
    var notifications: [String]
    var durationMs: Int

    static func fixture(
        turnID: String,
        observationEpoch: Int,
        nodes: [NativeObservationNode],
        bundleID: String = "com.conn.fixture",
        windowID: UInt32 = 1
    ) -> Self {
        Self(
            snapshotID: UUID().uuidString,
            observationID: UUID().uuidString,
            turnID: turnID,
            observationEpoch: observationEpoch,
            monotonicMs: NativeClock.ms(),
            bundleID: bundleID,
            pid: 123,
            processStartIdentity: "fixture-1",
            appName: "Fixture",
            windowID: windowID,
            windowTitle: "Fixture",
            windowFrame: NativeRect(x: 0, y: 0, width: 800, height: 600),
            documentURL: nil,
            focusedWindowRef: nil,
            focusedElementRef: nil,
            nodes: nodes,
            secure: nodes.contains(where: { $0.secure }),
            denied: false,
            windowCount: 1,
            clipboardHash: nil,
            notifications: [],
            durationMs: 0
        )
    }

    var digest: String {
        NativeHash.sha256([
            bundleID ?? "",
            String(pid ?? 0),
            processStartIdentity ?? "",
            String(windowID ?? 0),
            windowTitle ?? "",
            documentURL.flatMap(NativeActionCompiler.normalizeBrowserURL)
                .map(NativeHash.sha256) ?? "",
            nodes.map { "\($0.semanticFingerprint):\($0.valueHash ?? ""):" +
                "\($0.selected.map(String.init) ?? "")" }.joined(separator: "|"),
        ].joined(separator: "\u{1e}"))
    }

    var dictionary: [String: Any] {
        var result: [String: Any] = [
            "snapshot_id": snapshotID,
            "observation_id": observationID,
            "turn_id": turnID,
            "observation_epoch": observationEpoch,
            "monotonic_ms": monotonicMs,
            "nodes": nodes.map(\.dictionary),
            "secure": secure,
            "denied": denied,
            "window_count": windowCount,
            "digest": digest,
            "duration_ms": durationMs,
        ]
        result.put("bundle_id", bundleID)
        result.put("pid", pid.map { Int($0) })
        result.put("process_start_identity", processStartIdentity)
        result.put("app_name", appName)
        result.put("window_id", windowID.map { Int($0) })
        result.put("window_title", windowTitle)
        result.put("window_frame", windowFrame?.dictionary)
        result.put("document_url", documentURL)
        result.put("focused_window_ref", focusedWindowRef)
        result.put("focused_element_ref", focusedElementRef)
        result.put("clipboard_hash", clipboardHash)
        return result
    }
}

enum NativeObservationScope: String, Equatable {
    case currentWindow = "current_window"
    case currentApp = "current_app"
    case descendant
}

struct NativeObservationQuery {
    var bundleID: String?
    var pid: Int32?
    var includeMenu: Bool
    var maxNodes: Int
    var maxDepth: Int
    var deniedBundles: Set<String>
    var searchTerms: [String]
    var expectedRoles: Set<String>
    var expectedActions: Set<String>
    var scope: NativeObservationScope
    var ancestorRef: String?
    var resultLimit: Int
    var deadlineMs: Int?

    init(
        bundleID: String? = nil,
        pid: Int32? = nil,
        includeMenu: Bool = false,
        maxNodes: Int = 300,
        maxDepth: Int = 12,
        deniedBundles: Set<String> = [],
        searchTerms: [String] = [],
        expectedRoles: Set<String> = [],
        expectedActions: Set<String> = [],
        scope: NativeObservationScope = .currentWindow,
        ancestorRef: String? = nil,
        resultLimit: Int = 20,
        deadlineMs: Int? = nil
    ) {
        self.bundleID = bundleID
        self.pid = pid
        self.includeMenu = includeMenu
        self.maxNodes = min(max(maxNodes, 1), 500)
        self.maxDepth = min(max(maxDepth, 1), 20)
        self.deniedBundles = deniedBundles
        self.searchTerms = searchTerms
        self.expectedRoles = expectedRoles
        self.expectedActions = expectedActions
        self.scope = scope
        self.ancestorRef = ancestorRef
        self.resultLimit = min(max(resultLimit, 1), 20)
        self.deadlineMs = deadlineMs
    }

    static func parse(_ value: Any?) -> Self {
        let dictionary = value as? [String: Any] ?? [:]
        let denied = dictionary["denied_bundles"] as? [String] ?? []
        let explicitTerms = dictionary["search_terms"] as? [String]
        let legacyTerms = (dictionary["search"] as? String)?.split {
            $0.isWhitespace
        }.map(String.init) ?? []
        let terms = boundedUnique(explicitTerms ?? legacyTerms, count: 8, length: 128)
        let roles = boundedUnique(
            dictionary["expected_roles"] as? [String] ?? [], count: 16, length: 64
        )
        let actions = boundedUnique(
            dictionary["expected_actions"] as? [String] ?? [], count: 16, length: 64
        )
        let targeted = !terms.isEmpty || !roles.isEmpty || !actions.isEmpty
        return Self(
            bundleID: dictionary["bundle_id"] as? String,
            pid: (dictionary["pid"] as? Int).map(Int32.init),
            includeMenu: dictionary["include_menu"] as? Bool ?? false,
            maxNodes: dictionary["max_nodes"] as? Int ?? (targeted ? 500 : 300),
            maxDepth: dictionary["max_depth"] as? Int ?? (targeted ? 16 : 12),
            deniedBundles: Set(denied),
            searchTerms: terms,
            expectedRoles: Set(roles),
            expectedActions: Set(actions),
            scope: NativeObservationScope(
                rawValue: dictionary["scope"] as? String ?? "current_window"
            ) ?? .currentWindow,
            ancestorRef: nonempty(dictionary["ancestor_ref"] as? String),
            resultLimit: dictionary["result_limit"] as? Int ?? 20
        )
    }

    private static func boundedUnique(
        _ values: [String], count: Int, length: Int
    ) -> [String] {
        var seen: Set<String> = []
        var result: [String] = []
        for raw in values {
            let value = String(raw.trimmingCharacters(in: .whitespacesAndNewlines).prefix(length))
            let key = value.folding(
                options: [.caseInsensitive, .diacriticInsensitive], locale: .current
            )
            guard !value.isEmpty, seen.insert(key).inserted else { continue }
            result.append(value)
            if result.count == count { break }
        }
        return result
    }

    private static func nonempty(_ value: String?) -> String? {
        guard let value = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return nil }
        return String(value.prefix(128))
    }
}

struct NativeActionTarget {
    var snapshotID: String?
    var ref: String?
    var identifier: String?
    var title: String?
    var bundleID: String?
    var descendantKey: String? = nil

    static func parse(_ value: Any?) -> Self {
        let dictionary = value as? [String: Any] ?? [:]
        return Self(
            snapshotID: dictionary["snapshot_id"] as? String,
            ref: dictionary["ref"] as? String,
            identifier: dictionary["identifier"] as? String,
            title: dictionary["title"] as? String,
            bundleID: dictionary["bundle_id"] as? String
        )
    }
}

struct NativeActionPayload {
    var goal: String?
    var text: String?
    var bundleID: String?
    var teamID: String?
    var bundleIDHint: String?
    var appName: String?
    var url: String?
    var browserScope: String?
    var direction: String?
    var amount: Double?
    var keys: [String]
    var menuPath: [String]
    var submit: Bool
    var intentFamily: String?
    var intentKind: String?
    var intentRelation: String?
    var intentName: String?

    static func parse(_ value: Any?) -> Self {
        if let text = value as? String {
            return Self(goal: nil, text: text, bundleID: nil, teamID: nil,
                        bundleIDHint: nil, appName: nil, url: nil,
                        browserScope: nil,
                        direction: nil, amount: nil, keys: [], menuPath: [], submit: false,
                        intentFamily: nil, intentKind: nil, intentRelation: nil,
                        intentName: nil)
        }
        let dictionary = value as? [String: Any] ?? [:]
        return Self(
            goal: dictionary["goal"] as? String,
            text: dictionary["text"] as? String ?? dictionary["value"] as? String,
            bundleID: dictionary["bundle_id"] as? String,
            teamID: dictionary["team_id"] as? String,
            bundleIDHint: dictionary["bundle_id_hint"] as? String,
            appName: dictionary["app_name"] as? String ?? dictionary["name"] as? String,
            url: dictionary["url"] as? String,
            browserScope: dictionary["browser_scope"] as? String,
            direction: dictionary["direction"] as? String,
            amount: (dictionary["amount"] as? NSNumber)?.doubleValue,
            keys: dictionary["keys"] as? [String] ?? [],
            menuPath: dictionary["menu_path"] as? [String]
                ?? dictionary["titles"] as? [String] ?? [],
            submit: dictionary["submit"] as? Bool ?? false,
            intentFamily: dictionary["family"] as? String,
            intentKind: dictionary["kind"] as? String,
            intentRelation: dictionary["relation"] as? String,
            intentName: dictionary["target_name"] as? String
        )
    }

    var hash: String {
        NativeHash.sha256([
            goal ?? "", text ?? "", bundleID ?? "", teamID ?? "", bundleIDHint ?? "",
            appName ?? "", url ?? "", browserScope ?? "",
            direction ?? "", amount.map { String($0) } ?? "",
            keys.joined(separator: ","), menuPath.joined(separator: ">"),
            String(submit),
            intentFamily ?? "", intentKind ?? "", intentRelation ?? "",
            intentName ?? "",
        ].joined(separator: "\u{1f}"))
    }
}

enum NativeAppIdentity {
    static func validBundleID(_ value: String) -> Bool {
        !value.isEmpty && value.count <= 255
            && value.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || $0 == "." || $0 == "-") }
            && value.contains(".")
    }

    static func validTeamID(_ value: String) -> Bool {
        value.count == 10
            && value.allSatisfy { $0.isASCII && ($0.isUppercase || $0.isNumber) }
    }
}

struct NativeEffectPredicate: Equatable {
    var kind: String
    var ref: String?
    var attribute: String?
    var expected: String?
    var expectedDelta: Int?
    var notification: String?
    var baseline: String?

    init(
        kind: String,
        ref: String? = nil,
        attribute: String? = nil,
        expected: String? = nil,
        expectedDelta: Int? = nil,
        notification: String? = nil,
        baseline: String? = nil
    ) {
        self.kind = kind
        self.ref = ref
        self.attribute = attribute
        self.expected = expected
        self.expectedDelta = expectedDelta
        self.notification = notification
        self.baseline = baseline
    }

    static func parse(_ value: Any) -> Self? {
        guard let dictionary = value as? [String: Any],
              let kind = dictionary["kind"] as? String,
              Set([
                "frontmost_bundle_equals", "window_count_delta",
                "window_title_equals", "window_title_changes",
                "element_exists", "element_disappears",
                "element_attribute_equals", "element_attribute_changes",
                "focused_element_equals", "text_contains", "text_hash_equals",
                "clipboard_hash_equals", "document_url_equals", "notification",
                "unique_focused_find_field_appears",
                "unique_page_status_changes",
              ]).contains(kind) else { return nil }
        let expectedValue = dictionary["expected"] ?? dictionary["value"]
        return Self(
            kind: kind,
            ref: dictionary["ref"] as? String,
            attribute: dictionary["attribute"] as? String,
            expected: expectedValue.flatMap(NativeScalar.string),
            expectedDelta: dictionary["delta"] as? Int,
            notification: dictionary["notification"] as? String,
            baseline: nil
        )
    }

    var summary: String {
        [kind, ref, attribute, expected, expectedDelta.map(String.init), notification]
            .compactMap { $0 }.joined(separator: ":")
    }

    var dictionary: [String: Any] {
        var result: [String: Any] = ["kind": kind]
        result.put("ref", ref)
        result.put("attribute", attribute)
        result.put("expected", expected)
        result.put("expected_delta", expectedDelta)
        result.put("notification", notification)
        result.put("baseline", baseline)
        return result
    }
}

struct NativeEffectGroup: Equatable {
    var mode: String
    var predicates: [NativeEffectPredicate]

    static func parse(_ value: Any?) -> Self? {
        guard let dictionary = value as? [String: Any],
              let raw = dictionary["predicates"] as? [Any],
              raw.count <= 3 else { return nil }
        let predicates = raw.compactMap(NativeEffectPredicate.parse)
        guard predicates.count == raw.count else { return nil }
        let mode = dictionary["mode"] as? String ?? "all"
        guard mode == "all" || mode == "any" else { return nil }
        return Self(mode: mode, predicates: predicates)
    }

    var summary: String {
        "\(mode)(\(predicates.map(\.summary).joined(separator: ",")))"
    }
}

struct NativeActionRequest {
    var operation: NativeActionOperation
    var target: NativeActionTarget
    var payload: NativeActionPayload
    var desiredEffect: NativeEffectGroup?
    var risk: String
    var strategyCeiling: String
    var timeoutMs: Int
    var turnID: String
    var responseEpoch: Int
    var observationEpoch: Int
    var deniedBundles: Set<String>
    var applicationBinding: NativeApplicationBinding?
    var navigationGeneration: Int
    var executionConnectionID: String

    static func parse(_ params: [String: Any]) -> Self? {
        let raw = params["request"] as? [String: Any] ?? params
        guard let operationName = raw["operation"] as? String,
              let operation = NativeActionOperation(wireValue: operationName) else { return nil }
        let denied = raw["denied_bundles"] as? [String]
            ?? params["denied_bundles"] as? [String] ?? []
        let desiredEffect = NativeEffectGroup.parse(raw["desired_effect"])
        if let rawEffect = raw["desired_effect"], !(rawEffect is NSNull),
           desiredEffect == nil { return nil }
        let payload = NativeActionPayload.parse(raw["payload"])
        if operation == .setText,
           (payload.text == nil || payload.text!.utf8.count > 16_384) { return nil }
        return Self(
            operation: operation,
            target: NativeActionTarget.parse(raw["target"]),
            payload: payload,
            desiredEffect: desiredEffect,
            risk: raw["risk"] as? String ?? "local_mutation",
            strategyCeiling: raw["strategy_ceiling"] as? String ?? "semantic_only",
            timeoutMs: min(max(raw["timeout_ms"] as? Int ?? 1200, 10), 4000),
            turnID: params["turn_id"] as? String ?? raw["turn_id"] as? String ?? "system",
            responseEpoch: params["response_epoch"] as? Int ?? raw["response_epoch"] as? Int ?? 0,
            observationEpoch: params["observation_epoch"] as? Int
                ?? raw["observation_epoch"] as? Int ?? 0,
            deniedBundles: Set(denied),
            applicationBinding: nil,
            navigationGeneration: params["navigation_generation"] as? Int ?? 0,
            executionConnectionID: params["execution_connection_id"] as? String ?? "test"
        )
    }
}

struct NativeResolvedTarget {
    var original: NativeObservationNode
    var current: NativeObservationNode
    var resolution: String

    var safeDescription: String {
        current.title ?? current.description ?? current.role
    }
}

struct NativeDispatchResult {
    var state: NativeDispatchState
    var nativeError: String?
}

struct NativeDispatchProgress {
    private(set) var didDispatch = false

    mutating func markDispatched() {
        didDispatch = true
    }

    func failure(_ error: String) -> NativeDispatchResult {
        NativeDispatchResult(
            state: didDispatch ? .possiblyDispatched : .notDispatched,
            nativeError: error
        )
    }
}

enum NativeClock {
    static func ms() -> Int {
        Int(DispatchTime.now().uptimeNanoseconds / 1_000_000)
    }
}

enum NativeHash {
    static func sha256(_ text: String) -> String {
        SHA256.hash(data: Data(text.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}

private enum NativeScalar {
    static func string(_ value: Any) -> String? {
        if let value = value as? String { return value }
        if let value = value as? Bool { return String(value) }
        if let value = value as? NSNumber {
            return CFGetTypeID(value) == CFBooleanGetTypeID()
                ? String(value.boolValue) : value.stringValue
        }
        return nil
    }
}

extension Dictionary where Key == String, Value == Any {
    mutating func put(_ key: String, _ value: Any?) {
        if let value { self[key] = value }
    }
}
