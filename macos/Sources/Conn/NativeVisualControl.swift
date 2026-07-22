import AppKit
import CoreGraphics
import Foundation
import ImageIO
import ScreenCaptureKit
import UniformTypeIdentifiers

enum NativeVisualCaptureError: Error {
    case screenRecordingDenied
    case secureSurface
    case deniedBundle
    case noTargetWindow
    case captureFailed
    case targetChanged
}

protocol ScreenRecordingPermissionProviding {
    func preflight() -> Bool
    func request() -> Bool
}

struct NativeScreenRecordingPermissionProvider: ScreenRecordingPermissionProviding {
    func preflight() -> Bool {
        CGPreflightScreenCaptureAccess()
    }

    func request() -> Bool {
        CGRequestScreenCaptureAccess()
    }
}

enum ScreenRecordingPermissionSetup {
    static func ensure(
        using provider: ScreenRecordingPermissionProviding =
            NativeScreenRecordingPermissionProvider()
    ) -> Bool {
        provider.preflight() || provider.request()
    }
}

struct NativeVisualSource {
    let jpegData: Data
    let pixelWidth: Int
    let pixelHeight: Int
    let scale: Double
    let windowID: UInt32
    let bundleID: String
    let windowFrame: NativeRect
    let capturedMs: Int
    let excludedConnSurfaces: Bool
}

protocol NativeVisualCaptureProvider: Sendable {
    func capture(deniedBundles: Set<String>) async throws -> NativeVisualSource
    func accessibleLabel(at point: CGPoint) -> String?
    func dispatch(input: NativePointerInput, at point: CGPoint) -> NativeDispatchResult
}

enum NativePointerInput: String {
    case primaryClick = "primary_click"
    case doubleClick = "double_click"
    case rightClick = "right_click"
    case scroll

    var eventCount: Int {
        switch self {
        case .primaryClick, .rightClick: return 2
        case .doubleClick: return 4
        case .scroll: return 1
        }
    }
}

struct NativeVisualGrounding {
    let captureID: String
    let region: NativeRect
    let label: String
    let confidence: Double

    static func parse(_ value: Any?) -> Self? {
        guard let raw = value as? [String: Any],
              Set(raw.keys) == Set(["capture_id", "region", "label", "confidence"]),
              let captureID = raw["capture_id"] as? String,
              !captureID.isEmpty,
              captureID.count <= 128,
              let label = raw["label"] as? String,
              !label.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              label.count <= 160,
              let confidence = (raw["confidence"] as? NSNumber)?.doubleValue,
              confidence.isFinite,
              (0 ... 1).contains(confidence),
              let region = rect(raw["region"]),
              region.x >= 0,
              region.y >= 0,
              region.width > 0,
              region.height > 0,
              region.x + region.width <= 1,
              region.y + region.height <= 1 else { return nil }
        return Self(
            captureID: captureID,
            region: region,
            label: label.trimmingCharacters(in: .whitespacesAndNewlines),
            confidence: confidence
        )
    }

    static func point(region: NativeRect, windowFrame: NativeRect) -> CGPoint {
        CGPoint(
            x: windowFrame.x + (region.x + region.width / 2) * windowFrame.width,
            y: windowFrame.y + (region.y + region.height / 2) * windowFrame.height
        )
    }

    private static func rect(_ value: Any?) -> NativeRect? {
        guard let raw = value as? [String: Any],
              Set(raw.keys) == Set(["x", "y", "width", "height"]),
              let x = number(raw["x"]),
              let y = number(raw["y"]),
              let width = number(raw["width"]),
              let height = number(raw["height"]),
              [x, y, width, height].allSatisfy(\.isFinite) else { return nil }
        return NativeRect(x: x, y: y, width: width, height: height)
    }

    private static func number(_ value: Any?) -> Double? {
        (value as? NSNumber)?.doubleValue
    }
}

struct NativeVisualCaptureRecord {
    let captureID: String
    let source: NativeVisualSource
    let imageDigest: String
    let turnID: String
    let observationEpoch: Int
    let connectionID: String
    let expiresMs: Int
    let deniedBundles: Set<String>
}

