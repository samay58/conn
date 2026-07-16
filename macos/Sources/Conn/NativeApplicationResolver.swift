import AppKit
import CryptoKit
import Foundation
import Security

struct NativeInstalledApplication: Equatable {
    let name: String
    let bundleID: String
    let teamID: String?
    let bundleURL: URL
    let identityFingerprint: String
    let handlesHTTP: Bool

    var binding: NativeApplicationBinding {
        NativeApplicationBinding(
            name: name,
            bundleID: bundleID,
            teamID: teamID,
            bundleURL: bundleURL,
            identityFingerprint: identityFingerprint
        )
    }
}

struct NativeApplicationBinding: Equatable {
    let name: String
    let bundleID: String
    let teamID: String?
    let bundleURL: URL
    let identityFingerprint: String
}

struct NativeApplicationCandidate: Equatable {
    let display: String
    let appName: String
    let bundleID: String

    var dictionary: [String: Any] {
        ["display": display, "app_name": appName, "bundle_id": bundleID]
    }
}

enum NativeApplicationResolution {
    case resolved(NativeApplicationBinding)
    case ambiguous([NativeApplicationCandidate])
    case failed(String)

    var failureReason: String? {
        if case .failed(let reason) = self { return reason }
        return nil
    }
}

final class NativeApplicationResolver {
    private let inventory: (String, String?) -> [NativeInstalledApplication]

    init() {
        inventory = Self.installedApplications
    }

    init(applications: @escaping () -> [NativeInstalledApplication]) {
        inventory = { _, _ in applications() }
    }

    func resolve(
        name: String,
        bundleHint: String?,
        deniedBundles: Set<String>
    ) -> NativeApplicationResolution {
        let query = normalized(name)
        guard !query.isEmpty else { return .failed("app_name_missing") }
        let inventory = inventory(name, bundleHint)
        let named = inventory.filter { normalized($0.name) == query }
        let described = named.isEmpty
            ? inventory.filter {
                normalized(baseDisplay($0)) == query
                    || normalized(
                        "\(baseDisplay($0)) at \($0.bundleURL.deletingLastPathComponent().path)"
                    ) == query
            }
            : named
        guard !described.isEmpty else { return .failed("app_not_found") }

        let allowed = described.filter { !deniedBundles.contains($0.bundleID) }
        guard !allowed.isEmpty else { return .failed("denied_bundle") }
        let proven = allowed.filter(Self.identityIsProven)
        guard !proven.isEmpty else { return .failed("app_identity_unproven") }
        let unique = Dictionary(grouping: proven) {
            "\($0.bundleURL.standardizedFileURL.path)\u{1f}\($0.identityFingerprint)"
        }.compactMap(\.value.first)
        if unique.count == 1, let app = unique.first { return .resolved(app.binding) }
        return .ambiguous(candidateDescriptions(unique))
    }

    func resolveBrowser(
        scope: String?,
        currentBundleID: String?,
        bundleHint: String?,
        deniedBundles: Set<String>
    ) -> NativeApplicationResolution {
        if let scope = scope?.trimmingCharacters(in: .whitespacesAndNewlines),
           !scope.isEmpty {
            switch resolve(
                name: scope,
                bundleHint: bundleHint,
                deniedBundles: deniedBundles
            ) {
            case .resolved(let binding):
                let app = inventory(scope, bundleHint).first {
                    $0.bundleURL.standardizedFileURL == binding.bundleURL.standardizedFileURL
                        && $0.identityFingerprint == binding.identityFingerprint
                }
                return app?.handlesHTTP == true
                    ? .resolved(binding) : .failed("app_not_browser")
            case .ambiguous(let candidates): return .ambiguous(candidates)
            case .failed(let reason): return .failed(reason)
            }
        }
        guard let currentBundleID else { return .failed("current_browser_unavailable") }
        let matches = inventory("", currentBundleID).filter {
            $0.bundleID == currentBundleID && $0.handlesHTTP
                && !deniedBundles.contains($0.bundleID)
                && Self.identityIsProven($0)
        }
        if matches.count == 1, let app = matches.first { return .resolved(app.binding) }
        if matches.count > 1 { return .ambiguous(candidateDescriptions(matches)) }
        return .failed("current_app_not_browser")
    }

