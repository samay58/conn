import XCTest
@testable import Conn

final class LiveFailureFixtureTests: XCTestCase {
    func testSwiftConsumesTheSharedSafariAndNotesWitnessShapes() throws {
        let safari = try LiveFailureFixture.load("safari_nested_tabs.json")
        let notes = try LiveFailureFixture.load("notes_collections.json")
        let backend = SemanticFixtureBackend()
        let evaluator = NativeEffectEvaluator(
            store: NativeObservationStore(backend: backend)
        )

        XCTAssertEqual(evaluator.descendantCount(
            of: try XCTUnwrap(safari.nodes.first { $0.ref == "tab-strip" }),
            itemRoles: ["AXRadioButton"],
            in: safari.observation
        ), 2)
        XCTAssertEqual(evaluator.descendantCount(
            of: try XCTUnwrap(notes.nodes.first { $0.ref == "notes-list" }),
            itemRoles: ["AXRow"],
            in: notes.observation
        ), 2)
        XCTAssertEqual(evaluator.descendantCount(
            of: try XCTUnwrap(notes.nodes.first { $0.ref == "other-notes" }),
            itemRoles: ["AXRow"],
            in: notes.observation
        ), 1)
    }

    func testSwiftConsumesTheSharedDuplicateNameShape() throws {
        let river = try LiveFailureFixture.load("river_duplicate.json")
        let result = NativeObservationIndex().candidates(
            in: river.observation,
            query: NativeObservationQuery(
                searchTerms: ["RIVER"],
                expectedRoles: ["AXLink"]
            )
        ).dictionary
        let candidates = try XCTUnwrap(result["candidates"] as? [[String: Any]])

        XCTAssertEqual(candidates.count, 2)
        XCTAssertEqual(Set(candidates.compactMap { $0["ref"] as? String }), [
            "top-river", "secondary-river",
        ])
    }
}
