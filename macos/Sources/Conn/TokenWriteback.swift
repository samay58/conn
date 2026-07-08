import SwiftUI

// Write Back for the tuning playground (packet I12). Renders a complete
// DesignTokens.swift from the current store: raw literals interpolated from
// the tuned values, everything else (comments, the derived block, the
// forwarding enum) verbatim from the template below, never from slider
// state. If the canonical file gains a token, this template must gain the
// same line; the round-trip test (render of a default store equals the file
// on disk) is the enforcement.
//
// This file is excluded from the magic-number guard for the same reason
// DesignTokens.swift is: the template text IS the tokens file.

enum TokenWriteback {
    // Minimal literal formatting: %g trims trailing zeros, and unannotated
    // Double declarations get a decimal point so inference stays Double.
    static func fmt(_ x: Double) -> String {
        var s = String(format: "%g", x)
        if !s.contains(".") && !s.contains("e") { s += ".0" }
        return s
    }

    // CGFloat lines carry an explicit annotation, so bare integers are fine.
    static func fmtCG(_ x: CGFloat) -> String {
        String(format: "%g", Double(x))
    }

    static func fmtColor(_ c: PaletteColor) -> String {
        "PaletteColor(red: \(fmt(c.red)), green: \(fmt(c.green)), blue: \(fmt(c.blue)))"
    }

    static func hex(_ c: PaletteColor) -> String {
        String(format: "#%02X%02X%02X",
               Int((c.red * 255).rounded()),
               Int((c.green * 255).rounded()),
               Int((c.blue * 255).rounded()))
    }

