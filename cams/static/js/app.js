// CAMS front end: sign-in / first-time setup, the main shell and page routing.
import { logoMark, h, get, post, icon, toast, fail, ICONS, field } from "./util.js";
import { PAGES } from "./pages.js";
import { startTour, tourWanted } from "./tour.js";

const root = document.getElementById("root");
export const state = { status: null, user: null, current: null, alertsSeen: 0 };

const NAV = [
  { id: "overview", label: "Overview", icon: "overview" },
  { id: "live", label: "Live cameras", icon: "live" },
  { id: "find", label: "Find a person", icon: "find" },
  { id: "people", label: "People", icon: "people" },
  { id: "builder", label: "Campus builder", icon: "builder", role: "operator" },
  { id: "cameras", label: "Cameras", icon: "cameras", role: "operator" },
  { id: "alerts", label: "Alerts", icon: "alerts" },
  { id: "settings", label: "Settings", icon: "settings" },
  { id: "guide", label: "How to use CAMS", icon: "guide" },
];
const RANK = { viewer: 0, operator: 1, admin: 2 };
export const can = (role) => RANK[state.user?.role] >= RANK[role];

window.addEventListener("cams:signed-out", () => { if (state.user) boot(); });

async function boot() {
  try { state.status = await get("/api/status"); }
  catch (e) { root.replaceChildren(h("div", { class: "empty" }, h("h3", {}, "CAMS is starting"), e.message)); setTimeout(boot, 2000); return; }
  state.user = state.status.user;
  document.title = `CAMS - ${state.status.site_name}`;
  if (state.status.needs_setup) return renderSetup();
  if (!state.user) return renderLogin();
  renderShell();
}

// ------------------------------------------------------------------ gate screens
function planArt() {
  // decorative site plan: blocks, a path and one amber sighting
  return h("div", { html: `
  <svg class="plan" viewBox="0 0 400 500" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
    <defs><pattern id="g" width="20" height="20" patternUnits="userSpaceOnUse"><path d="M20 0H0V20" fill="none" stroke="rgba(227,236,239,.07)"/></pattern></defs>
    <rect width="400" height="500" fill="url(#g)"/>
    <g fill="rgba(11,122,117,.25)" stroke="#3fb5ad" stroke-width="1.2">
      <rect x="40" y="60" width="120" height="70"/><rect x="200" y="50" width="150" height="50"/>
      <rect x="220" y="130" width="60" height="110"/><polygon points="40,190 150,170 170,260 60,280"/>
      <rect x="300" y="160" width="60" height="60"/>
    </g>
    <rect x="70" y="320" width="260" height="110" fill="none" stroke="#3fb5ad" stroke-dasharray="6 5" stroke-width="1.2"/>
    <polyline points="100,300 190,250 250,270 320,150" fill="none" stroke="#f0b13a" stroke-width="2.5" stroke-dasharray="2 7" stroke-linecap="round"/>
    <circle cx="320" cy="150" r="7" fill="#f0b13a" stroke="#14304a" stroke-width="2"/>
    <circle cx="320" cy="150" r="15" fill="none" stroke="#f0b13a" stroke-width="1.5" opacity=".6"/>
  </svg>`}).firstElementChild;
}

function gate(form, lead) {
  root.replaceChildren(h("div", { class: "gate" },
    h("div", { class: "gate-art" }, planArt(), h("div", { class: "gate-logo" }, logoMark("gate-mark"), h("div", {}, h("h1", {}, "CAMS"), h("small", {}, "Camera AI Management System"))), h("p", {}, lead)),
    h("div", { class: "gate-form" }, form),
  ));
  form.querySelector("input")?.focus();
}

function renderLogin() {
  const err = h("div", { class: "error-text", role: "alert" });
  const form = h("form", {},
    h("h2", {}, `Sign in to ${state.status.site_name}`),
    field("Username", h("input", { name: "username", autocomplete: "username", required: true })),
    field("Password", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    err, h("button", { class: "primary", type: "submit" }, "Sign in"),
    h("p", { class: "hint" }, "Forgot the password? Ask a CAMS admin to set a new one in Settings."),
  );
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    try { await post("/api/login", { username: form.username.value, password: form.password.value }); boot(); }
    catch (ex) { err.textContent = ex.message; }
  });
  gate(form, "Camera AI Management System. Everything stays on this computer.");
}

