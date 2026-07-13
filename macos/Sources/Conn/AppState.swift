import SwiftUI

struct Chip: Identifiable, Equatable {
    let id: String
    let name: String
    let preview: String
    let status: String

    var pending: Bool { status == "proposed" }
    var ok: Bool { status == "verified" || status == "completed" }
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
    @Published var axWarning: String?
    @Published var lastActionOutcome: String?

    var pendingChip: Chip? { chips.first(where: \.pending) }
    var actionVerified: Bool { lastActionOutcome == "verified" }
    var showsDoneSuccess: Bool {
        phase == "done" && (lastActionOutcome == nil || actionVerified)
    }

    var islandPrimaryText: String {
        if let toast { return toast }
        if phase == "done", lastActionOutcome != nil { return stateLabel }
        switch phase {
        case "acting", "speaking":
            return modelLine.isEmpty ? stateLabel : modelLine
        case "awaiting_approval":
            return stateLabel
        case "budget_hold":
            return "Cap reached"
        default:
            if !modelLine.isEmpty { return modelLine }
            if !userLine.isEmpty { return userLine }
            return stateLabel
        }
    }

    var stateLabel: String {
        switch phase {
        case "idle": return "Idle"
        case "listening": return "Listening"
        case "thinking": return "Thinking"
        case "acting": return "Acting"
        case "awaiting_approval": return "Approve?"
        case "speaking": return "Speaking"
        case "done":
            if lastActionOutcome == "dispatch_only" { return "Sent, not confirmed" }
            if let lastActionOutcome, lastActionOutcome != "verified" { return "Did not run" }
            return "Done"
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
            let newPhase = msg["phase"] as? String ?? phase
            if newPhase == "listening", phase != "listening" {
                // Turn start: stale lines from the last turn never linger
                // behind the new gesture.
                userLine = ""
                modelLine = ""
                toast = nil
            }
            phase = newPhase
            connected = msg["connected"] as? Bool ?? connected
            if msg.keys.contains("last_action_outcome") {
                lastActionOutcome = msg["last_action_outcome"] as? String
            }
            if let spent = msg["spent_usd"] as? Double, spent > 0 { spentUSD = spent }
            if let ledger = msg["ledger"] as? [[String: Any]] {
                chips = ledger.map {
                    Chip(id: $0["call_id"] as? String ?? "",
                         name: $0["name"] as? String ?? "",
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
        case "low_signal":
            toast = "Barely heard you: speak up or check the input device"
        case "ax_grants":
            axWarning = Self.grantWarning(
                appAx: msg["app_ax"] as? String,
                pythonAx: msg["python_ax"] as? String)
        default:
            break
        }
    }

    /// T2 grant preflight: one short line for the island; the console banner
    /// and doctor carry the full fix. The app lane leads because it covers
    /// context reads; "unattached" and "unknown" are not dark lanes.
    static func grantWarning(appAx: String?, pythonAx: String?) -> String? {
        if appAx == "not_granted" {
            return "Accessibility grant lost: retoggle Conn in System Settings"
        }
        if pythonAx == "not_granted" {
            return "Daemon Accessibility lane dark: run conn --doctor"
        }
        return nil
    }
}
