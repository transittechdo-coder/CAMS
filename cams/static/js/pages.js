// All CAMS pages. Each page function fills `el` and may return a cleanup function.
import {
  h, get, post, put, patch, del, upload, icon, toast, fail, dialog, confirmBox, field, formValues,
  ago, clock, duration, where, CATEGORIES, PLURAL, cap, thumb, photoUrl, snapUrl, POSE_ICON,
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
  el.append(head("Live cameras", "Green box: recognised. Red: not enrolled (face blurred). Orange: on the watch list.", seg), grid);
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
    caps.set(c.id, { dot, meta, off, img });
    grid.append(h("div", { class: "cam-tile", ondblclick: () => img.requestFullscreen?.() }, img, off,
      h("div", { class: "cam-cap" }, dot, h("b", {}, c.name), meta)));
  }
  async function refresh() {
    for (const c of await get("/api/cameras")) {
      const t = caps.get(c.id);
      if (!t) continue;
      t.dot.className = `dot ${c.live.status}`;
      t.meta.textContent = c.live.status === "online" ? `${c.live.faces || 0} face${c.live.faces === 1 ? "" : "s"}` : c.live.status;
      t.off.textContent = c.live.status === "offline" ? c.live.error : "";
      t.off.classList.toggle("hidden", c.live.status !== "offline");
    }
  }
  refresh();
  const timer = setInterval(() => refresh().catch(() => {}), 3000);
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
      [["86400", "Last 24 hours"], ["today", "Today"], ["604800", "Last 7 days"], ["2592000", "Last 30 days"]].map(([v, l]) => h("option", { value: v }, l)));
    const tl = h("ul", { class: "timeline" });
    const mapBox = h("div");
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
        ),
        h("div", { class: "stack" }, ls?.snapshot_path ? thumb(snapUrl(ls), "thumb xl", "Last sighting") : null,
          can("operator") ? h("button", { class: "small", onclick: () => go("person", p.id) }, "Edit person") : null),
      )),
      h("div", { class: "split" }, mapBox,
        h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Movements"), rangeSel), h("div", { class: "panel-body" }, tl))),
    );
    const map = new MapView(mapBox, { height: "mid" });
    await map.load();
    async function loadTimeline() {
      let since;
      if (rangeSel.value === "today") { const d = new Date(); d.setHours(0, 0, 0, 0); since = d.getTime() / 1000; }
      else since = Date.now() / 1000 - Number(rangeSel.value);
      const rows = await get(`/api/people/${id}/timeline?since=${since}`);
      tl.replaceChildren(...(rows.length ? rows.map((s) => h("li", {},
        h("div", { class: "when" }, clock(s.first_seen), s.last_seen - s.first_seen > 30 ? ` to ${clock(s.last_seen)}` : ""),
        h("div", {}, s.camera_name, s.building_name ? `, ${s.building_name}` : ""),
        h("div", { class: "hint" }, `${duration(s.first_seen, s.last_seen)}, ${Math.round(s.confidence * 100)}% match`),
      )) : [h("li", {}, h("span", { class: "muted" }, "No sightings in this period."))]));
      const trail = trailFromSightings(rows);
      const pin = pinFor(rows[0] || ls, p.full_name.split(" ")[0], { pulse: true });
      map.setMarks({ pins: pin ? [pin] : [], trail });
      if (pin && map.mode === "2d") map.map2d.focus(pin.x, pin.y, 90);
    }
    rangeSel.addEventListener("change", () => loadTimeline().catch(fail));
    await loadTimeline();
    const t = setInterval(() => loadTimeline().catch(() => {}), 10000);
    cleanup = () => { clearInterval(t); map.destroy(); };
  }

  if (pid) await showPerson(Number(pid));
  else input.focus();
  return () => cleanup?.();
}

// ======================================================================= people
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
  );
  dialog({
    title: isNew ? "Add a camera" : `Edit ${cam.name}`, body,
    actions: [{ label: "Cancel" }, { label: isNew ? "Add camera" : "Save", class: "primary", run: async () => {
      const v = formValues(body);
      const payload = { ...cam, name: v.name, source: v.source, enabled: v.enabled, restricted: v.restricted, kind: null };
      delete payload.live; delete payload.source_display;
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
    return h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Site")),
      h("div", { class: "panel-body stack" },
        h("p", { class: "hint", style: { margin: 0 } }, "Optional: add a plan or satellite picture of your compound and trace over it."),
        h("div", { class: "row" }, h("button", { onclick: () => imgIn.click() }, icon("upload"), view.data.image ? "Replace picture" : "Add map picture"), imgIn,
          view.data.image ? h("button", { class: "small danger", onclick: async () => { await del("/api/map/image"); reload(); } }, "Remove") : null),
        f));
  }

  drawSide();
  return () => view.destroy();
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
  const saveRow = admin ? h("div", { class: "row end" }, h("button", { class: "primary", onclick: async () => {
    const v = { ...formValues(rec), ...formValues(priv) };
    v.blur_unknown = v.blur_unknown ? "1" : "0"; v.save_snapshots = v.save_snapshots ? "1" : "0";
    try { await put("/api/settings", v); toast("Settings saved"); } catch (e) { fail(e); }
  } }, "Save settings")) : h("p", { class: "hint" }, "Only an admin can change these settings.");

  const section = (title, ...kids) => h("section", { class: "panel", style: { marginBottom: "16px" } }, h("div", { class: "panel-head" }, h("h2", {}, title)), h("div", { class: "panel-body stack" }, ...kids));

  el.append(head("Settings", null),
    section("Recognition", rec),
    section("Privacy", priv, admin ? h("div", { class: "row" }, h("button", { onclick: async () => {
      const r = await post("/api/maintenance/purge"); toast(`${r.deleted} old sightings deleted`);
    } }, "Delete old sightings now")) : null),
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

export const PAGES = { overview, live, find, people, person, cameras, builder, alerts, settings, guide, report, activity: activityPage };
