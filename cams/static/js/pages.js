// All CAMS pages. Each page function fills `el` and may return a cleanup function.
import {
  h, get, post, put, patch, del, upload, icon, toast, fail, dialog, confirmBox, field, formValues,
  ago, clock, duration, where, CATEGORIES, PLURAL, cap, thumb, photoUrl, snapUrl, POSE_ICON,
  gpsLine, playDialog, videoPlayer, fmtTime, fmtSize, setPrefs, prefs, copyText, fmtLatLng,
} from "./util.js";
import { MapView } from "./mapview.js";
import { trailFromSightings, centroid } from "./map2d.js";
import { openEnrol, POSES, POSE_LABEL } from "./enrol.js";
import { state, can, go } from "./app.js";
import { startTour, GUIDE } from "./tour.js";
import { personDayPanel, report, activityPage, refreshActivityStatus } from "./activity.js";

function head(title, sub, ...actions) {
  return h("div", { class: "page-head" },
    h("div", { class: "grow" }, h("h1", {}, title), sub ? h("p", {}, sub) : null), ...actions);
}

function emptyState(title, text, action) {
  return h("div", { class: "empty" }, h("h3", {}, title), h("p", { style: { margin: "0 auto 12px" } }, text), action || null);
}

function anglesBadge(angles) {
  const set = new Set((angles || "").split(",").filter(Boolean));
  return h("span", { class: "angles", title: set.size ? `${set.size} of 9 views: ${[...set].map((a) => POSE_LABEL[a] || a).join(", ")}` : "No face captured" },
    POSES.map((p) => h("i", { class: set.has(p.id) ? "on" : "" })));
}

function pinFor(ls, label, extra = {}) {
  return ls && ls.map_x != null ? { x: ls.map_x, y: ls.map_y, label, ...extra } : null;
}

// ======================================================================= overview
async function overview(el) {
  const figs = h("div", { class: "figures" });
  const feed = h("ul", { class: "feed" });
  const mapBox = h("div");
  el.append(
    head("Overview", `Live picture of ${state.status.site_name}. Amber pins show where people were seen in the last hour.`,
      h("button", { class: "primary", onclick: () => go("find") }, icon("find"), "Find a person")),
    figs,
    h("div", { class: "split" },
      mapBox,
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Latest sightings"),
        h("button", { class: "small", onclick: () => go("find") }, "Search")), feed),
    ),
  );
  const map = new MapView(mapBox, { height: "tall" });
  await map.load();

  const figure = (n, label, cls = "") => h("div", { class: `figure ${cls}` }, h("span", { class: "num" }, n), h("span", {}, label));
  async function refresh() {
    const d = await get("/api/dashboard");
    figs.replaceChildren(
      figure(d.people_today, "people seen today"),
      figure(d.sightings_today, "sightings today"),
      figure(`${d.cameras_online}/${d.cameras}`, "cameras online", d.cameras && d.cameras_online < d.cameras ? "alerting" : ""),
      figure(d.enrolled, `of ${d.people} people enrolled`),
      figure(d.open_alerts, "open alerts", d.open_alerts ? "alerting" : ""),
    );
    if (!d.recent.length) {
      feed.replaceChildren(h("li", { style: { display: "block" } }, emptyState("No sightings yet",
        d.cameras ? (d.enrolled ? "When an enrolled person walks past a camera, they appear here." : "Enrol people's faces so cameras can recognise them.")
          : "Add your first camera to start.",
        h("button", { onclick: () => go(d.cameras ? "people" : "cameras") }, d.cameras ? "Go to People" : "Add a camera"))));
    } else {
      feed.replaceChildren(...d.recent.map((s) => h("li", { style: { cursor: s.person_id ? "pointer" : "" }, onclick: () => s.person_id && go("find", s.person_id) },
        thumb(snapUrl(s)),
        h("div", {}, h("div", { class: "who" }, s.full_name || "Unknown person"), h("div", { class: "where" }, s.camera_name, s.group_name ? `, ${s.group_name}` : "")),
        h("time", {}, clock(s.last_seen)))));
    }
    // pins: latest place of each person seen in the last hour
    const since = Date.now() / 1000 - 3600;
    const recent = await get(`/api/sightings?since=${since}&limit=400`);
    const cams = Object.fromEntries(map.data.cameras.map((c) => [c.id, c]));
    const latest = new Map();
    for (const s of recent) if (s.person_id && !latest.has(s.person_id)) latest.set(s.person_id, s);
    const pins = [];
    for (const s of latest.values()) {
      const c = cams[s.camera_id];
      if (c && c.map_x != null) pins.push({ x: c.map_x + (Math.random() - 0.5) * 3, y: c.map_y + (Math.random() - 0.5) * 3, small: true });
    }
    map.setMarks({ pins });
  }
  await refresh();
  const t = setInterval(() => refresh().catch(() => {}), 6000);
  return () => { clearInterval(t); map.destroy(); };
}

// ======================================================================= live
async function live(el) {
  let size = localStorage.getItem("cams-grid") || "auto";
  const grid = h("div", { class: `cam-grid size-${size}` });
  const seg = h("div", { class: "seg", role: "group", "aria-label": "Tile size" },
    [["auto", "Grid"], ["2", "2 across"], ["1", "Large"]].map(([v, l]) => h("button", { "aria-pressed": String(v === size), onclick: (e) => {
      size = v; try { localStorage.setItem("cams-grid", v); } catch {}
      grid.className = `cam-grid size-${v}`;
      seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget)));
    } }, l)));
  el.append(head("Live cameras", "Green box: recognised. Red: not enrolled (face blurred). Orange: on the watch list. Press Record to save a camera's video.", seg,
    h("button", { onclick: () => go("recordings") }, icon("recordings"), "Recordings")), grid);
  const cams = (await get("/api/cameras")).filter((c) => c.enabled);
  if (!cams.length) {
    grid.replaceWith(h("div", { class: "panel" }, emptyState("No cameras yet", "Add an IP, USB or Ethernet camera to see it here.",
      can("operator") ? h("button", { class: "primary", onclick: () => go("cameras") }, "Add a camera") : null)));
    return;
  }
  const caps = new Map();
  for (const c of cams) {
    const img = h("img", { alt: `Live picture from ${c.name}`, src: `/api/cameras/${c.id}/stream?fps=8` });
    const dot = h("span", { class: `dot ${c.live.status}` });
    const meta = h("span", { class: "num" }, "");
    const off = h("div", { class: "cam-off hidden" });
    const recBadge = h("span", { class: "rec-badge hidden" }, icon("rec"), h("span", { class: "num" }, "REC"));
    const colourTag = h("span", { class: "tag violet hidden", title: "This black-and-white camera is coloured by the AI. The colours are a guess." }, "AI colour");
    const recBtn = can("operator") ? h("button", { class: "small rec-btn", title: "Record this camera", onclick: async (e) => {
      e.stopPropagation();
      const on = recBtn.dataset.on === "1";
      recBtn.disabled = true;
      try {
        await post(`/api/cameras/${c.id}/record`, { action: on ? "stop" : "start" });
        toast(on ? `Recording of ${c.name} saved. Find it under Recordings.` : `Recording ${c.name}...`);
        await refresh();
      } catch (ex) { fail(ex); }
      recBtn.disabled = false;
    } }, icon("rec"), "Record") : null;
    caps.set(c.id, { dot, meta, off, img, recBadge, recBtn, colourTag });
    grid.append(h("div", { class: "cam-tile", ondblclick: () => img.requestFullscreen?.() }, img, off, recBadge,
      h("div", { class: "cam-cap" }, dot, h("b", {}, c.name), colourTag, meta, recBtn)));
  }
  async function refresh() {
    for (const c of await get("/api/cameras")) {
      const t = caps.get(c.id);
      if (!t) continue;
      t.colourTag.classList.toggle("hidden", !c.live.colour);
      const rec = c.recording || {};
      const since = rec.manual || rec.continuous;
      t.recBadge.classList.toggle("hidden", !since);
      if (since) t.recBadge.lastChild.textContent = `REC ${fmtTime(Date.now() / 1000 - since)}${rec.manual ? "" : " (all the time)"}`;
      if (t.recBtn) {
        t.recBtn.dataset.on = rec.manual ? "1" : "0";
        t.recBtn.classList.toggle("danger", !!rec.manual);
        t.recBtn.replaceChildren(icon(rec.manual ? "stop" : "rec"), rec.manual ? "Stop" : "Record");
      }
      t.dot.className = `dot ${c.live.status}`;
      t.meta.textContent = c.live.status === "online" ? `${c.live.faces || 0} face${c.live.faces === 1 ? "" : "s"}` : c.live.status;
      t.off.textContent = c.live.status === "offline" ? c.live.error : "";
      t.off.classList.toggle("hidden", c.live.status !== "offline");
    }
  }
  refresh();
  const timer = setInterval(() => refresh().catch(() => {}), 2000);
  return () => { clearInterval(timer); caps.forEach((t) => t.img.removeAttribute("src")); };
}

