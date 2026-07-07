import SwiftUI

enum DesignTokens {
    // motion
    static let summonSpring = Spring(response: 0.28, dampingRatio: 0.80)
    static let collapseSpring = Spring(response: 0.22, dampingRatio: 0.90)
    static let chipOpenDuration = 0.16
    static let chipButtonsFadeDelay = 0.06
    static let chipConfirmSettleDuration = 0.12
    static let stateWordCrossfade = 0.12
    static let doneSettleDuration = 0.32
    static let doneCollapseDelay = 0.90
    static let failedCollapseDelay = 2.50
    static let refusalPulseDuration = 0.25
    static let refusalShakeMagnitude: CGFloat = 2
    static let refusalShakeCycles = 3
    static let belaySnapDuration = 0.12
    static let contentStaggerDelay = 0.08
    static let toastDuration = 3.0
    static let thinkingEllipsisPeriod = 1.2
    static let thinkingDotOpacityFloor = 0.25
    // personality
    static let aliveness = 1.0
    static let breathAmplitude = 0.015
    static let breathPeriod = 3.2
    static let breathFrameInterval = 1.0 / 30.0
    static let squashHeightOvershoot = 0.04
    static let squashWidthOvershoot = 0.02
    static let squashWidthLeadMs = 40.0
    static let exhaleContraction = 0.02
    static let exhaleDuration = 0.22
    // derived personality values. aliveness scales every behavior: at 0 the
    // summon springs go critically damped, the width lead vanishes, and breath
    // and exhale render flat, leaving a fully static island.
    static let squashWidthLead = squashWidthLeadMs / 1000.0 * aliveness
    static let summonWidthSpring = springOvershooting(
        squashWidthOvershoot * aliveness, response: summonSpring.response)
    static let summonHeightSpring = springOvershooting(
        squashHeightOvershoot * aliveness, response: summonSpring.response)

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
    static let islandBg = Color.black
    static let islandText = Color.white.opacity(0.92)
    static let islandTextSecondary = Color.white.opacity(0.58)
    // lilac #C3B1E1: the signature color (listening waveform and ring, the
    // thinking word). Clears 4.5:1 on black by a wide margin (about 10.7:1).
    static let islandAccent = Color(red: 0.765, green: 0.694, blue: 0.882)
    static let islandAmber = Color(red: 0.91, green: 0.63, blue: 0.24)
    static let islandGreen = Color(red: 0.30, green: 0.76, blue: 0.54)
    static let islandRed = Color(red: 0.88, green: 0.32, blue: 0.32)
    // gold #E0C060: budget hold only. Money and caution without failure;
    // lighter and yellower than the amber approval dot. About 11.9:1 on black.
    static let islandGold = Color(red: 0.878, green: 0.753, blue: 0.376)
    // frozen panel surface (non-notch fallback; values preserved verbatim
    // from the panel era when WaveformView rejoined the guard at I7)
    static let panelBarSpring = Spring(response: 0.15, dampingRatio: 0.75)
    static let panelPhaseCrossfade = 0.25
    // geometry
    static let islandGrowWidth: CGFloat = 58
    static let islandContentHeight: CGFloat = 60
    static let islandCornerRadius: CGFloat = 13
    static let chipRowHeight: CGFloat = 40
    static let chipButtonMinHeight: CGFloat = 24
    static let chipButtonCornerRadius: CGFloat = 6
    static let toolChipHeight: CGFloat = 20
    static let toolChipPaddingH: CGFloat = 8
    static let toolChipBgOpacity = 0.10
    // Just under half the button height: at exactly height/2 (a true capsule)
    // the stroke path renders seam ticks at the ends; 10pt reads identically.
    static let overrideCornerRadius: CGFloat = 10
}
