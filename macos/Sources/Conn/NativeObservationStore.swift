import Foundation

protocol NativeSemanticBackend: AnyObject {
    func capture(
        turnID: String,
        observationEpoch: Int,
        query: NativeObservationQuery
    ) -> NativeCapturedObservation

    func dispatch(
        strategy: NativeActionStrategy,
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) -> NativeDispatchResult

    func beginEvidenceObservation(
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    )

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool
}

extension NativeSemanticBackend {
    func beginEvidenceObservation(
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) {}

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool { true }
}

enum NativeResolutionError: Error, Equatable {
    case staleSnapshot
    case staleProcess
    case staleWindow
    case missingTarget
    case ambiguous
}

final class NativeObservationStore {
    private let backend: NativeSemanticBackend
    private var snapshots: [String: NativeCapturedObservation] = [:]
    private let snapshotLimit = 8

    init(backend: NativeSemanticBackend) {
        self.backend = backend
    }

    func observe(
        turnID: String,
        observationEpoch: Int,
        query: NativeObservationQuery
    ) -> NativeCapturedObservation {
        let snapshot = backend.capture(
            turnID: turnID,
            observationEpoch: observationEpoch,
            query: query
        )
        snapshots[snapshot.snapshotID] = snapshot
        if snapshots.count > snapshotLimit {
            let oldest = snapshots.values.sorted { $0.monotonicMs < $1.monotonicMs }
            for item in oldest.prefix(snapshots.count - snapshotLimit) {
                snapshots.removeValue(forKey: item.snapshotID)
            }
        }
        return snapshot
    }

    func snapshot(id: String) -> NativeCapturedObservation? {
        snapshots[id]
    }

    func resolve(
        target: NativeActionTarget,
        baseline: NativeCapturedObservation,
        current: NativeCapturedObservation
    ) -> Result<NativeResolvedTarget, NativeResolutionError> {
        guard baseline.turnID == current.turnID,
              baseline.observationEpoch == current.observationEpoch else {
            return .failure(.staleSnapshot)
        }
        if baseline.pid != current.pid
            || baseline.processStartIdentity != current.processStartIdentity {
            return .failure(.staleProcess)
        }
        if baseline.windowID != nil, baseline.windowID != current.windowID {
            return .failure(.staleWindow)
        }

        guard let original = originalNode(target: target, in: baseline) else {
            return .failure(.missingTarget)
        }

        if let identifier = original.identifier, !identifier.isEmpty {
            let matches = current.nodes.filter { $0.identifier == identifier }
            if matches.count > 1 { return .failure(.ambiguous) }
            if matches.count == 1,
               semanticContextMatches(
                   original,
                   matches[0],
                   baseline: baseline,
                   current: current
               ) {
                return .success(NativeResolvedTarget(
                    original: original,
                    current: matches[0],
                    resolution: "identifier"
                ))
            }
        }

        let semanticMatches = current.nodes.filter {
            $0.semanticFingerprint == original.semanticFingerprint
        }
        if semanticMatches.count > 1 { return .failure(.ambiguous) }
        if semanticMatches.count == 1,
           semanticContextMatches(
               original,
               semanticMatches[0],
               baseline: baseline,
               current: current
           ) {
            return .success(NativeResolvedTarget(
                original: original,
                current: semanticMatches[0],
                resolution: "semantic_fingerprint"
            ))
        }

        let pathMatches = current.nodes.filter {
            $0.path == original.path
                && $0.siblingSignature == original.siblingSignature
                && $0.role == original.role
                && $0.semanticFingerprint == original.semanticFingerprint
                && framesWithinDrift($0.frame, original.frame)
        }
        if pathMatches.count == 1 {
            return .success(NativeResolvedTarget(
                original: original,
                current: pathMatches[0],
                resolution: "path_sibling_frame"
            ))
        }
        return .failure(pathMatches.isEmpty ? .missingTarget : .ambiguous)
    }

    private func originalNode(
        target: NativeActionTarget,
        in snapshot: NativeCapturedObservation
    ) -> NativeObservationNode? {
        if let ref = target.ref,
           let match = snapshot.nodes.first(where: { $0.ref == ref }) {
            return match
        }
        if let identifier = target.identifier {
            let matches = snapshot.nodes.filter { $0.identifier == identifier }
            return matches.count == 1 ? matches[0] : nil
        }
        if let title = target.title {
            let matches = snapshot.nodes.filter { normalize($0.title) == normalize(title) }
            return matches.count == 1 ? matches[0] : nil
        }
        return nil
    }

    private func normalize(_ value: String?) -> String {
        (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }

    private func framesWithinDrift(_ lhs: NativeRect?, _ rhs: NativeRect?) -> Bool {
        guard let lhs, let rhs else { return lhs == nil && rhs == nil }
        return lhs.distance(to: rhs) <= 24
    }

    private func semanticContextMatches(
        _ original: NativeObservationNode,
        _ candidate: NativeObservationNode,
        baseline: NativeCapturedObservation,
        current: NativeCapturedObservation
    ) -> Bool {
        original.path.dropLast() == candidate.path.dropLast()
            && framesWithinDrift(original.frame, candidate.frame)
            && ancestorSignature(of: original, in: baseline)
                == ancestorSignature(of: candidate, in: current)
    }

    private func ancestorSignature(
        of node: NativeObservationNode,
        in snapshot: NativeCapturedObservation
    ) -> [String] {
        var result: [String] = []
        var parentRef = node.parentRef
        while let ref = parentRef,
              let parent = snapshot.nodes.first(where: { $0.ref == ref }) {
            result.append([
                parent.role,
                parent.subrole ?? "",
                parent.title ?? "",
                parent.description ?? "",
                parent.identifier ?? "",
            ].joined(separator: "\u{1f}"))
            parentRef = parent.parentRef
        }
        return result
    }
}
