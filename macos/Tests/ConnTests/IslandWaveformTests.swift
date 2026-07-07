import AppKit
import SwiftUI
import XCTest
@testable import Conn

// The motion policy: three gated timelines, none ticking outside its phase.
// The island waveform's timeline runs only in the four active phases, and the
// thinking ellipsis runs only in thinking. Each test hosts the real view in
// an offscreen window and counts timeline ticks; the in-phase render is the
// positive control proving the harness can observe ticks.
@MainActor
final class IslandWaveformTests: XCTestCase {
    private func host<V: View>(_ view: V, for duration: TimeInterval, reset: () -> Void, count: () -> Int) -> Int {
        let window = NSWindow(
            contentRect: NSRect(x: -3000, y: -3000, width: 200, height: 60),
            styleMask: [.borderless],
            backing: .buffered, defer: false)
        window.contentView = NSHostingView(rootView: view)
        window.orderFrontRegardless()
        defer {
            // Kill the hosting view too: an ordered-out window's TimelineView
            // can keep ticking and bleed counts into the next measurement.
            window.contentView = nil
            window.orderOut(nil)
        }

        reset()
        RunLoop.main.run(until: Date(timeIntervalSinceNow: duration))
        return count()
    }

    private func ticks(phase: String, for duration: TimeInterval) -> Int {
        host(IslandWaveform(level: 0.5, phase: phase), for: duration,
             reset: { IslandWaveform.tickCount = 0 },
             count: { IslandWaveform.tickCount })
    }

    private func ellipsisTicks(phase: String, for duration: TimeInterval) -> Int {
        host(ThinkingEllipsis(phase: phase), for: duration,
             reset: { ThinkingEllipsis.tickCount = 0 },
             count: { ThinkingEllipsis.tickCount })
    }

    func testApprovalNeverTicksAndListeningDoes() {
        let approval = ticks(phase: "awaiting_approval", for: 0.4)
        XCTAssertEqual(approval, 0,
            "no timeline tick may fire while a chip is open")

        let listening = ticks(phase: "listening", for: 0.4)
        XCTAssertGreaterThan(listening, 0,
            "positive control: the timeline must tick while listening")
    }

    func testEllipsisTicksOnlyWhileThinking() {
        for phase in ["listening", "awaiting_approval", "acting"] {
            XCTAssertEqual(ellipsisTicks(phase: phase, for: 0.4), 0,
                "the ellipsis timeline must stay paused in \(phase)")
        }

        let thinking = ellipsisTicks(phase: "thinking", for: 0.4)
        XCTAssertGreaterThan(thinking, 0,
            "positive control: the ellipsis must tick while thinking")
    }
}
