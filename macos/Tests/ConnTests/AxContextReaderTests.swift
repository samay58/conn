import XCTest
@testable import Conn

/// The payload contract for ax_read_result (S2). The daemon whitelists and
/// coerces on its side; these pin the app-side shape so the two ends cannot
/// drift apart silently. Live AX reads need a TCC grant and are exercised in
/// the live drive, not here.
final class AxContextReaderTests: XCTestCase {
    func testPayloadCarriesAllFiveKeys() {
        let payload = AxContextReader.payload(app: "Safari", bundleId: "com.apple.Safari",
                                              windowTitle: "Apple", selectedText: "hello",
                                              trusted: true)
        XCTAssertEqual(payload["app"] as? String, "Safari")
        XCTAssertEqual(payload["bundle_id"] as? String, "com.apple.Safari")
        XCTAssertEqual(payload["window_title"] as? String, "Apple")
        XCTAssertEqual(payload["selected_text"] as? String, "hello")
        XCTAssertEqual(payload["accessibility"] as? String, "granted")
    }

    func testMissingValuesSerializeAsNullNotAbsent() throws {
        let payload = AxContextReader.payload(app: nil, bundleId: nil, windowTitle: nil,
                                              selectedText: nil, trusted: false)
        XCTAssertEqual(payload["accessibility"] as? String, "not_granted")
        let data = try JSONSerialization.data(withJSONObject: payload)
        let decoded = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        for key in ["app", "bundle_id", "window_title", "selected_text"] {
            XCTAssertTrue(decoded.keys.contains(key), "\(key) must be present as null")
            XCTAssertTrue(decoded[key] is NSNull, "\(key) must be JSON null")
        }
    }
}
