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
    // A card hangs below the island as its own tile, so a card height (the
    // tile as measured by IslandView) adds the gap and the tile. The summon
    // scale below ignores it: the morph scales the island, not the card.
    func expandedFrame(chipOpen: Bool, cardHeight: CGFloat = 0) -> CGRect {
        var frame = notchRect.insetBy(dx: -DesignTokens.islandGrowWidth, dy: 0)
        frame.size.height = notchRect.height + DesignTokens.islandContentHeight
        frame.origin.y = screenFrame.maxY - frame.height
        if chipOpen {
            frame.size.height += DesignTokens.chipRowHeight
            frame.origin.y -= DesignTokens.chipRowHeight
        }
        if cardHeight > 0 {
            let extra = DesignTokens.cardGap + cardHeight
            frame.size.height += extra
            frame.origin.y -= extra
        }
        return frame
    }

    // The panel for a glass style (D): the surface's
    // measured size plus room for its shadow, centered on the notch and flush
    // to the screen's top edge. The surface sizes itself inside; the panel
    // only has to contain it. A zero size (nothing laid out yet) gets the
    // widest card frame so the first layout is never clipped.
    func surfaceFrame(for size: CGSize) -> CGRect {
        let surface = size.width > 0 && size.height > 0 ? size : Self.surfaceEstimate(notchHeight: notchRect.height)
        let width = surface.width + 2 * DesignTokens.characterPanelMargin
        let height = surface.height + DesignTokens.characterPanelBottomMargin
        return CGRect(x: notchRect.midX - width / 2,
                      y: screenFrame.maxY - height,
                      width: width, height: height)
    }

    static func surfaceEstimate(notchHeight: CGFloat) -> CGSize {
        CGSize(width: DesignTokens.characterExpandedWidth,
               height: notchHeight + DesignTokens.islandContentHeight + DesignTokens.chipRowHeight)
    }

    // Scale fractions that map the expanded island back onto the bare notch
    // rect. The summon morph grows the shape from these to 1; collapse returns
    // to them, so the island visibly emerges from and retreats into the notch.
    func collapsedScale(chipOpen: Bool = false) -> (x: CGFloat, y: CGFloat) {
        let frame = expandedFrame(chipOpen: chipOpen)
        return (notchRect.width / frame.width, notchRect.height / frame.height)
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
