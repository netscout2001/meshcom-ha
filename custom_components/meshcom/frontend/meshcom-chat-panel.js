/*
 * MeshCom panel for Home Assistant: chat, own nodes, heard stations.
 *
 * Security (concept C-01): every text that comes from the radio is untrusted.
 * This file never uses innerHTML, outerHTML, insertAdjacentHTML,
 * document.write, eval or Function, and never turns message text into links.
 * All content is set with textContent. The only link the panel opens is an
 * OpenStreetMap address built from two numbers. A test checks this.
 */

const TEXT = {
  en: {
    title: "MeshCom",
    tabs: { chat: "Chat", nodes: "Nodes", stations: "Stations" },
    filters: { all: "All", unread: "Unread", dm: "DMs", group: "Groups", other: "Other" },
    all: "All",
    group: "Group",
    other: "To",
    newChat: "Callsign for a direct message",
    open: "Open",
    placeholder: "Message",
    send: "Send",
    readOnly: "Messages to this addressee cannot be sent from here.",
    sendingOff: "Sending is switched off for this node.",
    noNodes: "No MeshCom node you are allowed to read.",
    empty: "No messages yet.",
    noConversations: "No conversations in this view.",
    invalidCall: "Not a valid callsign.",
    tooLong: "Too long",
    viaServer: "via server",
    via: "via",
    newMessages: "New messages",
    jump: (n) => (n ? `${n} new` : "Latest"),
    status: {
      sent: "sent",
      heard_by_node: "heard by the node",
      gateway: "at the gateway",
      delivered: "delivered",
      held: "held",
      failed: "failed",
      rejected: "rejected",
      unknown: "unknown",
    },
    error: "Error",
    access: { udp: "External UDP", kiss: "KISS over TCP" },
    dash: {
      uptime: "running",
      now: "now",
      since: (text) => `for ${text}`,
      active: "active",
      inactive: "inactive",
      lastHeard: (text) => `last heard ${text}`,
      server: { connected: "server connected", lost: "server not answering", waiting: "server: no answer yet", no_ip: "no IP address", not_selected: "no server selected", off: "gateway off" },
      kiss: { true: "KISS connected", false: "KISS disconnected" },
      web: { ok: "web API ok", down: "web API not reachable", paused: "web API paused (node inactive)" },
      battery: "Battery",
      signal: "Last signal (packet)",
      channel: "Channel use",
      channelOff: "Switch on \"Read radio statistics\" in the node's options to see channel use and queue.",
      queue: "TX queue",
      queueState: { accepted: "own messages accepted", slow_down: "own messages: slow down", refused: "own messages refused" },
      received: "Received (48 h)",
      sent: "Sent (48 h)",
      stations: "Stations (24 h)",
      directCount: (n) => `${n} direct`,
      kinds: { received_direct: "DM", received_group: "groups", received_all: "to all" },
      delivery: { delivered: "delivered", pending: "open", failed: "failed", unknown: "unknown" },
      activity: "Messages per hour (48 h)",
      utilisation: "Channel use (48 h)",
      receivedLine: "received",
      sentLine: "sent",
      rxLine: "RX",
      txLine: "TX",
      noHistory: "No history yet.",
      groups: { radio: "Radio", status: "Status", gps: "GPS", environment: "Environment" },
      rows: {
        rx: "Channel use RX", tx: "Channel use TX", queue: "TX queue", dropped: "Dropped (5 min)",
        duplicates: "Duplicates (5 min)", dedup: "Dedup window", battery: "Battery", voltage: "Voltage",
        uptime: "Running for", lastPacket: "Last packet", firmware: "Firmware", hardware: "Hardware",
        wifi: "WLAN signal", server: "MeshCom server", blocked: "Blocked frames", hops: "Max. hops text / position",
        satellites: "Satellites", nextBeacon: "Next position", interval: "Position interval",
        received: "Messages received", sentTotal: "Messages sent", duplicatesTotal: "Duplicates since HA start", filtered: "Filtered since HA start",
      },
      fix: "fix",
      noFix: "no fix",
      inMinutes: (min) => `in ${min} min`,
      everyMinutes: (min) => `every ${min} min`,
      minutes: (min) => `${min} min`,
      neighbours: "Direct neighbours",
      noNeighbours: "No direct neighbours. They come from the node's MHeard page (web API).",
      columns: { callsign: "Callsign", snr: "SNR", hearsMe: "Hears me", role: "Relay role", hardware: "Hardware", heard: "Last heard" },
      controls: "Control",
      entities: "All entities",
      days: (d, h) => `${d} d ${h} h`,
      hours: (h, m) => `${h} h ${m} min`,
      mins: (m) => `${m} min`,
      secs: (sec) => `${sec} s`,
      dupOf: (dup, fresh) => `${dup} (${fresh} new)`,
      lastAnswer: (text) => `last answer ${text} ago`,
    },
    map: "Map",
    stationsOff: "Stations are switched off in the options of this node.",
    message: "Message",
    osm: "OpenStreetMap",
    ownNode: "own node",
    dm: "DM",
    showOnMap: "Show on the map",
    legend: { own: "Own node", direct: "Direct neighbour", fresh: "< 1 h", recent: "< 24 h", old: "older" },
    noStations: "No stations heard yet.",
    search: "Search callsign",
    refresh: "Refresh",
    columns: {
      callsign: "Callsign",
      last_heard: "Last heard",
      rssi: "RSSI (dBm)",
      snr: "SNR (dB)",
      hops: "Hops",
      battery: "Battery",
      temperature: "Temp.",
      humidity: "Hum.",
      pressure: "Pressure",
      hardware: "Hardware",
      hears_me_snr: "Hears me",
      relay_role: "Relay role",
      position: "Position",
    },
    direct: "heard directly",
    distance: "Distance",
    directOnly: "Direct neighbours only",
    noDirect: "No direct neighbours. They come from the node's MHeard page (web API).",
    roles: { super: "Super node", needed: "Needed", redundant: "Redundant" },
    hearsMe: (snr) => (snr === null || snr === undefined ? "not reported" : `yes, ${snr} dB`),
    itHears: (all, only) => `Hears ${all} stations, ${only} only it`,
    reports: (n) => `reports ${n} neighbours`,
    altitude: "Altitude",
    gateway: "Gateway",
    showPath: "Show the path on the map",
    ago: (min) => (min < 1 ? "just now" : min < 60 ? `${min} min ago` : min < 1440 ? `${Math.floor(min / 60)} h ago` : `${Math.floor(min / 1440)} d ago`),
    on: "On",
    off: "Off",
  },
  de: {
    title: "MeshCom",
    tabs: { chat: "Chat", nodes: "Nodes", stations: "Stationen" },
    filters: { all: "Alle", unread: "Ungelesen", dm: "DMs", group: "Gruppen", other: "Sonstige" },
    all: "Alle",
    group: "Gruppe",
    other: "An",
    newChat: "Rufzeichen f\u00fcr eine Direktnachricht",
    open: "\u00d6ffnen",
    placeholder: "Nachricht",
    send: "Senden",
    readOnly: "An diesen Adressaten kann von hier nicht gesendet werden.",
    sendingOff: "Senden ist f\u00fcr diesen Node ausgeschaltet.",
    noNodes: "Kein MeshCom-Node, den du lesen darfst.",
    empty: "Noch keine Nachrichten.",
    noConversations: "Keine Gespr\u00e4che in dieser Ansicht.",
    invalidCall: "Kein g\u00fcltiges Rufzeichen.",
    tooLong: "Zu lang",
    viaServer: "\u00fcber Server",
    via: "via",
    newMessages: "Neue Nachrichten",
    jump: (n) => (n ? `${n} neu` : "Neueste"),
    status: {
      sent: "gesendet",
      heard_by_node: "vom Node geh\u00f6rt",
      gateway: "am Gateway",
      delivered: "zugestellt",
      held: "zur\u00fcckgehalten",
      failed: "fehlgeschlagen",
      rejected: "abgelehnt",
      unknown: "unbekannt",
    },
    error: "Fehler",
    access: { udp: "Externes UDP", kiss: "KISS \u00fcber TCP" },
    dash: {
      uptime: "l\u00e4uft",
      now: "jetzt",
      since: (text) => `seit ${text}`,
      active: "aktiv",
      inactive: "inaktiv",
      lastHeard: (text) => `zuletzt geh\u00f6rt ${text}`,
      server: { connected: "Server verbunden", lost: "Server antwortet nicht", waiting: "Server: noch keine Antwort", no_ip: "keine IP-Adresse", not_selected: "kein Server gew\u00e4hlt", off: "Gateway aus" },
      kiss: { true: "KISS verbunden", false: "KISS getrennt" },
      web: { ok: "Web-API ok", down: "Web-API nicht erreichbar", paused: "Web-API pausiert (Node inaktiv)" },
      battery: "Akku",
      signal: "Letztes Signal (Paket)",
      channel: "Kanalauslastung",
      channelOff: "F\u00fcr Kanalauslastung und Warteschlange in den Optionen des Nodes \"Funkstatistik lesen\" einschalten.",
      queue: "Sendewarteschlange",
      queueState: { accepted: "eigene Nachrichten angenommen", slow_down: "eigene Nachrichten: langsamer", refused: "eigene Nachrichten abgelehnt" },
      received: "Empfangen (48 h)",
      sent: "Gesendet (48 h)",
      stations: "Stationen (24 h)",
      directCount: (n) => `${n} direkt`,
      kinds: { received_direct: "DM", received_group: "Gruppen", received_all: "an alle" },
      delivery: { delivered: "zugestellt", pending: "offen", failed: "fehlgeschlagen", unknown: "unbekannt" },
      activity: "Nachrichten pro Stunde (48 h)",
      utilisation: "Kanalauslastung (48 h)",
      receivedLine: "empfangen",
      sentLine: "gesendet",
      rxLine: "RX",
      txLine: "TX",
      noHistory: "Noch kein Verlauf.",
      groups: { radio: "Funk", status: "Status", gps: "GPS", environment: "Umwelt" },
      rows: {
        rx: "Kanalauslastung RX", tx: "Kanalauslastung TX", queue: "Sendewarteschlange", dropped: "Verworfen (5 min)",
        duplicates: "Duplikate (5 min)", dedup: "Dedup-Fenster", battery: "Akku", voltage: "Spannung",
        uptime: "L\u00e4uft seit", lastPacket: "Letztes Paket", firmware: "Firmware", hardware: "Hardware",
        wifi: "WLAN-Signal", server: "MeshCom-Server", blocked: "Gesperrte Rahmen", hops: "Max. Hops Text / Position",
        satellites: "Satelliten", nextBeacon: "N\u00e4chste Position", interval: "Positionsintervall",
        received: "Nachrichten empfangen", sentTotal: "Nachrichten gesendet", duplicatesTotal: "Duplikate seit HA-Start", filtered: "Gefiltert seit HA-Start",
      },
      fix: "Fix",
      noFix: "kein Fix",
      inMinutes: (min) => `in ${min} min`,
      everyMinutes: (min) => `alle ${min} min`,
      minutes: (min) => `${min} min`,
      neighbours: "Direkte Nachbarn",
      noNeighbours: "Keine direkten Nachbarn. Sie kommen von der MHeard-Seite des Nodes (Web-API).",
      columns: { callsign: "Rufzeichen", snr: "SNR", hearsMe: "H\u00f6rt mich", role: "Relay-Rolle", hardware: "Hardware", heard: "Zuletzt geh\u00f6rt" },
      controls: "Steuerung",
      entities: "Alle Entit\u00e4ten",
      days: (d, h) => `${d} T ${h} h`,
      hours: (h, m) => `${h} h ${m} min`,
      mins: (m) => `${m} min`,
      secs: (sec) => `${sec} s`,
      dupOf: (dup, fresh) => `${dup} (${fresh} neu)`,
      lastAnswer: (text) => `letzte Antwort vor ${text}`,
    },
    map: "Karte",
    stationsOff: "Stationen sind in den Optionen dieses Nodes ausgeschaltet.",
    message: "Nachricht",
    osm: "OpenStreetMap",
    ownNode: "eigener Node",
    dm: "DM",
    showOnMap: "Auf der Karte zeigen",
    legend: { own: "Eigener Node", direct: "Direkter Nachbar", fresh: "< 1 h", recent: "< 24 h", old: "\u00e4lter" },
    noStations: "Noch keine Stationen geh\u00f6rt.",
    search: "Rufzeichen suchen",
    refresh: "Aktualisieren",
    columns: {
      callsign: "Rufzeichen",
      last_heard: "Zuletzt geh\u00f6rt",
      rssi: "RSSI (dBm)",
      snr: "SNR (dB)",
      hops: "Hops",
      battery: "Akku",
      temperature: "Temp.",
      humidity: "Feuchte",
      pressure: "Luftdruck",
      hardware: "Hardware",
      hears_me_snr: "H\u00f6rt mich",
      relay_role: "Relay-Rolle",
      position: "Position",
    },
    direct: "direkt geh\u00f6rt",
    distance: "Entfernung",
    directOnly: "Nur direkte Nachbarn",
    noDirect: "Keine direkten Nachbarn. Sie kommen von der MHeard-Seite des Nodes (Web-API).",
    roles: { super: "Supernode", needed: "Ben\u00f6tigt", redundant: "Redundant" },
    hearsMe: (snr) => (snr === null || snr === undefined ? "nicht gemeldet" : `ja, ${snr} dB`),
    itHears: (all, only) => `H\u00f6rt ${all} Stationen, davon ${only} nur sie`,
    reports: (n) => `meldet ${n} Nachbarn`,
    altitude: "H\u00f6he",
    gateway: "Gateway",
    showPath: "Pfad auf der Karte zeigen",
    ago: (min) => (min < 1 ? "gerade eben" : min < 60 ? `vor ${min} min` : min < 1440 ? `vor ${Math.floor(min / 60)} h` : `vor ${Math.floor(min / 1440)} d`),
    on: "An",
    off: "Aus",
  },
};

// Same rule as aiomeshcom/callsign.py; the server checks again.
const CALLSIGN_RE = /^(?=[A-Z0-9]*[0-9])(?=[A-Z0-9]*[A-Z])[A-Z0-9]{3,7}(?:-[0-9]{1,2})?$/;
const MAX_TEXT_BYTES = 150;
const ENCODER = new TextEncoder();
// The only address the panel opens; filled with two checked numbers.
const OSM_URL = "https://www.openstreetmap.org/";
const NEAR_BOTTOM = 80;
const VIEW_KEY = "meshcom-panel-view";
const TABS = ["chat", "nodes", "stations"];
const STATIONS_REFRESH_MS = 60000;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function kindOf(id) {
  if (id === "all") return "all";
  return id.slice(0, id.indexOf(":"));
}

