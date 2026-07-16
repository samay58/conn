import XCTest
@testable import Conn

final class InstalledAppResolverTests: XCTestCase {
    func testInstalledAppOutsideConfiguredHintsResolvesToExactIdentity() {
        let app = fixtureApp(name: "Fixture Browser", bundleID: "com.example.browser")
        let resolver = NativeApplicationResolver(applications: { [app] })

        let result = resolver.resolve(
            name: "Fixture Browser", bundleHint: nil, deniedBundles: []
        )

        guard case .resolved(let binding) = result else {
            return XCTFail("expected one installed identity")
        }
        XCTAssertEqual(binding.bundleID, "com.example.browser")
        XCTAssertEqual(binding.teamID, "FIXTURE001")
        XCTAssertEqual(binding.bundleURL, app.bundleURL)
    }

    func testDuplicateNamesReturnDeterministicRealCandidates() {
        let one = fixtureApp(name: "Fixture", bundleID: "com.example.one")
        let two = fixtureApp(name: "Fixture", bundleID: "com.example.two")
        let resolver = NativeApplicationResolver(applications: { [two, one] })

        let result = resolver.resolve(name: "Fixture", bundleHint: nil, deniedBundles: [])

        guard case .ambiguous(let candidates) = result else {
            return XCTFail("expected ambiguity")
        }
        XCTAssertEqual(candidates.map(\.bundleID), ["com.example.one", "com.example.two"])
        XCTAssertEqual(candidates.map(\.display), [
            "Fixture (com.example.one)",
            "Fixture (com.example.two)",
        ])
    }

    func testDuplicateDescriptorBindsTheExactInstallation() {
        let one = NativeInstalledApplication(
            name: "Fixture",
            bundleID: "com.example.fixture",
            teamID: "FIXTURE001",
            bundleURL: URL(fileURLWithPath: "/Applications/Fixture.app"),
            identityFingerprint: "identity-one",
            handlesHTTP: false
        )
        let two = NativeInstalledApplication(
            name: "Fixture",
            bundleID: "com.example.fixture",
            teamID: "FIXTURE001",
            bundleURL: URL(fileURLWithPath: "/Users/test/Applications/Fixture.app"),
            identityFingerprint: "identity-two",
            handlesHTTP: false
        )
        let resolver = NativeApplicationResolver(applications: { [one, two] })
        guard case .ambiguous(let candidates) = resolver.resolve(
            name: "Fixture", bundleHint: nil, deniedBundles: []
        ) else { return XCTFail("expected duplicate candidates") }

        let result = resolver.resolve(
            name: candidates[1].display, bundleHint: nil, deniedBundles: []
        )

        guard case .resolved(let binding) = result else {
            return XCTFail("expected exact descriptor binding")
        }
        XCTAssertEqual(binding.bundleURL, two.bundleURL)
        XCTAssertEqual(binding.identityFingerprint, "identity-two")
    }

    func testDeniedAndUnprovenIdentitiesRefuse() {
        let denied = fixtureApp(name: "Denied", bundleID: "com.example.denied")
        let unsigned = NativeInstalledApplication(
            name: "Unsigned",
            bundleID: "com.example.unsigned",
            teamID: nil,
            bundleURL: URL(fileURLWithPath: "/Applications/Unsigned.app"),
            identityFingerprint: "",
            handlesHTTP: false
        )
        let resolver = NativeApplicationResolver(applications: { [denied, unsigned] })

        XCTAssertEqual(
            resolver.resolve(
                name: "Denied", bundleHint: nil,
                deniedBundles: ["com.example.denied"]
            ).failureReason,
            "denied_bundle"
        )
        XCTAssertEqual(
            resolver.resolve(
                name: "Unsigned", bundleHint: nil, deniedBundles: []
            ).failureReason,
            "app_identity_unproven"
        )
    }

    func testCurrentBrowserMustBeTheFrontmostRegisteredHTTPHandler() {
        let browser = fixtureApp(
            name: "Fixture Browser", bundleID: "com.example.browser",
            handlesHTTP: true
        )
        let editor = fixtureApp(name: "Fixture Editor", bundleID: "com.example.editor")
        let resolver = NativeApplicationResolver(applications: { [browser, editor] })

        let resolved = resolver.resolveBrowser(
            scope: nil,
            currentBundleID: "com.example.browser",
            bundleHint: nil,
            deniedBundles: []
        )
        let refused = resolver.resolveBrowser(
            scope: nil,
            currentBundleID: "com.example.editor",
            bundleHint: nil,
            deniedBundles: []
        )

        guard case .resolved(let binding) = resolved else {
            return XCTFail("expected current browser")
        }
        XCTAssertEqual(binding.bundleID, "com.example.browser")
        XCTAssertEqual(refused.failureReason, "current_app_not_browser")
    }

    private func fixtureApp(
        name: String,
        bundleID: String,
        handlesHTTP: Bool = false
    ) -> NativeInstalledApplication {
        NativeInstalledApplication(
            name: name,
            bundleID: bundleID,
            teamID: "FIXTURE001",
            bundleURL: URL(fileURLWithPath: "/Applications/\(name).app"),
            identityFingerprint: "identity-\(bundleID)",
            handlesHTTP: handlesHTTP
        )
    }
}
