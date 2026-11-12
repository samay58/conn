import SwiftUI

// The canonical island waveform, drawn from WaveformEngine (the model and
// its tuning notes live in WaveformEngine.swift), plus the frozen panel
// waveform below it. The island timeline runs only in the four active
// phases (listening, thinking, acting, speaking) plus one short settle after
// leaving them, so the line eases down to rest instead of snapping. Every
// other phase renders one static frame and starts no timer, which is the
// motion-policy guarantee that nothing ticks while a chip is open or after
// collapse.
//
// The level comes from a VoiceLevelMeter read inside the timeline, not a
// published value, so 25 Hz level messages never re-render the island.
// `face` puts the Character eyes on the same timeline so they can blink and
// lift with the voice.

struct IslandWaveform: View {
    let meter: VoiceLevelMeter
    var phase: String
    // The prototype glass styles draw on light glass, where the on-black
    // tints wash out; nil keeps the phase tint below.
    var tintOverride: Color?
    // A gradient across the line (the Character speaking voice); wins over
    // the tint.
    var gradient: [Color]?
    var scale: CGFloat
    var lineOpacity: Double
    var face: CharacterEyes.Mood?

    // Increments once per timeline tick; the motion-policy test asserts it
    // stays static in every non-active phase.
    @MainActor static var tickCount = 0
    // Every frame evaluation, ticked or not: proves the paused timeline is
    // really idle rather than re-rendering a static frame.
    @MainActor static var renderCount = 0

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var engine = WaveformEngine()
    @State private var settling = false

    init(meter: VoiceLevelMeter, phase: String, tintOverride: Color? = nil,
         gradient: [Color]? = nil, scale: CGFloat = 1, lineOpacity: Double = 1,
         face: CharacterEyes.Mood? = nil) {
        self.meter = meter
        self.phase = phase
        self.tintOverride = tintOverride
        self.gradient = gradient
        self.scale = scale
        self.lineOpacity = lineOpacity
        self.face = face
    }

    // A fixed level that never goes stale: previews and tests.
    init(level: Double, phase: String, tintOverride: Color? = nil) {
        self.init(meter: VoiceLevelMeter(holding: level), phase: phase, tintOverride: tintOverride)
    }

    private var mode: WaveformEngine.Mode { WaveformEngine.Mode(phase: phase) }

    private var tint: Color {
        if let tintOverride { return tintOverride }
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

    // One timeline, paused outside the live phases, rather than swapping in
    // a static branch: the eyes keep their identity, so the wink and the
    // mood changes still animate across the pause boundary.
    var body: some View {
        let ticking = mode.animates || settling
        TimelineView(.animation(minimumInterval: DesignTokens.waveFrameInterval, paused: !ticking)) { context in
            frame(at: ticking ? context.date.timeIntervalSinceReferenceDate : VoiceLevelMeter.now(),
                  ticked: ticking)
        }
        .onChange(of: mode.animates) { was, now in
            guard was, !now, !reduceMotion else { return }
            settling = true
        }
        .task(id: settling) {
            guard settling else { return }
            try? await Task.sleep(for: .seconds(DesignTokens.waveMorphDuration))
            settling = false
        }
    }

    private func frame(at t: TimeInterval, ticked: Bool) -> some View {
        if ticked { Self.tickCount &+= 1 }
        Self.renderCount &+= 1
        let engine = engine
        engine.advance(to: t, meter: meter, mode: mode,
                       tuning: .current(reduceMotion: reduceMotion))
        return WaveformFace(heights: engine.heights, brightness: engine.brightness,
                            shading: shading, scale: scale, lineOpacity: lineOpacity,
                            face: face,
                            openness: face == .awake ? engine.eyeOpenness : 1,
                            lift: eyeLift(engine), glance: eyeGlance(engine))
    }

    private var shading: GraphicsContext.Shading {
        WaveformFace.shading(gradient: gradient, tint: tint, scale: scale)
    }

    // Conn's own voice lifts the eyes a hair, like a speaker's brows; the
    // user's voice draws their glance toward the line.
    private func eyeLift(_ engine: WaveformEngine) -> CGFloat {
        guard face == .awake, engine.mode == .speaking, !reduceMotion else { return 0 }
        return DesignTokens.characterNodLift * CGFloat(engine.eyeLevel)
    }

    private func eyeGlance(_ engine: WaveformEngine) -> CGFloat {
        guard face == .awake, engine.mode == .listening, !reduceMotion else { return 0 }
        return DesignTokens.characterGlanceShift * CGFloat(engine.eyeLevel)
    }
}

// One frame of the line (and the eyes, when there is a face): the live
// waveform and the playtest filmstrip render through this same view.
struct WaveformFace: View {
    let heights: [Double]
    let brightness: [Double]
    let shading: GraphicsContext.Shading
    var scale: CGFloat = 1
    var lineOpacity: Double = 1
    var face: CharacterEyes.Mood?
    var openness: Double = 1
    var lift: CGFloat = 0
    var glance: CGFloat = 0

    static func shading(gradient: [Color]?, tint: Color, scale: CGFloat) -> GraphicsContext.Shading {
        guard let gradient else { return .color(tint) }
        let width = WaveformPainter.naturalSize().width * scale
        return .linearGradient(Gradient(colors: gradient), startPoint: .zero,
                               endPoint: CGPoint(x: width, y: 0))
    }

    var body: some View {
        let size = WaveformPainter.naturalSize(bars: heights.count)
        HStack(spacing: DesignTokens.characterFaceGap) {
            if let face {
                CharacterEyes(mood: face, openness: openness, lift: lift, glance: glance)
            }
            Canvas { context, canvasSize in
                WaveformPainter.paint(&context, size: canvasSize, heights: heights,
                                      brightness: brightness, shading: shading)
            }
            .frame(width: size.width * scale, height: size.height * scale)
            .opacity(lineOpacity)
            .animation(.easeOut(duration: DesignTokens.stateWordCrossfade), value: lineOpacity)
        }
    }
}

// The frozen panel-era waveform. PanelView (the non-notch fallback surface)
// still renders this; its felt motion is unchanged, only the animation
// literals moved into DesignTokens when this file rejoined the guard. It
// reads the meter inside its timeline, since level is no longer published.

struct WaveformView: View {
    let meter: VoiceLevelMeter
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
            let level = meter.level(at: t, staleAfter: DesignTokens.waveStaleAfter)
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