function peerOf(id) {
  return id.slice(id.indexOf(":") + 1);
}

function conversationTitle(id, t) {
  const kind = kindOf(id);
  if (kind === "all") return t.all;
  if (kind === "group") return `${t.group} ${peerOf(id)}`;
  if (kind === "other") return `${t.other} ${peerOf(id)}`;
  return peerOf(id);
}

function avatarText(id) {
  const kind = kindOf(id);
  if (kind === "all") return "*";
  if (kind === "group") return `#${peerOf(id)}`;
  if (kind === "other") return "@";
  return peerOf(id).slice(0, 2);
}

function destinationOf(id) {
  const kind = kindOf(id);
  if (kind === "all") return "*";
  return kind === "group" || kind === "dm" ? peerOf(id) : null;
}

function openMap(lat, lon) {
  const latitude = Number(lat);
  const longitude = Number(lon);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return;
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180) return;
  const la = latitude.toFixed(5);
  const lo = longitude.toFixed(5);
  window.open(`${OSM_URL}?mlat=${la}&mlon=${lo}#map=13/${la}/${lo}`, "_blank", "noopener,noreferrer");
}

const STYLE = `
:host { display: flex; flex-direction: column; height: 100vh; height: 100dvh; overflow: hidden;
  color: var(--primary-text-color); background: var(--primary-background-color);
  font-family: var(--paper-font-body1_-_font-family, inherit); }
.toolbar { display: flex; align-items: center; gap: 8px; height: var(--header-height, 56px);
  padding: 0 12px; border-bottom: 1px solid var(--divider-color); flex-shrink: 0;
  background: var(--app-header-background-color, var(--primary-color, #03a9f4));
  color: var(--app-header-text-color, var(--text-primary-color, #fff)); box-sizing: border-box; }
.toolbar .title { font-size: 20px; margin-right: 12px; }
.tabs { display: flex; gap: 4px; flex: 1; }
.tab { background: none; border: none; color: inherit; padding: 8px 14px; font: inherit;
  border-bottom: 2px solid transparent; opacity: .75; }
.tab.active { opacity: 1; border-bottom-color: currentColor; font-weight: 500; }
.toolbar select { font: inherit; }
.view { flex: 1; min-height: 0; display: flex; }
.view[hidden] { display: none; }
.sidebar { width: 280px; min-width: 220px; border-right: 1px solid var(--divider-color);
  display: flex; flex-direction: column; min-height: 0; background: var(--card-background-color); }
.filters { display: flex; flex-wrap: wrap; gap: 4px; padding: 8px; border-bottom: 1px solid var(--divider-color); }
.chip { border: 1px solid var(--divider-color); background: none; color: inherit; border-radius: 14px;
  padding: 3px 10px; font: inherit; font-size: 12px; display: inline-flex; gap: 4px; align-items: center; }
.chip.active { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); border-color: var(--primary-color, #03a9f4); }
.convlist { flex: 1; overflow-y: auto; min-height: 0; }
.conv { padding: 8px 10px; cursor: pointer; border-bottom: 1px solid var(--divider-color);
  display: flex; align-items: center; gap: 10px; }
.conv:hover, .conv.active { background: var(--secondary-background-color); }
.avatar { width: 36px; height: 36px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center;
  justify-content: center; font-size: 11px; font-weight: bold; color: #fff; overflow: hidden; white-space: nowrap; }
.avatar.all { background: var(--warning-color, #ff9800); }
.avatar.group { background: var(--primary-color, #03a9f4); }
.avatar.dm { background: var(--success-color, #43a047); }
.avatar.other { background: var(--disabled-text-color, #888); }
.conv .info { flex: 1; min-width: 0; }
.conv .name, .conv .last { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.conv .last { font-size: 12px; opacity: .65; }
.conv.unread .name { font-weight: bold; }
.badge { background: var(--accent-color, var(--primary-color, #03a9f4)); color: var(--text-accent-color, #fff);
  border-radius: 10px; min-width: 20px; height: 20px; padding: 0 6px; box-sizing: border-box;
  font-size: 12px; font-weight: bold; line-height: 20px; text-align: center; flex-shrink: 0; }
.newchat { display: flex; gap: 4px; padding: 8px; border-top: 1px solid var(--divider-color); }
.newchat input { flex: 1; min-width: 0; text-transform: uppercase; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; position: relative; }
.convhead { padding: 10px 14px; border-bottom: 1px solid var(--divider-color); font-weight: 500; flex-shrink: 0; }
.messages { flex: 1; overflow-y: auto; min-height: 0; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.msg { max-width: 75%; padding: 6px 10px; border-radius: 10px; background: var(--card-background-color);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.2)); align-self: flex-start; }
.msg.own { align-self: flex-end; background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); }
.msg .meta { font-size: 11px; opacity: .75; }
.msg .sender { font-weight: bold; color: var(--primary-color, #03a9f4); margin-top: 2px; }
.msg.own .sender { color: inherit; }
.msg .text { white-space: pre-wrap; overflow-wrap: anywhere; unicode-bidi: plaintext; }
.msg .status { font-size: 11px; opacity: .75; text-align: right; margin-top: 2px; }
.divider { display: flex; align-items: center; gap: 10px; font-size: 12px; margin: 6px 0; }
.divider::before, .divider::after { content: ""; flex: 1; border-top: 1px solid currentColor; }
.divider.new { color: var(--warning-color, #ff9800); font-weight: bold; }
.divider.day { opacity: .55; }
.jump { position: absolute; right: 20px; bottom: 76px; border: none; border-radius: 16px; padding: 6px 14px;
  background: var(--accent-color, var(--primary-color, #03a9f4)); color: var(--text-accent-color, #fff);
  font: inherit; box-shadow: 0 2px 6px rgba(0,0,0,.3); }
.composer { display: flex; gap: 8px; padding: 8px 12px; border-top: 1px solid var(--divider-color);
  background: var(--card-background-color); align-items: center; flex-shrink: 0; }
.composer input { flex: 1; min-width: 0; font: inherit; padding: 8px; }
.composer .count { font-size: 12px; opacity: .7; min-width: 52px; text-align: right; }
.composer .count.over { color: var(--error-color); opacity: 1; }
.notice, .error { padding: 8px 12px; font-size: 13px; flex-shrink: 0; }
.error { color: var(--error-color); }
.empty { opacity: .6; padding: 24px; text-align: center; }
.scroll { flex: 1; overflow-y: auto; min-height: 0; padding: 16px; }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }
.card { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.2)); padding: 14px 16px; }
.card h2 { margin: 0; font-size: 18px; }
.card .sub { font-size: 12px; opacity: .65; margin-bottom: 10px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 5px 0;
  border-top: 1px solid var(--divider-color); }
.row .label { opacity: .8; }
.nodechips { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
.nodechips[hidden] { display: none; }
.nodechip { display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--divider-color);
  background: var(--card-background-color); color: inherit; border-radius: 18px; padding: 6px 14px; font: inherit; cursor: pointer; }
.nodechip.active { border-color: var(--primary-color, #03a9f4); box-shadow: 0 0 0 1px var(--primary-color, #03a9f4) inset; }
.nodechip .call { font-weight: 500; }
.nodechip .meta { font-size: 12px; opacity: .7; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: #9e9e9e; }
.dot.ok { background: #43a047; } .dot.warn { background: #fb8c00; } .dot.bad { background: #e53935; }
.dot.info { background: #1e88e5; } .dot.off { background: #9e9e9e; }
.dash { display: flex; flex-direction: column; gap: 14px; }
.dash .card h3 { margin: 0 0 10px; font-size: 13px; font-weight: 500; text-transform: uppercase; letter-spacing: .04em; opacity: .75; }
.dashhead { display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px; }
.headmain { display: flex; align-items: center; gap: 12px; min-width: 0; }
.headicon { width: 44px; height: 44px; border-radius: 10px; display: flex; align-items: center; justify-content: center;
  background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); flex-shrink: 0; }
.headtext { min-width: 0; }
.headtext .sub { margin: 2px 0 0; }
.pills { display: flex; flex-wrap: wrap; gap: 6px; }
.pill { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; border-radius: 12px; padding: 3px 10px;
  border: 1px solid var(--divider-color); background: var(--secondary-background-color); }
.pill.ok { border-color: rgba(67,160,71,.5); } .pill.warn { border-color: rgba(251,140,0,.6); } .pill.bad { border-color: rgba(229,57,53,.6); }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(165px, 1fr)); gap: 12px; }
.tile { background: var(--card-background-color); border-radius: var(--ha-card-border-radius, 12px);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.2)); padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.tilehead { display: flex; justify-content: space-between; align-items: center; font-size: 11px; text-transform: uppercase;
  letter-spacing: .05em; opacity: .75; gap: 6px; }
.tile .big { font-size: 26px; font-weight: 600; line-height: 1.1; }
.tile .big .unit { font-size: 13px; font-weight: 400; opacity: .7; margin-left: 4px; }
.tilesub { font-size: 12px; opacity: .75; }
.tile.hint { justify-content: center; }
.bar { display: flex; height: 6px; border-radius: 3px; overflow: hidden; background: var(--divider-color); width: 100%; }
.bar span { height: 100%; }
.minilegend { display: flex; flex-wrap: wrap; gap: 4px 10px; font-size: 11px; opacity: .85; }
.minilegend > span { display: inline-flex; align-items: center; gap: 4px; }
.minilegend i { display: inline-block; width: 10px; height: 10px; border-radius: 2px; }
.qwrap { position: relative; padding-bottom: 14px; }
.qbar { display: flex; gap: 2px; height: 12px; }
.qbar span { flex: 1; border-radius: 2px; }
.qbar span.free { background: var(--divider-color); }
.qtick { position: absolute; top: 0; bottom: 0; border-left: 1px solid var(--primary-text-color); font-size: 10px;
  padding-top: 13px; transform: translateX(-1px); opacity: .7; line-height: 1; }
.spark { width: 100%; height: 24px; display: block; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 14px; }
.chart .chartsvg { width: 100%; height: auto; display: block; }
.chartsvg .grid { stroke: var(--divider-color); stroke-dasharray: 3 4; }
.chartsvg .axis { stroke: var(--divider-color); }
.chartsvg .lbl { fill: var(--secondary-text-color, currentColor); font-size: 11px; }
.sensorgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 8px 24px; }
.srow { display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 5px 0; border-top: 1px solid var(--divider-color); align-items: center; }
.srow .label { opacity: .8; }
.srow .value { text-align: right; font-variant-numeric: tabular-nums; }
.srow .bar { grid-column: 1 / -1; height: 4px; }
.tablewrap { overflow-x: auto; }
table.neighbours { width: 100%; border-collapse: collapse; font-size: 13px; }
table.neighbours th, table.neighbours td { text-align: left; padding: 6px 8px; border-top: 1px solid var(--divider-color); white-space: nowrap; }
table.neighbours th { font-weight: 500; opacity: .75; border-top: none; }
table.neighbours td.num { min-width: 90px; }
table.neighbours td.num .bar { height: 4px; margin-top: 3px; }
details.allentities { margin-top: 10px; }
details.allentities summary { cursor: pointer; opacity: .8; padding: 4px 0; }
.row .value { text-align: right; }
.toggle { font: inherit; border-radius: 14px; padding: 2px 12px; border: 1px solid var(--divider-color);
  background: none; color: inherit; }
.toggle.on { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); border-color: var(--primary-color, #03a9f4); }
.map { position: relative; height: 45vh; min-height: 260px; overflow: hidden; margin-bottom: 12px;
  border-radius: var(--ha-card-border-radius, 12px); background: #aad3df; touch-action: none; cursor: grab; user-select: none; }
.map[hidden] { display: none; }
.map-tiles, .map-markers { position: absolute; inset: 0; }
.map-tile { position: absolute; left: 0; top: 0; width: 257px; height: 257px; pointer-events: none; }
.map.dark { background: #1c1f22; }
.map.dark .map-tile { filter: invert(1) hue-rotate(180deg) brightness(.85) contrast(.9); }
.map-marker { position: absolute; left: 0; top: 0; display: flex; align-items: center; gap: 4px; cursor: pointer; }
.map-marker .dot { width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%; border: 2px solid #fff;
  box-shadow: 0 0 2px rgba(0,0,0,.6); flex-shrink: 0; }
.map-marker .label { margin-top: -6px; font-size: 11px; font-weight: bold; color: #111; white-space: nowrap;
  text-shadow: 0 0 2px #fff, 0 0 2px #fff, 0 0 3px #fff; }
.map-marker.fresh .dot { background: var(--success-color, #43a047); }
.map-marker.recent .dot { background: var(--warning-color, #ff9800); }
.map-marker.old .dot { background: #9e9e9e; }
.map-marker.direct .dot { background: #8e24aa; }
.direct-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #8e24aa; margin-right: 6px; }
.map-popup .direct { font-weight: bold; color: #8e24aa; }
.map-popup .direct .hears { font-weight: normal; color: var(--primary-text-color); }
.map-marker.own .dot { background: var(--primary-color, #03a9f4); width: 16px; height: 16px; margin: -8px 0 0 -8px; }
.map-marker.selected { z-index: 2; }
.map-marker.selected .dot { transform: scale(1.4); }
.map-popup { position: absolute; left: 0; top: 0; z-index: 5; margin: 12px 0 0 -115px; width: 230px;
  max-height: calc(100% - 20px); overflow-y: auto; box-sizing: border-box; padding: 8px 10px;
  background: var(--card-background-color, #fff); color: var(--primary-text-color); border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,.35); font-size: 12px; cursor: default; }
.map-popup[hidden] { display: none; }
.map-popup .title { font-weight: bold; font-size: 14px; }
.map-popup .buttons { display: flex; gap: 6px; margin-top: 6px; flex-wrap: wrap; }
.map-controls { position: absolute; top: 8px; left: 8px; display: flex; flex-direction: column; gap: 4px; z-index: 4; }
.map-controls button { width: 30px; height: 30px; border: none; border-radius: 6px; font-size: 18px; line-height: 1;
  background: var(--card-background-color, #fff); color: var(--primary-text-color); box-shadow: 0 1px 4px rgba(0,0,0,.35); }
.map-path { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; overflow: visible; }
.map-path line { stroke: var(--primary-color, #03a9f4); stroke-width: 3; stroke-linecap: round; opacity: .85; }
.map-path line.gap { stroke-dasharray: 6 6; opacity: .6; }
.map-popup .path { opacity: .8; }
.msg .meta .via { font-size: inherit; color: inherit; text-decoration: underline dotted; }
.map-legend { position: absolute; left: 8px; bottom: 8px; z-index: 4; display: flex; gap: 10px; flex-wrap: wrap;
  padding: 4px 8px; border-radius: 6px; font-size: 11px; cursor: default;
  background: var(--card-background-color, #fff); color: var(--primary-text-color); box-shadow: 0 1px 4px rgba(0,0,0,.35); }
.map-legend .map-marker { position: static; cursor: default; gap: 4px; }
.map-legend .map-marker .dot { margin: 0; width: 10px; height: 10px; }
.map-legend .map-marker.own .dot { margin: 0; width: 12px; height: 12px; }
.map-attribution { position: absolute; right: 0; bottom: 0; z-index: 4; font-size: 10px; padding: 1px 5px;
  background: rgba(255,255,255,.75); color: #333; }
.stationbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 12px; }
.stationbar input { flex: 1 1 160px; max-width: 260px; font: inherit; padding: 6px; }
table { width: 100%; border-collapse: collapse; background: var(--card-background-color); font-size: 14px; }
th, td { padding: 6px 10px; border-bottom: 1px solid var(--divider-color); text-align: left; white-space: nowrap; }
th { cursor: pointer; user-select: none; font-weight: 500; }
td.num, th.num { text-align: right; }
.linkbutton.dm { font-size: 12px; opacity: .8; }
.linkbutton { background: none; border: none; color: var(--primary-color, #03a9f4); font: inherit; padding: 0; cursor: pointer; }
button { font: inherit; cursor: pointer; }
@media (max-width: 700px) {
  .view.chat { flex-direction: column; }
  .sidebar { width: auto; max-height: 40%; border-right: none; border-bottom: 1px solid var(--divider-color); }
  .msg { max-width: 90%; }
  .toolbar .title { display: none; }
}
`;

