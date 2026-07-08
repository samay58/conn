import AppKit
import SwiftUI

// The tuning playground inspector (packet I12). Every raw motion,
// personality, and palette token renders as a slider or color well beside
// the preview; derived values recompute live and display read-only. Replay
// drives the same reveal tokens IslandController uses. Write Back
// regenerates DesignTokens.swift on disk from the template (raw literals
// only; the derived block is verbatim) and prints the spec-table diff to
// stdout for manual paste-back.

struct InspectorView: View {
    @ObservedObject var tokens: DesignTokenStore
    var replay: () -> Void
    var collapse: () -> Void

    @State private var writeBackNote: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                actions
                section("Summon and collapse") {
                    slider("summon response", spring(\.summonSpring, \.response), 0.1...0.6)
                    slider("summon damping", spring(\.summonSpring, \.dampingRatio), 0.3...1.0)
                    slider("collapse response", spring(\.collapseSpring, \.response), 0.1...0.6)
                    slider("collapse damping", spring(\.collapseSpring, \.dampingRatio), 0.3...1.0)
                    slider("content stagger", $tokens.contentStaggerDelay, 0.0...0.3)
                }
                section("Personality") {
                    slider("aliveness", $tokens.aliveness, 0.0...1.0)
                    slider("breath amplitude", $tokens.breathAmplitude, 0.0...0.05)
                    slider("breath period", $tokens.breathPeriod, 1.0...6.0)
                    slider("height overshoot", $tokens.squashHeightOvershoot, 0.0...0.12)
                    slider("width overshoot", $tokens.squashWidthOvershoot, 0.0...0.12)
                    slider("width lead ms", $tokens.squashWidthLeadMs, 0.0...120.0)
                    slider("exhale contraction", $tokens.exhaleContraction, 0.0...0.08)
                    slider("exhale duration", $tokens.exhaleDuration, 0.1...0.6)
                }
                section("Derived (read-only)") {
                    derived("width lead", TokenWriteback.fmt(tokens.squashWidthLead) + "s")
                    derived("width spring damping", TokenWriteback.fmt(tokens.summonWidthSpring.dampingRatio))
                    derived("height spring damping", TokenWriteback.fmt(tokens.summonHeightSpring.dampingRatio))
                }
                section("Beats") {
                    slider("chip open", $tokens.chipOpenDuration, 0.05...0.4)
                    slider("chip buttons fade", $tokens.chipButtonsFadeDelay, 0.0...0.3)
                    slider("chip confirm settle", $tokens.chipConfirmSettleDuration, 0.0...0.4)
                    slider("state word crossfade", $tokens.stateWordCrossfade, 0.05...0.4)
                    slider("done settle", $tokens.doneSettleDuration, 0.1...0.8)
                    slider("done collapse delay", $tokens.doneCollapseDelay, 0.2...2.5)
                    slider("failed collapse delay", $tokens.failedCollapseDelay, 0.5...6.0)
                    slider("refusal pulse", $tokens.refusalPulseDuration, 0.1...0.6)
                    slider("belay snap", $tokens.belaySnapDuration, 0.05...0.4)
                    slider("toast duration", $tokens.toastDuration, 1.0...6.0)
                    slider("ellipsis period", $tokens.thinkingEllipsisPeriod, 0.4...3.0)
                    slider("dot opacity floor", $tokens.thinkingDotOpacityFloor, 0.0...0.8)
                }
                section("Palette") {
                    slider("text opacity", $tokens.islandTextOpacity, 0.5...1.0)
                    slider("secondary opacity", $tokens.islandTextSecondaryOpacity, 0.2...1.0)
                    colorWell("accent (lilac)", \.islandAccentRGB)
                    colorWell("amber", \.islandAmberRGB)
                    colorWell("green", \.islandGreenRGB)
                    colorWell("red", \.islandRedRGB)
                    colorWell("gold", \.islandGoldRGB)
                }
                section("Tool capsule and override") {
                    slider("capsule height", cg($tokens.toolChipHeight), 14.0...30.0)
                    slider("capsule padding", cg($tokens.toolChipPaddingH), 4.0...16.0)
                    slider("capsule bg opacity", $tokens.toolChipBgOpacity, 0.02...0.3)
                    slider("override radius", cg($tokens.overrideCornerRadius), 4.0...11.0)
                }
                if let note = writeBackNote {
                    Text(note)
                        .font(.system(size: 11))
                        .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
                }
            }
            .padding(16)
        }
        .frame(width: 300)
        .background(Color.white.opacity(0.38))
    }

    // MARK: actions

    private var actions: some View {
        HStack(spacing: 8) {
            Button("Replay", action: replay)
            Button("Collapse", action: collapse)
            Button("Write Back", action: writeBack)
        }
        .buttonStyle(.bordered)
    }

    private func writeBack() {
        let text = TokenWriteback.render(tokens)
        let path = DesignTokens.sourceFilePath
        do {
            try text.write(toFile: path, atomically: true, encoding: .utf8)
            writeBackNote = "wrote \(path)"
        } catch {
            writeBackNote = "write failed: \(error.localizedDescription)"
        }
        print("write-back: \(writeBackNote ?? "")")
        print(TokenWriteback.specTableDiff(from: DesignTokenStore(), to: tokens))
    }

    // MARK: bindings

    private func spring(
        _ kp: ReferenceWritableKeyPath<DesignTokenStore, Spring>,
        _ part: KeyPath<Spring, Double>
    ) -> Binding<Double> {
        Binding(
            get: { tokens[keyPath: kp][keyPath: part] },
            set: { newValue in
                let old = tokens[keyPath: kp]
                let response = part == \Spring.response ? newValue : old.response
                let damping = part == \Spring.dampingRatio ? newValue : old.dampingRatio
                tokens[keyPath: kp] = Spring(response: response, dampingRatio: damping)
            })
    }

    private func cg(_ binding: Binding<CGFloat>) -> Binding<Double> {
        Binding(get: { Double(binding.wrappedValue) },
                set: { binding.wrappedValue = CGFloat($0) })
    }

    private func colorBinding(
        _ kp: ReferenceWritableKeyPath<DesignTokenStore, PaletteColor>
    ) -> Binding<Color> {
        Binding(
            get: { tokens[keyPath: kp].color },
            set: { newValue in
                guard let c = NSColor(newValue).usingColorSpace(.sRGB) else { return }
                tokens[keyPath: kp] = PaletteColor(
                    red: Double(c.redComponent),
                    green: Double(c.greenComponent),
                    blue: Double(c.blueComponent))
            })
    }

    // MARK: rows

    private func section(_ title: String, @ViewBuilder content: () -> some View) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
            content()
        }
    }

    private func slider(_ label: String, _ value: Binding<Double>, _ range: ClosedRange<Double>) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
                .frame(width: 118, alignment: .leading)
            Slider(value: value, in: range)
            Text(TokenWriteback.fmt(value.wrappedValue))
                .font(.system(size: 11))
                .monospacedDigit()
                .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
                .frame(width: 44, alignment: .trailing)
        }
    }

    private func derived(_ label: String, _ value: String) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
                .frame(width: 118, alignment: .leading)
            Spacer()
            Text(value)
                .font(.system(size: 11))
                .monospacedDigit()
                .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
        }
    }

    private func colorWell(_ label: String, _ kp: ReferenceWritableKeyPath<DesignTokenStore, PaletteColor>) -> some View {
        HStack(spacing: 8) {
            Text(label)
                .font(.system(size: 11))
                .foregroundStyle(Color(red: 0.36, green: 0.34, blue: 0.30))
                .frame(width: 118, alignment: .leading)
            ColorPicker("", selection: colorBinding(kp), supportsOpacity: false)
                .labelsHidden()
            Spacer()
            Text(TokenWriteback.hex(tokens[keyPath: kp]))
                .font(.system(size: 11))
                .monospacedDigit()
                .foregroundStyle(Color(red: 0.12, green: 0.11, blue: 0.10))
        }
    }
}
