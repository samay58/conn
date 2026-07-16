import Foundation

struct DaemonEndpoint: Equatable {
    static let productionPort = 8787

    let port: Int

    var webSocket: URL {
        URL(string: "ws://127.0.0.1:\(port)/ws")!
    }

    var health: URL {
        URL(string: "http://127.0.0.1:\(port)/healthz")!
    }

    var appHealth: URL {
        URL(string: "http://127.0.0.1:\(port)/app-healthz")!
    }

    var console: URL {
        URL(string: "http://127.0.0.1:\(port)")!
    }

    static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> DaemonEndpoint {
        guard let raw = environment["CONN_SERVER_PORT"],
              let port = Int(raw),
              1...65535 ~= port else {
            return DaemonEndpoint(port: productionPort)
        }
        return DaemonEndpoint(port: port)
    }

    static var current: DaemonEndpoint {
        resolve()
    }
}

struct DaemonLaunchConfig: Equatable {
    let python: String
    let projectRoot: String
}

enum DaemonLauncher {
    static let defaultPython = "/Users/samaydhawan/conn/.venv/bin/python"
    static let defaultProjectRoot = "/Users/samaydhawan/conn"
    static let logRetentionDays = 7

    static var process: Process?

    static var endpoint: DaemonEndpoint {
        .current
    }

    static func ensureRunning(bridgeToken: String, then done: @escaping @MainActor () -> Void) {
        let challenge = BridgeChallenge.generate()
        URLSession.shared.dataTask(with: authenticatedHealthRequest(challenge: challenge)) { data, response, _ in
            let statusOK = (response as? HTTPURLResponse)?.statusCode == 200
            if statusOK, let data {
                if shouldAdopt(
                    healthzBody: data,
                    bridgeToken: bridgeToken,
                    challenge: challenge
                ) {
                    DispatchQueue.main.async {
                        Task { @MainActor in done() }
                    }
                    return
                }
                guard isAuthenticatedHealth(
                    healthzBody: data,
                    bridgeToken: bridgeToken,
                    challenge: challenge
                ) else {
                    NSLog("Conn refused to adopt a daemon that failed bridge authentication")
                    return
                }
                terminatePortOwner(endpoint.port)
            }
            launch(bridgeToken: bridgeToken)
            waitUntilAuthenticated(
                bridgeToken: bridgeToken,
                attemptsRemaining: 40,
                then: done
            )
        }.resume()
    }

    static func authenticatedHealthRequest(challenge: String) -> URLRequest {
        var request = URLRequest(url: endpoint.appHealth)
        request.timeoutInterval = 1
        request.setValue(challenge, forHTTPHeaderField: "X-Conn-Challenge")
        return request
    }

