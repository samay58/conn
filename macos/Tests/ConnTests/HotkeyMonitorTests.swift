import AppKit
import XCTest
@testable import Conn

final class HotkeyMonitorTests: XCTestCase {
    func testExternalKeyboardDefaultUsesRightCommand() {
        let defaults = isolatedDefaults()

        let monitor = HotkeyMonitor(defaults: defaults)

        XCTAssertEqual(monitor.binding, .rightCommand)
    }

    func testSelectedBindingPersistsForNextLaunch() {
        let defaults = isolatedDefaults()
        let monitor = HotkeyMonitor(defaults: defaults)

        monitor.setBinding(.leftControl)

        XCTAssertEqual(HotkeyMonitor(defaults: defaults).binding, .leftControl)
    }

    func testConfiguredModifierEmitsOnePressAndRelease() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        var events: [String] = []
        monitor.onDown = { events.append("down") }
        monitor.onUp = { events.append("up") }

        monitor.handle(
            keyCode: 54,
            eventType: .flagsChanged,
            modifierFlags: .command
        )
        monitor.handle(
            keyCode: 54,
            eventType: .flagsChanged,
            modifierFlags: .command
        )
        monitor.handle(
            keyCode: 54,
            eventType: .flagsChanged,
            modifierFlags: []
        )

        XCTAssertEqual(events, ["down", "up"])
    }

    func testChangingBindingReleasesAnActivePress() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        var events: [String] = []
        monitor.onDown = { events.append("down") }
        monitor.onUp = { events.append("up") }
        monitor.handle(
            keyCode: 54,
            eventType: .flagsChanged,
            modifierFlags: .command
        )

        monitor.setBinding(.leftControl)

        XCTAssertEqual(events, ["down", "up"])
    }

    func testFunctionKeyBindingUsesKeyDownAndKeyUp() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        monitor.setBinding(.f13)
        var events: [String] = []
        monitor.onDown = { events.append("down") }
        monitor.onUp = { events.append("up") }

        monitor.handle(keyCode: 105, eventType: .keyDown, modifierFlags: [])
        monitor.handle(
            keyCode: 105,
            eventType: .keyDown,
            modifierFlags: [],
            isRepeat: true
        )
        monitor.handle(keyCode: 105, eventType: .keyUp, modifierFlags: [])

        XCTAssertEqual(events, ["down", "up"])
    }

    func testBindingObservesOnlyItsRequiredEventTypes() {
        XCTAssertEqual(
            HotkeyMonitor.Binding.rightCommand.eventMask,
            .flagsChanged
        )
        XCTAssertEqual(
            HotkeyMonitor.Binding.f13.eventMask,
            [.keyDown, .keyUp]
        )
    }

    private func isolatedDefaults() -> UserDefaults {
        let name = "HotkeyMonitorTests.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: name)!
        defaults.removePersistentDomain(forName: name)
        return defaults
    }
}
