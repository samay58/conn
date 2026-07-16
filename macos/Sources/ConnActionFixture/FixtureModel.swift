import AppKit
import CryptoKit
import Foundation

enum FixtureScene: String, CaseIterable {
    case uniqueControl = "unique_control"
    case stableDuplicate = "stable_duplicate"
    case genuineAmbiguity = "genuine_ambiguity"
    case secureField = "secure_field"
    case lazyMenu = "lazy_menu"
    case menuRecapture = "menu_recapture"
    case nestedTabs = "nested_tabs"
    case notesCollections = "notes_collections"
    case delayedVerification = "delayed_verification"
    case noEffect = "no_effect"
    case opaqueMedia = "opaque_media"
    case staleWindowFrame = "stale_window_frame"
    case reorderedSiblings = "reordered_siblings"
    case changedWindowApp = "changed_window_app"
    case uncertainDispatch = "uncertain_dispatch"

    static func select(
        arguments: [String] = CommandLine.arguments,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> FixtureScene? {
        if let index = arguments.firstIndex(of: "--scene") {
            guard arguments.indices.contains(index + 1) else { return nil }
            return FixtureScene(rawValue: arguments[index + 1])
        }
        if let name = environment["CONN_FIXTURE_SCENE"] {
            return FixtureScene(rawValue: name)
        }
        return .noEffect
    }

    var initialState: [String: Any] {
        let state: [String: Any]
        switch self {
        case .uniqueControl:
            state = [
                "control": "fixture.unique",
                "label": "Continue",
                "role": "AXCheckBox",
                "value": false,
            ]
        case .stableDuplicate:
            state = [
                "label": "Duplicate",
                "identifiers": ["fixture.stable.1", "fixture.stable.2"],
            ]
        case .genuineAmbiguity:
            state = ["label": "Duplicate", "count": 2, "identifiers": []]
        case .secureField:
            state = ["field": "fixture.secure", "secure": true]
        case .lazyMenu:
            state = ["menu": "Actions", "item": "Lazy New Window", "lazy": true]
        case .menuRecapture:
            state = [
                "menu": "Actions",
                "item": "New Window",
                "identifier": "fixture.menu.new_window",
            ]
        case .nestedTabs:
            state = [
                "collection": "fixture.tab.collection",
                "item_role": "AXRadioButton",
                "descendant_count": 2,
                "direct_item_count": 0,
            ]
        case .notesCollections:
            state = [
                "collections": [
                    ["identifier": "fixture.notes.primary", "rows": 2],
                    ["identifier": "fixture.notes.secondary", "rows": 1],
                ],
                "item_role": "AXRow",
            ]
        case .delayedVerification:
            state = ["control": "fixture.delayed", "delay_ms": 250]
        case .noEffect:
            state = ["control": "fixture.no_effect", "effect": "none"]
        case .opaqueMedia:
            state = ["surface": "fixture.opaque_media", "playback": "play"]
        case .staleWindowFrame:
            state = ["control": "fixture.window.move", "window_origin": [100, 100]]
        case .reorderedSiblings:
            state = [
                "container": "fixture.reorder.container",
                "order": ["fixture.duplicate.1", "fixture.duplicate.2"],
            ]
        case .changedWindowApp:
            state = ["control": "fixture.window.change", "window": "main"]
        case .uncertainDispatch:
            state = ["control": "fixture.uncertain", "exit_after_first_input": true]
        }
        return [
            "schema_version": 1,
            "scene": rawValue,
            "state": state,
        ]
    }

    var initialStateData: Data {
        try! JSONSerialization.data(
            withJSONObject: initialState,
            options: [.sortedKeys, .withoutEscapingSlashes]
        )
    }

    var initialStateDigest: String {
        SHA256.hash(data: initialStateData).map {
            String(format: "%02x", $0)
        }.joined()
    }
}

final class FixtureTruthLog {
    private let url: URL
    private let lock = NSLock()

    init(environment: [String: String] = ProcessInfo.processInfo.environment) {
        let path = environment["CONN_FIXTURE_TRUTH_LOG"]
            ?? "/tmp/ConnActionFixture.truth.jsonl"
        url = URL(fileURLWithPath: path)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
    }