    static func render(_ v: DesignTokenStore) -> String {
        """
        import SwiftUI

        // The design token store. Raw motion, personality, and palette tokens are
        // mutable at runtime so the tuning playground (packet I12) can drive them
        // live; the DesignTokens enum below forwards the same static names every
        // view has always read, so call sites never see the store. Derived values
        // are computed properties: they recompute from the raw tokens on every read
        // and are never written directly. This file is regenerated verbatim by the
        // playground's Write Back (TokenWriteback.render); hand edits survive only
        // if the template in TokenWriteback.swift carries them.

        struct PaletteColor: Equatable {
            var red: Double
            var green: Double
            var blue: Double
            var color: Color { Color(red: red, green: green, blue: blue) }
        }

        final class DesignTokenStore: ObservableObject {
            // motion
            @Published var summonSpring = Spring(response: \(fmt(v.summonSpring.response)), dampingRatio: \(fmt(v.summonSpring.dampingRatio)))
            @Published var collapseSpring = Spring(response: \(fmt(v.collapseSpring.response)), dampingRatio: \(fmt(v.collapseSpring.dampingRatio)))
            @Published var chipOpenDuration = \(fmt(v.chipOpenDuration))
            @Published var chipButtonsFadeDelay = \(fmt(v.chipButtonsFadeDelay))
            @Published var chipConfirmSettleDuration = \(fmt(v.chipConfirmSettleDuration))
            @Published var stateWordCrossfade = \(fmt(v.stateWordCrossfade))
            @Published var doneSettleDuration = \(fmt(v.doneSettleDuration))
            @Published var doneCollapseDelay = \(fmt(v.doneCollapseDelay))
            @Published var failedCollapseDelay = \(fmt(v.failedCollapseDelay))
            @Published var refusalPulseDuration = \(fmt(v.refusalPulseDuration))
            @Published var belaySnapDuration = \(fmt(v.belaySnapDuration))
            @Published var contentStaggerDelay = \(fmt(v.contentStaggerDelay))
            @Published var toastDuration = \(fmt(v.toastDuration))
            @Published var thinkingEllipsisPeriod = \(fmt(v.thinkingEllipsisPeriod))
            @Published var thinkingDotOpacityFloor = \(fmt(v.thinkingDotOpacityFloor))
            let refusalShakeMagnitude: CGFloat = 2
            let refusalShakeCycles = 3
            // personality
            @Published var aliveness = \(fmt(v.aliveness))
            @Published var breathAmplitude = \(fmt(v.breathAmplitude))
            @Published var breathPeriod = \(fmt(v.breathPeriod))
            @Published var squashHeightOvershoot = \(fmt(v.squashHeightOvershoot))
            @Published var squashWidthOvershoot = \(fmt(v.squashWidthOvershoot))
            @Published var squashWidthLeadMs = \(fmt(v.squashWidthLeadMs))
            @Published var exhaleContraction = \(fmt(v.exhaleContraction))
            @Published var exhaleDuration = \(fmt(v.exhaleDuration))
            let breathFrameInterval = 1.0 / 30.0
            // derived personality values. aliveness scales every behavior: at 0 the
            // summon springs go critically damped, the width lead vanishes, and breath
            // and exhale render flat, leaving a fully static island. Computed, never
            // stored: the playground writes raw tokens and these follow.
            var squashWidthLead: Double { squashWidthLeadMs / 1000.0 * aliveness }
            var summonWidthSpring: Spring {
                Self.springOvershooting(squashWidthOvershoot * aliveness, response: summonSpring.response)
            }
            var summonHeightSpring: Spring {
                Self.springOvershooting(squashHeightOvershoot * aliveness, response: summonSpring.response)
            }

            // A spring whose first peak overshoots its target by `overshoot` (a 0...1
            // fraction). An underdamped spring overshoots by exp(-z * pi / sqrt(1 - z^2))
            // for damping ratio z; inverting that lands the peak exactly on the token.
            static func springOvershooting(_ overshoot: Double, response: Double) -> Spring {
                guard overshoot > 0 else { return Spring(response: response, dampingRatio: 1.0) }
                let k = -log(overshoot)
                let zeta = k / (k * k + Double.pi * Double.pi).squareRoot()
                return Spring(response: response, dampingRatio: zeta)
            }

            // palette (island, on black)
            let islandBg = Color.black
            @Published var islandTextOpacity = \(fmt(v.islandTextOpacity))
            @Published var islandTextSecondaryOpacity = \(fmt(v.islandTextSecondaryOpacity))
            // lilac #C3B1E1: the signature color (listening waveform and ring, the
            // thinking word). Clears 4.5:1 on black by a wide margin (about 10.7:1).
            @Published var islandAccentRGB = \(fmtColor(v.islandAccentRGB))
            @Published var islandAmberRGB = \(fmtColor(v.islandAmberRGB))
            @Published var islandGreenRGB = \(fmtColor(v.islandGreenRGB))
            @Published var islandRedRGB = \(fmtColor(v.islandRedRGB))
            // gold #E0C060: budget hold only. Money and caution without failure;
            // lighter and yellower than the amber approval dot. About 11.9:1 on black.
            @Published var islandGoldRGB = \(fmtColor(v.islandGoldRGB))
            // frozen panel surface (non-notch fallback; values preserved verbatim
            // from the panel era when WaveformView rejoined the guard at I7)
            let panelBarSpring = Spring(response: 0.15, dampingRatio: 0.75)
            let panelPhaseCrossfade = 0.25
            // geometry
            let islandGrowWidth: CGFloat = 58
            let islandContentHeight: CGFloat = 60
            let islandCornerRadius: CGFloat = 13
            let chipRowHeight: CGFloat = 40
            let chipButtonMinHeight: CGFloat = 24
            let chipButtonCornerRadius: CGFloat = 6
            @Published var toolChipHeight: CGFloat = \(fmtCG(v.toolChipHeight))
            @Published var toolChipPaddingH: CGFloat = \(fmtCG(v.toolChipPaddingH))
            @Published var toolChipBgOpacity = \(fmt(v.toolChipBgOpacity))
            // Just under half the button height: at exactly height/2 (a true capsule)
            // the stroke path renders seam ticks at the ends; 10pt reads identically.
            @Published var overrideCornerRadius: CGFloat = \(fmtCG(v.overrideCornerRadius))
        }

        // The static names every view reads. Forwarding, not storage: the values
        // live in `current`, which the tuning playground mutates live.
        enum DesignTokens {
            static let current = DesignTokenStore()
            static let sourceFilePath: String = #filePath

            // motion
            static var summonSpring: Spring { current.summonSpring }
            static var collapseSpring: Spring { current.collapseSpring }
            static var chipOpenDuration: Double { current.chipOpenDuration }
            static var chipButtonsFadeDelay: Double { current.chipButtonsFadeDelay }
            static var chipConfirmSettleDuration: Double { current.chipConfirmSettleDuration }
            static var stateWordCrossfade: Double { current.stateWordCrossfade }
            static var doneSettleDuration: Double { current.doneSettleDuration }
            static var doneCollapseDelay: Double { current.doneCollapseDelay }
            static var failedCollapseDelay: Double { current.failedCollapseDelay }
            static var refusalPulseDuration: Double { current.refusalPulseDuration }
            static var refusalShakeMagnitude: CGFloat { current.refusalShakeMagnitude }
            static var refusalShakeCycles: Int { current.refusalShakeCycles }
            static var belaySnapDuration: Double { current.belaySnapDuration }
            static var contentStaggerDelay: Double { current.contentStaggerDelay }
            static var toastDuration: Double { current.toastDuration }
            static var thinkingEllipsisPeriod: Double { current.thinkingEllipsisPeriod }
            static var thinkingDotOpacityFloor: Double { current.thinkingDotOpacityFloor }
            // personality
            static var aliveness: Double { current.aliveness }
            static var breathAmplitude: Double { current.breathAmplitude }
            static var breathPeriod: Double { current.breathPeriod }
            static var breathFrameInterval: Double { current.breathFrameInterval }
            static var squashHeightOvershoot: Double { current.squashHeightOvershoot }
            static var squashWidthOvershoot: Double { current.squashWidthOvershoot }
            static var squashWidthLeadMs: Double { current.squashWidthLeadMs }
            static var exhaleContraction: Double { current.exhaleContraction }
            static var exhaleDuration: Double { current.exhaleDuration }
            // derived
            static var squashWidthLead: Double { current.squashWidthLead }
            static var summonWidthSpring: Spring { current.summonWidthSpring }
            static var summonHeightSpring: Spring { current.summonHeightSpring }
            static func springOvershooting(_ overshoot: Double, response: Double) -> Spring {
                DesignTokenStore.springOvershooting(overshoot, response: response)
            }
            // palette
            static var islandBg: Color { current.islandBg }
            static var islandText: Color { Color.white.opacity(current.islandTextOpacity) }
            static var islandTextSecondary: Color { Color.white.opacity(current.islandTextSecondaryOpacity) }
            static var islandAccent: Color { current.islandAccentRGB.color }
            static var islandAmber: Color { current.islandAmberRGB.color }
            static var islandGreen: Color { current.islandGreenRGB.color }
            static var islandRed: Color { current.islandRedRGB.color }
            static var islandGold: Color { current.islandGoldRGB.color }
            // frozen panel surface
            static var panelBarSpring: Spring { current.panelBarSpring }
            static var panelPhaseCrossfade: Double { current.panelPhaseCrossfade }
            // geometry
            static var islandGrowWidth: CGFloat { current.islandGrowWidth }
            static var islandContentHeight: CGFloat { current.islandContentHeight }
            static var islandCornerRadius: CGFloat { current.islandCornerRadius }
            static var chipRowHeight: CGFloat { current.chipRowHeight }
            static var chipButtonMinHeight: CGFloat { current.chipButtonMinHeight }
            static var chipButtonCornerRadius: CGFloat { current.chipButtonCornerRadius }
            static var toolChipHeight: CGFloat { current.toolChipHeight }
            static var toolChipPaddingH: CGFloat { current.toolChipPaddingH }
            static var toolChipBgOpacity: Double { current.toolChipBgOpacity }
            static var overrideCornerRadius: CGFloat { current.overrideCornerRadius }
        }

        """
    }