struct NativeVisualPlan {
    let fingerprint: String
    let capture: NativeVisualCaptureRecord
    let grounding: NativeVisualGrounding
    let goal: String
    let input: NativePointerInput
    let generation: Int
    let connectionID: String
    let createdMs: Int
    let timeoutMs: Int
}

actor NativeVisualControl {
    static let maxImageBytes = 1_200_000
    static let maxDataURLBytes = 1_600_023
    static let maxLongEdge = 1_280
    static let jpegQuality = 0.72
    static let captureTTLms = 5_000

    private let provider: NativeVisualCaptureProvider
    private let executionInterlock: NativeExecutionInterlock?
    private var currentMetadata: [String: Any]?
    private var currentCapture: NativeVisualCaptureRecord?
    private var plans: [String: NativeVisualPlan] = [:]

    init(
        provider: NativeVisualCaptureProvider = ScreenCaptureVisualProvider(),
        executionInterlock: NativeExecutionInterlock? = nil
    ) {
        self.provider = provider
        self.executionInterlock = executionInterlock
    }

    func observe(_ params: [String: Any]) async -> [String: Any] {
        guard params["enabled"] as? Bool == true else {
            return refusal("visual_control_disabled", outcome: "blocked")
        }
        let denied = Set(params["denied_bundles"] as? [String] ?? [])
        do {
            let source = try await provider.capture(deniedBundles: denied)
            guard source.jpegData.count <= Self.maxImageBytes else {
                return refusal("visual_capture_too_large", outcome: "failed")
            }
            guard let decoded = Self.decodedJPEG(source.jpegData) else {
                return refusal("visual_capture_invalid_format", outcome: "failed")
            }
            guard source.pixelWidth > 0,
                  source.pixelHeight > 0,
                  source.pixelWidth == decoded.width,
                  source.pixelHeight == decoded.height,
                  max(source.pixelWidth, source.pixelHeight) <= Self.maxLongEdge,
                  source.scale.isFinite,
                  source.scale > 0,
                  source.windowFrame.width > 0,
                  source.windowFrame.height > 0,
                  NativeAppIdentity.validBundleID(source.bundleID) else {
                return refusal("visual_capture_invalid_metadata", outcome: "failed")
            }
            let dataURL = "data:image/jpeg;base64,\(source.jpegData.base64EncodedString())"
            guard dataURL.utf8.count <= Self.maxDataURLBytes else {
                return refusal("visual_capture_too_large", outcome: "failed")
            }
            let captureID = UUID().uuidString.lowercased()
            let digest = NativeHash.sha256(source.jpegData)
            let turnID = params["turn_id"] as? String ?? "system"
            let observationEpoch = params["observation_epoch"] as? Int ?? 0
            let connectionID = params["execution_connection_id"] as? String ?? "test"
            let metadata: [String: Any] = [
                "capture_id": captureID,
                "image_sha256": digest,
                "image_bytes": source.jpegData.count,
                "mime_type": "image/jpeg",
                "pixel_width": source.pixelWidth,
                "pixel_height": source.pixelHeight,
                "scale": source.scale,
                "window_id": Int(source.windowID),
                "bundle_id": source.bundleID,
                "window_frame": source.windowFrame.dictionary,
                "captured_ms": source.capturedMs,
                "excluded_conn_surfaces": source.excludedConnSurfaces,
                "turn_id": turnID,
                "observation_epoch": observationEpoch,
                "execution_connection_id": connectionID,
                "expires_ms": source.capturedMs + Self.captureTTLms,
            ]
            currentCapture = NativeVisualCaptureRecord(
                captureID: captureID,
                source: source,
                imageDigest: digest,
                turnID: turnID,
                observationEpoch: observationEpoch,
                connectionID: connectionID,
                expiresMs: source.capturedMs + Self.captureTTLms,
                deniedBundles: denied
            )
            currentMetadata = metadata
            return metadata.merging([
                "outcome": "observed",
                "ok": true,
                "image_data_url": dataURL,
            ], uniquingKeysWith: { current, _ in current })
        } catch let error as NativeVisualCaptureError {
            switch error {
            case .screenRecordingDenied:
                return refusal("screen_recording_denied", outcome: "blocked")
            case .secureSurface:
                return refusal("secure_surface", outcome: "blocked")
            case .deniedBundle:
                return refusal("denied_bundle", outcome: "blocked")
            case .noTargetWindow:
                return refusal("visual_target_window_missing", outcome: "blocked")
            case .captureFailed:
                return refusal("visual_capture_failed", outcome: "failed")
            case .targetChanged:
                return refusal("visual_target_changed", outcome: "blocked")
            }
        } catch {
            return refusal("visual_capture_failed", outcome: "failed")
        }
    }

    func metadata(captureID: String) -> [String: Any]? {
        guard currentMetadata?["capture_id"] as? String == captureID else { return nil }
        return currentMetadata
    }

    func revoke() {
        currentMetadata = nil
        currentCapture = nil
        plans.removeAll(keepingCapacity: true)
    }

    func ownsPlan(_ fingerprint: String) -> Bool {
        plans[fingerprint] != nil
    }

    func prepareVisual(_ params: [String: Any]) -> [String: Any] {
        let raw = params["request"] as? [String: Any] ?? [:]
        guard raw["operation"] as? String == "activate",
              raw["visual_enabled"] as? Bool == true,
              let payload = raw["payload"] as? [String: Any],
              let goal = payload["goal"] as? String,
              !goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              goal.count <= 160,
              let grounding = NativeVisualGrounding.parse(payload["visual_grounding"])
        else { return planFailure("invalid_visual_request") }
        guard grounding.confidence >= 0.7 else {
            return planFailure("visual_grounding_low_confidence")
        }
        guard let capture = currentCapture,
              capture.captureID == grounding.captureID else {
            return planFailure("visual_capture_missing")
        }
        let turnID = params["turn_id"] as? String ?? "system"
        let observationEpoch = params["observation_epoch"] as? Int ?? 0
        let connectionID = params["execution_connection_id"] as? String ?? "test"
        guard capture.turnID == turnID,
              capture.observationEpoch == observationEpoch,
              capture.connectionID == connectionID,
              NativeClock.ms() <= capture.expiresMs else {
            return planFailure("visual_plan_stale")
        }
        let generation = params["navigation_generation"] as? Int ?? 0
        let timeoutMs = min(max(raw["timeout_ms"] as? Int ?? 1200, 10), 4000)
        let effectClass = NativeActionCompiler.visualEffectClass(
            goal: goal, label: grounding.label
        )
        let input = NativeActionCompiler.visualPointerInput(
            goal: goal, label: grounding.label
        )
        let fingerprint = NativeHash.sha256([
            capture.captureID,
            capture.imageDigest,
            turnID,
            String(observationEpoch),
            String(generation),
            connectionID,
            String(timeoutMs),
            goal,
            grounding.label,
            String(grounding.region.x),
            String(grounding.region.y),
            String(grounding.region.width),
            String(grounding.region.height),
        ].joined(separator: "\u{1e}"))
        plans[fingerprint] = NativeVisualPlan(
            fingerprint: fingerprint,
            capture: capture,
            grounding: grounding,
            goal: goal,
            input: input,
            generation: generation,
            connectionID: connectionID,
            createdMs: NativeClock.ms(),
            timeoutMs: timeoutMs
        )
        while plans.count > 8, let oldest = plans.min(by: {
            $0.value.createdMs < $1.value.createdMs
        })?.key {
            plans.removeValue(forKey: oldest)
        }
        return [
            "plan_fingerprint": fingerprint,
            "preview": "Activate \(grounding.label)",
            "target": "\(grounding.label) in current window",
            "effect": "\(grounding.label) state changes",
            "authorized_strategies": ["visual_coordinate_press"],
            "risk": "act_low",
            "effect_class": effectClass.rawValue,
            "navigation_generation": generation,
            "bundle_id": capture.source.bundleID,
            "window_id": Int(capture.source.windowID),
            "capture_id": capture.captureID,
            "capture_digest": capture.imageDigest,
            "timeout_ms": timeoutMs,
            "predicates": [],
        ]
    }

    func executeVisual(_ params: [String: Any]) async -> [String: Any] {
        let fingerprint = params["plan_fingerprint"] as? String
        let plan = fingerprint.flatMap { plans.removeValue(forKey: $0) }
        return await NativeTransactionExecutor.executeVisual(
            params,
            plan: plan,
            provider: provider,
            executionInterlock: executionInterlock
        )
    }

    private func refusal(_ reason: String, outcome: String) -> [String: Any] {
        [
            "outcome": outcome,
            "ok": false,
            "reason_code": reason,
            "error": reason,
        ]
    }

    private func planFailure(_ reason: String) -> [String: Any] {
        [
            "outcome": "failed",
            "ok": false,
            "error": reason,
            "reason_code": reason,
            "dispatch_state": "not_dispatched",
            "retry_safe": true,
        ]
    }

    private static func decodedJPEG(_ data: Data) -> CGImage? {
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              CGImageSourceGetType(source) == UTType.jpeg.identifier as CFString else {
            return nil
        }
        return CGImageSourceCreateImageAtIndex(source, 0, nil)
    }
}

