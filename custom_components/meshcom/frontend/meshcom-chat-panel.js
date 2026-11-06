/*
 * MeshCom chat panel for Home Assistant.
 *
 * Security (concept C-01): every text that comes from the radio is untrusted.
 * This file never uses innerHTML, outerHTML, insertAdjacentHTML,
 * document.write, eval or Function, and never turns message text into links.
 * All content is set with textContent. A test in the repository checks this.
 */

const TEXT = {
  en: {
    title: "MeshCom",
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
    invalidCall: "Not a valid callsign.",
    tooLong: "Too long",
    viaServer: "via server",
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
  },
  de: {
    title: "MeshCom",
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
    invalidCall: "Kein g\u00fcltiges Rufzeichen.",
    tooLong: "Zu lang",
    viaServer: "\u00fcber Server",
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
  },
};

// Same rule as aiomeshcom/callsign.py; the server checks again.
const CALLSIGN_RE = /^(?=[A-Z0-9]*[0-9])(?=[A-Z0-9]*[A-Z])[A-Z0-9]{3,7}(?:-[0-9]{1,2})?$/;
const MAX_TEXT_BYTES = 150;
const ENCODER = new TextEncoder();

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function conversationTitle(id, t) {
  if (id === "all") return t.all;
  const [kind, peer] = [id.slice(0, id.indexOf(":")), id.slice(id.indexOf(":") + 1)];
  if (kind === "group") return `${t.group} ${peer}`;
  if (kind === "other") return `${t.other} ${peer}`;
  return peer;
}

function destinationOf(id) {
  if (id === "all") return "*";
  const kind = id.slice(0, id.indexOf(":"));
  const peer = id.slice(id.indexOf(":") + 1);
  return kind === "group" || kind === "dm" ? peer : null;
}

