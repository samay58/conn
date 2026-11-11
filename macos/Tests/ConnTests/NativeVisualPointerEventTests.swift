import CoreGraphics
import XCTest
@testable import Conn

final class NativeVisualPointerEventTests: XCTestCase {
    private let point = CGPoint(x: 412, y: 287)

    func testScrollLandsAtTheGroundedPoint() throws {
        let events = ScreenCaptureVisualProvider.pointerEvents(for: .scroll, at: point)
        XCTAssertEqual(events.count, NativePointerInput.scroll.eventCount)
        let scroll = try XCTUnwrap(events.first ?? nil)
        XCTAssertEqual(scroll.type, .scrollWheel)
        XCTAssertEqual(scroll.location.x, point.x, accuracy: 0.5)
        XCTAssertEqual(scroll.location.y, point.y, accuracy: 0.5)
    }

    func testEveryInputLandsAtTheGroundedPoint() throws {
        for input in [NativePointerInput.primaryClick, .doubleClick, .rightClick, .scroll, .scrollUp] {
            let events = ScreenCaptureVisualProvider.pointerEvents(for: input, at: point)
            XCTAssertEqual(events.count, input.eventCount, input.rawValue)
            for event in events {
                let event = try XCTUnwrap(event, input.rawValue)
                XCTAssertEqual(event.location.x, point.x, accuracy: 0.5, input.rawValue)
                XCTAssertEqual(event.location.y, point.y, accuracy: 0.5, input.rawValue)
            }
        }
    }

    func testScrollDirectionFollowsTheGoal() {
        XCTAssertEqual(NativeActionCompiler.visualPointerInput(goal: "scroll up", label: ""), .scrollUp)
        XCTAssertEqual(NativeActionCompiler.visualPointerInput(goal: "scroll to the top", label: ""), .scrollUp)
        XCTAssertEqual(NativeActionCompiler.visualPointerInput(goal: "scroll down", label: ""), .scroll)
        XCTAssertEqual(NativeActionCompiler.visualPointerInput(goal: "scroll this list", label: ""), .scroll)
    }

    func testScrollUpAndDownMoveOppositeWays() throws {
        let down = try XCTUnwrap(ScreenCaptureVisualProvider.pointerEvents(for: .scroll, at: point).first ?? nil)
        let up = try XCTUnwrap(ScreenCaptureVisualProvider.pointerEvents(for: .scrollUp, at: point).first ?? nil)
        XCTAssertLessThan(down.getIntegerValueField(.scrollWheelEventDeltaAxis1), 0)
        XCTAssertGreaterThan(up.getIntegerValueField(.scrollWheelEventDeltaAxis1), 0)
    }
}
