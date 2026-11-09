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
    map: "Map",
    stationsOff: "Stations are switched off in the options of this node.",
    mapHintData: "For a real map in Home Assistant: with the station mode \"One device per station\" (node options) the stations appear on the normal Home Assistant map, without any third-party server.",
    mapHintEntities: "The stations also appear on the normal Home Assistant map.",
    noStations: "No stations heard yet.",
    search: "Search callsign",
    refresh: "Refresh",
    columns: {
      callsign: "Callsign",
      last_heard: "Last heard",
      rssi: "RSSI",
      snr: "SNR",
      hops: "Hops",
      battery: "Battery",
      position: "Position",
    },
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
    map: "Karte",
    stationsOff: "Stationen sind in den Optionen dieses Nodes ausgeschaltet.",
    mapHintData: "F\u00fcr eine echte Karte in Home Assistant: Mit dem Stationsmodus \u201eEin Ger\u00e4t pro Station\u201c (Optionen des Nodes) erscheinen die Stationen auf der normalen Home-Assistant-Karte, ohne fremden Server.",
    mapHintEntities: "Die Stationen erscheinen auch auf der normalen Home-Assistant-Karte.",
    noStations: "Noch keine Stationen geh\u00f6rt.",
    search: "Rufzeichen suchen",
    refresh: "Aktualisieren",
    columns: {
      callsign: "Rufzeichen",
      last_heard: "Zuletzt geh\u00f6rt",
      rssi: "RSSI",
      snr: "SNR",
      hops: "Hops",
      battery: "Akku",
      position: "Position",
    },
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
.row .value { text-align: right; }
.toggle { font: inherit; border-radius: 14px; padding: 2px 12px; border: 1px solid var(--divider-color);
  background: none; color: inherit; }