    func record(
        _ effect: String,
        value: String? = nil,
        fields: [String: Any] = [:]
    ) {
        var payload: [String: Any] = [
            "effect": effect,
            "monotonic_ns": DispatchTime.now().uptimeNanoseconds,
        ]
        if let value { payload["value"] = value }
        for (key, fieldValue) in fields
        where !["effect", "monotonic_ns", "value"].contains(key) {
            payload[key] = fieldValue
        }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let handle = try? FileHandle(forWritingTo: url) else { return }
        lock.lock()
        defer { lock.unlock() }
        handle.seekToEndOfFile()
        handle.write(data)
        handle.write(Data([0x0A]))
        try? handle.close()
    }

    func recordSceneReady(_ scene: FixtureScene) {
        record("scene_ready", fields: [
            "scene": scene.rawValue,
            "initial_state_digest": scene.initialStateDigest,
        ])
    }

    func entries() -> [[String: Any]] {
        lock.lock()
        defer { lock.unlock() }
        guard let data = try? Data(contentsOf: url),
              let text = String(data: data, encoding: .utf8) else { return [] }
        return text.split(separator: "\n").compactMap { line in
            guard let data = line.data(using: .utf8) else { return nil }
            return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        }
    }
}

final class NoEffectButton: NSButton {
    override func accessibilityPerformPress() -> Bool {
        true
    }
}

final class OpaquePlaybackTarget: NSView {
    private let truth: FixtureTruthLog
    private(set) var state = "play"

    init(
        truth: FixtureTruthLog,
        frame: NSRect = NSRect(x: 0, y: 0, width: 240, height: 64)
    ) {
        self.truth = truth
        super.init(frame: frame)
        wantsLayer = true
        setAccessibilityIdentifier("fixture.opaque_media")
    }

    required init?(coder: NSCoder) {
        nil
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor(calibratedWhite: 0.12, alpha: 1).setFill()
        NSBezierPath(roundedRect: bounds, xRadius: 8, yRadius: 8).fill()
        let label = state == "play" ? "Play" : "Pause"
        let attributes: [NSAttributedString.Key: Any] = [
            .foregroundColor: NSColor.white,
            .font: NSFont.systemFont(ofSize: 18, weight: .semibold),
        ]
        let size = label.size(withAttributes: attributes)
        label.draw(
            at: NSPoint(
                x: (bounds.width - size.width) / 2,
                y: (bounds.height - size.height) / 2
            ),
            withAttributes: attributes
        )
    }

    override func mouseDown(with event: NSEvent) {
        activate()
    }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool {
        true
    }

    func activate() {
        state = state == "play" ? "pause" : "play"
        needsDisplay = true
        truth.record("playback_changed", value: state)
    }

    override func isAccessibilityElement() -> Bool { false }
    override func accessibilityChildren() -> [Any]? { [] }
}

@MainActor
final class FixtureController: NSObject, NSApplicationDelegate, NSMenuDelegate {
    private(set) var scene: FixtureScene
    let truth: FixtureTruthLog
    private var mainWindow: NSWindow?
    private var statusLabel = NSTextField(labelWithString: "baseline")
    private var reorderContainer = NSStackView()
    private var childWindows: [NSWindow] = []

    init(
        scene: FixtureScene = FixtureScene.select() ?? .noEffect,
        truth: FixtureTruthLog = FixtureTruthLog()
    ) {
        self.scene = scene
        self.truth = truth
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        installMenu()
        showMainWindow()
        truth.record("fixture_ready")
        truth.recordSceneReady(scene)
        NSApp.activate(ignoringOtherApps: true)
    }

    func showMainWindow() {
        let window = makeWindow(title: "Conn Action Fixture: \(scene.rawValue)")
        window.contentView = buildContent()
        window.makeKeyAndOrderFront(nil)
        mainWindow = window
    }

    func reset(to nextScene: FixtureScene) {
        childWindows.forEach { $0.close() }
        childWindows.removeAll(keepingCapacity: true)
        scene = nextScene
        statusLabel = NSTextField(labelWithString: "baseline")
        reorderContainer = NSStackView()
        if let mainWindow {
            installMenu()
            mainWindow.title = "Conn Action Fixture: \(scene.rawValue)"
            mainWindow.contentView = buildContent()
            mainWindow.makeKeyAndOrderFront(nil)
        }
        truth.record("scene_reset", fields: [
            "scene": scene.rawValue,
            "initial_state_digest": scene.initialStateDigest,
        ])
    }

