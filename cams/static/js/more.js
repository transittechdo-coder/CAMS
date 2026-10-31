// Pages added in CAMS 1.6: System health, Visitors and Vehicles (number plates).
import { h, get, post, put, del, upload, icon, toast, fail, dialog, confirmBox, field, formValues, ago, clock, fmtSize, snapUrl, thumb } from "./util.js";
import { can, go } from "./app.js";

const head = (title, sub, ...actions) => h("div", { class: "page-head" },
  h("div", { class: "grow" }, h("h1", {}, title), sub ? h("p", {}, sub) : null), ...actions);
const emptyState = (title, text, action) => h("div", { class: "empty" }, h("h3", {}, title), h("p", { style: { margin: "0 auto 12px" } }, text), action || null);
const section = (title, ...kids) => h("section", { class: "panel", style: { marginBottom: "16px" } },
  h("div", { class: "panel-head" }, h("h2", {}, title)), h("div", { class: "panel-body stack" }, ...kids));
const keep = (...xs) => xs.flat().filter((x) => x !== null && x !== undefined && x !== false);
export const span = (sec) => {
  sec = Math.max(0, Math.round(sec));
  if (sec < 90) return `${sec} s`;
  if (sec < 3600) return `${Math.round(sec / 60)} min`;
  const hh = Math.floor(sec / 3600), mm = Math.round((sec % 3600) / 60);
  if (hh < 48) return mm ? `${hh} h ${mm} min` : `${hh} h`;
  return `${Math.floor(hh / 24)} days ${hh % 24} h`;
};
const when = (ts) => new Date(ts * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

// ======================================================================= system health
export async function health(el) {
  const figs = h("div", { class: "figures" });
  const banner = h("div");
  const camsBody = h("tbody");
  const gaps = h("div");
  const ai = h("div", { class: "row", style: { flexWrap: "wrap", gap: "8px" } });
  const pc = h("div", { class: "hint" });
  const auto = h("div", { class: "stack" });
  el.append(
    head("System health", "Is everything working? Cameras, disk, AI, power and the times CAMS was off."),
    banner, figs,
    section("Cameras", h("div", { style: { overflowX: "auto" } }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["", "Camera", "Pictures / s", "Last picture", "Problem", "Recording"].map((t) => h("th", {}, t)))), camsBody))),
    section("Power cuts", auto, h("h3", { style: { margin: "6px 0 0" } }, "Times CAMS was off"), gaps),
    section("AI and computer", ai, pc),
  );
  let first = true;
  async function load() {
    const r = await get("/api/health");
    const online = r.cameras.filter((c) => c.status === "online").length;
    const enabled = r.cameras.filter((c) => c.status !== "off").length;
    const fig = (n, label, cls = "") => h("div", { class: `figure ${cls}` }, h("span", { class: "num" }, n), h("span", {}, label));
    const diskPct = r.disk ? r.disk.free / r.disk.total : 1;
    const b = r.battery;
    figs.replaceChildren(...keep(
      fig(`${online}/${enabled}`, "cameras working", online < enabled ? "alerting" : ""),
      fig(span(r.uptime), "running since start"),
      r.disk ? fig(fmtSize(r.disk.free), "free on the disk", diskPct < 0.1 ? "alerting" : "") : null,
      b ? fig(`${b.percent}%`, b.plugged ? "battery, on mains power" : "battery: POWER CUT", b.plugged ? "" : "alerting") : fig("Mains", "power"),
    ));
    banner.replaceChildren(...keep(
      b && !b.plugged ? h("div", { class: "banner red" }, `Power cut: CAMS is running on battery (${b.percent}%${b.seconds_left ? `, about ${span(b.seconds_left)} left` : ""}).`) : null,
      r.disk && diskPct < 0.1 ? h("div", { class: "banner red" }, "The disk is almost full. Old videos are being deleted: see Settings → Data and storage.") : null,
    ));
    camsBody.replaceChildren(...(r.cameras.length ? r.cameras.map((c) => h("tr", {},
      h("td", {}, h("span", { class: `dot ${c.status === "off" ? "" : c.status}` })),
      h("td", {}, h("b", {}, c.name)),
      h("td", { class: "num" }, c.status === "online" ? String(c.fps) : "–"),
      h("td", { class: "num" }, c.last_picture_ago == null ? "never" : c.last_picture_ago < 5 ? "now" : `${span(c.last_picture_ago)} ago`),
      h("td", {}, c.status === "off" ? h("span", { class: "faint" }, "Switched off") :
        c.offline_for ? h("span", { class: "error-text" }, `Offline for ${span(c.offline_for)}${c.error ? `: ${c.error}` : ""}`) :
        c.status === "online" ? h("span", { class: "tag teal" }, "OK") : h("span", { class: "faint" }, c.status)),
      h("td", {}, c.recording ? h("span", { class: "tag red" }, "REC") : c.last_recording ? h("span", { class: "faint" }, `last ${ago(c.last_recording)}`) : h("span", { class: "faint" }, "–")),
    )) : [h("tr", {}, h("td", { colspan: 6 }, h("span", { class: "muted" }, "No cameras yet.")))]));
    gaps.replaceChildren(r.downtime.length ? h("ul", { class: "plain-list" }, r.downtime.map((g) => h("li", {},
      h("b", {}, span(g.end_ts - g.start_ts)), ` from ${when(g.start_ts)} to ${when(g.end_ts)} `,
      h("span", { class: `tag ${g.reason === "unexpected" ? "amber" : ""}` }, g.reason === "unexpected" ? "power cut or crash" : "CAMS was closed")))) :
      h("p", { class: "muted", style: { margin: 0 } }, "CAMS has not been off since it was installed."));
    const yes = (ok, label) => h("span", { class: `tag ${ok ? "teal" : ""}` }, `${ok ? "✓" : "✗"} ${label}`);
    ai.replaceChildren(yes(r.ai.faces, "Face recognition"), yes(r.ai.people, "Person detection"), yes(r.ai.pose, "Body pose"), yes(r.ai.plates, "Number plates"));
    pc.replaceChildren(...keep(
      r.load ? `Computer load: processor ${Math.round(r.load.cpu)}%, memory ${Math.round(r.load.ram)}% (CAMS uses ${r.load.cams_ram_mb} MB). ` : "",
      `${r.frames_analysed.toLocaleString()} pictures checked by the AI since start. `,
      r.last_backup ? `Last backup ${ago(Number(r.last_backup))}.` : "No backup downloaded yet (Settings → Backup).",
    ));
    if (first) {
      first = false;
      const a = r.autostart;
      const box = h("input", { type: "checkbox", checked: a.on, disabled: !a.supported || !can("admin") });
      box.addEventListener("change", async () => {
        try { const x = await put("/api/health/autostart", { on: box.checked }); box.checked = x.on; toast(x.on ? "CAMS will start when this computer turns on" : "CAMS will not start by itself"); }
        catch (e) { box.checked = !box.checked; fail(e); }
      });
      auto.replaceChildren(
        h("label", { class: "check" }, box, "Start CAMS when this computer turns on"),
        h("p", { class: "hint", style: { margin: 0 } }, a.supported ? "So CAMS is back by itself after a power cut. Also set the computer to turn on when power returns: in the BIOS / UEFI settings this is called \"Restore on AC power loss\" or \"AC back: Power on\". A UPS keeps CAMS and the cameras going through short cuts." :
          "Available in the installed CAMS on Windows."),
        h("p", { class: "hint", style: { margin: 0 } }, "When CAMS starts after a power cut it writes an alert with how long it was off, so you know there is a gap in the recordings."));
    }
  }
  await load();
  const t = setInterval(() => load().catch(() => {}), 5000);
  return () => clearInterval(t);
}

