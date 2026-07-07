import XCTest
@testable import Conn

final class IslandGeometryTests: XCTestCase {
    private let screenFrame = CGRect(x: 0, y: 0, width: 1000, height: 700)
    private let safeTopInset: CGFloat = 30
    private lazy var auxTopLeft = CGRect(x: 0, y: screenFrame.height - safeTopInset, width: 400, height: safeTopInset)
    private lazy var auxTopRight = CGRect(x: 600, y: screenFrame.height - safeTopInset, width: 400, height: safeTopInset)

    func testNotchRectCenteredBetweenAuxAreas() {
        let geometry = IslandGeometry(
            screenFrame: screenFrame,
            safeTopInset: safeTopInset,
            auxTopLeft: auxTopLeft,
            auxTopRight: auxTopRight
        )

        XCTAssertNotNil(geometry)
        let expected = CGRect(
            x: auxTopLeft.maxX,
            y: screenFrame.maxY - safeTopInset,
            width: auxTopRight.minX - auxTopLeft.maxX,
            height: safeTopInset
        )
        XCTAssertEqual(geometry?.notchRect, expected)
    }

    func testNoNotchReturnsNil() {
        let geometry = IslandGeometry(
            screenFrame: screenFrame,
            safeTopInset: 0,
            auxTopLeft: nil,
            auxTopRight: nil
        )
        XCTAssertNil(geometry)
    }

    func testSyntheticBuiltInFallbackCreatesCenteredNotchWhenAppKitWithholdsAuxAreas() {
        let builtInFrame = CGRect(x: 0, y: 0, width: 1440, height: 900)
        let geometry = IslandGeometry.syntheticBuiltIn(screenFrame: builtInFrame)

        XCTAssertNotNil(geometry)
        guard let geometry else { return }
        XCTAssertEqual(geometry.notchRect.midX, builtInFrame.midX, accuracy: 0.001)
        XCTAssertEqual(geometry.notchRect.maxY, builtInFrame.maxY, accuracy: 0.001)
        XCTAssertGreaterThan(geometry.notchRect.width, 0)
        XCTAssertGreaterThan(geometry.notchRect.height, 0)
    }

    func testSyntheticBuiltInAdoptsMeasuredMenuBarHeight() {
        let builtInFrame = CGRect(x: 0, y: 0, width: 1440, height: 900)
        let geometry = IslandGeometry.syntheticBuiltIn(screenFrame: builtInFrame, topInset: 30)
        guard let geometry else {
            XCTFail("expected non-nil geometry")
            return
        }
        XCTAssertEqual(geometry.notchRect.height, 30, accuracy: 0.001)
        XCTAssertEqual(geometry.notchHeight, 30, accuracy: 0.001)
    }

    func testSyntheticNotchHeightClampsToNotchRange() {
        // A stray oversized inset (or zero) must not produce a giant black slab.
        XCTAssertEqual(IslandGeometry.clampedNotchHeight(62), CGFloat(40), accuracy: CGFloat(0.001))
        XCTAssertEqual(IslandGeometry.clampedNotchHeight(10), CGFloat(24), accuracy: CGFloat(0.001))
        XCTAssertEqual(IslandGeometry.clampedNotchHeight(0), CGFloat(32), accuracy: CGFloat(0.001))
    }

    func testExpandedFrameKeepsContentBelowTheNotch() {
        let geometry = IslandGeometry.syntheticBuiltIn(
            screenFrame: CGRect(x: 0, y: 0, width: 1440, height: 900),
            topInset: 30
        )
        guard let geometry else {
            XCTFail("expected non-nil geometry")
            return
        }
        let frame = geometry.expandedFrame(chipOpen: false)
        XCTAssertEqual(frame.maxY, 900, accuracy: 0.001)
        XCTAssertEqual(frame.height, geometry.notchRect.height + DesignTokens.islandContentHeight, accuracy: 0.001)
        // The content lane below the notch must be tall enough to hold the
        // waveform and caption without clipping.
        XCTAssertGreaterThanOrEqual(frame.height - geometry.notchRect.height, 52)
    }

    func testCollapsedScaleMapsExpandedFrameBackOntoNotch() {
        let geometry = IslandGeometry.syntheticBuiltIn(
            screenFrame: CGRect(x: 0, y: 0, width: 1440, height: 900),
            topInset: 30
        )
        guard let geometry else {
            XCTFail("expected non-nil geometry")
            return
        }

        let frame = geometry.expandedFrame(chipOpen: false)
        let scale = geometry.collapsedScale()
        XCTAssertEqual(frame.width * scale.x, geometry.notchRect.width, accuracy: 0.001)
        XCTAssertEqual(frame.height * scale.y, geometry.notchRect.height, accuracy: 0.001)
        XCTAssertLessThan(scale.x, 1)
        XCTAssertLessThan(scale.y, 1)
    }

    func testMainBuiltInScreenGetsIslandGeometry() throws {
        let screen = try XCTUnwrap(NSScreen.main)
        guard screen.localizedName.lowercased().contains("built-in") else { return }

        XCTAssertNotNil(IslandGeometry.forScreen(screen))
    }

    func testExpandedFrameChipClosedGrowsAndPinsToTop() {
        let geometry = IslandGeometry(
            screenFrame: screenFrame,
            safeTopInset: safeTopInset,
            auxTopLeft: auxTopLeft,
            auxTopRight: auxTopRight
        )
        guard let geometry else {
            XCTFail("expected non-nil geometry")
            return
        }

        let expected = CGRect(
            x: geometry.notchRect.origin.x - DesignTokens.islandGrowWidth,
            y: screenFrame.maxY - (geometry.notchRect.height + DesignTokens.islandContentHeight),
            width: geometry.notchRect.width + DesignTokens.islandGrowWidth * 2,
            height: geometry.notchRect.height + DesignTokens.islandContentHeight
        )
        XCTAssertEqual(geometry.expandedFrame(chipOpen: false), expected)
    }

    func testExpandedFrameChipOpenAddsChipRowBelow() {
        let geometry = IslandGeometry(
            screenFrame: screenFrame,
            safeTopInset: safeTopInset,
            auxTopLeft: auxTopLeft,
            auxTopRight: auxTopRight
        )
        guard let geometry else {
            XCTFail("expected non-nil geometry")
            return
        }

        let closed = geometry.expandedFrame(chipOpen: false)
        let expected = CGRect(
            x: closed.origin.x,
            y: closed.origin.y - DesignTokens.chipRowHeight,
            width: closed.width,
            height: closed.height + DesignTokens.chipRowHeight
        )
        XCTAssertEqual(geometry.expandedFrame(chipOpen: true), expected)
        XCTAssertEqual(geometry.expandedFrame(chipOpen: true).maxY, screenFrame.maxY)
    }
}
