import AppKit

MainActor.assumeIsolated {
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    let delegate = FixtureController()
    app.delegate = delegate
    app.run()
}
