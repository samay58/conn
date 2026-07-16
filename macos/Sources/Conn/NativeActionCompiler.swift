import Foundation

struct NativeCompilationFailure: Error {
    let reason: String
    let outcome: NativeActionOutcome
    let candidates: [NativeApplicationCandidate]
}

struct NativeActionCompiler {
    let applications: NativeApplicationResolver

    private static let destructiveWords: Set<String> = [
        "delete", "remove", "trash", "erase", "overwrite", "replace",
        "close", "quit",
    ]
    private static let consequentialWords: Set<String> = [
        "submit", "send", "publish", "purchase", "buy", "transfer",
        "install", "save", "upload", "download", "pay", "order",
    ]
    private static let reversibleControlWords: Set<String> = [
        "play", "pause", "mute", "unmute", "seek", "back", "forward",
        "next", "previous", "cancel", "tab", "link", "open", "scroll",
        "context", "double", "click",
    ]

    func bindApplication(
        request: NativeActionRequest,
        baseline: NativeCapturedObservation
    ) -> Result<NativeActionRequest, NativeCompilationFailure> {
        var request = request
        let requestedBundleID = request.payload.bundleID
        let resolution: NativeApplicationResolution?
        switch request.operation {
        case .openApp, .switchApp:
            guard let name = request.payload.appName else {
                if request.payload.bundleID != nil { return .success(request) }
                return .failure(failure("app_name_missing"))
            }
            resolution = applications.resolve(
                name: name,
                bundleHint: request.payload.bundleIDHint,
                deniedBundles: request.deniedBundles
            )
        case .navigate:
            guard let normalized = Self.normalizeBrowserURL(request.payload.url) else {
                return .failure(failure("invalid_browser_url"))
            }
            request.payload.url = normalized
            resolution = applications.resolveBrowser(
                scope: request.payload.browserScope,
                currentBundleID: baseline.bundleID,
                bundleHint: request.payload.bundleIDHint,
                deniedBundles: request.deniedBundles
            )
        default:
            if request.payload.bundleID == nil, let name = request.payload.appName {
                resolution = applications.resolve(
                    name: name,
                    bundleHint: request.payload.bundleIDHint,
                    deniedBundles: request.deniedBundles
                )
            } else {
                resolution = nil
            }
        }
        guard let resolution else { return .success(request) }
        switch resolution {
        case .resolved(let binding):
            if let requestedBundleID,
               binding.bundleID != requestedBundleID {
                return .failure(NativeCompilationFailure(
                    reason: "requested_app_mismatch",
                    outcome: .blocked,
                    candidates: []
                ))
            }
            request.payload.bundleID = binding.bundleID
            request.payload.teamID = binding.teamID
            request.applicationBinding = binding
            return .success(request)
        case .ambiguous(let candidates):
            return .failure(NativeCompilationFailure(
                reason: "app_name_ambiguous",
                outcome: .ambiguous,
                candidates: candidates
            ))
        case .failed(let reason):
            let outcome: NativeActionOutcome = reason == "denied_bundle"
                ? .blocked : .failed
            return .failure(NativeCompilationFailure(
                reason: reason,
                outcome: outcome,
                candidates: []
            ))
        }
    }

    func navigationEffect(_ request: NativeActionRequest) -> NativeEffectGroup? {
        guard request.operation == .navigate,
              let bundleID = request.payload.bundleID,
              let url = request.payload.url else { return nil }
        return NativeEffectGroup(mode: "all", predicates: [
            NativeEffectPredicate(
                kind: "frontmost_bundle_equals",
                expected: bundleID
            ),
            NativeEffectPredicate(kind: "document_url_equals", expected: url),
        ])
    }

    func effectClass(
        request: NativeActionRequest,
        target: NativeObservationNode?,
        baseline: NativeCapturedObservation
    ) -> NativeEffectClass {
        if request.operation == .keyChord,
           keyFocusRefusal(baseline) != nil {
            return .secureOrDenied
        }
        if baseline.denied || target?.secure == true { return .secureOrDenied }

        let words = semanticWords(request: request, target: target)
        if !words.isDisjoint(with: Self.destructiveWords) { return .destructive }
        if !words.isDisjoint(with: Self.consequentialWords) { return .consequential }

        switch request.operation {
        case .openApp, .switchApp, .openURL, .navigate, .focusTab, .scroll:
            return .reversibleNavigation
        case .setText:
            return request.payload.submit ? .consequential : .reversibleNavigation
        case .clipboardWrite:
            return .consequential
        case .keyChord:
            return keyChordIsReversible(request.payload.keys)
                ? .reversibleNavigation : .consequential
        case .press:
            let reversibleRoles: Set<String> = [
                "AXLink", "AXRadioButton", "AXCheckBox", "AXTab", "AXTabGroup",
            ]
            if let role = target?.role, reversibleRoles.contains(role) {
                return .reversibleNavigation
            }
            return words.isDisjoint(with: Self.reversibleControlWords)
                ? .unknown : .reversibleNavigation
        case .menu:
            if words.contains("new") && (words.contains("tab") || words.contains("window")) {
                return .reversibleNavigation
            }
            if words.contains("new")
                && (words.contains("note") || words.contains("document") || words.contains("folder")) {
                return .consequential
            }
            let navigationWords: Set<String> = [
                "back", "forward", "next", "previous", "view", "show", "hide",
                "tab", "window", "zoom", "reload", "refresh",
            ]
            return words.isDisjoint(with: navigationWords)
                ? .unknown : .reversibleNavigation
        case .semanticIntent:
            return .unknown
        }
    }