// ======================================================================= find
async function find(el, pid) {
  const input = h("input", { type: "search", placeholder: "Name or ID number, e.g. Asha or S1024", "aria-label": "Search by name or ID", autocomplete: "off" });
  const photoIn = h("input", { type: "file", accept: "image/*", class: "hidden" });
  const results = h("div", { class: "panel hidden" });
  const detail = h("div");
  el.append(
    head("Find a person", "Where was someone last seen? Search by name or ID, or use a photo."),
    h("form", { class: "bigask", onsubmit: (e) => { e.preventDefault(); search(); } },
      h("div", { class: "search" }, icon("search"), input),
      h("div", { class: "row" }, h("button", { class: "primary", type: "submit" }, "Search"),
        h("button", { type: "button", onclick: () => photoIn.click() }, icon("face"), "Search by photo"), photoIn)),
    h("div", { style: { height: "14px" } }), results, detail,
  );
  let cleanup = null;

  function resultRow(p, extra) {
    const ls = p.last_seen;
    return h("div", { class: "result", tabindex: 0, onclick: () => go("find", p.id), onkeydown: (e) => e.key === "Enter" && go("find", p.id) },
      thumb(photoUrl(p), "thumb lg"),
      h("div", {}, h("h3", {}, p.full_name), h("div", { class: "muted" }, [p.person_code, p.group_name, cap(p.category)].filter(Boolean).join(", ")), extra || null),
      h("div", { class: "seen", style: { textAlign: "right" } }, ls ? [h("strong", {}, ago(ls.last_seen)), h("div", { class: "muted" }, where(ls))] : h("span", { class: "faint" }, "Not seen yet")));
  }

  async function search() {
    const q = input.value.trim();
    if (q.length < 2) { input.focus(); return; }
    try {
      const rows = await get(`/api/search/last-seen?q=${encodeURIComponent(q)}`);
      results.classList.remove("hidden");
      results.replaceChildren(rows.length ? h("div", {}, rows.map((p) => resultRow(p))) :
        emptyState("Nobody found", `No one called "${q}" is in CAMS. Check the spelling or search by ID.`));
      if (rows.length === 1) go("find", rows[0].id);
    } catch (e) { fail(e); }
  }

  photoIn.addEventListener("change", async () => {
    const f = photoIn.files[0];
    if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await upload("/api/search/photo", fd);
      results.classList.remove("hidden");
      const matches = r.results.filter((x) => x.is_match);
      results.replaceChildren(
        h("div", { class: "panel-head" }, h("h2", {}, matches.length ? "Possible matches" : "No confident match"),
          h("span", { class: "hint" }, "Always check the photo yourself before acting.")),
        h("div", {}, (matches.length ? matches : r.results.slice(0, 3)).map((p) => resultRow(p,
          h("span", { class: `tag ${p.is_match ? "teal" : ""}` }, `${Math.round(p.similarity * 100)}% similar`)))),
      );
    } catch (e) { fail(e); }
    photoIn.value = "";
  });

  async function showPerson(id) {
    cleanup?.();
    detail.replaceChildren();
    const p = await get(`/api/people/${id}`);
    results.classList.add("hidden");
    const ls = p.last_seen;
    const rangeSel = h("select", { "aria-label": "Time range" },
      [["today", "Today"], ["86400", "Last 24 hours"], ["604800", "Last 7 days"], ["2592000", "Last 30 days"]].map(([v, l]) => h("option", { value: v }, l)));
    const tl = h("ul", { class: "timeline route-list" });
    const summary = h("p", { class: "route-summary" });
    const mapBox = h("div");
    const first = p.full_name.split(" ")[0];
    detail.append(
      h("div", { class: "panel", style: { marginBottom: "16px" } }, h("div", { class: "panel-body person-head" },
        thumb(photoUrl(p), "thumb xl"),
        h("div", { style: { flex: 1 } },
          h("h2", {}, p.full_name),
          h("div", { class: "muted" }, [p.person_code, p.group_name, cap(p.category)].filter(Boolean).join(", ")),
          p.alert_on_sight ? h("span", { class: "tag amber" }, "On watch list") : null,
          h("p", { style: { marginTop: "10px", fontSize: "16px" } }, ls
            ? [h("strong", { class: "num" }, `Last seen ${ago(ls.last_seen)}`), ` at ${where(ls)} (${clock(ls.last_seen)})`]
            : "Not seen by any camera yet."),
          ls ? gpsLine(ls, "Exact place:") : null,
        ),
        h("div", { class: "stack" }, ls?.snapshot_path ? thumb(snapUrl(ls), "thumb xl", "Last sighting") : null,
          ls?.clip_id ? h("button", { class: "small", onclick: () => watch(ls, p.full_name) }, icon("play"), "Watch") : null,
          can("operator") ? h("button", { class: "small", onclick: () => go("person", p.id) }, "Edit person") : null),
      )),
      h("div", { class: "split" }, mapBox,
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Route"), rangeSel),
          h("div", { class: "panel-body" }, summary, tl))),
    );
    const map = new MapView(mapBox, { height: "mid", mapOpts: { onStop: (st, i) => { markItem(i); if (st.clip) watch(st.rows[0], p.full_name, st); } } });
    await map.load();
    let stops = [], items = [], lastKey = "";

    function markItem(i) {
      items.forEach((li, k) => li.classList.toggle("sel", k === i));
      items[i]?.scrollIntoView({ block: "nearest" });
    }

    async function loadTimeline(auto = false) {
      let since;
      if (rangeSel.value === "today") { const d = new Date(); d.setHours(0, 0, 0, 0); since = d.getTime() / 1000; }
      else since = Date.now() / 1000 - Number(rangeSel.value);
      const rows = await get(`/api/people/${id}/timeline?since=${since}`);
      const key = rows.map((r) => `${r.id}:${r.last_seen}:${r.clip_id}`).join("|");
      if (auto && key === lastKey) return;          // nothing new: keep the user's selection
      lastKey = key;
      stops = routeStops(rows, map);
      const placed = stops.filter((s) => s.x != null);
      const names = [];
      for (const st of stops) if (names[names.length - 1] !== st.label) names.push(st.label);
      summary.replaceChildren(...(stops.length ? [
        h("span", { class: "muted" }, stops.length === 1 ? "Seen at " : `${first} went from `),
        ...names.flatMap((n, i) => [...(i ? [h("span", { class: "arrow", "aria-label": "then" }, " → ")] : []), h("b", {}, n)]),
      ] : [h("span", { class: "muted" }, "No sightings in this period.")]));
      items = stops.map((st, i) => {
        const li = h("li", { tabindex: 0, onclick: () => pick(i), onkeydown: (e) => e.key === "Enter" && pick(i) },
          h("span", { class: `stop-badge${i === stops.length - 1 ? " last" : i === 0 ? " first" : ""}` }, st.n),
          h("div", { class: "grow" },
            h("div", { class: "when" }, clock(st.from), st.to - st.from > 30 ? ` to ${clock(st.to)}` : ""),
            h("div", {}, h("b", {}, st.label), st.label !== st.camera ? h("span", { class: "muted" }, `, ${st.camera}`) : null),
            h("div", { class: "hint" }, `${duration(st.from, st.to)}${st.rows.length > 1 ? `, seen ${st.rows.length} times` : ""}, ${Math.round(st.confidence * 100)}% match`),
            st.lat != null ? gpsLine(st) : null),
          h("div", { class: "stop-media" },
            st.thumb ? thumb(st.thumb, "thumb", `${p.full_name} at ${st.label}`) : null,
            st.clip ? h("button", { class: "small", onclick: (e) => { e.stopPropagation(); watch(st.rows.find((r) => r.clip_id) || st.rows[0], p.full_name, st); } }, icon("play"), "Watch") : null));
        return li;
      });
      tl.replaceChildren(...(items.length ? [...items].reverse() : [h("li", {}, h("span", { class: "muted" }, "No sightings in this period."))]));
      map.setRoute(placed);
      if (!auto) {
        const last = placed[placed.length - 1];
        if (last && map.mode === "2d") {
          if (placed.length > 1) {
            const xs = placed.map((s) => s.x), ys = placed.map((s) => s.y);
            const span = Math.max(60, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)) * 1.4;
            map.map2d.focus((Math.max(...xs) + Math.min(...xs)) / 2, (Math.max(...ys) + Math.min(...ys)) / 2, span);
          } else map.map2d.focus(last.x, last.y, 90);
        }
      }
    }

    function pick(i) {
      markItem(i);
      const st = stops[i];
      const k = map.route.indexOf(st);
      if (k >= 0) { map.selectStop(k); if (map.mode === "2d") map.map2d.focus(st.x, st.y, 70); }
    }

    rangeSel.addEventListener("change", () => loadTimeline().catch(fail));
    await loadTimeline();
    const t = setInterval(() => loadTimeline(true).catch(() => {}), 10000);
    cleanup = () => { clearInterval(t); map.destroy(); };
  }

  if (pid) await showPerson(Number(pid));
  else input.focus();
  return () => cleanup?.();
}

// ======================================================================= people
// Group a person's sightings (newest first) into the stops of their route, oldest first.
// Sightings in a row on the same camera are one stop.
function routeStops(rows, map) {
  const stops = [];
  for (const r of rows.slice().reverse()) {
    const prev = stops[stops.length - 1];
    if (prev && prev.camera_id === r.camera_id) {
      prev.to = Math.max(prev.to, r.last_seen);
      prev.rows.push(r);
      prev.confidence = Math.max(prev.confidence, r.confidence);
      if (!prev.clip && r.clip_id) prev.clip = r.clip_id;
      if (r.snapshot_path) prev.thumb = snapUrl(r);
      continue;
    }
    const ll = r.lat != null ? { lat: r.lat, lng: r.lng } : map.latLng(r.map_x, r.map_y);
    stops.push({
      camera_id: r.camera_id, x: r.map_x ?? null, y: r.map_y ?? null,
      from: r.first_seen, to: r.last_seen, label: r.building_name || r.camera_name, camera: r.camera_name,
      rows: [r], thumb: snapUrl(r), clip: r.clip_id || null, confidence: r.confidence, sub: "",
      lat: ll?.lat ?? null, lng: ll?.lng ?? null,
    });
  }
  stops.forEach((st, i) => { st.n = i + 1; st.sub = clock(st.from); });
  return stops;
}

async function watch(sighting, name, stop) {
  try {
    const rec = await get(`/api/sightings/${sighting.id}/clip`);
    const place = stop ? stop.label : where(sighting);
    playDialog(rec, `${name} at ${place}, ${clock(sighting.first_seen)}`);
  } catch (e) { fail(e); }
}

function personForm(p = {}) {
  const groups = h("datalist", { id: "groups-list" });
  get("/api/people/groups").then((g) => groups.replaceChildren(...g.map((x) => h("option", { value: x })))).catch(() => {});
  return h("div", { class: "stack" },
    h("div", { class: "grid2" },
      field("Full name", h("input", { name: "full_name", value: p.full_name || "", required: true })),
      field("ID number", h("input", { name: "person_code", value: p.person_code || "", placeholder: "Admission or staff number" })),
      field("Type", h("select", { name: "category" }, CATEGORIES.map((c) => h("option", { value: c, selected: c === (p.category || "student") }, cap(c))))),
      field("Class or department", h("input", { name: "group_name", value: p.group_name || "", list: "groups-list", placeholder: "e.g. Form 5 PCM" })),
    ), groups,
    field("Notes", h("textarea", { name: "notes", rows: 2 }, p.notes || "")),
    h("fieldset", { class: "panel", style: { padding: "12px" } },
      h("legend", { style: { padding: "0 6px", fontWeight: 600 } }, "Consent"),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "consent_given", checked: !!p.consent_given }), "Written consent for face recognition has been given"),
      h("div", { class: "grid2", style: { marginTop: "8px" } },
        field("Given by", h("input", { name: "consent_by", value: p.consent_by || "", placeholder: "Person or parent/guardian name" })),
        field("Date", h("input", { name: "consent_date", type: "date", value: p.consent_date || "" }))),
    ),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "alert_on_sight", checked: !!p.alert_on_sight }), "Watch list: alert me whenever a camera sees this person"),
    p.id ? h("label", { class: "check" }, h("input", { type: "checkbox", name: "active", checked: p.active !== 0 }), "Active (untick when someone leaves; they will no longer be recognised)") : null,
  );
}

function personBody(v) {
  return { ...v, active: v.active === undefined ? true : v.active };
}

export function addPersonDialog(after) {
  const form = personForm();
  dialog({
    title: "Add a person", body: form,
    actions: [{ label: "Cancel" }, { label: "Save and capture face", class: "primary", run: async () => {
      const v = formValues(form);
      if (!v.full_name.trim()) { toast("Enter the full name.", "error"); return true; }
      const { id } = await post("/api/people", personBody(v));
      after?.();
      openEnrol({ id, full_name: v.full_name }, after);
    } }],
  });
}

