import Foundation
import CryptoKit
import QuartzCore
import AppKit

enum BridgeAuthentication {
    static let healthContext = "conn-app-health-v1"
    static let webSocketContext = "conn-app-websocket-v1"
    static let daemonWebSocketContext = "conn-daemon-websocket-v1"

    static func proof(token: String, context: String, challenge: String) -> String {
        let key = SymmetricKey(data: Data(token.utf8))
        let message = Data("\(context):\(challenge)".utf8)
        let digest = HMAC<SHA256>.authenticationCode(for: message, using: key)
        return digest.map { String(format: "%02x", $0) }.joined()
    }

    static func isValidProof(
        _ candidate: String,
        token: String,
        context: String,
        challenge: String
    ) -> Bool {
        let expected = Array(proof(
            token: token,
            context: context,
            challenge: challenge
        ).utf8)
        let received = Array(candidate.utf8)
        guard received.count == expected.count else { return false }

        var difference: UInt8 = 0
        for (receivedByte, expectedByte) in zip(received, expected) {
            difference |= receivedByte ^ expectedByte
        }
        return difference == 0
    }
}

enum AppBuildIdentity {
    /// Build identity the daemon traces alongside its own commit and config
    /// fingerprint: the signed executable's modification time, which the
    /// persistent-signing workflow changes on every rebuild.
    static let stamp: String = {
        guard let executable = Bundle.main.executableURL,
              let attributes = try? FileManager.default.attributesOfItem(
                  atPath: executable.path),
              let modified = attributes[.modificationDate] as? Date else {
            return "unknown"
        }
        return ISO8601DateFormatter().string(from: modified)
    }()
}

struct DaemonHandshake {
    private let bridgeToken: String
    private var currentConnection: UUID?
    private var authenticatedConnection: UUID?
    private var challengeConsumed = false
    private var proofSent = false
    private var completionConsumed = false
    private var pendingChallenge: String?

    init(bridgeToken: String) {
        self.bridgeToken = bridgeToken
    }

    mutating func beginConnection() -> UUID {
        let connection = UUID()
        currentConnection = connection
        authenticatedConnection = nil
        challengeConsumed = false
        proofSent = false
        completionConsumed = false
        pendingChallenge = nil
        return connection
    }

    mutating func respondToChallenge(
        connection: UUID,
        challenge: String,
        method: String
    ) -> [String: Any]? {
        guard currentConnection == connection,
              !challengeConsumed,
              method == "hmac-sha256",
              !challenge.isEmpty else { return nil }
        challengeConsumed = true
        proofSent = true
        pendingChallenge = challenge
        return [
            "type": "client_hello",
            "role": "app",
            "app_build": AppBuildIdentity.stamp,
            "proof": BridgeAuthentication.proof(
                token: bridgeToken,
                context: BridgeAuthentication.webSocketContext,
                challenge: challenge
            ),
        ]
    }

    mutating func completeAfterHello(
        connection: UUID,
        serverProof: String
    ) -> Bool {
        guard canCompleteHello(on: connection) else { return false }
        completionConsumed = true
        guard let pendingChallenge,
              BridgeAuthentication.isValidProof(
                  serverProof,
                  token: bridgeToken,
                  context: BridgeAuthentication.daemonWebSocketContext,
                  challenge: pendingChallenge
              ) else { return false }
        authenticatedConnection = connection
        self.pendingChallenge = nil
        return true
    }

    func canCompleteHello(on connection: UUID) -> Bool {
        currentConnection == connection && proofSent && !completionConsumed
    }

    func allowsPrivilegedFrames(on connection: UUID) -> Bool {
        currentConnection == connection && authenticatedConnection == connection
    }
}

struct NativeRequestReplayGuard {
    private var authenticatedConnection: UUID?
    private var lastSequence: Int?
    private var requestIDs: Set<String> = []

    mutating func beginAuthenticatedConnection(_ connection: UUID) {
        authenticatedConnection = connection
        lastSequence = nil
        requestIDs.removeAll(keepingCapacity: true)
    }