final class ScreenCaptureVisualProvider: NativeVisualCaptureProvider, @unchecked Sendable {
    func capture(deniedBundles: Set<String>) async throws -> NativeVisualSource {
        guard CGPreflightScreenCaptureAccess() else {
            throw NativeVisualCaptureError.screenRecordingDenied
        }
        let observation = NativeAXSemanticBackend().capture(
            turnID: "visual",
            observationEpoch: 0,
            query: NativeObservationQuery(
                maxNodes: 300,
                maxDepth: 16,
                deniedBundles: deniedBundles
            )
        )
        if observation.denied { throw NativeVisualCaptureError.deniedBundle }
        if observation.secure { throw NativeVisualCaptureError.secureSurface }
        guard let windowID = observation.windowID,
              let bundleID = observation.bundleID,
              let windowFrame = observation.windowFrame else {
            throw NativeVisualCaptureError.noTargetWindow
        }
        if bundleID == Bundle.main.bundleIdentifier {
            throw NativeVisualCaptureError.deniedBundle
        }

        let content: SCShareableContent
        do {
            content = try await SCShareableContent.excludingDesktopWindows(
                false, onScreenWindowsOnly: true
            )
        } catch {
            throw NativeVisualCaptureError.screenRecordingDenied
        }
        guard let window = content.windows.first(where: { $0.windowID == windowID }) else {
            throw NativeVisualCaptureError.noTargetWindow
        }
        guard window.owningApplication?.bundleIdentifier == bundleID,
              Self.framesMatch(window.frame, windowFrame) else {
            throw NativeVisualCaptureError.targetChanged
        }
        let size = Self.boundedSize(width: window.frame.width, height: window.frame.height)
        let configuration = SCStreamConfiguration()
        configuration.width = size.width
        configuration.height = size.height
        configuration.showsCursor = false
        configuration.ignoreShadowsSingleWindow = true
        let filter = SCContentFilter(desktopIndependentWindow: window)
        let image: CGImage
        do {
            image = try await SCScreenshotManager.captureImage(
                contentFilter: filter,
                configuration: configuration
            )
        } catch {
            throw NativeVisualCaptureError.captureFailed
        }
        guard let jpeg = Self.jpegData(image) else {
            throw NativeVisualCaptureError.captureFailed
        }
        return NativeVisualSource(
            jpegData: jpeg,
            pixelWidth: image.width,
            pixelHeight: image.height,
            scale: Double(image.width) / windowFrame.width,
            windowID: windowID,
            bundleID: bundleID,
            windowFrame: windowFrame,
            capturedMs: NativeClock.ms(),
            excludedConnSurfaces: true
        )
    }

