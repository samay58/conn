import SwiftUI

// The island voice line's model. The daemon publishes one level per 40 ms
// audio block (25 Hz): mic rms / 4000 while listening, playback rms / 6000
// while speaking, each clamped to 0...1 (src/conn/audio.py). This file turns
// that coarse, linear stream into something that reads like a voice:
//
// - VoiceLevelMeter holds the latest level and when it arrived. A level
//   older than waveStaleAfter reads as silence, so a playback stall or a
//   dropped socket can never freeze the line mid-surge.
// - WaveformEngine integrates on a fixed 120 Hz step: a noise gate and a
//   loudness curve (rms^0.6, roughly how loudness grows with amplitude),
//   then a fast attack and slower release so 25 Hz steps never show as
//   stairs. Each step lands in a short ring; bar k from the center shows the
//   level from k ripple steps ago, so every syllable rises in the middle and
//   travels outward. The right side lags a touch so the line never looks
//   mirrored by machine. A soft knee rounds peaks instead of flat-topping.
// - Silence while listening or speaking is a slow breath swelling from the
//   center, never a dead row of dots. Thinking is a different gesture on
//   purpose: a soft crest gliding side to side, not a quieter voice.
// - The Character face rides the same model: eyes blink at a speech pause
//   or after a long wait, and lift or glance with the phrase's energy (a
//   slower-smoothed level, so they follow phrases, not syllables).
//
// Reduced motion keeps the line honest (it still follows the level, more
// slowly) and drops the breath, shimmer, glide, blink, and eye travel.
// The engine allocates nothing per frame: every buffer is sized once.

final class VoiceLevelMeter {
    private(set) var value = 0.0
    private(set) var source = ""
    private(set) var receivedAt: TimeInterval = -.infinity

    init() {}

    // A meter whose level never goes stale: still shots and tests.
    convenience init(holding value: Double) {
        self.init()
        hold(value)
    }

    static func now() -> TimeInterval { Date.timeIntervalSinceReferenceDate }

    func push(_ value: Double, source: String = "", at time: TimeInterval = VoiceLevelMeter.now()) {
        self.value = value.isFinite ? min(max(value, 0), 1) : 0
        self.source = source
        receivedAt = time
    }

    func hold(_ value: Double) {
        push(value, source: source, at: .infinity)
    }

    func reset() {
        value = 0
        source = ""
        receivedAt = -.infinity
    }

    func level(at time: TimeInterval, staleAfter: Double) -> Double {
        time - receivedAt <= staleAfter ? value : 0
    }
}

// Every number the engine reads, gathered once per frame from DesignTokens
// so a test can pin its own values. Reduced motion is folded in here.
struct WaveformTuning {
    var bars = DesignTokens.waveBarCount
    var step = DesignTokens.waveStepInterval
    var attack = DesignTokens.waveAttack
    var release = DesignTokens.waveRelease
    var staleAfter = DesignTokens.waveStaleAfter
    var noiseFloor = DesignTokens.waveNoiseFloor
    var gamma = DesignTokens.waveGamma
    var knee = DesignTokens.waveKnee
    var envelopeFalloff = DesignTokens.waveEnvelopeFalloff
    var envelopeFloor = DesignTokens.waveEnvelopeFloor
    var rippleDelay = DesignTokens.waveRippleDelay
    var rippleSkew = DesignTokens.waveRippleSkew
    var shimmer = DesignTokens.waveShimmer
    var shimmerRate = DesignTokens.waveShimmerRate
    var breathFloor = DesignTokens.waveBreathFloor
    var breathDepth = DesignTokens.waveBreathDepth
    var breathPeriod = DesignTokens.waveBreathPeriod
    var breathTravel = DesignTokens.waveBreathTravel
    var thinkBase = DesignTokens.waveThinkBase
    var thinkCrest = DesignTokens.waveThinkCrest
    var thinkPeriod = DesignTokens.waveThinkPeriod
    var thinkWidth = DesignTokens.waveThinkWidth
    var restAmplitude = DesignTokens.waveRestAmplitude
    var brightnessFloor = DesignTokens.waveBrightnessFloor
    var morphDuration = DesignTokens.waveMorphDuration
    var voicedThreshold = DesignTokens.waveVoicedThreshold
    var eyeAttack = DesignTokens.waveEyeAttack
    var eyeRelease = DesignTokens.waveEyeRelease
    var blinkClose = DesignTokens.characterBlinkClose
    var blinkOpen = DesignTokens.characterBlinkOpen
    var blinkClosedScale = Double(DesignTokens.characterBlinkClosedScale)
    var blinkAfterPause = DesignTokens.characterBlinkAfterPause
    var blinkMinGap = DesignTokens.characterBlinkMinGap
    var blinkWhileWaiting = DesignTokens.characterBlinkWhileWaiting
    var reduceMotion = false

