import Foundation

/// Browser URL evidence: how a page's address is read from Accessibility and
/// when an observed address proves that a requested navigation landed.
/// A title is never evidence of a URL; only the web area's own address is.
enum NativeBrowserURL {
    /// Roles that only arrange content. The page's web area sits under a
    /// chain of these in Safari and Chrome; toolbars, tab strips, and the
    /// page's own content are never walked.
    static let containerRoles: Set<String> = [
        "AXSplitGroup", "AXTabGroup", "AXGroup", "AXScrollArea", "AXLayoutArea",
    ]

    /// The outermost AXWebArea elements under `roots`, found by walking
    /// container roles only. The walk stops at each web area, so an embedded
    /// frame's own web area (an ad or a video player) is never mistaken for
    /// the page. Bounded by visit count and depth, independent of the
    /// observation's node budget, so a large toolbar cannot starve it.
    static func outermostWebAreas<Element>(
        roots: [Element],
        role: (Element) -> String?,
        children: (Element) -> [Element],
        maxVisited: Int = 200,
        maxDepth: Int = 14,
        isExpired: () -> Bool = { false }
    ) -> [Element] {
        var queue = roots.map { (element: $0, depth: 1) }
        var found: [Element] = []
        var visited = 0
        while !queue.isEmpty, visited < maxVisited, !isExpired() {
            let next = queue.removeFirst()
            visited += 1
            let nodeRole = role(next.element)
            if nodeRole == "AXWebArea" {
                found.append(next.element)
                continue
            }
            guard let nodeRole, containerRoles.contains(nodeRole),
                  next.depth < maxDepth else { continue }
            queue.append(contentsOf: children(next.element).map {
                (element: $0, depth: next.depth + 1)
            })
        }
        return found
    }

    /// One normalized browser URL when every readable candidate agrees.
    static func uniqueURL(_ candidates: [String?]) -> String? {
        let normalized = Set(candidates.compactMap {
            $0.flatMap(NativeActionCompiler.normalizeBrowserURL)
        })
        return normalized.count == 1 ? normalized.first : nil
    }

    /// The comparison key for "the same page": http and https are the same,
    /// host case and a leading "www." are ignored, a default port and a
    /// trailing slash are dropped, and the fragment is ignored. The query
    /// string still counts.
    static func comparisonKey(_ raw: String?) -> String? {
        guard let normalized = raw.flatMap(NativeActionCompiler.normalizeBrowserURL),
              let components = URLComponents(string: normalized),
              let host = components.host?.lowercased() else { return nil }
        var path = components.percentEncodedPath
        while path.hasSuffix("/") { path.removeLast() }
        let port = components.port.flatMap { [80, 443].contains($0) ? nil : $0 }
        return [
            strippedHost(host),
            port.map(String.init) ?? "",
            path,
            components.percentEncodedQuery ?? "",
        ].joined(separator: "\u{1f}")
    }

    /// Bound at plan time: a hash of the page the browser showed before the
    /// action, so the witness can tell a real navigation from no change
    /// without writing the previous address into receipts or traces.
    static func baselineToken(_ raw: String?) -> String {
        comparisonKey(raw).map(NativeHash.sha256) ?? "none"
    }

    /// Marks a baseline taken while another app was in front: the page the
    /// browser showed before is unknown, so only an exact match verifies.
    static let unboundBaseline = "unbound"

    /// True when `actual` proves the navigation to `expected` landed: the
    /// same page under `comparisonKey`, or a redirect that stays on the
    /// requested registrable domain and moved the browser off the page it
    /// showed before (`baselineToken`). A missing or unbound baseline
    /// allows the exact match only.
    static func navigationLanded(
        expected: String?,
        actual: String?,
        baselineToken: String?
    ) -> Bool {
        guard let expectedKey = comparisonKey(expected),
              let actualKey = comparisonKey(actual) else { return false }
        if expectedKey == actualKey { return true }
        guard let baselineToken, baselineToken != unboundBaseline,
              let expectedHost = host(expected),
              let actualHost = host(actual),
              registrableDomain(expectedHost) == registrableDomain(actualHost) else {
            return false
        }
        return NativeHash.sha256(actualKey) != baselineToken
    }

    /// Approximate registrable domain without the public suffix list: the
    /// last two labels, or the last three under a two-letter country code
    /// whose second level is a generic one (example.co.uk). IP addresses
    /// compare whole.
    static func registrableDomain(_ rawHost: String) -> String {
        let host = strippedHost(rawHost.lowercased())
        if host.contains(":") || host.split(separator: ".").allSatisfy({
            $0.allSatisfy(\.isNumber)
        }) {
            return host
        }
        let labels = host.split(separator: ".").map(String.init)
        guard labels.count > 2 else { return host }
        let genericSecondLevels: Set<String> = [
            "co", "com", "org", "net", "gov", "ac", "edu", "ne", "or", "go",
        ]
        let tld = labels[labels.count - 1]
        let second = labels[labels.count - 2]
        let count = tld.count == 2 && genericSecondLevels.contains(second) ? 3 : 2
        return labels.suffix(count).joined(separator: ".")
    }

    private static func host(_ raw: String?) -> String? {
        raw.flatMap(NativeActionCompiler.normalizeBrowserURL)
            .flatMap { URLComponents(string: $0)?.host?.lowercased() }
    }

    private static func strippedHost(_ host: String) -> String {
        host.hasPrefix("www.") ? String(host.dropFirst(4)) : host
    }
}
