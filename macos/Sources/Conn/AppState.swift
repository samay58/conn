import SwiftUI

struct Chip: Identifiable, Equatable {
    let id: String
    let preview: String
    let status: String

    var pending: Bool { status == "proposed" }
    var ok: Bool { status == "completed" || status == "running" }
}

@MainActor
final class AppState: ObservableObject {
    @Published var phase = "idle"
    @Published var connected = false
    @Published var live = false
    @Published var userLine = ""
    @Published var modelLine = ""
    @Published var chips: [Chip] = []
    @Published var level: Double = 0
    @Published var spentUSD = 0.0
    @Published var capUSD = 1.0
    @Published var toast: String?
    @Published var rejectPulse: Int = 0

    var pendingChip: Chip? { chips.first(where: \.pending) }

    var stateLabel: String {
        switch phase {
        case "idle": return "Idle"
        case "listening": return "Listening"
        case "thinking": return "Thinking"
        case "acting": return "Acting"
        case "awaiting_approval": return "Approve?"
        case "speaking": return "Speaking"
        case "done": return "Done"
        case "failed": return "Reconnecting"
        case "budget_hold": return "Budget hold"
        default: return phase
        }
    }

    func apply(_ msg: [String: Any]) {
        switch msg["type"] as? String {
        case "hello":
            live = msg["live"] as? Bool ?? false
            if let cap = msg["cap_usd"] as? Double { capUSD = cap }
        case "state":
            phase = msg["phase"] as? String ?? phase
            connected = msg["connected"] as? Bool ?? connected
            if let spent = msg["spent_usd"] as? Double, spent > 0 { spentUSD = spent }
            if let ledger = msg["ledger"] as? [[String: Any]] {
                chips = ledger.map {
                    Chip(id: $0["call_id"] as? String ?? "",
                         preview: $0["preview"] as? String ?? "",
                         status: $0["status"] as? String ?? "")
                }
            }
        case "user_transcript":
            userLine = msg["text"] as? String ?? ""
            modelLine = ""
        case "transcript_delta":
            modelLine += msg["text"] as? String ?? ""
        case "level":
            level = msg["value"] as? Double ?? 0
        case "cost":
            if let r = msg["receipt"] as? [String: Any],
               let usd = r["estimated_usd"] as? Double { spentUSD = usd }
        case "receipt":
            if let r = msg["receipt"] as? [String: Any],
               let usd = r["estimated_usd"] as? Double { spentUSD = usd }
        case "toast":
            toast = msg["text"] as? String
        case "reject_input":
            rejectPulse += 1
        default:
            break
        }
    }
}
