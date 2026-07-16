import Foundation
import Security

enum BridgeToken {
    static let labMarker = "/Users/admin/.conn-lab-guest"

    static func generate() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "secure bridge token generation failed")
        return Data(bytes).base64EncodedString()
    }

    static func resolve(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        fileExists: (String) -> Bool = {
            FileManager.default.fileExists(atPath: $0)
        },
        generate: () -> String = BridgeToken.generate
    ) -> String {
        guard environment["CONN_LAB_GUEST"] == "1",
              environment["CONN_SERVER_PORT"] == "18787",
              fileExists(labMarker),
              let token = environment["CONN_BRIDGE_TOKEN"],
              Data(base64Encoded: token)?.count == 32 else {
            return generate()
        }
        return token
    }
}

enum BridgeChallenge {
    static func generate() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(
            status == errSecSuccess,
            "secure bridge challenge generation failed"
        )
        return encode(Data(bytes))
    }

    static func encode(_ data: Data) -> String {
        data.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}
