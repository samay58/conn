import AppKit
import SwiftUI

// `Conn --playtest-waveform <wav> <outdir>`: drives the island voice line
// from real audio, headlessly, and writes what it would have looked like.
//
// The wav (24 kHz mono 16-bit, the daemon's own rate) is cut into the same
// 40 ms blocks the audio callbacks see, and each block's level is computed
// exactly as src/conn/audio.py does: rms / 4000 for the mic, rms / 6000 for
// playback, clamped to 0...1 and rounded to three places as published. Each
// level reaches the meter when the daemon would publish it: a mic block one
// block after it was spoken, a playback block one output buffer before it is
// heard. The engine then steps at 60 fps, and the harness writes:
//
//   <name>-filmstrip.png  frames across the window, as the Character face
//   <name>-timeline.png   heard envelope, published level, smoothed level,
//                         and a bars-over-time heatmap for the whole file
//   <name>-metrics.json   jitter, reversals, clipping, dead bars, tracking
//
// Options: --phase listening|speaking|thinking|idle (default speaking),
// --source mic|speaker (default from the phase), --from S, --span S,
// --frames N, --name NAME, --legacy (the pre-playtest waveform, for a
// before/after), --reduce-motion, and --script listening@0,thinking@2.5,...
// to change phase mid-run (the mic level feeds listening, playback the rest),
// which is how the transitions and the settle are checked.

@MainActor
enum WaveformPlaytest {
    struct Options {
        var wav = ""
        var outDir = ""
        var phase = "speaking"
        var source: String?
        var from = 0.0
        var span = 4.0
        var frames = 24
        var name: String?
        var legacy = false
        var reduceMotion = false
        var script: [(phase: String, at: Double)] = []

        var resolvedSource: String { source ?? (phase == "listening" ? "mic" : "speaker") }

        func phase(at t: Double) -> String {
            script.last(where: { $0.at <= t })?.phase ?? phase
        }

        func source(at t: Double) -> String {
            if script.isEmpty { return resolvedSource }
            return phase(at: t) == "listening" ? "mic" : "speaker"
        }
    }

    // Mirrors src/conn/audio.py: FRAME_MS, TARGET_RATE, and the two
    // normalizers in _in_callback and _out_callback.
    static let sampleRate = 24_000
    static let blockSamples = 960
    static let blockSeconds = 0.04
    static let micReference = 4000.0
    static let speakerReference = 6000.0
    // Delivery model: the playback callback fills one device buffer ahead
    // of the speaker; the socket and main-thread hop add a few ms.
    static let outputLatency = 0.04
    static let transportDelay = 0.008
    static let fps = 60.0

    struct Published { let at: Double; let value: Double }

    struct FrameRecord {
        let t: Double
        let phase: String
        let heights: [Double]
        let brightness: [Double]
        let level: Double
        let openness: Double
        let lift: Double
        let glance: Double
    }

