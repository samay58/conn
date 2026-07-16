enum NativeReasonCode: String {
    case noTrustworthyWitness = "no_trustworthy_witness"
    case witnessNotMatched = "witness_not_matched"
    case ambiguousAfterFullLocator = "ambiguous_after_full_locator"
    case blockedWithoutReason = "blocked_without_reason"
    case nativeActionFailed = "native_action_failed"

    static func value(
        outcome: NativeActionOutcome,
        nativeError: String?
    ) -> String? {
        switch outcome {
        case .verified:
            return nil
        case .dispatchOnly:
            return noTrustworthyWitness.rawValue
        case .noEffect:
            return witnessNotMatched.rawValue
        case .ambiguous:
            return nativeError ?? ambiguousAfterFullLocator.rawValue
        case .blocked:
            return nativeError ?? blockedWithoutReason.rawValue
        case .failed:
            return nativeError ?? nativeActionFailed.rawValue
        }
    }
}
