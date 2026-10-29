// Shared helpers: API calls, DOM building, dialogs, toasts, formatting, icons.

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, credentials: "same-origin", headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  let res;
  try { res = await fetch(path, opts); }
  catch { throw new ApiError(0, "CAMS is not responding. Is the program still running?"); }
  const type = res.headers.get("content-type") || "";
  const data = type.includes("json") ? await res.json() : await res.blob();
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/login")) window.dispatchEvent(new Event("cams:signed-out"));
    throw new ApiError(res.status, (data && data.error) || `Request failed (${res.status})`);
  }
  return data;
}

export const get = (p) => api(p);
export const post = (p, body) => api(p, { method: "POST", body });
export const put = (p, body) => api(p, { method: "PUT", body });
export const patch = (p, body) => api(p, { method: "PATCH", body });
export const del = (p) => api(p, { method: "DELETE" });
export const upload = (p, form) => api(p, { method: "POST", form });

// ------------------------------------------------------------- DOM
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "html") el.innerHTML = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export function icon(name) {
  const span = document.createElement("span");
  span.style.display = "contents";
  span.innerHTML = ICONS[name] || "";
  return span.firstElementChild || span;
}

const svg = (d) => `<svg viewBox="0 0 24 24" aria-hidden="true">${d}</svg>`;
export const ICONS = {
  overview: svg('<path d="M3 20h18M5 20V9l7-5 7 5v11"/><path d="M10 20v-5h4v5"/>'),
  live: svg('<rect x="2" y="6" width="14" height="12" rx="2"/><path d="m16 10 6-3v10l-6-3"/>'),
  find: svg('<circle cx="11" cy="10" r="3"/><path d="M11 21s7-5.5 7-11a7 7 0 1 0-14 0c0 5.5 7 11 7 11z"/>'),
  people: svg('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c.8-3.6 3.4-5.5 6.5-5.5s5.7 1.9 6.5 5.5"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14.8c2 .7 3.2 2.4 3.6 5.2"/>'),
  builder: svg('<path d="M3 21h18"/><path d="M5 21V10l5-3v14M10 21V4l9 4v13"/><path d="M13 11h3M13 15h3"/>'),
  cameras: svg('<path d="M3 7h11l3 3v4l-3 3H3z"/><path d="M17 12h4M19 8v8"/>'),
  alerts: svg('<path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4z"/><path d="M10 21h4"/>'),
  settings: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>'),
  guide: svg('<circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.01"/>'),
  report: svg('<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 8h6M9 12h6M9 16h4"/>'),
  activity: svg('<circle cx="13" cy="4.5" r="2"/><path d="m7 21 3-6 3 2v4M13 17l-1-5 4 2 3-1M9 11l2-3h3"/>'),
  search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>'),
  plus: svg('<path d="M12 5v14M5 12h14"/>'),
  select: svg('<path d="m5 3 14 8-6 2-3 6z"/>'),
  polygon: svg('<path d="M4 7 12 3l8 5-2 11H6z"/>'),
  rect: svg('<rect x="4" y="6" width="16" height="12"/>'),
  camera: svg('<circle cx="12" cy="12" r="3"/><path d="M12 12 20 6M12 12l8 6"/>'),
  face: svg('<circle cx="12" cy="11" r="7"/><circle cx="9.5" cy="10" r=".8"/><circle cx="14.5" cy="10" r=".8"/><path d="M9.5 14c1.5 1.2 3.5 1.2 5 0"/>'),
  upload: svg('<path d="M12 16V4M7 9l5-5 5 5M4 20h16"/>'),
  sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
  moon: svg('<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>'),
  recordings: svg('<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="9" cy="12" r="2.5"/><path d="M14 10h4M14 14h4"/>'),
  rec: svg('<circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/>'),
  stop: svg('<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none"/>'),
  play: svg('<path d="M8 5v14l11-7z" fill="currentColor" stroke="none"/>'),
  pause: svg('<path d="M8 5v14M16 5v14" stroke-width="3"/>'),
  download: svg('<path d="M12 4v12M7 11l5 5 5-5M4 20h16"/>'),
  pin: svg('<path d="M12 21s7-6 7-11.5a7 7 0 1 0-14 0C5 15 12 21 12 21z"/><circle cx="12" cy="9.5" r="2.5"/>'),
  globe: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.2 3 14.8 0 18M12 3c-3 3.2-3 14.8 0 18"/>'),
  copy: svg('<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>'),
  star: svg('<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/>'),
  mouse: svg('<rect x="6" y="3" width="12" height="18" rx="6"/><path d="M12 3v6M6 9h12"/>'),
};

