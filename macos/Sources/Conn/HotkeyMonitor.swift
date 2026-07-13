import AppKit

final class HotkeyMonitor {
    enum Binding: String, CaseIterable {
        case rightCommand = "right_command"
        case leftControl = "left_control"
        case leftOption = "left_option"
        case rightControl = "right_control"
        case rightOption = "right_option"
        case f13

        static let defaultsKey = "pttKey"

        var title: String {
            switch self {
            case .rightCommand: "Right Command"
            case .leftControl: "Left Control"
            case .leftOption: "Left Option"
            case .rightControl: "Right Control"
            case .rightOption: "Right Option"
            case .f13: "F13"
            }
        }

        var keyCode: UInt16 {
            switch self {
            case .rightCommand: 54
            case .leftControl: 59
            case .leftOption: 58
            case .rightControl: 62
            case .rightOption: 61
            case .f13: 105
            }
        }

        var modifier: NSEvent.ModifierFlags? {
            switch self {
            case .rightCommand: .command
            case .leftControl, .rightControl: .control
            case .leftOption, .rightOption: .option
            case .f13: nil
            }
        }

        var eventMask: NSEvent.EventTypeMask {
            modifier == nil ? [.keyDown, .keyUp] : .flagsChanged
        }
    }

    private var monitors: [Any] = []
    private var held = false
    private var started = false
    private let defaults: UserDefaults
    private(set) var binding: Binding
    var onDown: (() -> Void)?
    var onUp: (() -> Void)?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        binding = defaults.string(forKey: Binding.defaultsKey)
            .flatMap(Binding.init(rawValue:)) ?? .rightCommand
    }

    var trusted: Bool { AXIsProcessTrusted() }

    func promptForTrust() {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true]
        AXIsProcessTrustedWithOptions(options as CFDictionary)
    }

    func setBinding(_ newBinding: Binding) {
        transition(to: false)
        binding = newBinding
        defaults.set(newBinding.rawValue, forKey: Binding.defaultsKey)
        if started {
            installMonitors()
        }
    }

    func handle(
        keyCode: UInt16,
        eventType: NSEvent.EventType,
        modifierFlags: NSEvent.ModifierFlags,
        isRepeat: Bool = false
    ) {
        guard keyCode == binding.keyCode else { return }
        if let modifier = binding.modifier {
            guard eventType == .flagsChanged else { return }
            transition(to: modifierFlags.contains(modifier))
        } else {
            guard !isRepeat else { return }
            if eventType == .keyDown {
                transition(to: true)
            } else if eventType == .keyUp {
                transition(to: false)
            }
        }
    }

    func start() {
        guard !started else { return }
        started = true
        installMonitors()
    }

    func stop() {
        transition(to: false)
        removeMonitors()
        started = false
    }

    private func installMonitors() {
        removeMonitors()
        let handle: (NSEvent) -> Void = { [weak self] event in
            self?.handle(
                keyCode: event.keyCode,
                eventType: event.type,
                modifierFlags: event.modifierFlags,
                isRepeat: event.isARepeat
            )
        }
        let mask = binding.eventMask
        if let global = NSEvent.addGlobalMonitorForEvents(matching: mask,
                                                          handler: handle) {
            monitors.append(global)
        }
        if let local = NSEvent.addLocalMonitorForEvents(matching: mask,
                                                        handler: { handle($0); return $0 }) {
            monitors.append(local)
        }
    }

    private func removeMonitors() {
        for monitor in monitors {
            NSEvent.removeMonitor(monitor)
        }
        monitors.removeAll()
    }

    private func transition(to down: Bool) {
        if down, !held {
            held = true
            onDown?()
        } else if !down, held {
            held = false
            onUp?()
        }
    }
}
