import XCTest
@testable import Conn

final class BridgeAuthenticationTests: XCTestCase {
    func testWebSocketHandshakeUsesProofAndGatesPrivilegedFramesUntilHello() {
        var handshake = DaemonHandshake(bridgeToken: "secret")
        let connection = handshake.beginConnection()
        XCTAssertFalse(handshake.canCompleteHello(on: connection))

        let response = handshake.respondToChallenge(
            connection: connection,
            challenge: "nonce",
            method: "hmac-sha256"
        )
        XCTAssertEqual(response?["type"] as? String, "client_hello")
        XCTAssertEqual(response?["role"] as? String, "app")
        XCTAssertEqual(
            response?["proof"] as? String,
            "e394df63d8f47be430292929ac34246acb47f099cc26643f9a721edf748ecc1b"
        )
        XCTAssertNil(response?["bridge_token"])
        XCTAssertFalse(handshake.allowsPrivilegedFrames(on: connection))
        XCTAssertTrue(handshake.canCompleteHello(on: connection))

        let serverProof = BridgeAuthentication.proof(
            token: "secret",
            context: BridgeAuthentication.daemonWebSocketContext,
            challenge: "nonce"
        )
        XCTAssertTrue(handshake.completeAfterHello(
            connection: connection,
            serverProof: serverProof
        ))
        XCTAssertTrue(handshake.allowsPrivilegedFrames(on: connection))
        XCTAssertFalse(handshake.canCompleteHello(on: connection))
    }

    func testWebSocketHandshakeRejectsStaleConnectionAndServerProofReplay() {
        var handshake = DaemonHandshake(bridgeToken: "secret")
        let staleConnection = handshake.beginConnection()
        XCTAssertNotNil(handshake.respondToChallenge(
            connection: staleConnection,
            challenge: "old",
            method: "hmac-sha256"
        ))
        let staleProof = BridgeAuthentication.proof(
            token: "secret",
            context: BridgeAuthentication.daemonWebSocketContext,
            challenge: "old"
        )

        let currentConnection = handshake.beginConnection()
        XCTAssertFalse(handshake.completeAfterHello(
            connection: staleConnection,
            serverProof: staleProof
        ))
        XCTAssertFalse(handshake.allowsPrivilegedFrames(on: staleConnection))

        XCTAssertNotNil(handshake.respondToChallenge(
            connection: currentConnection,
            challenge: "fresh",
            method: "hmac-sha256"
        ))
        XCTAssertNil(handshake.respondToChallenge(
            connection: currentConnection,
            challenge: "fresh",
            method: "hmac-sha256"
        ))
        XCTAssertFalse(handshake.completeAfterHello(
            connection: currentConnection,
            serverProof: staleProof
        ))
        XCTAssertFalse(handshake.allowsPrivilegedFrames(on: currentConnection))
        XCTAssertFalse(handshake.canCompleteHello(on: currentConnection))
    }

    func testWebSocketHandshakeRejectsBareAndWrongServerProof() {
        for serverProof in ["", "not-a-valid-proof"] {
            var handshake = DaemonHandshake(bridgeToken: "secret")
            let connection = handshake.beginConnection()
            XCTAssertNotNil(handshake.respondToChallenge(
                connection: connection,
                challenge: "fresh",
                method: "hmac-sha256"
            ))

            XCTAssertFalse(handshake.completeAfterHello(
                connection: connection,
                serverProof: serverProof
            ))
            XCTAssertFalse(handshake.allowsPrivilegedFrames(on: connection))
            XCTAssertFalse(handshake.canCompleteHello(on: connection))
        }
    }

    func testNativeRequestReplayGuardRejectsDuplicateAndLowerSequence() {
        var replayGuard = NativeRequestReplayGuard()
        let connection = UUID()
        replayGuard.beginAuthenticatedConnection(connection)

        let first: [String: Any] = [
            "type": "ax_action",
            "request_id": "request-1",
            "turn_id": "turn-1",
            "observation_epoch": 2,
            "sequence": 8,
        ]
        XCTAssertTrue(replayGuard.accept(first, connection: connection))
        XCTAssertFalse(replayGuard.accept(first, connection: connection))

        var lower = first
        lower["request_id"] = "request-lower"
        lower["sequence"] = 7
        XCTAssertFalse(replayGuard.accept(lower, connection: connection))

        var next = first
        next["request_id"] = "request-2"
        next["sequence"] = 9
        XCTAssertTrue(replayGuard.accept(next, connection: connection))
    }

    func testNativeRequestReplayGuardResetsOnlyForAuthenticatedConnection() {
        var replayGuard = NativeRequestReplayGuard()
        let oldConnection = UUID()
        let newConnection = UUID()
        replayGuard.beginAuthenticatedConnection(oldConnection)

        let request: [String: Any] = [
            "type": "ax_read",
            "request_id": "request-1",
            "turn_id": "turn-1",
            "observation_epoch": 1,
            "sequence": 4,
        ]
        XCTAssertTrue(replayGuard.accept(request, connection: oldConnection))
        XCTAssertFalse(replayGuard.accept(request, connection: newConnection))

        replayGuard.beginAuthenticatedConnection(newConnection)
        XCTAssertFalse(replayGuard.accept(request, connection: oldConnection))
        XCTAssertTrue(replayGuard.accept(request, connection: newConnection))

        var malformed = request
        malformed.removeValue(forKey: "turn_id")
        malformed["sequence"] = 5
        XCTAssertFalse(replayGuard.accept(malformed, connection: newConnection))
    }

