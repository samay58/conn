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

    func captureMenuForPreparation(
        request: NativeActionRequest,
        query: NativeObservationQuery,
        matchingTitles: Set<String>
    ) -> [NativeCapturedObservation]

    func beginEvidenceObservation(
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    )

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool

    func applicationBindingMatches(_ binding: NativeApplicationBinding) -> Bool
}

extension NativeSemanticBackend {
    func captureMenuForPreparation(
        request: NativeActionRequest,
        query: NativeObservationQuery,
        matchingTitles: Set<String>
    ) -> [NativeCapturedObservation] { [] }

    func beginEvidenceObservation(
        request: NativeActionRequest,
        target: NativeResolvedTarget?
    ) {}

    func applicationIdentityMatches(
        request: NativeActionRequest,
        observation: NativeCapturedObservation
    ) -> Bool { true }

    func applicationBindingMatches(_ binding: NativeApplicationBinding) -> Bool { true }
}

enum NativeResolutionError: Error, Equatable {
    case staleSnapshot
    case staleApplication
    case staleProcess
    case staleWindow
    case secureTransition
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

    func observeMenuForPreparation(
        request: NativeActionRequest,
        query: NativeObservationQuery,
        matchingTitles: Set<String>
    ) -> [NativeCapturedObservation] {
        let captured = backend.captureMenuForPreparation(
            request: request,
            query: query,
            matchingTitles: matchingTitles
        )
        for snapshot in captured {
            snapshots[snapshot.snapshotID] = snapshot
        }
        return captured
    }

    func resolve(
        target: NativeActionTarget,
        baseline: NativeCapturedObservation,
        current: NativeCapturedObservation
    ) -> Result<NativeResolvedTarget, NativeResolutionError> {
        resolve(
            target: target,
            baseline: baseline,
            current: current,
            allowAnonymousWitness: false,
            mutableCollectionDescription: false
        )
    }

    func resolveWitness(
        target: NativeActionTarget,
        baseline: NativeCapturedObservation,
        current: NativeCapturedObservation
    ) -> Result<NativeResolvedTarget, NativeResolutionError> {
        resolve(
            target: target,
            baseline: baseline,
            current: current,
            allowAnonymousWitness: true,
            mutableCollectionDescription: false
        )
    }

    func resolveCollectionWitness(
        target: NativeActionTarget,
        baseline: NativeCapturedObservation,
        current: NativeCapturedObservation
    ) -> Result<NativeResolvedTarget, NativeResolutionError> {
        resolve(
            target: target,
            baseline: baseline,
            current: current,
            allowAnonymousWitness: true,
            mutableCollectionDescription: true
        )
    }

    private func resolve(
        target: NativeActionTarget,
        baseline: NativeCapturedObservation,
        current: NativeCapturedObservation,
        allowAnonymousWitness: Bool,
        mutableCollectionDescription: Bool
    ) -> Result<NativeResolvedTarget, NativeResolutionError> {
        guard baseline.turnID == current.turnID,
              baseline.observationEpoch == current.observationEpoch else {
            return .failure(.staleSnapshot)
        }
        if baseline.bundleID != current.bundleID
            || target.bundleID.map({ $0 != current.bundleID }) == true {
            return .failure(.staleApplication)
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
        let semanticMatches = current.nodes.filter { candidate in
            candidate.role == original.role
                && (
                    mutableCollectionDescription
                    ? candidate.subrole == original.subrole
                        && candidate.title == original.title
                    : candidate.semanticFingerprint == original.semanticFingerprint
                )
                && candidate.supportedActions == original.supportedActions
                && (original.identifier == nil
                    || candidate.identifier == original.identifier)
                && (
                    target.descendantKey == nil
                        || Self.descendantSemanticKey(
                            of: candidate, in: current
                        ) == target.descendantKey
                )
        }
        guard allowAnonymousWitness
                || hasSemanticName(original)
                || target.descendantKey != nil else {
            return .failure(semanticMatches.count > 1 ? .ambiguous : .missingTarget)
        }
        if semanticMatches.contains(where: { $0.secure }) {
            return .failure(.secureTransition)
        }
        let fullMatches = semanticMatches.filter { candidate in
            candidate.path == original.path
                && candidate.siblingSignature == original.siblingSignature
                && framesWithinDrift(candidate.frame, original.frame)
                && (
                    mutableCollectionDescription
                    ? collectionAncestorSignature(of: original, in: baseline)
                        == collectionAncestorSignature(
                            of: candidate, in: current
                        )
                    : ancestorSignature(of: original, in: baseline)
                        == ancestorSignature(of: candidate, in: current)
                )
        }
        if fullMatches.count == 1 {
            return .success(NativeResolvedTarget(
                original: original,
                current: fullMatches[0],
                resolution: "full_locator"
            ))
        }
        return .failure(fullMatches.isEmpty ? .missingTarget : .ambiguous)
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

    private func hasSemanticName(_ node: NativeObservationNode) -> Bool {
        [node.title, node.description, node.identifier].contains { value in
            !normalize(value).isEmpty
        }
    }

    static func descendantSemanticKey(
        of node: NativeObservationNode,
        in snapshot: NativeCapturedObservation
    ) -> String? {
        let descendants = snapshot.nodes.filter {
            isDescendant($0, of: node.ref, in: snapshot)
        }.sorted { lhs, rhs in
            lhs.path.lexicographicallyPrecedes(rhs.path)
        }
        if let text = descendants.first(where: {
            !$0.secure && $0.role == "AXStaticText" && $0.valueHash != nil
        }), let valueHash = text.valueHash {
            return NativeHash.sha256(
                "\(text.role)\u{1f}\(valueHash)"
            )
        }
        for descendant in descendants where !descendant.secure {
            let value = [
                descendant.title,
                descendant.description,
                descendant.identifier,
            ].compactMap {
                $0?.trimmingCharacters(in: .whitespacesAndNewlines)
            }.first { !$0.isEmpty }
            if let value {
                let normalized = value.folding(
                    options: [.caseInsensitive, .diacriticInsensitive],
                    locale: .current
                )
                return NativeHash.sha256(
                    "\(descendant.role)\u{1f}\(normalized)"
                )
            }
        }
        return nil
    }

    private static func isDescendant(
        _ node: NativeObservationNode,
        of ancestorRef: String,
        in snapshot: NativeCapturedObservation
    ) -> Bool {
        var parentRef = node.parentRef
        var visited = Set<String>()
        while let ref = parentRef, visited.insert(ref).inserted {
            if ref == ancestorRef { return true }
            parentRef = snapshot.nodes.first { $0.ref == ref }?.parentRef
        }
        return false
    }

    private func framesWithinDrift(_ lhs: NativeRect?, _ rhs: NativeRect?) -> Bool {
        guard let lhs, let rhs else { return lhs == nil && rhs == nil }
        return lhs.distance(to: rhs) <= 24
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

    private func collectionAncestorSignature(
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
                parent.identifier ?? "",
            ].joined(separator: "\u{1f}"))
            parentRef = parent.parentRef
        }
        return result
    }
}
