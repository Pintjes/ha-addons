# Changelog

All notable changes to this add-on are documented here.
The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/).

## Highlights of 2.9 to 2.27 (16 November 2026)

- **Act on a node from its panel**: recovery attempt on an unavailable node, reset from a distance, pairing codes kept by the add-on (photo or scan of the label), pairing and naming a new device without leaving the page.
- **A node panel in sections**: facts and everyday actions on top, then signal, pairing, history and technical details, each one folding.
- **Robustness** (after an audit): files written whole or not at all, a sweep that no longer stops at one node, a reset checked with the device, threads that start again after an error, tests in the repository run by the CI.

## [2.27.0] - 2026-11-16

### Changed

- The image is the same at every install: exact versions of Python (3.13.18, Alpine 3.24) and of the libraries (zeroconf 0.154.0, paho-mqtt 2.2.0, websocket-client 1.9.2, ifaddr 0.2.0), all installed already built. No compiler in the image any more, nothing compiled on the machine of Home Assistant: a faster install that cannot fail at that step.
- The MQTT settings (broker, user, password) are read again from the Supervisor when the connection is lost or refused: a password changed in the Mosquitto add-on is used without restarting Mesh Guardian. A refused connection no longer subscribes as if it were connected.

### Fixed

- Automatic recovery: the pings of one cycle stop after 100 seconds (a ping of a lost node can wait 90 seconds for its answer), so a new outage or a node back is seen within minutes instead of waiting for five pings in a row. The nodes not pinged are pinged in the next cycles.
- Radio survey: a node, or one entry of a Thread table, described oddly (interview cut short, other firmware) is left out instead of making the whole survey fail.
- Recovery attempt: when its thread cannot start, the node is no longer left "recovering" for good with a result that never comes; the page says the action failed.
- Requests of the page: only JSON from the page itself is accepted (a form of another site open in the browser cannot act on the add-on), node ids and texts are checked, a request too large is refused instead of cut.
- Pairing codes: a code holding a passcode the Matter specification forbids (00000000, 11111111… 12345678, 87654321) is refused with a message: it is a reading or typing mistake, no device uses one.
## [2.26.0] - 2026-11-16

### Changed

- Messages of the page go away by themselves (longer for a longer text, kept while the pointer is over them); a code to type on the phone stays until clicked. The first message is announced by screen readers too.
- After a pairing started from the page, the new device is found when Home Assistant adds it to its registry, instead of reading the registry every 4 seconds for 10 minutes; the watch stops when you leave the page.
- Keyboard: the focus stays on the same element when the page is drawn again (every 30 seconds), Tab stays in the open node panel, and the name of a node is the button that opens it (a card or a row holding other buttons is no longer a button itself).
- The nodes removed from the Matter Server are also forgotten in the response times, the contact sources and what the Matter Server log said of them.

### Fixed

- Counters of the automatic recovery and storm detection are changed under a lock (they are fed from several threads): no count lost, no list changed while it is read.

### Removed

- Page code no longer used (silent nodes in the summary, a second list of hidden cards, unused parameters).
## [2.25.0] - 2026-11-16

### Changed

- The advice names the button as it is called: "Find a new link" (FR "Rechercher un nouveau lien").
- Node panel: the close button and the panel are named for screen readers, the focus goes back where it was when the panel closes, Escape closes the column menu first, action buttons are larger on a phone, cards no longer overflow on a very narrow screen.
- French texts: the infinitive everywhere (no more "tu"), the tooltip of "Interviewer" in French, the old parent and its verdict back in the "new parent" log line.
- Documentation brought up to date: the node panel and its sections, the actions of the table (Remove included), the events, the trial on routers, the options; the recipe to remove the router trial is complete.
- The image takes every module of the add-on (`COPY *.py`): a new file can no longer be forgotten.

### Removed

- 32 French texts and 15 page texts no longer used, and a style no longer used.

### Fixed

- A parent search whose result the page has no text for no longer shows an error of the page.
- English log: "leader router" instead of the French "routeur leader".

## [2.24.0] - 2026-11-16

### Fixed

- The active probes and the MQTT publishing start again after an error instead of stopping for good while the add-on looks alive; an error in an MQTT callback no longer stops the MQTT connection.
- The live link to the Matter Server reconnects within seconds after a drop, also after several drops (the wait stayed at 2 minutes).
- Automatic recovery no longer freezes when more than half of the nodes are removed: a much shorter list of nodes is taken as the real one after 10 minutes.
- Node panel: shown again after an action only when you are not typing in it, answering the reset question, replacing the pairing code or taking a photo; and at the same place in the panel instead of the top. A photo taken with the phone is no longer lost.
- QR code reader of the app: one scan at a time, and the reader of Home Assistant is given back when you leave the page during a scan. "Pair" pressed twice starts one pairing. When the code cannot be copied, the message shows it instead of saying "copied". When the reader does not answer, a message says so.
- A parent search or recovery is followed once per node, and not while the page is hidden.
- The "New device paired" panel waits until you are done with the panel you are typing in.
- "Remove": same lock as the other actions on a node, an event `node_removed`, and a warning in the confirmation when the pairing code of the node is not kept.
- The anonymized report no longer shows the name of Wi-Fi access points (channel only).

