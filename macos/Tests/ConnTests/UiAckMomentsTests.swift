import XCTest
@testable import Conn

final class UiAckMomentsTests: XCTestCase {
    func testListeningTransitionAcksListening() {
        XCTAssertEqual(DaemonClient.ackMoments(from: "idle", to: "listening"),
                       ["listening"])
    }

    func testThinkingTransitionAcksThinking() {
        XCTAssertEqual(DaemonClient.ackMoments(from: "listening", to: "thinking"),
                       ["thinking"])
    }

    func testTerminalOutcomesAckTerminal() {
        XCTAssertEqual(DaemonClient.ackMoments(from: "speaking", to: "done"),
                       ["terminal"])
        XCTAssertEqual(DaemonClient.ackMoments(from: "acting", to: "failed"),
                       ["terminal"])
    }

    func testApprovalPhaseAcksApproval() {
        XCTAssertEqual(
            DaemonClient.ackMoments(from: "thinking", to: "awaiting_approval"),
            ["approval"])
    }

    func testUnchangedPhaseAcksNothing() {
        XCTAssertEqual(DaemonClient.ackMoments(from: "thinking", to: "thinking"),
                       [])
    }

    func testOtherTransitionsAckNothing() {
        XCTAssertEqual(DaemonClient.ackMoments(from: "thinking", to: "acting"),
                       [])
        XCTAssertEqual(DaemonClient.ackMoments(from: "done", to: "idle"), [])
    }

    func testGestureIDsAreWireSafeAndUnique() {
        let first = PttGesture.newID()
        let second = PttGesture.newID()
        XCTAssertNotEqual(first, second)
        for id in [first, second] {
            XCTAssertFalse(id.isEmpty)
            XCTAssertLessThanOrEqual(id.count, 64)
            XCTAssertTrue(id.allSatisfy { $0.isASCII },
                          "gesture id must be ASCII")
            XCTAssertTrue(id.allSatisfy { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" },
                          "gesture id must be alphanumeric, hyphen, or underscore")
        }
    }
}

final class OwnershipLeaseEnvironmentTests: XCTestCase {
    func testLauncherEnvironmentCarriesParentPidLease() {
        let environment = DaemonLauncher.launchEnvironment(
            base: ["PATH": "/usr/bin"], bridgeToken: "secret")

        XCTAssertEqual(environment["CONN_PARENT_PID"],
                       String(ProcessInfo.processInfo.processIdentifier))
    }
}

@MainActor
final class TurnStartUiTests: XCTestCase {
    func testEnteringListeningClearsStaleLines() {
        let state = AppState()
        state.userLine = "previous command"
        state.modelLine = "previous answer"
        state.toast = "old toast"

        state.apply(["type": "state", "phase": "listening"])

        XCTAssertEqual(state.userLine, "")
        XCTAssertEqual(state.modelLine, "")
        XCTAssertNil(state.toast)
    }

    func testNonListeningPhasesKeepLines() {
        let state = AppState()
        state.userLine = "open safari"
        state.modelLine = "Opening Safari."

        state.apply(["type": "state", "phase": "acting"])

        XCTAssertEqual(state.userLine, "open safari")
        XCTAssertEqual(state.modelLine, "Opening Safari.")
    }
}

final class ExternalKeyboardDuplicateEdgeTests: XCTestCase {
    private func isolatedDefaults() -> UserDefaults {
        let name = "ExternalKeyboardDuplicateEdgeTests.\(UUID().uuidString)"
        guard let defaults = UserDefaults(suiteName: name) else {
            fatalError("could not create isolated defaults")
        }
        defaults.removePersistentDomain(forName: name)
        return defaults
    }

    func testDuplicateChordEdgesCollapseToOnePressAndRelease() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        var events: [String] = []
        monitor.onDown = { events.append("down") }
        monitor.onUp = { events.append("up") }

        let both: NSEvent.ModifierFlags = [.control, .option]
        // External keyboards can replay the same effective state on both
        // key codes of the chord; each edge must fire exactly once.
        monitor.handle(keyCode: 59, eventType: .flagsChanged, modifierFlags: both)
        monitor.handle(keyCode: 58, eventType: .flagsChanged, modifierFlags: both)
        monitor.handle(keyCode: 59, eventType: .flagsChanged, modifierFlags: both)
        monitor.handle(keyCode: 58, eventType: .flagsChanged, modifierFlags: .option)
        monitor.handle(keyCode: 58, eventType: .flagsChanged, modifierFlags: .option)
        monitor.handle(keyCode: 59, eventType: .flagsChanged, modifierFlags: [])

        XCTAssertEqual(events, ["down", "up"])
    }
}
