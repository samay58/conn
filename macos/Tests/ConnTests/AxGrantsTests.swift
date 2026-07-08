import XCTest
@testable import Conn

/// T2 grant preflight: the ax_grants message drives one short island warning
/// line, and only genuinely dark lanes fire it.
@MainActor
final class AxGrantsTests: XCTestCase {
    func testAppLaneDarkWinsOverPython() {
        let warning = AppState.grantWarning(appAx: "not_granted", pythonAx: "not_granted")
        XCTAssertEqual(warning, "Accessibility grant lost: retoggle Conn in System Settings")
    }

    func testPythonLaneDarkAlone() {
        let warning = AppState.grantWarning(appAx: "granted", pythonAx: "not_granted")
        XCTAssertEqual(warning, "Daemon Accessibility lane dark: run conn --doctor")
    }

    func testBothGrantedIsQuiet() {
        XCTAssertNil(AppState.grantWarning(appAx: "granted", pythonAx: "granted"))
    }

    func testUnattachedAndUnknownAreNotDark() {
        XCTAssertNil(AppState.grantWarning(appAx: "unattached", pythonAx: "unknown"))
    }

    func testApplySetsAndClearsWarning() {
        let state = AppState()
        state.apply(["type": "ax_grants", "app_ax": "not_granted", "python_ax": "granted"])
        XCTAssertNotNil(state.axWarning)
        state.apply(["type": "ax_grants", "app_ax": "granted", "python_ax": "granted"])
        XCTAssertNil(state.axWarning)
    }
}
