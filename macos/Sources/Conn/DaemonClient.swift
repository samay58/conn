import Foundation
import QuartzCore

@MainActor
final class DaemonClient {
    private let url = URL(string: "ws://127.0.0.1:8787/ws")!
    private var task: URLSessionWebSocketTask?
    private let state: AppState
    private var closed = false

    init(state: AppState) {
        self.state = state
    }

    static func monotonicMs() -> Int {
        Int(CACurrentMediaTime() * 1000)
    }

    func connect() {
        closed = false
        let task = URLSession.shared.webSocketTask(with: url)
        self.task = task
        task.resume()
        receive(on: task)
    }

    func close() {
        closed = true
        task?.cancel(with: .normalClosure, reason: nil)
    }

    private static let timedTypes: Set<String> = ["ptt_down", "ptt_up", "approval", "stop"]

    /// Stamps a monotonic client_ts_ms on ptt_down / ptt_up / approval / stop
    /// (unless the caller already supplied one), then sends.
    func send(_ dict: [String: Any]) {
        var stamped = dict
        if let type = dict["type"] as? String,
           Self.timedTypes.contains(type),
           stamped["client_ts_ms"] == nil {
            stamped["client_ts_ms"] = Self.monotonicMs()
        }
        guard let data = try? JSONSerialization.data(withJSONObject: stamped),
              let text = String(data: data, encoding: .utf8) else { return }
        task?.send(.string(text)) { _ in }
    }

    /// Sends a ui_ack after the render pass that first shows `moment`
    /// ("listening" | "thinking" | "chip"). The console calls this today; the
    /// island render wire that calls it lands with the per-state IslandView.
    func sendUiAck(moment: String) {
        send([
            "type": "ui_ack",
            "moment": moment,
            "client_ts_ms": Self.monotonicMs(),
        ])
    }

    private func receive(on task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self, self.task === task else { return }
                switch result {
                case .success(let message):
                    if case .string(let text) = message,
                       let data = text.data(using: .utf8),
                       let msg = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
                        self.state.apply(msg)
                    }
                    self.receive(on: task)
                case .failure:
                    self.state.connected = false
                    guard !self.closed else { return }
                    try? await Task.sleep(for: .milliseconds(800))
                    self.connect()
                }
            }
        }
    }
}
