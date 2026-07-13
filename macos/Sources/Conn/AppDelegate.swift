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
    private let bridgeToken = BridgeToken.generate()

    func applicationDidFinishLaunching(_ notification: Notification) {
        client = DaemonClient(state: state, bridgeToken: bridgeToken)
        statusItem = StatusItemController(
            state: state,
            client: client,
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

        hotkey = HotkeyMonitor()
        hotkey.onDown = { [weak self] in
            self?.client.send(["type": "ptt_down"])
            self?.primarySurface.show()
        }
        hotkey.onUp = { [weak self] in
            self?.client.send(["type": "ptt_up"])
        }
        hotkey.start()

        DaemonLauncher.ensureRunning(bridgeToken: bridgeToken) { [weak self] in
            self?.client.connect()
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
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
