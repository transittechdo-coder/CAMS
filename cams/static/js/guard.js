// CAMS guard view: a light page for guards' phones on the site's Wi-Fi.
// Alerts (with the red emergency screen and siren), cameras, visitors inside, find a person.
const app = document.getElementById("app");
let me = null, tab = "alerts", timers = [], audio = null, siren = null, muted = false, shownKey = "";

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c != null && c !== false) el.append(c.nodeType ? c : document.createTextNode(String(c)));
  return el;
}
async function api(path, opts = {}) {
  const r = await fetch(path, { method: opts.method || "GET", headers: opts.body ? { "content-type": "application/json" } : {},
    body: opts.body ? JSON.stringify(opts.body) : undefined, credentials: "same-origin" });
  if (r.status === 401 && path !== "/api/login") { me = null; showLogin(); throw new Error("Signed out"); }
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : null;
  if (!r.ok) throw new Error(data?.detail || `Error ${r.status}`);
  return data;
}
const ago = (ts) => { const s = Date.now() / 1000 - ts; return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : new Date(ts * 1000).toLocaleDateString(); };
const time = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const LABEL = { fire: ["FIRE", "red"], smoke: ["Heavy smoke", "red"], person_down: ["Person down", "red"], emergency_test: ["Alarm test", ""],
  watchlist: ["Watch list", "amber"], access_violation: ["Not allowed here", "red"], unknown_restricted: ["Restricted camera", "red"],
  visitor_overstay: ["Visitor overstay", "amber"], bag_left: ["Bag left", "amber"], plate_flagged: ["Flagged vehicle", "red"],
  plate_unknown: ["Unknown vehicle", "amber"], camera_offline: ["Camera offline", ""], tamper: ["Camera tampering", "red"],
  downtime: ["CAMS was off", "amber"], power: ["Power", "amber"], loitering: ["Loitering", "amber"], crowd: ["Crowd", "amber"],
  running: ["Running", "amber"], after_hours: ["After hours", "amber"] };
const EMERGENCY = { fire: "FIRE", smoke: "HEAVY SMOKE", person_down: "PERSON DOWN", emergency_test: "ALARM TEST" };

// ------------------------------------------------------------------ sign in
function showLogin(msg = "") {
  timers.forEach(clearInterval); timers = [];
  const user = h("input", { name: "u", autocomplete: "username", placeholder: "Username", autocapitalize: "none" });
  const pass = h("input", { name: "p", type: "password", autocomplete: "current-password", placeholder: "Password" });
  const err = h("p", { class: "err", role: "alert" }, msg);
  const go = async (e) => {
    e.preventDefault(); unlockAudio();
    try { await api("/api/login", { method: "POST", body: { username: user.value.trim(), password: pass.value } }); await start(); }
    catch (x) { err.textContent = x.message; }
  };
  app.replaceChildren(h("form", { class: "login card", onsubmit: go },
    h("h1", {}, "CAMS Guard"), h("p", { class: "muted" }, "Sign in with your CAMS account."),
    h("div", { style: "display:grid;gap:10px;margin-top:14px" }, user, pass, err, h("button", { class: "primary", type: "submit" }, "Sign in"))));
}

// ------------------------------------------------------------------ siren
function unlockAudio() { if (!audio) try { audio = new (window.AudioContext || window.webkitAudioContext)(); } catch {} }
// Inside the CAMS Guard app the phone itself rings (also when locked), so the page stays quiet.
const IN_APP = /CAMSGuardApp/.test(navigator.userAgent);
const ANDROID = /Android/i.test(navigator.userAgent);