export const POSE_ICON = {
  front: svg('<circle cx="12" cy="11" r="7"/><path d="M12 9v4"/>'),
  left: svg('<circle cx="12" cy="11" r="7"/><path d="M9 11H5"/>'),
  right: svg('<circle cx="12" cy="11" r="7"/><path d="M15 11h4"/>'),
  up: svg('<circle cx="12" cy="11" r="7"/><path d="M12 8V4"/>'),
  down: svg('<circle cx="12" cy="11" r="7"/><path d="M12 14v4"/>'),
};

// ------------------------------------------------------------- feedback
export function toast(msg, kind = "") {
  const el = h("div", { class: `toast ${kind}` }, msg);
  document.getElementById("toasts").append(el);
  setTimeout(() => el.remove(), kind === "error" ? 7000 : 4500);
}

export function fail(err) { toast(err?.message || String(err), "error"); }

export function dialog({ title, body, actions = [], wide = false, onClose }) {
  const d = h("dialog", { class: wide ? "wide" : "" });
  const close = () => { d.close(); };
  const foot = h("div", { class: "d-foot" });
  for (const a of actions) {
    const b = h("button", { class: a.class || "", type: a.type || "button" }, a.label);
    b.addEventListener("click", async () => {
      if (!a.run) return close();
      b.disabled = true;
      try { const keep = await a.run(d); if (keep !== true) close(); }
      catch (e) { fail(e); }
      finally { b.disabled = false; }
    });
    foot.append(b);
  }
  d.append(
    h("div", { class: "d-head" }, h("h2", {}, title), h("button", { class: "ghost small", "aria-label": "Close", onclick: close }, "Close")),
    h("div", { class: "d-body" }, body),
    ...(actions.length ? [foot] : []),
  );
  d.addEventListener("close", () => { onClose?.(); d.remove(); });
  document.body.append(d);
  d.showModal();
  return d;
}

export function confirmBox(title, text, okLabel = "Delete", danger = true) {
  return new Promise((resolve) => {
    let ok = false;
    dialog({
      title, body: h("p", {}, text),
      actions: [
        { label: "Cancel" },
        { label: okLabel, class: danger ? "danger solid" : "primary", run: () => { ok = true; } },
      ],
      onClose: () => resolve(ok),
    });
  });
}

export function field(label, input, hint) {
  return h("label", { class: "field" }, h("span", {}, label), input, hint ? h("small", { class: "hint" }, hint) : null);
}

export function formValues(root) {
  const out = {};
  root.querySelectorAll("[name]").forEach((el) => {
    out[el.name] = el.type === "checkbox" ? el.checked : el.value;
  });
  return out;
}

// ------------------------------------------------------------- formatting
export function ago(ts) {
  if (!ts) return "never";
  const s = Date.now() / 1000 - ts;
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.round(s / 86400)} days ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export function clock(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const today = new Date();
  const t = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toDateString() === today.toDateString() ? t : `${d.toLocaleDateString([], { day: "numeric", month: "short" })} ${t}`;
}

export function duration(a, b) {
  const s = Math.max(0, b - a);
  if (s < 60) return `${Math.round(s)} s`;
  if (s < 3600) return `${Math.round(s / 60)} min`;
  return `${(s / 3600).toFixed(1)} h`;
}

export function where(ls) {
  if (!ls) return "Not seen yet";
  return ls.building_name ? `${ls.camera_name}, ${ls.building_name}` : ls.camera_name || "Unknown camera";
}