    static func codeSigningRequirement(bundleID: String, teamID: String?) -> String? {
        guard NativeAppIdentity.validBundleID(bundleID) else { return nil }
        if bundleID.hasPrefix("com.apple.") {
            return "anchor apple and identifier \"\(bundleID)\""
        }
        guard let teamID, NativeAppIdentity.validTeamID(teamID) else { return nil }
        return "anchor apple generic and identifier \"\(bundleID)\" "
            + "and certificate leaf[subject.OU] = \"\(teamID)\""
    }

    static func bindingIsValid(_ binding: NativeApplicationBinding) -> Bool {
        guard let current = installedApplication(
            at: binding.bundleURL,
            handlesHTTP: false
        ) else { return false }
        return current.bundleID == binding.bundleID
            && current.teamID == binding.teamID
            && current.identityFingerprint == binding.identityFingerprint
    }

    private func candidateDescriptions(
        _ applications: [NativeInstalledApplication]
    ) -> [NativeApplicationCandidate] {
        let grouped = Dictionary(grouping: applications, by: baseDisplay)
        return applications.map { app in
            let base = baseDisplay(app)
            let display = grouped[base, default: []].count > 1
                ? "\(base) at \(app.bundleURL.deletingLastPathComponent().path)"
                : base
            return NativeApplicationCandidate(
                display: String(display.prefix(160)),
                appName: String(app.name.prefix(128)),
                bundleID: app.bundleID
            )
        }.sorted {
            if $0.display != $1.display { return $0.display < $1.display }
            return $0.bundleID < $1.bundleID
        }.prefix(20).map { $0 }
    }

    private func baseDisplay(_ app: NativeInstalledApplication) -> String {
        "\(app.name) (\(app.bundleID))"
    }

    private func normalized(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }

    private static func identityIsProven(_ app: NativeInstalledApplication) -> Bool {
        !app.identityFingerprint.isEmpty
            && (app.bundleID.hasPrefix("com.apple.")
                || app.teamID.map(NativeAppIdentity.validTeamID) == true)
    }

