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

    @State private var buttonsVisible = false
    @State private var decision: Decision?

    private enum Decision { case approved, denied }

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(DesignTokens.islandAmber)
                .frame(width: 5, height: 5)
            Text(chip.preview)
                .font(.system(size: 12.5, weight: .medium))
                .foregroundStyle(DesignTokens.islandText)
                .lineLimit(1)
                // The daemon budgets previews to fit whole; if this ever
                // fires it clips the end, never mid-word in the middle.
                .truncationMode(.tail)
            Spacer(minLength: 12)
            HStack(spacing: 12) {
                denyButton
                approveButton
            }
            .layoutPriority(1)
            .opacity(buttonsVisible ? 1 : 0)
        }
        .frame(maxWidth: 280)
        .onAppear {
            client.sendUiAck(moment: "chip")
            withAnimation(.easeOut(duration: DesignTokens.chipOpenDuration)
                .delay(DesignTokens.chipButtonsFadeDelay)) {
                buttonsVisible = true
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