    mutating func accept(
        _ message: [String: Any],
        connection: UUID
    ) -> Bool {
        guard authenticatedConnection == connection,
              let type = message["type"] as? String,
              type == "ax_read" || type == "ax_action",
              let requestID = message["request_id"] as? String,
              !requestID.isEmpty,
              let turnID = message["turn_id"] as? String,
              !turnID.isEmpty,
              let observationEpoch = message["observation_epoch"] as? Int,
              observationEpoch >= 0,
              let sequence = message["sequence"] as? Int,
              sequence > 0,
              lastSequence.map({ sequence > $0 }) ?? true,
              !requestIDs.contains(requestID) else { return false }
        lastSequence = sequence
        requestIDs.insert(requestID)
        return true
    }
}

/// Wire-safe gesture identity: one ID per physical PTT press, shared by both
/// edges so the daemon can correlate down and up without inferring pairs.
enum PttGesture {
    static func newID() -> String {
        UUID().uuidString.lowercased()
    }
}

@MainActor
final class DaemonClient {
    private static let semanticActionOperations: Set<String> = [
        "observe", "observe_visual", "prepare_action", "execute_action",
    ]
    private let url: URL
    private var task: URLSessionWebSocketTask?
    private let state: AppState
    private let bridgeToken: String
    private var handshake: DaemonHandshake
    private var requestReplayGuard = NativeRequestReplayGuard()
    private let executionInterlock: NativeExecutionInterlock
    private let actionFacade: NativeActionFacade
    private var connectionID: UUID?
    private var closed = false
    private var systemObservers: [NSObjectProtocol] = []

    init(
        state: AppState,
        bridgeToken: String = "",
        endpoint: DaemonEndpoint = .current
    ) {
        self.state = state
        self.bridgeToken = bridgeToken
        url = endpoint.webSocket
        handshake = DaemonHandshake(bridgeToken: bridgeToken)
        let executionInterlock = NativeExecutionInterlock()
        self.executionInterlock = executionInterlock
        actionFacade = NativeActionFacade(
            semantic: NativeSemanticActionEngine(
                executionInterlock: executionInterlock
            ),
            visual: NativeVisualControl(executionInterlock: executionInterlock)
        )
        installSystemObservers()
    }

    static func monotonicMs() -> Int {
        Int(CACurrentMediaTime() * 1000)
    }

    static func rejectedNativeActionData(for operation: String) -> [String: Any]? {
        guard !semanticActionOperations.contains(operation) else { return nil }
        return [
            "outcome": "failed",
            "ok": false,
            "dispatch_state": "not_dispatched",
            "retry_safe": true,
            "error": "semantic_operation_required",
            "lane": "semantic",
        ]
    }

    func connect() {
        closed = false
        invalidateNativeActions()
        task?.cancel(with: .goingAway, reason: nil)
        let connection = handshake.beginConnection()
        connectionID = connection
        executionInterlock.beginConnection(connection.uuidString)
        state.clearNavigationState()
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        receive(on: task, connection: connection)
    }

    func close() {
        closed = true
        invalidateNativeActions()
        task?.cancel(with: .normalClosure, reason: nil)
        task = nil
        if let connectionID {
            executionInterlock.disconnect(connectionID.uuidString)
        }
        connectionID = nil
        state.connected = false
        state.clearNavigationState()
    }

    private static let timedTypes: Set<String> = ["ptt_down", "ptt_up", "approval", "stop"]

    /// Stamps a monotonic client_ts_ms on ptt_down / ptt_up / approval / stop
    /// (unless the caller already supplied one), then sends.
    func send(_ dict: [String: Any]) {
        guard let task,
              let connectionID,
              handshake.allowsPrivilegedFrames(on: connectionID) else { return }
        sendAuthenticated(dict, on: task, connection: connectionID)
    }

    private func sendAuthenticated(
        _ dict: [String: Any],
        on task: URLSessionWebSocketTask,
        connection: UUID
    ) {
        guard self.task === task,
              connectionID == connection,
              handshake.allowsPrivilegedFrames(on: connection) else { return }
        var stamped = dict
        if let type = dict["type"] as? String,
           Self.timedTypes.contains(type),
           stamped["client_ts_ms"] == nil {
            stamped["client_ts_ms"] = Self.monotonicMs()
        }
        guard let data = try? JSONSerialization.data(withJSONObject: stamped),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { _ in }
    }