### Changed

- README: lists every action that writes to a node, the reset and the removal included.
- The tests written during the audit are in the repository (`tests/mesh_guardian`, `python tests/mesh_guardian/run_all.py`) and run in the CI.

## [2.23.0] - 2026-11-16

### Fixed

- The sweep no longer stops at the first node in error ("Sweep interrupted: Node … does not exist"): a node the Matter Server no longer knows is left out, and a node that fails counts as not answering. Only an unreachable Matter Server stops it.
- Reset from a distance: the add-on now asks the device itself to leave the fabric of Home Assistant and checks its answer. The Matter Server removed the node even when the device refused, and the reset was then reported done while the device kept a fabric nobody could use. New result "unsure" when the device does not confirm but can no longer be reached.
- Pairing codes: a code is only matched to a node of the same product (a node id is given again after the Matter Server is installed anew), the hardware address is the one of the Thread interface and never a placeholder of zeros, a code scanned before a pairing goes by itself only to a node paired within 30 minutes, and a code waiting since a reset only within 7 days. Otherwise it waits in the list, to be attached by hand.
- Files in /data are written whole or not at all (temporary file, flushed, then put in place): a power cut no longer leaves a half-written file. A file that cannot be read is kept aside as `<name>.bad-<date>` with a warning, instead of being replaced by an empty state; before, a damaged state file silently turned the automatic recovery off and lost the pairing codes.
- An outage left open when a node came back while the add-on was stopped is now closed: its availability no longer drops towards 0 % over 7 days.
- The page server only answers the Home Assistant ingress, also when it has to listen on every address.
- Top of the page: "A, B, C +2" again (the text had become "2 older").

## [2.22.1] - 2026-11-16

### Changed

- Node panel: the three everyday actions sit under the facts without a section of their own; "Signal and response" comes before "Pairing"; outages and parent changes have their own section, "History", before the technical details; the groups of the technical details are plain sub-titles again.

## [2.22.0] - 2026-11-16

### Changed

- Node panel cut in sections that fold with their arrow: General (always shown), Tools, Pairing, Signal and response (open at first), Technical details (closed at first, themselves cut in groups that fold). What is open or folded is kept in the browser.
- Outages and parent changes move into the technical details (History).
- Pairing without a code: a dashed zone with an icon takes the place of the sentence about dropping a photo; a click on it chooses a photo.
- French labels: "Recherche nouveau lien", "Interviewer".

## [2.21.1] - 2026-11-16

### Changed

- Node panel: the pairing code, with Reset and Remove, sits right under the actions (Ping, Find a new link, Interview) instead of at the bottom. Its QR code is always shown, small, beside the code.
- To make room, the Matter Server figures move into the technical details, and the outages and parent changes show their five newest lines (the older ones unfold).

## [2.21.0] - 2026-11-16

### Changed

- Node panel put in order, from what is read every day to what is rarely needed: state, network, role and power in the header; six facts (signal, response, parent, border router, last contact, outages); the actions that change nothing for good; the curves and the history; then the Matter Server figures, the pairing code with Reset and Remove, and the technical details.
- The pairing code takes one line (code, Copy, QR code on request) instead of a large QR code above the curves. Reset and Remove sit with it, away from Ping.
- Technical details are grouped (identity, Thread, running, contact) and show the date the node was paired. An empty history takes one line. A Wi-Fi or Ethernet node no longer shows the Thread-only action.

## [2.20.0] - 2026-11-16

### Added

- Node panel, technical details: serial number (when the device has one), firmware version, unique id and hardware address (a device may change those two at a factory reset). They are not in the report.

## [2.19.2] - 2026-11-16

### Fixed

- A border router whose Thread restarted announces itself anew under another id while its old announcement stays on the network: it was shown twice. The new announcement now takes over its card (name and history kept) and the old one is ignored; a card that goes offline while another, online, has the same addresses is folded into it.

## [2.19.1] - 2026-11-16

### Changed

- "Find a new link" on a router: the result is given as soon as the node is a router again (its role is read every 20 seconds) instead of after a fixed 3 minutes, which stay the limit. The message now says "waiting for the result…" and is replaced by the result.

## [2.19.0] - 2026-11-16

### Added

- After a pairing started with "Pair", the page asks the name and the area of the new device and saves them in Home Assistant (the step the "Add Matter device" screen of Home Assistant does).

## [2.18.0] - 2026-11-16

### Added

- In the Home Assistant app, "Pair" first opens the QR code reader of the app: the code of the label is kept and attaches by itself to the node the pairing brings. The same reader is offered in the node panel ("Scan the QR code"), next to the photo.

