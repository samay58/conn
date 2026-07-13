import XCTest
@testable import ConnActionFixture

final class ActionFixtureTests: XCTestCase {
    func testAccessibilityPressCanReportSuccessWithoutFixtureEffect() throws {
        let path = FileManager.default.temporaryDirectory
            .appendingPathComponent(UUID().uuidString).path
        let truth = FixtureTruthLog(environment: ["CONN_FIXTURE_TRUTH_LOG": path])
        let button = NoEffectButton(title: "Reports success, no effect", target: nil, action: nil)

        XCTAssertTrue(button.accessibilityPerformPress())
        XCTAssertTrue(truth.entries().isEmpty)
    }
}
