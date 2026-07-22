import XCTest
@testable import Conn

final class NativeLabOracleRunnerTests: XCTestCase {
    func testSelectedMatchUsesANamedAncestorWithoutReturningItsLabel() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "oracle", observationEpoch: 1, nodes: [
            NativeObservationNode(
                ref: "list", role: "AXList"
            ),
            NativeObservationNode(
                ref: "item", parentRef: "list", role: "AXGroup",
                selected: true
            ),
            NativeObservationNode(
                ref: "image", parentRef: "item", role: "AXImage",
                title: "Projects", focused: true
            ),
        ], bundleID: "com.apple.finder")

        let result = NativeLabOracleRunner.summarize(
            observation, expected: "Projects"
        )

        XCTAssertEqual(result["selected_match_count"] as? Int, 1)
        XCTAssertEqual(result["focused_match_count"] as? Int, 1)
        XCTAssertEqual(result["label_match_count"] as? Int, 1)
        XCTAssertEqual(
            result["focused_match_roles"] as? [String: Int],
            ["AXImage": 1]
        )
        XCTAssertNil(result["label"])
        XCTAssertFalse(String(describing: result).contains("Projects"))
    }

    func testSecureValuesCannotMatch() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "oracle", observationEpoch: 1, nodes: [
            NativeObservationNode(
                ref: "secret", role: "AXSecureTextField",
                redactedValue: "Projects", focused: true
            ),
        ], bundleID: "com.apple.finder")

        let result = NativeLabOracleRunner.summarize(
            observation, expected: "Projects"
        )

        XCTAssertEqual(result["selected_match_count"] as? Int, 0)
        XCTAssertEqual(result["focused_match_count"] as? Int, 0)
        XCTAssertEqual(result["label_match_count"] as? Int, 0)
        XCTAssertEqual(result["focused_match_roles"] as? [String: Int], [:])
    }

    func testValueMatchesReportRolesWithoutReturningTheExpectedValue() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "oracle", observationEpoch: 1, nodes: [
                NativeObservationNode(
                    ref: "row-value", role: "AXStaticText",
                    redactedValue: "Selected note"
                ),
                NativeObservationNode(
                    ref: "detail-value", role: "AXTextArea",
                    redactedValue: "Selected note"
                ),
            ], bundleID: "com.apple.Notes"
        )

        let result = NativeLabOracleRunner.summarize(
            observation, expected: "Selected note"
        )

        XCTAssertEqual(
            result["value_match_roles"] as? [String: Int],
            ["AXStaticText": 1, "AXTextArea": 1]
        )
        XCTAssertEqual(
            result["value_hash_match_roles"] as? [String: Int],
            ["AXStaticText": 1, "AXTextArea": 1]
        )
        XCTAssertFalse(String(describing: result).contains("Selected note"))
    }

    func testPageStatusesReportOnlyBoundedStructuralValues() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "oracle", observationEpoch: 1, nodes: [
                NativeObservationNode(
                    ref: "page", role: "AXStaticText",
                    redactedValue: "Page 2 of 3"
                ),
                NativeObservationNode(
                    ref: "private", role: "AXStaticText",
                    redactedValue: "Private document text"
                ),
            ], bundleID: "com.apple.Preview"
        )

        let result = NativeLabOracleRunner.summarize(
            observation, expected: "Page 3 of 3"
        )

        XCTAssertEqual(result["page_statuses"] as? [String], ["Page 2 of 3"])
        XCTAssertFalse(String(describing: result).contains("Private document text"))
    }

    func testUniquePressableTargetReturnsOnlyItsFrame() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "target", observationEpoch: 1, nodes: [
                NativeObservationNode(
                    ref: "previous", role: "AXButton", title: "Previous",
                    frame: NativeRect(x: 100, y: 80, width: 20, height: 20),
                    supportedActions: ["AXPress"]
                ),
            ], bundleID: "com.apple.iCal"
        )

        let result = NativeLabOracleRunner.target(
            observation, expected: "Previous"
        )

        XCTAssertEqual(result["match_count"] as? Int, 1)
        XCTAssertEqual(
            (result["frame"] as? [String: Any])?["x"] as? Double, 100
        )
        XCTAssertFalse(String(describing: result).contains("Previous"))
    }

    func testAmbiguousPressableTargetReturnsNoFrame() {
        let nodes = (1...2).map {
            NativeObservationNode(
                ref: "previous-\($0)", role: "AXButton", title: "Previous",
                frame: NativeRect(x: Double($0 * 20), y: 80, width: 20, height: 20),
                supportedActions: ["AXPress"]
            )
        }
        let observation = NativeCapturedObservation.fixture(
            turnID: "target", observationEpoch: 1, nodes: nodes,
            bundleID: "com.apple.iCal"
        )

        let result = NativeLabOracleRunner.target(
            observation, expected: "Previous"
        )

        XCTAssertEqual(result["match_count"] as? Int, 2)
        XCTAssertTrue(result["frame"] is NSNull)
    }

    func testTargetAffordancesReportStructureWithoutReturningTheLabel() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "affordance", observationEpoch: 1, nodes: [
                NativeObservationNode(
                    ref: "table", role: "AXTable",
                    settableAttributes: ["AXSelectedRows"]
                ),
                NativeObservationNode(
                    ref: "row", parentRef: "table", role: "AXRow",
                    selected: false,
                    frame: NativeRect(x: 20, y: 40, width: 200, height: 32),
                    supportedActions: ["AXPress"],
                    settableAttributes: ["AXSelected"]
                ),
                NativeObservationNode(
                    ref: "label", parentRef: "row", role: "AXStaticText",
                    valueHash: NativeHash.sha256("Second note")
                ),
            ], bundleID: "com.apple.Notes"
        )

        let result = NativeLabOracleRunner.targetAffordances(
            observation, expected: "Second note"
        )

        XCTAssertEqual(result["match_count"] as? Int, 1)
        let matches = result["matches"] as? [[String: Any]]
        XCTAssertEqual(matches?.first?["role"] as? String, "AXRow")
        XCTAssertEqual(
            matches?.first?["supported_actions"] as? [String], ["AXPress"]
        )
        XCTAssertEqual(
            matches?.first?["settable_attributes"] as? [String], ["AXSelected"]
        )
        XCTAssertEqual(matches?.first?["parent_role"] as? String, "AXTable")
        XCTAssertEqual(
            matches?.first?["frame"] as? [String: Double],
            ["x": 20, "y": 40, "width": 200, "height": 32]
        )
        XCTAssertEqual(
            matches?.first?["parent_settable_attributes"] as? [String],
            ["AXSelectedRows"]
        )
        XCTAssertFalse(String(describing: result).contains("Second note"))
    }

    func testTargetAffordancesFallBackToBoundedTableRowsWithoutLabels() {
        let observation = NativeCapturedObservation.fixture(
            turnID: "affordance", observationEpoch: 1, nodes: [
                NativeObservationNode(
                    ref: "table", role: "AXTable",
                    settableAttributes: ["AXSelectedRows"]
                ),
                NativeObservationNode(
                    ref: "one", parentRef: "table", role: "AXRow",
                    selected: true, settableAttributes: ["AXSelected"]
                ),
                NativeObservationNode(
                    ref: "two", parentRef: "table", role: "AXRow",
                    selected: false, settableAttributes: ["AXSelected"]
                ),
            ], bundleID: "com.apple.Notes"
        )

        let result = NativeLabOracleRunner.targetAffordances(
            observation, expected: "not exposed"
        )

        XCTAssertEqual(result["match_count"] as? Int, 2)
        let matches = try? XCTUnwrap(result["matches"] as? [[String: Any]])
        XCTAssertEqual(matches?.map { $0["selected"] as? Bool }, [true, false])
    }

}
