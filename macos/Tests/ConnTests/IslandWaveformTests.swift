import AppKit
import SwiftUI
import XCTest
@testable import Conn

// The motion policy: the island waveform's timeline runs only in the four
// active phases. This hosts the real view in an offscreen window and counts
// timeline ticks; listening is the positive control proving the harness can
// observe ticks, awaiting_approval must stay at zero (nothing animates while
// a chip is open).
@MainActor
final class IslandWaveformTests: XCTestCase {
    private func ticks(phase: String, for duration: TimeInterval) -> Int {
        let window = NSWindow(
            contentRect: NSRect(x: -3000, y: -3000, width: 200, height: 60),
            styleMask: [.borderless],
            backing: .buffered, defer: false)
        window.contentView = NSHostingView(
            rootView: IslandWaveform(level: 0.5, phase: phase))
        window.orderFrontRegardless()
        defer {
            // Kill the hosting view too: an ordered-out window's TimelineView
            // can keep ticking and bleed counts into the next measurement.
            window.contentView = nil
            window.orderOut(nil)
        }

        IslandWaveform.tickCount = 0
        RunLoop.main.run(until: Date(timeIntervalSinceNow: duration))
        return IslandWaveform.tickCount
    }

    func testApprovalNeverTicksAndListeningDoes() {
        let approval = ticks(phase: "awaiting_approval", for: 0.4)
        XCTAssertEqual(approval, 0,
            "no timeline tick may fire while a chip is open")

        let listening = ticks(phase: "listening", for: 0.4)
        XCTAssertGreaterThan(listening, 0,
            "positive control: the timeline must tick while listening")
    }
}