    func accessibleLabel(at point: CGPoint) -> String? {
        guard let app = NSWorkspace.shared.frontmostApplication else { return nil }
        let appElement = AXUIElementCreateApplication(app.processIdentifier)
        var hit: AXUIElement?
        guard AXUIElementCopyElementAtPosition(
            appElement, Float(point.x), Float(point.y), &hit
        ) == .success, let hit else { return nil }
        var rawRole: CFTypeRef?
        _ = AXUIElementCopyAttributeValue(
            hit, kAXRoleAttribute as CFString, &rawRole
        )
        let role = rawRole as? String ?? ""
        var rawActions: CFArray?
        guard AXUIElementCopyActionNames(hit, &rawActions) == .success else {
            return nil
        }
        let actionNames = rawActions as? [String] ?? []
        var values: [String?] = []
        for attribute in [kAXTitleAttribute, kAXDescriptionAttribute, kAXIdentifierAttribute] {
            var value: CFTypeRef?
            if AXUIElementCopyAttributeValue(
                hit, attribute as CFString, &value
            ) == .success {
                values.append(value as? String)
            } else {
                values.append(nil)
            }
        }
        return Self.actionableLabel(
            role: role,
            actionNames: actionNames,
            values: values
        )
    }

    static func actionableLabel(
        role: String,
        actionNames: [String],
        values: [String?]
    ) -> String? {
        let activationActions = Set(["AXPress", "AXConfirm", "AXPick"])
        let menuRoles = Set([
            "AXButton", "AXMenuButton", "AXMenuItem", "AXPopUpButton",
        ])
        let actionable = !activationActions.isDisjoint(with: actionNames)
            || (actionNames.contains("AXShowMenu") && menuRoles.contains(role))
        guard actionable else {
            return nil
        }
        return values.compactMap { value in
            let text = value?.trimmingCharacters(in: .whitespacesAndNewlines)
            return text?.isEmpty == false ? text : nil
        }.first
    }