function startSiren() {
  if (IN_APP || siren || muted || !audio) return;
  audio.resume?.();
  const o = audio.createOscillator(), g = audio.createGain();
  o.type = "square"; g.gain.value = 0.15; o.connect(g).connect(audio.destination); o.start();
  let hi = false;
  const t = setInterval(() => { hi = !hi; o.frequency.setValueAtTime(hi ? 1000 : 700, audio.currentTime); navigator.vibrate?.([300, 120, 300]); }, 450);
  siren = { stop: () => { clearInterval(t); try { o.stop(); } catch {} } };
}
function stopSiren() { siren?.stop(); siren = null; }

const em = h("div", { class: "em hidden", role: "alertdialog", "aria-live": "assertive" });
document.body.append(em);
async function pollEmergencies() {
  if (!me) return;
  let list = [];
  try { list = await api("/api/alerts/emergencies"); } catch { return; }
  if (!list.length) { em.classList.add("hidden"); stopSiren(); shownKey = ""; muted = false; return; }
  const key = list.map((a) => a.id).join(",");
  if (key !== shownKey) {
    if (list.some((a) => !shownKey.split(",").includes(String(a.id)))) muted = false;
    shownKey = key;
    em.replaceChildren(
      h("div", { class: "row" }, h("h1", { class: "grow" }, list.length > 1 ? `${list.length} EMERGENCIES` : EMERGENCY[list[0].kind]),
        h("button", { class: "mute", onclick: () => { muted = true; stopSiren(); } }, "Mute")),
      ...list.map((a) => h("div", { class: "item" },
        a.snapshot_path ? h("img", { src: `/api/snapshots/${a.snapshot_path}`, alt: "Camera picture" }) : null,
        h("p", {}, h("b", {}, EMERGENCY[a.kind]), " · ", time(a.created_at), a.camera_name ? ` · ${a.camera_name}` : ""),
        h("p", {}, a.message),
        h("button", { class: "ok", onclick: async (e) => { e.target.disabled = true; try { await api(`/api/alerts/${a.id}/ack`, { method: "POST" }); } catch {} pollEmergencies(); } },
          a.kind === "emergency_test" ? "Stop the test" : "I'm handling it"))),
      h("p", {}, "Tanzania: 114 fire and rescue, 112 emergency."));
  }
  em.classList.remove("hidden");
  startSiren();
}

// ------------------------------------------------------------------ main screen
const main = h("main");
const counts = {};
const TABS = [["alerts", "Alerts"], ["cameras", "Cameras"], ["visitors", "Visitors"], ["find", "Find"]];
const nav = h("nav", {}, TABS.map(([id, label]) => {
  counts[id] = h("span", { class: "count hidden" });
  return h("button", { "data-tab": id, onclick: () => show(id) }, label, counts[id]);
}));

async function start() {
  const st = await api("/api/status");
  if (!st.user) return showLogin();
  me = st.user;
  document.title = `CAMS Guard - ${st.site_name}`;
  app.replaceChildren(
    h("header", {}, h("b", {}, st.site_name, h("br"), h("small", {}, `${me.full_name || me.username} · CAMS Guard`)),
      h("button", { onclick: async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); me = null; showLogin(); } }, "Sign out")),
    main, nav);
  show(tab);
  timers.push(setInterval(pollEmergencies, 3000), setInterval(badge, 10000));
  pollEmergencies(); badge();
}

async function badge() {
  try { const a = await api("/api/alerts?open_only=true&limit=99"); counts.alerts.textContent = a.length; counts.alerts.classList.toggle("hidden", !a.length); } catch {}
}

let pageTimer = null;
function show(id) {
  tab = id;
  clearInterval(pageTimer);
  nav.querySelectorAll("button").forEach((b) => b.dataset.tab === id ? b.setAttribute("aria-current", "page") : b.removeAttribute("aria-current"));
  main.replaceChildren();
  ({ alerts, cameras, visitors, find })[id]().catch((e) => main.append(h("p", { class: "err" }, e.message)));
}