## [2.17.0] - 2026-11-16

### Added

- "Pair" button: starts the pairing of a new or reset device from the page. In the Home Assistant app on a phone it starts the app's own Matter pairing (same as "Add Matter device"); in a browser it opens that screen of Home Assistant. Under "Pairing codes", "Pair with this code" copies the code first.

### Changed

- The "Pairing codes" button is shown only while a code waits for its device.

## [2.16.0] - 2026-11-16

### Added

- Pairing code: a "Take a photo of the QR code" button opens the camera of the phone, straight from the node panel.
- A node paired in the last 24 hours whose pairing code is not kept is shown first under "To handle", as "New node", while you are still in front of it ("Seen" hides it).

### Changed

- Documentation: in the list of Matter devices of the phone, remove only the entry of the device that is stuck; each entry removed makes its device leave every ecosystem.

## [2.15.1] - 2026-11-16

### Changed

- After a reset from a distance, the pairing code follows the node by itself when it comes back: the only code of that product waiting since such a reset is attached to the new node (the panel says so).
- A code typed for a device whose QR code is already kept takes that QR code back, instead of showing digits only.
- Reset of a Thread router: the panel warns to wait 2 to 3 minutes before pairing it again.
- Documentation: what to do when the pairing stops halfway and the device stays paired with the phone only.

### Fixed

- The old identity of a node reset from a distance, still announced by the border routers for some days, is no longer reported as "unknown to the Matter Server".

## [2.15.0] - 2026-11-16

### Added

- Reset from a distance (node panel): the node is removed from every fabric it is in, Home Assistant last, which makes it erase its Matter data and go back to pairing, without touching it. Only for an available node whose pairing code is kept; the panel shows the ecosystems it will leave and asks for a ticked box. Event `node_reset`. Trial: what a device does once out of its last fabric depends on its maker.

## [2.14.0] - 2026-11-16

### Added

- Pairing codes: the node panel keeps the code printed on the device, given by a photo of the QR code (dropped, chosen or pasted; read in the browser) or typed. It then shows the QR code and the code in digits, to pair the device again after a reset without reaching its label. The codes are kept by the add-on and survive the reset or removal of the node; a "Pairing codes" button lists those of the devices that left the table. They never appear in the log, the events or the report.
- The page ships jsQR 1.4.0 (Apache-2.0) and qrcode-generator 1.4.4 (MIT) to read and draw QR codes locally; they are loaded only when a pairing code needs them.

## [2.13.1] - 2026-11-16

### Fixed

- Recovery attempt: when the node is back before the fail-safe could be closed, the closing command is sent again (3 tries). Left armed, the fail-safe expired 2 minutes later and the node reverted its configuration, which on some devices restarts Thread once more.

## [2.13.0] - 2026-11-16

### Added

- Recovery attempt on an unavailable Thread node (node table and node panel, in place of "Find a new link"): the node is pinged, then asked to connect again to its own network, which restarts its Thread connection if the command gets through. One command is much shorter than the subscription the Matter Server needs to call a node available, so it can pass on a link that loses most messages. Result in the table and in the `recover_result` event. Needs the Matter Server based on matter.js (add-on 9 and later).

## [2.12.1] - 2026-11-16

### Changed

- Trial, provisional: "Find a new link" also works on the leader, after a stronger warning (the whole network elects a new leader, nodes can become unavailable for about 2 minutes).

## [2.12.0] - 2026-11-16

### Changed

- The button "Find a new parent" is now "Find a new link".
- Trial, provisional: the button also works on a router (not on the leader). It restarts the Thread interface of the router, after a warning: its end devices drop and attach elsewhere, and a better link is not expected since a router picks its routes by itself. The result (router again or not, first link before and after) comes 3 minutes later. This will be removed if the trials show no benefit.

## [2.11.2] - 2026-11-16

### Fixed

- An unavailable node that still answers now and then (a recovery ping answered, or the Matter Server opened several sessions with it within the hour) is no longer told "Check its power": it has power. The card and the panel now say that it answers now and then and to cut its power for 10 seconds.

## [2.11.0] - 2026-11-16

### Added

- The add-on follows the log of the Matter Server and counts, per node over 24 hours, what Home Assistant does not show: subscriptions lost, sessions closed, how many times and how long the node was offline for the Matter Server, addresses that could not be reached, pings without answer, and the address the Matter Server uses. Shown in the node panel ("Matter Server · 24h") and in an optional column "Losses 24h". No text of the log is kept, only the counts.

## [2.10.7] - 2026-11-16

### Added

- A border router card opens a panel with everything known about it: state, role, primary, Thread network, prefix, last contact, detaches of the last 7 days, the nodes going through it and attached to it, model, addresses.
- "Remove" in that panel, for an offline border router that was taken away or whose Thread was turned off on purpose: it leaves the list, the quality score and the Home Assistant entities, and comes back by itself if it is heard again.