    private func sendHandshake(
        _ dict: [String: Any],
        on task: URLSessionWebSocketTask,
        connection: UUID
    ) {
        guard self.task === task,
              connectionID == connection,
              let data = try? JSONSerialization.data(withJSONObject: dict),
              let text = String(data: data, encoding: .utf8) else { return }
        task.send(.string(text)) { _ in }
    }

    /// Sends a ui_ack after the render pass that first shows `moment`
    /// ("listening" | "thinking" | "approval" | "terminal" | "chip").
    func sendUiAck(moment: String) {
        send([
            "type": "ui_ack",
            "moment": moment,
            "client_ts_ms": Self.monotonicMs(),
        ])
    }

    /// Which ui_ack moments a phase transition produces on the primary
    /// surface. State application and the SwiftUI render for it share one
    /// main-actor turn, so acking at apply time stamps the same pass the
    /// user sees.
    nonisolated static func ackMoments(from oldPhase: String, to newPhase: String) -> [String] {
        guard oldPhase != newPhase else { return [] }
        switch newPhase {
        case "listening": return ["listening"]
        case "thinking": return ["thinking"]
        case "awaiting_approval": return ["approval"]
        case "done", "failed": return ["terminal"]
        default: return []
        }
    }

    private func handleAuthenticatedSideband(
        _ msg: [String: Any],
        on task: URLSessionWebSocketTask,
        connection: UUID
    ) {
        switch msg["type"] as? String {
        case "ax_read":
            guard requestReplayGuard.accept(msg, connection: connection) else { return }
            guard let requestId = msg["request_id"] as? String else { return }
            Task.detached { [weak self] in
                let data = AxContextReader.read()
                await MainActor.run { [weak self] in
                    guard let self else { return }
                    self.sendAuthenticated(
                        self.rpcReply(
                            type: "ax_read_result",
                            requestId: requestId,
                            data: data,
                            request: msg
                        ),
                        on: task,
                        connection: connection
                    )
                }
            }
        case "ax_action":
            guard requestReplayGuard.accept(msg, connection: connection) else { return }
            guard let requestId = msg["request_id"] as? String else { return }
            let op = msg["op"] as? String ?? ""
            var params = msg["params"] as? [String: Any] ?? [:]
            params["execution_connection_id"] = connection.uuidString
            if let rejection = Self.rejectedNativeActionData(for: op) {
                sendAuthenticated(
                    rpcReply(
                        type: "ax_action_result",
                        requestId: requestId,
                        data: rejection,
                        request: msg
                    ),
                    on: task,
                    connection: connection
                )
                return
            }
            Task { @MainActor [weak self] in
                guard let self else { return }
                let data = await actionFacade.perform(op: op, params: params)
                self.sendAuthenticated(
                    self.rpcReply(
                        type: "ax_action_result",
                        requestId: requestId,
                        data: data ?? NSNull(),
                        request: msg
                    ),
                    on: task,
                    connection: connection
                )
            }
        default:
            break
        }
    }

    private func rpcReply(type: String, requestId: String, data: Any,
                          request: [String: Any]) -> [String: Any] {
        [
            "type": type,
            "request_id": requestId,
            "turn_id": request["turn_id"] as? String ?? "system",
            "observation_epoch": request["observation_epoch"] as? Int ?? 0,
            "sequence": request["sequence"] as? Int ?? 0,
            "data": data,
        ]
    }

