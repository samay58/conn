import XCTest
@testable import Conn

final class NativeKeyChordTests: XCTestCase {
    func testParsesModifiersAndPrimary() throws {
        let (code, flags) = try XCTUnwrap(NativeKeyChord.parse(["cmd", "t"]))
        XCTAssertEqual(code, 0x11)
        XCTAssertEqual(flags, .maskCommand)
    }

    func testStacksModifiers() throws {
        let (code, flags) = try XCTUnwrap(
            NativeKeyChord.parse(["cmd", "shift", "p"])
        )
        XCTAssertEqual(code, 0x23)
        XCTAssertTrue(flags.contains(.maskCommand))
        XCTAssertTrue(flags.contains(.maskShift))
    }

    func testRejectsUnknownOrModifierOnlyChord() {
        XCTAssertNil(NativeKeyChord.parse(["cmd", "f13"]))
        XCTAssertNil(NativeKeyChord.parse(["cmd", "shift"]))
    }

    func testKeycodeTableMatchesDaemonSpotChecks() {
        XCTAssertEqual(NativeKeyChord.keyCodes["return"], 0x24)
        XCTAssertEqual(NativeKeyChord.keyCodes["space"], 0x31)
        XCTAssertEqual(NativeKeyChord.keyCodes["escape"], 0x35)
        XCTAssertEqual(NativeKeyChord.keyCodes.count, 45)
    }
}