function renderSetup() {
  let step = 0;
  const vals = { site_name: "", full_name: "", username: "admin", password: "" };
  const form = h("form", {});
  const draw = () => {
    const err = h("div", { class: "error-text", role: "alert" });
    const bar = h("div", { class: "steps-bar", "aria-label": `Step ${step + 1} of 3` }, [0, 1, 2].map((i) => h("i", { class: i <= step ? "on" : "" })));
    if (step === 0) {
      form.replaceChildren(bar, h("h2", {}, "Welcome to CAMS"),
        h("p", { class: "muted" }, "Let's set up this computer. It takes about a minute. All data stays on this PC; no internet is needed."),
        field("Name of your school or company", h("input", { name: "site_name", value: vals.site_name, required: true, placeholder: "e.g. Mikocheni Secondary School" })),
        err, h("button", { class: "primary", type: "submit" }, "Continue"));
    } else if (step === 1) {
      form.replaceChildren(bar, h("h2", {}, "Create the admin account"),
        h("p", { class: "muted" }, "The admin can add users, cameras and people. Keep this password safe."),
        field("Your full name", h("input", { name: "full_name", value: vals.full_name })),
        field("Username", h("input", { name: "username", value: vals.username, required: true, minlength: 3 })),
        field("Password", h("input", { name: "password", type: "password", required: true, minlength: 8, autocomplete: "new-password" }), "At least 8 characters, letters and numbers."),
        field("Type the password again", h("input", { name: "password2", type: "password", required: true, autocomplete: "new-password" })),
        err, h("div", { class: "row" }, h("button", { type: "button", onclick: () => { step = 0; draw(); } }, "Back"), h("button", { class: "primary", type: "submit" }, "Continue")));
    } else {
      form.replaceChildren(bar, h("h2", {}, "Before you start"),
        h("p", {}, "Face recognition processes personal data. Before enrolling anyone:"),
        h("ul", { class: "muted" },
          h("li", {}, "Get written consent (from a parent or guardian for students under 18)."),
          h("li", {}, "Put up signs telling people that cameras with face recognition are in use."),
          h("li", {}, "Only give CAMS accounts to staff who need them."),
        ),
        h("label", { class: "check" }, h("input", { type: "checkbox", name: "agree", required: true }), "I understand and will follow these rules and the data protection law of our country."),
        err, h("div", { class: "row" }, h("button", { type: "button", onclick: () => { step = 1; draw(); } }, "Back"), h("button", { class: "primary", type: "submit" }, "Finish setup")));
    }
    form.onsubmit = async (e) => {
      e.preventDefault();
      if (step === 0) { vals.site_name = form.site_name.value.trim(); step = 1; return draw(); }
      if (step === 1) {
        if (form.password.value !== form.password2.value) { err.textContent = "The two passwords are different."; return; }
        Object.assign(vals, { full_name: form.full_name.value, username: form.username.value.trim(), password: form.password.value });
        step = 2; return draw();
      }
      try { await post("/api/setup", vals); boot(); }
      catch (ex) { err.textContent = ex.message; if (/password/i.test(ex.message)) { step = 1; draw(); } }
    };
    form.querySelector("input")?.focus();
  };
  draw();
  gate(form, "Find anyone on your campus in seconds, using the cameras you already have.");
}

// ------------------------------------------------------------------ shell
let pageCleanup = null;
let alertBadge = null;

function renderShell() {
  const nav = h("nav", { "aria-label": "Main" });
  for (const n of NAV) {
    if (n.role && !can(n.role)) continue;
    const b = h("button", { class: "nav-btn", "data-page": n.id, onclick: () => go(n.id) },
      icon(n.icon), h("span", { class: "lbl" }, n.label));
    if (n.id === "alerts") { alertBadge = h("span", { class: "badge hidden" }, "0"); b.append(alertBadge); }
    nav.append(b);
  }
  const theme = () => document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const themeBtn = h("button", { class: "ghost small", title: "Switch light / dark", onclick: () => {
    const next = theme() === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("cams-theme", next); } catch {}
    themeBtn.replaceChildren(icon(next === "dark" ? "sun" : "moon"));
    if (state.current === "overview" || state.current === "find" || state.current === "builder") route();
  } }, icon(theme() === "dark" ? "sun" : "moon"));

  const rail = h("aside", { class: "rail" },
    h("div", { class: "brand" }, logoMark(),
      h("div", {}, h("b", {}, "CAMS"), h("small", {}, state.status.site_name || "Camera AI Management System"))),
    nav,
    h("div", { class: "rail-foot" },
      h("div", { class: "who" }, state.user.full_name || state.user.username),
      h("div", { class: "faint" }, state.user.role),
      h("div", { class: "row", style: { marginTop: "6px" } },
        h("button", { class: "small", onclick: async () => { await post("/api/logout"); boot(); } }, "Sign out"), themeBtn),
    ),
  );
  const main = h("main", { class: "main", id: "main", tabindex: "-1" });
  root.replaceChildren(h("div", { class: "app" }, rail, main));
  window.onhashchange = route;
  route();
  pollAlerts();
  if (tourWanted(state)) setTimeout(() => startTour(state), 500);
}

export function go(page, arg) {
  location.hash = arg !== undefined ? `#${page}/${encodeURIComponent(arg)}` : `#${page}`;
}

async function route() {
  const [page, arg] = (location.hash.slice(1) || "overview").split("/");
  const def = PAGES[page] || PAGES.overview;
  const id = PAGES[page] ? page : "overview";
  state.current = id;
  document.querySelectorAll(".nav-btn").forEach((b) => b.toggleAttribute("aria-current", false));
  document.querySelector(`.nav-btn[data-page="${id === "person" ? "people" : id}"]`)?.setAttribute("aria-current", "page");
  pageCleanup?.();
  pageCleanup = null;
  const main = document.getElementById("main");
  const page$ = h("div", { class: "page" });
  main.replaceChildren(page$);
  main.scrollTop = 0;
  if (!state.status.models_ok) {
    page$.append(h("div", { class: "banner red" }, "Face recognition is switched off because the AI model files are missing. Reinstall CAMS, or run scripts/download_models.py once."));
  }
  try { pageCleanup = (await def(page$, arg ? decodeURIComponent(arg) : undefined)) || null; }
  catch (e) { fail(e); }
}

async function pollAlerts() {
  if (!state.user) return;
  try {
    const open = await get("/api/alerts?open_only=true&limit=20");
    alertBadge.textContent = open.length >= 20 ? "20+" : String(open.length);
    alertBadge.classList.toggle("hidden", open.length === 0);
    const newest = open[0]?.id || 0;
    if (state.alertsSeen && newest > state.alertsSeen) {
      open.filter((a) => a.id > state.alertsSeen).slice(0, 3).forEach((a) => toast(a.message, "alert"));
    }
    state.alertsSeen = Math.max(state.alertsSeen, newest) || -1;
  } catch { /* signed out or offline: ignore */ }
  setTimeout(pollAlerts, 5000);
}

boot();
