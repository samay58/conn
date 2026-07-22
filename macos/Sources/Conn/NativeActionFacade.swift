import Foundation

actor NativeActionFacade {
    private let semantic: NativeSemanticActionEngine
    private let visual: NativeVisualControl

    init(
        semantic: NativeSemanticActionEngine,
        visual: NativeVisualControl
    ) {
        self.semantic = semantic
        self.visual = visual
    }

    func perform(op: String, params: [String: Any]) async -> [String: Any]? {
        if op == "observe_visual" {
            return await visual.observe(params)
        }
        if op == "prepare_action", Self.isVisualPreparation(params) {
            return await visual.prepareVisual(params)
        }
        if op == "execute_action",
           let fingerprint = params["plan_fingerprint"] as? String,
           await visual.ownsPlan(fingerprint) {
            return await visual.executeVisual(params)
        }
        return await semantic.perform(op: op, params: params)
    }

    func invalidate() async {
        await semantic.invalidatePlans()
        await visual.revoke()
    }

    private static func isVisualPreparation(_ params: [String: Any]) -> Bool {
        guard let request = params["request"] as? [String: Any],
              request["operation"] as? String == "activate",
              let payload = request["payload"] as? [String: Any] else {
            return false
        }
        return payload["visual_grounding"] is [String: Any]
    }
}
