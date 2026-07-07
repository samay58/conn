import SwiftUI

// The canonical island waveform (promoted from IslandView at packet I7) plus
// the frozen panel waveform below it. The island waveform animates only while
// a session is in an active phase (listening, thinking, acting, speaking);
// every other phase renders a static low bar set and starts no timer, which
// is the motion-policy guarantee that nothing ticks while a chip is open or
// after collapse. The traveling-wave constants are shape parameters approved
// live for fluidity, not motion tokens; they stay inline by design.

struct IslandWaveform: View {
    var level: Double
    var phase: String

    // Increments once per timeline tick; the motion-policy test asserts it
    // stays static in every non-active phase.
    @MainActor static var tickCount = 0

    private static let bars = 15
    private static let envelope: [Double] = (0..<bars).map { i in
        let x = (Double(i) - Double(bars - 1) / 2) / (Double(bars) / 2)
        return max(exp(-1.9 * x * x), 0.22)
    }

    private var animates: Bool {
        phase == "listening" || phase == "thinking" || phase == "acting" || phase == "speaking"
    }

    private var tint: Color {
        switch phase {
        case "listening": return DesignTokens.islandAccent
        case "speaking": return DesignTokens.islandText
        case "failed": return DesignTokens.islandRed
        case "budget_hold": return DesignTokens.islandGold
        case "awaiting_approval": return DesignTokens.islandAmber.opacity(0.5)
        case "done": return DesignTokens.islandGreen
        default: return DesignTokens.islandTextSecondary
        }
    }

    var body: some View {
        if animates {
            TimelineView(.animation(minimumInterval: 1.0 / 60.0)) { context in
                bars(at: context.date.timeIntervalSinceReferenceDate, ticked: true)
            }
        } else {
            bars(at: 0, ticked: false)
        }
    }

    // A traveling wave with a slow swell rather than per-bar noise: the crest
    // moves across the bar set so it reads as one fluid ribbon, and the mic or
    // playback level drives most of the height so speech makes it surge.
    private func bars(at t: Double, ticked: Bool) -> some View {
        if ticked { Self.tickCount &+= 1 }
        let busy = phase == "thinking" || phase == "acting"
        return HStack(spacing: 3) {
            ForEach(0..<Self.bars, id: \.self) { i in
                let travel = sin(t * 5.2 - Double(i) * 0.55)
                let swell = 0.62 + 0.38 * sin(t * 1.7 + Double(i) * 0.22)
                let wave = (0.55 + 0.45 * travel) * swell
                let amplitude: Double = animates
                    ? (busy
                        ? 0.10 + 0.12 * (0.5 + 0.5 * sin(t * 2.4 - Double(i) * 0.45))
                        : min(max(level * 1.4, 0.16) * (0.35 + 0.65 * wave), 1.0))
                    : 0.05
                let height = 3.0 + 21.0 * Self.envelope[i] * amplitude
                Capsule(style: .continuous)
                    .fill(tint)
                    .frame(width: 3, height: max(height, 3))
            }
        }
        .frame(height: 24)
        .animation(.easeOut(duration: DesignTokens.stateWordCrossfade), value: animates)
    }
}

// The frozen panel-era waveform. PanelView (the non-notch fallback surface)
// still renders this; its felt motion is unchanged, only the animation
// literals moved into DesignTokens when this file rejoined the guard.

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
                        .animation(.spring(DesignTokens.panelBarSpring), value: level)
                }
            }
            .frame(height: 40)
        }
        .animation(.easeInOut(duration: DesignTokens.panelPhaseCrossfade), value: phase)
    }
}
