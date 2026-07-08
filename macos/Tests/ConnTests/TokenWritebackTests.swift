import SwiftUI
import XCTest
@testable import Conn

// Write Back must round-trip: rendering a default store reproduces the
// checked-in DesignTokens.swift byte for byte, which is simultaneously the
// compilability proof (the file on disk builds this test target) and the
// template-drift guard. Raw literals come from the store; the derived block
// is template text and never follows slider state.
final class TokenWritebackTests: XCTestCase {
    func testRenderOfDefaultsMatchesSourceFile() throws {
        let rendered = TokenWriteback.render(DesignTokenStore())
        let disk = try String(contentsOfFile: DesignTokens.sourceFilePath, encoding: .utf8)
        if rendered != disk {
            let dump = "/tmp/DesignTokens.rendered.swift"
            try? rendered.write(toFile: dump, atomically: true, encoding: .utf8)
            XCTFail("render of defaults differs from DesignTokens.swift; rendered copy at \(dump)")
        }
    }

    func testTunedRawLiteralLandsInRender() {
        let store = DesignTokenStore()
        store.summonSpring = Spring(response: 0.31, dampingRatio: store.summonSpring.dampingRatio)
        store.chipOpenDuration = 0.2
        let rendered = TokenWriteback.render(store)
        XCTAssertTrue(rendered.contains("summonSpring = Spring(response: 0.31, dampingRatio: 0.8)"))
        XCTAssertTrue(rendered.contains("chipOpenDuration = 0.2\n"))
    }

    func testDerivedBlockStaysTemplateVerbatim() {
        let store = DesignTokenStore()
        store.aliveness = 0
        store.squashWidthLeadMs = 90
        let rendered = TokenWriteback.render(store)
        // The derived section is the computed-property text, not values.
        XCTAssertTrue(rendered.contains("var squashWidthLead: Double { squashWidthLeadMs / 1000.0 * aliveness }"))
        XCTAssertTrue(rendered.contains("Self.springOvershooting(squashHeightOvershoot * aliveness, response: summonSpring.response)"))
        XCTAssertFalse(rendered.contains("var squashWidthLead = "))
    }

    func testSpecTableDiffReportsOnlyChanges() {
        let base = DesignTokenStore()
        let tuned = DesignTokenStore()
        XCTAssertTrue(TokenWriteback.specTableDiff(from: base, to: tuned).contains("no tuned values differ"))
        tuned.breathPeriod = 4.0
        tuned.islandAccentRGB = PaletteColor(red: 1, green: 0, blue: 0)
        let diff = TokenWriteback.specTableDiff(from: base, to: tuned)
        XCTAssertTrue(diff.contains("breathPeriod [Personality / Breath]: 3.2 -> 4.0"))
        XCTAssertTrue(diff.contains("island.accent [Palette]: #C3B1E1 -> #FF0000"))
        XCTAssertFalse(diff.contains("exhale"))
    }

    // The playground contract: mutating the store changes what the statics
    // hand to the next replay, no rebuild. Restore on exit; the store is
    // shared process state.
    func testStoreMutationDrivesStaticsLive() {
        let old = DesignTokens.current.summonSpring
        defer { DesignTokens.current.summonSpring = old }
        DesignTokens.current.summonSpring = Spring(response: 0.4, dampingRatio: old.dampingRatio)
        XCTAssertEqual(DesignTokens.summonSpring.response, 0.4, accuracy: 1e-9)
        XCTAssertEqual(DesignTokens.summonWidthSpring.response, 0.4, accuracy: 1e-9)
    }

    func testAlivenessZeroFlattensDerivedLive() {
        let old = DesignTokens.current.aliveness
        defer { DesignTokens.current.aliveness = old }
        DesignTokens.current.aliveness = 0
        XCTAssertEqual(DesignTokens.summonHeightSpring.dampingRatio, 1.0, accuracy: 1e-9)
        XCTAssertEqual(DesignTokens.summonWidthSpring.dampingRatio, 1.0, accuracy: 1e-9)
        XCTAssertEqual(DesignTokens.squashWidthLead, 0, accuracy: 1e-9)
    }
}