    static func run(_ args: [String]) -> Int32 {
        guard let options = parse(args) else {
            print("usage: Conn --playtest-waveform <wav> <outdir> [--phase P] [--source mic|speaker] "
                  + "[--from S] [--span S] [--frames N] [--name NAME] [--legacy] [--reduce-motion]")
            return 2
        }
        guard let samples = readWav(options.wav) else {
            print("playtest: could not read a 24 kHz mono 16-bit wav at \(options.wav)")
            return 1
        }
        let outURL = URL(fileURLWithPath: options.outDir, isDirectory: true)
        try? FileManager.default.createDirectory(at: outURL, withIntermediateDirectories: true)
        let name = (options.name ?? URL(fileURLWithPath: options.wav).deletingPathExtension().lastPathComponent
            + "-\(options.phase)") + (options.legacy ? "-before" : "")

        let source = options.resolvedSource
        let duration = Double(samples.count) / Double(sampleRate)
        let mic = publishedLevels(samples, source: "mic")
        let speaker = publishedLevels(samples, source: "speaker")
        let records = simulate(mic: mic, speaker: speaker, duration: duration, options: options)
        // Plots and metrics follow whichever source is live at each moment.
        let levels = mic.indices.map { k in
            options.source(at: Double(k) * blockSeconds) == "mic" ? mic[k] : speaker[k]
        }
        let micEnvelope = heardEnvelope(samples, source: "mic")
        let speakerEnvelope = heardEnvelope(samples, source: "speaker")
        let envelope = micEnvelope.indices.map {
            options.source(at: Double($0) / 200) == "mic" ? micEnvelope[$0] : speakerEnvelope[$0]
        }
        let metrics = measure(records: records, levels: levels, envelope: envelope, options: options)

        let window = records.filter { $0.t >= options.from && $0.t <= options.from + options.span }
        let picks = pick(window, count: options.frames)
        let title = "\(name)  ·  \(options.legacy ? "before" : "after")  ·  \(options.phase) from \(source)"
            + (options.reduceMotion ? "  ·  reduced motion" : "")
        var ok = true
        ok = write(Filmstrip(title: title, metricsLine: metrics.summary, frames: picks,
                             legacy: options.legacy),
                   to: outURL.appendingPathComponent("\(name)-filmstrip.png")) && ok
        ok = write(TimelineSheet(title: title, records: records, levels: levels, envelope: envelope,
                                 duration: duration, window: (options.from, options.from + options.span)),
                   to: outURL.appendingPathComponent("\(name)-timeline.png")) && ok
        let json = outURL.appendingPathComponent("\(name)-metrics.json")
        if let data = try? JSONSerialization.data(withJSONObject: metrics.dictionary,
                                                  options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: json)
        }
        print("\(name): \(metrics.summary)")
        return ok ? 0 : 1
    }

    static func parse(_ args: [String]) -> Options? {
        guard let flag = args.firstIndex(of: "--playtest-waveform"), flag + 2 < args.count else { return nil }
        var o = Options()
        o.wav = args[flag + 1]
        o.outDir = args[flag + 2]
        func value(_ key: String) -> String? {
            guard let i = args.firstIndex(of: key), i + 1 < args.count else { return nil }
            return args[i + 1]
        }
        if let v = value("--phase") { o.phase = v }
        if let v = value("--source") { o.source = v }
        if let v = value("--from").flatMap(Double.init) { o.from = v }
        if let v = value("--span").flatMap(Double.init) { o.span = v }
        if let v = value("--frames").flatMap(Int.init) { o.frames = max(v, 1) }
        if let v = value("--name") { o.name = v }
        o.legacy = args.contains("--legacy")
        o.reduceMotion = args.contains("--reduce-motion")
        if let v = value("--script") {
            o.script = v.split(separator: ",").compactMap { entry in
                let parts = entry.split(separator: "@")
                guard parts.count == 2, let at = Double(parts[1]) else { return nil }
                return (String(parts[0]), at)
            }
            if let first = o.script.first { o.phase = first.phase }
        }
        return o
    }

    // MARK: audio

    static func readWav(_ path: String) -> [Int16]? {
        guard let data = FileManager.default.contents(atPath: path), data.count > 12,
              String(decoding: data[0..<4], as: UTF8.self) == "RIFF",
              String(decoding: data[8..<12], as: UTF8.self) == "WAVE" else { return nil }
        func u16(_ o: Int) -> Int { Int(data[o]) | Int(data[o + 1]) << 8 }
        func u32(_ o: Int) -> Int { u16(o) | u16(o + 2) << 16 }
        var offset = 12
        var formatOK = false
        while offset + 8 <= data.count {
            let id = String(decoding: data[offset..<offset + 4], as: UTF8.self)
            let size = u32(offset + 4)
            let body = offset + 8
            if id == "fmt " {
                formatOK = u16(body) == 1 && u16(body + 2) == 1
                    && u32(body + 4) == sampleRate && u16(body + 14) == 16
            } else if id == "data" {
                guard formatOK else { return nil }
                let end = min(body + size, data.count)
                var samples = [Int16]()
                samples.reserveCapacity((end - body) / 2)
                var i = body
                while i + 1 < end {
                    samples.append(Int16(bitPattern: UInt16(data[i]) | UInt16(data[i + 1]) << 8))
                    i += 2
                }
                return samples
            }
            offset = body + size + (size & 1)
        }
        return nil
    }

    static func rms(_ samples: ArraySlice<Int16>) -> Double {
        guard !samples.isEmpty else { return 0 }
        var sum = 0.0
        for s in samples { sum += Double(s) * Double(s) }
        return (sum / Double(samples.count)).squareRoot()
    }

    static func publishedLevels(_ samples: [Int16], source: String) -> [Published] {
        let reference = source == "mic" ? micReference : speakerReference
        var out = [Published]()
        var k = 0
        while k * blockSamples < samples.count {
            let block = samples[(k * blockSamples)..<min((k + 1) * blockSamples, samples.count)]
            let value = (min(rms(block) / reference, 1.0) * 1000).rounded() / 1000
            let start = Double(k) * blockSeconds
            let at = source == "mic" ? start + blockSeconds + transportDelay
                                     : start - outputLatency + transportDelay
            out.append(Published(at: at, value: value))
            k += 1
        }
        return out
    }

    // What the ear gets: 5 ms rms on the same normalizer, for the plot only.
    static func heardEnvelope(_ samples: [Int16], source: String) -> [Double] {
        let reference = source == "mic" ? micReference : speakerReference
        let hop = sampleRate / 200
        return stride(from: 0, to: samples.count, by: hop).map {
            min(rms(samples[$0..<min($0 + hop, samples.count)]) / reference, 1)
        }
    }

    // MARK: simulation

    static func simulate(mic: [Published], speaker: [Published], duration: Double,
                         options: Options) -> [FrameRecord] {
        let meter = VoiceLevelMeter()
        let engine = WaveformEngine()
        let tuning = WaveformTuning.current(reduceMotion: options.reduceMotion)
        // An arbitrary epoch so the engine's clock never starts at zero.
        let epoch = 10_000.0
        var nextMic = 0
        var nextSpeaker = 0
        var records = [FrameRecord]()
        let count = Int(duration * fps)
        for f in 0...count {
            let t = Double(f) / fps
            let phase = options.phase(at: t)
            let mode = WaveformEngine.Mode(phase: phase)
            let source = options.source(at: t)
            let live = mode == .listening || mode == .speaking
            // Both streams advance; only the live one reaches the meter, as
            // the daemon publishes mic levels only while the gate is open
            // and playback levels only while audio plays.
            while nextMic < mic.count, mic[nextMic].at <= t {
                if live, source == "mic" { meter.push(mic[nextMic].value, source: "mic", at: epoch + mic[nextMic].at) }
                nextMic += 1
            }
            while nextSpeaker < speaker.count, speaker[nextSpeaker].at <= t {
                if live, source == "speaker" {
                    meter.push(speaker[nextSpeaker].value, source: "speaker", at: epoch + speaker[nextSpeaker].at)
                }
                nextSpeaker += 1
            }
            if options.legacy {
                let heights = LegacyWaveform.heights(at: epoch + t, level: meter.value, phase: phase)
                records.append(FrameRecord(t: t, phase: phase, heights: heights,
                                           brightness: Array(repeating: 1, count: heights.count),
                                           level: min(max(meter.value * 1.4, 0), 1),
                                           openness: 1, lift: 0, glance: 0))
            } else {
                engine.advance(to: epoch + t, meter: meter, mode: mode, tuning: tuning)
                records.append(FrameRecord(
                    t: t, phase: phase, heights: engine.heights, brightness: engine.brightness,
                    level: engine.level,
                    openness: live ? engine.eyeOpenness : 1,
                    lift: mode == .speaking && !tuning.reduceMotion
                        ? Double(DesignTokens.characterNodLift) * engine.eyeLevel : 0,
                    glance: mode == .listening && !tuning.reduceMotion
                        ? Double(DesignTokens.characterGlanceShift) * engine.eyeLevel : 0))
            }
        }
        return records
    }

    static func pick(_ records: [FrameRecord], count: Int) -> [FrameRecord] {
        guard records.count > count, count > 1 else { return records }
        return (0..<count).map { records[Int(Double($0) * Double(records.count - 1) / Double(count - 1))] }
    }

    // MARK: metrics

    struct Metrics {
        var dictionary: [String: Any]
        var summary: String
    }

    static func measure(records: [FrameRecord], levels: [Published], envelope: [Double],
                        options: Options) -> Metrics {
        let bars = records.first?.heights.count ?? 0
        guard records.count > 2, bars > 0 else { return Metrics(dictionary: [:], summary: "no frames") }
        let center = bars / 2
        var jitter = 0.0
        var reversals = 0
        var clipped = 0
        var voiced = 0
        var dead = 0
        var spread = 0.0
        var lastDelta = [Double](repeating: 0, count: bars)
        let envelopeShape = (0..<bars).map { i -> Double in
            let x = (Double(i) - Double(bars - 1) / 2) / (Double(bars) / 2)
            return max(exp(-DesignTokens.waveEnvelopeFalloff * x * x), DesignTokens.waveEnvelopeFloor)
        }
        func publishedValue(at t: Double) -> Double {
            levels.last(where: { $0.at <= t })?.value ?? 0
        }
        for f in 1..<records.count {
            let a = records[f - 1].heights
            let b = records[f].heights
            for i in 0..<bars {
                let d = b[i] - a[i]
                jitter += abs(d)
                if abs(d) > 0.004 {
                    if lastDelta[i] != 0, (d > 0) != (lastDelta[i] > 0) { reversals += 1 }
                    lastDelta[i] = d
                }
            }
            if (b.max() ?? 0) >= 0.97 { clipped += 1 }
            if publishedValue(at: records[f].t) > 0.08 {
                voiced += 1
                if (b.max() ?? 0) < 0.2 { dead += 1 }
                let shape = (0..<bars).map { b[$0] / envelopeShape[$0] }
                let mean = shape.reduce(0, +) / Double(bars)
                let variance = shape.reduce(0) { $0 + ($1 - mean) * ($1 - mean) } / Double(bars)
                spread += mean > 0 ? variance.squareRoot() / mean : 0
            }
        }
        let n = Double(records.count - 1)
        let seconds = n / fps
        // Tracking: correlation of the center bar with what is heard, at the
        // lag (visual behind audio is positive) that fits best.
        func heard(_ t: Double) -> Double {
            let i = Int(t * 200)
            return i >= 0 && i < envelope.count ? envelope[i] : 0
        }
        var best = (lag: 0, r: -1.0)
        for lagMs in stride(from: -150, through: 250, by: 10) {
            let xs = records.map { heard($0.t - Double(lagMs) / 1000) }
            let ys = records.map { $0.heights[center] }
            let r = pearson(xs, ys)
            if r > best.r { best = (lagMs, r) }
        }
        let zeroLag = pearson(records.map { heard($0.t) }, records.map { $0.heights[center] })
        let dict: [String: Any] = [
            "phase": options.phase,
            "legacy": options.legacy,
            "reduce_motion": options.reduceMotion,
            "jitter_per_frame": jitter / n / Double(bars),
            "reversals_per_bar_per_s": Double(reversals) / Double(bars) / seconds,
            "clipped_frame_fraction": Double(clipped) / n,
            "dead_voiced_fraction": voiced > 0 ? Double(dead) / Double(voiced) : 0,
            "shape_spread_voiced": voiced > 0 ? spread / Double(voiced) : 0,
            "tracking_r_zero_lag": zeroLag,
            "tracking_best_r": best.r,
            "tracking_best_lag_ms": best.lag,
        ]
        let summary = String(format: "jitter %.4f/frame · reversals %.1f/bar/s · clipped %.1f%% · dead %.1f%% · spread %.2f · track r %.2f (best %.2f at %+d ms)",
                             jitter / n / Double(bars), Double(reversals) / Double(bars) / seconds,
                             100 * Double(clipped) / n, voiced > 0 ? 100 * Double(dead) / Double(voiced) : 0,
                             voiced > 0 ? spread / Double(voiced) : 0, zeroLag, best.r, best.lag)
        return Metrics(dictionary: dict, summary: summary)
    }

    static func pearson(_ xs: [Double], _ ys: [Double]) -> Double {
        let n = Double(xs.count)
        guard n > 1 else { return 0 }
        let mx = xs.reduce(0, +) / n
        let my = ys.reduce(0, +) / n
        var sxy = 0.0, sxx = 0.0, syy = 0.0
        for i in xs.indices {
            sxy += (xs[i] - mx) * (ys[i] - my)
            sxx += (xs[i] - mx) * (xs[i] - mx)
            syy += (ys[i] - my) * (ys[i] - my)
        }
        return sxx > 0 && syy > 0 ? sxy / (sxx * syy).squareRoot() : 0
    }

    // MARK: rendering

    static func mood(for phase: String) -> CharacterEyes.Mood {
        switch phase {
        case "listening", "speaking": return .awake
        case "done": return .wink
        case "awaiting_approval": return .alert
        default: return .focused
        }
    }

    static func tone(for phase: String) -> IslandTone {
        switch phase {
        case "listening": return .listening
        case "speaking": return .speaking
        case "thinking": return .thinking
        case "acting": return .acting
        case "done": return .done
        default: return .idle
        }
    }

    static func write<V: View>(_ view: V, to url: URL) -> Bool {
        let renderer = ImageRenderer(content: view.environment(\.colorScheme, .dark))
        renderer.scale = 2
        guard let image = renderer.cgImage,
              let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]),
              (try? png.write(to: url)) != nil else {
            print("playtest: could not write \(url.path)")
            return false
        }
        print("wrote \(url.path)")
        return true
    }
}

