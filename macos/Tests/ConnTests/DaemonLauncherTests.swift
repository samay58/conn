import XCTest
@testable import Conn

final class DaemonLauncherTests: XCTestCase {
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
