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
    actions.length ? foot : null,
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