async function people(el) {
  const q = h("input", { type: "search", placeholder: "Search name, ID or class", "aria-label": "Search people" });
  const catSel = h("select", { "aria-label": "Type" }, h("option", { value: "" }, "Everyone"), CATEGORIES.map((c) => h("option", { value: c }, PLURAL[c])));
  const groupSel = h("select", { "aria-label": "Class or department" }, h("option", { value: "" }, "All classes"));
  const csvIn = h("input", { type: "file", accept: ".csv,text/csv", class: "hidden" });
  const body = h("tbody");
  const count = h("span", { class: "muted" });
  el.append(
    head("People", "Students, staff and visitors CAMS can recognise.", count,
      can("operator") ? h("button", { onclick: () => csvIn.click(), title: "CSV with columns full_name, person_code, category, group_name" }, icon("upload"), "Import list") : null, csvIn,
      can("operator") ? h("button", { class: "primary", id: "add-person", onclick: () => addPersonDialog(load) }, icon("plus"), "Add person") : null),
    h("div", { class: "row", style: { marginBottom: "12px" } }, h("div", { class: "search", style: { flex: "1 1 260px" } }, icon("search"), q), catSel, groupSel),
    h("div", { class: "panel", style: { overflowX: "auto" } }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["", "Name", "ID", "Class / department", "Type", "360° views", "Consent", "Last seen"].map((t) => h("th", {}, t)))), body)),
  );
  get("/api/people/groups").then((g) => groupSel.append(...g.map((x) => h("option", { value: x }, x))));
  let timer;
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(load, 250); });
  catSel.addEventListener("change", load);
  groupSel.addEventListener("change", load);
  csvIn.addEventListener("change", async () => {
    const fd = new FormData(); fd.append("file", csvIn.files[0]);
    try { const r = await upload("/api/people/import", fd); toast(`${r.added} people imported. Now capture their faces.`); load(); }
    catch (e) { fail(e); }
    csvIn.value = "";
  });
  async function load() {
    const rows = await get(`/api/people?q=${encodeURIComponent(q.value)}&category=${catSel.value}&group=${encodeURIComponent(groupSel.value)}`);
    count.textContent = `${rows.length} ${rows.length === 1 ? "person" : "people"}`;
    if (!rows.length) {
      body.replaceChildren(h("tr", {}, h("td", { colspan: 8 }, emptyState(q.value ? "No matches" : "No people yet",
        q.value ? "Try another name or clear the filters." : "Add people one by one, or import your class list as a CSV file."))));
      return;
    }
    body.replaceChildren(...rows.map((p) => h("tr", { class: "clickable", onclick: () => go(can("operator") ? "person" : "find", p.id) },
      h("td", {}, thumb(photoUrl(p))),
      h("td", {}, h("b", {}, p.full_name), !p.active ? h("span", { class: "tag", style: { marginLeft: "6px" } }, "Inactive") : null,
        p.alert_on_sight ? h("span", { class: "tag amber", style: { marginLeft: "6px" } }, "Watch") : null),
      h("td", {}, p.person_code), h("td", {}, p.group_name), h("td", {}, cap(p.category)),
      h("td", {}, p.samples ? anglesBadge(p.angles) : h("span", { class: "tag red" }, "No face")),
      h("td", {}, p.consent_given ? h("span", { class: "tag teal" }, "Yes") : h("span", { class: "tag" }, "Missing")),
      h("td", { class: "muted" }, ago(p.last_seen)),
    )));
  }
  await load();
}

async function person(el, id) {
  const p = await get(`/api/people/${id}`);
  const form = personForm(p);
  const samples = h("div", { class: "samples" });
  el.append(
    head(p.full_name, [p.person_code, p.group_name].filter(Boolean).join(", "),
      h("button", { onclick: () => go("find", p.id) }, icon("find"), "Where is this person?"),
      can("admin") ? h("button", { class: "danger", onclick: async () => {
        if (await confirmBox("Delete this person?", `This permanently removes ${p.full_name}, their face pictures and every sighting. Use this when someone asks for their data to be erased.`)) {
          try { await del(`/api/people/${p.id}`); toast("Person and their data deleted"); go("people"); } catch (e) { fail(e); }
        }
      } }, "Delete person and data") : null),
    h("div", { class: "split" },
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Details")),
        h("div", { class: "panel-body" }, form, h("div", { class: "row end", style: { marginTop: "14px" } },
          h("button", { class: "primary", onclick: async () => {
            try { await put(`/api/people/${p.id}`, personBody(formValues(form))); toast("Saved"); } catch (e) { fail(e); }
          } }, "Save changes")))),
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Face pictures"),
        h("button", { class: "primary small", onclick: () => openEnrol(p, loadSamples) }, icon("face"), "Capture face")),
        h("div", { class: "panel-body" }, samples,
          h("p", { class: "hint", style: { marginTop: "10px" } }, "Capture all nine 360° views for the best results: seven face views for recognition, plus back and top for guards to compare. Delete blurry or wrong pictures."))),
    ),
    personDayPanel(p),
  );
  async function loadSamples() {
    const fresh = await get(`/api/people/${id}`);
    if (!fresh.samples.length && !fresh.references.length) {
      samples.replaceChildren(h("p", { class: "muted" }, "No face captured yet. Press Capture face."));
      return;
    }
    const tile = (src, angle, delUrl, ref) => h("div", { class: "sample", title: ref ? "Reference picture (not used for recognition)" : "Used for recognition" },
      h("img", { src, alt: `${POSE_LABEL[angle] || angle} view` }),
      h("span", {}, (POSE_LABEL[angle] || angle) + (ref ? " (ref)" : "")),
      h("button", { "aria-label": `Delete ${angle} picture`, onclick: async () => {
        try { await del(delUrl); loadSamples(); } catch (e) { fail(e); }
      } }, "x"));
    const order = (a) => POSES.findIndex((p) => p.id === a.angle);
    samples.replaceChildren(
      ...fresh.samples.slice().sort((a, b) => order(a) - order(b)).map((s) => tile(`/api/samples/${s.id}/image`, s.angle, `/api/samples/${s.id}`, false)),
      ...fresh.references.map((r) => tile(`/api/references/${r.id}/image`, r.angle, `/api/references/${r.id}`, true)));
  }
  await loadSamples();
}

// ======================================================================= cameras
function cameraDialog(cam, after) {
  const isNew = !cam;
  cam = cam || { name: "", source: "", restricted: 0, enabled: 1 };
  const templates = get("/api/cameras/templates");
  const src = h("input", { name: "source", value: cam.source_display || cam.source || "", required: true, placeholder: "rtsp://admin:password@192.168.1.64:554/Streaming/Channels/101" });
  const preview = h("div", { class: "hint" });
  const brand = h("select", { "aria-label": "Brand" }, h("option", { value: "" }, "Choose brand..."));
  const ip = h("input", { placeholder: "192.168.1.64", "aria-label": "IP address" });
  const user = h("input", { value: "admin", "aria-label": "Username" });
  const pass = h("input", { type: "password", "aria-label": "Camera password" });
  const chan = h("input", { type: "number", value: 1, min: 1, "aria-label": "Channel" });
  templates.then((t) => brand.append(...Object.keys(t).map((k) => h("option", { value: k }, k))));
  const fill = async () => {
    const t = (await templates)[brand.value];
    if (!t || !ip.value) return;
    src.value = t.replace("{user}", encodeURIComponent(user.value)).replace("{password}", encodeURIComponent(pass.value))
      .replace("{ip}", ip.value.trim()).replaceAll("{channel}", chan.value || 1);
  };
  [brand, ip, user, pass, chan].forEach((x) => x.addEventListener("input", fill));
  const body = h("div", { class: "stack" },
    field("Camera name", h("input", { name: "name", value: cam.name, required: true, placeholder: "e.g. Main gate" })),
    h("details", { open: isNew },
      h("summary", {}, "Help me build the address"),
      h("div", { class: "stack", style: { marginTop: "10px" } },
        h("div", { class: "grid2" }, field("Brand", brand), field("IP address", ip), field("Username", user), field("Password", pass), field("Channel (for NVR / DVR)", chan)),
        h("p", { class: "hint" }, "USB webcam: type 0 (or 1, 2 for more webcams). Phone with IP Webcam app: http://phone-ip:8080/video"))),
    field("Camera address", src, "RTSP (IP, Ethernet, PoE and NVR cameras), HTTP, a USB number, or a video file path."),
    h("div", { class: "row" }, h("button", { type: "button", onclick: async (e) => {
      e.currentTarget.disabled = true;
      preview.replaceChildren("Connecting...");
      try {
        const r = await post("/api/cameras/test", { source: src.value.includes("****") ? cam.source : src.value });
        preview.replaceChildren(r.ok ? h("div", {}, h("p", { style: { color: "var(--green)" } }, `Connected: ${r.width} x ${r.height}`), h("img", { src: r.preview, alt: "Test picture", style: { maxHeight: "180px", borderRadius: "6px" } }))
          : h("p", { style: { color: "var(--red)" } }, r.error));
      } catch (ex) { preview.replaceChildren(ex.message); }
      e.currentTarget.disabled = false;
    } }, "Test connection")), preview,
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "enabled", checked: cam.enabled !== 0 }), "Camera is on"),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "restricted", checked: !!cam.restricted }),
      "Restricted area: alert me when someone who is not enrolled appears"),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "record_always", checked: cam.record_mode === "always" }),
      "Record this camera all the time (kept for the days set in Settings, then deleted)"),
    field("Colour for black-and-white video", h("select", { name: "colour_mode" },
      [["off", "Off: show the picture as the camera sends it"],
       ["auto", "Automatic: colour it when the camera turns black and white (night / infrared)"],
       ["always", "Always colour this camera (an old black-and-white camera)"]].map(([v, l]) => h("option", { value: v, selected: (cam.colour_mode || "off") === v }, l))),
      "The colour AI guesses the colours. Never trust the colour of clothes or cars in AI-coloured video. Set it up in Settings > Video."),
  );
  dialog({
    title: isNew ? "Add a camera" : `Edit ${cam.name}`, body,
    actions: [{ label: "Cancel" }, { label: isNew ? "Add camera" : "Save", class: "primary", run: async () => {
      const v = formValues(body);
      const payload = { ...cam, name: v.name, source: v.source, enabled: v.enabled, restricted: v.restricted, kind: null,
        record_mode: v.record_always ? "always" : "off", colour_mode: v.colour_mode };
      delete payload.live; delete payload.source_display; delete payload.recording;
      if (isNew) await post("/api/cameras", payload); else await put(`/api/cameras/${cam.id}`, payload);
      toast(isNew ? "Camera added. Place it on the map in the Campus builder." : "Camera saved");
      after();
    } }],
  });
}

function scanDialog(after) {
  const list = h("div", { class: "stack" }, h("p", { class: "muted" }, "Looking for cameras on this network. This takes up to 30 seconds..."));
  dialog({ title: "Find cameras on the network", body: list, actions: [{ label: "Close" }] });
  post("/api/cameras/scan", {}).then((r) => {
    if (!r.devices.length) { list.replaceChildren(h("p", {}, "No cameras answered. Check the cameras are on the same network as this PC, or type the address yourself.")); return; }
    list.replaceChildren(h("p", { class: "muted" }, "These devices have a camera streaming port open. Choose one to add it."),
      h("table", { class: "list" }, h("tbody", {}, r.devices.map((d) => h("tr", {},
        h("td", { class: "num" }, d.ip), h("td", {}, d.likely_camera ? h("span", { class: "tag teal" }, "RTSP camera") : h("span", { class: "tag" }, "Web device")),
        h("td", { class: "muted" }, `ports ${d.ports.join(", ")}`),
        h("td", {}, h("button", { class: "small", onclick: () => {
          document.querySelector("dialog")?.close();
          cameraDialog({ name: `Camera ${d.ip.split(".").pop()}`, source: d.likely_camera ? `rtsp://admin:PASSWORD@${d.ip}:554/` : `http://${d.ip}:${d.ports.find((p) => p !== 554) || 80}/video`, enabled: 1 }, after);
        } }, "Add")))))));
  }).catch((e) => list.replaceChildren(h("p", {}, e.message)));
}

