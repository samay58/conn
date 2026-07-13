import AppKit
import XCTest
@testable import Conn

final class HotkeyMonitorTests: XCTestCase {
    func testExternalKeyboardDefaultUsesControlOptionChord() {
        let defaults = isolatedDefaults()

        let monitor = HotkeyMonitor(defaults: defaults)

        XCTAssertEqual(monitor.binding, .controlOption)
    }

    func testSelectedBindingPersistsForNextLaunch() {
        let defaults = isolatedDefaults()
        let monitor = HotkeyMonitor(defaults: defaults)

        monitor.setBinding(.leftControl)

        XCTAssertEqual(HotkeyMonitor(defaults: defaults).binding, .leftControl)
    }

    func testConfiguredModifierEmitsOnePressAndRelease() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        monitor.setBinding(.rightCommand)
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

    func testControlOptionStartsOnlyWhenBothModifiersAreHeld() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        var events: [String] = []
        monitor.onDown = { events.append("down") }
        monitor.onUp = { events.append("up") }

        monitor.handle(
            keyCode: 59,
            eventType: .flagsChanged,
            modifierFlags: .control
        )
        monitor.handle(
            keyCode: 58,
            eventType: .flagsChanged,
            modifierFlags: [.control, .option]
        )
        monitor.handle(
            keyCode: 59,
            eventType: .flagsChanged,
            modifierFlags: .option
        )
        monitor.handle(
            keyCode: 58,
            eventType: .flagsChanged,
            modifierFlags: .option
        )
        monitor.handle(
            keyCode: 59,
            eventType: .flagsChanged,
            modifierFlags: [.control, .option]
        )
        monitor.handle(
            keyCode: 58,
            eventType: .flagsChanged,
            modifierFlags: .control
        )

        XCTAssertEqual(events, ["down", "up", "down", "up"])
    }

    func testModifierEventBoundaryDoesNotReadTypingOnlyProperties() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        var pressed = false
        monitor.onDown = { pressed = true }
        let event = NSEvent.keyEvent(
            with: .flagsChanged,
            location: .zero,
            modifierFlags: [.control, .option],
            timestamp: 0,
            windowNumber: 0,
            context: nil,
            characters: "",
            charactersIgnoringModifiers: "",
            isARepeat: false,
            keyCode: 58
        )!

        monitor.handle(event)

        XCTAssertTrue(pressed)
    }

    func testChangingBindingReleasesAnActivePress() {
        let monitor = HotkeyMonitor(defaults: isolatedDefaults())
        monitor.setBinding(.rightCommand)
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
