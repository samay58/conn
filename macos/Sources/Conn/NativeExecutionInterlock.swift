import Foundation

enum NativeExecutionCheck: Equatable {
    case allowed
    case suspended
    case staleConnection
    case staleGrant
}

final class NativeExecutionInterlock: @unchecked Sendable {
    private let lock = NSLock()
    private var connectionID: String?
    private var generation: Int?
    private var suspended = true

    func beginConnection(_ connectionID: String) {
        lock.withLock {
            self.connectionID = connectionID
            generation = nil
            suspended = true
        }
    }

    @discardableResult
    func accept(connectionID: String, generation: Int, suspended: Bool) -> Bool {
        lock.withLock {
            guard connectionID == self.connectionID else { return false }
            self.generation = generation
            self.suspended = suspended
            return true
        }
    }

    func suspend() {
        lock.withLock { suspended = true }
    }

    func disconnect(_ connectionID: String) {
        lock.withLock {
            guard connectionID == self.connectionID else { return }
            self.connectionID = nil
            generation = nil
            suspended = true
        }
    }

    func check(connectionID: String, generation: Int) -> NativeExecutionCheck {
        lock.withLock {
            guard connectionID == self.connectionID else { return .staleConnection }
            guard !suspended else { return .suspended }
            guard generation == self.generation else { return .staleGrant }
            return .allowed
        }
    }
}
