import SwiftUI

struct Chip: Identifiable, Equatable {
    let id: String
    let name: String
    let preview: String
    let status: String

    var pending: Bool { status == "proposed" }
    var ok: Bool { status == "verified" || status == "completed" }
}

// The island's detail surface (daemon src/conn/cards.py): a list of rows or
// the full text of a reply. One card shows at a time; a card with the same id
// is a revision of the one on screen ("reply" moves draft -> approve ->
// sent) and replaces it in place. Approval never lives here: a reply card in
// state "approve" only shows the body, and the decision stays on the chip.
struct IslandCard: Identifiable, Equatable {
    enum Kind: String { case list, reply }

    struct Row: Equatable {
        let title: String
        let detail: String
        let note: String
    }

    // The daemon caps rows at the same number; the island enforces it too.
    static let maxRows = 8

    let id: String
    let kind: Kind
    let title: String
    let subtitle: String
    let rows: [Row]
    let body: String
    let state: String
    let persist: Bool

    init(id: String, kind: Kind, title: String, subtitle: String = "",
         rows: [Row] = [], body: String = "", state: String = "", persist: Bool = false) {
        self.id = id
        self.kind = kind
        self.title = title
        self.subtitle = subtitle
        self.rows = Array(rows.prefix(Self.maxRows))
        self.body = body
        self.state = state
        self.persist = persist
    }

    // nil for anything malformed: a card is a convenience, never an error.
    init?(wire: [String: Any]) {
        guard let id = wire["id"] as? String, !id.isEmpty,
              let kind = (wire["kind"] as? String).flatMap(Kind.init(rawValue:)),
              let title = wire["title"] as? String else { return nil }
        let rows = (wire["rows"] as? [[String: Any]] ?? []).map {
            Row(title: $0["title"] as? String ?? "",
                detail: $0["detail"] as? String ?? "",
                note: $0["note"] as? String ?? "")
        }
        self.init(id: id, kind: kind, title: title,
                  subtitle: wire["subtitle"] as? String ?? "",
                  rows: rows,
                  body: wire["body"] as? String ?? "",
                  state: wire["state"] as? String ?? "",
                  persist: wire["persist"] as? Bool ?? false)
    }

    // A reply that has already gone (or definitively not).
    var isSettledReply: Bool {
        kind == .reply && ["sent", "unconfirmed", "held"].contains(state)
    }

    // How long a card that does not persist stays up. A verified send only
    // needs a glance; "not sent" and "not confirmed" are news and get read;
    // a list earns time per row.
    var linger: Double {
        if kind == .reply, state == "sent" { return DesignTokens.cardSettledLinger }
        return DesignTokens.cardLinger + DesignTokens.cardLingerPerRow * Double(rows.count)
    }
}

@MainActor
final class AppState: ObservableObject {
    @Published var phase = "idle"
    @Published var connected = false
    @Published var live = false
    @Published var userLine = ""
    @Published var modelLine = ""
    @Published var chips: [Chip] = []
    // Mic or playback level, 25 Hz. Deliberately not published: the
    // waveform reads the meter inside its own timeline, so level traffic
    // never re-renders the island. Setting `level` stamps it fresh.
    let meter = VoiceLevelMeter()
    var level: Double {
        get { meter.value }
        set { meter.push(newValue, source: meter.source) }
    }
    @Published var spentUSD = 0.0
    @Published var capUSD = 5.0
    @Published var toast: String?
    @Published var rejectPulse: Int = 0
    @Published var axWarning: String?
    @Published var lastActionOutcome: String?
    @Published var navigationGranted = false
    @Published var navigationSuspended = false
    @Published var navigationGeneration = 0
    @Published var navigationGuidance = ""
    @Published private(set) var card: IslandCard?
    // Bumped on every card change so a retire timer armed for an earlier
    // card can never clear its replacement.
    private var cardRevision = 0
    private var cardRetireTask: Task<Void, Never>?

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
                // behind the new gesture. A card that does not persist
                // retires with them.
                userLine = ""
                modelLine = ""
                toast = nil
                if let card, !card.persist { clearCard() }
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
            if let navigation = msg["navigation"] as? [String: Any] {
                navigationGranted = navigation["granted"] as? Bool ?? false
                navigationSuspended = navigation["suspended"] as? Bool ?? false
                navigationGeneration = navigation["generation"] as? Int ?? 0
                navigationGuidance = navigation["guidance"] as? String ?? ""
            }
        case "user_transcript":
            userLine = msg["text"] as? String ?? ""
            modelLine = ""
        case "transcript_delta":
            modelLine += msg["text"] as? String ?? ""
        case "level":
            meter.push(msg["value"] as? Double ?? 0, source: msg["source"] as? String ?? "")
        case "cost":
            if let r = msg["receipt"] as? [String: Any],
               let usd = r["estimated_usd"] as? Double { spentUSD = usd }
        case "receipt":
            if let r = msg["receipt"] as? [String: Any],
               let usd = r["estimated_usd"] as? Double { spentUSD = usd }
        case "card":
            if let payload = msg["card"] as? [String: Any],
               let next = IslandCard(wire: payload) {
                setCard(next)
            }
        case "card_clear":
            clearCard()
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

    // `retires: false` is for the preview, whose sample cards must hold
    // still; every daemon card arms its retire rule.
    func setCard(_ next: IslandCard, retires: Bool = true) {
        card = next
        cardRevision &+= 1
        cardRetireTask?.cancel()
        cardRetireTask = nil
        if retires { scheduleCardRetire() }
    }

    // Also the card's close button: Swift-local, no daemon message.
    func clearCard() {
        cardRetireTask?.cancel()
        cardRetireTask = nil
        cardRevision &+= 1
        card = nil
    }

    // Persisting cards stay until replaced, cleared, or closed. The rest
    // retire after IslandCard.linger.
    private func scheduleCardRetire() {
        cardRetireTask?.cancel()
        cardRetireTask = nil
        guard let card, !card.persist else { return }
        let linger = card.linger
        let revision = cardRevision
        cardRetireTask = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(linger))
            guard !Task.isCancelled, let self, self.cardRevision == revision else { return }
            self.clearCard()
        }
    }

    func clearNavigationState() {
        navigationGranted = false
        navigationSuspended = false
        navigationGeneration = 0
        navigationGuidance = ""
    }

    /// The daemon socket died: show the reconnecting state now rather than
    /// freezing the last phase, and drop chips whose buttons can no longer
    /// reach the daemon. The next daemon `state` message restores the truth.
    func markDaemonLost() {
        connected = false
        phase = "failed"
        chips = []
        userLine = ""
        modelLine = ""
        toast = nil
        meter.reset()
        // A card may describe a send whose chip just died with the socket.
        clearCard()
        clearNavigationState()
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