// The waveform as it shipped before the playtest (commit 10fcfb5), kept only
// so the harness can render a before/after from the same audio: the raw
// level held between messages, a time-driven traveling sine for shape, and
// a hard clamp at the top.
enum LegacyWaveform {
    static func heights(at t: Double, level: Double, phase: String) -> [Double] {
        let bars = 15
        let animates = ["listening", "thinking", "acting", "speaking"].contains(phase)
        let busy = phase == "thinking" || phase == "acting"
        return (0..<bars).map { i in
            let x = (Double(i) - Double(bars - 1) / 2) / (Double(bars) / 2)
            let envelope = max(exp(-1.9 * x * x), 0.22)
            let travel = sin(t * 5.2 - Double(i) * 0.55)
            let swell = 0.62 + 0.38 * sin(t * 1.7 + Double(i) * 0.22)
            let wave = (0.55 + 0.45 * travel) * swell
            let amplitude: Double = animates
                ? (busy ? 0.10 + 0.12 * (0.5 + 0.5 * sin(t * 2.4 - Double(i) * 0.45))
                        : min(max(level * 1.4, 0.16) * (0.35 + 0.65 * wave), 1.0))
                : 0.05
            return envelope * amplitude
        }
    }
}

private struct PlaytestPill<Content: View>: View {
    @ViewBuilder var content: Content

