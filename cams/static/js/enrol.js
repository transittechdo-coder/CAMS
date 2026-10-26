// 360-degree enrolment: seven face angles used for recognition, plus back and top
// of the head kept as reference pictures for guards. Webcam (automatic), any CAMS
// camera, photos, or a short turn-around video.
import { h, get, upload, post, dialog, toast, fail, POSE_ICON } from "./util.js";
const poseIcon = (id) => POSE_ICON[id] || POSE_ICON[id.includes("left") ? "left" : id.includes("right") ? "right" : id === "back" || id === "top" ? "up" : "front"];

export const POSES = [
  { id: "front", label: "Front", say: "Look straight at the camera" },
  { id: "three_quarter_left", label: "Half left", say: "Turn your head a little to your left" },
  { id: "left", label: "Left side", say: "Turn your head fully to your left" },
  { id: "three_quarter_right", label: "Half right", say: "Turn your head a little to your right" },
  { id: "right", label: "Right side", say: "Turn your head fully to your right" },
  { id: "up", label: "Up", say: "Lift your chin and look up a little" },
  { id: "down", label: "Down", say: "Lower your chin and look down a little" },
  { id: "back", label: "Back", say: "Turn around so your back faces the camera", ref: true },
  { id: "top", label: "Top", say: "Bow your head so the top faces the camera", ref: true },
];
export const POSE_LABEL = Object.fromEntries(POSES.map((p) => [p.id, p.label]));

