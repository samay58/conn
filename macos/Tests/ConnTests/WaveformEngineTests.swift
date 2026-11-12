import Combine
import XCTest
@testable import Conn

// The voice line's level mapping, driven the way the daemon drives it:
// levels pushed at 25 Hz, the engine advanced at 60 fps. Covers silence,
// a loud burst, a long monotone, a stalled stream, the outward ripple, the
// thinking glide, phase morphs, blinks, and reduced motion.
final class WaveformEngineTests: XCTestCase {
    private struct Run {
        var frames: [[Double]] = []
        var levels: [Double] = []
        var times: [Double] = []
    }

    private let epoch = 50_000.0

    // Steps `seconds` of simulated time. `level(t)` is the daemon level at
    // t (nil publishes nothing, like a stalled stream).
    private func drive(_ engine: WaveformEngine, _ meter: VoiceLevelMeter, mode: WaveformEngine.Mode,
                       from start: Double = 0, seconds: Double, tuning: WaveformTuning = WaveformTuning(),
                       level: (Double) -> Double?) -> Run {
        var run = Run()
        var nextPublish = start
        var t = start
        while t <= start + seconds + 1e-9 {
            while nextPublish <= t {
                if let value = level(nextPublish) { meter.push(value, at: epoch + nextPublish) }
                nextPublish += 0.04
            }
            engine.advance(to: epoch + t, meter: meter, mode: mode, tuning: tuning)
            run.frames.append(engine.heights)
            run.levels.append(engine.level)
            run.times.append(t)
            t += 1.0 / 60.0
        }
        return run
    }

    private var center: Int { DesignTokens.waveBarCount / 2 }

    func testLoudnessCurveGatesNoiseAndKeepsHeadroom() {
        let tuning = WaveformTuning()
        XCTAssertEqual(tuning.loudness(0), 0)
        XCTAssertEqual(tuning.loudness(tuning.noiseFloor), 0, "room noise must not move the line")
        XCTAssertEqual(tuning.loudness(1), 1, accuracy: 1e-9)
        var last = 0.0
        for i in 1...100 {
            let v = tuning.loudness(Double(i) / 100)
            XCTAssertGreaterThanOrEqual(v, last, "the curve must be monotonic")
            last = v
        }
        // Quiet speech (rms about 600 on the playback normalizer) still
        // reads, well above its linear value.
        XCTAssertGreaterThan(tuning.loudness(0.1), 0.2)
        XCTAssertEqual(tuning.softClip(0.5), 0.5, "identity below the knee")
        XCTAssertLessThan(tuning.softClip(5), 1, "the shoulder never flat-tops")
        XCTAssertGreaterThan(tuning.softClip(1.2), tuning.softClip(1.0), "peaks stay distinguishable")
    }

