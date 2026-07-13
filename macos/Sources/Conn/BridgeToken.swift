import Foundation
import Security

enum BridgeToken {
    static func generate() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "secure bridge token generation failed")
        return Data(bytes).base64EncodedString()
    }
}
