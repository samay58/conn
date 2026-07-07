import Foundation

struct DaemonLaunchConfig: Equatable {
    let python: String
    let projectRoot: String
}

enum DaemonLauncher {
    static let defaultPython = "/Users/samaydhawan/conn/.venv/bin/python"
    static let defaultProjectRoot = "/Users/samaydhawan/conn"
    static let health = URL(string: "http://127.0.0.1:8787/healthz")!
    static let port = 8787
    static let logRetentionDays = 7

    static var process: Process?

    static func ensureRunning(then done: @escaping @MainActor () -> Void) {
        URLSession.shared.dataTask(with: health) { data, response, _ in
            let statusOK = (response as? HTTPURLResponse)?.statusCode == 200
            if statusOK, let data, shouldAdopt(healthzBody: data) {
                DispatchQueue.main.async {
                    Task { @MainActor in done() }
                }
                return
            }
            if statusOK {
                terminatePortOwner(port)
            }
            launch()
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) {
                Task { @MainActor in done() }
            }
        }.resume()
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

    /// Decides whether to adopt an already-running daemon based on its healthz body.
    /// Absence of "phase_age_s"/"upstream_connected" (older daemon, pre-packet P0-D)
    /// is treated as healthy for back-compat.
    static func shouldAdopt(healthzBody data: Data) -> Bool {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return true
        }
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
        if let phaseAge, phaseAge < 120 {
            return true
        }
        return false
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

    static func launch() {
        guard let config = resolveConfig() else {
            NSLog(
                "Conn daemon launch skipped: set CONN_PROJECT_ROOT and CONN_PYTHON, or install Conn at \(defaultProjectRoot) with python at \(defaultPython)"
            )
            return
        }
        let proc = Process()
        proc.executableURL = URL(fileURLWithPath: config.python)
        proc.arguments = ["-m", "conn", "--no-hotkey"]
        proc.currentDirectoryURL = URL(fileURLWithPath: config.projectRoot)
        var env = ProcessInfo.processInfo.environment
        env["PYTHONPATH"] = "src"
        proc.environment = env

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
