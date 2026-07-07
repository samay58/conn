import SwiftUI
import XCTest
@testable import Conn

// The personality springs derive their damping from the overshoot tokens:
// an underdamped spring's first peak overshoots by exp(-z * pi / sqrt(1 - z^2)),
// so DesignTokens.springOvershooting inverts that to land exactly on the token.
final class IslandMotionTests: XCTestCase {
    private func overshoot(of spring: Spring) -> Double {
        let zeta = spring.dampingRatio
        guard zeta < 1 else { return 0 }
        return exp(-zeta * .pi / (1 - zeta * zeta).squareRoot())
    }

    func testZeroOvershootIsCriticallyDamped() {
        let spring = DesignTokens.springOvershooting(0, response: 0.28)
        XCTAssertEqual(spring.dampingRatio, 1.0, accuracy: 1e-9)
    }

    func testDerivedDampingReproducesRequestedOvershoot() {
        for requested in [0.02, 0.04, 0.10] {
            let spring = DesignTokens.springOvershooting(requested, response: 0.28)
            XCTAssertEqual(overshoot(of: spring), requested, accuracy: 1e-6)
            XCTAssertLessThan(spring.dampingRatio, 1.0)
        }
    }

    func testSummonSpringsFollowTheirTokens() {
        XCTAssertEqual(
            overshoot(of: DesignTokens.summonHeightSpring),
            DesignTokens.squashHeightOvershoot * DesignTokens.aliveness,
            accuracy: 1e-6)
        XCTAssertEqual(
            overshoot(of: DesignTokens.summonWidthSpring),
            DesignTokens.squashWidthOvershoot * DesignTokens.aliveness,
            accuracy: 1e-6)
        // Height overshoots more than width, so it must be less damped. At
        // aliveness 0 both springs are critically damped and the ordering is
        // deliberately gone.
        if DesignTokens.aliveness > 0 {
            XCTAssertLessThan(
                DesignTokens.summonHeightSpring.dampingRatio,
                DesignTokens.summonWidthSpring.dampingRatio)
        } else {
            XCTAssertEqual(DesignTokens.summonHeightSpring.dampingRatio, 1.0, accuracy: 1e-9)
            XCTAssertEqual(DesignTokens.summonWidthSpring.dampingRatio, 1.0, accuracy: 1e-9)
        }
        XCTAssertEqual(DesignTokens.summonWidthSpring.response, DesignTokens.summonSpring.response, accuracy: 1e-9)
        XCTAssertEqual(DesignTokens.summonHeightSpring.response, DesignTokens.summonSpring.response, accuracy: 1e-9)
    }

    func testWidthLeadDerivesFromMillisecondsAndAliveness() {
        XCTAssertEqual(
            DesignTokens.squashWidthLead,
            DesignTokens.squashWidthLeadMs / 1000.0 * DesignTokens.aliveness,
            accuracy: 1e-9)
    }
}
