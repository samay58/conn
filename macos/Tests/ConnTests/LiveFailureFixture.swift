import Foundation
@testable import Conn

struct LiveFailureFixture {
    let nodes: [NativeObservationNode]
    let observation: NativeCapturedObservation

    static func load(_ name: String) throws -> Self {
        let root = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        let url = root
            .appendingPathComponent("tests/fixtures/live_failures")
            .appendingPathComponent(name)
        let data = try Data(contentsOf: url)
        let raw = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let rows = raw["nodes"] as! [[String: Any]]
        let nodes = rows.map { row in
            NativeObservationNode(
                ref: row["ref"] as! String,
                parentRef: row["parent_ref"] as? String,
                path: row["path"] as? [Int] ?? [],
                role: row["role"] as! String,
                title: row["title"] as? String,
                description: row["description"] as? String,
                selected: row["selected"] as? Bool,
                frame: rect(row["frame"]),
                supportedActions: row["supported_actions"] as? [String] ?? []
            )
        }
        let observation = NativeCapturedObservation.fixture(
            turnID: "shared-live-failure",
            observationEpoch: 1,
            nodes: nodes,
            bundleID: raw["bundle_id"] as? String ?? "com.conn.fixture",
            windowID: UInt32(raw["window_id"] as? Int ?? 1)
        )
        return Self(nodes: nodes, observation: observation)
    }

    private static func rect(_ value: Any?) -> NativeRect? {
        guard let raw = value as? [String: Any],
              let x = (raw["x"] as? NSNumber)?.doubleValue,
              let y = (raw["y"] as? NSNumber)?.doubleValue,
              let width = (raw["width"] as? NSNumber)?.doubleValue,
              let height = (raw["height"] as? NSNumber)?.doubleValue else {
            return nil
        }
        return NativeRect(x: x, y: y, width: width, height: height)
    }
}