    @MainActor
    func testNativeActionPolicyRejectsLegacyExecutorOperations() {
        XCTAssertNil(DaemonClient.rejectedNativeActionData(for: "observe"))
        XCTAssertNil(DaemonClient.rejectedNativeActionData(for: "observe_visual"))

        let rejection = DaemonClient.rejectedNativeActionData(for: "press_menu_path")

        XCTAssertEqual(rejection?["outcome"] as? String, "failed")
        XCTAssertEqual(rejection?["dispatch_state"] as? String, "not_dispatched")
        XCTAssertEqual(rejection?["retry_safe"] as? Bool, true)
        XCTAssertEqual(rejection?["error"] as? String, "semantic_operation_required")
    }

    func testGeneratedBridgeTokenIs256Bits() {
        let token = BridgeToken.generate()
        XCTAssertEqual(Data(base64Encoded: token)?.count, 32)
    }

    func testLabGuestCanUseRunnerOwnedBridgeToken() {
        let token = Data(repeating: 7, count: 32).base64EncodedString()

        XCTAssertEqual(
            BridgeToken.resolve(
                environment: [
                    "CONN_LAB_GUEST": "1",
                    "CONN_SERVER_PORT": "18787",
                    "CONN_BRIDGE_TOKEN": token,
                ],
                fileExists: { $0 == "/Users/admin/.conn-lab-guest" },
                generate: { "generated" }
            ),
            token
        )
    }

    func testBridgeTokenOverrideIsRefusedOutsideMarkedLabGuest() {
        let token = Data(repeating: 7, count: 32).base64EncodedString()
        let environments = [
            ["CONN_SERVER_PORT": "18787", "CONN_BRIDGE_TOKEN": token],
            [
                "CONN_LAB_GUEST": "1",
                "CONN_SERVER_PORT": "8787",
                "CONN_BRIDGE_TOKEN": token,
            ],
            [
                "CONN_LAB_GUEST": "1",
                "CONN_SERVER_PORT": "18787",
                "CONN_BRIDGE_TOKEN": "short",
            ],
        ]

        for environment in environments {
            XCTAssertEqual(
                BridgeToken.resolve(
                    environment: environment,
                    fileExists: { _ in false },
                    generate: { "generated" }
                ),
                "generated"
            )
        }
    }

    func testGeneratedHealthChallengeUsesOnlyServerAcceptedCharacters() {
        XCTAssertEqual(BridgeChallenge.encode(Data([0xfb, 0xff])), "-_8")

        let challenge = BridgeChallenge.generate()
        XCTAssertEqual(challenge.count, 43)
        XCTAssertNotNil(
            challenge.range(
                of: #"^[A-Za-z0-9_-]+$"#,
                options: .regularExpression
            )
        )
    }

    func testLauncherEnvironmentPassesTokenOnlyToChild() {
        let environment = DaemonLauncher.launchEnvironment(
            base: ["PATH": "/usr/bin"], bridgeToken: "secret")

        XCTAssertEqual(environment["CONN_BRIDGE_TOKEN"], "secret")
        XCTAssertEqual(environment["PYTHONPATH"], "src")
    }

    func testLauncherHealthRequestUsesChallengeAndRequiresMatchingProof() {
        let request = DaemonLauncher.authenticatedHealthRequest(challenge: "health-nonce")

        XCTAssertEqual(request.url?.path, "/app-healthz")
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "X-Conn-Challenge"),
            "health-nonce"
        )
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Conn-Bridge-Token"))

        let response = Data(
            #"{"bridge_proof":"6379ee9da4da62ddb9041309dd1a762fe72642a2efff5b76561bd6c4d25ea959"}"#.utf8
        )
        XCTAssertTrue(DaemonLauncher.shouldAdopt(
            healthzBody: response,
            bridgeToken: "secret",
            challenge: "health-nonce"
        ))
        XCTAssertFalse(DaemonLauncher.shouldAdopt(
            healthzBody: response,
            bridgeToken: "secret",
            challenge: "replayed-under-another-challenge"
        ))

        let unhealthyResponse = Data(
            #"{"bridge_proof":"6379ee9da4da62ddb9041309dd1a762fe72642a2efff5b76561bd6c4d25ea959","phase":"failed","phase_age_s":180,"upstream_connected":false}"#.utf8
        )
        XCTAssertTrue(DaemonLauncher.isAuthenticatedHealth(
            healthzBody: unhealthyResponse,
            bridgeToken: "secret",
            challenge: "health-nonce"
        ))
        XCTAssertFalse(DaemonLauncher.shouldAdopt(
            healthzBody: unhealthyResponse,
            bridgeToken: "secret",
            challenge: "health-nonce"
        ))
    }
}