function activityDialog(cam, after) {
  const a = cam.analytics || {};
  const [from, to] = (a.after_hours || "").split("-");
  const body = h("div", { class: "stack" },
    h("p", { class: "muted", style: { margin: 0 } }, "CAMS has a person-detection AI that runs on this PC. These rules use it to flag situations for a guard to check. They cannot judge what a person intends."),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "people", checked: a.people !== false }), "Detect people on this camera (needed for the rules below)"),
    h("div", { class: "grid2" },
      field("Loitering: alert when someone stays longer than (minutes)", h("input", { name: "loiter_minutes", type: "number", min: 0, step: 1, value: a.loiter_minutes || 0 }), "0 = off. Try 5 for gates and corridors."),
      field("Crowd: alert when this many people gather", h("input", { name: "crowd_count", type: "number", min: 0, value: a.crowd_count || 0 }), "0 = off. They must stay together for 10 seconds.")),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "running", checked: !!a.running }), "Alert when someone is running (corridors, stores, offices)"),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "after_on", checked: !!a.after_hours }), "Alert for anyone seen at this camera between"),
    h("div", { class: "row" }, h("input", { type: "time", name: "from", value: from || "18:00" }), "and", h("input", { type: "time", name: "to", value: to || "06:00" })),
    h("p", { class: "hint", style: { margin: 0 } }, "Closed hours can also be set for a whole building in the Campus builder."),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "tamper", checked: a.tamper !== false }), "Alert when the camera is covered, blurred or turned away"),
  );
  dialog({ title: `Activity detection: ${cam.name}`, body, actions: [{ label: "Cancel" }, { label: "Save rules", class: "primary", run: async () => {
    const v = formValues(body);
    await put(`/api/cameras/${cam.id}/analytics`, {
      people: v.people, loiter_minutes: +v.loiter_minutes || 0, crowd_count: +v.crowd_count || 0, running: v.running,
      after_hours: v.after_on ? `${v.from}-${v.to}` : "", tamper: v.tamper,
    });
    toast("Activity rules saved"); after();
  } }] });
}

function ruleTags(a) {
  if (!a || a.people === false) return [];
  const t = [];
  if (a.loiter_minutes) t.push(`loiter ${a.loiter_minutes} min`);
  if (a.crowd_count) t.push(`crowd ${a.crowd_count}+`);
  if (a.running) t.push("running");
  if (a.after_hours) t.push(`closed ${a.after_hours}`);
  if (a.tamper) t.push("tamper");
  return t;
}