export function openEnrol(person, onDone) {
  let stream = null, timer = null, closed = false, source = "webcam";
  const done = new Map();       // pose -> image url
  let current = 0;
  let goodRuns = 0;

  const video = h("video", { autoplay: true, playsinline: true, muted: true, class: "mirror" });
  const camImg = h("img", { alt: "Camera picture", class: "hidden" });
  const oval = h("div", { class: "oval" });
  const prompt = h("div", { class: "prompt" });
  const viewer = h("div", { class: "viewer" }, video, camImg, oval, prompt);
  const statusLine = h("p", { class: "hint", role: "status" });
  const poseList = h("ul", { class: "poses" });
  const camSelect = h("select", { "aria-label": "Camera" });
  const sourceSeg = h("div", { class: "seg", role: "group", "aria-label": "Picture source" });
  const fileInput = h("input", { type: "file", accept: "image/*", multiple: true, class: "hidden" });
  const captureBtn = h("button", { class: "primary", onclick: () => capture(true) }, "Take picture now");

  function drawPoses() {
    poseList.replaceChildren(...POSES.map((p, i) => h("li", { class: done.has(p.id) ? "done" : i === current ? "current" : "" },
      done.has(p.id) ? h("img", { src: done.get(p.id), alt: "" }) : h("span", { class: "ph", html: poseIcon(p.id) }),
      h("div", {}, h("b", {}, p.label), h("div", { class: "hint" }, done.has(p.id) ? "Saved" : p.ref ? "Reference picture" : p.say)),
    )));
    const pose = POSES[current];
    prompt.textContent = pose ? pose.say : "All angles saved";
    captureBtn.textContent = pose && pose.ref ? `Take ${pose.label.toLowerCase()} picture` : "Take picture now";
  }

  async function startWebcam() {
    stopAll();
    source = "webcam";
    video.classList.remove("hidden"); camImg.classList.add("hidden"); camSelect.classList.add("hidden");
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
      video.srcObject = stream;
      statusLine.textContent = "Position the face inside the oval. CAMS takes the picture automatically.";
      timer = setInterval(() => check(), 700);
    } catch (e) {
      statusLine.textContent = "This computer's webcam is not available. Use a CAMS camera or upload photos instead.";
    }
  }

  async function startCamera() {
    stopAll();
    source = "camera";
    video.classList.add("hidden"); camImg.classList.remove("hidden"); camSelect.classList.remove("hidden");
    const cams = (await get("/api/cameras")).filter((c) => c.enabled);
    if (!cams.length) { statusLine.textContent = "No cameras are set up yet."; return; }
    if (!camSelect.options.length) camSelect.replaceChildren(...cams.map((c) => h("option", { value: c.id }, c.name)));
    camImg.src = `/api/cameras/${camSelect.value}/stream?fps=6`;
    statusLine.textContent = "Ask the person to stand close to the camera and follow the instruction, then press Take picture now.";
  }

  function stopAll() {
    clearInterval(timer); timer = null;
    stream?.getTracks().forEach((t) => t.stop()); stream = null;
    camImg.removeAttribute("src");
  }

  function grab() {
    const c = document.createElement("canvas");
    c.width = video.videoWidth; c.height = video.videoHeight;
    if (!c.width) return null;
    c.getContext("2d").drawImage(video, 0, 0);
    return new Promise((r) => c.toBlob(r, "image/jpeg", 0.92));
  }

  let busy = false;
  async function check() {
    if (busy || closed || current >= POSES.length || POSES[current].ref) {
      if (POSES[current]?.ref) { oval.classList.remove("good"); statusLine.textContent = "Back and top pictures are taken by hand: press the button when the person is in position."; }
      return;
    }
    busy = true;
    try {
      const blob = await grab();
      if (!blob) return;
      const fd = new FormData(); fd.append("file", blob, "f.jpg");
      const r = await upload("/api/faces/check", fd);
      const want = POSES[current].id;
      if (r.faces.length !== 1) { oval.classList.remove("good"); goodRuns = 0; statusLine.textContent = r.faces.length ? "Only one person should be in the picture." : "No face found yet. Move closer and face the light."; return; }
      const f = r.faces[0];
      const ok = f.angle === want && f.quality >= 0.45;
      oval.classList.toggle("good", ok);
      statusLine.textContent = ok ? "Hold still..." : f.quality < 0.45 ? "Picture is blurry or dark. Hold still, face the light." : POSES[current].say + ".";
      goodRuns = ok ? goodRuns + 1 : 0;
      if (goodRuns >= 2) { goodRuns = 0; await capture(false, blob); }
    } catch (e) { statusLine.textContent = e.message; }
    finally { busy = false; }
  }

  async function capture(manual, blob) {
    if (current >= POSES.length) return;
    const pose = POSES[current].id;
    captureBtn.disabled = true;
    try {
      let res;
      if (source === "camera") {
        res = await post(`/api/people/${person.id}/samples/from-camera/${camSelect.value}?angle=${pose}`);
      } else {
        blob = blob || (await grab());
        if (!blob) throw new Error("No picture from the webcam yet.");
        const fd = new FormData(); fd.append("files", blob, `${pose}.jpg`); fd.append("angle", pose);
        res = (await upload(`/api/people/${person.id}/samples`, fd)).added[0];
      }
      if (res.warning) toast(res.warning, "alert");
      done.set(pose, res.reference ? `/api/references/${res.id}/image` : `/api/samples/${res.id}/image?t=${Date.now()}`);
      current = POSES.findIndex((p) => !done.has(p.id));
      if (current < 0) current = POSES.length;
      drawPoses();
      if (current >= POSES.length) { statusLine.textContent = "All 360° angles are saved. You can close this window."; stopAll(); }
    } catch (e) { if (manual) fail(e); else statusLine.textContent = e.message; }
    finally { captureBtn.disabled = false; }
  }

  const videoInput = h("input", { type: "file", accept: "video/*", class: "hidden" });
  videoInput.addEventListener("change", async () => {
    const f = videoInput.files[0];
    if (!f) return;
    statusLine.textContent = "Reading the video and picking the best picture for each angle. This can take a minute...";
    const fd = new FormData(); fd.append("file", f);
    try {
      const r = await upload(`/api/people/${person.id}/samples/video`, fd);
      for (const a of r.added) done.set(a.angle, a.reference ? `/api/references/${a.id}/image` : `/api/samples/${a.id}/image`);
      current = POSES.findIndex((p) => !done.has(p.id));
      if (current < 0) current = POSES.length;
      drawPoses();
      statusLine.textContent = `${r.added.length} angles taken from the video.` + (r.missing.length ? ` Still missing: ${r.missing.map((m) => POSE_LABEL[m]).join(", ")}.` : "");
    } catch (e) { fail(e); statusLine.textContent = ""; }
    videoInput.value = "";
  });
  const angleSel = h("select", { "aria-label": "Which side do the photos show?" },
    h("option", { value: "" }, "Photos: detect angle automatically"),
    POSES.map((p) => h("option", { value: p.id }, `Photos show: ${p.label}`)));

  fileInput.addEventListener("change", async () => {
    if (!fileInput.files.length) return;
    const fd = new FormData();
    [...fileInput.files].forEach((f) => fd.append("files", f));
    if (angleSel.value) fd.append("angle", angleSel.value);
    try {
      const r = await upload(`/api/people/${person.id}/samples`, fd);
      for (const a of r.added) { done.set(a.angle, a.reference ? `/api/references/${a.id}/image` : `/api/samples/${a.id}/image`); if (a.warning) toast(a.warning, "alert"); }
      r.errors.forEach((e) => toast(`${e.file}: ${e.error}`, "error"));
      current = Math.max(0, POSES.findIndex((p) => !done.has(p.id)));
      if (done.size >= POSES.length) current = POSES.length;
      drawPoses();
      toast(`${r.added.length} photo${r.added.length === 1 ? "" : "s"} added`);
    } catch (e) { fail(e); }
    fileInput.value = "";
  });

  const btns = [["webcam", "This PC's webcam", startWebcam], ["camera", "A CAMS camera", startCamera]];
  sourceSeg.append(...btns.map(([id, label, fn]) => h("button", { "aria-pressed": String(id === "webcam"), onclick: (e) => {
    sourceSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b === e.currentTarget))); fn();
  } }, label)));
  camSelect.classList.add("hidden");
  camSelect.addEventListener("change", startCamera);

  drawPoses();
  dialog({
    title: `Capture face: ${person.full_name}`,
    wide: true,
    body: h("div", { class: "stack" },
      h("div", { class: "row" }, sourceSeg, camSelect),
      h("div", { class: "row" }, angleSel, h("button", { onclick: () => fileInput.click() }, "Upload photos"), fileInput,
        h("button", { onclick: () => videoInput.click(), title: "Film the person slowly turning all the way around, 10-20 seconds" }, "Upload turn-around video"), videoInput),
      h("div", { class: "enrol" },
        h("div", { class: "stack" }, viewer, statusLine, h("div", { class: "row" }, captureBtn,
          h("button", { onclick: () => { current = (current + 1) % POSES.length; drawPoses(); } }, "Skip this angle"))),
        h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "360° views"), poseList,
          h("p", { class: "hint", style: { marginTop: "8px" } }, "Face views are used for recognition: more angles = better results on high or side cameras. Back and top cannot identify a person; they are kept so guards can compare by eye.")),
      ),
    ),
    actions: [{ label: "Done", class: "primary" }],
    onClose: () => { closed = true; stopAll(); onDone?.(); },
  });
  startWebcam();
}
