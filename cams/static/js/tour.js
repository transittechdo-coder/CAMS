// First-time guide: a short tour of the screen, plus the written "How to use CAMS" page.
import { h, put } from "./util.js";

export const GUIDE = [
  {
    title: "Add your cameras", page: "cameras", button: "Open Cameras",
    text: [
      "Open Cameras and press Add camera. Use Help me build the address: choose the brand (Hikvision, Dahua and others), type the camera's IP address, username and password. Press Test connection to see a picture.",
      "Not sure of the IP? Press Find on network and CAMS lists the cameras it can see. USB webcams use the address 0, 1, 2. Cameras connected to an NVR use the NVR's IP with the channel number.",
      "Tick Restricted area for places like the staff room or server room, so CAMS alerts you about anyone it does not know.",
    ],
  },
  {
    title: "Build your campus map", page: "builder", button: "Open Campus builder",
    text: [
      "In the Campus builder, add a picture of your compound if you have one (a plan or a satellite screenshot) and type its real width and depth in metres.",
      "Draw each building, gate, field and parking area with the rectangle or shape tool. Give buildings their height and number of floors to see them in 3D.",
      "Then click each camera in the list and click where it is mounted. Drag the amber handle so the cone points where the camera looks.",
    ],
  },
  {
    title: "Add people and capture their faces", page: "people", button: "Open People",
    text: [
      "Add people one at a time, or import your class list as a CSV file with the columns full_name, person_code, category and group_name.",
      "Open a person and press Capture face. Using this PC's webcam, CAMS asks the person to look straight, left, right, up and down and takes each picture automatically when the pose is right. You can also capture from any CAMS camera, or upload photos.",
      "Record consent before enrolling. For students under 18, consent comes from a parent or guardian.",
    ],
  },
  {
    title: "Find a person", page: "find", button: "Open Find a person",
    text: [
      "Type a name or ID number. CAMS shows when and where the person was last seen, their movements on the map (2D or 3D), and a timeline for today or the last days.",
      "You can also search with a photo, for example of a visitor. Always check the result with your own eyes before acting on it.",
    ],
  },
  {
    title: "Keep it safe and fair", page: "settings", button: "Open Settings",
    text: [
      "Give each staff member their own account with the lowest role they need. Every search and change is written in the activity log.",
      "Faces of people who are not enrolled are blurred. Sightings are deleted automatically after the number of days you choose. When someone leaves, untick Active, or delete them to erase all their data.",
      "CAMS runs completely on this computer. Nothing is sent to the internet.",
    ],
  },
];

const STEPS = [
  { sel: '.nav-btn[data-page="cameras"]', title: "1. Connect cameras", text: "Start here. Add IP, Ethernet, NVR or USB cameras, or let CAMS find them on your network." },
  { sel: '.nav-btn[data-page="builder"]', title: "2. Draw your campus", text: "Draw buildings and gates, then put each camera on the map. You can view it in 3D too." },
  { sel: '.nav-btn[data-page="people"]', title: "3. Enrol people", text: "Add students and staff, record consent, and capture their faces from five angles." },
  { sel: '.nav-btn[data-page="find"]', title: "4. Find anyone", text: "Type a name to see where and when they were last seen, and their path on the map." },
  { sel: '.nav-btn[data-page="alerts"]', title: "5. Alerts", text: "Watch-list people, strangers in restricted areas and offline cameras show up here." },
  { sel: '.nav-btn[data-page="guide"]', title: "Need help later?", text: "The full step-by-step guide is always here." },
];

export function tourWanted(state) {
  return !state.status.onboarding_done;
}

export function startTour(state, force = false) {
  let i = 0;
  const visible = STEPS.filter((s) => document.querySelector(s.sel));
  if (!visible.length) return;
  const hole = h("div", { class: "tour-hole" });
  const card = h("div", { class: "tour-card", role: "dialog", "aria-modal": "true", "aria-label": "Getting started" });
  document.body.append(hole, card);

  const finish = () => {
    hole.remove(); card.remove();
    window.removeEventListener("resize", place);
    document.removeEventListener("keydown", onKey);
    state.status.onboarding_done = true;
    put("/api/settings", { onboarding_done: "1" }).catch(() => {});
  };
  const onKey = (e) => {
    if (e.key === "Escape") finish();
    if (e.key === "ArrowRight") next();
    if (e.key === "ArrowLeft" && i > 0) { i--; place(); }
  };
  const next = () => { if (++i >= visible.length) finish(); else place(); };

  function place() {
    const step = visible[i];
    const target = document.querySelector(step.sel);
    const r = target.getBoundingClientRect();
    Object.assign(hole.style, { left: `${r.left - 6}px`, top: `${r.top - 6}px`, width: `${r.width + 12}px`, height: `${r.height + 12}px` });
    const left = Math.min(window.innerWidth - 360, r.right + 18);
    const top = Math.max(12, Math.min(window.innerHeight - 220, r.top - 20));
    Object.assign(card.style, window.innerWidth < 760 ? { left: "12px", top: `${r.bottom + 14}px` } : { left: `${left}px`, top: `${top}px` });
    const nextBtn = h("button", { class: "primary", onclick: next }, i === visible.length - 1 ? "Finish" : "Next");
    card.replaceChildren(
      h("div", { class: "step" }, `${i + 1} of ${visible.length}`),
      h("h3", {}, step.title), h("p", {}, step.text),
      h("div", { class: "row end" }, h("button", { class: "ghost", onclick: finish }, "Skip tour"), nextBtn),
    );
    nextBtn.focus();
  }
  window.addEventListener("resize", place);
  document.addEventListener("keydown", onKey);
  place();
}