    var body: some View {
        content
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: DesignTokens.characterCornerRadius, style: .continuous)
                    .fill(Color.black)
                    .overlay(RoundedRectangle(cornerRadius: DesignTokens.characterCornerRadius, style: .continuous)
                        .strokeBorder(DesignTokens.iconLilac.opacity(0.25), lineWidth: 1))
            )
    }
}

private struct Filmstrip: View {
    let title: String
    let metricsLine: String
    let frames: [WaveformPlaytest.FrameRecord]
    let legacy: Bool

    private let columns = 6

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.system(size: 13, weight: .semibold)).foregroundStyle(.white)
            Text(metricsLine).font(.system(size: 10)).foregroundStyle(.white.opacity(0.6))
            Grid(horizontalSpacing: 10, verticalSpacing: 10) {
                ForEach(0..<rows, id: \.self) { r in
                    GridRow {
                        ForEach(0..<columns, id: \.self) { c in
                            let i = r * columns + c
                            if i < frames.count { cell(frames[i]) } else { Color.clear.frame(width: 1, height: 1) }
                        }
                    }
                }
            }
        }
        .padding(16)
        .background(Color(white: 0.16))
    }

    private var rows: Int { (frames.count + columns - 1) / columns }

    private func cell(_ f: WaveformPlaytest.FrameRecord) -> some View {
        let live = ["listening", "thinking", "acting", "speaking"].contains(f.phase)
        let tone = WaveformPlaytest.tone(for: f.phase)
        return VStack(spacing: 4) {
            PlaytestPill {
                WaveformFace(heights: f.heights, brightness: f.brightness,
                             shading: WaveformFace.shading(gradient: VoiceLine.gradient(for: tone),
                                                           tint: VoiceLine.tint(for: tone),
                                                           scale: DesignTokens.characterVoiceScale),
                             scale: DesignTokens.characterVoiceScale,
                             lineOpacity: live ? 1 : DesignTokens.characterRestingVoiceOpacity,
                             face: WaveformPlaytest.mood(for: f.phase), openness: f.openness,
                             lift: CGFloat(f.lift), glance: CGFloat(f.glance))
            }
            Text(String(format: "%.2fs %@", f.t, f.phase)).font(.system(size: 9)).foregroundStyle(.white.opacity(0.5))
        }
    }
}

