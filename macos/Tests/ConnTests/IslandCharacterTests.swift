import AppKit
import XCTest
@testable import Conn

// Style D (Character) is the live default. These pin what makes it safe to
// ship as one: the panel is sized from the surface it hosts (so cards and
// approvals are never clipped), it stays centered on the notch and flush to
// the screen's top edge, a shrinking surface is never cut off mid-morph, and
// the menu-bar style choice only ever selects a shipped style.
@MainActor
final class IslandCharacterTests: XCTestCase {
    private let screenFrame = CGRect(x: 0, y: 0, width: 1000, height: 700)

    private func geometry() throws -> IslandGeometry {
        try XCTUnwrap(IslandGeometry(
            screenFrame: screenFrame,
            safeTopInset: 30,
            auxTopLeft: CGRect(x: 0, y: 670, width: 400, height: 30),
            auxTopRight: CGRect(x: 600, y: 670, width: 400, height: 30)))
    }

    func testCharacterIsTheCompiledDefault() {
        XCTAssertEqual(DesignTokenStore().islandStyle, .d)
    }

    func testSurfaceFrameContainsTheSurfaceCenteredOnTheNotchAndFlushToTop() throws {
        let g = try geometry()
        let surface = CGSize(width: 360, height: 310)
        let frame = g.surfaceFrame(for: surface)
        XCTAssertEqual(frame.midX, g.notchRect.midX, accuracy: 0.001)
        XCTAssertEqual(frame.maxY, screenFrame.maxY, accuracy: 0.001)
        XCTAssertEqual(frame.width, surface.width + 2 * DesignTokens.characterPanelMargin, accuracy: 0.001)
        XCTAssertEqual(frame.height, surface.height + DesignTokens.characterPanelBottomMargin, accuracy: 0.001)
    }

    func testUnmeasuredSurfaceGetsRoomForTheWidestCard() throws {
        let g = try geometry()
        let frame = g.surfaceFrame(for: .zero)
        XCTAssertGreaterThanOrEqual(frame.width, DesignTokens.characterExpandedWidth)
        XCTAssertGreaterThan(frame.height, g.notchHeight + DesignTokens.islandContentHeight)
        XCTAssertEqual(frame.maxY, screenFrame.maxY, accuracy: 0.001)
    }

    func testFitterGrowsAtOnceAndDefersTheShrink() {
        let panel = IslandPanel(
            contentRect: NSRect(x: 100, y: 100, width: 300, height: 100),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: false)
        panel.orderFrontRegardless()
        defer { panel.orderOut(nil) }
        guard panel.isVisible else { return } // no window server in this run
        let fitter = GlassPanelFitter(panel: panel)

        let big = NSRect(x: 50, y: 20, width: 400, height: 180)
        fitter.fit({ big }, immediately: false)
        XCTAssertEqual(panel.frame, big, "growth must land before the surface springs open")

        let small = NSRect(x: 100, y: 100, width: 300, height: 100)
        fitter.fit({ small }, immediately: false)
        XCTAssertEqual(panel.frame, big, "a shrink waits for the morph so nothing clips")

        let settled = expectation(description: "shrink lands after the morph settles")
        DispatchQueue.main.asyncAfter(
            deadline: .now() + DesignTokens.glassMorphSpring.settlingDuration + 0.3
        ) { settled.fulfill() }
        wait(for: [settled], timeout: DesignTokens.glassMorphSpring.settlingDuration + 2)
        XCTAssertEqual(panel.frame, small)
    }

    func testFitterAppliesImmediatelyWhenAsked() {
        let panel = IslandPanel(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 100),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered, defer: true)
        let fitter = GlassPanelFitter(panel: panel)
        let target = NSRect(x: 10, y: 10, width: 200, height: 80)
        fitter.fit({ target }, immediately: true)
        XCTAssertEqual(panel.frame, target)
    }

    func testStylePreferenceRoundTripsShippedStylesOnly() throws {
        let suite = "conn.tests.islandStyle.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        XCTAssertNil(IslandStylePreference.load(defaults))
        IslandStylePreference.save(.classic, defaults)
        XCTAssertEqual(IslandStylePreference.load(defaults), .classic)
        IslandStylePreference.save(.d, defaults)
        XCTAssertEqual(IslandStylePreference.load(defaults), .d)

        // A prototype or junk value never becomes the live surface.
        defaults.set(IslandStyle.b.rawValue, forKey: IslandStylePreference.defaultsKey)
        XCTAssertNil(IslandStylePreference.load(defaults))
        defaults.set("nonsense", forKey: IslandStylePreference.defaultsKey)
        XCTAssertNil(IslandStylePreference.load(defaults))
    }

    func testCharacterInkKeepsTextWhiteAndColorInTheDetails() {
        let ink = IslandInk.character
        // Done words read in the primary text color; only the check is lime.
        XCTAssertEqual(ink.color(for: .done, speech: false), ink.primary)
        XCTAssertNotEqual(ink.done, ink.primary)
        // Approve is filled, Deny is not: one primary action.
        XCTAssertNotEqual(ink.approveFill, ink.well)
    }
}
