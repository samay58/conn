import Foundation
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers
import XCTest
@testable import Conn

final class NativeVisualObservationTests: XCTestCase {
    func testScreenRecordingSetupRequestsOnlyWhenAccessIsMissing() {
        let missing = ScreenRecordingPermissionFixture(
            preflightResult: false,
            requestResult: true
        )
        let granted = ScreenRecordingPermissionFixture(
            preflightResult: true,
            requestResult: false
        )

        XCTAssertTrue(ScreenRecordingPermissionSetup.ensure(using: missing))
        XCTAssertEqual(missing.requestCount, 1)
        XCTAssertTrue(ScreenRecordingPermissionSetup.ensure(using: granted))
        XCTAssertEqual(granted.requestCount, 0)
    }

    func testCurrentWindowCaptureCarriesBoundedMetadataAndImage() async throws {
        let provider = VisualFixtureProvider()
        let control = NativeVisualControl(provider: provider)

        let result = await control.observe(["enabled": true])

        XCTAssertEqual(result["outcome"] as? String, "observed")
        XCTAssertEqual(result["bundle_id"] as? String, "com.conn.fixture")
        XCTAssertEqual(result["window_id"] as? Int, 42)
        XCTAssertEqual(result["pixel_width"] as? Int, 1280)
        XCTAssertEqual(result["pixel_height"] as? Int, 720)
        XCTAssertEqual(result["scale"] as? Double, 1.6)
        XCTAssertEqual(result["excluded_conn_surfaces"] as? Bool, true)
        XCTAssertEqual(result["image_bytes"] as? Int, provider.image.count)
        XCTAssertEqual(
            result["image_sha256"] as? String,
            NativeHash.sha256(provider.image)
        )
        let dataURL = try XCTUnwrap(result["image_data_url"] as? String)
        XCTAssertTrue(dataURL.hasPrefix("data:image/jpeg;base64,"))
        XCTAssertLessThanOrEqual(dataURL.utf8.count, NativeVisualControl.maxDataURLBytes)
        XCTAssertNotNil(result["capture_id"] as? String)
        XCTAssertNotNil(result["captured_ms"] as? Int)
        XCTAssertEqual(provider.captureCount, 1)
    }

    func testReplacementRevokesPriorCaptureAndKeepsOneCurrent() async throws {
        let provider = VisualFixtureProvider()
        let control = NativeVisualControl(provider: provider)

        let first = await control.observe(["enabled": true])
        let second = await control.observe(["enabled": true])
        let firstID = try XCTUnwrap(first["capture_id"] as? String)
        let secondID = try XCTUnwrap(second["capture_id"] as? String)
        let staleMetadata = await control.metadata(captureID: firstID)
        let currentMetadata = await control.metadata(captureID: secondID)

        XCTAssertNotEqual(firstID, secondID)
        XCTAssertNil(staleMetadata)
        XCTAssertEqual(currentMetadata?["capture_id"] as? String, secondID)
        await control.revoke()
        let revokedMetadata = await control.metadata(captureID: secondID)
        XCTAssertNil(revokedMetadata)
    }

    func testDisabledVisualControlRefusesWithoutCapture() async {
        let provider = VisualFixtureProvider()
        let result = await NativeVisualControl(provider: provider).observe([
            "enabled": false,
        ])

        XCTAssertEqual(result["outcome"] as? String, "blocked")
        XCTAssertEqual(result["reason_code"] as? String, "visual_control_disabled")
        XCTAssertEqual(provider.captureCount, 0)
    }

    func testPermissionSecureDeniedAndMissingWindowHaveStableCeilings() async {
        for (failure, reason) in [
            (NativeVisualCaptureError.screenRecordingDenied, "screen_recording_denied"),
            (.secureSurface, "secure_surface"),
            (.deniedBundle, "denied_bundle"),
            (.noTargetWindow, "visual_target_window_missing"),
        ] {
            let provider = VisualFixtureProvider()
            provider.failure = failure
            let result = await NativeVisualControl(provider: provider).observe([
                "enabled": true,
            ])

            XCTAssertEqual(result["outcome"] as? String, "blocked")
            XCTAssertEqual(result["reason_code"] as? String, reason)
            XCTAssertNil(result["image_data_url"])
        }
    }