.toggle.on { background: var(--primary-color, #03a9f4); color: var(--text-primary-color, #fff); border-color: var(--primary-color, #03a9f4); }
.hint { font-size: 13px; opacity: .8; margin-bottom: 12px; padding: 8px 12px; border-radius: 8px;
  border-left: 3px solid var(--primary-color, #03a9f4); background: var(--secondary-background-color); }
.stationbar { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; }
.stationbar input { flex: 1; max-width: 260px; font: inherit; padding: 6px; }
table { width: 100%; border-collapse: collapse; background: var(--card-background-color); font-size: 14px; }
th, td { padding: 6px 10px; border-bottom: 1px solid var(--divider-color); text-align: left; white-space: nowrap; }
th { cursor: pointer; user-select: none; font-weight: 500; }
td.num, th.num { text-align: right; }
.linkbutton { background: none; border: none; color: var(--primary-color, #03a9f4); font: inherit; padding: 0; cursor: pointer; }
button { font: inherit; cursor: pointer; }
@media (max-width: 700px) {
  .view.chat { flex-direction: column; }
  .sidebar { width: auto; max-height: 40%; border-right: none; border-bottom: 1px solid var(--divider-color); }
  .msg { max-width: 90%; }
  .toolbar .title { display: none; }
}
`;

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
      await this._selectNode(this._nodes[0].entry_id);
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
    for (const key of ["chat", "nodes", "stations"]) {
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

  _buildNodes() {
    this._nodesView = el("div", "view");
    this._nodesBody = el("div", "scroll");
    this._nodesView.append(this._nodesBody);
    return this._nodesView;
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
    const refresh = el("button", "toggle", t.refresh);
    refresh.addEventListener("click", () => this._loadStations());
    bar.append(this._stationSearch, refresh);
    this._mapHint = el("div", "hint");
    this._mapHint.hidden = true;
    this._stationsBody = el("div");
    body.append(this._mapHint, bar, this._stationsBody);
    this._stationsView.append(body);
    return this._stationsView;
  }

  _setTab(tab) {
    this._tab = tab;
    for (const [key, button] of Object.entries(this._tabButtons)) {
      button.className = key === tab ? "tab active" : "tab";
    }
    this._chatView.hidden = tab !== "chat";
    this._nodesView.hidden = tab !== "nodes";
    this._stationsView.hidden = tab !== "stations";
    clearInterval(this._stationTimer);
    if (tab === "nodes") {
      this._nodesSignature = "";
      this._renderNodes();
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
    this._entryId = entryId;
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
    if (path.length > 1) parts.push(`${t.via} ${path.join(" > ")}`);
    if (message.via_server) parts.push(t.viaServer);
    if (!message.own && message.rssi !== null && message.rssi !== undefined) {
      parts.push(`${message.rssi} dBm / ${message.snr} dB`);
    }
    const meta = el("div", "meta", parts.join(" \u00b7 "));
    meta.dir = "auto";
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

  _renderNodes() {
    if (!this._nodesBody || !this._hass || !this._loaded) return;
    const t = this._t;
    const states = this._hass.states;
    const signature = JSON.stringify(
      this._nodes.map((node) => node.entities.map((item) => {
        const state = states[item.entity_id];
        return state ? [state.state, state.attributes.latitude, state.attributes.longitude] : null;
      }))
    );
    if (signature === this._nodesSignature) return;
    this._nodesSignature = signature;
    if (!this._nodes.length) {
      this._nodesBody.replaceChildren(el("div", "empty", t.noNodes));
      return;
    }
    const cards = el("div", "cards");
    for (const node of this._nodes) cards.append(this._renderNodeCard(node, t));
    this._nodesBody.replaceChildren(cards);
  }

  _renderNodeCard(node, t) {
    const card = el("div", "card");
    card.append(el("h2", null, node.callsign), el("div", "sub", t.access[node.access] || node.access));
    for (const item of node.entities) {
      const state = this._hass.states[item.entity_id];
      if (!state) continue;
      const row = el("div", "row");
      row.append(el("span", "label", this._entityLabel(state, node)));
      row.append(this._entityValue(item, state, t));
      card.append(row);
    }
    return card;
  }

  _entityLabel(state, node) {
    const name = String(state.attributes.friendly_name || state.entity_id);
    // "MeshCom DO8RE-12 Akku" -> "Akku"
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
  }

  _renderStations() {
    if (!this._stationsBody) return;
    const t = this._t;
    const hint = this._stationsMode === "data" ? t.mapHintData : this._stationsMode === "entities" ? t.mapHintEntities : "";
    this._mapHint.textContent = hint;
    this._mapHint.hidden = !hint;
    if (this._stationsMode === "off") {
      this._stationsBody.replaceChildren(el("div", "empty", t.stationsOff));
      return;
    }
    if (this._stations === null) return;
    const rows = this._stations.filter(
      (s) => !this._stationFilter || s.callsign.includes(this._stationFilter)
    );
    if (!rows.length) {
      this._stationsBody.replaceChildren(el("div", "empty", t.noStations));
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
    const numeric = new Set(["rssi", "snr", "hops", "battery"]);
    for (const column of ["callsign", "last_heard", "rssi", "snr", "hops", "battery", "position"]) {
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
      const call = el("button", "linkbutton", station.callsign);
      call.addEventListener("click", () => this._openDirect(station.callsign));
      callTd.append(call);
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
        el("td", "num", station.battery === null || station.battery === undefined ? "" : `${station.battery} %`)
      );
      const posTd = el("td");
      if (Number.isFinite(station.latitude) && Number.isFinite(station.longitude)) {
        const map = el("button", "linkbutton", t.map);
        map.addEventListener("click", () => openMap(station.latitude, station.longitude));
        posTd.append(map);
      }
      tr.append(posTd);
      table.append(tr);
    }
    this._stationsBody.replaceChildren(table);
  }
}

if (!customElements.get("meshcom-chat-panel")) {
  customElements.define("meshcom-chat-panel", MeshComChatPanel);
}