## [2.10.6] - 2026-11-16

### Fixed

- Two border routers could be shown as "primary" at the same time: one that stopped announcing itself kept the label of its last announcement. Only the one heard last keeps it.

## [2.10.5] - 2026-11-16

### Fixed

- The count of recovery pings sent to an unavailable node goes on after a restart of the add-on instead of starting again at 1.
- When the Thread partition is replaced by a new one, the log says "New Thread partition" instead of "Thread partitions: 1 → 1".
- Result of "Ping all nodes": "X (battery), Y (battery)" instead of "X, battery, Y, battery".
- Log texts: "becomes primary" / "no longer primary" for a border router instead of "True", node prefixes written as a plain list, correct singular and plural in the hourly summary and the radio survey, French spacing before a colon.

## [2.10.4] - 2026-11-16

### Fixed

- The radio survey no longer names a node "most unstable" when no node has any detach, parent or partition change (a node that only restarted was named).

## [2.10.3] - 2026-11-16

### Fixed

- With the option "Advice" off, the advice column could still be ticked in the column menu.

## [2.10.2] - 2026-11-16

### Added

- Option "Advice" (on by default): off, the add-on gives no advice for the available nodes (cards, column, log). An unavailable node keeps what to do about it, and the notes about the network stay.

## [2.10.1] - 2026-11-16

### Fixed

- 24h counters (detaches, parent and partition changes, "most unstable" of the radio survey): 2.10.0 read the counters from the nodes for the first time and compared them with yesterday's values of the Matter Server cache, which can be days old, so the difference counted all those days (e.g. 261 detaches "in 24h"). A difference is now only shown once both values are the node's own; until then the counter shows "—" (about 24 hours after the first read).

## [2.10.0] - 2026-11-16

### Added

- Every value now has an age: the add-on remembers when the node gave it (a report or a read). A value given more than 2 hours ago, or taken from the Matter Server cache without anyone knowing when, is old: shown in grey, without colour or signal bars, with its age in the tooltip. It applies to the link (parent, signal, border router, path), the 24h counters, the uptime, the response time and the Wi-Fi signal.
- The age of the response time is in its tooltip.
- Battery nodes: role, neighbor table and addresses are read once an hour, right after the read of their response time, while they are awake (no wake-up added). Mains nodes: the counters (detaches, parent and partition changes) are read with their tables once an hour. Wi-Fi nodes: their signal is read once an hour.

### Changed

- No advice is drawn from an old link any more.

## [2.9.9] - 2026-11-16

### Added

- Every card has the "Seen" button: advice, unavailable node, network. A hidden card comes back when it changes (another advice, the node unavailable again). The table and the summary at the top still show everything.

## [2.9.8] - 2026-11-16

### Added

- The "Seen" button also hides the orange network notes (e.g. a border router that detaches). A hidden note comes back when it changes.

## [2.9.7] - 2026-11-15

### Fixed

- Many nodes dropping together no longer show "Home Assistant or the Matter Server restarted" when the Supervisor log shows that nothing restarted: it is a network problem, and each node keeps its own card.

## [2.9.6] - 2026-11-15

### Changed

- A restart of the Matter Server or of Home Assistant is now read in the Supervisor log instead of being deduced from a dropped link: the card gives the exact time and the cause ("was restarted", "was updated to 9.3.1", "crashed (code 1)"). It also works when Mesh Guardian restarted at the same time, which the live link missed. Without access to the log, the detection by the live link remains.
- The add-on keeps the Supervisor role "manager" for this. It only reads the Supervisor log and the name of the Matter Server; see "Supervisor access" in the documentation.

### Added

- Event `server_restart` (who, cause, exit code, version).

### Removed

- The Supervisor API test of 2.9.3 – 2.9.5.

## [2.9.5] - 2026-11-15

### Changed

- Test of the Supervisor API with the role "manager" (to compare with "default").

## [2.9.4] - 2026-11-15

### Fixed

- 2.9.3 did not start (a file missing from the image).

## [2.9.3] - 2026-11-15

### Added

- Access to the Supervisor API (role "default"), as a test: at start, the add-on tries the Supervisor calls it could use (Matter Server state and log, Home Assistant state, network…) and logs which ones its role allows. Only the status codes are kept, never the content.

## [2.9.2] - 2026-11-15

### Fixed

- A restart of the Matter Server is now detected by Mesh Guardian itself (its live link drops and comes back), no longer through Home Assistant: 2.9.1 missed it when Home Assistant restarted at the same time.
- While Home Assistant starts, an incomplete list of nodes no longer makes their names and outage times disappear ("0x14", "Since ?").

### Changed

- The nodes taken down by a restart get their own card again after 5 minutes (was 30).

## [2.9.1] - 2026-11-15

### Changed

- After a restart of the Matter Server (or of Home Assistant), the nodes it took down no longer get one red card each: a single card says when it restarted and how many nodes are still reconnecting. A node still unavailable 30 minutes later gets its own card again.

