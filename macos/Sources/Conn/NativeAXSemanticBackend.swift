import AppKit
import ApplicationServices
import Security

private final class NativeAXNotificationBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String] = []

    func append(_ value: String) {
        lock.lock()
        defer { lock.unlock() }
        if values.count < 32 { values.append(value) }
    }

    func snapshot() -> [String] {
        lock.lock()
        defer { lock.unlock() }
        return values
    }
}

private func nativeSemanticAXObserverCallback(
    _ observer: AXObserver,
    _ element: AXUIElement,
    _ notification: CFString,
    _ refcon: UnsafeMutableRawPointer?
) {
    guard let refcon else { return }
    Unmanaged<NativeAXNotificationBuffer>
        .fromOpaque(refcon).takeUnretainedValue()
        .append(notification as String)
}

final class NativeAXSemanticBackend: NativeSemanticBackend, @unchecked Sendable {
    private let messagingTimeout: Float = 0.25
    private var latestElements: [String: AXUIElement] = [:]
    private var latestApplication: NSRunningApplication?
    private var evidenceObserver: AXObserver?
    private var evidenceBuffer: NativeAXNotificationBuffer?

    static func codeSigningRequirement(bundleID: String, teamID: String?) -> String? {
        guard NativeAppIdentity.validBundleID(bundleID) else { return nil }
        if bundleID.hasPrefix("com.apple.") {
            return "anchor apple and identifier \"\(bundleID)\""
        }
        guard let teamID, NativeAppIdentity.validTeamID(teamID) else { return nil }
        return "anchor apple generic and identifier \"\(bundleID)\" "
            + "and certificate leaf[subject.OU] = \"\(teamID)\""
    }

