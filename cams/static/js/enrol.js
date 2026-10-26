// Face enrolment: capture a person from five angles (front, left, right, up, down)
// so CAMS can recognise them from any camera position.
import { h, get, upload, post, dialog, toast, fail, POSE_ICON } from "./util.js";

const POSES = [
  { id: "front", say: "Look straight at the camera" },
  { id: "left", say: "Turn your head slowly to your left" },
  { id: "right", say: "Turn your head slowly to your right" },
  { id: "up", say: "Lift your chin and look up a little" },
  { id: "down", say: "Lower your chin and look down a little" },
];

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
      done.has(p.id) ? h("img", { src: done.get(p.id), alt: "" }) : h("span", { class: "ph", html: POSE_ICON[p.id] }),
      h("div", {}, h("b", {}, p.id[0].toUpperCase() + p.id.slice(1)), h("div", { class: "hint" }, done.has(p.id) ? "Saved" : p.say)),
    )));
    const pose = POSES[current];
    prompt.textContent = pose ? pose.say : "All angles saved";
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
    if (busy || closed || current >= POSES.length) return;
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
      done.set(pose, `/api/samples/${res.id}/image?t=${Date.now()}`);
      current = POSES.findIndex((p) => !done.has(p.id));
      if (current < 0) current = POSES.length;
      drawPoses();
      if (current >= POSES.length) { statusLine.textContent = "All five angles are saved. You can close this window."; stopAll(); }
    } catch (e) { if (manual) fail(e); else statusLine.textContent = e.message; }
    finally { captureBtn.disabled = false; }
  }

  fileInput.addEventListener("change", async () => {
    if (!fileInput.files.length) return;
    const fd = new FormData();
    [...fileInput.files].forEach((f) => fd.append("files", f));
    try {
      const r = await upload(`/api/people/${person.id}/samples`, fd);
      for (const a of r.added) { done.set(a.angle, `/api/samples/${a.id}/image`); if (a.warning) toast(a.warning, "alert"); }
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
      h("div", { class: "row" }, sourceSeg, camSelect, h("button", { onclick: () => fileInput.click() }, "Upload photos instead"), fileInput),
      h("div", { class: "enrol" },
        h("div", { class: "stack" }, viewer, statusLine, h("div", { class: "row" }, captureBtn,
          h("button", { onclick: () => { current = (current + 1) % POSES.length; drawPoses(); } }, "Skip this angle"))),
        h("div", {}, h("h3", { style: { marginBottom: "8px" } }, "Five angles"), poseList,
          h("p", { class: "hint", style: { marginTop: "8px" } }, "More angles = better recognition on high or side-mounted cameras. Front alone also works.")),
      ),
    ),
    actions: [{ label: "Done", class: "primary" }],
    onClose: () => { closed = true; stopAll(); onDone?.(); },
  });
  startWebcam();
}
