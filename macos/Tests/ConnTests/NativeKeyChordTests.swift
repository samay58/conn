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

    func testSemanticFindKeyExpandsToCommandF() throws {
        let (code, flags) = try XCTUnwrap(NativeKeyChord.parse(["find"]))

        XCTAssertEqual(code, 0x03)
        XCTAssertEqual(flags, .maskCommand)
    }

    func testRejectsUnknownOrModifierOnlyChord() {
        XCTAssertNil(NativeKeyChord.parse(["cmd", "f13"]))
        XCTAssertNil(NativeKeyChord.parse(["cmd", "shift"]))
    }

    func testKeycodeTableMatchesDaemonSpotChecks() {
        XCTAssertEqual(NativeKeyChord.keyCodes["return"], 0x24)
        XCTAssertEqual(NativeKeyChord.keyCodes["space"], 0x31)
        XCTAssertEqual(NativeKeyChord.keyCodes["escape"], 0x35)
        XCTAssertEqual(NativeKeyChord.keyCodes["home"], 0x73)
        XCTAssertEqual(NativeKeyChord.keyCodes["pageup"], 0x74)
        XCTAssertEqual(NativeKeyChord.keyCodes["end"], 0x77)
        XCTAssertEqual(NativeKeyChord.keyCodes["pagedown"], 0x79)
        XCTAssertEqual(NativeKeyChord.keyCodes.count, 49)
    }
}
