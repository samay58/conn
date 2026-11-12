import AppKit
import SwiftUI

// The tuning inspector beside the preview stage. Every raw motion,
// personality, and palette token renders as a slider or color well; derived
// values recompute live and display read-only. "Write to source" regenerates
// DesignTokens.swift on disk from the template (raw literals only; the
// derived block is verbatim) and prints the spec-table diff to stdout for
// manual paste-back.

struct InspectorView: View {
    @ObservedObject var tokens: DesignTokenStore

    @State private var writeBackNote: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                group("Summon and collapse") {
                    slider("Summon response", spring(\.summonSpring, \.response), 0.1...0.6, unit: "s")
                    slider("Summon damping", spring(\.summonSpring, \.dampingRatio), 0.3...1.0)
                    slider("Collapse response", spring(\.collapseSpring, \.response), 0.1...0.6, unit: "s")
                    slider("Collapse damping", spring(\.collapseSpring, \.dampingRatio), 0.3...1.0)
                    slider("Content stagger", $tokens.contentStaggerDelay, 0.0...0.3, unit: "s")
                }
                group("Personality") {
                    slider("Aliveness", $tokens.aliveness, 0.0...1.0)
                    slider("Breath amplitude", $tokens.breathAmplitude, 0.0...0.05)
                    slider("Breath period", $tokens.breathPeriod, 1.0...6.0, unit: "s")
                    slider("Height overshoot", $tokens.squashHeightOvershoot, 0.0...0.12)
                    slider("Width overshoot", $tokens.squashWidthOvershoot, 0.0...0.12)
                    slider("Width lead", $tokens.squashWidthLeadMs, 0.0...120.0, unit: "ms")
                    slider("Exhale contraction", $tokens.exhaleContraction, 0.0...0.08)
                    slider("Exhale duration", $tokens.exhaleDuration, 0.1...0.6, unit: "s")
                } footer: {
                    derivedFooter
                }
                group("Beats") {
                    slider("Chip open", $tokens.chipOpenDuration, 0.05...0.4, unit: "s")
                    slider("Chip buttons fade", $tokens.chipButtonsFadeDelay, 0.0...0.3, unit: "s")
                    slider("Chip confirm settle", $tokens.chipConfirmSettleDuration, 0.0...0.4, unit: "s")
                    slider("State word crossfade", $tokens.stateWordCrossfade, 0.05...0.4, unit: "s")
                    slider("Done settle", $tokens.doneSettleDuration, 0.1...0.8, unit: "s")
                    slider("Done collapse delay", $tokens.doneCollapseDelay, 0.2...2.5, unit: "s")
                    slider("Failed collapse delay", $tokens.failedCollapseDelay, 0.5...6.0, unit: "s")
                    slider("Refusal pulse", $tokens.refusalPulseDuration, 0.1...0.6, unit: "s")
                    slider("Belay snap", $tokens.belaySnapDuration, 0.05...0.4, unit: "s")
                    slider("Toast duration", $tokens.toastDuration, 1.0...6.0, unit: "s")
                    slider("Ellipsis period", $tokens.thinkingEllipsisPeriod, 0.4...3.0, unit: "s")
                    slider("Dot opacity floor", $tokens.thinkingDotOpacityFloor, 0.0...0.8)
                }
                group("Palette") {
                    slider("Text opacity", $tokens.islandTextOpacity, 0.5...1.0)
                    slider("Secondary opacity", $tokens.islandTextSecondaryOpacity, 0.2...1.0)
                    colorWell("Accent", \.islandAccentRGB)
                    colorWell("Amber", \.islandAmberRGB)
                    colorWell("Green", \.islandGreenRGB)
                    colorWell("Red", \.islandRedRGB)
                    colorWell("Gold", \.islandGoldRGB)
                }
                group("Tool capsule and override") {
                    slider("Capsule height", cg($tokens.toolChipHeight), 14.0...30.0, unit: "pt")
                    slider("Capsule padding", cg($tokens.toolChipPaddingH), 4.0...16.0, unit: "pt")
                    slider("Capsule fill", $tokens.toolChipBgOpacity, 0.02...0.3)
                    slider("Override radius", cg($tokens.overrideCornerRadius), 4.0...11.0, unit: "pt")
                }
            }
            .padding(16)
        }
        .controlSize(.small)
        .safeAreaInset(edge: .bottom, spacing: 0) { writeBar }
    }

    // MARK: write back

    private var writeBar: some View {
        VStack(alignment: .leading, spacing: 6) {
            Divider()
            HStack {
                if let note = writeBackNote {
                    Text(note)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                        .truncationMode(.head)
                } else {
                    Text("Changes apply live and reset on quit.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer(minLength: 8)
                Button("Write to source", action: writeBack)
                    .help("Save these values into DesignTokens.swift")
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
        }
        .background(.bar)
    }

    private func writeBack() {
        let text = TokenWriteback.render(tokens)
        let path = DesignTokens.sourceFilePath
        do {
            try text.write(toFile: path, atomically: true, encoding: .utf8)
            writeBackNote = "Saved to \((path as NSString).lastPathComponent)"
        } catch {
            writeBackNote = "Could not save: \(error.localizedDescription)"
        }
        print("write-back: \(writeBackNote ?? "")")
        print(TokenWriteback.specTableDiff(from: DesignTokenStore(), to: tokens))
    }

    private var derivedFooter: some View {
        Text("Derived: width lead \(Self.short(tokens.squashWidthLead)) s, "
             + "width damping \(Self.short(tokens.summonWidthSpring.dampingRatio)), "
             + "height damping \(Self.short(tokens.summonHeightSpring.dampingRatio))")
            .font(.caption)
            .foregroundStyle(.secondary)
            .monospacedDigit()
            .frame(maxWidth: .infinity, alignment: .leading)
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

    // A titled group of rows on one rounded panel.
    private func group<Content: View>(_ title: String,
                                      @ViewBuilder content: () -> Content) -> some View {
        group(title, content: content) { EmptyView() }
    }

    private func group<Content: View, Footer: View>(
        _ title: String,
        @ViewBuilder content: () -> Content,
        @ViewBuilder footer: () -> Footer
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
                .padding(.leading, 4)
            VStack(spacing: 0) {
                content()
                    .padding(.horizontal, 12)
                    .frame(minHeight: Self.rowHeight)
            }
            .padding(.vertical, 4)
            .background(
                RoundedRectangle(cornerRadius: Self.panelRadius, style: .continuous)
                    .fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(
                RoundedRectangle(cornerRadius: Self.panelRadius, style: .continuous)
                    .strokeBorder(Color.primary.opacity(0.07)))
            footer()
                .padding(.horizontal, 4)
        }
    }

    private static let rowHeight: CGFloat = 30
    private static let panelRadius: CGFloat = 8


    private static func short(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(0...3)))
    }

    private func slider(_ label: String, _ value: Binding<Double>, _ range: ClosedRange<Double>,
                        unit: String? = nil) -> some View {
        HStack(spacing: 10) {
            Text(label)
                .lineLimit(1)
                .frame(maxWidth: .infinity, alignment: .leading)
            Slider(value: value, in: range)
                .frame(width: Self.sliderWidth)
            Text(Self.short(value.wrappedValue) + (unit.map { " \($0)" } ?? ""))
                .monospacedDigit()
                .foregroundStyle(.secondary)
                .frame(width: Self.valueWidth, alignment: .trailing)
        }
    }

    private static let sliderWidth: CGFloat = 112
    private static let valueWidth: CGFloat = 50

    private func colorWell(_ label: String, _ kp: ReferenceWritableKeyPath<DesignTokenStore, PaletteColor>) -> some View {
        HStack(spacing: 10) {
            Text(label)
                .frame(maxWidth: .infinity, alignment: .leading)
            Text(TokenWriteback.hex(tokens[keyPath: kp]))
                .monospacedDigit()
                .foregroundStyle(.secondary)
            ColorPicker("", selection: colorBinding(kp), supportsOpacity: false)
                .labelsHidden()
        }
    }
}
