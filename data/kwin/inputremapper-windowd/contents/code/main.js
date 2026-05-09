// input-remapper Window Daemon Client — KWin script
//
// This script is installed as a KWin script and listens for foreground
// window changes. When the active window changes, it sends the window's
// class, caption, PID, and internal UUID to the input-remapper window
// daemon service over the session D-Bus.
//
// The window daemon then evaluates window rules and, if a rule matches,
// switches the input-remapper preset for the configured device.

const SERVICE_NAME = "inputremapper.WindowDaemon";
const OBJECT_PATH = "/inputremapper/WindowDaemon";
const INTERFACE_NAME = "inputremapper.WindowDaemon";

function notifyWindow(client) {
    if (!client) {
        // Desktop, lockscreen, or no window
        var data = {
            windowClass: "",
            title: "",
            pid: 0,
            internalId: ""
        };
        callDBus(
            SERVICE_NAME,
            OBJECT_PATH,
            INTERFACE_NAME,
            "NotifyWindow",
            JSON.stringify(data)
        );
        return;
    }

    var internalId = "";
    try {
        internalId = client.internalId.toString();
    } catch (e) {
        // internalId may not be available on all KWin versions
        internalId = "";
    }

    var data = {
        windowClass: client.resourceClass || "",
        title: client.caption || "",
        pid: client.pid || 0,
        internalId: internalId
    };

    callDBus(
        SERVICE_NAME,
        OBJECT_PATH,
        INTERFACE_NAME,
        "NotifyWindow",
        JSON.stringify(data)
    );
}

// Listen for foreground window changes
workspace.windowActivated.connect(notifyWindow);

// Notify on startup for the currently active window.
// In KWin 6 / Plasma 6 (Wayland) the property is called activeWindow.
// The callback from windowActivated receives the same window object type.
var activeWindow = workspace.activeWindow;
if (activeWindow) {
    notifyWindow(activeWindow);
}
