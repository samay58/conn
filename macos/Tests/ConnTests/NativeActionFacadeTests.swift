import XCTest
@testable import Conn

final class NativeActionFacadeTests: XCTestCase {
    func testFacadeRoutesVisualObservationThroughVisualOwner() async {
        let provider = VisualFixtureProvider()
        let facade = NativeActionFacade(
            semantic: NativeSemanticActionEngine(backend: SemanticFixtureBackend()),
            visual: NativeVisualControl(provider: provider)
        )

        let result = await facade.perform(
            op: "observe_visual",
            params: ["enabled": false]
        )

        XCTAssertEqual(result?["outcome"] as? String, "blocked")
        XCTAssertEqual(
            result?["reason_code"] as? String,
            "visual_control_disabled"
        )
        XCTAssertEqual(provider.captureCount, 0)
    }
}