    func capture(
        turnID: String,
        observationEpoch: Int,
        query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        let started = NativeClock.ms()
        let snapshotID = UUID().uuidString
        latestElements = [:]
        guard AXIsProcessTrusted(), let application = application(for: query) else {
            return emptyObservation(
                snapshotID: snapshotID,
                turnID: turnID,
                observationEpoch: observationEpoch,
                denied: false,
                durationMs: NativeClock.ms() - started
            )
        }
        latestApplication = application
        let bundleID = application.bundleIdentifier
        let denied = bundleID.map(query.deniedBundles.contains) ?? false
        let appElement = AXUIElementCreateApplication(application.processIdentifier)
        AXUIElementSetMessagingTimeout(appElement, messagingTimeout)
        let focusedWindow = elementAttribute(appElement, kAXFocusedWindowAttribute)
        let focusedElement = elementAttribute(appElement, kAXFocusedUIElementAttribute)
        let windows = elementArrayAttribute(appElement, kAXWindowsAttribute)
        let windowTitle = stringAttribute(focusedWindow, kAXTitleAttribute)
        let windowFrame = rect(of: focusedWindow)
        let windowID = stableWindowID(
            pid: application.processIdentifier,
            title: windowTitle,
            frame: windowFrame
        )
        let documentURL = stringAttribute(focusedWindow, kAXDocumentAttribute)
        let clipboardHash = NSPasteboard.general.string(forType: .string).map(NativeHash.sha256)
        guard !denied else {
            return NativeCapturedObservation(
                snapshotID: snapshotID,
                observationID: UUID().uuidString,
                turnID: turnID,
                observationEpoch: observationEpoch,
                monotonicMs: NativeClock.ms(),
                bundleID: bundleID,
                pid: application.processIdentifier,
                processStartIdentity: processIdentity(application),
                appName: application.localizedName,
                windowID: windowID,
                windowTitle: windowTitle,
                windowFrame: windowFrame,
                documentURL: documentURL,
                focusedWindowRef: nil,
                focusedElementRef: nil,
                nodes: [],
                secure: false,
                denied: true,
                windowCount: windows.count,
                clipboardHash: clipboardHash,
                notifications: evidenceBuffer?.snapshot() ?? [],
                durationMs: NativeClock.ms() - started
            )
        }

        var roots: [AXUIElement] = []
        if query.includeMenu,
           let menuBar = elementAttribute(appElement, kAXMenuBarAttribute) {
            roots.append(menuBar)
        }
        if let focusedWindow { roots.append(focusedWindow) }
        if roots.isEmpty { roots.append(appElement) }
        let tree = boundedTree(
            roots: roots,
            snapshotID: snapshotID,
            maxNodes: query.maxNodes,
            maxDepth: query.maxDepth
        )
        let focusedWindowRef = ref(for: focusedWindow, elements: latestElements)
        let focusedElementRef = ref(for: focusedElement, elements: latestElements)
        return NativeCapturedObservation(
            snapshotID: snapshotID,
            observationID: UUID().uuidString,
            turnID: turnID,
            observationEpoch: observationEpoch,
            monotonicMs: NativeClock.ms(),
            bundleID: bundleID,
            pid: application.processIdentifier,
            processStartIdentity: processIdentity(application),
            appName: application.localizedName,
            windowID: windowID,
            windowTitle: windowTitle,
            windowFrame: windowFrame,
            documentURL: documentURL,
            focusedWindowRef: focusedWindowRef,
            focusedElementRef: focusedElementRef,
            nodes: tree,
            secure: tree.contains(where: { $0.secure }),
            denied: false,
            windowCount: windows.count,
            clipboardHash: clipboardHash,
            notifications: evidenceBuffer?.snapshot() ?? [],
            durationMs: NativeClock.ms() - started
        )
    }

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        switch strategy {
        case .launchServices:
            return dispatchLaunch(request)
        case .pasteboard:
            guard let text = request.payload.text else {
                return NativeDispatchResult(state: .notDispatched, nativeError: "missing_text")
            }
            let pasteboard = NSPasteboard.general
            var progress = NativeDispatchProgress()
            pasteboard.clearContents()
            progress.markDispatched()
            guard pasteboard.setString(text, forType: .string) else {
                return progress.failure("pasteboard_write_failed")
            }
            return NativeDispatchResult(state: .dispatched, nativeError: nil)
        case .axPress:
            return performAction(kAXPressAction, target: target)
        case .axSetSelected:
            return setAttribute(kAXSelectedAttribute, value: true, target: target)
        case .axSetValue:
            return setValue(request: request, target: target)
        case .axScrollToVisible:
            return performAction("AXScrollToVisible", target: target)
        case .axMenuAction:
            return dispatchMenu(request.payload.menuPath)
        case .liveMenuShortcut:
            if let keys = target?.current.menuShortcut {
                return postKeyChord(keys)
            }
            return dispatchMenuShortcut(path: request.payload.menuPath)
        case .unicodeText:
            guard let text = request.payload.text else {
                return NativeDispatchResult(state: .notDispatched, nativeError: "missing_text")
            }
            return postUnicode(text, target: target)
        case .keyChord:
            return postKeyChord(request.payload.keys)
        }
    }

    func beginEvidenceObservation(
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) {
        removeEvidenceObserver()
        guard let application = latestApplication else { return }
        let buffer = NativeAXNotificationBuffer()
        var observer: AXObserver?
        guard AXObserverCreate(
            application.processIdentifier,
            nativeSemanticAXObserverCallback,
            &observer
        ) == .success, let observer else { return }
        evidenceObserver = observer
        evidenceBuffer = buffer
        let refcon = Unmanaged.passUnretained(buffer).toOpaque()
        let app = AXUIElementCreateApplication(application.processIdentifier)
        let targetElement = target.flatMap { latestElements[$0.current.ref] }
        let notifications = [
            kAXFocusedWindowChangedNotification,
            kAXFocusedUIElementChangedNotification,
            kAXWindowCreatedNotification,
            kAXTitleChangedNotification,
            kAXValueChangedNotification,
            kAXSelectedChildrenChangedNotification,
            kAXUIElementDestroyedNotification,
            "AXMenuOpened",
            "AXMenuItemSelected",
            "AXMenuClosed",
        ]
        for notification in notifications {
            _ = AXObserverAddNotification(
                observer,
                app,
                notification as CFString,
                refcon
            )
            if let targetElement {
                _ = AXObserverAddNotification(
                    observer,
                    targetElement,
                    notification as CFString,
                    refcon
                )
            }
        }
        CFRunLoopAddSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(observer),
            .commonModes
        )
    }

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool {
        guard let expectedBundleID = request.payload.bundleID else { return true }
        guard observation.bundleID == expectedBundleID,
              let pid = observation.pid,
              let application = NSRunningApplication(processIdentifier: pid),
              let bundleURL = application.bundleURL else { return false }
        return applicationIdentityIsValid(bundleURL, request: request)
    }

    private func boundedTree(
        roots: [AXUIElement],
        snapshotID: String,
        maxNodes: Int,
        maxDepth: Int
    ) -> [NativeObservationNode] {
        struct Pending {
            var element: AXUIElement
            var parentRef: String?
            var path: [Int]
            var depth: Int
            var siblingSignature: String?
        }
        var queue = roots.enumerated().map {
            Pending(element: $0.element, parentRef: nil, path: [$0.offset], depth: 0,
                    siblingSignature: "root:\($0.offset):\(roots.count)")
        }
        var nodes: [NativeObservationNode] = []
        var visited = Set<CFHashCode>()
        while !queue.isEmpty, nodes.count < maxNodes {
            let pending = queue.removeFirst()
            let hash = CFHash(pending.element)
            guard visited.insert(hash).inserted else { continue }
            let ref = "\(snapshotID.prefix(8))-n\(nodes.count)"
            latestElements[ref] = pending.element
            let values = multipleAttributes(pending.element, [
                kAXRoleAttribute, kAXSubroleAttribute, kAXTitleAttribute,
                kAXDescriptionAttribute, kAXIdentifierAttribute, kAXValueAttribute,
                kAXEnabledAttribute, kAXFocusedAttribute, kAXSelectedAttribute,
                kAXExpandedAttribute, kAXPositionAttribute, kAXSizeAttribute,
                kAXChildrenAttribute, kAXMenuItemCmdCharAttribute,
                kAXMenuItemCmdModifiersAttribute,
                NSAccessibility.Attribute.containsProtectedContent.rawValue,
            ])
            let role = values[kAXRoleAttribute] as? String ?? "AXUnknown"
            let subrole = values[kAXSubroleAttribute] as? String
            let secure = role == "AXSecureTextField" || subrole == "AXSecureTextField"
            let rawValue = secure ? nil : stringValue(values[kAXValueAttribute])
            let value = rawValue.map { String($0.prefix(512)) }
            let children: [AXUIElement] = (
                values[kAXChildrenAttribute] as? [AnyObject] ?? []
            ).compactMap { value -> AXUIElement? in
                guard CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
                return unsafeDowncast(value, to: AXUIElement.self)
            }
            let actions = actionNames(pending.element)
            let settable = [kAXFocusedAttribute, kAXSelectedAttribute, kAXValueAttribute]
                .filter { attributeIsSettable(pending.element, $0) }
            let frame = rect(
                position: values[kAXPositionAttribute],
                size: values[kAXSizeAttribute]
            )
            let shortcut = menuShortcut(
                character: values[kAXMenuItemCmdCharAttribute],
                modifiers: values[kAXMenuItemCmdModifiersAttribute]
            )
            nodes.append(NativeObservationNode(
                ref: ref,
                parentRef: pending.parentRef,
                path: pending.path,
                role: role,
                subrole: subrole,
                title: values[kAXTitleAttribute] as? String,
                description: values[kAXDescriptionAttribute] as? String,
                identifier: values[kAXIdentifierAttribute] as? String,
                redactedValue: value,
                valueHash: rawValue.map(NativeHash.sha256),
                valueType: valueType(values[kAXValueAttribute]),
                enabled: boolValue(values[kAXEnabledAttribute]),
                focused: boolValue(values[kAXFocusedAttribute]),
                selected: boolValue(values[kAXSelectedAttribute]),
                expanded: boolValue(values[kAXExpandedAttribute]),
                visible: frame.map(isVisible),
                frame: frame,
                displayID: frame.flatMap(displayID),
                supportedActions: actions,
                settableAttributes: settable,
                siblingSignature: pending.siblingSignature,
                menuShortcut: shortcut,
                protectedContent: boolValue(
                    values[NSAccessibility.Attribute.containsProtectedContent.rawValue]
                )
            ))
            guard pending.depth < maxDepth else { continue }
            let signature = childSignature(children)
            for (index, child) in children.enumerated() {
                queue.append(Pending(
                    element: child,
                    parentRef: ref,
                    path: pending.path + [index],
                    depth: pending.depth + 1,
                    siblingSignature: "\(signature):\(index)"
                ))
            }
        }
        return nodes
    }

    private func dispatchLaunch(_ request: NativeActionRequest) -> NativeDispatchResult {
        if request.operation == .openURL {
            guard let text = request.payload.url, let url = URL(string: text),
                  ["http", "https", "obsidian", "file"].contains(url.scheme?.lowercased() ?? "")
            else { return NativeDispatchResult(state: .notDispatched, nativeError: "invalid_url") }
            return NativeDispatchResult(
                state: NSWorkspace.shared.open(url) ? .dispatched : .notDispatched,
                nativeError: nil
            )
        }
        guard let expectedBundleID = request.payload.bundleID,
              !expectedBundleID.isEmpty else {
            return NativeDispatchResult(
                state: .notDispatched,
                nativeError: "missing_bundle_id"
            )
        }
        let running = NSRunningApplication.runningApplications(
            withBundleIdentifier: expectedBundleID
        ).first
        if let running,
           running.bundleIdentifier == expectedBundleID,
           let bundleURL = running.bundleURL,
           applicationIdentityIsValid(bundleURL, request: request) {
            return NativeDispatchResult(
                state: running.activate(options: [.activateAllWindows])
                    ? .dispatched : .notDispatched,
                nativeError: nil
            )
        }
        guard let appURL = NSWorkspace.shared.urlForApplication(
            withBundleIdentifier: expectedBundleID
        ), Bundle(url: appURL)?.bundleIdentifier == expectedBundleID,
           applicationIdentityIsValid(appURL, request: request) else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "app_not_found")
        }
        let configuration = NSWorkspace.OpenConfiguration()
        configuration.activates = true
        NSWorkspace.shared.openApplication(
            at: appURL,
            configuration: configuration
        ) { _, _ in }
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }

    private func applicationIdentityIsValid(
        _ url: URL,
        request: NativeActionRequest
    ) -> Bool {
        guard let bundleID = request.payload.bundleID,
              let requirementText = Self.codeSigningRequirement(
                bundleID: bundleID,
                teamID: request.payload.teamID
              ) else { return false }
        var staticCode: SecStaticCode?
        guard SecStaticCodeCreateWithPath(
            url as CFURL,
            SecCSFlags(),
            &staticCode
        ) == errSecSuccess, let staticCode else { return false }
        var requirement: SecRequirement?
        guard SecRequirementCreateWithString(
            requirementText as CFString,
            SecCSFlags(),
            &requirement
        ) == errSecSuccess, let requirement else { return false }
        return SecStaticCodeCheckValidity(
            staticCode,
            SecCSFlags(rawValue: kSecCSCheckAllArchitectures),
            requirement
        ) == errSecSuccess
    }

    private func performAction(
        _ action: String,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        guard let target, let element = latestElements[target.current.ref] else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "target_missing")
        }
        return Self.classifyDispatchError(
            AXUIElementPerformAction(element, action as CFString)
        )
    }

    private func setAttribute(
        _ attribute: String,
        value: Any,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        guard let target, let element = latestElements[target.current.ref] else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "target_missing")
        }
        guard attributeIsSettable(element, attribute) else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "attribute_not_settable")
        }
        return Self.classifyDispatchError(
            AXUIElementSetAttributeValue(element, attribute as CFString, value as CFTypeRef)
        )
    }

    private func setValue(
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        if request.operation == .setText, let text = request.payload.text {
            guard let target, let element = latestElements[target.current.ref] else {
                return NativeDispatchResult(state: .notDispatched, nativeError: "target_missing")
            }
            var progress = NativeDispatchProgress()
            guard targetApplicationIsFrontmost() else {
                return progress.failure("target_app_not_frontmost")
            }
            if !targetIsFocused(target) {
                let focus = Self.classifyDispatchError(AXUIElementSetAttributeValue(
                    element,
                    kAXFocusedAttribute as CFString,
                    true as CFTypeRef
                ))
                guard focus.state == .dispatched else { return focus }
                progress.markDispatched()
                guard targetIsFocused(target) else {
                    return progress.failure("focus_not_confirmed")
                }
            }
            let result = setAttribute(kAXValueAttribute, value: text, target: target)
            if result.state == .notDispatched, progress.didDispatch {
                return progress.failure(result.nativeError ?? "value_write_failed")
            }
            return result
        }
        guard request.operation == .scroll,
              let target,
              let element = latestElements[target.current.ref],
              let direction = request.payload.direction,
              ["up", "down", "left", "right"].contains(direction),
              let amount = request.payload.amount,
              amount > 0,
              let number = numberAttribute(element, kAXValueAttribute) else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "scroll_value_unavailable")
        }
        let delta = direction == "up" || direction == "left"
            ? -amount : amount
        return setAttribute(kAXValueAttribute, value: number.doubleValue + delta, target: target)
    }

    private func dispatchMenu(_ path: [String]) -> NativeDispatchResult {
        let resolved = menuLeaf(path: path)
        if let failure = resolved.failure { return failure }
        guard let current = resolved.element else {
            return resolved.progress.failure("menu_unavailable")
        }
        guard boolAttribute(current, kAXEnabledAttribute) != false else {
            return resolved.progress.failure("menu_item_disabled")
        }
        let actions = actionNames(current)
        let action = actions.contains(kAXPressAction) ? kAXPressAction
            : actions.contains(kAXPickAction) ? kAXPickAction : nil
        guard let action else {
            return resolved.progress.failure("menu_action_unsupported")
        }
        let result = Self.classifyDispatchError(
            AXUIElementPerformAction(current, action as CFString)
        )
        if result.state == .notDispatched, resolved.progress.didDispatch {
            return resolved.progress.failure(result.nativeError ?? "menu_action_failed")
        }
        return result
    }

    private func menuLeaf(
        path: [String]
    ) -> (
        element: AXUIElement?,
        progress: NativeDispatchProgress,
        failure: NativeDispatchResult?
    ) {
        var progress = NativeDispatchProgress()
        guard AXIsProcessTrusted(), let application = latestApplication,
              !path.isEmpty else {
            return (nil, progress, progress.failure("menu_unavailable"))
        }
        let app = AXUIElementCreateApplication(application.processIdentifier)
        AXUIElementSetMessagingTimeout(app, messagingTimeout)
        guard let bar = elementAttribute(app, kAXMenuBarAttribute) else {
            return (nil, progress, progress.failure("menu_bar_unavailable"))
        }
        var current = bar
        for (index, title) in path.enumerated() {
            let matches = titledDescendantMatches(current, title: title)
            guard matches.count == 1 else {
                return (
                    nil,
                    progress,
                    progress.failure(
                        matches.isEmpty ? "menu_item_missing" : "menu_item_ambiguous"
                    )
                )
            }
            current = matches[0]
            if index < path.count - 1 {
                let actions = actionNames(current)
                let openAction = actions.contains(kAXShowMenuAction)
                    ? kAXShowMenuAction : kAXPressAction
                let opened = Self.classifyDispatchError(
                    AXUIElementPerformAction(current, openAction as CFString)
                )
                guard opened.state == .dispatched else {
                    return (nil, progress, opened)
                }
                progress.markDispatched()
                RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.05))
            }
        }
        return (current, progress, nil)
    }

    private func dispatchMenuShortcut(path: [String]) -> NativeDispatchResult {
        let resolved = menuLeaf(path: path)
        if let failure = resolved.failure { return failure }
        guard let element = resolved.element,
              let keys = menuShortcut(
            character: attribute(element, kAXMenuItemCmdCharAttribute),
            modifiers: attribute(element, kAXMenuItemCmdModifiersAttribute)
              ) else {
            return resolved.progress.failure("menu_shortcut_unavailable")
        }
        let result = postKeyChord(keys)
        if result.state == .notDispatched, resolved.progress.didDispatch {
            return resolved.progress.failure(result.nativeError ?? "menu_shortcut_failed")
        }
        return result
    }

    private func postKeyChord(_ keys: [String]) -> NativeDispatchResult {
        guard AXIsProcessTrusted(), targetApplicationIsFrontmost(),
              let (code, flags) = NativeKeyChord.parse(keys),
              let down = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: true),
              let up = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: false) else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "invalid_key_chord")
        }
        down.flags = flags
        up.flags = flags
        down.post(tap: .cghidEventTap)
        up.post(tap: .cghidEventTap)
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }

    private func postUnicode(
        _ text: String,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult {
        guard AXIsProcessTrusted(), !text.isEmpty,
              let target, target.current.secure == false,
              let element = latestElements[target.current.ref] else {
            return NativeDispatchResult(state: .notDispatched, nativeError: "unicode_input_blocked")
        }
        var progress = NativeDispatchProgress()
        guard targetApplicationIsFrontmost() else {
            return progress.failure("target_app_not_frontmost")
        }
        if !targetIsFocused(target) {
            let focusResult = Self.classifyDispatchError(AXUIElementSetAttributeValue(
                element,
                kAXFocusedAttribute as CFString,
                true as CFTypeRef
            ))
            guard focusResult.state == .dispatched else { return focusResult }
            progress.markDispatched()
            guard targetIsFocused(target) else {
                return progress.failure("focus_not_confirmed")
            }
        }
        for chunk in text.chunked(maxUTF16: 64) {
            guard targetApplicationIsFrontmost(),
                  targetIsFocused(target),
                  let event = CGEvent(keyboardEventSource: nil, virtualKey: 0, keyDown: true) else {
                return progress.failure("focus_changed")
            }
            let units = Array(chunk.utf16)
            units.withUnsafeBufferPointer {
                event.keyboardSetUnicodeString(stringLength: units.count, unicodeString: $0.baseAddress!)
            }
            event.post(tap: .cghidEventTap)
            progress.markDispatched()
        }
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }

    private func targetApplicationIsFrontmost() -> Bool {
        guard let application = latestApplication,
              let frontmost = NSWorkspace.shared.frontmostApplication else { return false }
        return application.processIdentifier == frontmost.processIdentifier
    }

    private func targetIsFocused(_ target: NativeResolvedTarget?) -> Bool {
        guard let target, let element = latestElements[target.current.ref],
              let application = latestApplication else { return false }
        let app = AXUIElementCreateApplication(application.processIdentifier)
        guard let focused = elementAttribute(app, kAXFocusedUIElementAttribute) else { return false }
        return CFEqual(element, focused)
    }

    static func classifyDispatchError(_ error: AXError) -> NativeDispatchResult {
        switch error {
        case .success:
            return NativeDispatchResult(state: .dispatched, nativeError: nil)
        case .cannotComplete:
            return NativeDispatchResult(state: .possiblyDispatched, nativeError: "kAXErrorCannotComplete")
        case .illegalArgument, .invalidUIElement, .invalidUIElementObserver,
             .attributeUnsupported, .actionUnsupported, .apiDisabled,
             .parameterizedAttributeUnsupported:
            return NativeDispatchResult(
                state: .notDispatched,
                nativeError: "AXError(\(error.rawValue))"
            )
        default:
            return NativeDispatchResult(
                state: .possiblyDispatched,
                nativeError: "AXError(\(error.rawValue))"
            )
        }
    }

    private func application(for query: NativeObservationQuery) -> NSRunningApplication? {
        if let pid = query.pid { return NSRunningApplication(processIdentifier: pid) }
        if let bundleID = query.bundleID {
            return NSRunningApplication.runningApplications(withBundleIdentifier: bundleID).first
        }
        if let app = NSWorkspace.shared.frontmostApplication,
           app.activationPolicy == .regular { return app }
        return NSWorkspace.shared.runningApplications.first {
            $0.isActive && $0.activationPolicy == .regular
        }
    }

    private func processIdentity(_ app: NSRunningApplication) -> String {
        "\(app.processIdentifier):\(app.launchDate?.timeIntervalSince1970 ?? 0)"
    }

    private func emptyObservation(
        snapshotID: String,
        turnID: String,
        observationEpoch: Int,
        denied: Bool,
        durationMs: Int
    ) -> NativeCapturedObservation {
        NativeCapturedObservation(
            snapshotID: snapshotID,
            observationID: UUID().uuidString,
            turnID: turnID,
            observationEpoch: observationEpoch,
            monotonicMs: NativeClock.ms(),
            bundleID: nil,
            pid: nil,
            processStartIdentity: nil,
            appName: nil,
            windowID: nil,
            windowTitle: nil,
            windowFrame: nil,
            documentURL: nil,
            focusedWindowRef: nil,
            focusedElementRef: nil,
            nodes: [],
            secure: false,
            denied: denied,
            windowCount: 0,
            clipboardHash: NSPasteboard.general.string(forType: .string).map(NativeHash.sha256),
            notifications: evidenceBuffer?.snapshot() ?? [],
            durationMs: durationMs
        )
    }

    private func multipleAttributes(
        _ element: AXUIElement,
        _ attributes: [String]
    ) -> [String: Any] {
        var values: CFArray?
        let error = AXUIElementCopyMultipleAttributeValues(
            element,
            attributes as CFArray,
            AXCopyMultipleAttributeOptions(rawValue: 0),
            &values
        )
        guard error == .success, let array = values as? [Any] else { return [:] }
        var result: [String: Any] = [:]
        for (index, attribute) in attributes.enumerated() where index < array.count {
            let value = array[index]
            if !(value is NSNull) {
                result[attribute] = value
            }
        }
        return result
    }

    private func removeEvidenceObserver() {
        guard let observer = evidenceObserver else {
            evidenceBuffer = nil
            return
        }
        CFRunLoopRemoveSource(
            CFRunLoopGetMain(),
            AXObserverGetRunLoopSource(observer),
            .commonModes
        )
        evidenceObserver = nil
        evidenceBuffer = nil
    }

    private func elementAttribute(_ element: AXUIElement?, _ name: String) -> AXUIElement? {
        guard let value = attribute(element, name),
              CFGetTypeID(value) == AXUIElementGetTypeID() else { return nil }
        return unsafeDowncast(value, to: AXUIElement.self)
    }

    private func elementArrayAttribute(_ element: AXUIElement?, _ name: String) -> [AXUIElement] {
        (attribute(element, name) as? [AnyObject] ?? []).compactMap {
            guard CFGetTypeID($0) == AXUIElementGetTypeID() else { return nil }
            return unsafeDowncast($0, to: AXUIElement.self)
        }
    }

    private func stringAttribute(_ element: AXUIElement?, _ name: String) -> String? {
        attribute(element, name) as? String
    }

    private func numberAttribute(_ element: AXUIElement?, _ name: String) -> NSNumber? {
        attribute(element, name) as? NSNumber
    }

    private func boolAttribute(_ element: AXUIElement?, _ name: String) -> Bool? {
        (attribute(element, name) as? NSNumber)?.boolValue
    }

    private func attribute(_ element: AXUIElement?, _ name: String) -> AnyObject? {
        guard let element else { return nil }
        var value: AnyObject?
        guard AXUIElementCopyAttributeValue(element, name as CFString, &value) == .success else {
            return nil
        }
        return value
    }

    private func attributeIsSettable(_ element: AXUIElement, _ name: String) -> Bool {
        var settable = DarwinBoolean(false)
        return AXUIElementIsAttributeSettable(element, name as CFString, &settable) == .success
            && settable.boolValue
    }

    private func actionNames(_ element: AXUIElement) -> [String] {
        var names: CFArray?
        guard AXUIElementCopyActionNames(element, &names) == .success else { return [] }
        return (names as? [String] ?? []).sorted()
    }

    private func stringValue(_ value: Any?) -> String? {
        switch value {
        case let text as String: return text
        case let number as NSNumber: return number.stringValue
        default: return nil
        }
    }

    private func valueType(_ value: Any?) -> String? {
        switch value {
        case is String: return "string"
        case let number as NSNumber:
            return CFGetTypeID(number) == CFBooleanGetTypeID() ? "boolean" : "number"
        case nil: return nil
        default: return "other"
        }
    }

    private func boolValue(_ value: Any?) -> Bool? {
        (value as? NSNumber)?.boolValue
    }

    private func rect(of element: AXUIElement?) -> NativeRect? {
        guard let element else { return nil }
        return rect(
            position: attribute(element, kAXPositionAttribute),
            size: attribute(element, kAXSizeAttribute)
        )
    }

    private func rect(position: Any?, size: Any?) -> NativeRect? {
        guard let position, let size,
              CFGetTypeID(position as CFTypeRef) == AXValueGetTypeID(),
              CFGetTypeID(size as CFTypeRef) == AXValueGetTypeID() else { return nil }
        var point = CGPoint.zero
        var dimensions = CGSize.zero
        guard AXValueGetValue(position as! AXValue, .cgPoint, &point),
              AXValueGetValue(size as! AXValue, .cgSize, &dimensions) else { return nil }
        return NativeRect(
            x: point.x,
            y: point.y,
            width: dimensions.width,
            height: dimensions.height
        )
    }

    private func isVisible(_ rect: NativeRect) -> Bool {
        NSScreen.screens.contains {
            $0.frame.intersects(NSRect(x: rect.x, y: rect.y, width: rect.width, height: rect.height))
        }
    }

    private func displayID(_ rect: NativeRect) -> UInt32? {
        NSScreen.screens.first {
            $0.frame.intersects(NSRect(x: rect.x, y: rect.y, width: rect.width, height: rect.height))
        }?.deviceDescription[NSDeviceDescriptionKey("NSScreenNumber")] as? UInt32
    }

    private func childSignature(_ children: [AXUIElement]) -> String {
        let values = children.prefix(8).map {
            "\(stringAttribute($0, kAXRoleAttribute) ?? ""):\(stringAttribute($0, kAXTitleAttribute) ?? "")"
        }
        return NativeHash.sha256(values.joined(separator: "|"))
    }

    private func menuShortcut(character: Any?, modifiers: Any?) -> [String]? {
        guard let character = character as? String, !character.isEmpty else { return nil }
        let mask = (modifiers as? NSNumber)?.uintValue ?? 0
        var keys: [String] = []
        if mask & 8 == 0 { keys.append("cmd") }
        if mask & 1 != 0 { keys.append("shift") }
        if mask & 2 != 0 { keys.append("alt") }
        if mask & 4 != 0 { keys.append("ctrl") }
        keys.append(character.lowercased())
        return keys
    }

    private func exactTitledDescendants(
        _ element: AXUIElement,
        title: String,
        transparentUntitled: Bool
    ) -> [AXUIElement] {
        var matches: [AXUIElement] = []
        for child in elementArrayAttribute(element, kAXChildrenAttribute) {
            let childTitle = stringAttribute(child, kAXTitleAttribute) ?? ""
            if childTitle.localizedCaseInsensitiveCompare(title) == .orderedSame {
                matches.append(child)
            } else if transparentUntitled && childTitle.isEmpty {
                matches.append(contentsOf: exactTitledDescendants(
                    child,
                    title: title,
                    transparentUntitled: true
                ))
            }
        }
        return matches
    }

    private func titledDescendantMatches(
        _ element: AXUIElement,
        title: String
    ) -> [AXUIElement] {
        let exact = exactTitledDescendants(
            element,
            title: title,
            transparentUntitled: true
        )
        if !exact.isEmpty { return exact }
        let candidates = titledDescendants(element, transparentUntitled: true)
        let desired = normalizedTitle(title)
        let scored = candidates.map { candidate in
            (candidate, titleSimilarity(
                normalizedTitle(stringAttribute(candidate, kAXTitleAttribute) ?? ""),
                desired
            ))
        }.sorted { $0.1 > $1.1 }
        guard let best = scored.first, best.1 >= 0.86 else { return [] }
        if scored.count > 1, best.1 - scored[1].1 < 0.08 {
            return [best.0, scored[1].0]
        }
        return [best.0]
    }

    private func titledDescendants(
        _ element: AXUIElement,
        transparentUntitled: Bool
    ) -> [AXUIElement] {
        var result: [AXUIElement] = []
        for child in elementArrayAttribute(element, kAXChildrenAttribute) {
            let title = stringAttribute(child, kAXTitleAttribute) ?? ""
            if title.isEmpty, transparentUntitled {
                result.append(contentsOf: titledDescendants(
                    child,
                    transparentUntitled: true
                ))
            } else if !title.isEmpty {
                result.append(child)
            }
        }
        return result
    }

    private func normalizedTitle(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }

    private func titleSimilarity(_ lhs: String, _ rhs: String) -> Double {
        guard !lhs.isEmpty || !rhs.isEmpty else { return 1 }
        let left = Array(lhs)
        let right = Array(rhs)
        var previous = Array(0...right.count)
        for (leftIndex, leftCharacter) in left.enumerated() {
            var current = [leftIndex + 1]
            for (rightIndex, rightCharacter) in right.enumerated() {
                current.append(min(
                    current[rightIndex] + 1,
                    previous[rightIndex + 1] + 1,
                    previous[rightIndex] + (leftCharacter == rightCharacter ? 0 : 1)
                ))
            }
            previous = current
        }
        return 1 - Double(previous.last ?? 0) / Double(max(left.count, right.count, 1))
    }

    private func stableWindowID(
        pid: pid_t,
        title: String?,
        frame: NativeRect?
    ) -> UInt32? {
        guard let info = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID)
            as? [[String: Any]] else { return nil }
        let candidates = info.filter { ($0[kCGWindowOwnerPID as String] as? Int32) == pid }
        let exactTitle = candidates.filter { ($0[kCGWindowName as String] as? String) == title }
        let pool = exactTitle.isEmpty ? candidates : exactTitle
        let selected = pool.min { lhs, rhs in
            windowDistance(lhs, frame: frame) < windowDistance(rhs, frame: frame)
        }
        return (selected?[kCGWindowNumber as String] as? NSNumber)?.uint32Value
    }

    private func windowDistance(_ info: [String: Any], frame: NativeRect?) -> Double {
        guard let frame,
              let bounds = info[kCGWindowBounds as String] as? [String: Double] else { return 0 }
        let candidate = NativeRect(
            x: bounds["X"] ?? 0,
            y: bounds["Y"] ?? 0,
            width: bounds["Width"] ?? 0,
            height: bounds["Height"] ?? 0
        )
        return candidate.distance(to: frame)
    }

    private func ref(
        for element: AXUIElement?,
        elements: [String: AXUIElement]
    ) -> String? {
        guard let element else { return nil }
        return elements.first { CFEqual($0.value, element) }.map(\.key)
    }
}

private extension String {
    func chunked(maxUTF16: Int) -> [String] {
        guard utf16.count > maxUTF16 else { return [self] }
        var result: [String] = []
        var current = ""
        var count = 0
        for character in self {
            let size = String(character).utf16.count
            if count + size > maxUTF16, !current.isEmpty {
                result.append(current)
                current = ""
                count = 0
            }
            current.append(character)
            count += size
        }
        if !current.isEmpty { result.append(current) }
        return result
    }
}