export const CATEGORIES = ["student", "staff", "visitor", "contractor", "other"];
export const PLURAL = { student: "Students", staff: "Staff", visitor: "Visitors", contractor: "Contractors", other: "Others" };
export const cap = (s) => (s ? s[0].toUpperCase() + s.slice(1) : "");

export function thumb(src, cls = "thumb", alt = "") {
  const img = h("img", { class: cls, alt, loading: "lazy" });
  if (src) { img.src = src; img.onerror = () => { img.removeAttribute("src"); }; }
  return img;
}

export const photoUrl = (p) => (p && p.photo_path ? `/api/people/${p.id ?? p.person_id}/photo` : null);
export const snapUrl = (s) => (s && s.snapshot_path ? `/api/snapshots/${s.snapshot_path}` : null);

// The CAMS logo mark. The C takes the text colour around it, so it shows on light and dark backgrounds.
export function logoMark(cls = "brand-mark") {
  const wrap = document.createElement("span");
  wrap.innerHTML = `<svg class="${cls}" viewBox="0 0 96 96" role="img" aria-label="CAMS logo">
    <g fill="none" stroke="#00998c" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M6 28V13a7 7 0 0 1 7-7h15"/><path d="M68 6h15a7 7 0 0 1 7 7v15"/>
      <path d="M90 68v15a7 7 0 0 1-7 7H68"/><path d="M28 90H13a7 7 0 0 1-7-7V68"/></g>
    <path d="M67.8 31.6A25.75 25.75 0 1 0 67.8 63.4" fill="none" stroke="currentColor" stroke-width="9.5" stroke-linecap="round"/>
    <circle cx="67" cy="47.5" r="6" fill="#00998c"/></svg>`;
  return wrap.firstElementChild;
}

// ------------------------------------------------------------- personal preferences
// map_mouse: "standard" = left drag moves the map, right drag looks around;
//            "swapped"  = right drag moves the map, left drag looks around.
export const prefs = { mouse: "standard" };
export function setPrefs(p) {
  Object.assign(prefs, p);
  window.dispatchEvent(new CustomEvent("cams:prefs", { detail: { ...prefs } }));
}
export const mouseSwapped = () => prefs.mouse === "swapped";

// ------------------------------------------------------------- GPS position on the campus map
// Same maths as cams/geo.py: Web Mercator pixels at zoom 20 around the map centre.
const Z = 20, N = 256 * 2 ** Z;
const mercX = (lng) => ((lng + 180) / 360) * N;
const mercY = (lat) => { const s = Math.sin((lat * Math.PI) / 180); return (0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * N; };
export function toLatLng(map, x, y) {
  const g = map?.geo;
  if (!g || x == null || y == null) return null;
  const mpp = (156543.03392804097 * Math.cos((g.lat * Math.PI) / 180)) / 2 ** Z;
  const px = mercX(g.lng) + (x - map.width_m / 2) / mpp, py = mercY(g.lat) + (y - map.height_m / 2) / mpp;
  const lng = (px / N) * 360 - 180;
  const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * py) / N))) * 180) / Math.PI;
  return { lat, lng };
}
export const fmtLatLng = (p) => (p ? `${p.lat.toFixed(6)}, ${p.lng.toFixed(6)}` : "");

export async function copyText(text, what = "Copied") {
  try { await navigator.clipboard.writeText(text); toast(`${what}: ${text}`); }
  catch {
    const t = h("textarea", { style: { position: "fixed", opacity: 0 } }, text);
    document.body.append(t); t.select();
    try { document.execCommand("copy"); toast(`${what}: ${text}`); } catch { toast(text); }
    t.remove();
  }
}

// A small "GPS: -6.770123, 39.240456 [copy]" line.
export function gpsLine(p, label = "GPS") {
  if (!p || p.lat == null) return null;
  const text = fmtLatLng(p);
  return h("span", { class: "gps" }, icon("pin"), h("span", { class: "num" }, `${label} ${text}`),
    h("button", { class: "ghost small", title: "Copy the position (paste it into Google Maps)", "aria-label": "Copy GPS position",
      onclick: (e) => { e.stopPropagation(); copyText(text, "Position copied"); } }, icon("copy")));
}