async function cameras(el) {
  const body = h("tbody");
  el.append(
    head("Cameras", "Any camera that gives a video stream works: IP, Ethernet/PoE, NVR channels, USB webcams and phones.",
      h("button", { onclick: () => scanDialog(load) }, icon("search"), "Find on network"),
      h("button", { class: "primary", id: "add-camera", onclick: () => cameraDialog(null, load) }, icon("plus"), "Add camera")),
    h("div", { class: "panel", style: { overflowX: "auto" } }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["Status", "Name", "Address", "Picture", "On map", ""].map((t) => h("th", {}, t)))), body)),
  );
  async function load() {
    const cams = await get("/api/cameras");
    if (!cams.length) {
      body.replaceChildren(h("tr", {}, h("td", { colspan: 6 }, emptyState("No cameras yet", "Add your first camera, or let CAMS look for cameras on your network."))));
      return;
    }
    body.replaceChildren(...cams.map((c) => h("tr", {},
      h("td", {}, h("span", { class: "row" }, h("span", { class: `dot ${c.enabled ? c.live.status : ""}` }), c.enabled ? c.live.status : "off")),
      h("td", {}, h("b", {}, c.name), c.restricted ? h("span", { class: "tag red", style: { marginLeft: "6px" } }, "Restricted") : null,
        c.record_mode === "always" ? h("span", { class: "tag", style: { marginLeft: "6px" } }, "Recording all the time") : null,
        c.colour_mode && c.colour_mode !== "off" ? h("span", { class: "tag violet", style: { marginLeft: "6px" } }, c.colour_mode === "auto" ? "AI colour at night" : "AI colour") : null,
        h("div", { class: "row", style: { gap: "4px", marginTop: "2px" } }, ruleTags(c.analytics).map((t) => h("span", { class: "tag" }, t))),
        c.live.status === "offline" ? h("div", { class: "hint" }, c.live.error) : null),
      h("td", { class: "muted", style: { maxWidth: "320px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, c.source_display),
      h("td", { class: "num" }, c.live.status === "online" ? `${c.live.width}x${c.live.height}, ${c.live.fps} fps` : ""),
      h("td", {}, c.map_x != null ? h("span", { class: "tag teal" }, "Placed") : h("button", { class: "small", onclick: () => go("builder") }, "Place on map")),
      h("td", {}, h("div", { class: "row end" },
        h("button", { class: "small", onclick: () => activityDialog(c, load) }, "Activity rules"),
        h("button", { class: "small", onclick: () => cameraDialog(c, load) }, "Edit"),
        h("button", { class: "small danger", onclick: async () => {
          if (await confirmBox("Delete camera?", `${c.name} will be removed. Past sightings stay in the log.`)) { await del(`/api/cameras/${c.id}`); load(); }
        } }, "Delete"))),
    )));
  }
  await load();
  const t = setInterval(() => load().catch(() => {}), 5000);
  return () => clearInterval(t);
}

// ======================================================================= builder
const COLORS = ["#5b8def", "#0b7a75", "#8a6bd1", "#d0763a", "#3f9a54", "#9aa5ad", "#c2453a"];
const PURPOSES = { "": "Not set", dining: "Dining hall / eating", classroom: "Classroom", lab: "Laboratory", library: "Library / study",
  dormitory: "Dormitory / sleeping", sports: "Sports ground", worship: "Chapel / mosque / prayer", assembly: "Assembly / hall",
  office: "Office / staff room", gate: "Gate / entrance", outdoor: "Outdoor / walkway", other: "Other" };
const KINDS = { building: "Building", zone: "Zone / area", gate: "Gate", field: "Field / ground", parking: "Parking" };

async function builder(el) {
  const side = h("div", { class: "stack" });
  const mapBox = h("div");
  const studioBtn = h("button", { class: "primary", onclick: async () => {
    studioBtn.disabled = true;
    try {
      const { openStudio } = await import("./studio.js");
      await openStudio({ onClose: async () => { await reload(); if (view.view3d) { view.view3d.reloadScene(); } } });
    } catch (e) { fail(e); }
    finally { studioBtn.disabled = false; }
  } }, icon("builder"), "Open 3D Map Studio");
  el.append(head("Campus builder", "Draw your compound, then drag each camera to where it hangs and turn it to face the way it looks. Use the 3D Map Studio to draw buildings, roofs, floors and stairs in 3D.", studioBtn),
    h("div", { class: "builder" }, mapBox, side));
  let selected = null;
  const view = new MapView(mapBox, {
    height: "tall", editable: true,
    mapOpts: {
      onShapeDrawn: (pts) => newShape(pts),
      onSelect: (sel) => { selected = sel; drawSide(); },
      onBuildingChanged: (b) => saveBuilding(b),
      onCameraChanged: (c) => patch(`/api/cameras/${c.id}/place`, { map_x: c.map_x, map_y: c.map_y, direction: c.direction }).then(drawSide).catch(fail),
      onPlaceCamera: (x, y) => placeCamera(x, y),
    },
  });
  const map = view.map2d;
  await view.load();
  let mode = "select";
  let placing = null;

  const note = h("div", { class: "map-note hidden" });
  view.wrap.append(note);
  const setMode = (m, msg) => {
    mode = m; map.setMode(m);
    note.textContent = msg || ""; note.classList.toggle("hidden", !msg);
    drawSide();
  };

  async function reload() { const sel = map.selected; await view.load(); map.select(sel); drawSide(); }

  async function saveBuilding(b) {
    try { await put(`/api/buildings/${b.id}`, b); if (view.view3d) view.view3d.setData(view.data); } catch (e) { fail(e); }
  }

  function newShape(pts) {
    const body = h("div", { class: "stack" },
      field("Name", h("input", { name: "name", required: true, placeholder: "e.g. Library, Block A, Main gate" })),
      h("div", { class: "grid3" },
        field("Type", h("select", { name: "kind" }, Object.entries(KINDS).map(([k, l]) => h("option", { value: k }, l)))),
        field("Height (m)", h("input", { name: "height_m", type: "number", value: 7, min: 1, step: 0.5 })),
        field("Floors", h("input", { name: "floors", type: "number", value: 2, min: 1 }))));
    dialog({ title: "Name this shape", body, actions: [{ label: "Cancel" }, { label: "Add to map", class: "primary", run: async () => {
      const v = formValues(body);
      if (!v.name.trim()) { toast("Give it a name.", "error"); return true; }
      const color = v.kind === "field" ? "#3f9a54" : v.kind === "zone" ? "#d0763a" : COLORS[view.data.buildings.length % 5];
      const { id } = await post("/api/buildings", { name: v.name, kind: v.kind, polygon: pts, height_m: +v.height_m || 6, floors: +v.floors || 1, color });
      await reload();
      map.select({ kind: "building", id }); selected = { kind: "building", id }; drawSide();
    } }] });
  }

  async function placeCamera(x, y) {
    if (!placing) return;
    await patch(`/api/cameras/${placing}/place`, { map_x: x, map_y: y });
    const id = placing;
    placing = null;
    setMode("select");
    await reload();
    map.select({ kind: "camera", id }); selected = { kind: "camera", id }; drawSide();
    toast("Camera placed. Drag the amber handle to point it the right way.");
  }

  const toolBtn = (id, label, ic, msg) => h("button", { class: "tool", "aria-pressed": String(mode === id), onclick: () => setMode(id, msg) }, icon(ic), label);

  const groupsP = get("/api/people/groups").catch(() => []);

  function rotateBuilding(b, deg) {
    const [cx, cy] = centroid(b.polygon);
    const a = (deg * Math.PI) / 180, cos = Math.cos(a), sin = Math.sin(a);
    b.polygon = b.polygon.map(([x, y]) => [
      Math.round((cx + (x - cx) * cos - (y - cy) * sin) * 10) / 10,
      Math.round((cy + (x - cx) * sin + (y - cy) * cos) * 10) / 10]);
    b.rotation = ((b.rotation || 0) + deg + 360) % 360;
    saveBuilding(b); map.render(); drawSide();
  }

  function floorName(b, i) {
    return (b.floor_names || [])[i] || (i === 0 ? "Ground floor" : `Floor ${i}`);
  }

  function buildingPanels(bld) {
    const f = h("div", { class: "stack" },
      field("Name", h("input", { name: "name", value: bld.name })),
      h("div", { class: "grid3" },
        field("Type", h("select", { name: "kind" }, Object.entries(KINDS).map(([k, l]) => h("option", { value: k, selected: k === bld.kind }, l)))),
        field("Height m", h("input", { name: "height_m", type: "number", value: bld.height_m, min: 1, step: 0.5 })),
        field("Floors", h("input", { name: "floors", type: "number", value: bld.floors, min: 1, max: 200 }))),
      field("Used for", h("select", { name: "purpose" }, Object.entries(PURPOSES).map(([k, l]) => h("option", { value: k, selected: k === (bld.purpose || "") }, l))),
        "Helps the activity AI: e.g. people seen eating in a Dining hall, missed meals, lessons."),
      h("div", { class: "swatches", role: "group", "aria-label": "Colour" }, COLORS.map((c) => h("button", { style: { background: c }, "aria-label": c, "aria-pressed": String(c === bld.color), onclick: () => { bld.color = c; saveBuilding(bld); map.render(); drawSide(); } }))),
    );
    f.addEventListener("change", () => {
      const v = formValues(f);
      const floors = Math.max(1, +v.floors || 1);
      // keep height sensible when floors are added (about 3.2 m per floor)
      const height = floors !== bld.floors && +v.height_m === bld.height_m ? Math.max(bld.height_m, floors * 3.2) : +v.height_m || 6;
      Object.assign(bld, { name: v.name, kind: v.kind, height_m: Math.round(height * 10) / 10, floors, purpose: v.purpose });
      refreshActivityStatus();
      saveBuilding(bld); map.render(); drawSide();
    });
    const arrange = h("div", { class: "row" },
      h("button", { class: "small", onclick: () => rotateBuilding(bld, -15), title: "Turn left 15°" }, "Turn left"),
      h("button", { class: "small", onclick: () => rotateBuilding(bld, 15), title: "Turn right 15°" }, "Turn right"),
      h("button", { class: "small", onclick: () => rotateBuilding(bld, 90) }, "90°"),
      h("button", { class: "small", onclick: async () => {
        const copy = { ...bld, name: `${bld.name} copy`, polygon: bld.polygon.map(([x, y]) => [x + 8, y + 8]) };
        delete copy.id;
        const { id } = await post("/api/buildings", copy);
        await reload(); selected = { kind: "building", id }; map.select(selected); drawSide();
      } }, "Duplicate"));

    const panels = [h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Selected shape"),
      h("button", { class: "small danger", onclick: async () => {
        if (!(await confirmBox("Delete this shape?", `${bld.name} and its access rules will be removed from the map.`))) return;
        await del(`/api/buildings/${bld.id}`); selected = null; map.select(null); reload();
      } }, "Delete")),
      h("div", { class: "panel-body stack" }, f, arrange, h("p", { class: "hint", style: { margin: 0 } }, "Drag the shape to move it. Drag a corner to reshape.")))];

    if (bld.kind === "building") {
      const list = h("div", { class: "floors" });
      for (let i = bld.floors - 1; i >= 0; i--) {
        const inp = h("input", { value: floorName(bld, i), "aria-label": `Name of floor ${i}` });
        inp.addEventListener("change", () => {
          const names = Array.from({ length: bld.floors }, (_, k) => floorName(bld, k));
          names[i] = inp.value.trim() || floorName({}, i);
          bld.floor_names = names; saveBuilding(bld);
        });
        const camsHere = view.data.cameras.filter((c) => c.building_id === bld.id && (c.floor || 0) === i).length;
        list.append(h("div", { class: "row" }, h("span", { class: "num faint", style: { width: "22px" } }, i), inp,
          h("span", { class: "hint", style: { width: "70px" } }, camsHere ? `${camsHere} camera${camsHere > 1 ? "s" : ""}` : "")));
      }
      panels.push(h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Floors"),
        h("button", { class: "small", onclick: () => { bld.floors += 1; bld.height_m = Math.max(bld.height_m, bld.floors * 3.2); saveBuilding(bld); map.render(); drawSide(); } }, "Add floor"),
        bld.floors > 1 ? h("button", { class: "small", onclick: () => { bld.floors -= 1; bld.floor_names = (bld.floor_names || []).slice(0, bld.floors); saveBuilding(bld); drawSide(); } }, "Remove top floor") : null),
        h("div", { class: "panel-body" }, list, h("p", { class: "hint", style: { margin: "8px 0 0" } }, "Put cameras on a floor by selecting the camera and choosing this building and floor."))));
    }
    panels.push(accessPanel(bld));
    return panels;
  }

  function accessPanel(bld) {
    const modeSel = h("select", { "aria-label": "Who may enter" },
      h("option", { value: "everyone", selected: bld.access_mode === "everyone" }, "Everyone may enter"),
      h("option", { value: "allow", selected: bld.access_mode === "allow" }, "Only the people chosen below"),
      h("option", { value: "deny", selected: bld.access_mode === "deny" }, "Everyone except the people chosen below"));
    const cats = h("div", { class: "chips" }, CATEGORIES.map((c) => h("label", {},
      h("input", { type: "checkbox", value: c, checked: (bld.access_categories || []).includes(c) }), PLURAL[c])));
    const groups = h("div", { class: "chips" }, h("span", { class: "hint" }, "Loading classes..."));
    groupsP.then((gs) => groups.replaceChildren(...(gs.length ? gs.map((g) => h("label", {},
      h("input", { type: "checkbox", value: g, checked: (bld.access_groups || []).includes(g) }), g)) : [h("span", { class: "hint" }, "No classes or departments yet.")])));
    const peopleBox = h("div", { class: "chips" });
    const drawPeople = async () => {
      const ids = bld.access_people || [];
      const names = await Promise.all(ids.map((id) => get(`/api/people/${id}`).then((p) => p.full_name).catch(() => `#${id}`)));
      peopleBox.replaceChildren(...ids.map((id, i) => h("span", { class: "chip-x" }, names[i],
        h("button", { "aria-label": `Remove ${names[i]}`, onclick: () => { bld.access_people = ids.filter((x) => x !== id); save(); drawPeople(); } }, "x"))));
    };
    drawPeople();
    const search = h("input", { type: "search", placeholder: "Add a person by name or ID", "aria-label": "Add a person" });
    const results = h("div", { class: "chips" });
    let t;
    search.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        if (search.value.trim().length < 2) return results.replaceChildren();
        const rows = await get(`/api/people?q=${encodeURIComponent(search.value.trim())}&limit=6`);
        results.replaceChildren(...rows.map((p) => h("button", { class: "small", onclick: () => {
          bld.access_people = [...new Set([...(bld.access_people || []), p.id])]; save(); drawPeople(); search.value = ""; results.replaceChildren();
        } }, `+ ${p.full_name}`)));
      }, 250);
    });
    const [from, to] = (bld.closed_hours || "").split("-");
    const closedOn = h("input", { type: "checkbox", checked: !!bld.closed_hours });
    const tFrom = h("input", { type: "time", value: from || "18:00", "aria-label": "Closed from" });
    const tTo = h("input", { type: "time", value: to || "06:00", "aria-label": "Closed until" });
    const chosen = h("div", { class: "stack" },
      h("div", {}, h("div", { class: "hint" }, "Types of people"), cats),
      h("div", {}, h("div", { class: "hint" }, "Classes or departments"), groups),
      h("div", {}, h("div", { class: "hint" }, "Particular people"), peopleBox, search, results));
    const body = h("div", { class: "stack" }, modeSel, chosen,
      h("label", { class: "check" }, closedOn, "Closed hours: alert for anyone seen here between"),
      h("div", { class: "row" }, tFrom, "and", tTo),
      h("p", { class: "hint", style: { margin: 0 } }, "During closed hours only the chosen people (with \"Only the people chosen\") may be here. Unknown faces in a restricted area always cause an alert."));
    const syncVisible = () => chosen.classList.toggle("hidden", modeSel.value === "everyone");
    function save() {
      bld.access_mode = modeSel.value;
      bld.access_categories = [...cats.querySelectorAll("input:checked")].map((i) => i.value);
      bld.access_groups = [...groups.querySelectorAll("input:checked")].map((i) => i.value);
      bld.closed_hours = closedOn.checked ? `${tFrom.value}-${tTo.value}` : "";
      saveBuilding(bld); map.render();
    }
    body.addEventListener("change", (e) => { if (e.target !== search) { syncVisible(); save(); } });
    syncVisible();
    return h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Who may enter")),
      h("div", { class: "panel-body" }, body));
  }

  function drawSide() {
    const d = view.data;
    const bld = selected?.kind === "building" && d.buildings.find((b) => b.id === selected.id);
    const cam = selected?.kind === "camera" && d.cameras.find((c) => c.id === selected.id);
    const unplaced = d.cameras.filter((c) => c.map_x == null);

    const props = [];
    if (bld) props.push(...buildingPanels(bld));
    if (cam) {
      const f = h("div", { class: "stack" },
        h("div", { class: "grid2" },
          field("Facing (degrees)", h("input", { name: "direction", type: "number", value: cam.direction, min: 0, max: 359 }), "0 = up the map"),
          field("View width", h("input", { name: "fov", type: "number", value: cam.fov, min: 10, max: 360 }))),
        h("div", { class: "grid2" },
          field("In building", h("select", { name: "building_id" }, h("option", { value: "" }, "Outside"),
            d.buildings.filter((b) => b.kind === "building").map((b) => h("option", { value: b.id, selected: b.id === cam.building_id }, b.name)))),
          field("Floor", (() => {
            const b = d.buildings.find((x) => x.id === cam.building_id && x.kind === "building");
            return b ? h("select", { name: "floor" }, Array.from({ length: b.floors }, (_, i) => h("option", { value: i, selected: i === (cam.floor || 0) }, floorName(b, i))))
              : h("input", { name: "floor", type: "number", value: cam.floor || 0, min: 0 });
          })(), "0 = ground")));
      f.addEventListener("change", async () => {
        const v = formValues(f);
        const body = { direction: (+v.direction || 0) % 360, fov: +v.fov || 90, building_id: v.building_id ? +v.building_id : null, floor: +v.floor || 0 };
        Object.assign(cam, body);
        await patch(`/api/cameras/${cam.id}/place`, body).catch(fail);
        map.render(); drawSide();
      });
      props.push(h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, cam.name),
        h("button", { class: "small", onclick: async () => { await patch(`/api/cameras/${cam.id}/place`, { map_x: null, map_y: null }); selected = null; map.select(null); reload(); } }, "Remove from map")),
        h("div", { class: "panel-body" }, f)));
    }

    side.replaceChildren(
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Tools")),
        h("div", { class: "panel-body toolbox" },
          toolBtn("select", "Select and move", "select"),
          toolBtn("rect", "Draw a rectangle", "rect", "Drag on the map to draw a rectangle."),
          toolBtn("polygon", "Draw any shape", "polygon", "Click each corner. Click the first corner (or press Enter) to finish. Esc cancels."))),
      ...props,
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Cameras")),
        h("div", { class: "panel-body stack" },
          unplaced.length ? h("div", { class: "stack" }, h("p", { class: "hint", style: { margin: 0 } }, "Not on the map yet. Choose one, then click where it is."),
            ...unplaced.map((c) => h("button", { class: "tool", "aria-pressed": String(placing === c.id), onclick: () => { placing = c.id; setMode("camera", `Click on the map where "${c.name}" is mounted.`); } }, icon("camera"), c.name)))
            : h("p", { class: "hint", style: { margin: 0 } }, d.cameras.length ? "All cameras are on the map. Click a camera to adjust it." : "Add cameras on the Cameras page first."),
        )),
      h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "On the map")),
        h("ul", { class: "layer-list" }, d.buildings.map((b) => h("li", { class: bld && bld.id === b.id ? "sel" : "", onclick: () => {
          selected = { kind: "building", id: b.id }; map.select(selected); map.focus(...centroid(b.polygon), 80); drawSide();
        } }, h("span", { class: "sw", style: { background: b.color } }), b.name, h("span", { class: "faint", style: { marginLeft: "auto" } }, KINDS[b.kind]))))),
      siteSettings(),
    );
  }

  function siteSettings() {
    const imgIn = h("input", { type: "file", accept: "image/*", class: "hidden" });
    imgIn.addEventListener("change", async () => {
      const fd = new FormData(); fd.append("file", imgIn.files[0]);
      try { await upload("/api/map/image", fd); map._fitted = false; await reload(); toast("Map picture added. Set the real size below so distances are right."); } catch (e) { fail(e); }
    });
    const f = h("div", { class: "grid2" },
      field("Width (m)", h("input", { name: "width_m", type: "number", value: view.data.width_m, min: 10 })),
      field("Depth (m)", h("input", { name: "height_m", type: "number", value: view.data.height_m, min: 10 })));
    f.addEventListener("change", async () => {
      const v = formValues(f);
      try { await put("/api/map", { width_m: +v.width_m, height_m: +v.height_m }); map._fitted = false; await reload(); } catch (e) { fail(e); }
    });
    const g = view.data.geo;
    return h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Site")),
      h("div", { class: "panel-body stack" },
        h("button", { class: "primary", onclick: () => satellitePicker(view.data, async () => { map._fitted = false; await reload(); }) },
          icon("globe"), g ? "Change the real satellite map" : "Use a real satellite map"),
        g ? h("p", { class: "hint", style: { margin: 0 } }, "Map centre: ", gpsLine(g, "")) :
          h("p", { class: "hint", style: { margin: 0 } }, "Find your compound on a satellite map of the world. CAMS saves the picture (internet needed once) and then knows the exact GPS position of every camera and sighting."),
        h("p", { class: "hint", style: { margin: 0 } }, "Or add your own plan picture and trace over it."),
        h("div", { class: "row" }, h("button", { onclick: () => imgIn.click() }, icon("upload"), view.data.image ? "Replace picture" : "Add map picture"), imgIn,
          view.data.image ? h("button", { class: "small danger", onclick: async () => { await del("/api/map/image"); reload(); } }, "Remove") : null),
        f));
  }

  drawSide();
  return () => view.destroy();
}

