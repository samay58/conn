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
    @Published var summonSpring = Spring(response: 0.28, dampingRatio: 0.8)
    @Published var collapseSpring = Spring(response: 0.22, dampingRatio: 0.9)
    @Published var chipOpenDuration = 0.16
    @Published var chipButtonsFadeDelay = 0.06
    @Published var chipConfirmSettleDuration = 0.12
    @Published var stateWordCrossfade = 0.12
    @Published var doneSettleDuration = 0.32
    @Published var doneCollapseDelay = 0.9
    @Published var failedCollapseDelay = 2.5
    @Published var refusalPulseDuration = 0.25
    @Published var belaySnapDuration = 0.12
    @Published var contentStaggerDelay = 0.08
    @Published var toastDuration = 3.0
    @Published var thinkingEllipsisPeriod = 1.2
    @Published var thinkingDotOpacityFloor = 0.25
    let refusalShakeMagnitude: CGFloat = 2
    let refusalShakeCycles = 3
    // personality
    @Published var aliveness = 1.0
    @Published var breathAmplitude = 0.015
    @Published var breathPeriod = 3.2
    @Published var squashHeightOvershoot = 0.04
    @Published var squashWidthOvershoot = 0.02
    @Published var squashWidthLeadMs = 40.0
    @Published var exhaleContraction = 0.02
    @Published var exhaleDuration = 0.22
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
    @Published var islandTextOpacity = 0.92
    @Published var islandTextSecondaryOpacity = 0.58
    // lilac #C3B1E1: the signature color (listening waveform and ring, the
    // thinking word). Clears 4.5:1 on black by a wide margin (about 10.7:1).
    @Published var islandAccentRGB = PaletteColor(red: 0.765, green: 0.694, blue: 0.882)
    @Published var islandAmberRGB = PaletteColor(red: 0.91, green: 0.63, blue: 0.24)
    @Published var islandGreenRGB = PaletteColor(red: 0.3, green: 0.76, blue: 0.54)
    @Published var islandRedRGB = PaletteColor(red: 0.88, green: 0.32, blue: 0.32)
    // gold #E0C060: budget hold only. Money and caution without failure;
    // lighter and yellower than the amber approval dot. About 11.9:1 on black.
    @Published var islandGoldRGB = PaletteColor(red: 0.878, green: 0.753, blue: 0.376)
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
    @Published var toolChipHeight: CGFloat = 20
    @Published var toolChipPaddingH: CGFloat = 8
    @Published var toolChipBgOpacity = 0.1
    // Just under half the button height: at exactly height/2 (a true capsule)
    // the stroke path renders seam ticks at the ends; 10pt reads identically.
    @Published var overrideCornerRadius: CGFloat = 10
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