async function alerts() {
  const load = async () => {
    const list = await api("/api/alerts?open_only=true&limit=50");
    main.replaceChildren(h("div", { class: "row", style: "margin-bottom:10px" }, h("b", { class: "grow" }, `${list.length} open alert${list.length === 1 ? "" : "s"}`),
      list.length ? h("button", { onclick: async () => { await api("/api/alerts/ack-all", { method: "POST" }); load(); badge(); } }, "All seen") : null),
    ...(list.length ? list.map((a) => {
      const [label, cls] = LABEL[a.kind] || [a.kind, ""];
      const scene = a.snapshot_path?.includes("scene_");
      return h("div", { class: "card alert" },
        h("div", { class: "row" }, a.snapshot_path && !scene ? h("img", { class: "face", src: `/api/snapshots/${a.snapshot_path}`, alt: "" }) : null,
          h("div", { class: "grow" }, h("span", { class: `tag ${cls}` }, label), " ", h("span", { class: "muted" }, `${time(a.created_at)}${a.camera_name ? " · " + a.camera_name : ""}`),
            h("div", {}, a.message)),
          h("button", { onclick: async () => { await api(`/api/alerts/${a.id}/ack`, { method: "POST" }); load(); badge(); } }, "Seen")),
        scene ? h("img", { src: `/api/snapshots/${a.snapshot_path}`, alt: "What the camera saw", loading: "lazy" }) : null);
    }) : [h("div", { class: "card muted" }, "No open alerts. New ones appear here, and emergencies cover the screen.")]));
  };
  await load();
  pageTimer = setInterval(() => load().catch(() => {}), 6000);
}

async function cameras() {
  const cams = (await api("/api/cameras")).filter((c) => c.enabled);
  if (!cams.length) { main.append(h("div", { class: "card muted" }, "No cameras.")); return; }
  const imgs = [];
  main.append(h("p", { class: "muted", style: "margin-top:0" }, "Pictures refresh every few seconds. Tap a camera to watch it live."),
    h("div", { class: "cams" }, cams.map((c) => {
      const img = h("img", { alt: c.name, src: `/api/cameras/${c.id}/snapshot.jpg?t=${Date.now()}` });
      img.onerror = () => { img.removeAttribute("src"); };
      imgs.push([c, img]);
      return h("button", { class: "cam", onclick: () => watch(c) }, img, h("span", {}, c.live.status === "online" ? c.name : `${c.name} (${c.live.status})`));
    })));
  const refresh = () => { if (!document.hidden && tab === "cameras" && !document.querySelector(".full")) imgs.forEach(([c, img]) => { img.src = `/api/cameras/${c.id}/snapshot.jpg?t=${Date.now()}`; }); };
  pageTimer = setInterval(refresh, 3000);
}
function watch(c) {
  const img = h("img", { alt: `Live: ${c.name}`, src: `/api/cameras/${c.id}/stream?fps=5` });
  const box = h("div", { class: "full" }, h("div", { class: "bar" }, h("b", { class: "grow" }, c.name),
    h("button", { onclick: () => { img.removeAttribute("src"); box.remove(); } }, "Close")), img);
  document.body.append(box);
}

async function visitors() {
  const load = async () => {
    const list = await api("/api/visitors?inside=true");
    main.replaceChildren(h("b", {}, `${list.length} visitor${list.length === 1 ? "" : "s"} inside`), h("div", { style: "height:10px" }),
      ...(list.length ? list.map((v) => h("div", { class: `card ${v.overstaying ? "over" : ""}` },
        h("div", { class: "row" }, v.has_photo ? h("img", { src: `/api/visitors/${v.id}/photo`, alt: "", style: "width:56px;height:56px;object-fit:cover;border-radius:6px" }) : null,
          h("div", { class: "grow" }, h("b", {}, v.full_name), h("div", { class: "muted" }, [v.host && `Visiting ${v.host}`, v.purpose].filter(Boolean).join(" · ")),
            h("div", { class: "muted" }, v.overstaying ? h("b", { style: "color:var(--red)" }, `Should have left at ${time(v.expected_out)}`) : `Leaves by ${time(v.expected_out)}`,
              v.last_seen ? ` · seen at ${v.last_seen.building_name || v.last_seen.camera_name} ${ago(v.last_seen.last_seen)}` : ""))),
        me.role !== "viewer" ? h("button", { class: "danger", style: "margin-top:8px;width:100%", onclick: async () => {
          if (!confirm(`Check out ${v.full_name}?`)) return;
          await api(`/api/visitors/${v.id}/checkout`, { method: "POST" }); load();
        } }, "Check out") : null)) : [h("div", { class: "card muted" }, "No visitors inside.")]));
  };
  await load();
  pageTimer = setInterval(() => load().catch(() => {}), 10000);
}

