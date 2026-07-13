import AppKit

MainActor.assumeIsolated {
    if CommandLine.arguments.contains("--preview") {
        PreviewRunner.run()
    } else if let index = CommandLine.arguments.firstIndex(of: "--action-probe"),
              CommandLine.arguments.indices.contains(index + 1) {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task {
            let record = await NativeActionProbeRunner.run(CommandLine.arguments[index + 1])
            NativeActionProbeRunner.printJSON(record)
            NSApp.terminate(nil)
        }
        app.run()
    } else {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory)
        app.run()
    }
}
