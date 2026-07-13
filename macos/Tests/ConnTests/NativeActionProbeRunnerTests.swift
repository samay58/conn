import CoreGraphics
import XCTest
@testable import Conn

final class NativeActionProbeRunnerTests: XCTestCase {
    func testFrontmostVisibleOwnerSkipsOverlayAndInvisibleWindows() {
        let windows: [[String: Any]] = [
            [
                kCGWindowOwnerPID as String: NSNumber(value: 11),
                kCGWindowLayer as String: NSNumber(value: 3),
                kCGWindowAlpha as String: NSNumber(value: 1),
                kCGWindowIsOnscreen as String: true,
                kCGWindowBounds as String: ["Width": 100.0, "Height": 100.0],
            ],
            [
                kCGWindowOwnerPID as String: NSNumber(value: 12),
                kCGWindowLayer as String: NSNumber(value: 0),
                kCGWindowAlpha as String: NSNumber(value: 0),
                kCGWindowIsOnscreen as String: true,
                kCGWindowBounds as String: ["Width": 100.0, "Height": 100.0],
            ],
            [
                kCGWindowOwnerPID as String: NSNumber(value: 13),
                kCGWindowLayer as String: NSNumber(value: 0),
                kCGWindowAlpha as String: NSNumber(value: 1),
                kCGWindowIsOnscreen as String: true,
                kCGWindowBounds as String: ["Width": 800.0, "Height": 600.0],
            ],
        ]

        XCTAssertEqual(
            NativeActionProbeRunner.frontmostVisibleOwnerPID(from: windows),
            13
        )
    }
}
