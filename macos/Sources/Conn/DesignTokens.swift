import SwiftUI

enum DesignTokens {
    // motion
    static let summonSpring = Spring(response: 0.28, dampingRatio: 0.80)
    static let collapseSpring = Spring(response: 0.22, dampingRatio: 0.90)
    static let chipOpenDuration = 0.16
    static let chipButtonsFadeDelay = 0.06
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
    // personality
    static let aliveness = 1.0
    static let breathAmplitude = 0.015
    static let breathPeriod = 3.2
    static let squashHeightOvershoot = 0.04
    static let squashWidthOvershoot = 0.02
    static let squashWidthLeadMs = 40.0
    static let exhaleContraction = 0.02
    static let exhaleDuration = 0.22
    // palette (island, on black)
    static let islandBg = Color.black
    static let islandText = Color.white.opacity(0.92)
    static let islandTextSecondary = Color.white.opacity(0.58)
    static let islandAccent = Color(red: 0.48, green: 0.65, blue: 0.88)
    static let islandAmber = Color(red: 0.91, green: 0.63, blue: 0.24)
    static let islandGreen = Color(red: 0.30, green: 0.76, blue: 0.54)
    static let islandRed = Color(red: 0.88, green: 0.32, blue: 0.32)
    // geometry
    static let islandGrowWidth: CGFloat = 58
    static let islandContentHeight: CGFloat = 60
    static let islandCornerRadius: CGFloat = 13
    static let chipRowHeight: CGFloat = 40
}