    private func makeWindow(title: String) -> NSWindow {
        let window = NSWindow(
            contentRect: NSRect(x: 100, y: 100, width: 760, height: 680),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = title
        return window
    }

    func buildContent() -> NSView {
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 10
        root.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)

        switch scene {
        case .uniqueControl:
            let control = NSButton(
                checkboxWithTitle: "Continue",
                target: self,
                action: #selector(uniqueChanged)
            )
            control.setAccessibilityIdentifier("fixture.unique")
            root.addArrangedSubview(control)
        case .stableDuplicate:
            root.addArrangedSubview(button(
                "Duplicate", #selector(duplicatePressed), id: "fixture.stable.1"
            ))
            root.addArrangedSubview(button(
                "Duplicate", #selector(duplicatePressed), id: "fixture.stable.2"
            ))
        case .genuineAmbiguity:
            root.addArrangedSubview(button(
                "Duplicate", #selector(duplicatePressed), id: nil
            ))
            root.addArrangedSubview(button(
                "Duplicate", #selector(duplicatePressed), id: nil
            ))
        case .secureField:
            let secure = NSSecureTextField(string: "")
            secure.placeholderString = "Secure field"
            secure.setAccessibilityIdentifier("fixture.secure")
            root.addArrangedSubview(secure)
        case .lazyMenu, .menuRecapture:
            root.addArrangedSubview(NSTextField(
                labelWithString: "Use the Actions menu"
            ))
        case .nestedTabs:
            root.addArrangedSubview(nestedTabCollection())
        case .notesCollections:
            root.addArrangedSubview(notesCollection(
                identifier: "fixture.notes.primary", rows: 2
            ))
            root.addArrangedSubview(notesCollection(
                identifier: "fixture.notes.secondary", rows: 1
            ))
        case .delayedVerification:
            addStatus(to: root)
            root.addArrangedSubview(button(
                "Delayed change", #selector(delayedChange), id: "fixture.delayed"
            ))
        case .noEffect:
            addStatus(to: root)
            let noEffect = NoEffectButton(
                title: "Reports success, no effect",
                target: self,
                action: #selector(noEffect)
            )
            noEffect.bezelStyle = .rounded
            noEffect.setAccessibilityIdentifier("fixture.no_effect")
            root.addArrangedSubview(noEffect)
        case .opaqueMedia:
            root.addArrangedSubview(OpaquePlaybackTarget(truth: truth))
        case .staleWindowFrame:
            root.addArrangedSubview(button(
                "Move window", #selector(moveWindow), id: "fixture.window.move"
            ))
        case .reorderedSiblings:
            reorderContainer.orientation = .horizontal
            reorderContainer.setAccessibilityIdentifier("fixture.reorder.container")
            reorderContainer.addArrangedSubview(button(
                "Duplicate", #selector(duplicatePressed), id: "fixture.duplicate.1"
            ))
            reorderContainer.addArrangedSubview(button(
                "Duplicate", #selector(duplicatePressed), id: "fixture.duplicate.2"
            ))
            reorderContainer.addArrangedSubview(button(
                "Reorder siblings", #selector(reorderSiblings), id: "fixture.reorder"
            ))
            root.addArrangedSubview(reorderContainer)
        case .changedWindowApp:
            root.addArrangedSubview(button(
                "Change window", #selector(changeWindow), id: "fixture.window.change"
            ))
        case .uncertainDispatch:
            root.addArrangedSubview(button(
                "Dispatch then exit", #selector(uncertainInput), id: "fixture.uncertain"
            ))
        }
        return root
    }

    private func addStatus(to root: NSStackView) {
        statusLabel.setAccessibilityIdentifier("fixture.status")
        root.addArrangedSubview(statusLabel)
    }