private struct TimelineSheet: View {
    let title: String
    let records: [WaveformPlaytest.FrameRecord]
    let levels: [WaveformPlaytest.Published]
    let envelope: [Double]
    let duration: Double
    let window: (Double, Double)

    private let pxPerSecond = 120.0
    private let plotHeight = 110.0
    private let rowHeight = 8.0

    var body: some View {
        let width = max(duration * pxPerSecond, 200)
        let bars = records.first?.heights.count ?? 0
        VStack(alignment: .leading, spacing: 8) {
            Text(title + "  ·  gray: heard 5 ms rms · white: published level · lime: what drives the bars")
                .font(.system(size: 11, weight: .medium)).foregroundStyle(.white.opacity(0.85))
            Canvas { ctx, size in plot(&ctx, size) }
                .frame(width: width, height: plotHeight)
            Canvas { ctx, size in heatmap(&ctx, size) }
                .frame(width: width, height: Double(bars) * rowHeight)
            Text("bars over time (top: leftmost bar). Brighter is taller. Ticks every second; the filmstrip window is outlined.")
                .font(.system(size: 10)).foregroundStyle(.white.opacity(0.5))
        }
        .padding(14)
        .background(Color(white: 0.1))
    }

    private func x(_ t: Double) -> Double { t * pxPerSecond }

