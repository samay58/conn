import AppKit

MainActor.assumeIsolated {
    if CommandLine.arguments.contains("--preview") {
        PreviewRunner.run()
    } else if CommandLine.arguments.contains("--request-screen-recording") {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task {
            let granted = ScreenRecordingPermissionSetup.ensure()
            print(granted ? "screen_recording=granted" : "screen_recording=denied")
            NSApp.terminate(nil)
        }
        app.run()
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
    } else if let index = CommandLine.arguments.firstIndex(
        of: "--capability-probe"
    ), CommandLine.arguments.indices.contains(index + 1) {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task {
            let menuKind = CommandLine.arguments.firstIndex(
                of: "--menu-kind"
            ).flatMap { index in
                CommandLine.arguments.indices.contains(index + 1)
                    ? CommandLine.arguments[index + 1] : nil
            }
            let record: [String: Any]
            if NativeCapabilityProbeRunner.isLabGuest() {
                record = await NativeCapabilityProbeRunner.run(
                    CommandLine.arguments[index + 1],
                    menuKind: menuKind
                )
            } else {
                record = [
                    "outcome": "blocked",
                    "reason_code": "lab_guest_required",
                ]
            }
            if let outputIndex = CommandLine.arguments.firstIndex(of: "--output"),
               CommandLine.arguments.indices.contains(outputIndex + 1) {
                _ = NativeCapabilityProbeRunner.writeJSON(
                    record,
                    to: CommandLine.arguments[outputIndex + 1]
                )
            }
            NativeActionProbeRunner.printJSON(record)
            NSApp.terminate(nil)
        }
        app.run()
    } else if let index = CommandLine.arguments.firstIndex(
        of: "--lab-affordances"
    ), CommandLine.arguments.indices.contains(index + 2) {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task {
            let record: [String: Any]
            if NativeCapabilityProbeRunner.isLabGuest() {
                record = NativeLabOracleRunner.runAffordances(
                    bundleID: CommandLine.arguments[index + 1],
                    expected: CommandLine.arguments[index + 2]
                )
            } else {
                record = [
                    "outcome": "blocked",
                    "reason_code": "lab_guest_required",
                ]
            }
            if let outputIndex = CommandLine.arguments.firstIndex(of: "--output"),
               CommandLine.arguments.indices.contains(outputIndex + 1) {
                _ = NativeCapabilityProbeRunner.writeJSON(
                    record,
                    to: CommandLine.arguments[outputIndex + 1]
                )
            }
            NativeActionProbeRunner.printJSON(record)
            NSApp.terminate(nil)
        }
        app.run()
    } else if let index = CommandLine.arguments.firstIndex(of: "--lab-target"),
              CommandLine.arguments.indices.contains(index + 2) {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task {
            let record: [String: Any]
            if NativeCapabilityProbeRunner.isLabGuest() {
                record = NativeLabOracleRunner.runTarget(
                    bundleID: CommandLine.arguments[index + 1],
                    expected: CommandLine.arguments[index + 2]
                )
            } else {
                record = [
                    "outcome": "blocked",
                    "reason_code": "lab_guest_required",
                ]
            }
            if let outputIndex = CommandLine.arguments.firstIndex(of: "--output"),
               CommandLine.arguments.indices.contains(outputIndex + 1) {
                _ = NativeCapabilityProbeRunner.writeJSON(
                    record,
                    to: CommandLine.arguments[outputIndex + 1]
                )
            }
            NativeActionProbeRunner.printJSON(record)
            NSApp.terminate(nil)
        }
        app.run()
    } else if let index = CommandLine.arguments.firstIndex(of: "--lab-oracle"),
              CommandLine.arguments.indices.contains(index + 2) {
        let app = NSApplication.shared
        app.setActivationPolicy(.accessory)
        Task {
            let record: [String: Any]
            if NativeCapabilityProbeRunner.isLabGuest() {
                record = NativeLabOracleRunner.run(
                    bundleID: CommandLine.arguments[index + 1],
                    expected: CommandLine.arguments[index + 2]
                )
            } else {
                record = [
                    "outcome": "blocked",
                    "reason_code": "lab_guest_required",
                ]
            }
            if let outputIndex = CommandLine.arguments.firstIndex(of: "--output"),
               CommandLine.arguments.indices.contains(outputIndex + 1) {
                _ = NativeCapabilityProbeRunner.writeJSON(
                    record,
                    to: CommandLine.arguments[outputIndex + 1]
                )
            }
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
