import SwiftUI

struct WaveformView: View {
    var level: Double
    var phase: String

    private static let bars = 15
    private static let envelope: [Double] = {
        (0..<bars).map { i in
            let x = (Double(i) - Double(bars - 1) / 2) / (Double(bars) / 2)
            return max(exp(-2.0 * x * x), 0.24)
        }
    }()
    private static let speeds: [Double] = (0..<bars).map { 2.6 + Double(($0 * 7) % 5) * 0.45 }
    private static let phases: [Double] = (0..<bars).map { Double($0) * 1.31 }

    private var active: Bool { phase == "listening" || phase == "speaking" }
    private var busy: Bool { phase == "thinking" || phase == "acting" }

    private var tint: Color {
        switch phase {
        case "listening": return .accent
        case "speaking": return .ink
        case "failed", "budget_hold": return Color(red: 0.70, green: 0.15, blue: 0.12)
        case "awaiting_approval": return Color.ink.opacity(0.22)
        default: return Color.ink.opacity(0.35)
        }
    }

    var body: some View {
        TimelineView(.animation(minimumInterval: 1.0 / 60.0)) { context in
            let t = context.date.timeIntervalSinceReferenceDate
            HStack(spacing: 4.5) {
                ForEach(0..<Self.bars, id: \.self) { i in
                    let wobble = 0.5 + 0.5 * sin(t * Self.speeds[i] + Self.phases[i])
                    let breath = 0.5 + 0.5 * sin(t * 1.5 + Self.phases[i] * 0.4)
                    let amplitude: Double = active ? max(level, 0.16)
                        : busy ? 0.14 + 0.08 * breath
                        : 0.08 + 0.04 * breath
                    let height = 4.0 + 32.0 * Self.envelope[i] * amplitude * (0.35 + 0.65 * wobble)
                    Capsule(style: .continuous)
                        .fill(tint)
                        .frame(width: 4, height: max(height, 4))
                        .animation(.spring(response: 0.15, dampingFraction: 0.75),
                                   value: level)
                }
            }
            .frame(height: 40)
        }
        .animation(.easeInOut(duration: 0.25), value: phase)
    }
}