    private func plot(_ ctx: inout GraphicsContext, _ size: CGSize) {
        let h = size.height
        ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(Color(white: 0.05)))
        var area = Path()
        area.move(to: CGPoint(x: 0, y: h))
        for (i, v) in envelope.enumerated() {
            area.addLine(to: CGPoint(x: x(Double(i) / 200), y: h - v * h))
        }
        area.addLine(to: CGPoint(x: x(Double(envelope.count) / 200), y: h))
        area.closeSubpath()
        ctx.fill(area, with: .color(Color(white: 0.35)))
        var steps = Path()
        for (i, l) in levels.enumerated() {
            let end = i + 1 < levels.count ? levels[i + 1].at : l.at + WaveformPlaytest.blockSeconds
            let y = h - l.value * h
            if i == 0 { steps.move(to: CGPoint(x: x(l.at), y: y)) } else { steps.addLine(to: CGPoint(x: x(l.at), y: y)) }
            steps.addLine(to: CGPoint(x: x(end), y: y))
        }
        ctx.stroke(steps, with: .color(.white.opacity(0.7)), lineWidth: 1)
        var drive = Path()
        for (i, r) in records.enumerated() {
            let p = CGPoint(x: x(r.t), y: h - r.level * h)
            if i == 0 { drive.move(to: p) } else { drive.addLine(to: p) }
        }
        ctx.stroke(drive, with: .color(DesignTokens.iconLime), lineWidth: 1.5)
        ticks(&ctx, size)
    }

    private func heatmap(_ ctx: inout GraphicsContext, _ size: CGSize) {
        ctx.fill(Path(CGRect(origin: .zero, size: size)), with: .color(.black))
        let w = pxPerSecond / WaveformPlaytest.fps
        for r in records {
            for (i, v) in r.heights.enumerated() {
                let rect = CGRect(x: x(r.t), y: Double(i) * rowHeight, width: w + 0.5, height: rowHeight)
                ctx.fill(Path(rect), with: .color(Color(hue: 0.75 - 0.45 * min(v, 1), saturation: 0.7,
                                                        brightness: 0.15 + 0.85 * min(v, 1))))
            }
        }
        ticks(&ctx, size)
    }

    private func ticks(_ ctx: inout GraphicsContext, _ size: CGSize) {
        var s = 0.0
        while s <= duration {
            ctx.fill(Path(CGRect(x: x(s), y: 0, width: 1, height: 6)), with: .color(.white.opacity(0.6)))
            s += 1
        }
        let frame = CGRect(x: x(window.0), y: 0.5, width: x(window.1) - x(window.0), height: size.height - 1)
        ctx.stroke(Path(frame), with: .color(DesignTokens.iconPink.opacity(0.8)), lineWidth: 1)
    }
}