    // The spec rows a tuned value belongs to, printed old -> new so the
    // paste-back into docs/2026-07-05-ux-craft-spec.md is mechanical.
    static func specTableDiff(from old: DesignTokenStore, to new: DesignTokenStore) -> String {
        var lines: [String] = []

        func row(_ label: String, _ table: String, _ a: String, _ b: String) {
            if a != b { lines.append("  \(label) [\(table)]: \(a) -> \(b)") }
        }

        row("summonSpring.response", "Motion / Summon morph",
            fmt(old.summonSpring.response), fmt(new.summonSpring.response))
        row("summonSpring.dampingRatio", "Motion / Summon morph",
            fmt(old.summonSpring.dampingRatio), fmt(new.summonSpring.dampingRatio))
        row("collapseSpring.response", "Motion / Collapse",
            fmt(old.collapseSpring.response), fmt(new.collapseSpring.response))
        row("collapseSpring.dampingRatio", "Motion / Collapse",
            fmt(old.collapseSpring.dampingRatio), fmt(new.collapseSpring.dampingRatio))
        row("chipOpenDuration", "Motion / Chip open-close", fmt(old.chipOpenDuration), fmt(new.chipOpenDuration))
        row("chipButtonsFadeDelay", "Motion / Chip open-close", fmt(old.chipButtonsFadeDelay), fmt(new.chipButtonsFadeDelay))
        row("chipConfirmSettleDuration", "Motion / Chip open-close", fmt(old.chipConfirmSettleDuration), fmt(new.chipConfirmSettleDuration))
        row("stateWordCrossfade", "Motion / State word crossfade", fmt(old.stateWordCrossfade), fmt(new.stateWordCrossfade))
        row("doneSettleDuration", "Motion / Done settle", fmt(old.doneSettleDuration), fmt(new.doneSettleDuration))
        row("doneCollapseDelay", "Motion / Done settle", fmt(old.doneCollapseDelay), fmt(new.doneCollapseDelay))
        row("failedCollapseDelay", "State vocabulary / failed", fmt(old.failedCollapseDelay), fmt(new.failedCollapseDelay))
        row("refusalPulseDuration", "Motion / Refusal pulse", fmt(old.refusalPulseDuration), fmt(new.refusalPulseDuration))
        row("belaySnapDuration", "Motion / Belay snap", fmt(old.belaySnapDuration), fmt(new.belaySnapDuration))
        row("contentStaggerDelay", "Motion / Summon morph", fmt(old.contentStaggerDelay), fmt(new.contentStaggerDelay))
        row("toastDuration", "State vocabulary / toast", fmt(old.toastDuration), fmt(new.toastDuration))
        row("thinkingEllipsisPeriod", "Motion / Thinking ellipsis", fmt(old.thinkingEllipsisPeriod), fmt(new.thinkingEllipsisPeriod))
        row("thinkingDotOpacityFloor", "Motion / Thinking ellipsis", fmt(old.thinkingDotOpacityFloor), fmt(new.thinkingDotOpacityFloor))
        row("aliveness", "Personality", fmt(old.aliveness), fmt(new.aliveness))
        row("breathAmplitude", "Personality / Breath", fmt(old.breathAmplitude), fmt(new.breathAmplitude))
        row("breathPeriod", "Personality / Breath", fmt(old.breathPeriod), fmt(new.breathPeriod))
        row("squashHeightOvershoot", "Personality / Squash and stretch", fmt(old.squashHeightOvershoot), fmt(new.squashHeightOvershoot))
        row("squashWidthOvershoot", "Personality / Squash and stretch", fmt(old.squashWidthOvershoot), fmt(new.squashWidthOvershoot))
        row("squashWidthLeadMs", "Personality / Squash and stretch", fmt(old.squashWidthLeadMs), fmt(new.squashWidthLeadMs))
        row("exhaleContraction", "Personality / Exhale", fmt(old.exhaleContraction), fmt(new.exhaleContraction))
        row("exhaleDuration", "Personality / Exhale", fmt(old.exhaleDuration), fmt(new.exhaleDuration))
        row("island.text opacity", "Palette", fmt(old.islandTextOpacity), fmt(new.islandTextOpacity))
        row("island.textSecondary opacity", "Palette", fmt(old.islandTextSecondaryOpacity), fmt(new.islandTextSecondaryOpacity))
        row("island.accent", "Palette", hex(old.islandAccentRGB), hex(new.islandAccentRGB))
        row("island.amber", "Palette", hex(old.islandAmberRGB), hex(new.islandAmberRGB))
        row("island.green", "Palette", hex(old.islandGreenRGB), hex(new.islandGreenRGB))
        row("island.red", "Palette", hex(old.islandRedRGB), hex(new.islandRedRGB))
        row("island.gold", "Palette", hex(old.islandGoldRGB), hex(new.islandGoldRGB))
        row("toolChipHeight", "State vocabulary / acting", fmtCG(old.toolChipHeight), fmtCG(new.toolChipHeight))
        row("toolChipPaddingH", "State vocabulary / acting", fmtCG(old.toolChipPaddingH), fmtCG(new.toolChipPaddingH))
        row("toolChipBgOpacity", "State vocabulary / acting", fmt(old.toolChipBgOpacity), fmt(new.toolChipBgOpacity))
        row("overrideCornerRadius", "State vocabulary / budget_hold", fmtCG(old.overrideCornerRadius), fmtCG(new.overrideCornerRadius))

        if lines.isEmpty { return "spec-table diff: no tuned values differ from the compiled defaults" }
        return "spec-table diff (paste back into docs/2026-07-05-ux-craft-spec.md):\n" + lines.joined(separator: "\n")
    }
}
