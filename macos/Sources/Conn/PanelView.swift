import SwiftUI

extension Color {
    static let ink = Color(red: 0.11, green: 0.11, blue: 0.10)
    static let inkTertiary = Color(red: 0.11, green: 0.11, blue: 0.10).opacity(0.42)
    static let accent = Color(red: 0.18, green: 0.35, blue: 0.66)
    static let amber = Color(red: 0.69, green: 0.32, blue: 0.05)
}

struct PanelView: View {
    @ObservedObject var state: AppState
    let client: DaemonClient

    var body: some View {
        VStack(spacing: 0) {
            WaveformView(level: state.level, phase: state.phase)
                .padding(.top, 16)
                .padding(.bottom, 10)

            if state.pendingChip == nil {
                Text(state.stateLabel.uppercased())
                    .font(.system(size: 9.5, weight: .medium))
                    .tracking(1.8)
                    .foregroundStyle(Color.inkTertiary)
                    .contentTransition(.opacity)
                    .animation(.easeInOut(duration: 0.15), value: state.stateLabel)
            }

            if !state.modelLine.isEmpty || !state.userLine.isEmpty {
                Text(state.modelLine.isEmpty ? state.userLine : state.modelLine)
                    .font(.system(size: 13))
                    .foregroundStyle(state.modelLine.isEmpty ? Color.inkTertiary : Color.ink)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 24)
                    .padding(.top, 10)
                    .transition(.opacity)
            }

            if let chip = state.pendingChip {
                approvalChip(chip)
                    .padding(.horizontal, 14)
                    .padding(.top, 12)
            }

            HStack(spacing: 5) {
                Circle()
                    .fill(state.connected ? Color.accent.opacity(0.8) : Color.inkTertiary)
                    .frame(width: 4.5, height: 4.5)
                Text(state.live ? "live" : "demo")
                    .font(.system(size: 9.5, design: .monospaced))
                    .foregroundStyle(Color.inkTertiary)
                Spacer()
                if state.spentUSD > 0 {
                    Text(String(format: "$%.3f", state.spentUSD))
                        .font(.system(size: 9.5, design: .monospaced))
                        .foregroundStyle(Color.inkTertiary)
                        .contentTransition(.numericText())
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 12)
            .padding(.bottom, 11)
        }
        .frame(width: PanelController.width, height: PanelController.height)
        .animation(.easeInOut(duration: 0.18), value: state.pendingChip)
        .animation(.easeInOut(duration: 0.18),
                   value: state.modelLine.isEmpty && state.userLine.isEmpty)
    }

    private func approvalChip(_ chip: Chip) -> some View {
        HStack(spacing: 10) {
            Circle()
                .fill(Color.amber)
                .frame(width: 5, height: 5)
            Text(chip.preview)
                .font(.system(size: 12.5, weight: .medium))
                .foregroundStyle(Color.ink)
                .lineLimit(2)
            Spacer(minLength: 10)
            Button("Deny") { decide(chip, false) }
                .buttonStyle(ChipButtonStyle(prominent: false))
                .fixedSize()
            Button("Approve") { decide(chip, true) }
                .buttonStyle(ChipButtonStyle(prominent: true))
                .fixedSize()
        }
        .padding(.leading, 12)
        .padding(.trailing, 8)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 9, style: .continuous)
                .fill(Color.ink.opacity(0.04))
                .overlay(
                    RoundedRectangle(cornerRadius: 9, style: .continuous)
                        .strokeBorder(Color.ink.opacity(0.08), lineWidth: 1)
                )
        )
        .transition(.opacity.combined(with: .move(edge: .bottom)))
    }

    private func decide(_ chip: Chip, _ approved: Bool) {
        client.send(["type": "approval", "call_id": chip.id, "approved": approved])
    }
}

extension View {
    /// One chrome for the live panel and the preview: material layer firmed
    /// with a paper tint, hairline border, inner top highlight, soft shadow.
    func panelChrome() -> some View {
        self
            .background(
                ZStack {
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(.regularMaterial)
                    RoundedRectangle(cornerRadius: 12, style: .continuous)
                        .fill(Color.white.opacity(0.45))
                }
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12, style: .continuous)
                    .strokeBorder(Color.black.opacity(0.10), lineWidth: 0.5)
            )
            .overlay(alignment: .top) {
                RoundedRectangle(cornerRadius: 1)
                    .fill(Color.white.opacity(0.55))
                    .frame(height: 0.5)
                    .padding(.horizontal, 13)
                    .padding(.top, 0.5)
            }
            .compositingGroup()
            .shadow(color: .black.opacity(0.16), radius: 18, y: 7)
            .shadow(color: .black.opacity(0.08), radius: 2, y: 1)
    }
}

struct ChipButtonStyle: ButtonStyle {
    var prominent: Bool

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 12, weight: .medium))
            .padding(.horizontal, 12)
            .padding(.vertical, 4.5)
            .background(
                RoundedRectangle(cornerRadius: 6.5, style: .continuous)
                    .fill(prominent ? Color.ink : Color.ink.opacity(0.05))
            )
            .foregroundStyle(prominent ? Color.white : Color.ink)
            .scaleEffect(configuration.isPressed ? 0.97 : 1)
            .opacity(configuration.isPressed ? 0.85 : 1)
            .animation(.easeOut(duration: 0.1), value: configuration.isPressed)
    }
}
