// Invented demo data for the README screenshots. All callsigns use the
// prefix "Q", which is not assigned to any country, so none of them belongs
// to a real station. Positions are random points, not real locations.
(() => {
  const now = Date.now();
  const ago = (min) => new Date(now - min * 60000).toISOString();
  const own = "QX1NODE-12";
  const mobile = "QX1NODE-9";
  const relays = ["QB0RPT-12", "QB0HIL-12", "QB0TWR-1"];
  let id = 1;
  const messages = [];
  const add = (conversation, sender, text, min, extra = {}) =>
    messages.push({
      id: id++, conversation, sender, text, time: ago(min), own: sender === own,
      status: sender === own ? "sent" : null, rssi: -112, snr: -6, via_server: false,
      path: [sender, relays[id % 3]], ...extra,
    });
  add("group:262", "QA1ABC-12", "Good morning everyone, nice and clear up here today", 1500);
  add("group:262", "QD2XYZ-7", "Morning! New node on the hill is running fine", 1490, { rssi: -121, snr: -14, path: ["QD2XYZ-7", "QB0HIL-12", "QB0RPT-12"] });
  add("group:262", "QE4LMN-1", "Firmware update went smoothly here too", 1460, { via_server: true, rssi: null, snr: null, path: ["QE4LMN-1"] });
  add("group:262", own, "Test from Home Assistant, 73", 1400, { status: "sent", path: [own] });
  add("group:262", "QA1ABC-12", "Loud and clear, 73", 1395, { rssi: -98, snr: 7 });
  add("group:262", "QF7RST-12", "WX: 4 C, light fog, wind 1-5 km/h", 80, { path: ["QF7RST-12", "QB0TWR-1", "QB0RPT-12"] });
  add("group:262", "QD2XYZ-7", "Anyone up for a test with the mobile node this evening?", 25, { rssi: -124, snr: -16 });
  add("group:262", "QE4LMN-1", "Count me in, 19:00?", 12, { via_server: true, rssi: null, snr: null, path: ["QE4LMN-1"] });
  add("group:262", "QA1ABC-12", "19:00 works, see you on 262", 4, { rssi: -101, snr: 5 });
  add("group:20", "QG3UVW-12", "Hello from the south, the relay chain is open again", 300);
  add("group:20", "QH5JKL-2", "Thanks for the info!", 40);
  add("group:9", "QJ8MNO-12", "Group 9 test", 900);
  add("all", "QK2PQR-1", "CQ CQ from the valley", 600, { path: ["QK2PQR-1", "QB0RPT-12"] });
  add("dm:QB2DEF-1", own, "Hi, can you hear my node?", 70, { status: "delivered", path: [own] });
  add("dm:QB2DEF-1", "QB2DEF-1", "Yes, -104 dBm here. Good signal!", 66, { rssi: -95, snr: 9 });
  add("dm:QB2DEF-1", "QB2DEF-1", "Want to try the relay later?", 6, { rssi: -97, snr: 8 });
  add("dm:" + mobile, own, "Test", 200, { status: "delivered", path: [own] });
  add("dm:" + mobile, mobile, "Re-Test", 199, { rssi: -60, snr: 11, path: [mobile] });

  const conv = (c) => messages.filter((m) => m.conversation === c);
  const read = {
    all: conv("all").at(-1).time,
    "group:262": conv("group:262").at(-4).time,
    "group:20": conv("group:20")[0].time,
    "group:9": conv("group:9").at(-1).time,
    "dm:QB2DEF-1": conv("dm:QB2DEF-1").at(-2).time,
    ["dm:" + mobile]: conv("dm:" + mobile).at(-1).time,
  };
  try { localStorage.setItem("meshcom-chat-read:demo-udp", JSON.stringify(read)); } catch (e) {}

  // Stations around a random centre; no real places.
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const names = ["QA1ABC-12","QD2XYZ-7","QE4LMN-1","QF7RST-12","QG3UVW-12","QH5JKL-2","QJ8MNO-12","QK2PQR-1","QB2DEF-1",
    "QB0RPT-12","QB0HIL-12","QB0TWR-1","QL6STU-12","QM1VWX-3","QN4YZA-12","QP7BCD-1","QR2EFG-12","QS5HIJ-7","QT8KLM-12",
    "QU3NOP-2","QV6QRS-12","QW9TUV-1","QY2WXY-12","QZ5ZAB-4", mobile];
  const centre = { lat: 50.05, lon: 8.85 };
  const stations = names.map((callsign, i) => {
    const heard = i < 9 ? rnd() * 50 : i < 19 ? 70 + rnd() * 900 : 1600 + rnd() * 4000;
    const located = i % 7 !== 3;
    const relays = ["QB0RPT-12", "QB0HIL-12", "QB0TWR-1"].filter((r) => r !== callsign);
    // Direct neighbours (the first stations) were last heard without relay.
    const direct = i < 6;
    const randomHops = Math.floor(rnd() * 3); // drawn anyway: keeps the other values stable
    const hops = callsign === mobile || direct ? 0 : randomHops;
    const weather = rnd() > 0.55;
    return {
      path: relays.slice(0, hops),
      temperature: weather ? Math.round((2 + rnd() * 8) * 10) / 10 : null,
      humidity: weather ? Math.round(60 + rnd() * 35) : null,
      pressure: weather ? Math.round((1012 + rnd() * 14) * 10) / 10 : null,
      callsign, last_heard: ago(heard),
      rssi: callsign === mobile ? -60 : Math.round(-90 - rnd() * 37),
      snr: callsign === mobile ? 11 : Math.round(10 - rnd() * 27),
      hops,
      battery: rnd() > 0.4 ? Math.round(60 + rnd() * 40) : null,
      latitude: located ? centre.lat + (rnd() - 0.5) * 0.32 : null,
      longitude: located ? centre.lon + (rnd() - 0.5) * 1.3 : null,
      // Values from the MHeard list of the node.
      ...(direct ? {
        direct: true,
        hardware: ["TBEAM_AXP2101", "HELTEC_V3", "RAK4631", "TBEAM_1W"][i % 4],
        altitude: Math.round(400 + rnd() * 1200),
        hears_me_snr: i === 4 ? null : Math.round(8 - rnd() * 20),
        relay_role: i === 1 ? "super" : i === 3 ? "needed" : "redundant",
        it_hears: Math.round(3 + rnd() * 30),
        only_it_hears: i === 1 ? 9 : i === 3 ? 2 : 0,
        neighbours: Math.round(2 + rnd() * 30),
        gateway: i === 2,
      } : { direct: false }),
    };
  });

  // Entity states as Home Assistant has them: raw value plus unit.
  const ent = (key, domain, state, name, unit = null, extra = {}) => ({ key, domain, state, name, unit, extra });
  const minutesAgo = (min) => new Date(Date.now() - min * 60000).toISOString();
  const nodeEntities = (slug, kiss, values) =>
    [
      ent("active", "binary_sensor", "on", "Active"),
      ...(kiss ? [ent("kiss_connected", "binary_sensor", "on", "KISS connected")] : []),
      ent("no_msg_all", "switch", "on", "No MSG All"),
      ent("sending_enabled", "switch", "on", "Allow sending"),
      ent("altitude", "sensor", values.alt, "Altitude", "m"),
      ent("battery", "sensor", values.batt, "Battery", "%"),
      ent("battery_voltage", "sensor", values.volt, "Battery voltage", "V"),
      ent("firmware", "sensor", values.fw, "Firmware"),
      ent("last_message", "sensor", values.msg, "Last message"),
      ent("last_sender", "sensor", values.sender, "Last sender"),
      ent("last_rssi", "sensor", values.rssi, "Last RSSI", "dBm"),
      ent("last_snr", "sensor", values.snr, "Last SNR", "dB"),
      ent("messages_received", "sensor", values.rx, "Messages received"),
      ent("messages_sent", "sensor", values.tx, "Messages sent"),
      ent("stations_heard", "sensor", values.heard, "Stations heard (24 h)"),
      ent("last_packet", "sensor", values.lastPacket, "Last packet"),
      ...(values.radio
        ? [
            ent("channel_rx", "sensor", "11.4", "Channel use RX", "%"),
            ent("channel_tx", "sensor", "4.4", "Channel use TX", "%"),
            ent("tx_queue", "sensor", "3", "TX queue"),
          ]
        : []),
      ent("position", "device_tracker", "away", "Position", null, { latitude: values.lat, longitude: values.lon }),
    ].map((e) => ({ ...e, entity_id: `${e.domain}.${slug}_${e.key}` }));
  const udp = nodeEntities("meshcom_qx1node_12", false, { alt: "517", batt: "96", volt: "4.157", fw: "4.40a", msg: "19:00 works, see you on 262", sender: "QA1ABC-12", rssi: "-101", snr: "5.0", rx: "412", tx: "23", heard: "24", lastPacket: minutesAgo(1), lat: 50.06, lon: 8.82, radio: true });
  const kiss = nodeEntities("meshcom_qx1node_9", true, { alt: "512", batt: "63", volt: "3.86", fw: "4.40a", msg: "Test", sender: own, rssi: "-60", snr: "9.0", rx: "57", tx: "4", heard: "19", lastPacket: minutesAgo(4), lat: 50.0, lon: 8.95, radio: false });
  const states = {};
  for (const e of [...udp, ...kiss]) {
    const owner = udp.includes(e) ? own : mobile;
    const attributes = { friendly_name: `MeshCom ${owner} ${e.name}`, ...e.extra };
    if (e.unit) attributes.unit_of_measurement = e.unit;
    states[e.entity_id] = { entity_id: e.entity_id, state: e.state, attributes };
  }
  const entityList = (list) => list.map((e) => ({ entity_id: e.entity_id, domain: e.domain, key: e.key }));
  const nodes = [
    { entry_id: "demo-udp", callsign: own, groups: [262, 20, 9], sending_enabled: true, access: "udp", station_mode: "data", entities: entityList(udp) },
    { entry_id: "demo-kiss", callsign: mobile, groups: [262], sending_enabled: true, access: "kiss", station_mode: "data", entities: entityList(kiss) },
  ];

  // Node dashboard: 48 hours of message activity and channel use (invented).
  const hourStart = new Date();
  hourStart.setUTCMinutes(0, 0, 0);
  const hours = Array.from({ length: 48 }, (_, i) => new Date(hourStart.getTime() - (47 - i) * 3600000).toISOString());
  const wave = (i, base, amp, phase) => Math.max(0, Math.round(base + amp * Math.sin((i + phase) / 3.8) + (rnd() - 0.5) * amp));
  const activityFor = (scale) => ({
    hours,
    received_direct: hours.map((_, i) => Math.round(wave(i, 1, 1, 0) * scale)),
    received_group: hours.map((_, i) => Math.round(wave(i, 7, 5, 2) * scale)),
    received_all: hours.map((_, i) => Math.round(wave(i, 1, 1, 5) * scale)),
    sent: hours.map((_, i) => (i % 9 === 3 ? 1 : 0)),
  });
  const neighbourList = stations
    .filter((st) => st.direct)
    .map((st, i) => ({
      callsign: st.callsign, direct_heard: minutesAgo(i * 3), rssi: st.rssi, snr: st.snr,
      hears_me_snr: st.hears_me_snr, relay_role: st.relay_role, hardware: st.hardware,
      it_hears: st.it_hears, only_it_hears: st.only_it_hears, gateway: st.gateway, located: st.latitude !== null,
    }));
  const nodeStatus = {
    "demo-udp": {
      entry_id: "demo-udp", callsign: own, active: true, last_packet: minutesAgo(1), kiss_connected: null,
      web: {
        ok: true, paused: false, radio_enabled: true, fetched: minutesAgo(0.5), started: minutesAgo(2 * 1440 + 207),
        info: { uptime_seconds: 185220, hardware: "TBEAM_AXP2101", frequency_mhz: 433.175, bandwidth_khz: 250, spreading_factor: 11, coding_rate: 6, tx_power_dbm: 20, wifi_rssi: -56, server: "connected", server_age_seconds: 10, max_hop_text: 4, max_hop_pos: 2, blocked_dropped: 0 },
        gps: { enabled: true, satellites: 10, fix: true, hdop: 1, beacon_interval: 1800, next_beacon: 1275 },
        radio: { queue_used: 3, queue_size: 20, queue_by_priority: { crit: 0, high: 1, normal: 1, low: 0, bg: 1 }, waiting_ack: 1, slow_down_at: 7, refuse_at: 16, state: "accepted", rx_percent: 11.4, tx_percent: 4.4, dropped: 0, new_ids: 13, duplicates: 8, dedup_window_minutes: 27, window_age_seconds: 186 },
      },
      counters: { received: 412, sent: 23, duplicates: 148, filtered: 6 },
      activity: activityFor(1),
      delivery: { delivered: 4, pending: 1, failed: 0, unknown: 0 },
      stations: { heard_24h: 24, direct: neighbourList.length },
      neighbours: neighbourList,
    },
    "demo-kiss": {
      entry_id: "demo-kiss", callsign: mobile, active: true, last_packet: minutesAgo(4), kiss_connected: true,
      web: {
        ok: true, paused: false, radio_enabled: false, fetched: minutesAgo(1), started: minutesAgo(310),
        info: { uptime_seconds: 18600, hardware: "TLORA_V2_1_1p6", frequency_mhz: 433.175, bandwidth_khz: 250, spreading_factor: 11, coding_rate: 6, tx_power_dbm: 17, wifi_rssi: -71, server: "off", server_age_seconds: null, max_hop_text: 4, max_hop_pos: 2, blocked_dropped: 0 },
        gps: { enabled: false, satellites: null, fix: null, hdop: null, beacon_interval: 1800, next_beacon: 900 },
        radio: null,
      },
      counters: { received: 57, sent: 4, duplicates: 12, filtered: 0 },
      activity: activityFor(0.3),
      delivery: { delivered: 1, pending: 0, failed: 0, unknown: 0 },
      stations: { heard_24h: 19, direct: 3 },
      neighbours: neighbourList.slice(0, 3),
    },
  };
  const historyFor = (id) => {
    const points = [];
    for (let i = 0; i <= 48 * 12; i += 1) {
      const time = Date.now() - (48 * 12 - i) * 300000;
      let value;
      if (id.endsWith("_battery")) value = Math.round(96 - 3 * Math.sin((576 - i) / 70));
      else if (id.endsWith("_channel_rx")) value = Math.round((9 + 4 * Math.sin(i / 40) + rnd() * 4) * 10) / 10;
      else value = Math.round((3 + 2 * Math.sin(i / 25) + rnd() * 2) * 10) / 10;
      points.push({ s: String(value), lu: time / 1000 });
    }
    return points;
  };

  window.demoHass = {
    language: "en",
    themes: { darkMode: true },
    states,
    formatEntityState: (state) => (state.attributes.unit_of_measurement ? `${state.state} ${state.attributes.unit_of_measurement}` : state.state),
    callWS: async (msg) => {
      if (msg.type === "meshcom/chat/nodes") return { nodes };
      if (msg.type === "meshcom/chat/history") return { messages: msg.entry_id === "demo-udp" ? messages : messages.filter((m) => m.conversation === "dm:" + own) };
      if (msg.type === "meshcom/chat/stations") return { mode: "data", stations };
      if (msg.type === "meshcom/chat/node_status") return nodeStatus[msg.entry_id];
      if (msg.type === "history/history_during_period") return Object.fromEntries(msg.entity_ids.map((id) => [id, historyFor(id)]));
      return {};
    },
    callService: async () => {},
    connection: { addEventListener() {}, removeEventListener() {}, subscribeMessage: async () => () => {} },
  };
})();
