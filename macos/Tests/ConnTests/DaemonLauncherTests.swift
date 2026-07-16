import XCTest
@testable import Conn

final class DaemonLauncherTests: XCTestCase {
    func testLoopbackEndpointUsesLabPortFromEnvironment() {
        let endpoint = DaemonEndpoint.resolve(
            environment: ["CONN_SERVER_PORT": "18787"]
        )

        XCTAssertEqual(endpoint.port, 18787)
        XCTAssertEqual(endpoint.webSocket.absoluteString, "ws://127.0.0.1:18787/ws")
        XCTAssertEqual(endpoint.health.absoluteString, "http://127.0.0.1:18787/healthz")
        XCTAssertEqual(endpoint.appHealth.absoluteString, "http://127.0.0.1:18787/app-healthz")
        XCTAssertEqual(endpoint.console.absoluteString, "http://127.0.0.1:18787")
    }

    func testInvalidEndpointPortFallsBackToProductionPort() {
        for value in ["0", "65536", "8787oops"] {
            XCTAssertEqual(
                DaemonEndpoint.resolve(
                    environment: ["CONN_SERVER_PORT": value]
                ).port,
                8787
            )
        }
    }

    func testLabModeSelectsBoundedScriptedDaemonArguments() {
        XCTAssertEqual(
            DaemonLauncher.launchArguments(
                environment: ["CONN_DAEMON_MODE": "scripted"]
            ),
            ["-m", "conn", "--demo", "--no-audio", "--no-hotkey"]
        )
    }

    func testUnknownDaemonModeUsesLiveArguments() {
        XCTAssertEqual(
            DaemonLauncher.launchArguments(
                environment: ["CONN_DAEMON_MODE": "anything"]
            ),
            ["-m", "conn", "--no-hotkey"]
        )
    }

    func testEnvironmentPathsWinWhenBothAreSet() {
        let config = DaemonLauncher.resolveConfig(
            environment: [
                "CONN_PROJECT_ROOT": "/tmp/conn",
                "CONN_PYTHON": "/tmp/python",
            ],
            fileExists: { _ in false }
        )

        XCTAssertEqual(config, DaemonLaunchConfig(python: "/tmp/python", projectRoot: "/tmp/conn"))
    }

    func testDefaultPhoenixPathsAreFallbackWhenTheyExist() {
        let existing: Set<String> = [
            DaemonLauncher.defaultProjectRoot,
            DaemonLauncher.defaultPython,
        ]

        let config = DaemonLauncher.resolveConfig(
            environment: [:],
            fileExists: { existing.contains($0) }
        )

        XCTAssertEqual(
            config,
            DaemonLaunchConfig(
                python: DaemonLauncher.defaultPython,
                projectRoot: DaemonLauncher.defaultProjectRoot
            )
        )
    }

    func testMissingEnvironmentAndDefaultsReturnNil() {
        let config = DaemonLauncher.resolveConfig(
            environment: ["CONN_PROJECT_ROOT": "/tmp/conn"],
            fileExists: { _ in false }
        )

        XCTAssertNil(config)
    }
}
