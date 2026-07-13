import AppKit
import Foundation

final class FixtureTruthLog {
    private let url: URL
    private let lock = NSLock()

    init(environment: [String: String] = ProcessInfo.processInfo.environment) {
        let path = environment["CONN_FIXTURE_TRUTH_LOG"]
            ?? "/tmp/ConnActionFixture.truth.jsonl"
        url = URL(fileURLWithPath: path)
        try? FileManager.default.removeItem(at: url)
        FileManager.default.createFile(atPath: url.path, contents: nil)
    }

    func record(_ effect: String, value: String? = nil) {
        var payload: [String: Any] = [
            "effect": effect,
            "monotonic_ns": DispatchTime.now().uptimeNanoseconds,
        ]
        if let value { payload["value"] = value }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let handle = try? FileHandle(forWritingTo: url) else { return }
        lock.lock()
        defer { lock.unlock() }
        handle.seekToEndOfFile()
        handle.write(data)
        handle.write(Data([0x0A]))
        try? handle.close()
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

final class InaccessibleCanvas: NSView {
    override func draw(_ dirtyRect: NSRect) {
        NSColor.systemPurple.setFill()
        bounds.insetBy(dx: 8, dy: 8).fill()
    }

    override func isAccessibilityElement() -> Bool { false }
    override func accessibilityChildren() -> [Any]? { [] }
}

@MainActor
final class FixtureController: NSObject, NSApplicationDelegate, NSMenuDelegate, NSTextFieldDelegate {
    let truth: FixtureTruthLog
    private var mainWindow: NSWindow?
    private var statusLabel = NSTextField(labelWithString: "baseline")
    private var toggle = NSButton(checkboxWithTitle: "Feature enabled", target: nil, action: nil)
    private var tabs = NSTabView()
    private var scrollView = NSScrollView()
    private var reorderContainer = NSStackView()
    private var animationView = NSView()
    private var animationTimer: Timer?
    private var childWindows: [NSWindow] = []

    init(truth: FixtureTruthLog = FixtureTruthLog()) {
        self.truth = truth
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        installMenu()
        showMainWindow()
        truth.record("fixture_ready")
        NSApp.activate(ignoringOtherApps: true)
    }

    func showMainWindow() {
        let window = makeWindow(title: "Conn Action Fixture")
        window.contentView = buildContent()
        window.makeKeyAndOrderFront(nil)
        mainWindow = window
        startBackgroundAnimation()
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

    private func buildContent() -> NSView {
        let root = NSStackView()
        root.orientation = .vertical
        root.alignment = .leading
        root.spacing = 10
        root.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)

        statusLabel.setAccessibilityIdentifier("fixture.status")
        root.addArrangedSubview(statusLabel)
        root.addArrangedSubview(button("Immediate change", #selector(immediateChange), id: "fixture.immediate"))
        root.addArrangedSubview(button("Delayed change", #selector(delayedChange), id: "fixture.delayed"))

        let noEffect = NoEffectButton(title: "Reports success, no effect", target: self, action: #selector(noEffect))
        noEffect.bezelStyle = .rounded
        noEffect.setAccessibilityIdentifier("fixture.no_effect")
        root.addArrangedSubview(noEffect)

        toggle.target = self
        toggle.action = #selector(toggleChanged)
        toggle.setAccessibilityIdentifier("fixture.toggle")
        root.addArrangedSubview(toggle)

        tabs.addTabViewItem(NSTabViewItem(identifier: "first"))
        tabs.tabViewItems[0].label = "First tab"
        tabs.tabViewItems[0].view = NSTextField(labelWithString: "First tab content")
        tabs.addTabViewItem(NSTabViewItem(identifier: "second"))
        tabs.tabViewItems[1].label = "Second tab"
        tabs.tabViewItems[1].view = NSTextField(labelWithString: "Second tab content")
        tabs.frame.size = NSSize(width: 340, height: 90)
        root.addArrangedSubview(tabs)

        let field = NSTextField(string: "")
        field.placeholderString = "Plain text field"
        field.delegate = self
        field.setAccessibilityIdentifier("fixture.text")
        root.addArrangedSubview(field)

        let secure = NSSecureTextField(string: "")
        secure.placeholderString = "Secure field"
        secure.setAccessibilityIdentifier("fixture.secure")
        root.addArrangedSubview(secure)

        scrollView.hasVerticalScroller = true
        scrollView.frame.size = NSSize(width: 340, height: 90)
        let scrollContent = NSStackView()
        scrollContent.orientation = .vertical
        for index in 1...20 {
            scrollContent.addArrangedSubview(NSTextField(labelWithString: "Scroll row \(index)"))
        }
        scrollView.documentView = scrollContent
        root.addArrangedSubview(scrollView)

        reorderContainer.orientation = .horizontal
        reorderContainer.addArrangedSubview(button("Duplicate", #selector(duplicatePressed), id: "fixture.duplicate.1"))
        reorderContainer.addArrangedSubview(button("Duplicate", #selector(duplicatePressed), id: "fixture.duplicate.2"))
        reorderContainer.addArrangedSubview(button("Reorder siblings", #selector(reorderSiblings), id: "fixture.reorder"))
        root.addArrangedSubview(reorderContainer)

        root.addArrangedSubview(button("Create window", #selector(createWindow), id: "fixture.window.create"))
        root.addArrangedSubview(button("Close created window", #selector(closeWindow), id: "fixture.window.close"))
        root.addArrangedSubview(button("Create sheet", #selector(createSheet), id: "fixture.sheet.create"))
        root.addArrangedSubview(button("Change title", #selector(changeTitle), id: "fixture.title.change"))

        let canvas = InaccessibleCanvas(frame: NSRect(x: 0, y: 0, width: 180, height: 44))
        root.addArrangedSubview(canvas)

        animationView.wantsLayer = true
        animationView.layer?.backgroundColor = NSColor.systemBlue.cgColor
        animationView.frame.size = NSSize(width: 16, height: 16)
        root.addArrangedSubview(animationView)
        return root
    }

    private func button(_ title: String, _ action: Selector, id: String) -> NSButton {
        let button = NSButton(title: title, target: self, action: action)
        button.bezelStyle = .rounded
        button.setAccessibilityIdentifier(id)
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
        let item = NSMenuItem(title: "Lazy New Window", action: #selector(createWindow), keyEquivalent: "n")
        item.target = self
        menu.addItem(item)
    }

    @objc private func immediateChange() {
        statusLabel.stringValue = "immediate changed"
        truth.record("status_changed", value: statusLabel.stringValue)
    }

    @objc private func delayedChange() {
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) { [weak self] in
            guard let self else { return }
            statusLabel.stringValue = "delayed changed"
            truth.record("status_changed", value: statusLabel.stringValue)
        }
    }

    @objc private func noEffect() {}

    @objc private func toggleChanged() {
        truth.record("toggle_changed", value: toggle.state == .on ? "on" : "off")
    }

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

    @objc private func closeWindow() {
        guard let window = childWindows.popLast() else { return }
        window.close()
        truth.record("window_closed", value: window.title)
    }

    @objc private func createSheet() {
        guard let mainWindow else { return }
        let sheet = makeWindow(title: "Fixture sheet")
        sheet.contentView = NSTextField(labelWithString: "Created sheet")
        mainWindow.beginSheet(sheet)
        truth.record("sheet_created")
    }

    @objc private func changeTitle() {
        mainWindow?.title = "Conn Action Fixture Changed"
        truth.record("title_changed", value: mainWindow?.title)
    }

    func controlTextDidChange(_ obj: Notification) {
        guard let field = obj.object as? NSTextField else { return }
        truth.record("text_changed", value: field.stringValue)
    }

    private func startBackgroundAnimation() {
        animationTimer = Timer.scheduledTimer(
            timeInterval: 0.2,
            target: self,
            selector: #selector(backgroundTick),
            userInfo: nil,
            repeats: true
        )
    }

    @objc private func backgroundTick() {
        guard let layer = animationView.layer else { return }
        layer.backgroundColor = layer.backgroundColor == NSColor.systemBlue.cgColor
            ? NSColor.systemGreen.cgColor : NSColor.systemBlue.cgColor
    }
}
