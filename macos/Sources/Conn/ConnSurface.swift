import Foundation

@MainActor
protocol ConnSurface: AnyObject {
    func show()
    func hide()
}