## [2.9.0] - 2026-11-15

### Fixed

- An unavailable node showed its parent, signal ("good"), border router and response time read before the outage, as if they were current: they are now left empty.
- The nodes the recovery pings gave up on are kept across a restart ("Remove the battery for 10s" no longer becomes "Check its batteries").

## [2.8.9] - 2026-11-15

### Changed

- One section again, now called "Good to know", with every card (things to do and notes); "Nothing to report" when empty.

## [2.8.8] - 2026-11-15

### Changed

- "Good to know" notes under their own title, below "To handle", shown only when there is one.

## [2.8.7] - 2026-11-15

### Changed

- Border router cards show the state now (online, offline, other subnet). Detaches of the last 24h are a "good to know" note in "To handle", one for all border routers, with a "Seen" button; from 3 detaches, a note with an action, as before.

## [2.8.6] - 2026-11-15

### Changed

- Round values without decimals in the page: 100 %, 2 h, 1 s (not 100,0 %).

## [2.8.5] - 2026-11-15

### Added

- "Good to know" notes have a "Seen" button that hides them in this browser; a note that changes comes back.

## [2.8.4] - 2026-11-15

### Changed

- Status line: "reading the nodes… n/N" instead of "updating…", which suggested an update of the add-on.

## [2.8.3] - 2026-11-15

### Changed

- Status line: "connecting to the Matter Server…" while the dot is orange, then "updating… n/N" while the nodes are read again, then the time of the update.

## [2.8.2] - 2026-11-15

### Fixed

- An advice always names an action: "Changes parent n× in 24h" and "Detaches n× in 24h" were observations, not advice, and are removed (the figures stay in the node panel).

## [2.8.1] - 2026-11-15

### Fixed

- No advice when the table had been prepared by the background refresh.

## [2.8.0] - 2026-11-15

### Changed

- Advice rewritten: computed every time the table is shown (no longer every 30 minutes), each with its proof in the detail.
- Weak link of an end device: "Find a new parent" first, naming a better parent when one is known (a router it hears better, or a past parent with a good link) or the routers of its room or floor; "Move the node" or "Add a router in <room>" only after a search made since the link is weak found nothing better.
- Weak link of a router: "Add a router between <room> and <room>".
- Restarts: a power cut is no longer instability (power on reported, or several mains nodes restarting together); only crashes reported by the node count against a parent.
- Unavailable node: the cause first (parent unavailable too, power cut in the room, low batteries, recovery pings exhausted).

### Added

- Advice for a node that crashes or keeps restarting, a router that detaches (with the nodes that depend on it), a node hesitating between two parents, a weak Wi-Fi signal.
- Network notes: border router offline or detaching, node announced but unknown to the Matter Server.

### Fixed

- No link advice from a state read in the middle of a parent search.

## [2.7.3] - 2026-11-15

### Fixed

- Parent search: no answer to the connect command is no longer shown as "refused" (the node may be attaching again): the fail-safe is left armed, the result is followed as for a sleepy node. "Refused" only when the node answers with an error.
- A node whose route table says it has no link with the parent it routes through (read during a parent change) shows no parent instead of a wrong one.

### Changed

- While the nodes are read again, the status line says "updating… n/N" instead of the time of the last update.

## [2.7.2] - 2026-11-15

### Fixed

- After a restart, battery nodes showed the Matter Server cache again (old parent and signal) until the page was opened: the values read from the nodes in the last 2 hours (role, tables, addresses) are now kept across a restart.
- Parent of an end device shown from an old address with the signal of its new parent (e.g. during a parent search): its neighbor table and its addresses are now always read together, and the route table of a (sleepy) end device, not kept up to date by the node, is no longer used for its link quality.
- "Parent search refused" now gives the reason in French too.

## [2.7.1] - 2026-11-15

### Fixed

- A link quality of 0 between a child and its parent was taken as unknown: the stale value of the route table of a sleepy end device (3) was shown instead, and a link at the limit of reception was neither weak, advised nor counted in the score. It is now shown as "very weak" (orange, no bar) and counted as a weak link; the parent search also works on such a node.

## [2.7.0] - 2026-11-15

### Added

- Opening the page and Refresh read every available node again, battery ones included (response time, uptime, contact, role and Thread tables): three nodes at a time, mains nodes first, at most once every 5 minutes, never during a storm. The green dot blinks while the nodes are read, also during the reread after a start.

## [2.6.5] - 2026-11-15

### Fixed

- After a start, the first radio survey no longer uses neighbor and route tables hours old from the Matter Server cache (wrong parent changes, weak links missed): the tables of the mains-powered nodes are read again first, and the survey waits for it.
- A border router alone in its own partition for a few seconds is reported as a short detach of that border router (counted in its detaches and for storms), not as a network partition and a leader change.

### Changed

