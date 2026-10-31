// Activity AI screens: a person's day timeline, the daily report,
// and the Activity & routines page (routines, teaching the AI, place-and-time rules).
import { h, get, post, put, del, icon, toast, fail, dialog, confirmBox, field, formValues, CATEGORIES, PLURAL, cap, snapUrl } from "./util.js";
import { state, can, go } from "./app.js";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const KIND = {
  missed: ["red", "Missed"], out_of_place: ["red", "Out of place"], late: ["amber", "Late"], change: ["amber", "Change"],
  attended: ["teal", "On time"], not_seen: ["", "Not seen"], summary: ["", "Summary"],
};
const SOURCE = { ai: "AI", taught: "Taught", rule: "Your rule", corrected: "Corrected" };

const today = () => new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);
const shiftDay = (d, n) => { const t = new Date(`${d}T12:00:00`); t.setDate(t.getDate() + n); return t.toISOString().slice(0, 10); };
const hm = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const span = (a, b) => (b - a < 60 ? hm(a) : `${hm(a)} – ${hm(b)}`);
const mins = (s) => { const m = Math.round(s / 60); return m < 1 ? "<1 min" : m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60 ? `${m % 60} min` : ""}`.trim(); };
const imgUrl = (p) => (p ? snapUrl({ snapshot_path: p }) : null);

// append/replaceChildren would print "null" for missing optional parts
const keep = (...xs) => xs.flat().filter((x) => x !== null && x !== undefined && x !== false);

let statusP = null;
const status = () => (statusP ||= get("/api/activity/status").catch(() => ({ labels: {}, areas: [], purposes: {} })));
export function refreshActivityStatus() { statusP = null; }

function dayPicker(value, onchange) {
  const inp = h("input", { type: "date", value, max: today(), "aria-label": "Day" });
  inp.addEventListener("change", () => onchange(inp.value || today()));
  return h("div", { class: "row day-pick" },
    h("button", { class: "small", "aria-label": "Previous day", onclick: () => { inp.value = shiftDay(inp.value, -1); onchange(inp.value); } }, "‹"),
    inp,
    h("button", { class: "small", "aria-label": "Next day", onclick: () => { if (inp.value < today()) { inp.value = shiftDay(inp.value, 1); onchange(inp.value); } } }, "›"),
    h("button", { class: "small", onclick: () => { inp.value = today(); onchange(inp.value); } }, "Today"));
}

// ===================================================================== correct an entry
export async function correctDialog(entry, after) {
  const s = await status();
  const sel = h("select", { name: "label" }, Object.entries(s.labels).map(([k, v]) => h("option", { value: k, selected: k === entry.activity }, v)));
  const other = h("input", { name: "other", placeholder: "or type a new activity, e.g. Sweeping, Praying, Queueing" });
  const body = h("div", { class: "stack" },
    entry.image_path ? h("img", { src: imgUrl(entry.image_path), alt: "What the camera saw", class: "teach-img" }) : null,
    h("p", { class: "hint", style: { margin: 0 } }, `CAMS thought: ${entry.label}. Your answer teaches the AI: next time it sees something similar it will use your activity.`),
    field("What was the person doing?", sel), other);
  dialog({ title: "Correct this activity", body, actions: [{ label: "Cancel" }, { label: "Save and teach", class: "primary", run: async () => {
    const v = formValues(body);
    const label = v.other.trim() || v.label;
    await put(`/api/activity/entries/${entry.id}`, { label });
    refreshActivityStatus();
    toast("Thanks. CAMS learned from this example.");
    after?.();
  } }] });
}

// ===================================================================== person page panel
export function personDayPanel(p) {
  let day = today();
  const body = h("div", { class: "panel-body stack" });
  const panel = h("section", { class: "panel day-panel" },
    h("div", { class: "panel-head" }, h("h2", {}, "Day timeline"), dayPicker(day, (d) => { day = d; load(); })), body);
  async function load() {
    body.replaceChildren(h("p", { class: "muted" }, "Loading..."));
    let d;
    try { d = await get(`/api/people/${p.id}/day?day=${day}`); } catch (e) { body.replaceChildren(h("p", { class: "error-text" }, e.message)); return; }
    const notes = d.notes.filter((n) => n.kind !== "summary");
    const summary = d.notes.find((n) => n.kind === "summary")?.text || d.summary;
    const list = h("ul", { class: "timeline act-timeline" });
    for (const e of d.entries) {
      list.append(h("li", { class: `src-${e.source}` },
        e.image_path ? h("img", { class: "act-thumb", src: imgUrl(e.image_path), alt: "", loading: "lazy" }) : null,
        h("div", { class: "act-main" },
          h("div", { class: "num faint" }, span(e.start_ts, e.end_ts)),
          h("b", {}, e.label),
          h("div", { class: "muted" }, [e.area_name || e.camera_name, e.end_ts - e.start_ts >= 60 ? mins(e.end_ts - e.start_ts) : null].filter(Boolean).join(" · ")),
          h("div", { class: "row", style: { gap: "6px", marginTop: "4px" } },
            h("span", { class: `tag ${e.source === "ai" ? "" : "teal"}`, title: `How CAMS decided${e.confidence ? `, ${Math.round(e.confidence * 100)}% sure` : ""}` }, SOURCE[e.source] || e.source),
            can("operator") ? h("button", { class: "small ghost", onclick: () => correctDialog(e, load) }, "Correct") : null))));
    }
    const habits = h("div", { class: "habits" }, h("h3", {}, "Usual pattern (last 3 weeks)"), h("ul", {}, d.habits.sentences.map((s) => h("li", {}, s))));
    body.replaceChildren(...keep(
      h("p", { class: "day-summary" }, summary),
      notes.length ? h("ul", { class: "notes" }, notes.map((n) => h("li", {}, h("span", { class: `tag ${KIND[n.kind]?.[0] || ""}` }, KIND[n.kind]?.[1] || n.kind), " ", n.text))) : null,
      h("div", { class: "day-grid" },
        d.entries.length ? list : h("div", { class: "empty" }, h("h3", {}, "No activity recorded"),
          h("p", {}, "The activity AI writes here when a camera recognises this person's face and can see their body.")),
        habits)));
  }
  load();
  return panel;
}

// ===================================================================== daily report
export async function report(el) {
  let day = today();
  const figs = h("div", { class: "figures" });
  const table = h("div");
  const catSel = h("select", { "aria-label": "Type of person" }, h("option", { value: "" }, "Everyone"), CATEGORIES.map((c) => h("option", { value: c }, PLURAL[c])));
  const grpSel = h("select", { "aria-label": "Class or department" }, h("option", { value: "" }, "All classes"));
  get("/api/people/groups").then((gs) => grpSel.append(...gs.map((g) => h("option", { value: g }, g)))).catch(() => {});
  const allBox = h("input", { type: "checkbox" });
  [catSel, grpSel, allBox].forEach((x) => x.addEventListener("change", load));
  const qs = () => `day=${day}&category=${encodeURIComponent(catSel.value)}&group=${encodeURIComponent(grpSel.value)}&all=${allBox.checked}`;

  el.append(
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", {}, "Daily report"),
      h("p", {}, "Who was seen, where and when, and the routines they kept or missed. Kept short so it opens fast.")),
      h("button", { onclick: () => window.print() }, "Print"),
      h("button", { onclick: () => { location.href = `/api/report/daily.csv?${qs()}`; } }, "Download CSV")),
    h("div", { class: "row report-filters" }, dayPicker(day, (d) => { day = d; load(); }), catSel, grpSel,
      h("label", { class: "check" }, allBox, "Include people not seen"),
      can("operator") ? h("button", { class: "small", title: "Check routines that have ended and write the day summaries now", onclick: async (e) => {
        e.currentTarget.disabled = true;
        try { const r = await post(`/api/report/daily/summaries?day=${day}`); toast(`Notes written for ${r.people} people`); load(); } catch (x) { fail(x); }
        e.currentTarget.disabled = false;
      } }, "Write notes now") : null),
    figs, table);

  async function load() {
    table.replaceChildren(h("p", { class: "muted" }, "Loading..."));
    let r;
    try { r = await get(`/api/report/daily?${qs()}`); } catch (e) { table.replaceChildren(h("p", { class: "error-text" }, e.message)); return; }
    const fig = (n, label, cls = "") => h("div", { class: `figure ${cls}` }, h("span", { class: "num" }, n), h("span", {}, label));
    figs.replaceChildren(fig(`${r.seen}/${r.enrolled}`, "people seen"), fig(r.missed, "missed routines", r.missed ? "alerting" : ""),
      fig(r.late, "late"), fig(r.out_of_place, "out of place", r.out_of_place ? "alerting" : ""));
    if (!r.people.length) {
      table.replaceChildren(h("div", { class: "panel" }, h("div", { class: "empty" }, h("h3", {}, "Nobody to show for this day"),
        h("p", {}, "People appear here once a camera recognises them. Tick Include people not seen to list everyone."))));
      return;
    }
    table.replaceChildren(h("section", { class: "panel" }, h("table", { class: "list report-table" },
      h("thead", {}, h("tr", {}, ["Person", "First seen", "Last seen", "Where", "Routines", "Notes"].map((t) => h("th", {}, t)))),
      h("tbody", {}, r.people.map((p) => h("tr", {},
        h("td", {}, h("button", { class: "ghost name", onclick: () => go("person", p.person_id) }, p.name), h("div", { class: "faint" }, [cap(p.category), p.group].filter(Boolean).join(", "))),
        h("td", { class: "num" }, p.first_seen ? hm(p.first_seen) : "–", p.first_place ? h("div", { class: "faint" }, p.first_place) : null),
        h("td", { class: "num" }, p.last_seen ? hm(p.last_seen) : "–", p.last_place ? h("div", { class: "faint" }, p.last_place) : null),
        h("td", {}, p.places.map((x) => h("div", {}, `${x.place || "camera"} `, h("span", { class: "faint" }, mins(x.minutes * 60))))),
        h("td", {}, h("div", { class: "row", style: { gap: "4px" } },
          p.attended ? h("span", { class: "tag teal" }, `${p.attended} on time`) : null,
          p.late ? h("span", { class: "tag amber" }, `${p.late} late`) : null,
          p.missed ? h("span", { class: "tag red" }, `${p.missed} missed`) : null,
          p.out_of_place ? h("span", { class: "tag red" }, `${p.out_of_place} out of place`) : null)),
        h("td", { class: "report-notes" }, p.notes.length ? p.notes.map((n) => h("div", {}, n)) : h("span", { class: "faint" }, p.first_seen ? "Nothing unusual." : "Not seen by any camera."))))))));
  }
  load();
}

// ===================================================================== Activity & routines page
export async function activityPage(el) {
  let tab = "routines";
  const s = await status();
  const tabs = h("div", { class: "seg tabs", role: "tablist" });
  const body = h("div", { class: "stack" });
  el.append(...keep(
    h("div", { class: "page-head" }, h("div", { class: "grow" }, h("h1", {}, "Activity & routines"),
      h("p", {}, "Tell CAMS where people should be and when, teach it new activities, and set place-and-time rules. It then writes a timeline and notes for every recognised person."))),
    s.available ? null : h("div", { class: "banner red" }, "The activity AI needs the person-detection model. Reinstall CAMS to add it."),
    tabs, body));
  const TABS = [["routines", "Routines"], ["teach", "Teach the AI"], ["rules", "Place & time rules"], ["settings", "How it works"]];
  const draw = () => {
    tabs.replaceChildren(...TABS.map(([id, l]) => h("button", { role: "tab", "aria-pressed": String(tab === id), onclick: () => { tab = id; draw(); } }, l)));
    ({ routines: routinesTab, teach: teachTab, rules: rulesTab, settings: settingsTab })[tab](body);
  };
  draw();
}

function placeLabel(r, areas, purposes) {
  if (r.area_ids?.length) return areas.filter((a) => r.area_ids.includes(a.id)).map((a) => a.name).join(", ") || "(deleted area)";
  return purposes[r.purpose] ? `Any ${purposes[r.purpose].toLowerCase()}` : "–";
}
const daysLabel = (d) => (!d?.length || d.length === 7 ? "Every day" : d.join(",") === "0,1,2,3,4" ? "Mon–Fri" : d.map((x) => DAYS[x]).join(" "));

function placeChooser(areas, purposes, chosen = [], purpose = "") {
  const box = h("div", { class: "stack" });
  const mode = h("select", { "aria-label": "Place by" },
    h("option", { value: "kind", selected: !chosen.length }, "Any place of this kind"),
    h("option", { value: "areas", selected: !!chosen.length }, "These areas on the map"));
  const kind = h("select", { name: "purpose", "aria-label": "Kind of place" }, Object.entries(purposes).filter(([k]) => k).map(([k, v]) => h("option", { value: k, selected: k === purpose }, v)));
  const list = h("div", { class: "chips" }, areas.length ? areas.map((a) => h("label", {}, h("input", { type: "checkbox", value: a.id, checked: chosen.includes(a.id) }), a.name))
    : h("span", { class: "hint" }, "No areas drawn yet. Draw them in the Campus builder."));
  const sync = () => { kind.classList.toggle("hidden", mode.value !== "kind"); list.classList.toggle("hidden", mode.value !== "areas"); };
  mode.addEventListener("change", sync); sync();
  box.append(mode, kind, list);
  box.value = () => mode.value === "kind" ? { area_ids: [], purpose: kind.value } : { area_ids: [...list.querySelectorAll("input:checked")].map((i) => +i.value), purpose: "" };
  return box;
}

function daysChooser(days = [0, 1, 2, 3, 4]) {
  const box = h("div", { class: "chips" }, DAYS.map((d, i) => h("label", {}, h("input", { type: "checkbox", value: i, checked: days.includes(i) }), d)));
  box.value = () => [...box.querySelectorAll("input:checked")].map((i) => +i.value);
  return box;
}

// ------------------------------------------------------------------ routines
const TEMPLATES = [
  { name: "Breakfast", start: "06:30", end: "07:15", purpose: "dining" },
  { name: "Lunch", start: "13:00", end: "13:45", purpose: "dining" },
  { name: "Supper", start: "18:30", end: "19:15", purpose: "dining" },
  { name: "Morning assembly", start: "07:20", end: "07:45", purpose: "assembly" },
  { name: "Evening prep", start: "19:30", end: "21:00", purpose: "classroom" },
  { name: "Not in dormitory during lessons", start: "08:00", end: "15:30", purpose: "dormitory", expect: "absent" },
];

async function routinesTab(body) {
  const s = await status();
  const rows = await get("/api/routines");
  const add = (tpl) => routineDialog(tpl, () => routinesTab(body));
  body.replaceChildren(...keep(
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Routines"),
      can("operator") ? h("button", { class: "primary small", onclick: () => add() }, icon("plus"), "Add routine") : null),
      rows.length ? h("table", { class: "list" },
        h("thead", {}, h("tr", {}, ["Routine", "When", "Where", "Who", "Expect", "", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows.map((r) => h("tr", { class: r.enabled ? "" : "muted" },
          h("td", {}, h("b", {}, r.name), r.alert ? h("span", { class: "tag amber", style: { marginLeft: "6px" } }, "alerts") : null),
          h("td", {}, `${r.start}–${r.end}`, h("div", { class: "faint" }, daysLabel(r.days))),
          h("td", {}, placeLabel(r, s.areas, s.purposes)),
          h("td", {}, [...r.who_categories.map((c) => PLURAL[c]), ...r.who_groups, ...(r.who_people.length ? [`${r.who_people.length} people`] : [])].join(", ") || "Everyone"),
          h("td", {}, r.expect === "absent" ? "Should NOT be there" : "Should be there"),
          h("td", {}, can("operator") ? h("button", { class: "small", title: "Check this routine for today now", onclick: async () => {
            try { const x = await post(`/api/routines/${r.id}/check`); toast(`Checked ${x.checked} people: ${Object.entries(x.counts).map(([k, n]) => `${n} ${k.replace("_", " ")}`).join(", ") || "nobody in scope was seen"}`); } catch (e) { fail(e); }
          } }, "Check now") : null),
          h("td", {}, can("operator") ? h("div", { class: "row", style: { gap: "4px" } },
            h("button", { class: "small", onclick: () => routineDialog(r, () => routinesTab(body)) }, "Edit"),
            h("button", { class: "small danger", onclick: async () => { if (await confirmBox(`Delete ${r.name}?`, "Its notes are removed from people's timelines too.")) { await del(`/api/routines/${r.id}`); routinesTab(body); } } }, "Delete")) : null))))) :
        h("div", { class: "empty" }, h("h3", {}, "No routines yet"), h("p", {}, "A routine says where people should be at a time, like Lunch in the dining hall at 13:00. CAMS then notes who kept it, who came late and who missed it."))),
    can("operator") ? h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h3", {}, "Quick start")),
      h("div", { class: "panel-body row" }, TEMPLATES.map((t) => h("button", { class: "small", onclick: () => add({ ...t, days: [0, 1, 2, 3, 4], area_ids: [], who_categories: ["student"], who_groups: [], who_people: [], expect: t.expect || "present", grace_min: 10, alert: false, enabled: true, _new: true }) }, `+ ${t.name}`)))) : null,
    h("p", { class: "hint" }, "Routines are checked a couple of minutes after they end. Only people a camera saw that day are checked, so absent people are not marked as missing a meal. \"Not seen in the dining hall\" can also mean no camera saw them there: put cameras at the doors of places you check.")));
}

async function routineDialog(r, after) {
  const s = await status();
  const isNew = !r || r._new;
  r = r || { name: "", start: "13:00", end: "13:45", days: [0, 1, 2, 3, 4], area_ids: [], purpose: "dining", expect: "present", who_categories: ["student"], who_groups: [], who_people: [], grace_min: 10, alert: false, enabled: true };
  const groups = await get("/api/people/groups").catch(() => []);
  const place = placeChooser(s.areas, s.purposes, r.area_ids, r.purpose);
  const days = daysChooser(r.days);
  const cats = h("div", { class: "chips" }, CATEGORIES.map((c) => h("label", {}, h("input", { type: "checkbox", value: c, checked: r.who_categories.includes(c) }), PLURAL[c])));
  const grps = h("div", { class: "chips" }, groups.length ? groups.map((g) => h("label", {}, h("input", { type: "checkbox", value: g, checked: r.who_groups.includes(g) }), g)) : h("span", { class: "hint" }, "No classes or departments yet."));
  const body = h("div", { class: "stack" },
    field("Name", h("input", { name: "name", value: r.name, placeholder: "e.g. Lunch, Morning assembly, Evening prep" })),
    h("div", { class: "grid3" }, field("From", h("input", { type: "time", name: "start", value: r.start })), field("Until", h("input", { type: "time", name: "end", value: r.end })),
      field("Late after (minutes)", h("input", { type: "number", name: "grace_min", value: r.grace_min, min: 0, max: 240 }))),
    h("div", {}, h("div", { class: "hint" }, "Days"), days),
    h("div", {}, h("div", { class: "hint" }, "Place"), place),
    field("People should", h("select", { name: "expect" }, h("option", { value: "present", selected: r.expect !== "absent" }, "be there (note who missed it or came late)"),
      h("option", { value: "absent", selected: r.expect === "absent" }, "NOT be there (note who was there)"))),
    h("div", {}, h("div", { class: "hint" }, "Who (leave all empty for everyone)"), cats, grps),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "alert", checked: !!r.alert }), "Also raise an alert when someone misses it or is out of place"),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "enabled", checked: r.enabled !== false && r.enabled !== 0 }), "Routine is on"));
  dialog({ title: isNew ? "Add a routine" : `Edit ${r.name}`, body, wide: true, actions: [{ label: "Cancel" }, { label: isNew ? "Add routine" : "Save", class: "primary", run: async () => {
    const v = formValues(body);
    const payload = { name: v.name, start: v.start, end: v.end, grace_min: +v.grace_min || 0, expect: v.expect, alert: v.alert, enabled: v.enabled, days: days.value(), ...place.value(),
      who_categories: [...cats.querySelectorAll("input:checked")].map((i) => i.value), who_groups: [...grps.querySelectorAll("input:checked")].map((i) => i.value), who_people: r.who_people || [] };
    if (isNew) await post("/api/routines", payload); else await put(`/api/routines/${r.id}`, payload);
    toast("Routine saved"); after?.();
  } }] });
}

// ------------------------------------------------------------------ teach
async function teachTab(body) {
  refreshActivityStatus();
  const s = await status();
  let filter = { mode: "new", value: "" };
  const grid = h("div", { class: "teach-grid" });
  const filt = h("select", { "aria-label": "Show" },
    h("option", { value: "new|" }, "New pictures (not checked yet)"),
    h("optgroup", { label: "What the AI said" }, Object.entries(s.labels).map(([k, v]) => h("option", { value: `auto|${k}` }, `AI said: ${v}`))),
    h("optgroup", { label: "What you taught" }, s.taught.map((t) => h("option", { value: `label|${t.key}` }, `Taught: ${t.label} (${t.examples})`))));
  filt.addEventListener("change", () => { const [m, v] = filt.value.split("|"); filter = { mode: m, value: v }; loadGrid(); });
  const newAct = h("input", { placeholder: "New activity, e.g. Sweeping, Praying, Queueing for food", "aria-label": "New activity" });
  body.replaceChildren(
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Teach CAMS what people are doing")),
      h("div", { class: "panel-body stack" },
        h("p", { style: { margin: 0 } }, "CAMS already knows common activities (eating, sitting, walking, running, reading, using a phone, playing sport...). Teach it your own, or fix its mistakes: click a picture's activity below. After 3 examples of an activity CAMS starts recognising it by itself, and it gets better with every example you add."),
        h("div", { class: "row" }, newAct, h("button", { onclick: async () => {
          if (!newAct.value.trim()) return;
          try { await post("/api/activity/types", { label: newAct.value.trim() }); newAct.value = ""; refreshActivityStatus(); teachTab(body); toast("Activity added. Now label at least 3 pictures with it."); } catch (e) { fail(e); }
        } }, icon("plus"), "Add activity")),
        h("div", { class: "chips" }, Object.entries(s.labels).map(([k, v]) => {
          const t = s.taught.find((x) => x.key === k);
          const builtin = s.builtin.includes(k);
          return h("span", { class: `tag ${t ? "teal" : ""}` }, v, t ? ` · ${t.examples} taught` : "", !builtin && can("operator") ? h("button", { class: "tag-x", "aria-label": `Remove ${v}`, onclick: async () => {
            if (await confirmBox(`Remove ${v}?`, "Its taught examples become unlabelled. Timeline entries keep their name.", "Remove")) { await del(`/api/activity/types/${encodeURIComponent(k)}`); refreshActivityStatus(); teachTab(body); }
          } }, "×") : null);
        })))),
    h("div", { class: "row" }, h("b", {}, "Pictures"), filt), grid);

  async function loadGrid() {
    grid.replaceChildren(h("p", { class: "muted" }, "Loading..."));
    const qs = filter.mode === "new" ? "unlabelled=true" : filter.mode === "auto" ? `auto=${encodeURIComponent(filter.value)}` : `label=${encodeURIComponent(filter.value)}`;
    const rows = await get(`/api/activity/examples?${qs}&limit=90`);
    if (!rows.length) {
      grid.replaceChildren(h("div", { class: "empty" }, h("h3", {}, "No pictures here yet"), h("p", {}, "CAMS saves a picture each time it notes a new activity for a recognised person.")));
      return;
    }
    const labels = Object.entries(s.labels);
    grid.replaceChildren(...rows.map((x) => {
      const sel = h("select", { "aria-label": "Activity" }, h("option", { value: "" }, x.label ? "Remove label" : "This is..."),
        labels.map(([k, v]) => h("option", { value: k, selected: k === x.label }, v)));
      sel.addEventListener("change", async () => {
        try { await put(`/api/activity/examples/${x.id}`, { label: sel.value || null }); card.classList.add("done"); toast(sel.value ? `Taught: ${s.labels[sel.value] || sel.value}` : "Label removed"); refreshActivityStatus(); } catch (e) { fail(e); }
      });
      const card = h("div", { class: `teach-card ${x.label ? "done" : ""}` },
        h("img", { src: imgUrl(x.image_path), alt: "", loading: "lazy" }),
        h("div", { class: "teach-meta" }, h("b", {}, x.full_name || "Unknown"), h("span", { class: "faint" }, new Date(x.ts * 1000).toLocaleString([], { dateStyle: "short", timeStyle: "short" }))),
        h("div", { class: "faint" }, `AI said: ${x.auto_text}`), sel,
        h("div", { class: "row", style: { gap: "4px" } },
          h("button", { class: "small", title: "The AI was right", onclick: async () => {
            try { await put(`/api/activity/examples/${x.id}`, { label: x.auto_label }); card.classList.add("done"); sel.value = x.auto_label; refreshActivityStatus(); } catch (e) { fail(e); }
          } }, "Correct ✓"),
          h("button", { class: "small ghost", title: "Not useful: remove this picture", onclick: async () => { await del(`/api/activity/examples/${x.id}`); card.remove(); } }, "Remove")));
      return card;
    }));
  }
  loadGrid();
}

// ------------------------------------------------------------------ place & time rules
async function rulesTab(body) {
  const s = await status();
  const rows = await get("/api/activity/rules");
  body.replaceChildren(
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Place & time rules"),
      can("operator") ? h("button", { class: "primary small", onclick: () => ruleDialog(null, () => rulesTab(body)) }, icon("plus"), "Add rule") : null),
      h("div", { class: "panel-body" }, h("p", { class: "hint", style: { marginTop: 0 } }, "Rules name what people are doing from where and when they are, for things a camera cannot tell from the body alone. Example: in the Chapel from 07:00 to 07:30 on weekdays = Morning prayers. Rules win over the AI.")),
      rows.length ? h("table", { class: "list" },
        h("thead", {}, h("tr", {}, ["Activity", "Where", "When", "Body", ""].map((t) => h("th", {}, t)))),
        h("tbody", {}, rows.map((r) => h("tr", { class: r.enabled ? "" : "muted" },
          h("td", {}, h("b", {}, r.label)), h("td", {}, placeLabel(r, s.areas, s.purposes)),
          h("td", {}, `${r.start}–${r.end}`, h("div", { class: "faint" }, daysLabel(r.days))),
          h("td", {}, { any: "Any", sitting: "Sitting", standing: "Standing", moving: "Moving" }[r.body]),
          h("td", {}, can("operator") ? h("div", { class: "row", style: { gap: "4px" } },
            h("button", { class: "small", onclick: () => ruleDialog(r, () => rulesTab(body)) }, "Edit"),
            h("button", { class: "small danger", onclick: async () => { await del(`/api/activity/rules/${r.id}`); refreshActivityStatus(); rulesTab(body); } }, "Delete")) : null))))) :
        h("div", { class: "empty" }, h("p", {}, "No rules yet."))));
}

async function ruleDialog(r, after) {
  const s = await status();
  r = r || { activity: "", start: "07:00", end: "07:30", days: [0, 1, 2, 3, 4], area_ids: [], purpose: "worship", body: "any", enabled: true };
  const place = placeChooser(s.areas, s.purposes, r.area_ids, r.purpose);
  const days = daysChooser(r.days.length ? r.days : [0, 1, 2, 3, 4, 5, 6]);
  const list = h("datalist", { id: "act-names" }, Object.values(s.labels).map((v) => h("option", { value: v })));
  const body = h("div", { class: "stack" },
    field("Activity", h("input", { name: "activity", value: r.label || r.activity, list: "act-names", placeholder: "e.g. Morning prayers, Assembly, Lesson, Queueing for food" })), list,
    h("div", { class: "grid2" }, field("From", h("input", { type: "time", name: "start", value: r.start })), field("Until", h("input", { type: "time", name: "end", value: r.end }))),
    h("div", {}, h("div", { class: "hint" }, "Days"), days),
    h("div", {}, h("div", { class: "hint" }, "Place"), place),
    field("Only when the person is", h("select", { name: "body" }, [["any", "doing anything"], ["sitting", "sitting"], ["standing", "standing"], ["moving", "walking or running"]].map(([k, l]) => h("option", { value: k, selected: k === r.body }, l)))),
    h("label", { class: "check" }, h("input", { type: "checkbox", name: "enabled", checked: r.enabled !== false && r.enabled !== 0 }), "Rule is on"));
  dialog({ title: r.id ? "Edit rule" : "Add a place & time rule", body, wide: true, actions: [{ label: "Cancel" }, { label: "Save", class: "primary", run: async () => {
    const v = formValues(body);
    const payload = { activity: v.activity.trim(), start: v.start, end: v.end, body: v.body, enabled: v.enabled, days: days.value(), ...place.value() };
    if (r.id) await put(`/api/activity/rules/${r.id}`, payload); else await post("/api/activity/rules", payload);
    refreshActivityStatus(); toast("Rule saved"); after?.();
  } }] });
}

// ------------------------------------------------------------------ settings / how it works
async function settingsTab(body) {
  refreshActivityStatus();
  const s = await status();
  const set = await get("/api/settings").catch(() => ({}));
  const on = h("input", { type: "checkbox", checked: set.activity_ai !== "0", disabled: !can("admin") });
  const when = h("input", { type: "time", value: set.daily_summary_time || "20:30", disabled: !can("admin") });
  const save = async () => { try { await put("/api/settings", { activity_ai: on.checked ? "1" : "0", daily_summary_time: when.value || "20:30" }); toast("Saved"); } catch (e) { fail(e); } };
  on.addEventListener("change", save); when.addEventListener("change", save);
  body.replaceChildren(...keep(
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "Settings")),
      h("div", { class: "panel-body stack" },
        h("label", { class: "check" }, on, "Activity AI is on (write a timeline for every recognised person)"),
        field("Write daily summaries and \"changes from usual\" notes at", when),
        h("div", { class: "row" },
          h("span", { class: `tag ${s.available ? "teal" : "red"}` }, s.available ? "Object detection ready" : "Object detection missing"),
          h("span", { class: `tag ${s.pose ? "teal" : "amber"}` }, s.pose ? "Body pose AI ready" : "Body pose AI missing (activities use objects and movement only)"),
          h("span", { class: "tag" }, `${s.today_entries} timeline entries today`)),
        can("admin") ? null : h("p", { class: "hint" }, "Only an admin can change these."))),
    h("section", { class: "panel" }, h("div", { class: "panel-head" }, h("h2", {}, "How CAMS works out what people are doing")),
      h("div", { class: "panel-body how" },
        h("ol", {},
          h("li", {}, h("b", {}, "Who: "), "a camera recognises the face, then follows that person's body even when they turn away."),
          h("li", {}, h("b", {}, "Body: "), "a pose AI finds 33 body points: sitting or standing, lying down, a hand at the mouth, a hand raised, head down over a book."),
          h("li", {}, h("b", {}, "Things: "), "the object AI sees plates, cups, spoons, food, books, phones, laptops, balls, chairs, beds and tables near the person or in their hands."),
          h("li", {}, h("b", {}, "Movement and place: "), "walking or running speed, and what the area is used for (set it in the Campus builder)."),
          h("li", {}, h("b", {}, "Decision: "), "your place & time rules first, then activities you taught, then built-in knowledge.")),
        h("p", {}, "Notes describe what cameras saw. They are not judgements about a person. A missed routine can mean the person was somewhere without a camera, so check before acting on a note."),
        h("p", { class: "hint" }, "Everything runs on this PC. Pictures and timelines are deleted after the number of days set in Settings, except pictures you used to teach the AI. Deleting a person deletes their timeline and pictures too.")))));
}