// --- small tile map --------------------------------------------------------------
// OpenStreetMap tiles as plain images; markers and labels are elements with
// textContent. Tile addresses are built from three integers only.

const TILE_URL = "https://tile.openstreetmap.org/";
const SVG_NS = "http://www.w3.org/2000/svg";
const TILE = 256;
const MIN_ZOOM = 2;
const MAX_ZOOM = 18;
const MAX_LAT = 85.0511;

// Great-circle distance in kilometres (haversine, mean earth radius).
function distanceKm(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(h)));
}

// "850 m", "4,2 km", "37 km" - or miles/feet with the imperial unit system.
function formatDistance(km, imperial, language) {
  const fmt = (value, digits) =>
    value.toLocaleString(language || undefined, { minimumFractionDigits: digits, maximumFractionDigits: digits });
  if (imperial) {
    const miles = km / 1.609344;
    if (miles < 0.1) return `${fmt(Math.round(miles * 5280 / 10) * 10, 0)} ft`;
    return `${fmt(miles, miles < 100 ? 1 : 0)} mi`;
  }
  if (km < 1) return `${fmt(Math.round(km * 100) * 10, 0)} m`;
  return `${fmt(km, km < 100 ? 1 : 0)} km`;
}

function project(lat, lon, zoom) {
  const size = TILE * 2 ** zoom;
  const la = (Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * Math.PI) / 180;
  return {
    x: ((lon + 180) / 360) * size,
    y: ((1 - Math.log(Math.tan(la) + 1 / Math.cos(la)) / Math.PI) / 2) * size,
  };
}

function validPosition(lat, lon) {
  return (
    Number.isFinite(lat) && Number.isFinite(lon) &&
    Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0)
  );
}

class TileMap {
  constructor(container, popupFor, legend, pathFor) {
    this.container = container;
    this.popupFor = popupFor;
    // Points of the radio path of a station: [{lat, lon} | null, ...].
    this.pathFor = pathFor;
    this.route = null;
    this.zoom = 6;
    this.center = { lat: 50.0, lon: 10.0 };
    this.markers = [];
    this.selected = null;
    this.tiles = new Map();
    this.fitted = false;

    this.tileLayer = el("div", "map-tiles");
    this.pathLayer = document.createElementNS(SVG_NS, "svg");
    this.pathLayer.setAttribute("class", "map-path");
    this.markerLayer = el("div", "map-markers");
    this.popup = el("div", "map-popup");
    this.popup.hidden = true;
    const controls = el("div", "map-controls");
    const plus = el("button", null, "+");
    const minus = el("button", null, "\u2212");
    const fit = el("button", null, "\u25a2");
    plus.addEventListener("click", () => this.zoomBy(1));
    minus.addEventListener("click", () => this.zoomBy(-1));
    fit.addEventListener("click", () => this.fit());
    controls.append(plus, minus, fit);
    const attribution = el("div", "map-attribution", "\u00a9 OpenStreetMap contributors");
    const key = el("div", "map-legend");
    for (const kind of ["own", "direct", "fresh", "recent", "old"]) {
      const entry = el("span", `map-marker ${kind}`);
      entry.append(el("span", "dot"), el("span", null, legend[kind]));
      key.append(entry);
    }
    container.append(this.tileLayer, this.pathLayer, this.markerLayer, this.popup, controls, key, attribution);

    // Touch: one finger moves the map, two fingers zoom, a double tap zooms in.
    this._touches = new Map();
    this._pinch = null;
    this._gesture = 0;
    this._lastTap = null;
    this._touchZoomed = 0;
    container.addEventListener("pointerdown", (ev) => this._pointerDown(ev));
    container.addEventListener("pointermove", (ev) => this._touchMove(ev));
    container.addEventListener("pointerup", (ev) => this._touchEnd(ev, true));
    container.addEventListener("pointercancel", (ev) => this._touchEnd(ev, false));
    container.addEventListener("wheel", (ev) => this._wheel(ev), { passive: false });
    container.addEventListener("dblclick", (ev) => {
      if (ev.target.closest && ev.target.closest(".map-popup, .map-controls, .map-legend")) return;
      // A double tap was already handled by the touch code.
      if (Date.now() - this._touchZoomed < 600) return;
      this._zoomAround(1, ev);
    });
    this._resize = new ResizeObserver(() => this.render());
    this._resize.observe(container);
  }

  destroy() {
    this._resize.disconnect();
  }

  get width() {
    return this.container.clientWidth;
  }

  get height() {
    return this.container.clientHeight;
  }

  _origin() {
    const c = project(this.center.lat, this.center.lon, this.zoom);
    // Whole pixels: tiles placed on half pixels leave visible seams.
    return { x: Math.round(c.x - this.width / 2), y: Math.round(c.y - this.height / 2) };
  }

  _unproject(x, y, zoom) {
    const size = TILE * 2 ** zoom;
    const lon = (x / size) * 360 - 180;
    const n = Math.PI - (2 * Math.PI * y) / size;
    const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
    return { lat: Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)), lon: ((((lon + 180) % 360) + 360) % 360) - 180 };
  }

  setMarkers(markers) {
    this.markers = markers.filter((m) => validPosition(m.lat, m.lon));
    if (!this.fitted && this.markers.length && this.width) this.fit();
    else this.render();
  }

  fit() {
    if (!this.markers.length || !this.width) return;
    this.fitted = true;
    this._fitPoints(this.markers);
    this.render();
  }

  // Zoom and centre so that all points are visible (no render).
  _fitPoints(list, maxZoom = 13) {
    const pad = 40;
    let zoom = maxZoom;
    for (; zoom > MIN_ZOOM; zoom -= 1) {
      const points = list.map((m) => project(m.lat, m.lon, zoom));
      const xs = points.map((p) => p.x);
      const ys = points.map((p) => p.y);
      if (Math.max(...xs) - Math.min(...xs) <= this.width - 2 * pad &&
          Math.max(...ys) - Math.min(...ys) <= this.height - 2 * pad) break;
    }
    const points = list.map((m) => project(m.lat, m.lon, zoom));
    const x = (Math.min(...points.map((p) => p.x)) + Math.max(...points.map((p) => p.x))) / 2;
    const y = (Math.min(...points.map((p) => p.y)) + Math.max(...points.map((p) => p.y))) / 2;
    this.zoom = zoom;
    this.center = this._unproject(x, y, zoom);
  }

  _known(points) {
    return (points || []).filter((p) => p && validPosition(p.lat, p.lon));
  }

  // Show a path (e.g. of a chat message) without selecting a station.
  showRoute(points) {
    this.route = points;
    this.selected = null;
    const known = this._known(points);
    if (known.length && this.width) this._fitPoints(known, 12);
    this.render();
  }

  focus(id) {
    const marker = this.markers.find((m) => m.id === id);
    if (!marker) return;
    this.route = null;
    const path = this._known(this.pathFor(id));
    if (path.length > 1 && this.width) {
      // The station and its path to the own node in view.
      this._fitPoints(path, 12);
      this.selected = id;
      this.render();
      return;
    }
    this.zoom = Math.max(this.zoom, 12);
    this.center = { lat: marker.lat, lon: marker.lon };
    this.selected = id;
    this.render();
  }

  zoomBy(delta) {
    this.zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.zoom + delta));
    this.render();
  }

  _zoomAround(delta, ev) {
    const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, this.zoom + delta));
    if (zoom === this.zoom) return;
    const rect = this.container.getBoundingClientRect();
    const origin = this._origin();
    const px = origin.x + ev.clientX - rect.left;
    const py = origin.y + ev.clientY - rect.top;
    const point = this._unproject(px, py, this.zoom);
    // keep the point under the pointer in place
    const after = project(point.lat, point.lon, zoom);
    const cx = after.x - (ev.clientX - rect.left) + this.width / 2;
    const cy = after.y - (ev.clientY - rect.top) + this.height / 2;
    this.zoom = zoom;
    this.center = this._unproject(cx, cy, zoom);
    this.render();
  }

  _wheel(ev) {
    ev.preventDefault();
    const now = Date.now();
    if (this._lastWheel && now - this._lastWheel < 150) return;
    this._lastWheel = now;
    this._zoomAround(ev.deltaY < 0 ? 1 : -1, ev);
  }

  _pointerDown(ev) {
    if (ev.pointerType === "touch") {
      this._touches.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      if (this._touches.size === 2) {
        this._pinchStart();
        return;
      }
      if (this._touches.size > 2) return;
    }
    this._dragStart(ev);
  }

  // Container coordinates of the first two fingers: distance and midpoint.
  _fingers() {
    const rect = this.container.getBoundingClientRect();
    const [a, b] = [...this._touches.values()];
    return {
      dist: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
      x: (a.x + b.x) / 2 - rect.left,
      y: (a.y + b.y) / 2 - rect.top,
    };
  }

  _pinchStart() {
    this._gesture += 1; // ends a running one-finger drag
    this._lastTap = null;
    for (const id of this._touches.keys()) {
      try {
        this.container.setPointerCapture(id);
      } catch (err) {
        // the pointer is already gone
      }
    }
    const f = this._fingers();
    this._pinch = { start: f, last: f, zoom: this.zoom, origin: this._origin() };
    this.popup.hidden = true;
  }

  // Live preview: the drawn map is scaled around the start midpoint and
  // moved with the fingers; the tiles are loaded again when the fingers lift.
  _pinchMove() {
    const pinch = this._pinch;
    const f = this._fingers();
    pinch.last = f;
    const low = 2 ** (MIN_ZOOM - pinch.zoom);
    const high = 2 ** (MAX_ZOOM - pinch.zoom);
    const scale = Math.min(high, Math.max(low, f.dist / pinch.start.dist));
    const dx = f.x - pinch.start.x;
    const dy = f.y - pinch.start.y;
    for (const layer of [this.tileLayer, this.pathLayer, this.markerLayer]) {
      layer.style.transformOrigin = `${pinch.start.x}px ${pinch.start.y}px`;
      layer.style.transform = `translate(${dx}px, ${dy}px) scale(${scale})`;
    }
  }

  // The nearest zoom level; the place under the start midpoint ends up
  // under the last midpoint.
  _pinchEnd() {
    const pinch = this._pinch;
    this._pinch = null;
    for (const layer of [this.tileLayer, this.pathLayer, this.markerLayer]) {
      layer.style.transform = "";
      layer.style.transformOrigin = "";
    }
    const { start, last } = pinch;
    const steps = Math.round(Math.log2(last.dist / start.dist));
    const zoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, pinch.zoom + steps));
    const factor = 2 ** (zoom - pinch.zoom);
    const wx = (pinch.origin.x + start.x) * factor;
    const wy = (pinch.origin.y + start.y) * factor;
    this.zoom = zoom;
    this.center = this._unproject(wx - last.x + this.width / 2, wy - last.y + this.height / 2, zoom);
    this.render();
  }

  _touchMove(ev) {
    const touch = this._touches.get(ev.pointerId);
    if (!touch) return;
    touch.x = ev.clientX;
    touch.y = ev.clientY;
    if (this._pinch && this._touches.size >= 2) this._pinchMove();
  }

  _touchEnd(ev, lifted) {
    if (!this._touches.has(ev.pointerId)) return;
    this._touches.delete(ev.pointerId);
    if (this._pinch) {
      if (this._touches.size < 2) this._pinchEnd();
      return;
    }
    if (!lifted || this._touches.size) return;
    // Double tap: two short taps close together zoom in around them.
    if (ev.target.closest && ev.target.closest(".map-popup, .map-controls, .map-legend, .map-marker")) return;
    const now = Date.now();
    const tap = { time: now, x: ev.clientX, y: ev.clientY, gesture: this._gesture };
    const last = this._lastTap;
    if (last && now - last.time < 350 && Math.hypot(last.x - tap.x, last.y - tap.y) < 30 && last.gesture === tap.gesture) {
      this._lastTap = null;
      this._touchZoomed = now;
      this._zoomAround(1, ev);
      return;
    }
    this._lastTap = tap;
  }

  _dragStart(ev) {
    if (ev.button !== 0) return;
    if (ev.target.closest && ev.target.closest(".map-popup, .map-controls, .map-marker")) return;
    const start = { x: ev.clientX, y: ev.clientY, center: project(this.center.lat, this.center.lon, this.zoom) };
    const gesture = this._gesture;
    let moved = false;
    this.container.setPointerCapture(ev.pointerId);
    const move = (e) => {
      if (e.pointerId !== ev.pointerId) return;
      // A second finger turned the drag into a pinch.
      if (this._gesture !== gesture) return;
      const dx = e.clientX - start.x;
      const dy = e.clientY - start.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) moved = true;
      this.center = this._unproject(start.center.x - dx, start.center.y - dy, this.zoom);
      this.render();
    };
    const up = (e) => {
      if (e.pointerId !== ev.pointerId) return;
      this.container.removeEventListener("pointermove", move);
      this.container.removeEventListener("pointerup", up);
      this.container.removeEventListener("pointercancel", up);
      if (this._gesture !== gesture) return;
      if (moved) this._lastTap = null;
      if (!moved && (this.selected !== null || this.route !== null)) {
        this.selected = null;
        this.route = null;
        this.render();
      }
    };
    this.container.addEventListener("pointermove", move);
    this.container.addEventListener("pointerup", up);
    this.container.addEventListener("pointercancel", up);
  }

  render() {
    const width = this.width;
    const height = this.height;
    if (!width || !height) return;
    const origin = this._origin();
    const count = 2 ** this.zoom;
    const wanted = new Set();
    const x0 = Math.floor(origin.x / TILE);
    const x1 = Math.floor((origin.x + width) / TILE);
    const y0 = Math.max(0, Math.floor(origin.y / TILE));
    const y1 = Math.min(count - 1, Math.floor((origin.y + height) / TILE));
    for (let x = x0; x <= x1; x += 1) {
      for (let y = y0; y <= y1; y += 1) {
        const tx = ((x % count) + count) % count;
        const key = `${this.zoom}/${x}/${y}`;
        wanted.add(key);
        let img = this.tiles.get(key);
        if (!img) {
          img = document.createElement("img");
          img.className = "map-tile";
          img.alt = "";
          img.draggable = false;
          img.addEventListener("error", () => { img.style.visibility = "hidden"; });
          img.referrerPolicy = "strict-origin-when-cross-origin";
          img.src = `${TILE_URL}${Number(this.zoom)}/${Number(tx)}/${Number(y)}.png`;
          this.tiles.set(key, img);
          this.tileLayer.append(img);
        }
        img.style.transform = `translate(${x * TILE - origin.x}px, ${y * TILE - origin.y}px)`;
      }
    }
    for (const [key, img] of this.tiles) {
      if (!wanted.has(key)) {
        img.remove();
        this.tiles.delete(key);
      }
    }

    const items = [];
    for (const marker of this.markers) {
      const p = project(marker.lat, marker.lon, this.zoom);
      const left = p.x - origin.x;
      const top = p.y - origin.y;
      if (left < -50 || top < -20 || left > width + 50 || top > height + 20) continue;
      const item = el("div", `map-marker ${marker.kind}`);
      item.style.transform = `translate(${Math.round(left)}px, ${Math.round(top)}px)`;
      item.append(el("span", "dot"), el("span", "label", marker.label));
      item.addEventListener("click", (ev) => {
        ev.stopPropagation();
        this.selected = this.selected === marker.id ? null : marker.id;
        this.route = null;
        this.render();
      });
      if (marker.id === this.selected) item.classList.add("selected");
      items.push(item);
    }
    this.markerLayer.replaceChildren(...items);
    this._renderPath(origin);

    const chosen = this.markers.find((m) => m.id === this.selected);
    if (chosen) {
      const p = project(chosen.lat, chosen.lon, this.zoom);
      this.popup.replaceChildren(...this.popupFor(chosen.id));
      // Keep the box (230 px wide, centred under the marker) inside the map;
      // near the bottom edge it opens above the marker, and if it fits on
      // neither side it is moved up until it is fully visible.
      const x = Math.min(Math.max(p.x - origin.x, 123), width - 123);
      this.popup.hidden = false;
      const box = this.popup.offsetHeight;
      let y = p.y - origin.y;
      if (y + 12 + box > height) y = y - box - 24 >= 0 ? y - box - 24 : Math.max(-4, height - 16 - box);
      this.popup.style.transform = `translate(${Math.round(x)}px, ${Math.round(y)}px)`;
    } else {
      this.popup.hidden = true;
    }
  }

  // Lines between the known positions of a path; dashed across unknown hops.
  _renderPath(origin) {
    const points = this.selected !== null ? this.pathFor(this.selected) : this.route;
    const lines = [];
    let last = null;
    let gap = false;
    for (const point of points || []) {
      if (!point || !validPosition(point.lat, point.lon)) {
        gap = true;
        continue;
      }
      const p = project(point.lat, point.lon, this.zoom);
      const here = { x: Math.round(p.x - origin.x), y: Math.round(p.y - origin.y) };
      if (last) {
        const line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", String(last.x));
        line.setAttribute("y1", String(last.y));
        line.setAttribute("x2", String(here.x));
        line.setAttribute("y2", String(here.y));
        if (gap) line.setAttribute("class", "gap");
        lines.push(line);
      }
      last = here;
      gap = false;
    }
    this.pathLayer.replaceChildren(...lines);
  }
}