// ======================================================================= recordings
const dayStart = (dateStr) => { const [y, m, d] = dateStr.split("-").map(Number); return new Date(y, m - 1, d).getTime() / 1000; };
const isoDay = (d = new Date()) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const hhmm = (ts) => { const d = new Date(ts * 1000); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };

async function recordings(el) {
  const cams = await get("/api/cameras");
  const sumBox = h("div", { class: "hint" });
  el.append(head("Recordings", "Watch and download what the cameras recorded. Press Record on Live cameras, or set a camera to record all the time on the Cameras page.", sumBox));
  if (!cams.length) { el.append(h("div", { class: "panel" }, emptyState("No cameras yet", "Add a camera first.", can("operator") ? h("button", { class: "primary", onclick: () => go("cameras") }, "Add a camera") : null))); return; }

  // ---------------- download a part
  const camSel = h("select", { name: "camera" }, cams.map((c) => h("option", { value: c.id }, c.name)));
  const dayIn = h("input", { type: "date", value: isoDay(), max: isoDay() });
  const fromIn = h("input", { type: "time", step: 1, value: hhmm(Date.now() / 1000 - 600) });
  const toIn = h("input", { type: "time", step: 1, value: hhmm(Date.now() / 1000) });
  const covBar = h("div", { class: "cov-bar", title: "Shaded = recorded. Click to start the part there." });
  const covNote = h("p", { class: "hint", style: { margin: 0 } });
  const dlBtn = h("button", { class: "primary" }, icon("download"), "Download this part");
  const span = () => {
    const d0 = dayStart(dayIn.value);
    const t = (v) => { const [hh, mm, ss = 0] = v.split(":").map(Number); return d0 + hh * 3600 + mm * 60 + ss; };
    let a = t(fromIn.value), b = t(toIn.value);
    if (b <= a) b += 86400;                     // past midnight
    return [a, b];
  };
  let coverage = [];
  async function drawCoverage() {
    const d0 = dayStart(dayIn.value);
    coverage = await get(`/api/cameras/${camSel.value}/coverage?since=${d0}&until=${d0 + 86400}`);
    covBar.replaceChildren(
      ...[0, 3, 6, 9, 12, 15, 18, 21, 24].map((hr) => h("span", { class: "tick", style: { left: `${(hr / 24) * 100}%` } }, hr < 24 ? `${hr}:00` : "")),
      ...coverage.map(([a, b]) => h("i", { style: { left: `${((a - d0) / 86400) * 100}%`, width: `${Math.max(0.25, ((b - a) / 86400) * 100)}%` } })),
    );
    const [a, b] = span();
    covBar.append(h("b", { class: "cov-pick", style: { left: `${((a - d0) / 86400) * 100}%`, width: `${Math.max(0.3, ((b - a) / 86400) * 100)}%` } }));
    const total = coverage.reduce((n, [x, y]) => n + (y - x), 0);
    covNote.textContent = coverage.length ? `${fmtTime(total)} recorded on this day.` : "Nothing was recorded on this camera on this day.";
  }
  covBar.addEventListener("click", (e) => {
    const r = covBar.getBoundingClientRect();
    const t = dayStart(dayIn.value) + ((e.clientX - r.left) / r.width) * 86400;
    fromIn.value = new Date(t * 1000).toTimeString().slice(0, 8);
    toIn.value = new Date((t + 300) * 1000).toTimeString().slice(0, 8);
    drawCoverage().catch(fail);
  });
  [camSel, dayIn, fromIn, toIn].forEach((x) => x.addEventListener("change", () => drawCoverage().catch(fail)));
  dlBtn.onclick = async () => {
    const [a, b] = span();
    if (b - a > 3 * 3600) return toast("Download at most 3 hours at a time.", "error");
    await drawCoverage().catch(() => {});
    const covered = coverage.reduce((n, [x, y]) => n + Math.max(0, Math.min(b, y) - Math.max(a, x)), 0);
    if (covered < 0.5) return toast("Nothing was recorded on this camera at that time. Shaded parts of the bar were recorded.", "error");
    const link = h("a", { href: `/api/cameras/${camSel.value}/export?start=${a}&end=${b}`, download: "" });
    document.body.append(link); link.click(); link.remove();
    toast(covered < b - a - 2 ? `Downloading. Only ${fmtTime(covered)} of that time was recorded; gaps are left out.` : "Downloading the video. It goes to your Downloads folder.");
  };
  el.append(h("section", { class: "panel", style: { marginBottom: "16px" } },
    h("div", { class: "panel-head" }, h("h2", {}, "Download a part of a camera's video")),
    h("div", { class: "panel-body stack" },
      h("div", { class: "grid4" }, field("Camera", camSel), field("Day", dayIn), field("From", fromIn), field("To", toIn)),
      covBar, covNote, h("div", { class: "row" }, dlBtn,
        h("span", { class: "hint" }, "The video is an .mp4 file. It opens in Windows Media Player, Films & TV or VLC.")))));

  // ---------------- list
  const listCam = h("select", { "aria-label": "Camera" }, h("option", { value: "" }, "All cameras"), cams.map((c) => h("option", { value: c.id }, c.name)));
  const listDay = h("input", { type: "date", value: isoDay(), max: isoDay(), "aria-label": "Day" });
  const body = h("tbody");
  el.append(h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Recorded videos"), listCam, listDay),
    h("div", { style: { overflowX: "auto" } }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["Camera", "Started", "Length", "Size", "", ""].map((t) => h("th", {}, t)))), body))));
  const KIND = { manual: ["Recorded", "teal"], continuous: ["All the time", ""] };
  async function load() {
    const d0 = dayStart(listDay.value);
    const rows = await get(`/api/recordings?since=${d0}&until=${d0 + 86400}${listCam.value ? `&camera_id=${listCam.value}` : ""}`);
    const sum = await get("/api/recordings/summary");
    sumBox.textContent = `${sum.recordings} videos, ${fmtSize(sum.recordings_mb * 1e6)} (limit ${sum.limit_gb} GB, kept ${sum.days} days). Sighting clips: ${sum.clips}.`;
    if (!rows.length) { body.replaceChildren(h("tr", {}, h("td", { colspan: 6 }, emptyState("No videos on this day", "Press Record on a live camera to save its video.")))); return; }
    body.replaceChildren(...rows.map((r) => {
      const live = r.status === "recording";
      return h("tr", {},
        h("td", {}, h("b", {}, r.camera_name), " ", h("span", { class: `tag ${KIND[r.kind]?.[1] || ""}` }, KIND[r.kind]?.[0] || r.kind),
          r.keep ? h("span", { class: "tag amber", style: { marginLeft: "4px" } }, "Kept") : null),
        h("td", { class: "num" }, new Date(r.start_ts * 1000).toLocaleTimeString()),
        h("td", { class: "num" }, live ? h("span", { class: "rec-dot" }, `Recording ${fmtTime(r.duration)}`) : fmtTime(r.duration)),
        h("td", { class: "num muted" }, live ? "" : fmtSize(r.size_bytes)),
        h("td", {}, h("div", { class: "row end" },
          live ? (can("operator") && r.kind === "manual" ? h("button", { class: "small danger", onclick: async () => { await post(`/api/cameras/${r.camera_id}/record`, { action: "stop" }); load(); } }, icon("stop"), "Stop") : null)
            : [h("button", { class: "small", onclick: () => playDialog(r) }, icon("play"), "Play"),
              h("a", { class: "btn small", href: `/api/recordings/${r.id}/download`, download: "" }, icon("download"), "Download")],
          can("operator") && !live ? h("button", { class: "small", title: r.keep ? "Allow automatic deletion" : "Keep: never delete automatically", "aria-pressed": String(!!r.keep),
            onclick: async () => { await patch(`/api/recordings/${r.id}`, { keep: !r.keep }); load(); } }, icon("star"), r.keep ? "Kept" : "Keep") : null,
          can("operator") && !live ? h("button", { class: "small danger", onclick: async () => {
            if (await confirmBox("Delete this video?", `${r.camera_name}, ${clock(r.start_ts)} (${fmtTime(r.duration)}) will be deleted.`)) { await del(`/api/recordings/${r.id}`); load(); }
          } }, "Delete") : null)),
        h("td", {}));
    }));
  }
  [listCam, listDay].forEach((x) => x.addEventListener("change", () => load().catch(fail)));
  await Promise.all([drawCoverage(), load()]);
  const t = setInterval(() => { load().catch(() => {}); }, 5000);
  return () => clearInterval(t);
}

// ======================================================================= satellite picker
let leafletReady = null;
function loadLeaflet() {
  leafletReady ||= new Promise((resolve, reject) => {
    document.head.append(h("link", { rel: "stylesheet", href: "/static/vendor/leaflet/leaflet.css" }));
    const sc = h("script", { src: "/static/vendor/leaflet/leaflet.js" });
    sc.onload = () => resolve(window.L);
    sc.onerror = () => { leafletReady = null; reject(new Error("The map tool did not load.")); };
    document.head.append(sc);
  });
  return leafletReady;
}