    func dispatch(
        input: NativePointerInput, at point: CGPoint
    ) -> NativeDispatchResult {
        let events: [CGEvent?]
        switch input {
        case .primaryClick:
            events = [
                CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
                        mouseCursorPosition: point, mouseButton: .left),
                CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
                        mouseCursorPosition: point, mouseButton: .left),
            ]
        case .doubleClick:
            let firstDown = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
                                    mouseCursorPosition: point, mouseButton: .left)
            let firstUp = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
                                  mouseCursorPosition: point, mouseButton: .left)
            let secondDown = CGEvent(mouseEventSource: nil, mouseType: .leftMouseDown,
                                     mouseCursorPosition: point, mouseButton: .left)
            let secondUp = CGEvent(mouseEventSource: nil, mouseType: .leftMouseUp,
                                   mouseCursorPosition: point, mouseButton: .left)
            secondDown?.setIntegerValueField(.mouseEventClickState, value: 2)
            secondUp?.setIntegerValueField(.mouseEventClickState, value: 2)
            events = [firstDown, firstUp, secondDown, secondUp]
        case .rightClick:
            events = [
                CGEvent(mouseEventSource: nil, mouseType: .rightMouseDown,
                        mouseCursorPosition: point, mouseButton: .right),
                CGEvent(mouseEventSource: nil, mouseType: .rightMouseUp,
                        mouseCursorPosition: point, mouseButton: .right),
            ]
        case .scroll:
            events = [CGEvent(
                scrollWheelEvent2Source: nil, units: .line,
                wheelCount: 1, wheel1: -3, wheel2: 0, wheel3: 0
            )]
        }
        guard events.count == input.eventCount,
              events.allSatisfy({ $0 != nil }) else {
            return NativeDispatchResult(
                state: .notDispatched, nativeError: "native_event_creation_failed"
            )
        }
        for event in events.compactMap({ $0 }) {
            event.post(tap: .cghidEventTap)
        }
        return NativeDispatchResult(state: .dispatched, nativeError: nil)
    }

    private static func boundedSize(width: Double, height: Double) -> (width: Int, height: Int) {
        let longest = max(width, height, 1)
        let factor = min(Double(NativeVisualControl.maxLongEdge) / longest, 2)
        return (
            max(Int((width * factor).rounded()), 1),
            max(Int((height * factor).rounded()), 1)
        )
    }

    private static func framesMatch(_ captured: CGRect, _ observed: NativeRect) -> Bool {
        let tolerance = 2.0
        return abs(captured.origin.x - observed.x) <= tolerance
            && abs(captured.origin.y - observed.y) <= tolerance
            && abs(captured.width - observed.width) <= tolerance
            && abs(captured.height - observed.height) <= tolerance
    }

    private static func jpegData(_ image: CGImage) -> Data? {
        let data = NSMutableData()
        guard let destination = CGImageDestinationCreateWithData(
            data,
            UTType.jpeg.identifier as CFString,
            1,
            nil
        ) else { return nil }
        CGImageDestinationAddImage(
            destination,
            image,
            [kCGImageDestinationLossyCompressionQuality: NativeVisualControl.jpegQuality]
                as CFDictionary
        )
        guard CGImageDestinationFinalize(destination) else { return nil }
        return data as Data
    }
}
