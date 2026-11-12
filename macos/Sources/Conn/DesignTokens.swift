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
    @Published var toolCapsuleShowDelay = 0.25
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
    // island style (IslandGlassStyles.swift). D, Character, is the live
    // default; classic stays selectable from the menu bar and the preview
    // picker, and A, B and C remain preview-only prototypes. Glass is static
    // per state: only transform and opacity animate, never blur or glass
    // parameters.
    @Published var islandStyle = IslandStyle.d
    @Published var glassMorphSpring = Spring(response: 0.3, dampingRatio: 0.86)
    @Published var glassEnterDuration = 0.22
    @Published var glassRimOpacity = 0.22
    @Published var glassInnerLightOpacity = 0.05
    @Published var glassSmokeOpacity = 0.45
    // deep lilac: the accent on light glass, where #C3B1E1 washes out.
    @Published var glassAccentDeepRGB = PaletteColor(red: 0.42, green: 0.33, blue: 0.62)
    let glassRimWidth: CGFloat = 1.5
    let glassFusedCornerRadius: CGFloat = 20
    let glassFusedWidth: CGFloat = 340
    let glassCapsuleHeight: CGFloat = 40
    let glassCardCornerRadius: CGFloat = 24
    let glassCardWidth: CGFloat = 356
    let glassNotchGap: CGFloat = 8
    let glassEarWidth: CGFloat = 104
    let glassPillCornerRadius: CGFloat = 12
    let glassButtonHeight: CGFloat = 28
    // cards (the island detail surface, src/conn/cards.py): a card that
    // does not persist retires after cardLinger, a settled reply after the
    // shorter cardSettledLinger.
    @Published var cardLinger = 12.0
    @Published var cardSettledLinger = 2.5
    @Published var cardFadeDuration = 0.2
    let cardGap: CGFloat = 8
    let cardCornerRadius: CGFloat = 16
    let cardPadding: CGFloat = 14
    // icon identity (macos/icon/conn-icon.svg), the palette style d is built
    // on: ink background, deep pill, electric lime (eyes, live, listening),
    // lilac (voice, rim tint), hot pink (voice end, approve, attention), and a
    // white rim highlight fading to a lilac lower edge.
    @Published var iconInkTopRGB = PaletteColor(red: 0.1686, green: 0.149, blue: 0.251)
    @Published var iconInkBottomRGB = PaletteColor(red: 0.0706, green: 0.0627, blue: 0.0941)
    @Published var iconPillTopRGB = PaletteColor(red: 0.149, green: 0.1373, blue: 0.1843)
    @Published var iconPillBottomRGB = PaletteColor(red: 0.0196, green: 0.0196, blue: 0.0275)
    @Published var iconLimeRGB = PaletteColor(red: 0.8588, green: 1.0, blue: 0.2392)
    @Published var iconLilacRGB = PaletteColor(red: 0.8157, green: 0.549, blue: 1.0)
    @Published var iconPinkRGB = PaletteColor(red: 0.949, green: 0.4824, blue: 0.851)
    @Published var iconRimTopOpacity = 0.85
    @Published var iconRimMidOpacity = 0.08
    @Published var iconRimLilacOpacity = 0.6
    // style d: the done wink, one eye closing on an ease-out.
    @Published var characterWinkDuration = 0.2
    // style d (Character), the live default: the icon's pill hanging from
    // the notch. Geometry is fixed; the morph between compact and card
    // widths keeps one corner radius so no path is re-rounded mid-spring.
    let characterExpandedWidth: CGFloat = 360
    let characterCornerRadius: CGFloat = 22
    let characterPaddingH: CGFloat = 18
    let characterPaddingTop: CGFloat = 8
    let characterPaddingBottom: CGFloat = 14
    let characterSectionGap: CGFloat = 12
    let characterCaptionGap: CGFloat = 7
    let characterCaptionMaxWidth: CGFloat = 288
    let characterFaceGap: CGFloat = 12
    // the eyes: the icon's 64x112 eye and its wide set, at island scale
    // (its white glint is dropped: at this size it vanishes into the lime).
    let characterEyeWidth: CGFloat = 5.5
    let characterEyeHeight: CGFloat = 10
    let characterEyeGap: CGFloat = 8
    let characterWinkStroke: CGFloat = 2.25
    let characterFocusedEyeScale: CGFloat = 0.6
    let characterVoiceScale: CGFloat = 0.8
    // the body: a glass rim around a black core, a hairline sheen that runs
    // to a lilac lower edge, and a soft shadow drawn only outside the shape.
    let characterRimWidth: CGFloat = 1.5
    let characterSheenWidth: CGFloat = 0.75
    let characterTopFade: CGFloat = 12
    let characterShadowRadius: CGFloat = 14
    let characterShadowY: CGFloat = 5
    let characterPanelMargin: CGFloat = 20
    let characterPanelBottomMargin: CGFloat = 28
    let characterFloatingTopGap: CGFloat = 10
    let characterFloatingCollapsedScale: CGFloat = 0.96
    let characterCapsuleHeight: CGFloat = 22
    let characterCapsulePaddingH: CGFloat = 10
    let characterOverrideHeight: CGFloat = 24
    let characterCloseSize: CGFloat = 18
    let characterCloseHitSize: CGFloat = 28
    @Published var characterTextOpacity = 0.94
    @Published var characterTextSecondaryOpacity = 0.6
    @Published var characterWellOpacity = 0.08
    @Published var characterHairlineOpacity = 0.09
    @Published var characterGlassTintOpacity = 0.4
    @Published var characterBodyBottomRGB = PaletteColor(red: 0.055, green: 0.051, blue: 0.075)
    @Published var characterSheenSideOpacity = 0.14
    @Published var characterSheenTopOpacity = 0.28
    @Published var characterSheenLilacOpacity = 0.5
    @Published var characterShadowOpacity = 0.3
    @Published var characterRestingVoiceOpacity = 0.4
    @Published var characterFocusedEyeOpacity = 0.75
    @Published var characterLowEyeOpacity = 0.35
    @Published var characterPressScale = 0.96
    @Published var characterPressDuration = 0.12
    let characterWinkWidth: CGFloat = 7.5
    let characterWinkHeight: CGFloat = 3.5
    let characterWinkRestScale: CGFloat = 0.6
    @Published var characterCoreBottomOpacity = 0.9
    // voice line (WaveformEngine.swift): the island waveform, tuned against
    // real speech with `Conn --playtest-waveform`. Levels arrive at 25 Hz;
    // the engine integrates on a fixed 120 Hz step so the feel is the same
    // at any display rate. Times are seconds; amplitudes are 0...1 of the
    // bar's travel from waveMinHeight to waveMaxHeight.
    let waveBarCount = 15
    let waveBarWidth: CGFloat = 3
    let waveBarSpacing: CGFloat = 3
    let waveMinHeight: CGFloat = 3
    let waveMaxHeight: CGFloat = 24
    let waveFrameInterval = 1.0 / 60.0
    let waveStepInterval = 1.0 / 120.0
    let waveAttack = 0.025
    let waveRelease = 0.1
    let waveStaleAfter = 0.15
    let waveNoiseFloor = 0.012
    let waveGamma = 0.65
    let waveKnee = 0.7
    let waveEnvelopeFalloff = 1.3
    let waveEnvelopeFloor = 0.3
    let waveRippleDelay = 0.028
    let waveRippleSkew = 0.35
    let waveShimmer = 0.12
    let waveShimmerRate = 1.3
    let waveBreathFloor = 0.08
    let waveBreathDepth = 0.22
    let waveBreathPeriod = 2.8
    let waveBreathTravel = 0.5
    let waveThinkBase = 0.1
    let waveThinkCrest = 0.38
    let waveThinkPeriod = 1.8
    let waveThinkWidth = 2.0
    let waveRestAmplitude = 0.05
    let waveBrightnessFloor = 0.6
    let waveMorphDuration = 0.28
    let waveVoicedThreshold = 0.2
    let waveReducedAttack = 0.08
    let waveReducedRelease = 0.3
    let waveEyeAttack = 0.12
    let waveEyeRelease = 0.35
    let characterBlinkClose = 0.07
    let characterBlinkOpen = 0.13
    let characterBlinkClosedScale: CGFloat = 0.12
    let characterBlinkAfterPause = 0.28
    let characterBlinkMinGap = 1.8
    let characterBlinkWhileWaiting = 3.4
    let characterNodLift: CGFloat = 1.2
    let characterGlanceShift: CGFloat = 0.8
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
    static var toolCapsuleShowDelay: Double { current.toolCapsuleShowDelay }
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
    // island style prototypes
    static var islandStyle: IslandStyle { current.islandStyle }
    static var glassMorphSpring: Spring { current.glassMorphSpring }
    static var glassEnterDuration: Double { current.glassEnterDuration }
    static var glassRimOpacity: Double { current.glassRimOpacity }
    static var glassInnerLightOpacity: Double { current.glassInnerLightOpacity }
    static var glassSmokeOpacity: Double { current.glassSmokeOpacity }
    static var glassAccentDeep: Color { current.glassAccentDeepRGB.color }
    static var glassRimWidth: CGFloat { current.glassRimWidth }
    static var glassFusedCornerRadius: CGFloat { current.glassFusedCornerRadius }
    static var glassFusedWidth: CGFloat { current.glassFusedWidth }
    static var glassCapsuleHeight: CGFloat { current.glassCapsuleHeight }
    static var glassCardCornerRadius: CGFloat { current.glassCardCornerRadius }
    static var glassCardWidth: CGFloat { current.glassCardWidth }
    static var glassNotchGap: CGFloat { current.glassNotchGap }
    static var glassEarWidth: CGFloat { current.glassEarWidth }
    static var glassPillCornerRadius: CGFloat { current.glassPillCornerRadius }
    static var glassButtonHeight: CGFloat { current.glassButtonHeight }
    // cards
    static var cardLinger: Double { current.cardLinger }
    static var cardSettledLinger: Double { current.cardSettledLinger }
    static var cardFadeDuration: Double { current.cardFadeDuration }
    static var cardGap: CGFloat { current.cardGap }
    static var cardCornerRadius: CGFloat { current.cardCornerRadius }
    static var cardPadding: CGFloat { current.cardPadding }
    // icon identity
    static var iconInkTop: Color { current.iconInkTopRGB.color }
    static var iconInkBottom: Color { current.iconInkBottomRGB.color }
    static var iconPillTop: Color { current.iconPillTopRGB.color }
    static var iconPillBottom: Color { current.iconPillBottomRGB.color }
    static var iconLime: Color { current.iconLimeRGB.color }
    static var iconLilac: Color { current.iconLilacRGB.color }
    static var iconPink: Color { current.iconPinkRGB.color }
    static var iconRimTopOpacity: Double { current.iconRimTopOpacity }
    static var iconRimMidOpacity: Double { current.iconRimMidOpacity }
    static var iconRimLilacOpacity: Double { current.iconRimLilacOpacity }
    static var characterWinkDuration: Double { current.characterWinkDuration }
    // style d (Character)
    static var characterExpandedWidth: CGFloat { current.characterExpandedWidth }
    static var characterCornerRadius: CGFloat { current.characterCornerRadius }
    static var characterPaddingH: CGFloat { current.characterPaddingH }
    static var characterPaddingTop: CGFloat { current.characterPaddingTop }
    static var characterPaddingBottom: CGFloat { current.characterPaddingBottom }
    static var characterSectionGap: CGFloat { current.characterSectionGap }
    static var characterCaptionGap: CGFloat { current.characterCaptionGap }
    static var characterCaptionMaxWidth: CGFloat { current.characterCaptionMaxWidth }
    static var characterFaceGap: CGFloat { current.characterFaceGap }
    static var characterEyeWidth: CGFloat { current.characterEyeWidth }
    static var characterEyeHeight: CGFloat { current.characterEyeHeight }
    static var characterEyeGap: CGFloat { current.characterEyeGap }
    static var characterWinkStroke: CGFloat { current.characterWinkStroke }
    static var characterFocusedEyeScale: CGFloat { current.characterFocusedEyeScale }
    static var characterVoiceScale: CGFloat { current.characterVoiceScale }
    static var characterRimWidth: CGFloat { current.characterRimWidth }
    static var characterSheenWidth: CGFloat { current.characterSheenWidth }
    static var characterTopFade: CGFloat { current.characterTopFade }
    static var characterShadowRadius: CGFloat { current.characterShadowRadius }
    static var characterShadowY: CGFloat { current.characterShadowY }
    static var characterPanelMargin: CGFloat { current.characterPanelMargin }
    static var characterPanelBottomMargin: CGFloat { current.characterPanelBottomMargin }
    static var characterFloatingTopGap: CGFloat { current.characterFloatingTopGap }
    static var characterFloatingCollapsedScale: CGFloat { current.characterFloatingCollapsedScale }
    static var characterCapsuleHeight: CGFloat { current.characterCapsuleHeight }
    static var characterCapsulePaddingH: CGFloat { current.characterCapsulePaddingH }
    static var characterOverrideHeight: CGFloat { current.characterOverrideHeight }
    static var characterCloseSize: CGFloat { current.characterCloseSize }
    static var characterCloseHitSize: CGFloat { current.characterCloseHitSize }
    static var characterTextOpacity: Double { current.characterTextOpacity }
    static var characterTextSecondaryOpacity: Double { current.characterTextSecondaryOpacity }
    static var characterWellOpacity: Double { current.characterWellOpacity }
    static var characterHairlineOpacity: Double { current.characterHairlineOpacity }
    static var characterGlassTintOpacity: Double { current.characterGlassTintOpacity }
    static var characterBodyBottom: Color { current.characterBodyBottomRGB.color }
    static var characterSheenSideOpacity: Double { current.characterSheenSideOpacity }
    static var characterSheenTopOpacity: Double { current.characterSheenTopOpacity }
    static var characterSheenLilacOpacity: Double { current.characterSheenLilacOpacity }
    static var characterShadowOpacity: Double { current.characterShadowOpacity }
    static var characterRestingVoiceOpacity: Double { current.characterRestingVoiceOpacity }
    static var characterFocusedEyeOpacity: Double { current.characterFocusedEyeOpacity }
    static var characterLowEyeOpacity: Double { current.characterLowEyeOpacity }
    static var characterPressScale: Double { current.characterPressScale }
    static var characterPressDuration: Double { current.characterPressDuration }
    static var characterWinkWidth: CGFloat { current.characterWinkWidth }
    static var characterWinkHeight: CGFloat { current.characterWinkHeight }
    static var characterWinkRestScale: CGFloat { current.characterWinkRestScale }
    static var characterCoreBottomOpacity: Double { current.characterCoreBottomOpacity }
    // voice line
    static var waveBarCount: Int { current.waveBarCount }
    static var waveBarWidth: CGFloat { current.waveBarWidth }
    static var waveBarSpacing: CGFloat { current.waveBarSpacing }
    static var waveMinHeight: CGFloat { current.waveMinHeight }
    static var waveMaxHeight: CGFloat { current.waveMaxHeight }
    static var waveFrameInterval: Double { current.waveFrameInterval }
    static var waveStepInterval: Double { current.waveStepInterval }
    static var waveAttack: Double { current.waveAttack }
    static var waveRelease: Double { current.waveRelease }
    static var waveStaleAfter: Double { current.waveStaleAfter }
    static var waveNoiseFloor: Double { current.waveNoiseFloor }
    static var waveGamma: Double { current.waveGamma }
    static var waveKnee: Double { current.waveKnee }
    static var waveEnvelopeFalloff: Double { current.waveEnvelopeFalloff }
    static var waveEnvelopeFloor: Double { current.waveEnvelopeFloor }
    static var waveRippleDelay: Double { current.waveRippleDelay }
    static var waveRippleSkew: Double { current.waveRippleSkew }
    static var waveShimmer: Double { current.waveShimmer }
    static var waveShimmerRate: Double { current.waveShimmerRate }
    static var waveBreathFloor: Double { current.waveBreathFloor }
    static var waveBreathDepth: Double { current.waveBreathDepth }
    static var waveBreathPeriod: Double { current.waveBreathPeriod }
    static var waveBreathTravel: Double { current.waveBreathTravel }
    static var waveThinkBase: Double { current.waveThinkBase }
    static var waveThinkCrest: Double { current.waveThinkCrest }
    static var waveThinkPeriod: Double { current.waveThinkPeriod }
    static var waveThinkWidth: Double { current.waveThinkWidth }
    static var waveRestAmplitude: Double { current.waveRestAmplitude }
    static var waveBrightnessFloor: Double { current.waveBrightnessFloor }
    static var waveMorphDuration: Double { current.waveMorphDuration }
    static var waveVoicedThreshold: Double { current.waveVoicedThreshold }
    static var waveReducedAttack: Double { current.waveReducedAttack }
    static var waveReducedRelease: Double { current.waveReducedRelease }
    static var waveEyeAttack: Double { current.waveEyeAttack }
    static var waveEyeRelease: Double { current.waveEyeRelease }
    static var characterBlinkClose: Double { current.characterBlinkClose }
    static var characterBlinkOpen: Double { current.characterBlinkOpen }
    static var characterBlinkClosedScale: CGFloat { current.characterBlinkClosedScale }
    static var characterBlinkAfterPause: Double { current.characterBlinkAfterPause }
    static var characterBlinkMinGap: Double { current.characterBlinkMinGap }
    static var characterBlinkWhileWaiting: Double { current.characterBlinkWhileWaiting }
    static var characterNodLift: CGFloat { current.characterNodLift }
    static var characterGlanceShift: CGFloat { current.characterGlanceShift }
}
