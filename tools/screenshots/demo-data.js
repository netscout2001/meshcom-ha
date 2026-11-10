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

  const ent = (entity_id, domain, state, name, extra = {}) => ({ entity_id, domain, state, name, extra });
  const nodeEntities = (slug, call, kiss, values) => [
    ent(`binary_sensor.${slug}_active`, "binary_sensor", "Connected", "Active"),
    ...(kiss ? [ent(`binary_sensor.${slug}_kiss_connected`, "binary_sensor", "Connected", "KISS connected")] : []),
    ent(`switch.${slug}_no_msg_all`, "switch", "on", "No MSG All"),
    ent(`switch.${slug}_sending_enabled`, "switch", "on", "Allow sending"),
    ent(`sensor.${slug}_altitude`, "sensor", values.alt, "Altitude"),
    ent(`sensor.${slug}_battery`, "sensor", values.batt, "Battery"),
    ent(`sensor.${slug}_battery_voltage`, "sensor", values.volt, "Battery voltage"),
    ent(`sensor.${slug}_firmware`, "sensor", values.fw, "Firmware"),
    ent(`sensor.${slug}_last_message`, "sensor", values.msg, "Last message"),
    ent(`sensor.${slug}_last_sender`, "sensor", values.sender, "Last sender"),
    ent(`sensor.${slug}_last_rssi`, "sensor", values.rssi, "Last RSSI"),
    ent(`sensor.${slug}_last_snr`, "sensor", values.snr, "Last SNR"),
    ent(`sensor.${slug}_messages_received`, "sensor", values.rx, "Messages received"),
    ent(`sensor.${slug}_messages_sent`, "sensor", values.tx, "Messages sent"),
    ent(`sensor.${slug}_stations_heard`, "sensor", values.heard, "Stations heard (24 h)"),
    ent(`sensor.${slug}_last_packet`, "sensor", values.lastPacket, "Last packet"),
    ent(`device_tracker.${slug}_position`, "device_tracker", "away", "Position", { latitude: values.lat, longitude: values.lon }),
  ];
  const udp = nodeEntities("meshcom_qx1node_12", own, false, { alt: "516.9 m", batt: "96 %", volt: "4.01 V", fw: "4.40a", msg: "19:00 works, see you on 262", sender: "QA1ABC-12", rssi: "-101 dBm", snr: "5.0 dB", rx: "41", tx: "3", heard: "24", lastPacket: "1 minute ago", lat: 50.06, lon: 8.82 });
  const kiss = nodeEntities("meshcom_qx1node_9", mobile, true, { alt: "512.1 m", batt: "99 %", volt: "4.16 V", fw: "4.40a", msg: "Test", sender: own, rssi: "-60 dBm", snr: "9.0 dB", rx: "2", tx: "1", heard: "19", lastPacket: "4 minutes ago", lat: 50.0, lon: 8.95 });
  const states = {};
  for (const e of [...udp, ...kiss]) {
    const owner = udp.includes(e) ? own : mobile;
    states[e.entity_id] = { entity_id: e.entity_id, state: e.state, attributes: { friendly_name: `MeshCom ${owner} ${e.name}`, ...e.extra } };
  }
  const entityList = (list) => list.map((e) => ({ entity_id: e.entity_id, domain: e.domain, key: e.name }));
  const nodes = [
    { entry_id: "demo-udp", callsign: own, groups: [262, 20, 9], sending_enabled: true, access: "udp", station_mode: "data", entities: entityList(udp) },
    { entry_id: "demo-kiss", callsign: mobile, groups: [262], sending_enabled: true, access: "kiss", station_mode: "data", entities: entityList(kiss) },
  ];

  window.demoHass = {
    language: "en",
    themes: { darkMode: true },
    states,
    formatEntityState: (state) => (state.entity_id.startsWith("switch.") ? state.state : state.state),
    callWS: async (msg) => {
      if (msg.type === "meshcom/chat/nodes") return { nodes };
      if (msg.type === "meshcom/chat/history") return { messages: msg.entry_id === "demo-udp" ? messages : messages.filter((m) => m.conversation === "dm:" + own) };
      if (msg.type === "meshcom/chat/stations") return { mode: "data", stations };
      return {};
    },
    callService: async () => {},
    connection: { addEventListener() {}, removeEventListener() {}, subscribeMessage: async () => () => {} },
  };
})();