const STYLE = `
:host { display: block; height: 100%; color: var(--primary-text-color);
  background: var(--primary-background-color); font-family: var(--paper-font-body1_-_font-family, inherit); }
.toolbar { display: flex; align-items: center; gap: 8px; height: var(--header-height, 56px);
  padding: 0 12px; border-bottom: 1px solid var(--divider-color);
  background: var(--app-header-background-color, var(--primary-color));
  color: var(--app-header-text-color, var(--text-primary-color)); box-sizing: border-box; }
.toolbar .title { font-size: 20px; flex: 1; }
.toolbar select { font: inherit; }
.layout { display: flex; height: calc(100% - var(--header-height, 56px)); }
.sidebar { width: 260px; min-width: 200px; border-right: 1px solid var(--divider-color);
  overflow-y: auto; display: flex; flex-direction: column; background: var(--card-background-color); }
.conv { padding: 10px 12px; cursor: pointer; border-bottom: 1px solid var(--divider-color);
  display: flex; justify-content: space-between; gap: 8px; }
.conv:hover, .conv.active { background: var(--secondary-background-color); }
.conv .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.badge { background: var(--primary-color); color: var(--text-primary-color); border-radius: 10px;
  padding: 0 7px; font-size: 12px; line-height: 20px; }
.newchat { display: flex; gap: 4px; padding: 8px; border-top: 1px solid var(--divider-color); margin-top: auto; }
.newchat input { flex: 1; min-width: 0; text-transform: uppercase; }
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.msg { max-width: 75%; padding: 6px 10px; border-radius: 10px; background: var(--card-background-color);
  box-shadow: var(--ha-card-box-shadow, 0 1px 2px rgba(0,0,0,.2)); align-self: flex-start; }
.msg.own { align-self: flex-end; background: var(--primary-color); color: var(--text-primary-color); }
.msg .meta { font-size: 11px; opacity: .75; margin-bottom: 2px; }
.msg .text { white-space: pre-wrap; overflow-wrap: anywhere; unicode-bidi: plaintext; }
.msg .status { font-size: 11px; opacity: .75; text-align: right; margin-top: 2px; }
.composer { display: flex; gap: 8px; padding: 8px 12px; border-top: 1px solid var(--divider-color);
  background: var(--card-background-color); align-items: center; }
.composer input { flex: 1; min-width: 0; font: inherit; padding: 8px; }
.composer .count { font-size: 12px; opacity: .7; min-width: 52px; text-align: right; }
.composer .count.over { color: var(--error-color); opacity: 1; }
.notice, .error { padding: 8px 12px; font-size: 13px; }
.error { color: var(--error-color); }
.empty { opacity: .6; padding: 24px; text-align: center; }
button { font: inherit; cursor: pointer; }
@media (max-width: 640px) {
  .layout { flex-direction: column; }
  .sidebar { width: auto; max-height: 35%; border-right: none; border-bottom: 1px solid var(--divider-color); }
  .msg { max-width: 90%; }
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
    this._unread = new Map();
    this._unsubscribe = null;
    this._started = false;
    this._error = "";
    this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    const first = this._hass === null;
    this._hass = hass;
    if (this._menu) this._menu.hass = hass;
    if (first) this._start();
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
    this._renderNodeSelect();
    if (this._nodes.length) {
      await this._selectNode(this._nodes[0].entry_id);
    } else {
      this._render();
    }
  }

  _buildSkeleton() {
    const root = this.shadowRoot;
    root.replaceChildren();
    const style = el("style");
    style.textContent = STYLE;
    root.append(style);

    const toolbar = el("div", "toolbar");
    this._menu = document.createElement("ha-menu-button");
    this._menu.hass = this._hass;
    this._menu.narrow = this._narrow;
    this._title = el("div", "title", this._t.title);
    this._nodeSelect = el("select");
    this._nodeSelect.addEventListener("change", () => this._selectNode(this._nodeSelect.value));
    toolbar.append(this._menu, this._title, this._nodeSelect);

    const layout = el("div", "layout");
    this._sidebar = el("div", "sidebar");
    this._convList = el("div");
    const newChat = el("form", "newchat");
    this._newCall = el("input");
    this._newCall.placeholder = this._t.newChat;
    this._newCall.maxLength = 10;
    this._newCall.autocomplete = "off";
    newChat.append(this._newCall, el("button", null, this._t.open));
    newChat.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._openDirect(this._newCall.value);
    });
    this._sidebar.append(this._convList, newChat);

    const main = el("div", "main");
    this._errorLine = el("div", "error");
    this._messageList = el("div", "messages");
    this._notice = el("div", "notice");
    const composer = el("form", "composer");
    this._input = el("input");
    this._input.placeholder = this._t.placeholder;
    this._input.autocomplete = "off";
    this._count = el("span", "count");
    this._sendButton = el("button", null, this._t.send);
    composer.append(this._input, this._count, this._sendButton);
    composer.addEventListener("submit", (ev) => {
      ev.preventDefault();
      this._send();
    });
    this._input.addEventListener("input", () => this._updateCount());
    this._composer = composer;
    main.append(this._errorLine, this._messageList, this._notice, composer);

    layout.append(this._sidebar, main);
    root.append(toolbar, layout);
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

  async _selectNode(entryId) {
    if (!entryId) return;
    this._stopSubscription();
    this._entryId = entryId;
    this._nodeSelect.value = entryId;
    this._unread.clear();
    try {
      const history = await this._hass.callWS({ type: "meshcom/chat/history", entry_id: entryId });
      this._messages = history.messages;
      this._unsubscribe = await this._hass.connection.subscribeMessage(
        (event) => this._onEvent(entryId, event),
        { type: "meshcom/chat/subscribe", entry_id: entryId }
      );
      this._error = "";
    } catch (err) {
      this._showError(err);
    }
    this._render();
    this._scrollDown();
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
      this._messages.push(message);
      if (this._messages.length > 500) this._messages.shift();
      if (message.conversation !== this._active && !message.own) {
        this._unread.set(message.conversation, (this._unread.get(message.conversation) || 0) + 1);
      }
      this._render();
      if (message.conversation === this._active) this._scrollDown();
    } else if (event.status) {
      const target = [...this._messages].reverse().find((m) => m.own && m.id === event.status.id);
      if (target) {
        target.status = event.status.status;
        this._render();
      }
    }
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

  _render() {
    if (!this._convList) return;
    const t = this._t;
    this._errorLine.textContent = this._error;
    this._errorLine.hidden = !this._error;

    if (!this._nodes.length) {
      this._convList.replaceChildren();
      this._messageList.replaceChildren(el("div", "empty", t.noNodes));
      this._composer.hidden = true;
      this._notice.hidden = true;
      return;
    }

    this._convList.replaceChildren(
      ...this._conversations().map((id) => {
        const row = el("div", id === this._active ? "conv active" : "conv");
        const name = el("span", "name", conversationTitle(id, t));
        name.dir = "auto";
        row.append(name);
        const unread = this._unread.get(id);
        if (unread) row.append(el("span", "badge", unread));
        row.addEventListener("click", () => {
          this._active = id;
          this._unread.delete(id);
          this._render();
          this._scrollDown();
        });
        return row;
      })
    );

    const messages = this._messages.filter((m) => m.conversation === this._active);
    if (!messages.length) {
      this._messageList.replaceChildren(el("div", "empty", t.empty));
    } else {
      this._messageList.replaceChildren(...messages.map((m) => this._renderMessage(m, t)));
    }

    const destination = destinationOf(this._active);
    const node = this._node;
    let notice = "";
    if (destination === null) notice = t.readOnly;
    else if (node && !node.sending_enabled) notice = t.sendingOff;
    this._notice.textContent = notice;
    this._notice.hidden = !notice;
    this._composer.hidden = destination === null;
    this._updateCount();
  }

  _renderMessage(message, t) {
    const box = el("div", message.own ? "msg own" : "msg");
    const parts = [];
    if (!message.own || this._active === "all" || this._active.startsWith("group:")) {
      parts.push(message.sender);
    }
    const time = new Date(message.time);
    if (!Number.isNaN(time.getTime())) {
      parts.push(time.toLocaleString(this._hass.language || undefined, {
        dateStyle: "short",
        timeStyle: "short",
      }));
    }
    if (message.via_server) parts.push(t.viaServer);
    if (!message.own && message.rssi !== null && message.rssi !== undefined) {
      parts.push(`${message.rssi} dBm / ${message.snr} dB`);
    }
    const meta = el("div", "meta", parts.join(" \u00b7 "));
    meta.dir = "auto";
    const text = el("div", "text", message.text);
    text.dir = "auto";
    box.append(meta, text);
    if (message.own && message.status) {
      box.append(el("div", "status", t.status[message.status] || t.status.unknown));
    }
    return box;
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
    this._active = `dm:${call}`;
    this._render();
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
}

if (!customElements.get("meshcom-chat-panel")) {
  customElements.define("meshcom-chat-panel", MeshComChatPanel);
}
