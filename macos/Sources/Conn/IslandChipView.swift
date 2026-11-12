import SwiftUI

// The interactive approve/deny beat inside the island (packet I8). Pointer
// only, by construction: the hosting panel can never become key, both buttons
// are plain styles with no keyboard shortcut, no focus, and no default-button
// treatment, so no keystroke anywhere in the system can reach a decision.
// Approve renders a brief confirm settle before the decision is sent, so the
// daemon's phase change never clips the acknowledgment; deny sends at once.
// Either way the first click wins and later clicks are ignored.

struct IslandChipView: View {
    let chip: Chip
    let client: DaemonClient
    // The style restyles the buttons only; the decision path below (first
    // click wins, approve settles then sends, deny sends at once) is shared.
    var style: IslandStyle = .classic
    // Centered under a centered preview (D with no card); otherwise
    // right-aligned, Mac dialog order.
    var centered = false

    @State private var buttonsVisible = false
    @State private var decision: Decision?

    private enum Decision { case approved, denied }

    // The preview itself renders on the caption line above (IslandView), which
    // has the island's full width: beside the buttons it had about 15
    // characters, so "Remind tomorrow 9 AM: Call the vet" read "Remind tomorro…"
    // and the click approved words nobody could see.
    var body: some View {
        buttonRow
        .opacity(buttonsVisible ? 1 : 0)
        .onAppear {
            client.sendUiAck(moment: "chip")
            withAnimation(.easeOut(duration: DesignTokens.chipOpenDuration)
                .delay(DesignTokens.chipButtonsFadeDelay)) {
                buttonsVisible = true
            }
        }
    }

    @ViewBuilder private var buttonRow: some View {
        if style == .classic {
            HStack(spacing: 12) {
                denyButton
                approveButton
            }
            .frame(maxWidth: 280)
        } else {
            HStack(spacing: 8) {
                if !centered { Spacer(minLength: 0) }
                Button {
                    decide(.denied)
                } label: {
                    GlassButtonLabel(title: "Deny", role: .secondary, ink: style.ink,
                                     settled: decision == .denied)
                }
                .buttonStyle(IslandPressStyle())
                Button {
                    decide(.approved)
                } label: {
                    GlassButtonLabel(title: "Approve", role: .primary, ink: style.ink,
                                     settled: decision == .approved)
                }
                .buttonStyle(IslandPressStyle())
            }
        }
    }

    private var denyButton: some View {
        Button {
            decide(.denied)
        } label: {
            Text("Deny")
                .font(.system(size: 12, weight: .medium))
                .fixedSize()
                .foregroundStyle(decision == .denied
                                 ? DesignTokens.islandText
                                 : DesignTokens.islandTextSecondary)
                .padding(.horizontal, 8)
                .frame(minHeight: DesignTokens.chipButtonMinHeight)
                .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var approveButton: some View {
        Button {
            decide(.approved)
        } label: {
            Text("Approve")
                .font(.system(size: 12, weight: .medium))
                .fixedSize()
                .foregroundStyle(DesignTokens.islandBg)
                .padding(.horizontal, 12)
                .frame(minHeight: DesignTokens.chipButtonMinHeight)
                .background(
                    RoundedRectangle(cornerRadius: DesignTokens.chipButtonCornerRadius,
                                     style: .continuous)
                        .fill(decision == .approved
                              ? DesignTokens.islandGreen
                              : DesignTokens.islandText)
                )
                .contentShape(RoundedRectangle(cornerRadius: DesignTokens.chipButtonCornerRadius,
                                               style: .continuous))
        }
        .buttonStyle(.plain)
    }

    private func decide(_ choice: Decision) {
        guard decision == nil else { return }
        if choice == .denied {
            decision = .denied
            send(approved: false)
            return
        }
        withAnimation(.easeOut(duration: DesignTokens.chipConfirmSettleDuration)) {
            decision = .approved
        }
        // Deliberately an unstructured Task, not .task: the send must survive
        // the view unmounting mid-settle (a phase flicker would otherwise
        // silently drop the approval).
        Task {
            try? await Task.sleep(for: .seconds(DesignTokens.chipConfirmSettleDuration))
            send(approved: true)
        }
    }

    private func send(approved: Bool) {
        client.send([
            "type": "approval",
            "call_id": chip.id,
            "approved": approved,
        ])
    }
}