    func testOversizedCaptureRefusesBeforeBridgeEncoding() async {
        let provider = VisualFixtureProvider()
        provider.image = Data(repeating: 1, count: NativeVisualControl.maxImageBytes + 1)

        let result = await NativeVisualControl(provider: provider).observe([
            "enabled": true,
        ])

        XCTAssertEqual(result["outcome"] as? String, "failed")
        XCTAssertEqual(result["reason_code"] as? String, "visual_capture_too_large")
        XCTAssertNil(result["image_data_url"])
    }

    func testMarkerBytesWithoutDecodableJPEGRefuse() async {
        let provider = VisualFixtureProvider()
        provider.image = Data([0xff, 0xd8, 0xff]) + Data("not-an-image".utf8)

        let result = await NativeVisualControl(provider: provider).observe([
            "enabled": true,
        ])

        XCTAssertEqual(result["outcome"] as? String, "failed")
        XCTAssertEqual(result["reason_code"] as? String, "visual_capture_invalid_format")
    }

    func testDecodedDimensionsMustMatchCaptureMetadata() async {
        let provider = VisualFixtureProvider()
        provider.pixelWidth = 1279

        let result = await NativeVisualControl(provider: provider).observe([
            "enabled": true,
        ])

        XCTAssertEqual(result["outcome"] as? String, "failed")
        XCTAssertEqual(result["reason_code"] as? String, "visual_capture_invalid_metadata")
    }
}

final class ScreenRecordingPermissionFixture: ScreenRecordingPermissionProviding {
    let preflightResult: Bool
    let requestResult: Bool
    private(set) var requestCount = 0

    init(preflightResult: Bool, requestResult: Bool) {
        self.preflightResult = preflightResult
        self.requestResult = requestResult
    }

    func preflight() -> Bool {
        preflightResult
    }

    func request() -> Bool {
        requestCount += 1
        return requestResult
    }
}

final class VisualFixtureProvider: NativeVisualCaptureProvider, @unchecked Sendable {
    var image = VisualFixtureProvider.jpeg(width: 1280, height: 720)
    var pixelWidth = 1280
    var pixelHeight = 720
    var failure: NativeVisualCaptureError?
    var frame = NativeRect(x: 10, y: 20, width: 800, height: 450)
    var hitLabel: String?
    var hitLabels: [String?] = []
    var dispatchResult = NativeDispatchResult(state: .dispatched, nativeError: nil)
    var recaptureDelayMs = 0
    var dispatchDelayMs = 0
    private(set) var captureCount = 0
    private(set) var dispatchCount = 0

    func capture(deniedBundles: Set<String>) async throws -> NativeVisualSource {
        captureCount += 1
        if captureCount > 1, recaptureDelayMs > 0 {
            try await Task.sleep(for: .milliseconds(recaptureDelayMs))
        }
        if let failure { throw failure }
        return NativeVisualSource(
            jpegData: image,
            pixelWidth: pixelWidth,
            pixelHeight: pixelHeight,
            scale: 1.6,
            windowID: 42,
            bundleID: "com.conn.fixture",
            windowFrame: frame,
            capturedMs: NativeClock.ms(),
            excludedConnSurfaces: true
        )
    }

    func accessibleLabel(at point: CGPoint) -> String? {
        if !hitLabels.isEmpty { return hitLabels.removeFirst() }
        return hitLabel
    }

    func dispatch(
        input: NativePointerInput, at point: CGPoint
    ) -> NativeDispatchResult {
        dispatchCount += 1
        lastInput = input
        if dispatchDelayMs > 0 {
            Thread.sleep(forTimeInterval: Double(dispatchDelayMs) / 1000)
        }
        return dispatchResult
    }

    private(set) var lastInput: NativePointerInput?

    private static func jpeg(width: Int, height: Int) -> Data {
        let colorSpace = CGColorSpaceCreateDeviceRGB()
        let context = CGContext(
            data: nil,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width * 4,
            space: colorSpace,
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
        )!
        context.setFillColor(CGColor(gray: 0.5, alpha: 1))
        context.fill(CGRect(x: 0, y: 0, width: width, height: height))
        let image = context.makeImage()!
        let data = NSMutableData()
        let destination = CGImageDestinationCreateWithData(
            data, UTType.jpeg.identifier as CFString, 1, nil
        )!
        CGImageDestinationAddImage(destination, image, nil)
        precondition(CGImageDestinationFinalize(destination))
        return data as Data
    }
}