    private func nestedTabCollection() -> NSView {
        let collection = NSStackView()
        collection.orientation = .vertical
        collection.setAccessibilityIdentifier("fixture.tab.collection")
        let nested = NSStackView()
        nested.orientation = .horizontal
        for index in 1...2 {
            let tab = NSButton(
                radioButtonWithTitle: "Tab \(index)", target: nil, action: nil
            )
            tab.setAccessibilityIdentifier("fixture.tab.\(index)")
            nested.addArrangedSubview(tab)
        }
        collection.addArrangedSubview(nested)
        return collection
    }

    private func notesCollection(identifier: String, rows: Int) -> NSView {
        let list = NSStackView()
        list.orientation = .vertical
        list.setAccessibilityIdentifier(identifier)
        list.setAccessibilityRole(.list)
        for index in 1...rows {
            let row = NSTextField(labelWithString: "Note \(index)")
            row.setAccessibilityIdentifier("\(identifier).row.\(index)")
            row.setAccessibilityRole(.row)
            list.addArrangedSubview(row)
        }
        return list
    }

    private func button(
        _ title: String, _ action: Selector, id: String?
    ) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        if let id { button.setAccessibilityIdentifier(id) }
        return button
    }

    private func installMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        main.addItem(appItem)
        let appMenu = NSMenu(title: "ConnActionFixture")
        appMenu.addItem(withTitle: "Quit", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        appItem.submenu = appMenu

        let actionsItem = NSMenuItem()
        actionsItem.title = "Actions"
        main.addItem(actionsItem)
        let actionsMenu = NSMenu(title: "Actions")
        actionsMenu.delegate = self
        actionsItem.submenu = actionsMenu
        NSApp.mainMenu = main
    }

    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        let title: String
        switch scene {
        case .lazyMenu:
            title = "Lazy New Window"
        case .menuRecapture:
            title = "New Window"
        default:
            return
        }
        let item = NSMenuItem(
            title: title,
            action: #selector(createWindow),
            keyEquivalent: "n"
        )
        item.target = self
        if scene == .menuRecapture {
            item.setAccessibilityIdentifier("fixture.menu.new_window")
        }
        menu.addItem(item)
    }

    @objc private func immediateChange() {
        statusLabel.stringValue = "immediate changed"
        truth.record("status_changed", value: statusLabel.stringValue)
    }

    @objc private func uniqueChanged(_ sender: NSButton) {
        truth.record(
            "control_changed",
            value: sender.state == .on ? "on" : "off"
        )
    }

    @objc private func delayedChange() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            guard let self else { return }
            statusLabel.stringValue = "delayed changed"
            truth.record("status_changed", value: statusLabel.stringValue)
        }
    }

    @objc private func noEffect() {}

    @objc private func duplicatePressed() {
        truth.record("duplicate_pressed")
    }

    @objc private func reorderSiblings() {
        let views = reorderContainer.arrangedSubviews
        guard views.count >= 2 else { return }
        reorderContainer.removeArrangedSubview(views[0])
        views[0].removeFromSuperview()
        reorderContainer.insertArrangedSubview(views[0], at: 1)
        truth.record("siblings_reordered")
    }

    @objc private func createWindow() {
        let window = makeWindow(title: "Fixture child \(NSApp.windows.count)")
        window.contentView = NSTextField(labelWithString: "Created window")
        window.makeKeyAndOrderFront(nil)
        childWindows.append(window)
        truth.record("window_created", value: window.title)
    }

    @objc private func moveWindow() {
        guard let mainWindow else { return }
        let origin = mainWindow.frame.origin
        mainWindow.setFrameOrigin(NSPoint(x: origin.x + 40, y: origin.y + 20))
        truth.record("window_moved", fields: [
            "x": mainWindow.frame.origin.x,
            "y": mainWindow.frame.origin.y,
        ])
    }

    @objc private func changeWindow() {
        let window = makeWindow(title: "Fixture changed window")
        window.contentView = NSTextField(labelWithString: "Changed window")
        window.makeKeyAndOrderFront(nil)
        mainWindow?.orderOut(nil)
        childWindows.append(window)
        truth.record("window_changed", value: window.title)
    }

    @objc private func uncertainInput() {
        truth.record("first_input_received")
        DispatchQueue.main.async {
            NSApp.terminate(nil)
        }
    }
}