    static func visualEffectClass(goal: String, label: String) -> NativeEffectClass {
        let words = semanticWords("\(goal) \(label)")
        if !words.isDisjoint(with: destructiveWords) { return .destructive }
        if !words.isDisjoint(with: consequentialWords) { return .consequential }
        return words.isDisjoint(with: reversibleControlWords)
            ? .unknown : .reversibleNavigation
    }

    static func visualPointerInput(goal: String, label: String) -> NativePointerInput {
        let words = semanticWords("\(goal) \(label)")
        if words.contains("scroll") { return .scroll }
        if words.contains("double") { return .doubleClick }
        if words.contains("right") || words.contains("context") { return .rightClick }
        return .primaryClick
    }

    private static func semanticWords(_ text: String) -> Set<String> {
        Set(text.lowercased().split {
            !$0.isLetter && !$0.isNumber
        }.map(String.init))
    }

    private func semanticWords(
        request: NativeActionRequest, target: NativeObservationNode?
    ) -> Set<String> {
        let text = [
            target?.title, target?.description, target?.identifier,
            request.payload.goal,
            request.payload.intentKind, request.payload.menuPath.joined(separator: " "),
        ].compactMap { $0 }.joined(separator: " ").lowercased()
        return Set(text.split { !$0.isLetter && !$0.isNumber }.map(String.init))
    }

    private func keyChordIsReversible(_ rawKeys: [String]) -> Bool {
        let keys = rawKeys.map { $0.lowercased() }
        let singleKeys: Set<String> = [
            "space", "escape", "tab", "left", "right", "up", "down",
            "pageup", "pagedown", "home", "end",
        ]
        if keys.count == 1 { return singleKeys.contains(keys[0]) }
        return Set(keys) == Set(["cmd", "l"]) || Set(keys) == Set(["cmd", "t"])
    }

    func keyFocusRefusal(_ observation: NativeCapturedObservation) -> String? {
        let focused: NativeObservationNode?
        if let ref = observation.focusedElementRef {
            focused = observation.nodes.first(where: { $0.ref == ref })
        } else {
            let matches = observation.nodes.filter { $0.focused == true }
            focused = matches.count == 1 ? matches[0] : nil
        }
        guard let focused else { return nil }
        if focused.secure { return "secure_field" }
        let textRoles: Set<String> = [
            "AXTextField", "AXTextArea", "AXComboBox", "AXSearchField",
        ]
        if textRoles.contains(focused.role), !focused.secureStateKnown {
            return "secure_state_unknown"
        }
        return nil
    }

    func isInstalledBrowser(_ bundleID: String?) -> Bool {
        guard let bundleID else { return false }
        if case .resolved = applications.resolveBrowser(
            scope: nil,
            currentBundleID: bundleID,
            bundleHint: bundleID,
            deniedBundles: []
        ) {
            return true
        }
        return false
    }

    static func normalizeBrowserURL(_ value: String?) -> String? {
        guard let raw = value, !raw.isEmpty, raw.count <= 4096,
              raw == raw.trimmingCharacters(in: .whitespacesAndNewlines),
              !raw.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 })
        else { return nil }
        let candidate = raw.contains("://") ? raw : "https://\(raw)"
        guard var components = URLComponents(string: candidate),
              let scheme = components.scheme?.lowercased(),
              ["http", "https"].contains(scheme),
              let host = components.host, !host.isEmpty,
              components.user == nil, components.password == nil else { return nil }
        components.scheme = scheme
        components.host = host.lowercased()
        if components.path.isEmpty { components.path = "/" }
        guard let url = components.url, url.host != nil else { return nil }
        return url.absoluteString
    }

    private func failure(_ reason: String) -> NativeCompilationFailure {
        NativeCompilationFailure(reason: reason, outcome: .failed, candidates: [])
    }
}
