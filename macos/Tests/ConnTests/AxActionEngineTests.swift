import XCTest
@testable import Conn

/// T4 app-lane actions: the chord grammar must match the daemon's
/// tools/ax_input.py tables exactly, and unknown ops must answer nil so the
/// daemon reports lane failure instead of hanging on the bridge timeout.
final class AxActionEngineTests: XCTestCase {
    func testChordParsesModifiersAndPrimary() throws {
        let (code, flags) = try XCTUnwrap(AxActionEngine.chord(from: ["cmd", "t"]))
        XCTAssertEqual(code, 0x11)
        XCTAssertEqual(flags, .maskCommand)
    }

    func testChordStacksModifiers() throws {
        let (code, flags) = try XCTUnwrap(AxActionEngine.chord(from: ["cmd", "shift", "p"]))
        XCTAssertEqual(code, 0x23)
        XCTAssertTrue(flags.contains(.maskCommand))
        XCTAssertTrue(flags.contains(.maskShift))
    }

    func testChordRejectsUnknownKey() {
        XCTAssertNil(AxActionEngine.chord(from: ["cmd", "f13"]))
    }

    func testChordRejectsModifierOnly() {
        XCTAssertNil(AxActionEngine.chord(from: ["cmd", "shift"]))
    }

    func testKeycodeTableMatchesDaemonSpotChecks() {
        XCTAssertEqual(AxActionEngine.keyCodes["return"], 0x24)
        XCTAssertEqual(AxActionEngine.keyCodes["space"], 0x31)
        XCTAssertEqual(AxActionEngine.keyCodes["escape"], 0x35)
        XCTAssertEqual(AxActionEngine.keyCodes.count, 45)
    }

    func testUnknownOpAnswersNil() {
        XCTAssertNil(AxActionEngine.perform(op: "explode", params: [:]))
    }

    func testMalformedParamsAnswerNil() {
        XCTAssertNil(AxActionEngine.perform(op: "key_chord", params: ["keys": "cmd+t"]))
        XCTAssertNil(AxActionEngine.perform(op: "press_menu_path", params: ["pid": 1]))
    }
}