async function satellitePicker(data, after) {
  const L = await loadLeaflet();
  const box = h("div", { class: "sat-map" });
  const frame = h("div", { class: "sat-frame" }, h("span", { class: "sat-size num" }));
  const warn = h("div", { class: "banner amber hidden" }, "The satellite map is not loading. CAMS needs the internet once to fetch the picture of your compound. Check the connection and try again. Places viewed before still show.");
  const q = h("input", { type: "search", placeholder: "Place name, Google Maps link or coordinates, e.g. -6.7627, 39.2443", "aria-label": "Find a place" });
  const found = h("div", { class: "chips" });
  const labels = h("input", { type: "checkbox", checked: true });
  const keep = h("input", { type: "checkbox", checked: true });
  const body = h("div", { class: "stack" },
    h("form", { class: "row", onsubmit: (e) => { e.preventDefault(); find(); } }, h("div", { class: "search grow" }, icon("search"), q), h("button", { type: "submit" }, "Find")),
    found, warn,
    h("div", { class: "sat-wrap" }, box, frame),
    h("div", { class: "row" },
      h("label", { class: "check" }, labels, "Show place names"),
      data.buildings.length || data.cameras.some((c) => c.map_x != null) ? h("label", { class: "check" }, keep, "Keep my buildings and cameras where they are on the ground") : null),
    h("p", { class: "hint", style: { margin: 0 } }, "Move and zoom the map until your whole compound fits inside the box (scroll to zoom, drag to move). The box becomes your campus map. ",
      "Satellite imagery: Esri, Maxar, Earthstar Geographics. Place search: OpenStreetMap."),
  );
  let m;
  const centre = data.geo ? [data.geo.lat, data.geo.lng] : [-6.7924, 39.2083];   // Dar es Salaam until a place is chosen
  const area = () => {
    const mr = box.getBoundingClientRect(), fr = frame.getBoundingClientRect();
    const x0 = fr.left - mr.left, y0 = fr.top - mr.top, x1 = x0 + fr.width, y1 = y0 + fr.height;
    const ll = (x, y) => m.containerPointToLatLng([x, y]);
    const c = ll((x0 + x1) / 2, (y0 + y1) / 2);
    return { lat: c.lat, lng: c.lng, width_m: ll(x0, (y0 + y1) / 2).distanceTo(ll(x1, (y0 + y1) / 2)), height_m: ll((x0 + x1) / 2, y0).distanceTo(ll((x0 + x1) / 2, y1)) };
  };
  const showSize = () => { const a = area(); frame.firstChild.textContent = `${Math.round(a.width_m)} m × ${Math.round(a.height_m)} m`; };
  async function find() {
    const text = q.value.trim();
    if (text.length < 2) return;
    found.replaceChildren(h("span", { class: "hint" }, "Searching..."));
    try {
      const rows = await get(`/api/geo/search?q=${encodeURIComponent(text)}`);
      if (!rows.length) { found.replaceChildren(h("span", { class: "hint" }, "No place found. Try another spelling, or paste a Google Maps link.")); return; }
      if (rows.length === 1) { m.setView([rows[0].lat, rows[0].lng], 18); found.replaceChildren(); return; }
      found.replaceChildren(...rows.map((r) => h("button", { class: "small", type: "button", onclick: () => { m.setView([r.lat, r.lng], 17); found.replaceChildren(); } }, r.name.split(",").slice(0, 3).join(","))));
    } catch (e) { found.replaceChildren(h("span", { class: "hint" }, e.message)); }
  }
  dialog({
    title: "Use a real satellite map", wide: true, body,
    actions: [
      { label: "Cancel" },
      { label: "Only save the position", run: async () => {
        const a = area();
        await put("/api/geo", { lat: a.lat, lng: a.lng });
        toast("Position saved. CAMS now shows GPS positions on your own plan.");
        await after();
      } },
      { label: "Use this area", class: "primary", run: async (d) => {
        const a = area();
        if (a.width_m > 20000 || a.height_m > 20000) { toast("That area is too big. Zoom in to your compound.", "error"); return true; }
        if (a.width_m < 10) { toast("That area is too small. Zoom out a little.", "error"); return true; }
        const btn = d.querySelector(".d-foot .primary");
        btn.textContent = "Fetching the satellite picture...";
        const r = await post("/api/geo/satellite", { ...a, keep_buildings: keep.checked });
        toast(`Satellite map saved (${Math.round(a.width_m)} m × ${Math.round(a.height_m)} m${r.missing ? `, ${r.missing} pieces missing` : ""}). It now works without internet.`);
        await after();
      } },
    ],
    onClose: () => m?.remove(),
  });
  m = L.map(box, { zoomControl: true, attributionControl: true, maxZoom: 21, worldCopyJump: true, zoomSnap: 0.25, zoomDelta: 0.5, wheelPxPerZoomLevel: 90 });
  m.attributionControl.setPrefix(false);
  const sat = L.tileLayer("/api/geo/tiles/imagery/{z}/{x}/{y}", { maxNativeZoom: 19, maxZoom: 21, attribution: "Esri, Maxar, Earthstar Geographics" }).addTo(m);
  const names = L.tileLayer("/api/geo/tiles/labels/{z}/{x}/{y}", { maxNativeZoom: 19, maxZoom: 21 });
  if (labels.checked) names.addTo(m);
  labels.onchange = () => (labels.checked ? names.addTo(m) : names.remove());
  let ok = 0, bad = 0;
  sat.on("tileload", () => { ok++; warn.classList.add("hidden"); });
  sat.on("tileerror", () => { bad++; if (bad > 6 && ok === 0) warn.classList.remove("hidden"); });
  m.on("move zoom resize", showSize);
  setTimeout(() => {
    m.invalidateSize();
    if (data.geo) {
      // zoom so the current campus fills the box
      const fr = frame.getBoundingClientRect();
      const mpp = Math.max(data.width_m / fr.width, data.height_m / fr.height);
      const z = Math.log2((156543.03 * Math.cos((data.geo.lat * Math.PI) / 180)) / mpp);
      m.setView(centre, Math.min(19, Math.max(3, z)));
    } else m.setView(centre, 13);
    showSize();
  }, 60);
  q.focus();
}

// ======================================================================= alerts
async function alerts(el) {
  let openOnly = true;
  const list = h("div", { class: "panel" });
  const seg = h("div", { class: "seg" }, [["open", "Open"], ["all", "All"]].map(([v, l]) => h("button", { "aria-pressed": String(v === "open"), onclick: (e) => {
    openOnly = v === "open"; seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); load();
  } }, l)));
  el.append(head("Alerts", "Rule breaks, watch-list sightings, suspicious activity and cameras that stopped working. Always check the picture before acting.", seg,
    h("button", { onclick: async () => { await post("/api/alerts/ack-all"); load(); } }, "Mark all as seen")), list);
  const KIND = {
    watchlist: ["Watch list", "amber"], unknown_restricted: ["Restricted camera", "red"], access_violation: ["Not allowed here", "red"],
    camera_offline: ["Camera offline", ""], tamper: ["Camera tampering", "red"], after_hours: ["After hours", "amber"],
    loitering: ["Loitering", "amber"], crowd: ["Crowd", "amber"], running: ["Running", "amber"],
  };
  const big = (src) => dialog({ title: "Alert picture", wide: true, body: h("img", { src, alt: "Alert picture", style: { width: "100%", borderRadius: "6px" } }) });
  async function load() {
    const rows = await get(`/api/alerts?open_only=${openOnly}`);
    if (!rows.length) { list.replaceChildren(emptyState("No alerts", openOnly ? "Everything has been seen. New alerts appear here and pop up in the corner." : "Nothing has happened yet.")); return; }
    list.replaceChildren(h("ul", { class: "feed" }, rows.map((a) => h("li", { class: a.snapshot_path?.includes("scene_") ? "scene-row" : "" },
      a.snapshot_path?.includes("scene_") ? h("img", { class: "scene", src: snapUrl(a), alt: "Scene", onclick: () => big(snapUrl(a)) }) : thumb(snapUrl(a)),
      h("div", {}, h("div", { class: "who" }, a.message), h("div", { class: "where" }, h("span", { class: `tag ${KIND[a.kind]?.[1] || ""}` }, KIND[a.kind]?.[0] || a.kind), " ", clock(a.created_at))),
      h("div", { class: "row" },
        a.person_id ? h("button", { class: "small", onclick: () => go("find", a.person_id) }, "Track") : null,
        a.acknowledged ? h("span", { class: "faint" }, "Seen") : h("button", { class: "small", onclick: async () => { await post(`/api/alerts/${a.id}/ack`); load(); } }, "Seen")),
    ))));
  }
  await load();
  const t = setInterval(() => load().catch(() => {}), 6000);
  return () => clearInterval(t);
}

