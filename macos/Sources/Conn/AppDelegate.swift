import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let state = AppState()
    var client: DaemonClient!
    var hotkey: HotkeyMonitor!
    var statusItem: StatusItemController!
    var panel: PanelController?
    var island: IslandController?
    var primarySurface: ConnSurface!
    private var panelAutoReflectPhases = true
    private var currentGestureID: String?
    private let bridgeToken = BridgeToken.resolve()

    func applicationDidFinishLaunching(_ notification: Notification) {
        client = DaemonClient(state: state, bridgeToken: bridgeToken)
        hotkey = HotkeyMonitor()
        statusItem = StatusItemController(
            state: state,
            client: client,
            hotkey: hotkey,
            panelProvider: { [weak self] in
                guard let self else {
                    fatalError("Conn panel requested after AppDelegate deallocated")
                }
                return self.panelController()
            }
        )

        // The island path is used on notch displays (where the system
        // reserves a camera-housing area we can dock into). Everywhere
        // else, and when CONN_FORCE_PANEL=1 forces the legacy surface,
        // the existing floating panel remains unchanged.
        if let geometry = NSScreen.main.flatMap(IslandGeometry.forScreen),
           ProcessInfo.processInfo.environment["CONN_FORCE_PANEL"] != "1" {
            let controller = IslandController(state: state, client: client, geometry: geometry)
            island = controller
            panelAutoReflectPhases = false
            primarySurface = controller
        } else {
            panelAutoReflectPhases = true
            primarySurface = panelController()
        }

        hotkey.onDown = { [weak self] in
            guard let self else { return }
            let gesture = PttGesture.newID()
            self.currentGestureID = gesture
            self.client.send(["type": "ptt_down", "source": "app_hotkey",
                              "gesture_id": gesture])
            self.primarySurface.show()
        }
        hotkey.onUp = { [weak self] in
            guard let self else { return }
            let gesture = self.currentGestureID ?? PttGesture.newID()
            self.currentGestureID = nil
            self.client.send(["type": "ptt_up", "source": "app_hotkey",
                              "gesture_id": gesture])
        }
        hotkey.start()

        DaemonLauncher.ensureRunning(bridgeToken: bridgeToken) { [weak self] in
            self?.client.connect()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        hotkey.stop()
        client.send(["type": "shutdown"])
        // Give the shutdown frame a moment to flush before the socket dies;
        // the daemon's parent-loss lease is the backstop if this races.
        RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.2))
        client.close()
    }

    private func panelController() -> PanelController {
        if let panel {
            return panel
        }
        let controller = PanelController(
            state: state,
            client: client,
            autoReflectPhases: panelAutoReflectPhases
        )
        panel = controller
        return controller
    }
}