// Callsigns never start with "#", so this id cannot clash with a station.
// --- nodes dashboard: constants and helpers ---------------------------------------

const DASH_WINDOW_MS = 48 * 3600000;
const DASH_REFRESH_MS = 30000;
const DASH_HISTORY_MS = 5 * 60000;
const PRIORITIES = ["crit", "high", "normal", "low", "bg"];
// The node's own colours for the queue priorities (web_functions.cpp).
const PRIORITY_COLORS = { crit: "#A2182F", high: "#E07B39", normal: "#3B7DD8", low: "#6FA96F", bg: "#9E9E9E" };
const LEVEL_COLORS = { ok: "#43a047", warn: "#fb8c00", bad: "#e53935", info: "#1e88e5", off: "#9e9e9e" };
const SERIES_COLORS = { received: "#43a047", sent: "#1e88e5", rx: "#3B7DD8", tx: "#A2182F" };
const DIRECT_COLOR = "#8e24aa";
const ACTIVITY_KINDS = ["received_direct", "received_group", "received_all", "sent"];
const KIND_COLORS = { received_direct: "#43a047", received_group: "#1e88e5", received_all: "#fb8c00" };
const DELIVERY_STATES = ["delivered", "pending", "failed", "unknown"];
const DELIVERY_COLORS = { delivered: "#43a047", pending: "#1e88e5", failed: "#e53935", unknown: "#9e9e9e" };
const ENVIRONMENT_KEYS = ["temperature_1", "temperature_2", "humidity", "pressure_qnh", "pressure_qfe", "co2"];
// mdi:radio-tower (Pictogrammers, Apache License 2.0).
const ICON_TOWER =
  "M12,10A2,2 0 0,1 14,12C14,12.5 13.82,12.94 13.53,13.29L16.7,22H14.6L12,14.85L9.4,22H7.3L10.47,13.29C10.18,12.94 10,12.5 10,12A2,2 0 0,1 12,10M12,8A4,4 0 0,0 8,12C8,12.5 8.1,13 8.28,13.46L7.4,15.86C6.53,14.81 6,13.47 6,12A6,6 0 0,1 12,6A6,6 0 0,1 18,12C18,13.47 17.47,14.81 16.6,15.86L15.72,13.46C15.9,13 16,12.5 16,12A4,4 0 0,0 12,8M12,4A8,8 0 0,0 4,12C4,14.36 5,16.5 6.64,17.94L5.92,19.94C3.54,18.11 2,15.23 2,12A10,10 0 0,1 12,2A10,10 0 0,1 22,12C22,15.23 20.46,18.11 18.08,19.94L17.36,17.94C19,16.5 20,14.36 20,12A8,8 0 0,0 12,4Z";

function svg(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, String(value));
  return node;
}

// A round axis maximum (1, 2, 5, 10, 20, 50, ...).
function niceMax(value) {
  if (!(value > 0)) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  for (const step of [1, 2, 5, 10]) if (value <= step * power) return step * power;
  return 10 * power;
}

const OWN_MARKER = "#own";

class MeshComChatPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._narrow = false;
    this._nodes = [];
    this._entryId = null;
    this._messages = [];
    this._active = "all";
    this._tab = "chat";
    this._filter = "all";
    this._pinned = null;
    // Last read message time per conversation, kept per browser.
    this._read = {};
    // Read time of the open conversation when it was opened: the divider.
    this._dividerSince = null;
    this._unsubscribe = null;
    this._started = false;
    this._error = "";
    this._stations = null;
    this._stationsMode = "data";
    this._stationSort = { key: "last_heard", desc: true };
    this._stationFilter = "";
    this._directOnly = false;
    this._nodesSignature = "";
    this._loaded = false;
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._start();
    else if (this._tab === "nodes") this._renderNodes();
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._narrow = value;
    if (this._menu) this._menu.narrow = value;
  }

  get _t() {
    const lang = (this._hass && this._hass.language) || "en";
    return lang.startsWith("de") ? TEXT.de : TEXT.en;
  }

  disconnectedCallback() {
    clearTimeout(this._retry);
    clearInterval(this._stationTimer);
    clearInterval(this._nodeTimer);
    this._stopSubscription();
    if (this._hass && this._onReady) {
      this._hass.connection.removeEventListener("ready", this._onReady);
    }
    this._started = false;
  }

  connectedCallback() {
    if (this._hass && !this._started) this._start();
  }

  async _start() {
    if (this._started || !this._hass) return;
    this._started = true;
    this._buildSkeleton();
    // After a reconnect the subscription comes back on its own, but messages
    // received in between are missing: reload the history.
    this._onReady = () => this._selectNode(this._entryId);
    this._hass.connection.addEventListener("ready", this._onReady);
    try {
      const result = await this._hass.callWS({ type: "meshcom/chat/nodes" });
      this._nodes = result.nodes;
    } catch (err) {
      this._showError(err);
      return;
    }
    this._loaded = true;
    this._renderNodeSelect();
    if (this._nodes.length) {
      const remembered = this._loadView();
      this._directOnly = remembered.directOnly;
      if (this._directButton) this._directButton.className = this._directOnly ? "toggle on" : "toggle";
      const node = this._nodes.find((n) => n.entry_id === remembered.node) || this._nodes[0];
      if (remembered.tab && remembered.tab !== this._tab) this._setTab(remembered.tab);
      await this._selectNode(node.entry_id);
    } else {
      this._render();
    }
  }

  // --- skeleton ----------------------------------------------------------------

  _buildSkeleton() {
    const t = this._t;
    const root = this.shadowRoot;
    root.replaceChildren();
    const style = el("style");
    style.textContent = STYLE;
    root.append(style);

    const toolbar = el("div", "toolbar");
    this._menu = document.createElement("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    const tabs = el("div", "tabs");
    this._tabButtons = {};
    for (const key of TABS) {
      const button = el("button", "tab", t.tabs[key]);
      button.addEventListener("click", () => this._setTab(key));
      this._tabButtons[key] = button;
      tabs.append(button);
    }
    this._nodeSelect = el("select");
    this._nodeSelect.addEventListener("change", () => this._selectNode(this._nodeSelect.value));
    toolbar.append(this._menu, el("div", "title", t.title), tabs, this._nodeSelect);

    this._errorLine = el("div", "error");
    root.append(toolbar, this._errorLine, this._buildChat(), this._buildNodes(), this._buildStations());
    this._setTab(this._tab);
  }

  _buildChat() {
    const t = this._t;
    const view = el("div", "view chat");
    this._chatView = view;

    const sidebar = el("div", "sidebar");
    this._filterBar = el("div", "filters");
    this._convList = el("div", "convlist");
    const newChat = el("form", "newchat");
    this._newCall = el("input");
    this._newCall.placeholder = t.newChat;
    this._newCall.maxLength = 10;
    this._newCall.autocomplete = "off";
    newChat.append(this._newCall, el("button", null, t.open));
    newChat.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._openDirect(this._newCall.value);
    });
    sidebar.append(this._filterBar, this._convList, newChat);

    const main = el("div", "main");
    this._convHead = el("div", "convhead");
    this._messageList = el("div", "messages");
    this._messageList.addEventListener("scroll", () => this._onScroll());
    this._jump = el("button", "jump");
    this._jump.hidden = true;
    this._jump.addEventListener("click", () => {
      this._scrollDown();
      this._onScroll();
    });
    this._notice = el("div", "notice");
    const composer = el("form", "composer");
    this._input = el("input");
    this._input.placeholder = t.placeholder;
    this._input.autocomplete = "off";
    this._count = el("span", "count");
    this._sendButton = el("button", null, t.send);
    composer.append(this._input, this._count, this._sendButton);
    composer.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._send();
    });
    this._input.addEventListener("input", () => this._updateCount());
    this._composer = composer;
    main.append(this._convHead, this._messageList, this._jump, this._notice, composer);

    view.append(sidebar, main);
    return view;
  }

  _buildStations() {
    const t = this._t;
    this._stationsView = el("div", "view");
    const body = el("div", "scroll");
    const bar = el("div", "stationbar");
    this._stationSearch = el("input");
    this._stationSearch.placeholder = t.search;
    this._stationSearch.addEventListener("input", () => {
      this._stationFilter = this._stationSearch.value.trim().toUpperCase();
      this._renderStations();
    });
    // Only the stations the node heard directly (its MHeard list).
    this._directButton = el("button", this._directOnly ? "toggle on" : "toggle", t.directOnly);
    this._directButton.addEventListener("click", () => {
      this._directOnly = !this._directOnly;
      this._directButton.className = this._directOnly ? "toggle on" : "toggle";
      this._saveView();
      this._renderStations();
    });
    const refresh = el("button", "toggle", t.refresh);
    refresh.addEventListener("click", () => this._loadStations());
    bar.append(this._stationSearch, this._directButton, refresh);
    this._mapBox = el("div", "map");
    this._map = null;
    this._stationsBody = el("div");
    body.append(this._mapBox, bar, this._stationsBody);
    this._stationsView.append(body);
    return this._stationsView;
  }

  _setTab(tab) {
    this._tab = tab;
    this._saveView();
    for (const [key, button] of Object.entries(this._tabButtons)) {
      button.className = key === tab ? "tab active" : "tab";
    }
    this._chatView.hidden = tab !== "chat";
    this._nodesView.hidden = tab !== "nodes";
    this._stationsView.hidden = tab !== "stations";
    clearInterval(this._stationTimer);
    clearInterval(this._nodeTimer);
    if (tab === "nodes") {
      this._nodesSignature = "";
      this._renderNodes();
      this._loadNodeStatus();
      this._nodeTimer = setInterval(() => this._loadNodeStatus(), DASH_REFRESH_MS);
    } else if (tab === "stations") {
      this._loadStations();
      this._stationTimer = setInterval(() => this._loadStations(), STATIONS_REFRESH_MS);
    } else {
      this._render();
      this._scrollToStart();
    }
  }

  _renderNodeSelect() {
    this._nodeSelect.replaceChildren();
    for (const node of this._nodes) {
      const option = el("option", null, node.callsign);
      option.value = node.entry_id;
      this._nodeSelect.append(option);
    }
    this._nodeSelect.hidden = this._nodes.length < 2;
  }

  get _node() {
    return this._nodes.find((node) => node.entry_id === this._entryId) || null;
  }

  // --- data ----------------------------------------------------------------------

  async _selectNode(entryId) {
    if (!entryId) return;
    this._stopSubscription();
    if (entryId !== this._entryId) {
      // Conversations belong to one node: start the other node at "All".
      this._active = "all";
      this._pinned = null;
      this._dividerSince = null;
    }
    this._entryId = entryId;
    this._saveView();
    this._nodeSelect.value = entryId;
    this._stations = null;
    try {
      const history = await this._hass.callWS({ type: "meshcom/chat/history", entry_id: entryId });
      this._messages = history.messages;
      const stored = this._loadRead(entryId);
      if (stored === null) {
        // First visit in this browser: the history counts as read.
        this._read = {};
        for (const m of this._messages) this._read[m.conversation] = m.time;
        this._saveRead();
      } else {
        this._read = stored;
      }
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (event) => this._onEvent(entryId, event),
        { type: "meshcom/chat/subscribe", entry_id: entryId }
      );
      this._error = "";
    } catch (err) {
      this._showError(err);
    }
    if (this._tab === "stations") this._loadStations();
    if (this._tab === "nodes") this._loadNodeStatus();
    this._openConversation(this._active);
  }

  _reconnect(entryId, attempt) {
    clearTimeout(this._retry);
    this._retry = setTimeout(async () => {
      if (!this._started || entryId !== this._entryId) return;
      try {
        const result = await this._hass.callWS({ type: "meshcom/chat/nodes" });
        this._nodes = result.nodes;
        this._renderNodeSelect();
        if (this._nodes.some((node) => node.entry_id === entryId)) {
          await this._selectNode(entryId);
          return;
        }
      } catch (err) {
        // try again below
      }
      if (attempt < 10) this._reconnect(entryId, attempt + 1);
    }, 2000 * attempt);
  }

  _stopSubscription() {
    if (this._unsubscribe) {
      const unsubscribe = this._unsubscribe;
      this._unsubscribe = null;
      Promise.resolve(unsubscribe()).catch(() => {});
    }
  }

  _onEvent(entryId, event) {
    if (entryId !== this._entryId) return;
    if (event.closed) {
      // The node is being reloaded (e.g. options changed): reconnect.
      this._unsubscribe = null;
      this._reconnect(entryId, 1);
      return;
    }
    if (event.message) {
      const message = event.message;
      const atBottom = this._isNearBottom();
      this._messages.push(message);
      if (this._messages.length > 500) this._messages.shift();
      if (message.conversation === this._active && (atBottom || message.own)) {
        this._markRead(this._active);
      } else if (message.conversation === this._active && this._dividerSince === null) {
        // Scrolled up while new messages arrive: mark where they start.
        this._dividerSince = this._read[this._active] || "";
      }
      this._render();
      if (message.conversation === this._active && (atBottom || message.own)) this._scrollDown();
    } else if (event.status) {
      const target = [...this._messages].reverse().find((m) => m.own && m.id === event.status.id);
      if (target) {
        target.status = event.status.status;
        this._render();
      }
    }
  }

  // --- read state ----------------------------------------------------------------

  // Selected node and tab, kept per browser so a reload opens the same view.
  _loadView() {
    try {
      const data = JSON.parse(window.localStorage.getItem(VIEW_KEY) || "{}");
      return {
        node: typeof data.node === "string" ? data.node : null,
        tab: TABS.includes(data.tab) ? data.tab : null,
        directOnly: data.directOnly === true,
      };
    } catch (err) {
      return { node: null, tab: null, directOnly: false };
    }
  }

  _saveView() {
    if (!this._loaded) return;
    try {
      window.localStorage.setItem(
        VIEW_KEY,
        JSON.stringify({ node: this._entryId, tab: this._tab, directOnly: this._directOnly })
      );
    } catch (err) {
      // not stored: the panel opens with the first node next time
    }
  }

  get _readKey() {
    return `meshcom-chat-read:${this._entryId}`;
  }

  _loadRead(entryId) {
    // Browser storage can be missing or blocked; then nothing is remembered.
    try {
      const raw = window.localStorage.getItem(`meshcom-chat-read:${entryId}`);
      if (raw === null) return null;
      const data = JSON.parse(raw);
      if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
      const read = {};
      for (const [key, value] of Object.entries(data)) {
        if (typeof key === "string" && key.length < 40 && typeof value === "string" && value.length < 40) {
          read[key] = value;
        }
      }
      return read;
    } catch (err) {
      return null;
    }
  }

  _saveRead() {
    try {
      window.localStorage.setItem(this._readKey, JSON.stringify(this._read));
    } catch (err) {
      // not stored: badges start from scratch next time
    }
  }

  _messagesOf(id) {
    return this._messages.filter((m) => m.conversation === id);
  }

  _markRead(id) {
    const messages = this._messagesOf(id);
    if (!messages.length) return;
    const newest = messages[messages.length - 1].time;
    if (this._read[id] !== newest) {
      this._read[id] = newest;
      this._saveRead();
    }
  }

  _unreadCount(id) {
    const since = this._read[id] || "";
    let count = 0;
    for (const m of this._messages) {
      if (m.conversation === id && !m.own && m.time > since) count += 1;
    }
    return count;
  }

  // --- chat ----------------------------------------------------------------------

  _openConversation(id) {
    this._active = id;
    // Stays in the list while it is open, e.g. under "Unread" after reading.
    this._pinned = id;
    // Where the new messages start; kept while the conversation stays open.
    this._dividerSince = this._unreadCount(id) ? this._read[id] || "" : null;
    this._markRead(id);
    this._render();
    this._scrollToStart();
  }

  _conversations() {
    const last = new Map([["all", ""]]);
    const node = this._node;
    if (node) for (const group of node.groups) last.set(`group:${group}`, "");
    for (const message of this._messages) last.set(message.conversation, message.time);
    if (!last.has(this._active)) last.set(this._active, "");
    return [...last.entries()]
      .sort((a, b) => (a[0] === "all" ? -1 : b[0] === "all" ? 1 : b[1].localeCompare(a[1])))
      .map(([id]) => id);
  }

  _inFilter(id, filter) {
    const kind = kindOf(id);
    if (filter === "unread") return this._unreadCount(id) > 0;
    if (filter === "dm") return kind === "dm";
    if (filter === "group") return kind === "group" || kind === "all";
    if (filter === "other") return kind === "other";
    return true;
  }

  _render() {
    if (!this._convList || !this._loaded) return;
    const t = this._t;
    this._errorLine.textContent = this._error;
    this._errorLine.hidden = !this._error;

    if (!this._nodes.length) {
      this._filterBar.replaceChildren();
      this._convList.replaceChildren();
      this._convHead.textContent = "";
      this._messageList.replaceChildren(el("div", "empty", t.noNodes));
      this._composer.hidden = true;
      this._notice.hidden = true;
      this._jump.hidden = true;
      return;
    }

    const conversations = this._conversations();
    this._filterBar.replaceChildren(
      ...["all", "unread", "dm", "group", "other"].map((key) => {
        const chip = el("button", key === this._filter ? "chip active" : "chip", t.filters[key]);
        const unread = conversations
          .filter((id) => id !== this._active && this._inFilter(id, key))
          .reduce((sum, id) => sum + this._unreadCount(id), 0);
        if (unread && key !== "all") chip.append(el("span", "badge", unread > 99 ? "99+" : unread));
        chip.addEventListener("click", () => {
          this._filter = key;
          this._pinned = null;
          this._render();
        });
        return chip;
      })
    );

    const visible = conversations.filter(
      (id) => id === this._pinned || this._inFilter(id, this._filter)
    );
    if (!visible.length) {
      this._convList.replaceChildren(el("div", "empty", t.noConversations));
    } else {
      this._convList.replaceChildren(...visible.map((id) => this._renderConversation(id, t)));
    }

    this._convHead.textContent = conversationTitle(this._active, t);
    this._convHead.dir = "auto";
    this._renderMessages(t);

    const destination = destinationOf(this._active);
    const node = this._node;
    let notice = "";
    if (destination === null) notice = t.readOnly;
    else if (node && !node.sending_enabled) notice = t.sendingOff;
    this._notice.textContent = notice;
    this._notice.hidden = !notice;
    this._composer.hidden = destination === null;
    this._updateCount();
    this._updateJump();
  }

  _renderConversation(id, t) {
    const unread = id === this._active ? 0 : this._unreadCount(id);
    const classes = ["conv"];
    if (id === this._active) classes.push("active");
    if (unread) classes.push("unread");
    const row = el("div", classes.join(" "));
    row.append(el("div", `avatar ${kindOf(id)}`, avatarText(id)));
    const info = el("div", "info");
    const name = el("div", "name", conversationTitle(id, t));
    name.dir = "auto";
    info.append(name);
    const messages = this._messagesOf(id);
    if (messages.length) {
      const lastMessage = messages[messages.length - 1];
      const preview = el("div", "last", `${lastMessage.sender}: ${lastMessage.text}`);
      preview.dir = "auto";
      info.append(preview);
    }
    row.append(info);
    if (unread) row.append(el("span", "badge", unread > 99 ? "99+" : unread));
    row.addEventListener("click", () => this._openConversation(id));
    return row;
  }

  _renderMessages(t) {
    const list = this._messageList;
    const atBottom = this._isNearBottom();
    const keepTop = list.scrollTop;
    const messages = this._messagesOf(this._active);
    if (!messages.length) {
      list.replaceChildren(el("div", "empty", t.empty));
      return;
    }
    const items = [];
    let lastDay = "";
    let dividerDone = this._dividerSince === null;
    this._dividerElement = null;
    for (const m of messages) {
      const time = new Date(m.time);
      const day = Number.isNaN(time.getTime()) ? "" : time.toDateString();
      if (day && day !== lastDay) {
        items.push(el("div", "divider day", time.toLocaleDateString(this._hass.language || undefined, { dateStyle: "medium" })));
        lastDay = day;
      }
      if (!dividerDone && !m.own && m.time > this._dividerSince) {
        const divider = el("div", "divider new", t.newMessages);
        this._dividerElement = divider;
        items.push(divider);
        dividerDone = true;
      }
      items.push(this._renderMessage(m, t, time));
    }
    list.replaceChildren(...items);
    if (atBottom) this._scrollDown();
    else list.scrollTop = keepTop;
  }

  _renderMessage(message, t, time) {
    const box = el("div", message.own ? "msg own" : "msg");
    const parts = [];
    if (!Number.isNaN(time.getTime())) {
      parts.push(time.toLocaleTimeString(this._hass.language || undefined, { timeStyle: "medium" }));
    }
    const path = Array.isArray(message.path) ? message.path : [];
    const tail = [];
    if (message.via_server) tail.push(t.viaServer);
    if (!message.own && message.rssi !== null && message.rssi !== undefined) {
      tail.push(`${message.rssi} dBm / ${message.snr} dB`);
    }
    const meta = el("div", "meta", parts.join(" \u00b7 "));
    meta.dir = "auto";
    if (path.length > 1) {
      // The path opens the map with the route of this message.
      const via = el("button", "linkbutton via", `${t.via} ${path.join(" > ")}`);
      via.title = t.showPath;
      via.addEventListener("click", () => this._showRoute(path));
      meta.append(" \u00b7 ", via);
    }
    if (tail.length) meta.append(` \u00b7 ${tail.join(" \u00b7 ")}`);
    box.append(meta);
    if (!message.own) box.append(el("div", "sender", `${message.sender}:`));
    const text = el("div", "text", message.text);
    text.dir = "auto";
    box.append(text);
    if (message.own && message.status) {
      box.append(el("div", "status", t.status[message.status] || t.status.unknown));
    }
    return box;
  }

  _isNearBottom() {
    const list = this._messageList;
    if (!list) return true;
    return list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_BOTTOM;
  }

  _onScroll() {
    if (this._isNearBottom() && this._unreadCount(this._active)) {
      this._markRead(this._active);
      this._render();
    }
    this._updateJump();
  }

  _updateJump() {
    if (!this._jump) return;
    const show = !this._isNearBottom();
    this._jump.hidden = !show;
    if (show) this._jump.textContent = `\u2193 ${this._t.jump(this._unreadCount(this._active))}`;
  }

  _scrollToStart() {
    // Open at the first new message, otherwise at the newest one.
    requestAnimationFrame(() => {
      if (this._dividerElement) {
        this._messageList.scrollTop = Math.max(0, this._dividerElement.offsetTop - this._messageList.offsetTop - 8);
      } else {
        this._scrollDown();
      }
      this._updateJump();
    });
  }

  _updateCount() {
    const bytes = ENCODER.encode(this._input.value).length;
    this._count.textContent = `${bytes}/${MAX_TEXT_BYTES}`;
    const over = bytes > MAX_TEXT_BYTES;
    this._count.className = over ? "count over" : "count";
    const node = this._node;
    this._sendButton.disabled =
      over || bytes === 0 || !node || !node.sending_enabled || destinationOf(this._active) === null;
  }

  _openDirect(value) {
    const call = value.trim().toUpperCase();
    if (!CALLSIGN_RE.test(call)) {
      this._error = this._t.invalidCall;
      this._render();
      return;
    }
    this._error = "";
    this._newCall.value = "";
    this._setTab("chat");
    this._openConversation(`dm:${call}`);
  }

  async _send() {
    const destination = destinationOf(this._active);
    const text = this._input.value;
    if (destination === null || !text) return;
    if (ENCODER.encode(text).length > MAX_TEXT_BYTES) {
      this._error = this._t.tooLong;
      this._render();
      return;
    }
    this._sendButton.disabled = true;
    try {
      await this._hass.callWS({
        type: "meshcom/chat/send",
        entry_id: this._entryId,
        destination,
        text,
      });
      this._input.value = "";
      this._error = "";
    } catch (err) {
      this._showError(err);
    }
    this._render();
  }

  _showError(err) {
    const message = err && err.message ? err.message : String(err);
    this._error = `${this._t.error}: ${message}`;
    if (this._errorLine) {
      this._errorLine.textContent = this._error;
      this._errorLine.hidden = false;
    }
  }

  _scrollDown() {
    if (this._messageList) this._messageList.scrollTop = this._messageList.scrollHeight;
  }

  // --- nodes ---------------------------------------------------------------------

  // --- nodes dashboard -----------------------------------------------------------

  _buildNodes() {
    this._nodesView = el("div", "view");
    this._nodesBody = el("div", "scroll");
    this._nodeChips = el("div", "nodechips");
    this._nodeDash = el("div", "dash");
    this._nodesBody.append(this._nodeChips, this._nodeDash);
    this._nodesView.append(this._nodesBody);
    return this._nodesView;
  }

  // Values beyond the entity states (web pages, activity, neighbours).
  async _loadNodeStatus() {
    if (!this._entryId || this._tab !== "nodes" || !this._hass) return;
    const entryId = this._entryId;
    try {
      const status = await this._hass.callWS({ type: "meshcom/chat/node_status", entry_id: entryId });
      if (entryId !== this._entryId) return;
      this._nodeStatus = status;
      this._error = "";
    } catch (err) {
      this._showError(err);
    }
    await this._loadNodeHistory(entryId);
    this._nodeVersion = (this._nodeVersion || 0) + 1;
    this._renderNodes();
  }

  // Battery and channel use of the last 48 hours from the recorder (optional).
  async _loadNodeHistory(entryId) {
    const node = this._nodes.find((n) => n.entry_id === entryId);
    if (!node) return;
    const cached = this._nodeHistory;
    if (cached && cached.entryId === entryId && Date.now() - cached.time < DASH_HISTORY_MS) return;
    const ids = ["battery", "channel_rx", "channel_tx"].map((key) => this._entityOf(node, key)).filter(Boolean);
    const result = { entryId, time: Date.now(), series: {} };
    if (ids.length) {
      try {
        const data = await this._hass.callWS({
          type: "history/history_during_period",
          start_time: new Date(Date.now() - DASH_WINDOW_MS).toISOString(),
          entity_ids: ids,
          minimal_response: true,
          no_attributes: true,
          significant_changes_only: false,
        });
        for (const id of ids) {
          const points = [];
          for (const item of (data && data[id]) || []) {
            const value = item.s === "" ? NaN : Number(item.s);
            const time = item.lu !== undefined ? Number(item.lu) * 1000 : Date.parse(item.last_updated);
            if (Number.isFinite(value) && Number.isFinite(time)) points.push([time, value]);
          }
          result.series[id] = points;
        }
      } catch (err) {
        // The history is optional (recorder off or entity excluded).
      }
    }
    this._nodeHistory = result;
  }

  _entityOf(node, key) {
    const item = node.entities.find((entity) => entity.key === key);
    return item ? item.entity_id : null;
  }

  _stateOf(node, key) {
    const id = this._entityOf(node, key);
    return id ? this._hass.states[id] || null : null;
  }

  _numberOf(node, key) {
    const state = this._stateOf(node, key);
    if (!state || state.state === "" || state.state === null) return null;
    const value = Number(state.state);
    return Number.isFinite(value) ? value : null;
  }

  _fmt(value, digits = 0) {
    return Number(value).toLocaleString(this._hass.language || undefined, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
  }

  _duration(seconds) {
    const d = this._t.dash;
    const total = Math.max(0, Math.floor(seconds));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    if (days) return d.days(days, hours);
    if (hours) return d.hours(hours, minutes);
    if (minutes) return d.mins(minutes);
    return d.secs(total);
  }

  _agoOf(iso) {
    const time = Date.parse(iso);
    if (!Number.isFinite(time)) return "";
    return this._t.ago(Math.max(0, Math.floor((Date.now() - time) / 60000)));
  }

  _renderNodes() {
    if (!this._nodesBody || !this._hass || !this._loaded) return;
    const t = this._t;
    const states = this._hass.states;
    const signature = JSON.stringify([
      this._entryId,
      this._nodeVersion,
      Math.floor(Date.now() / 60000),
      this._nodes.map((node) =>
        node.entities.map((item) => {
          const state = states[item.entity_id];
          return state ? [state.state, state.attributes.latitude, state.attributes.longitude] : null;
        })
      ),
    ]);
    if (signature === this._nodesSignature) return;
    this._nodesSignature = signature;
    if (!this._nodes.length) {
      this._nodeChips.replaceChildren();
      this._nodeDash.replaceChildren(el("div", "empty", t.noNodes));
      return;
    }
    this._renderNodeChips(t);
    const node = this._node || this._nodes[0];
    this._nodeDash.replaceChildren(...this._renderDashboard(node, t));
  }

  // One chip per node: status, callsign, access, battery.
  _renderNodeChips(t) {
    const chips = this._nodes.map((node) => {
      const chip = el("button", node.entry_id === this._entryId ? "nodechip active" : "nodechip");
      const active = this._stateOf(node, "active");
      chip.append(el("span", `dot ${active && active.state === "on" ? "ok" : "off"}`));
      chip.append(el("span", "call", node.callsign));
      chip.append(el("span", "meta", String(node.access || "").toUpperCase()));
      const battery = this._numberOf(node, "battery");
      if (battery !== null) chip.append(el("span", "meta", `${Math.round(battery)} %`));
      chip.addEventListener("click", () => {
        if (node.entry_id === this._entryId) return;
        this._nodeStatus = null;
        this._selectNode(node.entry_id);
      });
      return chip;
    });
    this._nodeChips.replaceChildren(...chips);
    this._nodeChips.hidden = this._nodes.length < 2;
  }

  _renderDashboard(node, t) {
    const status = this._nodeStatus && this._nodeStatus.entry_id === node.entry_id ? this._nodeStatus : null;
    return [
      this._dashHead(node, status, t),
      this._dashTiles(node, status, t),
      ...this._dashCharts(node, status, t),
      this._dashSensors(node, status, t),
      this._dashNeighbours(status, t),
      this._dashControls(node, t),
    ].filter(Boolean);
  }

  _dashHead(node, status, t) {
    const d = t.dash;
    const web = status ? status.web : null;
    const info = web ? web.info : null;
    const card = el("div", "card dashhead");
    const main = el("div", "headmain");
    const icon = el("div", "headicon");
    const svgIcon = svg("svg", { viewBox: "0 0 24 24", width: 26, height: 26 });
    svgIcon.append(svg("path", { d: ICON_TOWER, fill: "currentColor" }));
    icon.append(svgIcon);
    const text = el("div", "headtext");
    text.append(el("h2", null, node.callsign));
    const firmware = this._stateOf(node, "firmware");
    const sub = [
      info && info.hardware,
      firmware && firmware.state !== "unknown" && firmware.state !== "unavailable" ? firmware.state : null,
      t.access[node.access] || node.access,
    ].filter(Boolean);
    text.append(el("div", "sub", sub.join(" \u00b7 ")));
    if (info && info.frequency_mhz) {
      const radio = [`${this._fmt(info.frequency_mhz, 3)} MHz`];
      if (info.bandwidth_khz) radio.push(`BW ${info.bandwidth_khz} kHz`);
      if (info.spreading_factor) radio.push(`SF ${info.spreading_factor}`);
      if (info.coding_rate) radio.push(`CR 4/${info.coding_rate}`);
      if (Number.isInteger(info.tx_power_dbm)) radio.push(`${info.tx_power_dbm} dBm`);
      text.append(el("div", "sub", radio.join(" \u00b7 ")));
    }
    main.append(icon, text);
    const pills = el("div", "pills");
    const active = this._stateOf(node, "active");
    const isActive = active && active.state === "on";
    const lastPacket = this._stateOf(node, "last_packet");
    const heard = lastPacket ? this._agoOf(lastPacket.state) : "";
    pills.append(this._pill(isActive ? "ok" : "off", heard ? `${isActive ? d.active : d.inactive} \u00b7 ${heard}` : isActive ? d.active : d.inactive));
    if (web && web.started) {
      pills.append(this._pill("info", `${d.uptime} ${d.since(this._duration((Date.now() - Date.parse(web.started)) / 1000))}`));
    }
    if (info && info.server && d.server[info.server]) {
      pills.append(this._pill(info.server === "connected" ? "ok" : info.server === "off" ? "off" : "warn", d.server[info.server]));
    }
    if (status && status.kiss_connected !== null && status.kiss_connected !== undefined) {
      pills.append(this._pill(status.kiss_connected ? "ok" : "bad", d.kiss[String(status.kiss_connected)]));
    }
    if (web) {
      if (web.ok) pills.append(this._pill("ok", d.web.ok));
      else pills.append(this._pill(web.paused ? "off" : "warn", web.paused ? d.web.paused : d.web.down));
    }
    card.append(main, pills);
    return card;
  }

  _pill(level, text) {
    const pill = el("span", `pill ${level}`);
    pill.append(el("span", `dot ${level}`), el("span", null, text));
    return pill;
  }

  // Bar of coloured segments; values relative to ``total``.
  _bar(segments, total) {
    const bar = el("div", "bar");
    const sum = total || segments.reduce((acc, seg) => acc + seg.value, 0);
    if (sum <= 0) return bar;
    for (const seg of segments) {
      if (!(seg.value > 0)) continue;
      const part = el("span");
      part.style.width = `${Math.min(100, (seg.value / sum) * 100)}%`;
      part.style.background = seg.color;
      if (seg.title) part.title = seg.title;
      bar.append(part);
    }
    return bar;
  }

  _tile(label, level, big, unit, sub, extra) {
    const tile = el("div", "tile");
    const head = el("div", "tilehead");
    head.append(el("span", null, label), el("span", `dot ${level}`));
    const value = el("div", "big", big);
    if (unit) value.append(el("span", "unit", unit));
    tile.append(head, value);
    if (sub) tile.append(el("div", "tilesub", sub));
    for (const item of extra || []) if (item) tile.append(item);
    return tile;
  }

  _legend(items) {
    const legend = el("div", "minilegend");
    for (const item of items) {
      const entry = el("span");
      const swatch = el("i");
      swatch.style.background = item.color;
      entry.append(swatch, el("span", null, item.text));
      legend.append(entry);
    }
    return legend;
  }

  _dashTiles(node, status, t) {
    const d = t.dash;
    const tiles = el("div", "tiles");
    const web = status ? status.web : null;
    const radio = web ? web.radio : null;
    // Battery, with the course of the last 48 hours.
    const battery = this._numberOf(node, "battery");
    if (battery !== null) {
      const voltage = this._numberOf(node, "battery_voltage");
      const level = battery >= 50 ? "ok" : battery >= 20 ? "warn" : "bad";
      const colour = LEVEL_COLORS[level];
      const id = this._entityOf(node, "battery");
      const points = this._nodeHistory && this._nodeHistory.entryId === node.entry_id ? this._nodeHistory.series[id] : null;
      tiles.append(
        this._tile(d.battery, level, this._fmt(battery), "%", voltage !== null ? `${this._fmt(voltage, 2)} V` : "", [
          this._bar([{ value: battery, color: colour }], 100),
          points && points.length > 1 ? this._sparkline(points, 0, 100, colour) : null,
        ])
      );
    }
    // Signal of the last received message.
    const rssi = this._numberOf(node, "last_rssi");
    if (rssi !== null) {
      const snr = this._numberOf(node, "last_snr");
      const level = rssi >= -100 ? "ok" : rssi >= -115 ? "warn" : "bad";
      tiles.append(
        this._tile(d.signal, level, String(Math.round(rssi)), "dBm", snr !== null ? `SNR ${this._fmt(snr, 1)} dB` : "", [
          this._bar([{ value: Math.min(90, Math.max(0, rssi + 130)), color: LEVEL_COLORS[level] }], 90),
        ])
      );
    }
    // Channel use and queue (LoRa queue panel, only with the option).
    if (radio) {
      if (radio.rx_percent !== null && radio.tx_percent !== null) {
        const used = radio.rx_percent + radio.tx_percent;
        const level = used < 30 ? "ok" : used < 60 ? "warn" : "bad";
        tiles.append(
          this._tile(d.channel, level, this._fmt(used, 1), "%", `RX ${this._fmt(radio.rx_percent, 1)} % \u00b7 TX ${this._fmt(radio.tx_percent, 1)} %`, [
            this._bar(
              [
                { value: radio.rx_percent, color: SERIES_COLORS.rx, title: "RX" },
                { value: radio.tx_percent, color: SERIES_COLORS.tx, title: "TX" },
                { value: Math.max(0, 100 - used), color: "var(--divider-color)" },
              ],
              100
            ),
          ])
        );
      }
      const level =
        radio.refuse_at && radio.queue_used >= radio.refuse_at ? "bad" : radio.slow_down_at && radio.queue_used >= radio.slow_down_at ? "warn" : "ok";
      tiles.append(
        this._tile(d.queue, level, String(radio.queue_used), `/ ${radio.queue_size}`, d.queueState[radio.state] || "", [
          this._queueBar(radio),
          this._legend(
            PRIORITIES.filter((name) => radio.queue_by_priority[name]).map((name) => ({ color: PRIORITY_COLORS[name], text: `${name} ${radio.queue_by_priority[name]}` }))
          ),
        ])
      );
    } else if (web && !web.radio_enabled) {
      const hint = el("div", "tile hint");
      hint.append(el("div", "tilehead", d.channel), el("div", "tilesub", d.channelOff));
      tiles.append(hint);
    }
    if (status) {
      // Messages of the last 48 hours by kind, own ones by delivery state.
      const activity = status.activity;
      const sums = {};
      for (const kind of ACTIVITY_KINDS) sums[kind] = (activity[kind] || []).reduce((a, b) => a + b, 0);
      const received = sums.received_direct + sums.received_group + sums.received_all;
      tiles.append(
        this._tile(d.received, "info", this._fmt(received), "", ACTIVITY_KINDS.filter((k) => k !== "sent").map((k) => `${d.kinds[k]} ${sums[k]}`).join(" \u00b7 "), [
          this._bar(ACTIVITY_KINDS.filter((k) => k !== "sent").map((k) => ({ value: sums[k], color: KIND_COLORS[k], title: d.kinds[k] }))),
        ])
      );
      const delivery = status.delivery;
      tiles.append(
        this._tile(d.sent, delivery.failed ? "warn" : "ok", this._fmt(sums.sent), "", DELIVERY_STATES.filter((k) => delivery[k]).map((k) => `${d.delivery[k]} ${delivery[k]}`).join(" \u00b7 "), [
          this._bar(DELIVERY_STATES.map((k) => ({ value: delivery[k], color: DELIVERY_COLORS[k], title: d.delivery[k] }))),
        ])
      );
      const stations = status.stations;
      tiles.append(
        this._tile(d.stations, "info", String(stations.heard_24h), "", d.directCount(stations.direct), [
          this._bar(
            [
              { value: stations.direct, color: DIRECT_COLOR },
              { value: Math.max(0, stations.heard_24h - stations.direct), color: SERIES_COLORS.received },
            ],
            Math.max(stations.heard_24h, stations.direct)
          ),
        ])
      );
    }
    return tiles;
  }

  // Queue like the node's own panel: one cell per slot, coloured by priority,
  // marks where the node asks to slow down (QRS) and refuses (QRT).
  _queueBar(radio) {
    const wrap = el("div", "qwrap");
    const cells = el("div", "qbar");
    let filled = 0;
    for (const name of PRIORITIES) {
      for (let i = 0; i < (radio.queue_by_priority[name] || 0) && filled < radio.queue_size; i += 1) {
        const cell = el("span");
        cell.style.background = PRIORITY_COLORS[name];
        cells.append(cell);
        filled += 1;
      }
    }
    for (; filled < radio.queue_size; filled += 1) cells.append(el("span", "free"));
    wrap.append(cells);
    for (const [mark, label] of [[radio.slow_down_at, "QRS"], [radio.refuse_at, "QRT"]]) {
      if (!mark) continue;
      const tick = el("span", "qtick", label);
      tick.style.left = `${(mark / radio.queue_size) * 100}%`;
      wrap.append(tick);
    }
    return wrap;
  }

  _sparkline(points, low, high, colour) {
    const start = Date.now() - DASH_WINDOW_MS;
    const box = svg("svg", { viewBox: "0 0 100 24", preserveAspectRatio: "none", class: "spark" });
    const coords = points
      .filter(([time]) => time >= start)
      .map(([time, value]) => [((time - start) / DASH_WINDOW_MS) * 100, 22 - ((Math.min(high, Math.max(low, value)) - low) / (high - low)) * 20]);
    if (coords.length) coords.push([100, coords[coords.length - 1][1]]);
    box.append(svg("polyline", { points: coords.map((p) => p.join(",")).join(" "), fill: "none", stroke: colour, "stroke-width": 1.5, "vector-effect": "non-scaling-stroke" }));
    return box;
  }

  // Line chart over the last 48 hours: series of [x 0..1, y].
  _lineChart(title, series, yMax, unit, t, width) {
    const d = t.dash;
    const card = el("div", "card chart");
    card.append(el("h3", null, title));
    const height = 170;
    const left = 34;
    const bottom = 20;
    const plotW = width - left - 8;
    const plotH = height - bottom - 10;
    const box = svg("svg", { viewBox: `0 0 ${width} ${height}`, class: "chartsvg", role: "img", "aria-label": title });
    const top = yMax > 0 ? yMax : 1;
    for (const [fraction, label] of [[0, "0"], [0.5, this._fmt(top / 2, top < 10 ? 1 : 0)], [1, this._fmt(top, top < 10 ? 1 : 0)]]) {
      const y = 10 + plotH - fraction * plotH;
      box.append(svg("line", { x1: left, x2: width - 8, y1: y, y2: y, class: fraction ? "grid" : "axis" }));
      const text = svg("text", { x: left - 4, y: y + 4, "text-anchor": "end", class: "lbl" });
      text.textContent = unit ? `${label}${unit}` : label;
      box.append(text);
    }
    for (const [fraction, label] of [[0, "-48 h"], [0.5, "-24 h"], [1, d.now]]) {
      const text = svg("text", { x: left + fraction * plotW, y: height - 4, "text-anchor": fraction === 0 ? "start" : fraction === 1 ? "end" : "middle", class: "lbl" });
      text.textContent = label;
      box.append(text);
    }
    let drawn = false;
    for (const line of series) {
      if (line.points.length < 2) continue;
      drawn = true;
      const coords = line.points.map(([x, y]) => `${(left + x * plotW).toFixed(1)},${(10 + plotH - (Math.min(y, top) / top) * plotH).toFixed(1)}`);
      box.append(svg("polyline", { points: coords.join(" "), fill: "none", stroke: line.color, "stroke-width": 2, "stroke-linejoin": "round" }));
    }
    card.append(box);
    if (!drawn) card.append(el("div", "tilesub", d.noHistory));
    card.append(this._legend(series.map((line) => ({ color: line.color, text: line.name }))));
    return card;
  }

  _dashCharts(node, status, t) {
    const d = t.dash;
    const charts = [];
    // Drawn at about the size it is shown, so the labels stay readable:
    // two charts side by side from 700 px, else one per row.
    const available = (this._nodesBody && this._nodesBody.clientWidth) || 600;
    const history = this._nodeHistory && this._nodeHistory.entryId === node.entry_id ? this._nodeHistory.series : null;
    const rxId = this._entityOf(node, "channel_rx");
    const txId = this._entityOf(node, "channel_tx");
    const count = (status ? 1 : 0) + (history && rxId && txId ? 1 : 0);
    const perRow = count > 1 && available >= 700 ? 2 : 1;
    const width = Math.round(Math.max(300, Math.min(1200, (available - 32) / perRow - 32)));
    if (status) {
      const activity = status.activity;
      const count = activity.hours.length;
      const x = (i) => (count > 1 ? i / (count - 1) : 0);
      const received = activity.hours.map((_, i) => [x(i), activity.received_direct[i] + activity.received_group[i] + activity.received_all[i]]);
      const sent = activity.sent.map((value, i) => [x(i), value]);
      const yMax = Math.max(1, ...received.map((p) => p[1]), ...sent.map((p) => p[1]));
      charts.push(
        this._lineChart(d.activity, [
          { name: d.receivedLine, color: SERIES_COLORS.received, points: received },
          { name: d.sentLine, color: SERIES_COLORS.sent, points: sent },
        ], niceMax(yMax), "", t, width)
      );
    }
    if (history && rxId && txId) {
      const start = Date.now() - DASH_WINDOW_MS;
      const toLine = (points) => {
        const line = (points || []).filter(([time]) => time >= start).map(([time, value]) => [(time - start) / DASH_WINDOW_MS, value]);
        if (line.length) line.push([1, line[line.length - 1][1]]);
        return line;
      };
      const rx = toLine(history[rxId]);
      const tx = toLine(history[txId]);
      const yMax = Math.max(5, ...rx.map((p) => p[1]), ...tx.map((p) => p[1]));
      charts.push(
        this._lineChart(d.utilisation, [
          { name: d.rxLine, color: SERIES_COLORS.rx, points: rx },
          { name: d.txLine, color: SERIES_COLORS.tx, points: tx },
        ], niceMax(yMax), " %", t, width)
      );
    }
    if (!charts.length) return [];
    const row = el("div", "charts");
    row.append(...charts);
    return [row];
  }

  // Sensor rows in groups; numeric ones with a small bar (fraction 0..1).
  _dashSensors(node, status, t) {
    const d = t.dash;
    const rows = d.rows;
    const web = status ? status.web : null;
    const info = web ? web.info : null;
    const gps = web ? web.gps : null;
    const radio = web ? web.radio : null;
    const groups = [];
    if (radio) {
      const list = [];
      if (radio.rx_percent !== null) list.push([rows.rx, `${this._fmt(radio.rx_percent, 1)} %`, radio.rx_percent / 100, SERIES_COLORS.rx]);
      if (radio.tx_percent !== null) list.push([rows.tx, `${this._fmt(radio.tx_percent, 1)} %`, radio.tx_percent / 100, SERIES_COLORS.tx]);
      list.push([rows.queue, `${radio.queue_used} / ${radio.queue_size}`, radio.queue_used / radio.queue_size]);
      if (radio.dropped !== null) list.push([rows.dropped, String(radio.dropped)]);
      if (radio.duplicates !== null) list.push([rows.duplicates, d.dupOf(radio.duplicates, radio.new_ids)]);
      if (radio.dedup_window_minutes) list.push([rows.dedup, d.minutes(radio.dedup_window_minutes)]);
      groups.push([d.groups.radio, list]);
    }
    const statusRows = [];
    const battery = this._numberOf(node, "battery");
    if (battery !== null) statusRows.push([rows.battery, `${this._fmt(battery)} %`, battery / 100]);
    const voltage = this._numberOf(node, "battery_voltage");
    if (voltage !== null) statusRows.push([rows.voltage, `${this._fmt(voltage, 2)} V`]);
    if (web && web.started) statusRows.push([rows.uptime, this._duration((Date.now() - Date.parse(web.started)) / 1000)]);
    const lastPacket = this._stateOf(node, "last_packet");
    if (lastPacket && this._agoOf(lastPacket.state)) statusRows.push([rows.lastPacket, this._agoOf(lastPacket.state)]);
    if (info && Number.isInteger(info.wifi_rssi)) statusRows.push([rows.wifi, `${info.wifi_rssi} dBm`, Math.min(1, Math.max(0, (info.wifi_rssi + 90) / 60))]);
    if (info && info.server && d.server[info.server]) {
      const age = Number.isInteger(info.server_age_seconds) ? ` (${d.lastAnswer(this._duration(info.server_age_seconds))})` : "";
      statusRows.push([rows.server, `${d.server[info.server]}${age}`]);
    }
    if (info && Number.isInteger(info.max_hop_text) && Number.isInteger(info.max_hop_pos)) statusRows.push([rows.hops, `${info.max_hop_text} / ${info.max_hop_pos}`]);
    if (info && Number.isInteger(info.blocked_dropped)) statusRows.push([rows.blocked, String(info.blocked_dropped)]);
    if (status) {
      statusRows.push([rows.duplicatesTotal, String(status.counters.duplicates)]);
      statusRows.push([rows.filtered, String(status.counters.filtered)]);
    }
    if (statusRows.length) groups.push([d.groups.status, statusRows]);
    const altitude = this._stateOf(node, "altitude");
    const gpsRows = [];
    if (altitude && altitude.state !== "unknown" && altitude.state !== "unavailable") {
      gpsRows.push([this._entityLabel(altitude, node), this._formatState(altitude)]);
    }
    if (gps && gps.enabled !== false) {
      const list = gpsRows;
      if (Number.isInteger(gps.satellites)) list.push([rows.satellites, `${gps.satellites} (${gps.fix ? d.fix : d.noFix})`, Math.min(1, gps.satellites / 12)]);
      if (Number.isInteger(gps.next_beacon)) list.push([rows.nextBeacon, d.inMinutes(Math.round(gps.next_beacon / 60))]);
      if (Number.isInteger(gps.beacon_interval)) list.push([rows.interval, d.everyMinutes(Math.round(gps.beacon_interval / 60))]);
    }
    if (gpsRows.length) groups.push([d.groups.gps, gpsRows]);
    const environment = [];
    for (const key of ENVIRONMENT_KEYS) {
      const state = this._stateOf(node, key);
      if (!state || state.state === "unknown" || state.state === "unavailable") continue;
      environment.push([this._entityLabel(state, node), this._formatState(state)]);
    }
    if (environment.length) groups.push([d.groups.environment, environment]);
    if (!groups.length) return null;
    const card = el("div", "card sensors");
    const grid = el("div", "sensorgrid");
    for (const [title, list] of groups) {
      const group = el("div", "sgroup");
      group.append(el("h3", null, title));
      for (const [label, value, fraction, colour] of list) {
        const row = el("div", "srow");
        row.append(el("span", "label", label), el("span", "value", value));
        if (typeof fraction === "number" && Number.isFinite(fraction)) {
          row.append(this._bar([{ value: Math.min(1, Math.max(0, fraction)), color: colour || SERIES_COLORS.received }], 1));
        }
        group.append(row);
      }
      grid.append(group);
    }
    card.append(grid);
    return card;
  }

  _dashNeighbours(status, t) {
    if (!status) return null;
    const d = t.dash;
    const card = el("div", "card");
    card.append(el("h3", null, `${d.neighbours} (${status.neighbours.length})`));
    if (!status.neighbours.length) {
      card.append(el("div", "tilesub", d.noNeighbours));
      return card;
    }
    const wrap = el("div", "tablewrap");
    const table = el("table", "neighbours");
    const head = el("tr");
    for (const key of ["callsign", "snr", "hearsMe", "role", "hardware", "heard"]) head.append(el("th", key === "snr" ? "num" : null, d.columns[key]));
    table.append(head);
    for (const station of status.neighbours) {
      const row = el("tr");
      const call = el("td");
      const button = el("button", "linkbutton", station.callsign);
      button.addEventListener("click", () => {
        this._setTab("stations");
        this._pendingFocus = station.callsign;
      });
      call.append(button);
      const snrTd = el("td", "num");
      if (typeof station.snr === "number") {
        snrTd.append(el("span", null, `${this._fmt(station.snr, 1)} dB`));
        snrTd.append(this._bar([{ value: Math.min(32, Math.max(0, station.snr + 20)), color: station.snr >= 0 ? LEVEL_COLORS.ok : station.snr >= -10 ? LEVEL_COLORS.warn : LEVEL_COLORS.bad }], 32));
      }
      row.append(
        call,
        snrTd,
        el("td", null, t.hearsMe(station.hears_me_snr)),
        el("td", null, t.roles[station.relay_role] || ""),
        el("td", null, station.hardware || ""),
        el("td", null, station.direct_heard ? this._agoOf(station.direct_heard) : "")
      );
      table.append(row);
    }
    wrap.append(table);
    card.append(wrap);
    return card;
  }

  // Switches, then every entity of the node (as the tab showed before).
  _dashControls(node, t) {
    const d = t.dash;
    const card = el("div", "card");
    card.append(el("h3", null, d.controls));
    for (const item of node.entities) {
      if (item.domain !== "switch") continue;
      const state = this._hass.states[item.entity_id];
      if (!state) continue;
      const row = el("div", "row");
      row.append(el("span", "label", this._entityLabel(state, node)), this._entityValue(item, state, t));
      card.append(row);
    }
    const details = el("details", "allentities");
    details.append(el("summary", null, d.entities));
    for (const item of node.entities) {
      const state = this._hass.states[item.entity_id];
      if (!state) continue;
      const row = el("div", "row");
      row.append(el("span", "label", this._entityLabel(state, node)), this._entityValue(item, state, t));
      details.append(row);
    }
    details.open = Boolean(this._entitiesOpen);
    details.addEventListener("toggle", () => {
      this._entitiesOpen = details.open;
    });
    card.append(details);
    return card;
  }

  _entityLabel(state, node) {
    const name = String(state.attributes.friendly_name || state.entity_id);
    // "MeshCom QX1YZ-12 Akku" -> "Akku"
    const index = name.indexOf(node.callsign);
    const rest = index >= 0 ? name.slice(index + node.callsign.length).trim() : name;
    return rest || name;
  }

  _formatState(state) {
    if (typeof this._hass.formatEntityState === "function") {
      try {
        return this._hass.formatEntityState(state);
      } catch (err) {
        // fall back below
      }
    }
    const unit = state.attributes.unit_of_measurement;
    return unit ? `${state.state} ${unit}` : state.state;
  }

  _entityValue(item, state, t) {
    if (item.domain === "switch") {
      const on = state.state === "on";
      const button = el("button", on ? "toggle on" : "toggle", on ? t.on : t.off);
      button.disabled = state.state === "unavailable";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await this._hass.callService("switch", "toggle", { entity_id: item.entity_id });
          this._error = "";
        } catch (err) {
          this._showError(err);
        }
        button.disabled = false;
      });
      return button;
    }
    if (item.domain === "device_tracker") {
      const lat = Number(state.attributes.latitude);
      const lon = Number(state.attributes.longitude);
      if (!Number.isFinite(lat) || !Number.isFinite(lon)) return el("span", "value", this._formatState(state));
      const button = el("button", "linkbutton", `${lat.toFixed(4)}, ${lon.toFixed(4)}`);
      button.addEventListener("click", () => openMap(lat, lon));
      return button;
    }
    return el("span", "value", this._formatState(state));
  }

  // --- stations ------------------------------------------------------------------

  async _loadStations() {
    if (!this._entryId || this._tab !== "stations") return;
    try {
      const result = await this._hass.callWS({ type: "meshcom/chat/stations", entry_id: this._entryId });
      this._stations = result.stations;
      this._stationsMode = result.mode;
    } catch (err) {
      this._showError(err);
    }
    this._renderStations();
    if (this._pendingFocus) {
      // Opened from a neighbour on the nodes tab.
      const callsign = this._pendingFocus;
      this._pendingFocus = null;
      this._focusStation(callsign);
    }
  }

  _renderStations() {
    if (!this._stationsBody) return;
    const t = this._t;
    this._mapBox.hidden = this._stationsMode === "off";
    if (this._stationsMode !== "off" && this._stations !== null) this._renderMap();
    if (this._stationsMode === "off") {
      this._stationsBody.replaceChildren(el("div", "empty", t.stationsOff));
      return;
    }
    if (this._stations === null) return;
    const rows = this._visibleStations().filter(
      (s) => !this._stationFilter || s.callsign.includes(this._stationFilter)
    );
    if (!rows.length) {
      this._stationsBody.replaceChildren(el("div", "empty", this._directOnly ? t.noDirect : t.noStations));
      return;
    }
    const { key, desc } = this._stationSort;
    rows.sort((a, b) => {
      const x = a[key];
      const y = b[key];
      if (x === y) return 0;
      if (x === null || x === undefined) return 1;
      if (y === null || y === undefined) return -1;
      const order = x < y ? -1 : 1;
      return desc ? -order : order;
    });
    const table = el("table");
    const head = el("tr");
    const numeric = new Set(["rssi", "snr", "hops", "battery", "temperature", "humidity", "pressure", "hears_me_snr"]);
    const columns = [
      "callsign", "last_heard", "rssi", "snr", "hops", "battery", "temperature", "humidity", "pressure",
      "hears_me_snr", "relay_role", "hardware", "position",
    ];
    for (const column of columns) {
      const marker = column === key ? (desc ? " \u25bc" : " \u25b2") : "";
      const th = el("th", numeric.has(column) ? "num" : null, `${t.columns[column]}${marker}`);
      if (column !== "position") {
        th.addEventListener("click", () => {
          this._stationSort = { key: column, desc: column === key ? !desc : column !== "callsign" };
          this._renderStations();
        });
      }
      head.append(th);
    }
    table.append(head);
    const now = Date.now();
    for (const station of rows) {
      const tr = el("tr");
      const callTd = el("td");
      if (station.direct === true) {
        const dot = el("span", "direct-dot");
        dot.title = t.legend.direct;
        callTd.append(dot);
      }
      const located = Number.isFinite(station.latitude) && Number.isFinite(station.longitude);
      if (located) {
        // Callsign: show it on the map above; "(DM)": open the direct message.
        const call = el("button", "linkbutton", station.callsign);
        call.title = t.showOnMap;
        call.addEventListener("click", () => this._focusStation(station.callsign));
        callTd.append(call);
      } else {
        callTd.append(el("span", null, station.callsign));
      }
      const dm = el("button", "linkbutton dm", `(${t.dm})`);
      dm.title = t.message;
      dm.addEventListener("click", () => this._openDirect(station.callsign));
      callTd.append(" ", dm);
      const heard = new Date(station.last_heard).getTime();
      const minutes = Number.isNaN(heard) ? null : Math.max(0, Math.floor((now - heard) / 60000));
      const heardTd = el("td", null, minutes === null ? "" : t.ago(minutes));
      if (!Number.isNaN(heard)) heardTd.title = new Date(heard).toLocaleString(this._hass.language || undefined);
      tr.append(
        callTd,
        heardTd,
        el("td", "num", station.rssi ?? ""),
        el("td", "num", station.snr ?? ""),
        el("td", "num", station.hops ?? ""),
        el("td", "num", station.battery === null || station.battery === undefined ? "" : `${station.battery} %`),
        el("td", "num", Number.isFinite(station.temperature) ? `${station.temperature.toFixed(1)} \u00b0C` : ""),
        el("td", "num", Number.isFinite(station.humidity) ? `${Math.round(station.humidity)} %` : ""),
        el("td", "num", Number.isFinite(station.pressure) ? `${Math.round(station.pressure)} hPa` : ""),
        el("td", "num", station.direct === true ? t.hearsMe(station.hears_me_snr) : ""),
        el("td", null, t.roles[station.relay_role] || ""),
        el("td", null, station.hardware || "")
      );
      const posTd = el("td");
      if (Number.isFinite(station.latitude) && Number.isFinite(station.longitude)) {
        const map = el("button", "linkbutton", t.map);
        map.addEventListener("click", () => this._focusStation(station.callsign));
        posTd.append(map);
      }
      tr.append(posTd);
      table.append(tr);
    }
    this._stationsBody.replaceChildren(table);
  }

  // The stations shown in table and map ("direct neighbours only" applied).
  _visibleStations() {
    const stations = this._stations || [];
    return this._directOnly ? stations.filter((s) => s.direct === true) : stations;
  }

  _weatherText(station) {
    const values = [];
    if (Number.isFinite(station.temperature)) values.push(`${station.temperature.toFixed(1)} \u00b0C`);
    if (Number.isFinite(station.humidity)) values.push(`${Math.round(station.humidity)} %`);
    if (Number.isFinite(station.pressure)) values.push(`${Math.round(station.pressure)} hPa`);
    return values.join(" \u00b7 ");
  }

  _focusStation(callsign) {
    if (!this._map) return;
    this._map.focus(callsign);
    this._mapBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  _ownPositions() {
    const node = this._node;
    if (!node || !this._hass) return [];
    for (const item of node.entities) {
      if (item.domain !== "device_tracker") continue;
      const state = this._hass.states[item.entity_id];
      if (!state) continue;
      return [{
        id: OWN_MARKER,
        lat: Number(state.attributes.latitude),
        lon: Number(state.attributes.longitude),
        label: node.callsign,
        kind: "own",
      }];
    }
    return [];
  }

  _renderMap() {
    if (!this._map) this._map = new TileMap(
        this._mapBox,
        (id) => this._mapPopup(id),
        this._t.legend,
        (id) => this._stationRoute(id)
      );
    const dark = Boolean(this._hass && this._hass.themes && this._hass.themes.darkMode);
    this._mapBox.classList.toggle("dark", dark);
    const now = Date.now();
    const markers = this._visibleStations().map((station) => {
      const heard = new Date(station.last_heard).getTime();
      const minutes = Number.isNaN(heard) ? Infinity : (now - heard) / 60000;
      return {
        id: station.callsign,
        lat: Number(station.latitude),
        lon: Number(station.longitude),
        label: station.callsign,
        kind: station.direct === true ? "direct" : minutes < 60 ? "fresh" : minutes < 1440 ? "recent" : "old",
      };
    });
    this._map.setMarkers([...this._ownPositions(), ...markers]);
    if (this._pendingRoute) {
      const route = this._pendingRoute;
      this._pendingRoute = null;
      this._map.showRoute(this._routePoints(route));
      this._mapBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }

  // Positions along a path: originator, relays, then the own node.
  _routePoints(callsigns) {
    const own = this._ownPositions()[0] || null;
    const node = this._node;
    const position = (call) => {
      if (node && call === node.callsign) return own;
      const station = (this._stations || []).find((s) => s.callsign === call);
      return station && Number.isFinite(station.latitude) && Number.isFinite(station.longitude)
        ? { lat: station.latitude, lon: station.longitude }
        : null;
    };
    const points = callsigns.map(position);
    if (!node || callsigns[callsigns.length - 1] !== node.callsign) points.push(own);
    return points;
  }

  _stationRoute(id) {
    if (id === OWN_MARKER) return [];
    const station = (this._stations || []).find((s) => s.callsign === id);
    if (!station) return [];
    return this._routePoints([station.callsign, ...(Array.isArray(station.path) ? station.path : [])]);
  }

  // From the chat: show the path of a message on the map.
  _showRoute(path) {
    this._pendingRoute = path;
    this._setTab("stations");
  }

  // Values from the node's MHeard list: neighbour values only while direct.
  _neighbourLines(station) {
    const t = this._t;
    const lines = [];
    if (station.direct === true) {
      const head = el("div", "direct", t.legend.direct);
      head.append(el("span", "hears", ` \u00b7 ${t.columns.hears_me_snr}: ${t.hearsMe(station.hears_me_snr)}`));
      lines.push(head);
      const relay = [];
      if (t.roles[station.relay_role]) relay.push(`${t.columns.relay_role}: ${t.roles[station.relay_role]}`);
      if (Number.isInteger(station.it_hears) && Number.isInteger(station.only_it_hears)) {
        relay.push(t.itHears(station.it_hears, station.only_it_hears));
      }
      if (Number.isInteger(station.neighbours)) relay.push(t.reports(station.neighbours));
      if (relay.length) lines.push(el("div", null, relay.join(" \u00b7 ")));
    }
    const device = [];
    if (station.hardware) device.push(station.hardware);
    if (Number.isInteger(station.altitude)) device.push(`${t.altitude} ${station.altitude} m`);
    if (station.direct === true && station.gateway === true) device.push(t.gateway);
    if (device.length) lines.push(el("div", null, device.join(" \u00b7 ")));
    return lines;
  }

  // Distance from the own node, only if both positions are known.
  _distanceText(station) {
    const own = this._ownPositions()[0];
    const target = { lat: Number(station.latitude), lon: Number(station.longitude) };
    if (!own || !validPosition(own.lat, own.lon) || !validPosition(target.lat, target.lon)) return "";
    const hass = this._hass;
    const imperial = Boolean(hass && hass.config && hass.config.unit_system && hass.config.unit_system.length === "mi");
    return formatDistance(distanceKm(own, target), imperial, hass && hass.language);
  }

  _mapPopup(id) {
    const t = this._t;
    const node = this._node;
    if (id === OWN_MARKER) {
      return [el("div", "title", node ? node.callsign : ""), el("div", null, t.ownNode)];
    }
    const station = (this._stations || []).find((s) => s.callsign === id);
    if (!station) return [];
    const parts = [el("div", "title", station.callsign)];
    const heard = new Date(station.last_heard).getTime();
    if (!Number.isNaN(heard)) {
      parts.push(el("div", null, t.ago(Math.max(0, Math.floor((Date.now() - heard) / 60000)))));
    }
    const values = [];
    if (station.rssi !== null && station.rssi !== undefined) values.push(`${station.rssi} dBm / ${station.snr} dB`);
    if (station.hops !== null && station.hops !== undefined) values.push(`${t.columns.hops} ${station.hops}`);
    if (station.battery !== null && station.battery !== undefined) values.push(`${t.columns.battery} ${station.battery} %`);
    if (values.length) parts.push(el("div", null, values.join(" \u00b7 ")));
    const weather = this._weatherText(station);
    if (weather) parts.push(el("div", null, weather));
    const distance = this._distanceText(station);
    if (distance) parts.push(el("div", null, `${t.distance} ${distance}`));
    parts.push(...this._neighbourLines(station));
    const path = Array.isArray(station.path) ? station.path : [];
    parts.push(el("div", "path", path.length ? `${t.via} ${path.join(" > ")}` : t.direct));
    const buttons = el("div", "buttons");
    const dm = el("button", "toggle", t.message);
    dm.addEventListener("click", () => this._openDirect(station.callsign));
    const osm = el("button", "toggle", t.osm);
    osm.addEventListener("click", () => openMap(station.latitude, station.longitude));
    buttons.append(dm, osm);
    parts.push(buttons);
    return parts;
  }
}

if (!customElements.get("meshcom-chat-panel")) {
  customElements.define("meshcom-chat-panel", MeshComChatPanel);
}