    static func current(reduceMotion: Bool) -> WaveformTuning {
        var t = WaveformTuning()
        if reduceMotion {
            t.reduceMotion = true
            t.attack = DesignTokens.waveReducedAttack
            t.release = DesignTokens.waveReducedRelease
        }
        return t
    }

    // The daemon level mapped to display loudness: gate the room noise,
    // then rms^gamma so quiet speech still moves the line and loud speech
    // has headroom left.
    func loudness(_ raw: Double) -> Double {
        let gated = max(0, raw - noiseFloor) / max(1 - noiseFloor, 1e-6)
        return pow(min(gated, 1), gamma)
    }

    // Identity below the knee, then a tanh shoulder that approaches 1 but
    // never reaches it: loud peaks round off instead of flat-topping.
    func softClip(_ x: Double) -> Double {
        guard x > knee else { return max(x, 0) }
        let room = 1 - knee
        return knee + room * tanh((x - knee) / room)
    }
}

final class WaveformEngine {
    enum Mode: Equatable {
        case rest, listening, speaking, thinking

        init(phase: String) {
            switch phase {
            case "listening": self = .listening
            case "speaking": self = .speaking
            case "thinking", "acting": self = .thinking
            default: self = .rest
            }
        }

        var animates: Bool { self != .rest }
    }

    // Outputs, read by the painter and the eyes after each advance.
    private(set) var heights: [Double]
    private(set) var brightness: [Double]
    // Smoothed display loudness (0...1) and the slower one the eyes ride.
    private(set) var level = 0.0
    private(set) var eyeLevel = 0.0
    // 1 is open; a blink dips toward blinkClosedScale and back.
    private(set) var eyeOpenness = 1.0
    private(set) var mode = Mode.rest
    private(set) var started = false
    private(set) var blinkCount = 0

    private let bars: Int
    private var envelope: [Double]
    private var target: [Double]
    private var from: [Double]
    private var ring: [Double]
    private var head = 0
    private var clock = 0.0
    private var modeStart = -Double.infinity
    private var lastVoicedAt = -Double.infinity
    private var lastBlinkAt = -Double.infinity
    private var blinkStart = -Double.infinity
    private var voicedSinceBlink = false

    // Ring capacity covers the deepest ripple delay (eight bars out, with
    // skew) at the finest step with room to spare.
    private static let ringCapacity = 96
    // A gap longer than this (the view was off screen, a breakpoint) is a
    // fresh start, not a catch-up burst of steps.
    private static let maxGap = 0.5
    // Shape constants, not feel: shimmerSpread detunes each bar's wobble so
    // no two move in step; shimmerPhase scatters their starting points;
    // brightnessGain lets ordinary speech reach full brightness; thinkInset
    // keeps the gliding crest off the outermost bars; thinkStill is the
    // reduced-motion crest weight, spread evenly instead of gliding.
    private static let shimmerSpread = 0.29
    private static let shimmerPhase = 2.1
    private static let brightnessGain = 1.25
    private static let thinkInset = 1.5
    private static let thinkStill = 0.35

    init(bars: Int = DesignTokens.waveBarCount) {
        self.bars = max(bars, 1)
        heights = Array(repeating: 0, count: self.bars)
        brightness = Array(repeating: 1, count: self.bars)
        envelope = Array(repeating: 1, count: self.bars)
        target = Array(repeating: 0, count: self.bars)
        from = Array(repeating: 0, count: self.bars)
        ring = Array(repeating: 0, count: Self.ringCapacity)
    }

