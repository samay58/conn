import CoreGraphics

enum NativeKeyChord {
    static let modifierFlags: [String: CGEventFlags] = [
        "cmd": .maskCommand,
        "shift": .maskShift,
        "alt": .maskAlternate,
        "ctrl": .maskControl,
    ]

    static let keyCodes: [String: CGKeyCode] = [
        "a": 0x00, "b": 0x0B, "c": 0x08, "d": 0x02, "e": 0x0E, "f": 0x03,
        "g": 0x05, "h": 0x04, "i": 0x22, "j": 0x26, "k": 0x28, "l": 0x25,
        "m": 0x2E, "n": 0x2D, "o": 0x1F, "p": 0x23, "q": 0x0C, "r": 0x0F,
        "s": 0x01, "t": 0x11, "u": 0x20, "v": 0x09, "w": 0x0D, "x": 0x07,
        "y": 0x10, "z": 0x06,
        "0": 0x1D, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17,
        "6": 0x16, "7": 0x1A, "8": 0x1C, "9": 0x19,
        "return": 0x24, "tab": 0x30, "space": 0x31, "escape": 0x35,
        "delete": 0x33, "up": 0x7E, "down": 0x7D, "left": 0x7B, "right": 0x7C,
    ]

    static func parse(_ keys: [String]) -> (CGKeyCode, CGEventFlags)? {
        var flags: CGEventFlags = []
        var primary: CGKeyCode?
        for key in keys {
            if let modifier = modifierFlags[key] {
                flags.insert(modifier)
            } else if let code = keyCodes[key], primary == nil {
                primary = code
            } else {
                return nil
            }
        }
        guard let primary else { return nil }
        return (primary, flags)
    }
}