    private func receive(on task: URLSessionWebSocketTask, connection: UUID) {
        task.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self,
                      self.task === task,
                      self.connectionID == connection else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message,
                       let data = text.data(using: .utf8),
                       let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        guard self.handle(
                            msg,
                            on: task,
                            connection: connection
                        ) else { return }
                    }
                    self.receive(on: task, connection: connection)
                case .failure:
                    self.state.connected = false
                    self.state.clearNavigationState()
                    self.invalidateNativeActions()
                    guard !self.closed else { return }
                    self.task = nil
                    self.executionInterlock.disconnect(connection.uuidString)
                    self.connectionID = nil
                    self.scheduleAuthenticatedReconnect()
                }
            }
        }
    }

    private func handle(
        _ msg: [String: Any],
        on task: URLSessionWebSocketTask,
        connection: UUID
    ) -> Bool {
        switch msg["type"] as? String {
        case "auth_challenge":
            guard let challenge = msg["challenge"] as? String,
                  let method = msg["method"] as? String,
                  let reply = handshake.respondToChallenge(
                      connection: connection,
                      challenge: challenge,
                      method: method
                  ) else {
                rejectAuthentication(on: task, connection: connection)
                return false
            }
            sendHandshake(reply, on: task, connection: connection)
        case "hello":
            guard let serverProof = msg["server_proof"] as? String,
                  handshake.completeAfterHello(
                      connection: connection,
                      serverProof: serverProof
                  ) else {
                rejectAuthentication(on: task, connection: connection)
                return false
            }
            requestReplayGuard.beginAuthenticatedConnection(connection)
            state.apply(msg)
        default:
            guard handshake.allowsPrivilegedFrames(on: connection) else {
                rejectAuthentication(on: task, connection: connection)
                return false
            }
            handleAuthenticatedSideband(msg, on: task, connection: connection)
            let oldPhase = state.phase
            state.apply(msg)
            acceptNavigationState(msg, connection: connection)
            for moment in Self.ackMoments(from: oldPhase, to: state.phase) {
                sendUiAck(moment: moment)
            }
        }
        return true
    }

    private func rejectAuthentication(
        on task: URLSessionWebSocketTask,
        connection: UUID
    ) {
        guard self.task === task, connectionID == connection else { return }
        state.connected = false
        state.clearNavigationState()
        invalidateNativeActions()
        task.cancel(with: .policyViolation, reason: nil)
        self.task = nil
        executionInterlock.disconnect(connection.uuidString)
        connectionID = nil
        guard !closed else { return }
        scheduleAuthenticatedReconnect()
    }

    private func scheduleAuthenticatedReconnect() {
        Task { @MainActor [weak self] in
            try? await Task.sleep(for: .milliseconds(800))
            guard let self, !self.closed, self.task == nil else { return }
            DaemonLauncher.ensureRunning(bridgeToken: self.bridgeToken) { [weak self] in
                guard let self, !self.closed, self.task == nil else { return }
                self.connect()
            }
        }
    }

    private func invalidateNativeActions() {
        Task { await actionFacade.invalidate() }
    }

    private func acceptNavigationState(_ msg: [String: Any], connection: UUID) {
        guard let navigation = msg["navigation"] as? [String: Any],
              let generation = navigation["generation"] as? Int else { return }
        let suspended = navigation["suspended"] as? Bool ?? true
        _ = executionInterlock.accept(
            connectionID: connection.uuidString,
            generation: generation,
            suspended: suspended
        )
    }

    private func installSystemObservers() {
        let suspendNames = [
            NSWorkspace.willSleepNotification,
            NSWorkspace.sessionDidResignActiveNotification,
        ]
        for name in suspendNames {
            systemObservers.append(
                NSWorkspace.shared.notificationCenter.addObserver(
                    forName: name, object: nil, queue: .main
                ) { [weak self, executionInterlock] _ in
                    executionInterlock.suspend()
                    Task { @MainActor [weak self] in self?.systemDidSuspend() }
                }
            )
        }
        let resumeNames = [
            NSWorkspace.didWakeNotification,
            NSWorkspace.sessionDidBecomeActiveNotification,
        ]
        for name in resumeNames {
            systemObservers.append(
                NSWorkspace.shared.notificationCenter.addObserver(
                    forName: name, object: nil, queue: .main
                ) { [weak self] _ in
                    Task { @MainActor [weak self] in self?.systemDidResume() }
                }
            )
        }
        let distributed = DistributedNotificationCenter.default()
        systemObservers.append(distributed.addObserver(
            forName: Notification.Name("com.apple.screenIsLocked"),
            object: nil,
            queue: .main
        ) { [weak self, executionInterlock] _ in
            executionInterlock.suspend()
            Task { @MainActor [weak self] in self?.systemDidSuspend() }
        })
        systemObservers.append(distributed.addObserver(
            forName: Notification.Name("com.apple.screenIsUnlocked"),
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in self?.systemDidResume() }
        })
    }

    private func systemDidSuspend() {
        invalidateNativeActions()
        send(["type": "navigation_suspend"])
    }

    private func systemDidResume() {
        guard state.navigationGranted else { return }
        send([
            "type": "navigation_resume",
            "generation": state.navigationGeneration,
        ])
    }
}