    func advance(to t: TimeInterval, meter: VoiceLevelMeter, mode next: Mode, tuning: WaveformTuning) {
        refreshEnvelope(tuning)
        if !started || t < clock || t - clock > Self.maxGap {
            warmStart(at: t, meter: meter, mode: next, tuning: tuning)
            return
        }
        if next != mode {
            for i in 0..<bars { from[i] = heights[i] }
            mode = next
            modeStart = t
            // The user's words never earn a pause blink in Conn's reply.
            voicedSinceBlink = false
        }
        let step = tuning.step
        let attackK = 1 - exp(-step / max(tuning.attack, 1e-4))
        let releaseK = 1 - exp(-step / max(tuning.release, 1e-4))
        let eyeAttackK = 1 - exp(-step / max(tuning.eyeAttack, 1e-4))
        let eyeReleaseK = 1 - exp(-step / max(tuning.eyeRelease, 1e-4))
        var steps = 0
        while clock + step <= t {
            clock += step
            let loud = tuning.loudness(meter.level(at: clock, staleAfter: tuning.staleAfter))
            level += (loud - level) * (loud > level ? attackK : releaseK)
            eyeLevel += (level - eyeLevel) * (level > eyeLevel ? eyeAttackK : eyeReleaseK)
            head = (head + 1) % Self.ringCapacity
            ring[head] = level
            steps += 1
            if steps >= Self.ringCapacity {
                clock = t
                break
            }
        }
        updateBlink(at: t, tuning: tuning)
        compose(at: t, tuning: tuning)
        let blend = Self.ease(min(max((t - modeStart) / max(tuning.morphDuration, 1e-4), 0), 1))
        for i in 0..<bars {
            heights[i] = from[i] + (target[i] - from[i]) * blend
        }
    }

    // First frame (or after a long gap): no attack from zero, no morph, so
    // a still shot or a reopened island shows the line as it is now.
    private func warmStart(at t: TimeInterval, meter: VoiceLevelMeter, mode next: Mode, tuning: WaveformTuning) {
        let loud = tuning.loudness(meter.level(at: t, staleAfter: tuning.staleAfter))
        level = loud
        eyeLevel = loud
        for i in 0..<Self.ringCapacity { ring[i] = loud }
        clock = t
        mode = next
        modeStart = -.infinity
        started = true
        eyeOpenness = 1
        blinkStart = -.infinity
        lastVoicedAt = t
        voicedSinceBlink = false
        compose(at: t, tuning: tuning)
        for i in 0..<bars {
            heights[i] = target[i]
            from[i] = target[i]
        }
    }

    private var envelopeKey = (falloff: -1.0, floor: -1.0)

    private func refreshEnvelope(_ tuning: WaveformTuning) {
        guard envelopeKey.falloff != tuning.envelopeFalloff
            || envelopeKey.floor != tuning.envelopeFloor else { return }
        envelopeKey = (tuning.envelopeFalloff, tuning.envelopeFloor)
        let half = Double(bars) / 2
        let center = Double(bars - 1) / 2
        for i in 0..<bars {
            let x = (Double(i) - center) / half
            envelope[i] = max(exp(-tuning.envelopeFalloff * x * x), tuning.envelopeFloor)
        }
    }

    // The level `delay` seconds ago, linearly interpolated between steps.
    private func history(_ delay: Double, step: Double) -> Double {
        let back = min(max(delay / step, 0), Double(Self.ringCapacity - 2))
        let k = Int(back)
        let f = back - Double(k)
        let a = ring[(head - k + Self.ringCapacity) % Self.ringCapacity]
        let b = ring[(head - k - 1 + Self.ringCapacity) % Self.ringCapacity]
        return a + (b - a) * f
    }

    private func compose(at t: TimeInterval, tuning: WaveformTuning) {
        let center = Double(bars - 1) / 2
        switch mode {
        case .rest:
            for i in 0..<bars {
                target[i] = envelope[i] * tuning.restAmplitude
                brightness[i] = 1
            }
        case .listening, .speaking:
            let breathAngle = 2 * Double.pi * t / max(tuning.breathPeriod, 1e-3)
            for i in 0..<bars {
                let d = Double(i) - center
                let delay = abs(d) * tuning.rippleDelay * (d > 0 ? 1 + tuning.rippleSkew : 1)
                let v = history(delay, step: tuning.step)
                let shimmer = tuning.reduceMotion ? 1
                    : 1 + tuning.shimmer * sin(t * tuning.shimmerRate * (1 + Self.shimmerSpread * Double(i))
                                               + Double(i) * Self.shimmerPhase)
                let voice = tuning.softClip(v * shimmer)
                let swell = tuning.reduceMotion ? 0.5
                    : 0.5 + 0.5 * sin(breathAngle - abs(d) * tuning.breathTravel)
                let breath = tuning.breathFloor + tuning.breathDepth * swell
                // Screen blend: never below the breath, smooth into the voice.
                target[i] = envelope[i] * (breath + (1 - breath) * voice)
                brightness[i] = tuning.brightnessFloor
                    + (1 - tuning.brightnessFloor) * min(v * Self.brightnessGain, 1)
            }
        case .thinking:
            let reach = max(center - Self.thinkInset, 0)
            let crest = tuning.reduceMotion ? center
                : center + reach * sin(2 * Double.pi * t / max(tuning.thinkPeriod, 1e-3))
            let width = max(tuning.thinkWidth, 0.1)
            for i in 0..<bars {
                let g = tuning.reduceMotion ? Self.thinkStill : exp(-pow((Double(i) - crest) / width, 2))
                target[i] = envelope[i].squareRoot() * (tuning.thinkBase + tuning.thinkCrest * g)
                brightness[i] = tuning.brightnessFloor + (1 - tuning.brightnessFloor) * g
            }
        }
    }