async function find() {
  const q = h("input", { type: "search", placeholder: "Name or ID number", "aria-label": "Search" });
  const out = h("div", { style: "margin-top:10px" });
  const run = async (e) => {
    e?.preventDefault();
    if (q.value.trim().length < 2) return;
    try {
      const rows = await api(`/api/search/last-seen?q=${encodeURIComponent(q.value.trim())}`);
      out.replaceChildren(...(rows.length ? rows.map((p) => h("div", { class: "card row" },
        p.photo_path ? h("img", { src: `/api/people/${p.id}/photo`, alt: "", style: "width:56px;height:56px;object-fit:cover;border-radius:6px" }) : null,
        h("div", { class: "grow" }, h("b", {}, p.full_name), h("div", { class: "muted" }, [p.person_code, p.group_name].filter(Boolean).join(" · ")),
          h("div", {}, p.last_seen ? `Last seen ${ago(p.last_seen.last_seen)} at ${p.last_seen.building_name || p.last_seen.camera_name}` : "Not seen recently")))) :
        [h("div", { class: "card muted" }, "Nobody found.")]));
    } catch (x) { out.replaceChildren(h("p", { class: "err" }, x.message)); }
  };
  main.append(h("form", { class: "row", onsubmit: run }, q, h("button", { class: "primary", type: "submit" }, "Find")), out);
  q.focus();
}

document.addEventListener("pointerdown", unlockAudio);
// ------------------------------------------------------------------ connect by QR code
function pairingCode() {
  const m = /pair=([A-Z0-9]+)/i.exec(location.hash || "");
  return m ? m[1].toUpperCase() : null;
}
async function pairHere(code) {
  try {
    await api("/api/phones/pair", { method: "POST", body: { code, device: ANDROID ? "Android phone (browser)" : "Phone (browser)" } });
    history.replaceState(null, "", "/guard");
    await start();
  } catch (x) { showLogin(x.message); }
}
async function showConnect(code) {
  let apk = false;
  try { apk = (await fetch("/app/CAMS-Guard.apk", { method: "HEAD" })).ok; } catch {}
  if (!ANDROID || !apk) return pairHere(code);
  app.replaceChildren(h("div", { class: "login" },
    h("h1", {}, "Connect this phone"),
    h("div", { class: "card" },
      h("p", { style: "margin-top:0" }, h("b", {}, "Best: install the CAMS Guard app."), " The phone then rings for fire, smoke or a person down, even when it is locked."),
      h("a", { href: "/app/CAMS-Guard.apk", download: "CAMS-Guard.apk" }, h("button", { class: "primary", style: "width:100%" }, "1. Install the app")),
      h("p", { class: "muted" }, "If the phone asks, allow installing apps from this browser. Then open CAMS Guard and press Scan the code, and point it at the same code on the CAMS computer.")),
    h("button", { style: "width:100%;margin-top:8px", onclick: () => pairHere(code) }, "Or use this page instead")));
}

const code = pairingCode();
if (code) showConnect(code);
else api("/api/status").then((st) => (st.user ? start() : showLogin())).catch(() => showLogin("CAMS is not reachable. Is the CAMS computer on?"));