- Thread partitions and leader change once the new state held 30 seconds.
- One text for every partition change: "Thread partitions: 1 → 2".

## [2.6.4] - 2026-11-15

### Fixed

- A border router offline before a restart stays offline after it: it is no longer counted online for 15 minutes, then reported offline a second time.

## [2.6.3] - 2026-11-14

### Changed

- Node list: the "Clear" button is removed; "All" shows every node again and also clears the text filter.

## [2.6.2] - 2026-11-14

### Fixed

- Path to the border router: a loop between route tables read at different times (a node shown in its own path) now ends the path, marked as incomplete.

## [2.6.1] - 2026-11-14

### Fixed

- Node panel: a parent change made by a parent search shows in "Parent changes" at once.

## [2.6.0] - 2026-11-14

### Added

- Parent search: when the result is not known right away (sleepy node), the add-on reads the node and its parent again every 30 s for 5 minutes, then shows the result (new or same parent, link quality, RSSI), or that the node did not answer.

### Changed

- After a parent search, the advice follows at once: an unstable-parent advice is hidden for 24 h; a weak link that kept the same parent becomes "Add a router near …". The last searches are kept across restarts.

## [2.5.6] - 2026-11-14

### Fixed

- Sorting on "Attachment · signal" follows the link quality, then the RSSI.

## [2.5.5] - 2026-11-14

### Fixed

- Mains-powered children whose route table gives no link quality with their parent are recognised too.

## [2.5.4] - 2026-11-14

### Fixed

- Parent of some battery nodes shown as "router 0"; mains-powered children whose route table keeps an old next hop for their parent are recognised.

## [2.5.3] - 2026-11-14

### Fixed

- A mains-powered node attached as a child (it keeps links with several routers but sends everything through its parent) was shown as a router: it is now an end device with its parent, and can look for a new parent.
- "Find better parents" also covers these nodes.

## [2.5.2] - 2026-11-14

### Added

- Diagnostics: the Thread tables of a node as received (`api/raw?id=`).

## [2.5.1] - 2026-11-14

### Fixed

- The route table of mains-powered nodes is read again every hour, with the neighbor table: the first hop of a router no longer comes from an old route.

## [2.5.0] - 2026-11-14

### Changed

- "Attachment · signal": one signal per node, the weakest direction of the link it sends through (RSSI and link quality).
- A router shows the first hop of its route to the border router; nothing when the route is not known.
- One rule for a weak link everywhere (color, advice, "Find better parents", score): link quality 1, or -90 dBm when it is not known.
- Signal colors: good and fair in green, weak in orange; red is kept for unavailable nodes.
- Parent search result: the parent (new or same) with its link quality and RSSI.

## [2.4.6] - 2026-11-14

### Fixed

- Summary: the number of advised actions matches the cards in "To handle" (identical advice counted once).
- Page header shows the add-on logo.

## [2.4.5] - 2026-11-14

### Fixed

- "new" badge: the date a node was added was not passed to the table.

## [2.4.4] - 2026-11-14

### Added

- "new" badge next to a node added to Matter less than 24 h ago.

## [2.4.3] - 2026-11-14

### Changed

- "To handle": the same advice for several nodes is shown as one card listing the nodes.

## [2.4.2] - 2026-11-14

### Changed

- Screenshot of the page (demo data) in the README and the add-on store.
- Same light bulb icon for every advice in the node list.

## [2.4.1] - 2026-11-14

### Changed

- Router attachment: the neighbor it really sends through (first hop of its
  route to the border router) and that link's signal, instead of its strongest
  neighbor.

## [2.4.0] - 2026-11-14

### Changed