    private static func waitUntilAuthenticated(
        bridgeToken: String,
        attemptsRemaining: Int,
        then done: @escaping @MainActor () -> Void
    ) {
        guard attemptsRemaining > 0 else {
            // The daemon we spawned is slow, not foreign: connect anyway.
            // A refused socket lands in DaemonClient's reconnect loop, which
            // re-runs ensureRunning until the health check answers, so a
            // slow upstream handshake can never strand the app disconnected.
            NSLog("Conn daemon slow to authenticate; connecting optimistically")
            DispatchQueue.main.async {
                Task { @MainActor in done() }
            }
            return
        }
        let challenge = BridgeChallenge.generate()
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.25) {
            URLSession.shared.dataTask(with: authenticatedHealthRequest(challenge: challenge)) {
                data, response, _ in
                let statusOK = (response as? HTTPURLResponse)?.statusCode == 200
                if statusOK,
                   let data,
                   shouldAdopt(
                       healthzBody: data,
                       bridgeToken: bridgeToken,
                       challenge: challenge
                   ) {
                    DispatchQueue.main.async {
                        Task { @MainActor in done() }
                    }
                    return
                }
                waitUntilAuthenticated(
                    bridgeToken: bridgeToken,
                    attemptsRemaining: attemptsRemaining - 1,
                    then: done
                )
            }.resume()
        }
    }

    static func resolveConfig(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> DaemonLaunchConfig? {
        if let projectRoot = environment["CONN_PROJECT_ROOT"],
           let python = environment["CONN_PYTHON"],
           !projectRoot.isEmpty,
           !python.isEmpty {
            return DaemonLaunchConfig(python: python, projectRoot: projectRoot)
        }
        if fileExists(defaultProjectRoot), fileExists(defaultPython) {
            return DaemonLaunchConfig(python: defaultPython, projectRoot: defaultProjectRoot)
        }
        return nil
    }

    static func shouldAdopt(
        healthzBody data: Data,
        bridgeToken: String,
        challenge: String
    ) -> Bool {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let proof = json["bridge_proof"] as? String else { return false }
        guard BridgeAuthentication.isValidProof(
            proof,
            token: bridgeToken,
            context: BridgeAuthentication.healthContext,
            challenge: challenge
        ) else { return false }
        guard json["phase_age_s"] != nil || json["upstream_connected"] != nil else {
            return true
        }
        let phase = json["phase"] as? String
        let upstreamConnected = json["upstream_connected"] as? Bool ?? false
        if phase == "idle" && upstreamConnected {
            return true
        }
        let phaseAge: Double? = (json["phase_age_s"] as? Double)
            ?? (json["phase_age_s"] as? Int).map(Double.init)
        return phaseAge.map { $0 < 120 } ?? false
    }

    static func isAuthenticatedHealth(
        healthzBody data: Data,
        bridgeToken: String,
        challenge: String
    ) -> Bool {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let proof = json["bridge_proof"] as? String else { return false }
        return BridgeAuthentication.isValidProof(
            proof,
            token: bridgeToken,
            context: BridgeAuthentication.healthContext,
            challenge: challenge
        )
    }

    static func terminatePortOwner(_ port: Int) {
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: "/usr/sbin/lsof")
        proc.arguments = ["-ti", ":\(port)"]
        let outPipe = Pipe()
        proc.standardOutput = outPipe
        proc.standardError = Pipe()
        do {
            try proc.run()
        } catch {
            return
        }
        proc.waitUntilExit()
        let data = outPipe.fileHandleForReading.readDataToEndOfFile()
        guard let output = String(data: data, encoding: .utf8) else { return }
        for line in output.split(separator: "\n") {
            if let pid = Int32(line.trimmingCharacters(in: .whitespaces)) {
                kill(pid, SIGTERM)
            }
        }
    }

    static func logDirectory(config: DaemonLaunchConfig? = nil) -> URL {
        let root = config?.projectRoot ?? defaultProjectRoot
        return URL(fileURLWithPath: root).appendingPathComponent("data/logs")
    }

    static func currentLogFileURL(now: Date = Date(), config: DaemonLaunchConfig? = nil) -> URL {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        formatter.timeZone = TimeZone.current
        let dateStr = formatter.string(from: now)
        return logDirectory(config: config).appendingPathComponent("daemon-\(dateStr).log")
    }

    static func pruneOldLogs(in dir: URL, olderThanDays days: Int, now: Date = Date()) {
        let fm = FileManager.default
        guard let contents = try? fm.contentsOfDirectory(
            at: dir,
            includingPropertiesForKeys: [.contentModificationDateKey]
        ) else { return }
        let cutoff = now.addingTimeInterval(-Double(days) * 86400)
        for file in contents {
            guard file.lastPathComponent.hasPrefix("daemon-"), file.pathExtension == "log" else { continue }
            guard let attrs = try? fm.attributesOfItem(atPath: file.path),
                  let modDate = attrs[.modificationDate] as? Date,
                  modDate < cutoff else { continue }
            try? fm.removeItem(at: file)
        }
    }

    static func openLogFileHandle(config: DaemonLaunchConfig) -> FileHandle? {
        let fm = FileManager.default
        let dir = logDirectory(config: config)
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
        pruneOldLogs(in: dir, olderThanDays: logRetentionDays)

        let logFile = currentLogFileURL(config: config)
        if !fm.fileExists(atPath: logFile.path) {
            fm.createFile(atPath: logFile.path, contents: nil)
        }
        let handle = try? FileHandle(forWritingTo: logFile)
        handle?.seekToEndOfFile()
        return handle
    }

    static func launchEnvironment(base: [String: String], bridgeToken: String) -> [String: String] {
        var env = base
        env["PYTHONPATH"] = "src"
        env["CONN_BRIDGE_TOKEN"] = bridgeToken
        // Ownership lease: the daemon exits on bounded grace after this
        // process dies, so a quit app never strands a port-squatting daemon.
        env["CONN_PARENT_PID"] = String(ProcessInfo.processInfo.processIdentifier)
        return env
    }

    static func launchArguments(
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> [String] {
        if environment["CONN_DAEMON_MODE"] == "scripted" {
            return ["-m", "conn", "--demo", "--no-audio", "--no-hotkey"]
        }
        return ["-m", "conn", "--no-hotkey"]
    }

    static func launch(bridgeToken: String) {
        guard let config = resolveConfig() else {
            NSLog(
                "Conn daemon launch skipped: set CONN_PROJECT_ROOT and CONN_PYTHON, or install Conn at \(defaultProjectRoot) with python at \(defaultPython)"
            )
            return
        }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: config.python)
        proc.arguments = launchArguments()
        proc.currentDirectoryURL = URL(fileURLWithPath: config.projectRoot)
        proc.environment = launchEnvironment(
            base: ProcessInfo.processInfo.environment,
            bridgeToken: bridgeToken
        )

        if let handle = openLogFileHandle(config: config) {
            proc.standardOutput = handle
            proc.standardError = handle
        }

        do {
            try proc.run()
        } catch {
            NSLog("Conn daemon launch failed: \(error.localizedDescription)")
            return
        }
        process = proc
    }
}
