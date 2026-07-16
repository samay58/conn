import AppKit

MainActor.assumeIsolated {
    let arguments = CommandLine.arguments
    if arguments.contains("--list-scenes") {
        printJSON(["scenes": FixtureScene.allCases.map(\.rawValue)])
        exit(0)
    }
    if let index = arguments.firstIndex(of: "--describe-scene") {
        guard arguments.indices.contains(index + 1),
              let scene = FixtureScene(rawValue: arguments[index + 1]) else {
            fputs("unknown fixture scene\n", stderr)
            exit(2)
        }
        printJSON([
            "scene": scene.rawValue,
            "initial_state_digest": scene.initialStateDigest,
            "initial_state": scene.initialState,
        ])
        exit(0)
    }
    guard let scene = FixtureScene.select(arguments: arguments) else {
        fputs("unknown fixture scene\n", stderr)
        exit(2)
    }
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    let delegate = FixtureController(scene: scene)
    app.delegate = delegate
    app.run()
}

private func printJSON(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(
        withJSONObject: value,
        options: [.sortedKeys, .withoutEscapingSlashes]
    ), let text = String(data: data, encoding: .utf8) else {
        fputs("fixture JSON encoding failed\n", stderr)
        exit(3)
    }
    print(text)
}
