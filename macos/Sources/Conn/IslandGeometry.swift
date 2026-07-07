import AppKit
import CoreGraphics

struct IslandGeometry {
    let notchRect: CGRect
    private let screenFrame: CGRect

    var notchHeight: CGFloat { notchRect.height }

    private static let syntheticNotchWidth: CGFloat = 200
    private static let syntheticNotchHeightFallback: CGFloat = 32
    private static let syntheticNotchHeightRange: ClosedRange<CGFloat> = 24...40
    private static let minimumSyntheticScreenWidth: CGFloat = 1100
    private static let minimumSyntheticScreenHeight: CGFloat = 650

    init?(screenFrame: CGRect, safeTopInset: CGFloat, auxTopLeft: CGRect?, auxTopRight: CGRect?) {
        guard safeTopInset > 0,
              let left = auxTopLeft,
              let right = auxTopRight else {
            return nil
        }

        let notchX = left.maxX
        let notchWidth = right.minX - left.maxX
        let notchY = screenFrame.maxY - safeTopInset
        let notchHeight = safeTopInset

        self.notchRect = CGRect(x: notchX, y: notchY, width: notchWidth, height: notchHeight)
        self.screenFrame = screenFrame
    }

    private init(notchRect: CGRect, screenFrame: CGRect) {
        self.notchRect = notchRect
        self.screenFrame = screenFrame
    }

    // Island top edge stays flush to the screen edge; the shape grows downward
    // out of the notch. Height is the notch depth plus the content lane, so all
    // readable content lives below the physical notch and never clips into it.
    func expandedFrame(chipOpen: Bool) -> CGRect {
        var frame = notchRect.insetBy(dx: -DesignTokens.islandGrowWidth, dy: 0)
        frame.size.height = notchRect.height + DesignTokens.islandContentHeight
        frame.origin.y = screenFrame.maxY - frame.height
        if chipOpen {
            frame.size.height += DesignTokens.chipRowHeight
            frame.origin.y -= DesignTokens.chipRowHeight
        }
        return frame
    }

    static func syntheticBuiltIn(
        screenFrame: CGRect,
        topInset: CGFloat = syntheticNotchHeightFallback
    ) -> IslandGeometry? {
        guard screenFrame.width >= minimumSyntheticScreenWidth,
              screenFrame.height >= minimumSyntheticScreenHeight else {
            return nil
        }

        let width = min(syntheticNotchWidth, screenFrame.width)
        let height = clampedNotchHeight(topInset)
        let notchRect = CGRect(
            x: screenFrame.midX - width / 2,
            y: screenFrame.maxY - height,
            width: width,
            height: height
        )
        return IslandGeometry(notchRect: notchRect, screenFrame: screenFrame)
    }

    static func clampedNotchHeight(_ inset: CGFloat) -> CGFloat {
        guard inset > 0 else { return syntheticNotchHeightFallback }
        return min(max(inset, syntheticNotchHeightRange.lowerBound), syntheticNotchHeightRange.upperBound)
    }

    static func forScreen(_ screen: NSScreen) -> IslandGeometry? {
        if let geometry = IslandGeometry(
            screenFrame: screen.frame,
            safeTopInset: screen.safeAreaInsets.top,
            auxTopLeft: screen.auxiliaryTopLeftArea,
            auxTopRight: screen.auxiliaryTopRightArea
        ) {
            return geometry
        }

        if screen.localizedName.lowercased().contains("built-in") {
            let menuBarInset = screen.frame.maxY - screen.visibleFrame.maxY
            return syntheticBuiltIn(screenFrame: screen.frame, topInset: menuBarInset)
        }

        return nil
    }
}