    // Blinks come from the audio, not a random timer: once at a pause after
    // Conn has said something, or after the user has left the line quiet
    // for a while. Never while thinking, never with reduced motion.
    private func updateBlink(at t: TimeInterval, tuning: WaveformTuning) {
        guard !tuning.reduceMotion, mode == .listening || mode == .speaking else {
            blinkStart = -.infinity
            eyeOpenness = 1
            return
        }
        if level >= tuning.voicedThreshold {
            lastVoicedAt = t
            voicedSinceBlink = true
        }
        let rested = t - lastBlinkAt >= tuning.blinkMinGap
        switch mode {
        case .speaking:
            if voicedSinceBlink && rested && t - lastVoicedAt >= tuning.blinkAfterPause {
                blink(at: t)
            }
        case .listening:
            let quietSince = max(lastVoicedAt, modeStart, lastBlinkAt)
            if t - quietSince >= tuning.blinkWhileWaiting { blink(at: t) }
        default:
            break
        }
        let e = t - blinkStart
        let closed = tuning.blinkClosedScale
        if e < 0 {
            eyeOpenness = 1
        } else if e < tuning.blinkClose {
            eyeOpenness = 1 - (1 - closed) * Self.ease(e / tuning.blinkClose)
        } else if e < tuning.blinkClose + tuning.blinkOpen {
            eyeOpenness = closed + (1 - closed) * Self.ease((e - tuning.blinkClose) / tuning.blinkOpen)
        } else {
            eyeOpenness = 1
        }
    }

    private func blink(at t: TimeInterval) {
        blinkStart = t
        lastBlinkAt = t
        voicedSinceBlink = false
        blinkCount += 1
    }

    static func ease(_ x: Double) -> Double {
        let c = min(max(x, 0), 1)
        return c * c * (3 - 2 * c)
    }
}

// One Canvas pass for the whole line: no per-bar views, no layout per frame.
enum WaveformPainter {
    static func naturalSize(bars: Int = DesignTokens.waveBarCount) -> CGSize {
        let n = CGFloat(bars)
        return CGSize(width: n * DesignTokens.waveBarWidth + (n - 1) * DesignTokens.waveBarSpacing,
                      height: DesignTokens.waveMaxHeight)
    }

    static func paint(_ context: inout GraphicsContext, size: CGSize,
                      heights: [Double], brightness: [Double],
                      shading: GraphicsContext.Shading) {
        let natural = naturalSize(bars: heights.count)
        let scale = natural.width > 0 ? size.width / natural.width : 1
        let w = DesignTokens.waveBarWidth * scale
        let pitch = (DesignTokens.waveBarWidth + DesignTokens.waveBarSpacing) * scale
        let minH = DesignTokens.waveMinHeight * scale
        let travel = (DesignTokens.waveMaxHeight - DesignTokens.waveMinHeight) * scale
        let midY = size.height / 2
        let base = context.opacity
        for i in heights.indices {
            let h = minH + travel * CGFloat(min(max(heights[i], 0), 1))
            let rect = CGRect(x: CGFloat(i) * pitch, y: midY - h / 2, width: w, height: h)
            context.opacity = base * (i < brightness.count ? min(max(brightness[i], 0), 1) : 1)
            context.fill(Path(roundedRect: rect, cornerRadius: w / 2, style: .continuous), with: shading)
        }
        context.opacity = base
    }
}