// ======================================================================= settings
async function settings(el) {
  const s = await get("/api/settings");
  const admin = can("admin");
  const dis = !admin;
  const thr = h("input", { type: "range", name: "match_threshold", min: 0.3, max: 0.7, step: 0.01, value: s.match_threshold, disabled: dis });
  const thrOut = h("output", { class: "num" }, s.match_threshold);
  thr.addEventListener("input", () => { thrOut.textContent = thr.value; });
  const rec = h("div", { class: "stack" },
    field("Match strictness", h("div", { class: "row" }, h("span", { class: "hint" }, "More matches"), h("div", { style: { flex: 1 } }, thr), h("span", { class: "hint" }, "Fewer mistakes"), thrOut),
      "If CAMS confuses people, move right. If it misses people it should know, move left. 0.40 suits most sites."),
    h("div", { class: "grid3" },
      field("Pictures checked per second (per camera)", h("input", { name: "analysis_fps", type: "number", min: 0.2, max: 15, step: 0.5, value: s.analysis_fps, disabled: dis }), "Lower this on slow PCs."),
      field("Join sightings within (seconds)", h("input", { name: "sighting_merge_seconds", type: "number", min: 5, max: 600, value: s.sighting_merge_seconds, disabled: dis })),
      field("Recognition workers", h("input", { name: "workers", type: "number", min: 0, max: 16, value: s.workers, disabled: dis }), "0 = automatic. Restart CAMS after changing.")),
  );
  const priv = h("div", { class: "stack" },
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "blur_unknown", checked: s.blur_unknown === "1", disabled: dis }), "Blur the faces of people who are not enrolled (live view and snapshots)"),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "save_snapshots", checked: s.save_snapshots === "1", disabled: dis }), "Keep a small face picture with each sighting"),
    field("Delete sightings older than (days)", h("input", { name: "retention_days", type: "number", min: 1, max: 3650, value: s.retention_days, disabled: dis, style: { maxWidth: "160px" } }), "Keep only as long as you really need."),
  );
  const video = h("div", { class: "stack" },
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "sighting_clips", checked: s.sighting_clips !== "0", disabled: dis }),
      "Save a short video clip each time a person is seen (watch it on their route in Find a person)"),
    h("div", { class: "grid3" },
      field("Clip length (seconds)", h("input", { name: "clip_seconds", type: "number", min: 3, max: 30, value: s.clip_seconds, disabled: dis })),
      field("Recording: pictures per second", h("input", { name: "record_fps", type: "number", min: 1, max: 25, value: s.record_fps, disabled: dis }), "8 is smooth enough for security video and saves space."),
      field("Recording size", h("select", { name: "record_width", disabled: dis }, [["640", "Small (640 wide)"], ["960", "Medium (960)"], ["1280", "HD (1280)"], ["1920", "Full HD (1920)"]].map(([v, l]) => h("option", { value: v, selected: v === String(s.record_width) }, l))))),
    h("div", { class: "grid3" },
      field("Delete recordings older than (days)", h("input", { name: "recording_days", type: "number", min: 1, max: 365, value: s.recording_days, disabled: dis }), "Videos marked Keep are never deleted automatically."),
      field("Space for recordings (GB)", h("input", { name: "recording_max_gb", type: "number", min: 1, max: 20000, value: s.recording_max_gb, disabled: dis }), "When full, the oldest videos are deleted first.")),
  );
  // ---- colour for black-and-white (night) video
  const aiBox = h("div", { class: "stack" });
  const modelIn = h("input", { type: "file", accept: ".onnx", class: "hidden" });
  let aiTimer = null;
  async function drawAi() {
    const st = await get("/api/colour");
    const d = st.download || {};
    const pct = d.total ? Math.round((d.done / d.total) * 100) : 0;
    aiBox.replaceChildren(...[
      h("div", { class: "row" },
        st.installed ? h("span", { class: "tag teal" }, `Colour AI installed (${st.size_mb} MB)`) : h("span", { class: "tag" }, "Colour AI not installed yet"),
        st.installed && st.last_ms ? h("span", { class: "hint" }, `Last colouring took ${Math.round(st.last_ms)} ms`) : null,
        st.active?.length ? h("span", { class: "hint" }, `${st.active.length} camera${st.active.length > 1 ? "s" : ""} in colour now`) : null),
      d.running ? h("div", { class: "stack" }, h("progress", { max: 100, value: pct }), h("span", { class: "hint" }, d.total ? `Downloading ${pct}% of ${Math.round(d.total / 1e6)} MB...` : "Connecting...")) : null,
      d.error ? h("p", { class: "error-text", style: { margin: 0 } }, d.error) : null,
      st.error ? h("p", { class: "error-text", style: { margin: 0 } }, st.error) : null,
      admin && !d.running ? h("div", { class: "row" },
        h("button", { onclick: async () => { try { await post("/api/colour/download"); drawAi(); } catch (e) { fail(e); } } }, icon("download"), st.installed ? "Download again" : "Download the colour AI (about 130 MB, once)"),
        h("button", { onclick: () => modelIn.click(), title: "If this PC has no internet, copy colorizer.onnx onto a USB stick on another PC" }, icon("upload"), "Load colorizer.onnx from this PC"),
        st.installed ? h("button", { class: "small danger", onclick: async () => { await del("/api/colour/model"); drawAi(); } }, "Remove") : null) : null,
    ].filter(Boolean));
    clearTimeout(aiTimer);
    if (d.running) aiTimer = setTimeout(() => drawAi().catch(() => {}), 1000);
  }
  modelIn.addEventListener("change", async () => {
    const f = modelIn.files[0]; if (!f) return;
    const fd = new FormData(); fd.append("file", f);
    aiBox.prepend(h("p", { class: "hint" }, "Checking the file..."));
    try { await upload("/api/colour/model", fd); toast("Colour AI installed"); } catch (e) { fail(e); }
    modelIn.value = ""; drawAi();
  });
  const colourOpts = h("div", { class: "stack" },
    h("p", { class: "muted", style: { margin: 0 } }, "At night most CCTV cameras switch to infrared and show black and white. CAMS can colour that video live with an AI. ",
      h("b", {}, "The colours are the AI's guess, not the real colours"), ": never rely on the colour of clothes or a car in AI-coloured video. Coloured pictures are marked \"AI colour\". Choose which cameras use it in each camera's settings (Cameras > Edit)."),
    aiBox, modelIn,
    h("div", { class: "grid3" },
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "colour_enhance", checked: s.colour_enhance !== "0", disabled: dis }), "Also make dark night pictures clearer"),
      field("Colour AI speed", h("select", { name: "colour_refresh", disabled: dis },
        [["0.3", "Fast (more work for the PC)"], ["0.6", "Normal"], ["1.5", "Light (slow PCs)"]].map(([v, l]) => h("option", { value: v, selected: v === String(s.colour_refresh) }, l))),
        "How often the colours are worked out again for each camera being watched.")),
  );
  drawAi().catch(() => {});
  const saveRow = admin ? h("div", { class: "row end" }, h("button", { class: "primary", onclick: async () => {
    const v = { ...formValues(rec), ...formValues(priv), ...formValues(video), ...formValues(colourOpts) };
    v.colour_enhance = v.colour_enhance ? "1" : "0";
    v.blur_unknown = v.blur_unknown ? "1" : "0"; v.save_snapshots = v.save_snapshots ? "1" : "0"; v.sighting_clips = v.sighting_clips ? "1" : "0";
    try { await put("/api/settings", v); toast("Settings saved"); } catch (e) { fail(e); }
  } }, "Save settings")) : h("p", { class: "hint" }, "Only an admin can change these settings.");

  const section = (title, ...kids) => h("section", { class: "panel", style: { marginBottom: "16px" } }, h("div", { class: "panel-head" }, h("h2", {}, title)), h("div", { class: "panel-body stack" }, ...kids));

  // ---- maps and mouse: every user can choose
  const mouseOpt = (val, title, lines) => h("label", { class: `choice${prefs.mouse === val ? " on" : ""}` },
    h("input", { type: "radio", name: "map_mouse", value: val, checked: prefs.mouse === val }),
    h("div", {}, h("b", {}, title), h("ul", { class: "hint" }, lines.map((l) => h("li", {}, l)))));
  const mouse = h("div", { class: "choices", role: "radiogroup", "aria-label": "Mouse buttons on maps" },
    mouseOpt("standard", "Standard", ["Left button drag: move the plan; turn around a point in 3D", "Right button drag: look around in 3D"]),
    mouseOpt("swapped", "Swapped (right button moves the map)", ["Right button drag: move the plan; turn around a point in 3D", "Left button drag: look around in 3D", "Clicking to choose and draw stays on the left button"]));
  mouse.addEventListener("change", async (e) => {
    const val = e.target.value;
    try {
      await put("/api/settings", { map_mouse: val });
      setPrefs({ mouse: val });
      mouse.querySelectorAll(".choice").forEach((c) => c.classList.toggle("on", c.querySelector("input").checked));
      toast(val === "swapped" ? "Mouse buttons swapped: drag with the right button to move the map." : "Mouse buttons back to standard.");
    } catch (ex) { fail(ex); }
  });

  el.append(head("Settings", null),
    section("Maps and mouse", h("p", { class: "muted", style: { margin: 0 } }, "Choose which mouse button moves the map (Overview, Find a person, Campus builder and 3D Map Studio). The middle button (wheel) always moves the map too."), mouse),
    section("Recognition", rec),
    section("Privacy", priv, admin ? h("div", { class: "row" }, h("button", { onclick: async () => {
      const r = await post("/api/maintenance/purge"); toast(`${r.deleted} old sightings deleted`);
    } }, "Delete old sightings now")) : null),
    section("Video recordings and clips", video),
    section("Colour for black-and-white (night) video", colourOpts),
    saveRow,
    h("div", { style: { height: "16px" } }),
  );

  // own password
  const pw = h("div", { class: "grid2" },
    field("New password", h("input", { type: "password", name: "password", autocomplete: "new-password" })),
    field("Type it again", h("input", { type: "password", name: "password2", autocomplete: "new-password" })));
  el.append(section("My password", pw, h("div", { class: "row" }, h("button", { onclick: async () => {
    const v = formValues(pw);
    if (v.password !== v.password2) return toast("The two passwords are different.", "error");
    try { await put(`/api/users/${state.user.id}/password`, { password: v.password }); toast("Password changed"); pw.querySelectorAll("input").forEach((i) => (i.value = "")); } catch (e) { fail(e); }
  } }, "Change password"))));

  if (admin) {
    const usersBody = h("tbody");
    const loadUsers = async () => {
      const us = await get("/api/users");
      usersBody.replaceChildren(...us.map((u) => h("tr", {},
        h("td", {}, h("b", {}, u.username)), h("td", {}, u.full_name), h("td", {}, h("span", { class: "tag" }, u.role)),
        h("td", {}, h("div", { class: "row end" },
          h("button", { class: "small", onclick: () => {
            const inp = h("input", { type: "password", autocomplete: "new-password" });
            dialog({ title: `New password for ${u.username}`, body: field("Password", inp), actions: [{ label: "Cancel" }, { label: "Set password", class: "primary", run: () => put(`/api/users/${u.id}/password`, { password: inp.value }).then(() => toast("Password set")) }] });
          } }, "Reset password"),
          u.id !== state.user.id ? h("button", { class: "small danger", onclick: async () => {
            if (await confirmBox("Delete user?", `${u.username} will no longer be able to sign in.`)) { try { await del(`/api/users/${u.id}`); loadUsers(); } catch (e) { fail(e); } }
          } }, "Delete") : null)))));
    };
    const addUser = () => {
      const f = h("div", { class: "stack" },
        h("div", { class: "grid2" }, field("Username", h("input", { name: "username" })), field("Full name", h("input", { name: "full_name" }))),
        h("div", { class: "grid2" }, field("Password", h("input", { name: "password", type: "password", autocomplete: "new-password" })),
          field("Role", h("select", { name: "role" },
            h("option", { value: "viewer" }, "Viewer: watch cameras and search"),
            h("option", { value: "operator", selected: true }, "Operator: also enrol people and set up cameras"),
            h("option", { value: "admin" }, "Admin: everything, including users and settings")))));
      dialog({ title: "Add a user", body: f, actions: [{ label: "Cancel" }, { label: "Add user", class: "primary", run: async () => { await post("/api/users", formValues(f)); loadUsers(); } }] });
    };
    el.append(section("Users", h("table", { class: "list" }, usersBody), h("div", { class: "row" }, h("button", { onclick: addUser }, icon("plus"), "Add user"))));
    await loadUsers();

    const auditBody = h("tbody");
    el.append(section("Backup and records",
      h("p", { class: "muted" }, "Download a backup of people, face pictures, cameras and the map. Store it somewhere safe and locked, because it contains personal data."),
      h("div", { class: "row" }, h("a", { class: "btn", href: "/api/backup", download: true }, "Download backup")),
      h("h3", { style: { marginTop: "8px" } }, "Activity log"),
      h("p", { class: "hint", style: { margin: 0 } }, "Who searched, enrolled, changed or deleted what."),
      h("div", { style: { maxHeight: "320px", overflowY: "auto" } }, h("table", { class: "list" }, auditBody)),
    ));
    const log = await get("/api/audit?limit=200");
    auditBody.replaceChildren(...log.map((a) => h("tr", {}, h("td", { class: "num muted" }, clock(a.ts)), h("td", {}, a.username), h("td", {}, a.action.replaceAll("_", " ")),
      h("td", { class: "hint", style: { maxWidth: "360px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" } }, a.detail))));
  }
  el.append(h("p", { class: "hint" }, `CAMS ${state.status.version}. A TransitTech and Godwill Andrew Madunda collaboration.`));
}

// ======================================================================= guide
async function guide(el) {
  el.append(head("How to use CAMS", "Five steps to get from installation to finding people.",
    h("button", { class: "primary", onclick: () => startTour(state, true) }, "Show me around")));
  el.append(h("div", { class: "stack" }, GUIDE.map((g, i) => h("section", { class: "panel" },
    h("div", { class: "panel-head" }, h("h2", {}, `${i + 1}. ${g.title}`), g.page ? h("button", { class: "small", onclick: () => go(g.page) }, g.button) : null),
    h("div", { class: "panel-body" }, g.text.map((t) => h("p", {}, t)))))));
}

export const PAGES = { overview, live, find, people, person, cameras, builder, alerts, settings, guide, report, activity: activityPage, recordings };