    func testSilenceWhileListeningBreathesAndIsNeverDead() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let run = drive(engine, meter, mode: .listening, seconds: 4) { _ in 0 }
        let centerHeights = run.frames.map { $0[center] }
        let tuning = WaveformTuning()
        XCTAssertGreaterThanOrEqual(centerHeights.min() ?? 0, tuning.breathFloor - 1e-9)
        XCTAssertLessThanOrEqual(centerHeights.max() ?? 1, tuning.breathFloor + tuning.breathDepth + 1e-9)
        XCTAssertGreaterThan((centerHeights.max() ?? 0) - (centerHeights.min() ?? 0), tuning.breathDepth * 0.8,
            "the breath must visibly swell over a period")
        for frame in run.frames { XCTAssertTrue(frame.allSatisfy { $0 > 0 }, "no bar may vanish") }
    }

    func testLoudBurstRoundsOffWithoutClipping() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let run = drive(engine, meter, mode: .speaking, seconds: 2) { t in t >= 0.5 && t < 1.0 ? 1.0 : 0 }
        let peak = run.frames.flatMap { $0 }.max() ?? 0
        XCTAssertLessThan(peak, 1, "a full-scale burst must not pin the bars at the top")
        XCTAssertGreaterThan(peak, 0.85, "a full-scale burst must read as loud")
        XCTAssertTrue(run.frames.flatMap { $0 }.allSatisfy { $0.isFinite && $0 >= 0 })
        // It decays once the burst ends: a second later the line is back to breath.
        XCTAssertLessThan(run.frames.last?[center] ?? 1, 0.4)
    }

    func testLongMonotoneSettlesCalm() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let run = drive(engine, meter, mode: .speaking, seconds: 4) { _ in 0.5 }
        let settled = run.frames.enumerated().filter { run.times[$0.offset] > 1 }.map { $0.element[center] }
        let mean = settled.reduce(0, +) / Double(settled.count)
        let sd = (settled.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / Double(settled.count)).squareRoot()
        XCTAssertLessThan(sd, 0.05, "a steady tone must hold steady, not churn")
        XCTAssertEqual(run.levels.last ?? 0, WaveformTuning().loudness(0.5), accuracy: 0.01)
        // Frame-to-frame motion stays small: no jitter on a constant input.
        var maxStep = 0.0
        for i in 1..<run.frames.count where run.times[i] > 1 {
            maxStep = max(maxStep, abs(run.frames[i][center] - run.frames[i - 1][center]))
        }
        XCTAssertLessThan(maxStep, 0.03)
    }

    func testStalledStreamFallsToSilenceInsteadOfFreezing() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let run = drive(engine, meter, mode: .speaking, seconds: 1) { t in t < 0.2 ? 0.8 : nil }
        XCTAssertLessThan(run.levels.last ?? 1, 0.02, "the last level must not hold after the stream stops")
        XCTAssertEqual(meter.level(at: epoch + 1, staleAfter: DesignTokens.waveStaleAfter), 0)
    }

    func testSyllableRipplesOutwardFromTheCenter() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let run = drive(engine, meter, mode: .speaking, seconds: 1.2) { t in t >= 0.3 && t < 0.38 ? 0.9 : 0 }
        func peakTime(_ bar: Int) -> Double {
            let index = run.frames.indices.max { run.frames[$0][bar] < run.frames[$1][bar] } ?? 0
            return run.times[index]
        }
        let last = DesignTokens.waveBarCount - 1
        XCTAssertLessThan(peakTime(center), peakTime(center + 3))
        XCTAssertLessThan(peakTime(center + 3), peakTime(last))
        XCTAssertLessThan(peakTime(center - 3), peakTime(0))
        // The right side lags the left a touch, so the line is not a mirror.
        XCTAssertGreaterThan(peakTime(last), peakTime(0))
    }

    func testThinkingGlidesRegardlessOfLevel() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let run = drive(engine, meter, mode: .thinking, seconds: 2) { _ in 0.9 }
        let crests = Set(run.frames.map { frame in frame.indices.max { frame[$0] < frame[$1] } ?? 0 })
        XCTAssertGreaterThanOrEqual(crests.count, 6, "the crest must travel across the line")
        let peak = run.frames.flatMap { $0 }.max() ?? 1
        XCTAssertLessThan(peak, 0.6, "thinking must not read as loud speech")
        XCTAssertEqual(engine.eyeOpenness, 1, "no blinks while thinking")
    }

    func testPhaseChangeMorphsInsteadOfSnapping() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let loud = drive(engine, meter, mode: .listening, seconds: 0.6) { _ in 0.7 }
        let before = loud.frames.last ?? []
        let rest = drive(engine, meter, mode: .rest, from: 0.6 + 1.0 / 60.0, seconds: 0.6) { _ in nil }
        let first = rest.frames.first ?? []
        for i in before.indices { XCTAssertLessThan(abs(first[i] - before[i]), 0.15, "bar \(i) snapped") }
        let settled = rest.frames.last ?? []
        let expected = WaveformTuning().restAmplitude
        XCTAssertEqual(settled[center], expected, accuracy: 1e-6, "the line lands on its resting shape")
    }

    func testBlinksFollowSpeechPausesAndLongWaits() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        _ = drive(engine, meter, mode: .speaking, seconds: 1.5) { t in t < 0.8 ? 0.6 : 0 }
        XCTAssertEqual(engine.blinkCount, 1, "one blink at the pause after Conn speaks")

        let waiting = WaveformEngine()
        _ = drive(waiting, VoiceLevelMeter(), mode: .listening, seconds: 3) { _ in 0 }
        XCTAssertEqual(waiting.blinkCount, 0, "no blink before the wait threshold")
        _ = drive(waiting, VoiceLevelMeter(), mode: .listening, from: 3 + 1.0 / 60.0, seconds: 1) { _ in 0 }
        XCTAssertEqual(waiting.blinkCount, 1, "a waiting blink once the user has been quiet a while")
    }

    func testReducedMotionIsCalmAndNeverBlinks() {
        var tuning = WaveformTuning.current(reduceMotion: true)
        tuning.reduceMotion = true
        let engine = WaveformEngine()
        let silent = drive(engine, VoiceLevelMeter(), mode: .listening, seconds: 5, tuning: tuning) { _ in 0 }
        let first = silent.frames.first ?? []
        for frame in silent.frames {
            for i in frame.indices { XCTAssertEqual(frame[i], first[i], accuracy: 1e-9, "silence must hold still") }
        }
        XCTAssertEqual(engine.blinkCount, 0)

        let speaking = WaveformEngine()
        let calm = drive(speaking, VoiceLevelMeter(), mode: .speaking, seconds: 3, tuning: tuning) { t in
            0.5 + 0.4 * sin(t * 2 * Double.pi * 4.5)
        }
        let lively = drive(WaveformEngine(), VoiceLevelMeter(), mode: .speaking, seconds: 3) { t in
            0.5 + 0.4 * sin(t * 2 * Double.pi * 4.5)
        }
        func motion(_ run: Run) -> Double {
            var sum = 0.0
            for i in 1..<run.frames.count {
                for b in run.frames[i].indices { sum += abs(run.frames[i][b] - run.frames[i - 1][b]) }
            }
            return sum
        }
        XCTAssertLessThan(motion(calm), motion(lively) * 0.8, "reduced motion moves less")
        XCTAssertGreaterThan(motion(calm), 0, "but still follows the voice")
        XCTAssertEqual(speaking.blinkCount, 0)
    }

    func testMeterHoldResetAndStaleness() {
        let meter = VoiceLevelMeter(holding: 0.4)
        XCTAssertEqual(meter.level(at: VoiceLevelMeter.now() + 1_000, staleAfter: 0.15), 0.4)
        meter.push(0.7, source: "speaker", at: 10)
        XCTAssertEqual(meter.level(at: 10.1, staleAfter: 0.15), 0.7)
        XCTAssertEqual(meter.level(at: 10.2, staleAfter: 0.15), 0)
        meter.push(.nan, at: 11)
        XCTAssertEqual(meter.value, 0, "a malformed level reads as silence")
        meter.push(3, at: 11)
        XCTAssertEqual(meter.value, 1)
        meter.reset()
        XCTAssertEqual(meter.value, 0)
        XCTAssertEqual(meter.level(at: 11, staleAfter: 0.15), 0)
    }

    @MainActor
    func testLevelMessagesFeedTheMeterWithoutPublishing() {
        let state = AppState()
        var changes = 0
        let token = state.objectWillChange.sink { changes += 1 }
        state.apply(["type": "level", "source": "speaker", "value": 0.42])
        XCTAssertEqual(state.meter.value, 0.42, accuracy: 1e-9)
        XCTAssertEqual(state.meter.source, "speaker")
        XCTAssertEqual(changes, 0, "level traffic must not re-render the island")
        token.cancel()
    }

    // A guard against an accidental per-frame blowup, not a benchmark: a
    // hundred seconds of 60 fps frames must cost well under a second even
    // in a debug build.
    func testAdvanceStaysCheap() {
        let engine = WaveformEngine()
        let meter = VoiceLevelMeter()
        let tuning = WaveformTuning()
        let start = Date()
        for f in 0..<6000 {
            let t = epoch + Double(f) / 60
            if f % 2 == 0 { meter.push(0.5 + 0.4 * sin(Double(f) * 0.3), at: t) }
            engine.advance(to: t, meter: meter, mode: .speaking, tuning: tuning)
        }
        let elapsed = Date().timeIntervalSince(start)
        XCTAssertLessThan(elapsed, 1.0, "6000 frames took \(elapsed) s")
        print("waveform engine: \(elapsed / 6000 * 1e6) us per frame (debug build)")
    }
}