    private static func installedApplications(
        name: String,
        bundleHint: String?
    ) -> [NativeInstalledApplication] {
        let workspace = NSWorkspace.shared
        var urls: Set<URL> = []
        if let bundleHint, NativeAppIdentity.validBundleID(bundleHint) {
            urls.formUnion(workspace.urlsForApplications(withBundleIdentifier: bundleHint))
        }
        for app in workspace.runningApplications {
            if let url = app.bundleURL { urls.insert(url) }
        }
        let roots = [
            URL(fileURLWithPath: "/Applications", isDirectory: true),
            URL(fileURLWithPath: "/System/Applications", isDirectory: true),
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Applications", isDirectory: true),
        ]
        for root in roots { urls.formUnion(applicationBundles(under: root)) }

        let query = normalizedName(name)
        let candidates = urls.filter { url in
            guard let bundle = Bundle(url: url),
                  let bundleID = bundle.bundleIdentifier else { return false }
            if query.isEmpty { return bundleHint == nil || bundleID == bundleHint }
            let appName = (bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
                ?? (bundle.object(forInfoDictionaryKey: "CFBundleName") as? String)
                ?? url.deletingPathExtension().lastPathComponent
            let normalizedApp = normalizedName(appName)
            return normalizedApp == query
                || query == normalizedName("\(appName) (\(bundleID))")
                || query.hasPrefix(normalizedName("\(appName) (\(bundleID)) at "))
        }

        let handlers = httpHandlerURLs()
        var registered: Set<URL> = []
        for url in candidates {
            guard let bundleID = Bundle(url: url)?.bundleIdentifier else { continue }
            registered.formUnion(workspace.urlsForApplications(withBundleIdentifier: bundleID))
        }
        let allCandidates = Set(candidates).union(registered).filter { url in
            guard let bundle = Bundle(url: url),
                  let bundleID = bundle.bundleIdentifier else { return false }
            if query.isEmpty { return bundleHint == nil || bundleID == bundleHint }
            let appName = (bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
                ?? (bundle.object(forInfoDictionaryKey: "CFBundleName") as? String)
                ?? url.deletingPathExtension().lastPathComponent
            return normalizedName(appName) == query
                || query == normalizedName("\(appName) (\(bundleID))")
                || query.hasPrefix(normalizedName("\(appName) (\(bundleID)) at "))
        }
        return allCandidates.prefix(20).compactMap {
            installedApplication(at: $0, handlesHTTP: handlers.contains($0.standardizedFileURL))
        }
    }

    private static func applicationBundles(under root: URL) -> Set<URL> {
        guard let enumerator = FileManager.default.enumerator(
            at: root,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles, .skipsPackageDescendants]
        ) else { return [] }
        var result: Set<URL> = []
        for case let url as URL in enumerator {
            if url.pathExtension.caseInsensitiveCompare("app") == .orderedSame {
                result.insert(url.standardizedFileURL)
                if result.count == 4096 { break }
            }
        }
        return result
    }

    private static func httpHandlerURLs() -> Set<URL> {
        let workspace = NSWorkspace.shared
        let probes = ["http://conn.invalid", "https://conn.invalid"].compactMap(URL.init)
        let groups = probes.map { Set(workspace.urlsForApplications(toOpen: $0)) }
        guard let first = groups.first else { return [] }
        return groups.dropFirst().reduce(first) { $0.intersection($1) }
            .map(\.standardizedFileURL).reduce(into: Set<URL>()) { $0.insert($1) }
    }

    private static func normalizedName(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines)
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }

    private static func installedApplication(
        at url: URL,
        handlesHTTP: Bool
    ) -> NativeInstalledApplication? {
        let standardized = url.standardizedFileURL
        guard let bundle = Bundle(url: standardized),
              let bundleID = bundle.bundleIdentifier,
              NativeAppIdentity.validBundleID(bundleID) else { return nil }
        let name = (bundle.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String)
            ?? (bundle.object(forInfoDictionaryKey: "CFBundleName") as? String)
            ?? standardized.deletingPathExtension().lastPathComponent
        var staticCode: SecStaticCode?
        guard SecStaticCodeCreateWithPath(
            standardized as CFURL, SecCSFlags(), &staticCode
        ) == errSecSuccess, let staticCode else { return nil }
        var information: CFDictionary?
        guard SecCodeCopySigningInformation(
            staticCode,
            SecCSFlags(rawValue: kSecCSSigningInformation),
            &information
        ) == errSecSuccess,
        let info = information as? [CFString: Any] else { return nil }
        let teamID = info[kSecCodeInfoTeamIdentifier] as? String
        guard let requirementText = codeSigningRequirement(
            bundleID: bundleID, teamID: teamID
        ) else { return nil }
        var requirement: SecRequirement?
        guard SecRequirementCreateWithString(
            requirementText as CFString, SecCSFlags(), &requirement
        ) == errSecSuccess, let requirement,
        SecStaticCodeCheckValidity(
            staticCode,
            SecCSFlags(rawValue: kSecCSCheckAllArchitectures),
            requirement
        ) == errSecSuccess else { return nil }
        let unique = (info[kSecCodeInfoUnique] as? Data)?.map {
            String(format: "%02x", $0)
        }.joined() ?? ""
        let fingerprint = SHA256.hash(
            data: Data("\(standardized.path)\u{1f}\(unique)".utf8)
        ).map { String(format: "%02x", $0) }.joined()
        return NativeInstalledApplication(
            name: String(name.prefix(128)),
            bundleID: bundleID,
            teamID: teamID,
            bundleURL: standardized,
            identityFingerprint: fingerprint,
            handlesHTTP: handlesHTTP
        )
    }
}