// ------------------------------------------------------------- video player
// Recordings are .mp4 files on the CAMS PC. The window shows them by receiving the
// pictures one by one (like the live view), so every Windows PC can play them.
export const fmtTime = (s) => {
  s = Math.max(0, Math.round(s));
  const hh = Math.floor(s / 3600), mm = Math.floor((s % 3600) / 60), ss = s % 60;
  return hh ? `${hh}:${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}` : `${mm}:${String(ss).padStart(2, "0")}`;
};
export const fmtSize = (b) => (b > 1e9 ? `${(b / 1e9).toFixed(1)} GB` : b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1e3))} KB`);

export function videoPlayer(rec, { autoplay = true, loop = false } = {}) {
  const dur = Math.max(0.1, rec.duration || rec.end_ts - rec.start_ts);
  let pos = 0, playing = false, t0 = 0, p0 = 0, speed = 1, timer = null;
  const img = h("img", { alt: `Video from ${rec.camera_name}` });
  const bar = h("input", { type: "range", min: 0, max: dur, step: 0.1, value: 0, "aria-label": "Position in the video" });
  const playBtn = h("button", { class: "small", "aria-label": "Play" }, icon("play"));
  const tLabel = h("span", { class: "num p-time" });
  const clockLabel = h("span", { class: "num p-clock" });
  const sp = h("select", { "aria-label": "Speed" }, [0.5, 1, 2, 4, 8].map((v) => h("option", { value: v, selected: v === 1 }, `${v}x`)));
  const now = () => (playing ? Math.min(dur, p0 + ((performance.now() - t0) / 1000) * speed) : pos);
  const show = () => {
    const p = now();
    bar.value = p;
    tLabel.textContent = `${fmtTime(p)} / ${fmtTime(dur)}`;
    clockLabel.textContent = new Date((rec.start_ts + p) * 1000).toLocaleTimeString();
  };
  const still = () => { img.src = `/api/recordings/${rec.id}/frame.jpg?t=${pos.toFixed(2)}`; };
  function play() {
    if (pos >= dur - 0.2) pos = 0;
    playing = true; p0 = pos; t0 = performance.now();
    img.src = `/api/recordings/${rec.id}/play?start=${pos.toFixed(2)}&speed=${speed}&_=${Date.now()}`;
    playBtn.replaceChildren(icon("pause")); playBtn.setAttribute("aria-label", "Pause");
    clearInterval(timer);
    timer = setInterval(() => {
      show();
      if (now() >= dur) { pos = dur; pause(); if (loop) play(); }
    }, 200);
  }
  function pause() {
    pos = now(); playing = false; clearInterval(timer);
    playBtn.replaceChildren(icon("play")); playBtn.setAttribute("aria-label", "Play");
    still(); show();
  }
  playBtn.onclick = () => (playing ? pause() : play());
  bar.oninput = () => { const was = playing; if (was) { playing = false; clearInterval(timer); } pos = +bar.value; show(); if (was) play(); else still(); };
  sp.onchange = () => { speed = +sp.value; if (playing) { pos = now(); play(); } };
  const ext = rec.ext || ".mp4";
  const el = h("div", { class: "player" },
    h("div", { class: "p-screen", onclick: () => playBtn.click() }, img),
    h("div", { class: "p-bar" }, playBtn, bar, tLabel, clockLabel, sp,
      h("a", { class: "btn small", href: `/api/recordings/${rec.id}/download`, download: `${rec.camera_name || "camera"}${ext}`, title: "Save this video to the Downloads folder" }, icon("download"), "Download")));
  el.stop = () => { clearInterval(timer); playing = false; img.removeAttribute("src"); };
  show();
  if (autoplay) play(); else still();
  return el;
}

export function playDialog(rec, title) {
  const p = videoPlayer(rec);
  dialog({ title: title || `${rec.camera_name}, ${clock(rec.start_ts)}`, wide: true, body: p, onClose: () => p.stop() });
}
