import XCTest
@testable import Conn

final class NativeTransactionExecutorTests: XCTestCase {
    func testMissingOrConsumedPlanReturnsFinalNotDispatchedReceipt() async {
        let backend = SemanticFixtureBackend()
        let store = NativeObservationStore(backend: backend)
        let compiler = NativeActionCompiler(
            applications: NativeApplicationResolver()
        )
        let evaluator = NativeEffectEvaluator(store: store)
        let executor = NativeTransactionExecutor(
            backend: backend,
            store: store,
            compiler: compiler,
            evaluator: evaluator,
            executionInterlock: nil
        )

        let receipt = await executor.execute([
            "plan_fingerprint": "consumed",
        ], plan: nil)

        XCTAssertEqual(receipt["outcome"] as? String, "failed")
        XCTAssertEqual(receipt["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(receipt["reason_code"] as? String, "stale_plan")
        XCTAssertEqual(receipt["retry_safe"] as? Bool, true)
    }
}
