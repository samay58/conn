import ApplicationServices
import XCTest
@testable import Conn

final class SelectedRowsDispatchClassificationTests: XCTestCase {
    func testCannotCompleteIsPossiblyDispatched() {
        let result = NativeAXSemanticBackend.classifySelectedRowsError(.cannotComplete)
        XCTAssertEqual(result.state, .possiblyDispatched)
        XCTAssertEqual(result.nativeError, "selected_rows_set_failed:-25204")
    }

    func testUnknownFailureIsPossiblyDispatched() {
        let result = NativeAXSemanticBackend.classifySelectedRowsError(.failure)
        XCTAssertEqual(result.state, .possiblyDispatched)
        XCTAssertEqual(result.nativeError, "selected_rows_set_failed:-25200")
    }

    func testProvenRejectionIsNotDispatched() {
        let result = NativeAXSemanticBackend.classifySelectedRowsError(.illegalArgument)
        XCTAssertEqual(result.state, .notDispatched)
        XCTAssertEqual(result.nativeError, "selected_rows_set_failed:-25201")
    }

    func testSuccessIsDispatched() {
        let result = NativeAXSemanticBackend.classifySelectedRowsError(.success)
        XCTAssertEqual(result.state, .dispatched)
        XCTAssertNil(result.nativeError)
    }
}