// ======================================================================= visitors
const STAY = [[0.5, "30 minutes"], [1, "1 hour"], [2, "2 hours"], [4, "4 hours"], [8, "Until evening (8 hours)"]];
const PURPOSES = ["Meeting", "Parent / guardian", "Delivery", "Repair / contractor", "Interview", "Official visit"];

export async function visitors(el) {
  const { openEnrol } = await import("./enrol.js");
  const figs = h("div", { class: "figures" });
  const insideBox = h("div");
  const logBox = h("div");
  const daysSel = h("select", { "aria-label": "Period" }, [["1", "Today"], ["7", "Last 7 days"], ["30", "Last 30 days"]].map(([v, l]) => h("option", { value: v }, l)));
  daysSel.addEventListener("change", () => load().catch(fail));
  const op = can("operator");
  el.append(
    head("Visitors", "Check visitors in at the gate. CAMS recognises them on every camera, alerts if they go where they may not, or stay too long. Their face is forgotten when they check out.",
      op ? h("button", { class: "primary", onclick: () => checkIn() }, icon("plus"), "Check in a visitor") : null),
    figs,
    h("section", { class: "panel", style: { marginBottom: "16px" } }, h("div", { class: "panel-head" }, h("h2", {}, "Inside now")), insideBox),
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Visitor log"), daysSel), logBox),
  );

  const photo = (v) => v.has_photo ? h("img", { class: "thumb", src: `/api/visitors/${v.id}/photo?f=${v.faces}`, alt: v.full_name }) : h("span", { class: "thumb ph", "aria-hidden": "true", html: "" });
  const due = (v) => new Date(v.expected_out * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  async function load() {
    const all = await get(`/api/visitors?days=${daysSel.value}`);
    const inside = all.filter((v) => v.inside);
    const over = inside.filter((v) => v.overstaying);
    const fig = (n, label, cls = "") => h("div", { class: `figure ${cls}` }, h("span", { class: "num" }, n), h("span", {}, label));
    figs.replaceChildren(fig(inside.length, "inside now"), fig(over.length, "stayed too long", over.length ? "alerting" : ""),
      fig(all.length, daysSel.value === "1" ? "visitors today" : `visitors in ${daysSel.value} days`));
    insideBox.replaceChildren(inside.length ? h("ul", { class: "feed visitor-list" }, inside.map((v) => h("li", { class: v.overstaying ? "over" : "" },
      photo(v),
      h("div", { class: "grow" },
        h("div", { class: "who" }, v.full_name, v.badge ? h("span", { class: "tag", style: { marginLeft: "6px" } }, `Badge ${v.badge}`) : null),
        h("div", { class: "where" }, keep(v.host ? `Visiting ${v.host}` : "", v.purpose, v.from_where ? `from ${v.from_where}` : "", v.phone).filter(Boolean).join(" · ")),
        h("div", { class: "hint" }, `In since ${clock(v.checked_in_at)} · `, h("b", { class: v.overstaying ? "error-text" : "" }, v.overstaying ? `should have left at ${due(v)}` : `leaves by ${due(v)}`),
          v.last_seen ? ` · last seen at ${v.last_seen.building_name || v.last_seen.camera_name} ${ago(v.last_seen.last_seen)}` : " · not seen by a camera yet"),
        !v.faces ? h("div", { class: "hint error-text" }, "No face photo yet: cameras cannot recognise this visitor.") : null),
      h("div", { class: "row", style: { flexWrap: "wrap", justifyContent: "flex-end" } },
        op ? h("button", { class: `small${v.faces ? "" : " primary"}`, onclick: () => openEnrol({ id: v.person_id, full_name: v.full_name }, () => load()) }, icon("face"), v.faces ? "Face photos" : "Add face photo") : null,
        h("button", { class: "small", onclick: () => go("find", v.person_id) }, "Track"),
        h("button", { class: "small", onclick: () => printPass(v) }, "Pass"),
        op ? h("button", { class: "small", onclick: () => extend(v) }, "More time") : null,
        op ? h("button", { class: "small danger", onclick: async () => {
          if (!(await confirmBox(`Check out ${v.full_name}?`, "CAMS stops recognising them and forgets their face. The visit stays in the visitor log.", "Check out", false))) return;
          try { await post(`/api/visitors/${v.id}/checkout`); toast(`${v.full_name} checked out`); load(); } catch (e) { fail(e); }
        } }, "Check out") : null),
    ))) : emptyState("No visitors inside", "When a visitor arrives, press Check in a visitor."));
    const out = all.filter((v) => !v.inside);
    logBox.replaceChildren(out.length ? h("div", { style: { overflowX: "auto" } }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["", "Visitor", "Visiting", "In", "Out", "Stayed"].map((t) => h("th", {}, t)))),
      h("tbody", {}, out.map((v) => h("tr", {},
        h("td", {}, photo(v)),
        h("td", {}, h("b", {}, v.full_name), h("div", { class: "faint" }, keep(v.from_where, v.phone).join(" · "))),
        h("td", {}, v.host || "–", h("div", { class: "faint" }, v.purpose)),
        h("td", { class: "num" }, when(v.checked_in_at)),
        h("td", { class: "num" }, when(v.checked_out_at)),
        h("td", { class: "num" }, span(v.checked_out_at - v.checked_in_at))))))) :
      h("p", { class: "muted", style: { padding: "0 16px 12px" } }, "Nobody has checked out in this period."));
  }

  async function checkIn() {
    const [hosts, map] = await Promise.all([get("/api/visitors/hosts").catch(() => []), get("/api/map").catch(() => ({ buildings: [] }))]);
    const list = h("datalist", { id: "vis-hosts" }, hosts.map((p) => h("option", { value: p.full_name }, p.group_name)));
    const plist = h("datalist", { id: "vis-purposes" }, PURPOSES.map((p) => h("option", { value: p })));
    const blds = map.buildings.filter((b) => b.kind === "building");
    const body = h("div", { class: "stack" }, list, plist,
      h("div", { class: "grid2" },
        field("Visitor's name", h("input", { name: "full_name", required: true, autocomplete: "off" })),
        field("Phone", h("input", { name: "phone", type: "tel", autocomplete: "off" }))),
      h("div", { class: "grid2" },
        field("Visiting", h("input", { name: "host", list: "vis-hosts", placeholder: "Name of the staff member or office" })),
        field("Reason", h("input", { name: "purpose", list: "vis-purposes", placeholder: "e.g. Meeting" }))),
      h("div", { class: "grid3" },
        field("From", h("input", { name: "from_where", placeholder: "Company, school, family of..." })),
        field("Stays for", h("select", { name: "hours" }, STAY.map(([v, l]) => h("option", { value: v, selected: v === 2 }, l)))),
        field("Badge number", h("input", { name: "badge", placeholder: "optional" }))),
      field("ID or licence number", h("input", { name: "id_document", placeholder: "optional, only if your site asks for it" })),
      blds.length ? h("fieldset", { class: "stack", style: { border: "1px solid var(--line)", borderRadius: "var(--radius)", padding: "10px 12px" } },
        h("legend", { class: "hint" }, "May only go to (leave empty for anywhere visitors may go)"),
        h("div", { class: "row", style: { flexWrap: "wrap", gap: "6px 16px" } }, blds.map((b) => h("label", { class: "check" }, h("input", { type: "checkbox", value: b.id, "data-area": "1" }), b.name)))) : null,
      h("p", { class: "hint", style: { margin: 0 } }, "Next, take the visitor's face photo so the cameras can recognise them. Tell the visitor that cameras will follow them while they are inside."));
    dialog({ title: "Check in a visitor", body, actions: [{ label: "Cancel" }, { label: "Check in and take face photo", class: "primary", run: async () => {
      const v = formValues(body);
      v.allowed_areas = [...body.querySelectorAll("[data-area]:checked")].map((x) => Number(x.value));
      const r = await post("/api/visitors", v);
      toast(`${r.full_name} checked in`);
      load();
      openEnrol({ id: r.person_id, full_name: r.full_name }, () => load());
    } }] });
  }

  function extend(v) {
    const sel = h("select", {}, [[0.5, "30 more minutes"], [1, "1 more hour"], [2, "2 more hours"], [4, "4 more hours"]].map(([x, l]) => h("option", { value: x }, l)));
    dialog({ title: `More time for ${v.full_name}`, body: field("Stay", sel), actions: [{ label: "Cancel" }, { label: "Save", class: "primary", run: async () => {
      const base = Math.max(Date.now() / 1000, v.expected_out);
      await post(`/api/visitors/${v.id}/extend`, { until: base + Number(sel.value) * 3600 }); toast("Time extended"); load();
    } }] });
  }

  function printPass(v) {
    const w = window.open("", "_blank", "width=420,height=560");
    if (!w) return toast("Allow pop-up windows to print the pass.", "error");
    const site = document.title.replace(/^CAMS - /, "");
    const esc = (x) => String(x || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    w.document.write(`<!doctype html><meta charset="utf-8"><title>Visitor pass</title><style>
      body{font-family:system-ui,sans-serif;margin:0;padding:24px}
      .pass{border:3px solid #0f6e6a;border-radius:12px;padding:18px;max-width:320px;margin:auto;text-align:center}
      .top{background:#0f6e6a;color:#fff;margin:-18px -18px 14px;padding:10px;border-radius:8px 8px 0 0;font-weight:800;letter-spacing:.2em}
      img{width:140px;height:140px;object-fit:cover;border-radius:8px;background:#eee}
      h1{font-size:22px;margin:10px 0 4px} p{margin:4px 0;color:#333} .due{font-weight:700;font-size:18px;margin-top:10px}
      @media print{button{display:none}}</style>
      <div class="pass"><div class="top">VISITOR</div>
      ${v.has_photo ? `<img src="/api/visitors/${v.id}/photo" alt="">` : ""}
      <h1>${esc(v.full_name)}</h1><p>${esc(site)}</p><p>Visiting: <b>${esc(v.host || "–")}</b></p><p>${esc(v.purpose)}</p>
      <p>${new Date(v.checked_in_at * 1000).toLocaleString()}</p><p class="due">Valid until ${due(v)}</p>${v.badge ? `<p>Badge ${esc(v.badge)}</p>` : ""}</div>
      <p style="text-align:center"><button onclick="print()">Print</button></p>`);
    w.document.close();
  }

  await load();
  const t = setInterval(() => load().catch(() => {}), 10000);
  return () => clearInterval(t);
}
// ======================================================================= vehicles (number plates)
export async function vehicles(el) {
  const op = can("operator");
  const q = h("input", { type: "search", placeholder: "Plate or owner, e.g. T 123", "aria-label": "Search plates" });
  const daysSel = h("select", { "aria-label": "Period" }, [["1", "Today"], ["7", "Last 7 days"], ["30", "Last 30 days"]].map(([v, l]) => h("option", { value: v }, l)));
  const camSel = h("select", { "aria-label": "Camera" }, h("option", { value: "0" }, "All gate cameras"));
  const note = h("div");
  const logBox = h("div");
  const listBox = h("div");
  let timer = null;
  [daysSel, camSel].forEach((x) => x.addEventListener("change", () => load().catch(fail)));
  q.addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(() => load().catch(fail), 300); });
  el.append(
    head("Vehicles", "Number plates read by gate cameras: every car, bus and motorbike that came in or out, with the time and a picture of the plate.",
      op ? h("button", { onclick: () => addPlate() }, icon("plus"), "Add a plate to the list") : null),
    note,
    h("section", { class: "panel", style: { marginBottom: "16px" } }, h("div", { class: "panel-head" }, h("h2", {}, "Vehicle log"),
      h("div", { class: "row" }, q, camSel, daysSel)), logBox),
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Known and flagged plates")), listBox));

  const plateTag = (shown, kind) => h("span", { class: `plate${kind === "flagged" ? "" : " white"}` }, shown);
  let camsLoaded = false;

  async function load() {
    const r = await get(`/api/vehicles?days=${daysSel.value}&q=${encodeURIComponent(q.value)}&camera_id=${camSel.value}`);
    if (!camsLoaded) { camsLoaded = true; camSel.append(...r.cameras.map((c) => h("option", { value: c.id }, c.name))); }
    note.replaceChildren(...keep(
      !r.ai ? h("div", { class: "banner red" }, "The number plate AI is missing from this installation. Reinstall CAMS.") : null,
      r.ai && !r.cameras.length ? h("div", { class: "banner" }, "No camera reads number plates yet. Open Cameras → Activity rules for a gate camera and tick Read number plates. ",
        "Point the camera at the plates (not from too high, plates at least 20 pixels tall), and use a camera with good night vision.") : null));
    logBox.replaceChildren(r.rows.length ? h("div", { style: { overflowX: "auto" } }, h("table", { class: "list" },
      h("thead", {}, h("tr", {}, ["Plate", "", "Seen", "Camera", "Owner / note", ""].map((t) => h("th", {}, t)))),
      h("tbody", {}, r.rows.map((v) => h("tr", {},
        h("td", {}, plateTag(v.shown, v.list_kind), v.list_kind === "flagged" ? h("div", { class: "error-text", style: { fontSize: "12px" } }, "FLAGGED") : null),
        h("td", {}, v.image_path ? h("img", { class: "plate-crop", src: `/api/snapshots/${v.image_path}`, alt: `Plate ${v.shown}` }) : null),
        h("td", { class: "num" }, clock(v.first_seen), v.last_seen - v.first_seen > 20 ? h("div", { class: "faint" }, `until ${clock(v.last_seen)}`) : null),
        h("td", {}, v.camera_name),
        h("td", {}, v.owner || (v.list_kind ? "" : h("span", { class: "faint" }, "Unknown")), v.note ? h("div", { class: "faint" }, v.note) : null),
        h("td", {}, op && !v.list_kind ? h("div", { class: "row end" },
          h("button", { class: "small", onclick: () => addPlate(v.plate, "known") }, "Known"),
          h("button", { class: "small danger", onclick: () => addPlate(v.plate, "flagged") }, "Flag")) : null)))))) :
      h("p", { class: "muted", style: { padding: "0 16px 12px" } }, q.value ? "No plate matches." : "No vehicles read in this period."));
    const list = await get("/api/plates");
    listBox.replaceChildren(list.length ? h("ul", { class: "feed plate-list" }, list.map((l) => h("li", {},
      plateTag(l.shown, l.kind),
      h("div", { class: "grow" }, h("div", { class: "who" }, l.owner || (l.kind === "flagged" ? "Flagged vehicle" : "Known vehicle")),
        h("div", { class: "where" }, h("span", { class: `tag ${l.kind === "flagged" ? "red" : "teal"}` }, l.kind === "flagged" ? "Alert when seen" : "Known"), " ", l.note)),
      op ? h("div", { class: "row" }, h("button", { class: "small", onclick: () => addPlate(l.plate, l.kind, l) }, "Edit"),
        h("button", { class: "small danger", onclick: async () => { await del(`/api/plates/${l.id}`); load(); } }, "Remove")) : null))) :
      h("p", { class: "muted", style: { padding: "0 16px 12px" } }, "Add staff cars, school buses and delivery vans as known. Flag a plate to get an alert when it comes."));
  }

  function addPlate(plate = "", kind = "known", row = null) {
    const body = h("div", { class: "stack" },
      h("div", { class: "grid2" },
        field("Number plate", h("input", { name: "plate", value: plate, placeholder: "T 123 ABC", autocomplete: "off", style: { textTransform: "uppercase" } })),
        field("List", h("select", { name: "kind" }, [["known", "Known (staff, bus, delivery)"], ["flagged", "Flagged: alert when seen"]].map(([v, l]) => h("option", { value: v, selected: v === kind }, l))))),
      field("Owner", h("input", { name: "owner", value: row?.owner || "", placeholder: "e.g. Mr Mushi (Physics)" })),
      field("Note", h("input", { name: "note", value: row?.note || "", placeholder: "e.g. Not allowed after the incident on 3 May" })));
    dialog({ title: row ? "Edit plate" : "Add a plate", body, actions: [{ label: "Cancel" }, { label: "Save", class: "primary", run: async () => {
      const r = await post("/api/plates", formValues(body)); toast(`${r.shown} saved`); load();
    } }] });
  }

  await load();
  const t = setInterval(() => load().catch(() => {}), 8000);
  return () => clearInterval(t);
}
