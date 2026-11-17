# USB/IP Link

Uses the USB devices of another computer (USB/IP: **usbipd-win** on Windows) and **keeps
them attached**: again by itself after a restart of that computer. For Home Assistant in a
virtual machine without USB (Hyper-V), e.g. a ZBT-2 radio plugged into the Windows host.

- attached as soon as the server answers, found by its `VID:PID` (USB port changes do not matter);
- a dead link (server restarting) is freed and attached again when the server is back;
- add-ons restarted after a new attachment (OpenThread border router);
- state as Home Assistant entities (MQTT), read by Mesh Guardian.

**Beta**, privileged (protection mode off). See the **Documentation** tab.

Based on the idea of [rogerfar/ha-usbip-client](https://github.com/rogerfar/ha-usbip-client)
(MIT), rewritten. License: [MIT](LICENSE).
