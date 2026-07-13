// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Conn",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Conn",
            path: "Sources/Conn"
        ),
        .executableTarget(
            name: "ConnActionFixture",
            path: "Sources/ConnActionFixture",
            exclude: ["Info.plist"]
        ),
        .testTarget(
            name: "ConnTests",
            dependencies: ["Conn", "ConnActionFixture"],
            path: "Tests/ConnTests"
        )
    ]
)