- One kind of advice, *Action advised*, in blue (no more orange nor "Good to
  know"); the verdict of actions is blue too.

### Fixed

- A value read directly from a node (after a parent search, or by the hourly
  read) is no longer overwritten by the older copy the Matter Server keeps: it
  stays until the node reports that attribute, or 2 hours.

## [2.3.4] - 2026-11-14

### Fixed

- Node panel curves end on the current values of the table ("now" was the last
  15-minute point).

## [2.3.3] - 2026-11-14

### Added

- A node that goes silent gets one ping in the background: if it answers, it is
  no longer silent.

## [2.3.2] - 2026-11-14

### Fixed

- Parent search result: only the signal of the table is given (no other source);
  "same parent" when the parent did not change even if the node got a new
  address; the node addresses are read again after the search.
- Attachment signal: when the parent does not give it, the one read on the node
  side is kept instead of "—".

## [2.3.1] - 2026-11-14

### Changed

- Silent nodes: only their status (with its tooltip) shows it, no card in *To
  handle* nor line in the verdict (often short-lived).

## [2.3.0] - 2026-11-14

Texts audit: short and to the point.

### Fixed

- Ping without answer showed "error"; failed actions showed a raw Python error.
- Parent search: the log, the Home Assistant entity and the result now give the
  parent and the signal of the table (received by the parent); a sleeping node
  gives "no answer" instead of "a router has no parent"; same weak threshold as
  the advice (-85 dBm); a router-eligible end device can be asked too.
- "1 others" in the verdict: the unavailable nodes are listed (3 at most).
- The node panel shows the new values after an action.

### Changed

- Shorter texts everywhere (verdict, silent nodes, storm, advice, parent search,
  events, confirmations); "available again" instead of "back"; units written
  "-84 dBm", "24 h", "5 min" in French; no internal event type in the log; the
  advice count is logged only when it changes.
- The result of an action stays until clicked.
- A *Clear* button appears when a filter or a search is active.
- "Good to know" title when there is nothing to handle.

## [2.2.0] - 2026-11-14

### Added

- *Remove* action on a node (after confirmation): removes it from the Matter
  network through the Matter Server. Actions laid out in two rows.

## [2.1.3] - 2026-11-14

### Changed

- Parent search result in a few words: new or same parent and its signal.

## [2.1.2] - 2026-11-14

### Changed

- Parent search from the table: the result gives the signal of the table (received
  by the parent) before and after; the neighbor table of the new parent is read
  at once.

## [2.1.1] - 2026-11-14

### Changed

- Counts written 6× instead of ×6.

## [2.1.0] - 2026-11-14

### Changed

- Advice: *Finding a new parent could improve the situation* (button on the line)
  replaces *Remove the battery 10s* / *Unplug 10s* / *change the parent*; when a
  parent search found nothing better in the last 7 days, *Add a router near…*.
- Fewer columns: the id is in the *Node* column, the link quality (LQI) next to
  the signal, outages 24h and 7d in one column.
- Parent search result: says that the signal is the one received by the node.

## [2.0.2] - 2026-11-14

### Changed

- Quality score parts: the gain over the 24h value is drawn in green, the loss in
  red.

## [2.0.1] - 2026-11-14

### Fixed

- Signal of a link: some firmwares report an impossible average RSSI (e.g. -21dBm
  for a link heard at -77dBm); the last RSSI is used instead. Affected the parent
  search result and the attachment column.

### Changed

- Parent search result names the old and the new parent.
- Shorter tooltips on the action buttons.

## [2.0.0] - 2026-11-14

### Changed

- The new view replaces the old one (no more beta badge or switch).

### Added

- *Actions* column and buttons in the node panel: ping, find a better parent
  (end devices, one node, after confirmation) and interview again.
- Advice for a router whose best link is weak: add a router nearby.

### Fixed

- Path to a border router ending on another router id of the same border router
  was shown as incomplete (*at least N hops*).
- Thread leader shown as unknown when the router asked was the leader itself, or
  when the first routers asked did not answer.

## [1.9.0] - 2026-11-14

### Added

- **Find better parents** button: reads the parent link of every Thread end
  device and asks those whose link is poor (LQI 2 or less, or -80dBm or less)
  to attach again, so they pick a parent among the routers they hear now. The
  node does not reboot and keeps its configuration. Routers and nodes with a
  good link are left alone. Result per node in the `reattach_result` event and
  in `sensor.mesh_guardian_parent_search`. Nothing is sent until the button is
  pressed.
- A parent change that follows this button is no longer counted as a
  spontaneous change of the model.

## [1.8.0] - 2026-11-14

### Added

- Rhythm of each node: its usual silence between two signs of life, measured
  from every contact (with passive contact, close to the liveness interval of
  the Matter subscription). In the API (`rhythm_s`, `silent_limit_s`,
  `silent_s`) and in the technical details of the beta view.
- Beta view: a node silent for much longer than usual is shown *silent* (probably
  without power), minutes before the Matter Server declares it unavailable. No
  extra radio traffic; needs passive contact. The availability, the outages and
  the quality score still follow the Matter Server.

## [1.7.1] - 2026-11-14

### Fixed

- Weak-link advice hidden as soon as the link shown is no longer weak.
- A node announced as a child whose fresh neighbor table has no link with that
  parent but links with several routers is shown as a router (its role and
  address were out of date).

- Weak-link advice disappears as soon as the link is above the weak threshold
  again, without waiting for the next radio survey.
- Mains nodes: the hourly read also refreshes their addresses, so the RLOC16
  (and the parent derived from it) follows a change of role.

## [1.7.0] - 2026-11-14

### Added

- Wi-Fi access points can be named in the node panel (beta view); the name is
  used for every node on that access point when Home Assistant does not know it.

### Fixed

- Missing link signal for mains end devices: their role and neighbor table are
  read again at most hourly (some nodes never report them again, so the Matter
  Server kept an old table). Battery nodes are not read.

## [1.6.0] - 2026-11-14

### Added

- Wi-Fi nodes: access point they are connected to (BSSID matched against the
  MAC addresses of the Home Assistant devices, e.g. UniFi access points), shown
  in the attachment column; the BSSID is on hover and in the API (`bssid`,
  `access_point`).

### Changed

- Beta view: *Power* column (mains or battery), battery icon filled with its
  charge (green > 50 %, orange 20–50 %, red < 20 %).
- Beta view: the column button moved next to the filters (it covered the last
  header); narrower default columns so they fit without scrolling.

## [1.5.2] - 2026-11-14

### Changed

- Beta view curves: scale centered on the 7-day average (dashed line), ±5 dBm at
  least (±50 % for response times), widened by whole steps to fit every point;
  the weak-signal threshold is drawn only when it is within the scale, otherwise
  noted as off scale.

## [1.5.1] - 2026-11-14

### Changed

- Beta view: status and role in one column (*Status · Role*), shorter role names
  (*Sleepy end*, *End*…).

### Fixed

- Beta view: the column button no longer covers the last header; with many
  columns the table scrolls sideways instead of overflowing the card.

## [1.5.0] - 2026-11-14

### Added

- *Border router* column (beta view, shown by default): the border router each
  node reaches Home Assistant through, with the number of hops; the full path is
  in the technical details of the node panel. The API `route` now has `path`,
  `hops` and `complete`.
- Beta view: columns can be moved by dragging their header, or in the column
  list (which follows the same order).

### Changed

- Beta view: no ↔ sign in the attachment column any more; the meaning (parent
  of an end device, best neighbor router of a router) is explained on hover and
  in the node panel.
- Sorting has two states (click, click again to reverse); the default order
  (problems first) is in the column menu.

## [1.4.0] - 2026-11-14

### Added

- Beta view: column picker (small button at the right of the column headers):
  role, path to Home Assistant, link quality, neighbors, weak links, detaches,
  parent changes, outages, downtime, reboots, uptime, RLOC16, id. Remembered per
  browser; the phone cards keep their fixed layout.

### Changed

- Beta view sorting: *Status* sorts available / unavailable, *Attachment ·
  signal* sorts by signal strength, names sort alphabetically (accents ignored).

## [1.3.5] - 2026-11-14

### Changed

- Beta view: the 24h quality score is shown next to the trend, and each part of
  the score has a mark at its 24h value (exact values on hover).

### Fixed

- Response time: after a failed read (node switched off…), the node is read again
  2 minutes after it is back, then with a growing delay, instead of showing
  "no answer" until the next regular read (15 min, 60 min on battery).

## [1.3.4] - 2026-11-14

### Added

- Beta view: sort by clicking a column header (ascending, descending, then back
  to problems first); remembered per browser.

## [1.3.3] - 2026-11-14

### Fixed

- Node table: advice about a parent disappears as soon as the node has left that
  parent for a good link, without waiting for the next radio survey.

## [1.3.2] - 2026-11-14

### Fixed

- Path to the border router: an end device always goes through its parent (its
  own route table can be stale); routers whose link quality to the next hop is
  not published get a path too.

## [1.3.1] - 2026-11-14

### Fixed

- Path to the border router: the route table cost starts at the next hop, the
  link to the next hop is now added (and direct links are taken into account).

## [1.3.0] - 2026-11-14

### Added

- Path to Home Assistant of every Thread node, from the route tables: nearest
  border router (lowest path cost), next hop and cost; end devices go through
  their parent. In the API (`route`) and in the beta view (tooltip of the link
  and node panel).

### Changed

- Beta view: link column renamed *Attachment · signal*, with an explanation.

## [1.2.0] - 2026-11-14

### Added

- New view (beta), reachable from the classic view: summary with verdict and
  quality score parts, list of what to handle, border routers, node list with
  problems first and quick filters, side panel with the 7-day curves and the
  technical details. Follows the Home Assistant light or dark theme, adapted to
  phones. The last view used is kept per browser; the classic view is unchanged.

## [1.1.2] - 2026-11-14

### Fixed

- Nodes shown per network: total of that network instead of all nodes.

## [1.1.1] - 2026-11-14

### Changed

- Network panel: nodes shown counted per network (Thread, Wi-Fi, Ethernet); a
  network without nodes is not listed.

## [1.1.0] - 2026-11-14

### Added

- Matter nodes on Wi-Fi and Ethernet in the node table (column *Network*): link
  and Wi-Fi signal, availability, outages, reboots, uptime, response time, last
  contact, 7-day panel.

## [1.0.0] - 2026-11-14

### Added

- Border router monitoring (any brand): online state, role, partition, network
  prefix, leader, network splits, Thread storms, routing problems (VLAN, IPv6).
- Automatic recovery of lost Matter nodes by ping (off at first start).
- Node table in the sidebar: role, parent or best link with its signal,
  neighbors, detaches, outages, reboots, battery, uptime, last contact, response
  time, advice; compact layout on phones; 7-day panel per node; anonymized report.
- Network quality score (sensor and badge) over the last hour and 24 hours.
- Response time of every node (timed uptime read) and optional passive contact.
- Notification blueprints, MQTT entities, event log, English and French.
