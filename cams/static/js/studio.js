// CAMS Map Studio: draw the campus in 3D like a game level editor.
// Shapes stack on top of each other, roofs snap onto buildings, walls are drawn
// by clicking points, and the camera flies freely (right-drag + W A S D).
import * as THREE from "three";
import { TransformControls } from "/static/vendor/TransformControls.js";
import { h, get, put, patch, post, toast, fail, confirmBox, logoMark, mouseSwapped } from "./util.js";
import { TYPES, CATS, MATERIALS, defaults, buildObject, disposeGroup, setupLights, fitSunShadow, material } from "./world3d.js";
import { CameraRig } from "./camrig.js";

const SWATCHES = ["#e9e4da", "#e6e1d6", "#cfc8bb", "#9fb4c8", "#5b8def", "#0b7a75", "#3f8a3a", "#6aa84f",
  "#c27a5a", "#b5533c", "#8f3f30", "#d0763a", "#e3a21a", "#c9b067", "#8a5a36", "#55595e", "#8e9ba5", "#2d2f33", "#ffffff", "#c23a2b"];
const FIXED = new Set(["tree", "pine", "palm", "bush", "rock", "car", "bus", "bench", "table", "lamp", "flag", "tank", "goal", "sign",
  "label", "person", "door", "window", "ladder", "column"]);
const ON_WALL = new Set(["door", "window", "sign", "ladder"]);
const ROOFLIKE = new Set(["roofGable", "roofHip", "roofShed", "roofFlat", "roofPyramid", "roofDome", "roofMetal", "floor"]);
const HOSTS = new Set(["box", "building", "room", "floor", "roofFlat", "wedge"]);
const FLOOR_H = 3.2;

const TOOL_HINTS = {
  select: "Click a shape to choose it, drag it to slide it. Drag empty space to turn the view. Shift-click chooses more than one.",
  move: "Drag the arrows to move. Hold the coloured square to slide on the ground.",
  rotate: "Drag a ring to turn the shape.",
  scale: "Drag a handle to make the shape bigger or smaller.",
  paint: "Drag on the ground to paint. [ and ] change the brush size.",
  erasePaint: "Drag on the ground to rub out paint.",
  scatter: "Drag to plant trees and bushes.",
  freehand: "Drag to draw a path, road, hedge or fence by hand.",
  eraser: "Drag over shapes to delete them.",
  measure: "Click two points to measure the distance.",
  picker: "Click a shape to copy its colour and material.",
};

export async function openStudio({ onClose } = {}) {
  const [mapData, sceneDoc] = await Promise.all([get("/api/map"), get("/api/map/scene")]);
  const W = mapData.width_m, H = mapData.height_m;
  const doc = {
    version: 1, objects: Array.isArray(sceneDoc.objects) ? sceneDoc.objects : [], paint: sceneDoc.paint || null,
    view: sceneDoc.view || null, settings: { grid: 1, snap: true, showAreas: true, showImage: true, sun: 40, ...(sceneDoc.settings || {}) },
  };
  let nextId = doc.objects.reduce((m, o) => Math.max(m, +String(o.id).replace(/\D/g, "") || 0), 0) + 1;
  doc.objects.forEach((o) => { if (!o.id) o.id = `o${nextId++}`; });

  // ---------------------------------------------------------------- layout
  const root = h("div", { class: "studio", role: "application", "aria-label": "Map Studio" });
  const viewBox = h("div", { class: "st-view" });
  const left = h("aside", { class: "st-left" });
  const right = h("aside", { class: "st-right" });
  const top = h("header", { class: "st-top" });
  const status = h("footer", { class: "st-status" });
  const hint = h("div", { class: "st-hint" });
  viewBox.append(hint);
  root.append(top, left, viewBox, right, status);
  document.body.append(root);
  document.body.classList.add("studio-open");

  // ---------------------------------------------------------------- three
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.localClippingEnabled = false;
  viewBox.prepend(renderer.domElement);
  const canvas = renderer.domElement;
  canvas.tabIndex = 0;
  const scene = new THREE.Scene();
  scene.background = new THREE.Color("#cfe3ee");
  scene.fog = new THREE.Fog("#cfe3ee", Math.max(W, H) * 2, Math.max(W, H) * 6);
  // weak or software graphics: start without shadows so the view stays smooth
  if (doc.settings.shadows == null) doc.settings.shadows = !slowGraphics(renderer);
  renderer.shadowMap.enabled = doc.settings.shadows;
  if (!doc.settings.shadows) renderer.setPixelRatio(1);
  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 20000);
  const sun = setupLights(scene);
  fitSunShadow(sun, W / 2, H / 2, Math.max(W, H));

  const world = new THREE.Group(); scene.add(world);       // drawn objects
  const extras = new THREE.Group(); scene.add(extras);     // areas, CCTV cameras
  const helpers = new THREE.Group(); scene.add(helpers);   // selection boxes, ghosts, measure

  // ground: the uploaded site plan + painted layer
  const outer = new THREE.Mesh(new THREE.PlaneGeometry(W * 8, H * 8).rotateX(-Math.PI / 2).translate(W / 2, -0.03, H / 2),
    new THREE.MeshStandardMaterial({ color: "#b9c7a8", roughness: 1 }));
  outer.receiveShadow = true; scene.add(outer);
  const PX = 2048, PY = Math.max(256, Math.round((2048 * H) / W));
  const paintCanvas = Object.assign(document.createElement("canvas"), { width: PX, height: PY });
  const paintCtx = paintCanvas.getContext("2d");
  const groundCanvas = Object.assign(document.createElement("canvas"), { width: PX, height: PY });
  const groundCtx = groundCanvas.getContext("2d");
  const groundTex = new THREE.CanvasTexture(groundCanvas); groundTex.colorSpace = THREE.SRGBColorSpace; groundTex.anisotropy = 8;
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(W, H).rotateX(-Math.PI / 2).translate(W / 2, 0, H / 2),
    new THREE.MeshStandardMaterial({ map: groundTex, roughness: 1 }));
  ground.receiveShadow = true; ground.userData.ground = true; scene.add(ground);
  let baseImage = null;
  function composeGround() {
    groundCtx.fillStyle = "#dfe7d8"; groundCtx.fillRect(0, 0, PX, PY);
    if (baseImage && doc.settings.showImage) groundCtx.drawImage(baseImage, 0, 0, PX, PY);
    groundCtx.drawImage(paintCanvas, 0, 0);
    groundTex.needsUpdate = true;
  }
  if (mapData.image) { const im = new Image(); im.onload = () => { baseImage = im; composeGround(); }; im.src = mapData.image; }
  if (doc.paint) { const im = new Image(); im.onload = () => { paintCtx.drawImage(im, 0, 0, PX, PY); composeGround(); }; im.src = doc.paint; }
  composeGround();

  let grid;
  function makeGrid() {
    if (grid) { scene.remove(grid); grid.geometry.dispose(); }
    const span = Math.ceil(Math.max(W, H) / 10) * 10;
    grid = new THREE.GridHelper(span, Math.round(span / Math.max(1, doc.settings.grid >= 1 ? doc.settings.grid * 5 : 5)), 0x5d7385, 0x9aaab6);
    grid.material.transparent = true; grid.material.opacity = 0.35; grid.material.depthWrite = false;
    grid.position.set(span / 2, levelY() + 0.02, span / 2);
    scene.add(grid);
  }

  // ---------------------------------------------------------------- state
  const groups = new Map();         // id -> THREE.Group
  let selection = [];               // object ids
  let selCam = null;                // CCTV camera id
  let tool = "select";
  let level = 0;                    // working floor
  let cutOn = false;
  let dirty = false;
  let history = [], future = [];
  let clipboard = [];
  const brush = { size: 3, color: "#6aa84f", opacity: 0.9, mat: null, scatter: "mix", freehand: "path", newColor: null };
  const byId = (id) => doc.objects.find((o) => o.id === id);
  const levelY = () => level * FLOOR_H;

  function markDirty() { dirty = true; saveBtn.classList.add("primary"); saveBtn.textContent = "Save"; }
  function snapshot() { history.push(JSON.stringify(doc.objects)); if (history.length > 120) history.shift(); future = []; }
  function restore(json) { doc.objects = JSON.parse(json); rebuildAll(); select([]); markDirty(); }
  function undo() { if (!history.length) return; future.push(JSON.stringify(doc.objects)); restore(history.pop()); }
  function redo() { if (!future.length) return; history.push(JSON.stringify(doc.objects)); restore(future.pop()); }

  function addGroup(o) {
    const g = buildObject(o);
    world.add(g); groups.set(o.id, g);
    return g;
  }
  function rebuild(o) {
    const old = groups.get(o.id);
    if (old) { world.remove(old); disposeGroup(old); }
    const g = addGroup(o);
    if (tc.object === old) tc.attach(g);
    return g;
  }
  function rebuildAll() {
    for (const g of groups.values()) { world.remove(g); disposeGroup(g); }
    groups.clear();
    doc.objects.forEach(addGroup);
    refreshOutline();
  }

  function newObject(type, over = {}) {
    const o = { id: `o${nextId++}`, ...defaults(type), pos: [0, 0, 0], rot: [0, 0, 0], ...over };
    if (brush.newColor && !over.color && !["tree", "pine", "palm", "bush", "label", "sign"].includes(type)) o.color = brush.newColor;
    if (brush.mat && !over.mat && !["tree", "pine", "palm", "label"].includes(type)) o.mat = brush.mat;
    doc.objects.push(o);
    addGroup(o);
    markDirty();
    return o;
  }
  function removeObjects(ids) {
    if (!ids.length) return;
    snapshot();
    for (const id of ids) {
      const g = groups.get(id);
      if (g) { if (tc.object === g) tc.detach(); world.remove(g); disposeGroup(g); groups.delete(id); }
    }
    doc.objects = doc.objects.filter((o) => !ids.includes(o.id));
    select(selection.filter((s) => !ids.includes(s)));
    markDirty();
  }
  function syncFromGroup(o) {
    const g = groups.get(o.id);
    o.pos = [round(g.position.x), round(g.position.y), round(g.position.z)];
    o.rot = [deg(g.rotation.x), deg(g.rotation.y), deg(g.rotation.z)];
  }
  const round = (v, n = 100) => Math.round(v * n) / n;
  const deg = (r) => round(THREE.MathUtils.radToDeg(r), 10);
  const snap = (v, step = doc.settings.grid) => (doc.settings.snap ? Math.round(v / step) * step : v);

  // ---------------------------------------------------------------- CCTV cameras + access areas
  const camMarks = new Map();
  function drawExtras() {
    for (const c of [...extras.children]) { extras.remove(c); disposeGroup(c); }
    camMarks.clear();
    if (doc.settings.showAreas) {
      for (const b of mapData.buildings) {
        if (b.polygon.length < 3) continue;
        const shape = new THREE.Shape(b.polygon.map(([x, y]) => new THREE.Vector2(x, -y)));
        const geo = new THREE.ExtrudeGeometry(shape, { depth: 0.08, bevelEnabled: false }).rotateX(-Math.PI / 2);
        const m = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: b.color, transparent: true, opacity: 0.28, depthWrite: false }));
        m.position.y = 0.03; m.userData.area = b.id;
        extras.add(m);
        const pts = b.polygon.concat([b.polygon[0]]).map(([x, z]) => new THREE.Vector3(x, 0.12, z));
        extras.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color: b.color, dashSize: 1, gapSize: 0.6 })).computeLineDistances());
      }
    }
    for (const c of mapData.cameras) {
      if (c.map_x == null) continue;
      const g = new THREE.Group();
      const body = new THREE.Mesh(new THREE.BoxGeometry(0.35, 0.3, 0.6), new THREE.MeshStandardMaterial({ color: c.live?.status === "offline" ? "#c23a2b" : "#0b7a75" }));
      const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.1, 0.12, 0.12, 14).rotateX(Math.PI / 2).translate(0, 0, -0.34), new THREE.MeshStandardMaterial({ color: "#14304a" }));
      const fov = THREE.MathUtils.degToRad(c.fov || 90), R = 12;
      const wedgeShape = new THREE.Shape([new THREE.Vector2(0, 0), new THREE.Vector2(Math.sin(-fov / 2) * R, -Math.cos(fov / 2) * R), new THREE.Vector2(Math.sin(fov / 2) * R, -Math.cos(fov / 2) * R)]);
      const wedge = new THREE.Mesh(new THREE.ShapeGeometry(wedgeShape).rotateX(Math.PI / 2), new THREE.MeshBasicMaterial({ color: "#00998c", transparent: true, opacity: 0.18, side: THREE.DoubleSide, depthWrite: false }));
      wedge.position.y = -0.2; wedge.scale.z = -1;
      wedge.rotation.x = 0.35;
      [body, lens].forEach((m) => { m.userData.camId = c.id; m.castShadow = true; });
      g.add(body, lens, wedge);
      g.userData.camId = c.id;
      const bld = mapData.buildings.find((b) => b.id === c.building_id);
      const fh = bld && bld.kind === "building" ? bld.height_m / Math.max(1, bld.floors) : FLOOR_H;
      g.position.set(c.map_x, (c.floor || 0) * fh + 2.6, c.map_y);
      g.rotation.y = -THREE.MathUtils.degToRad(c.direction || 0);
      extras.add(g);
      camMarks.set(c.id, g);
    }
  }

  // ---------------------------------------------------------------- transform gizmo
  const pivot = new THREE.Object3D(); scene.add(pivot);
  const tc = new TransformControls(camera, canvas);
  tc.setSize(0.9);
  scene.add(tc.getHelper());
  let multiStart = null;
  tc.addEventListener("dragging-changed", (e) => {
    rig.enabled = !e.value;
    if (e.value) {
      if (tc.object?.userData.camId == null) snapshot();
      if (tc.object === pivot) multiStart = { inv: pivot.matrixWorld.clone().invert(), items: selection.map((id) => ({ id, m: groups.get(id).matrixWorld.clone() })) };
    } else {
      finishTransform();
    }
  });
  tc.addEventListener("objectChange", () => {
    if (tc.object === pivot && multiStart) {
      pivot.updateMatrixWorld();
      for (const it of multiStart.items) {
        const g = groups.get(it.id);
        const m = pivot.matrixWorld.clone().multiply(multiStart.inv).multiply(it.m);
        m.decompose(g.position, g.quaternion, new THREE.Vector3());
        g.rotation.setFromQuaternion(g.quaternion, "YXZ");
      }
    }
    updateBoxes();
  });
  function finishTransform() {
    const obj = tc.object;
    if (!obj) return;
    if (obj.userData.camId != null) {
      const id = obj.userData.camId;
      const dir = ((-THREE.MathUtils.radToDeg(obj.rotation.y) % 360) + 360) % 360;
      patch(`/api/cameras/${id}/place`, { map_x: round(obj.position.x, 10), map_y: round(obj.position.z, 10), direction: Math.round(dir) })
        .then(() => { const c = mapData.cameras.find((x) => x.id === id); Object.assign(c, { map_x: obj.position.x, map_y: obj.position.z, direction: dir }); toast("Camera position saved"); })
        .catch(fail);
      return;
    }
    if (obj === pivot) {
      selection.forEach((id) => syncFromGroup(byId(id)));
      multiStart = null;
    } else {
      const o = byId(obj.userData.objId);
      if (!o) return;
      if (obj.scale.x !== 1 || obj.scale.y !== 1 || obj.scale.z !== 1) {
        o.size = [round(Math.max(0.05, o.size[0] * obj.scale.x)), round(Math.max(0.02, o.size[1] * obj.scale.y)), round(Math.max(0.02, o.size[2] * obj.scale.z))];
        obj.scale.set(1, 1, 1);
        syncFromGroup(o);
        rebuild(o);
      } else syncFromGroup(o);
    }
    markDirty(); updateBoxes(); drawProps();
  }
  function applySnapToGizmo() {
    tc.setTranslationSnap(doc.settings.snap ? doc.settings.grid : null);
    tc.setRotationSnap(doc.settings.snap ? THREE.MathUtils.degToRad(15) : null);
    tc.setScaleSnap(doc.settings.snap ? 0.1 : null);
  }

  // ---------------------------------------------------------------- selection
  const boxes = [];
  function updateBoxes() {
    boxes.forEach((b) => { helpers.remove(b); b.geometry.dispose(); });
    boxes.length = 0;
    for (const id of selection) {
      const g = groups.get(id); if (!g) continue;
      const b = new THREE.BoxHelper(g, 0xf0b13a); b.material.depthTest = false; b.renderOrder = 30;
      helpers.add(b); boxes.push(b);
    }
  }
  function attachGizmo() {
    tc.detach();
    const mode = { move: "translate", rotate: "rotate", scale: "scale" }[tool];
    if (selCam != null && camMarks.get(selCam) && (mode === "translate" || mode === "rotate")) {
      tc.attach(camMarks.get(selCam)); tc.setMode(mode); tc.showX = mode === "translate"; tc.showZ = mode === "translate"; tc.showY = mode === "rotate";
      return;
    }
    tc.showX = tc.showY = tc.showZ = true;
    if (!mode || !selection.length) return;
    const locked = selection.some((id) => byId(id)?.locked);
    if (locked) return;
    if (selection.length === 1) {
      tc.attach(groups.get(selection[0])); tc.setMode(mode); tc.setSpace(mode === "translate" ? "world" : "local");
    } else {
      if (mode === "scale") return;
      const box = new THREE.Box3(); selection.forEach((id) => box.expandByObject(groups.get(id)));
      pivot.position.copy(box.getCenter(new THREE.Vector3())); pivot.position.y = box.min.y; pivot.rotation.set(0, 0, 0); pivot.scale.set(1, 1, 1);
      pivot.updateMatrixWorld();
      tc.attach(pivot); tc.setMode(mode); tc.setSpace("world");
      if (mode === "rotate") { tc.showX = false; tc.showZ = false; }
    }
  }
  function select(ids, cam = null) {
    selection = ids.filter((id) => groups.has(id));
    selCam = cam;
    updateBoxes(); attachGizmo(); drawProps(); refreshOutline();
  }

  // ---------------------------------------------------------------- picking
  const ray = new THREE.Raycaster();
  function setRay(cx, cy) {
    const r = canvas.getBoundingClientRect();
    ray.setFromCamera(new THREE.Vector2(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1), camera);
  }
  const cutY = () => (cutOn ? levelY() + FLOOR_H - 0.05 : Infinity);
  function hitObjects(cx, cy, { cams = false } = {}) {
    setRay(cx, cy);
    const targets = [world]; if (cams) targets.push(extras);
    const hits = ray.intersectObjects(targets, true).filter((x) => {
      const ud = x.object.userData;
      if (!(ud.objId || ud.camId != null)) return false;
      if (x.point.y > cutY() + 0.01) return false;
      return visibleChain(x.object);
    });
    for (const x of hits) {
      if (x.object.userData.objId && byId(x.object.userData.objId)?.locked && tool !== "picker") continue;
      const n = x.face ? x.face.normal.clone().transformDirection(x.object.matrixWorld) : new THREE.Vector3(0, 1, 0);
      return { id: x.object.userData.objId, camId: x.object.userData.camId, point: x.point, normal: n };
    }
    return null;
  }
  function visibleChain(o) { for (let p = o; p; p = p.parent) if (!p.visible) return false; return true; }
  function planeHit(cx, cy, y = levelY()) {
    setRay(cx, cy);
    const p = new THREE.Vector3();
    return ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), -y), p) ? p : null;
  }
  // Where would a new shape stand if dropped under the cursor?
  function surfaceAt(cx, cy) {
    const hit = hitObjects(cx, cy);
    const ph = planeHit(cx, cy);
    if (hit && (!ph || hit.point.distanceTo(camera.position) <= ph.distanceTo(camera.position) + 0.01)) {
      if (hit.normal.y > 0.5) return { point: hit.point.clone(), baseY: hit.point.y, hostId: hit.id, normal: hit.normal };
      return { point: hit.point.clone(), baseY: floorAt(hit.point.x + hit.normal.x * 0.05, hit.point.z + hit.normal.z * 0.05, hit.point.y + 0.05) ?? levelY(), hostId: hit.id, normal: hit.normal, side: true };
    }
    if (ph) return { point: ph, baseY: levelY(), hostId: null, normal: new THREE.Vector3(0, 1, 0) };
    return null;
  }
  const down = new THREE.Raycaster();
  down.camera = camera;
  function floorAt(x, z, fromY) {
    down.set(new THREE.Vector3(x, fromY, z), new THREE.Vector3(0, -1, 0));
    down.far = 1e5;
    for (const x2 of down.intersectObjects(world.children, true)) {
      if (x2.object.isSprite || !visibleChain(x2.object)) continue;
      const n = x2.face ? x2.face.normal.clone().transformDirection(x2.object.matrixWorld) : null;
      if (n && n.y > 0.3) return x2.point.y;
    }
    return 0;
  }
  const side = new THREE.Raycaster();
  side.camera = camera;
  function blocked(from, dir, dist) {
    side.set(from, dir); side.far = dist;
    for (const x of side.intersectObjects(world.children, true)) {
      if (x.object.isSprite || !visibleChain(x.object) || x.object.material?.opacity < 0.3) continue;
      const n = x.face ? x.face.normal.clone().transformDirection(x.object.matrixWorld) : null;
      if (n && Math.abs(n.y) > 0.6) continue;
      return byId(x.object.userData.objId)?.type === "ladder" ? "ladder" : true;
    }
    return false;
  }

  // ---------------------------------------------------------------- camera
  const rig = new CameraRig(camera, canvas, {
    keysAlways: true,
    pick: (cx, cy) => hitObjects(cx, cy)?.point || planeHit(cx, cy, 0),
    floorAt: (x, z, y) => floorAt(x, z, y),
    blocked,
    onWalkExit: () => setWalk(false),
  });
  if (doc.view?.pos) {
    camera.position.fromArray(doc.view.pos); rig.yaw = doc.view.yaw; rig.pitch = doc.view.pitch; rig._apply();
  } else {
    const span = Math.max(W, H);
    rig.lookAt(new THREE.Vector3(W / 2 - span * 0.3, span * 0.55, H / 2 + span * 0.75), new THREE.Vector3(W / 2, 0, H / 2));
  }
  function setView(kind) {
    const box = selection.length ? selBox() : worldBox();
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3()), r = Math.max(s.x, s.z, s.y, 6);
    const pos = { top: new THREE.Vector3(c.x, r * 1.6 + c.y, c.z + 0.01), front: new THREE.Vector3(c.x, c.y + r * 0.25, c.z + r * 1.4),
      side: new THREE.Vector3(c.x + r * 1.4, c.y + r * 0.25, c.z), persp: new THREE.Vector3(c.x - r * 0.6, c.y + r * 0.9, c.z + r * 1.1) }[kind];
    rig.flyTo(pos, c);
  }
  function worldBox() {
    const b = new THREE.Box3(new THREE.Vector3(0, 0, 0), new THREE.Vector3(W, 1, H));
    if (world.children.length) b.expandByObject(world);
    return b;
  }
  function selBox() { const b = new THREE.Box3(); selection.forEach((id) => b.expandByObject(groups.get(id))); if (selCam != null) b.expandByObject(camMarks.get(selCam)); return b; }
  function focus() { rig.frame(selection.length || selCam != null ? selBox() : worldBox()); }
  function setWalk(on) {
    if (on) { select([]); rig.startWalk(); walkBtn.setAttribute("aria-pressed", "true"); showHint("Walking: move the mouse to look, W A S D to walk, Space to jump, walk into a ladder to climb. Press Esc to stop."); }
    else { rig.stopWalk(); walkBtn.setAttribute("aria-pressed", "false"); showHint(); }
  }

  // ---------------------------------------------------------------- ghost preview
  const ghostMat = new THREE.MeshBasicMaterial({ color: 0x00998c, transparent: true, opacity: 0.38, depthWrite: false });
  let ghost = null, ghostKey = "";
  function showGhost(o) {
    const key = JSON.stringify([o.type, o.size, o.props]);
    if (key !== ghostKey) {
      hideGhost();
      ghost = buildObject({ ...o, id: "ghost" });
      ghost.traverse((c) => { if (c.isMesh) { c.material = ghostMat; c.castShadow = false; } });
      helpers.add(ghost); ghostKey = key;
    }
    ghost.position.fromArray(o.pos);
    ghost.rotation.set(0, THREE.MathUtils.degToRad(o.rot[1]), 0, "YXZ");
  }
  function hideGhost() { if (ghost) { helpers.remove(ghost); disposeGroup(ghost); ghost = null; ghostKey = ""; } }

  // Work out size/position for placing `type` at a surface (smart roofs, doors into walls...)
  function placement(type, surf, rect) {
    const d = defaults(type);
    const o = { ...d, pos: [snap(surf.point.x), surf.baseY, snap(surf.point.z)], rot: [0, 0, 0] };
    const host = surf.hostId && byId(surf.hostId);
    if (host && ROOFLIKE.has(type) && HOSTS.has(host.type) && !surf.side && !rect) {
      const over = type === "floor" ? 0 : 0.6;
      o.size = [host.size[0] + over * 2, type === "floor" ? d.size[1] : Math.max(1.2, Math.min(host.size[0], host.size[2]) * 0.3), host.size[2] + over * 2];
      if (type === "roofFlat") o.size[1] = 0.3;
      const g = groups.get(host.id);
      const topY = new THREE.Box3().setFromObject(g).max.y;
      o.pos = [host.pos[0], topY, host.pos[2]]; o.rot = [0, host.rot?.[1] || 0, 0];
      o.fitted = true;
      return o;
    }
    if (surf.side && ON_WALL.has(type)) {
      const n = surf.normal;
      const yaw = Math.atan2(n.x, n.z);
      const halfD = o.size[2] / 2;
      o.pos = [round(surf.point.x + n.x * halfD), type === "window" ? surf.baseY + 1 : surf.baseY, round(surf.point.z + n.z * halfD)];
      if (type === "sign") o.pos[1] = surf.baseY;
      o.rot = [0, deg(yaw), 0];
      return o;
    }
    if (surf.side) {
      // drop next to the face you pointed at
      const n = surf.normal;
      o.pos[0] = round(surf.point.x + n.x * o.size[0] / 2); o.pos[2] = round(surf.point.z + n.z * o.size[2] / 2);
    }
    if (rect) {
      const [x0, z0, x1, z1] = rect;
      o.size = [Math.max(0.3, round(Math.abs(x1 - x0))), o.size[1], Math.max(0.3, round(Math.abs(z1 - z0)))];
      o.pos = [round((x0 + x1) / 2), surf.baseY, round((z0 + z1) / 2)];
    }
    if (TYPES[type].lift && !surf.side) o.pos[1] += TYPES[type].lift;
    return o;
  }

  function segmentObject(type, a, b, baseY) {
    const d = defaults(type);
    const dx = b.x - a.x, dz = b.z - a.z, len = Math.hypot(dx, dz);
    const extra = ["wall", "hedge"].includes(type) ? d.size[2] : 0;   // walls overlap at corners
    return { ...d, size: [round(len + extra), d.size[1], d.size[2]], pos: [round((a.x + b.x) / 2), baseY, round((a.z + b.z) / 2)], rot: [0, deg(Math.atan2(-dz, dx)), 0] };
  }

  // ---------------------------------------------------------------- pointer handling
  let act = null;           // current drag action
  let chain = null;         // { type, last: Vector3, baseY } while drawing walls
  let measure = null;       // { a, line, label }
  let lastCursor = null;
  let rmbAt = null;
  const placing = () => tool.startsWith("place:") ? tool.slice(6) : null;

  canvas.addEventListener("pointerdown", (e) => {
    if (e.button === 2) { rmbAt = [e.clientX, e.clientY]; return; }
    if (e.button !== 0 || e.altKey || rig.mode === "walk") return;
    if (tc.dragging || tc.axis) return;       // the gizmo took it
    canvas.focus();
    const type = placing();
    if (type) {
      const surf = surfaceAt(e.clientX, e.clientY); if (!surf) return;
      if (TYPES[type].line) {
        const pt = new THREE.Vector3(snap(surf.point.x), surf.baseY, snap(surf.point.z));
        if (!chain) { chain = { type, last: pt, baseY: surf.baseY, count: 0 }; snapshot(); }
        else {
          const end = straighten(chain.last, pt, e.shiftKey);
          if (end.distanceTo(chain.last) > 0.2) {
            newObject(type, segmentObject(type, chain.last, end, chain.baseY));
            chain.last = end; chain.count++;
          }
        }
        return;
      }
      act = { kind: "place", type, surf, start: [e.clientX, e.clientY], p0: new THREE.Vector3(snap(surf.point.x), surf.baseY, snap(surf.point.z)) };
      canvas.setPointerCapture(e.pointerId);
      return;
    }
    if (tool === "paint" || tool === "erasePaint") { snapshotPaint(); act = { kind: "paint" }; paintAt(e); canvas.setPointerCapture(e.pointerId); return; }
    if (tool === "scatter") { snapshot(); act = { kind: "scatter", last: null }; scatterAt(e); canvas.setPointerCapture(e.pointerId); return; }
    if (tool === "freehand") { snapshot(); const s = surfaceAt(e.clientX, e.clientY); if (s) act = { kind: "freehand", last: s.point.clone(), baseY: s.baseY }; canvas.setPointerCapture(e.pointerId); return; }
    if (tool === "eraser") { snapshot(); act = { kind: "erase" }; eraseAt(e); canvas.setPointerCapture(e.pointerId); return; }
    if (tool === "measure") { measureClick(e); return; }
    if (tool === "picker") {
      const hit = hitObjects(e.clientX, e.clientY);
      if (hit?.id) { const o = byId(hit.id); brush.newColor = o.color; brush.mat = o.mat; brush.color = o.color; drawPalette(); toast(`Picked ${o.name}'s colour and material`); setTool("select"); }
      return;
    }
    // select / move / rotate / scale
    const hit = hitObjects(e.clientX, e.clientY, { cams: true });
    if (hit?.camId != null) { select([], hit.camId); return; }
    if (hit?.id) {
      let ids;
      if (e.shiftKey || e.ctrlKey) ids = selection.includes(hit.id) ? selection.filter((x) => x !== hit.id) : [...selection, hit.id];
      else ids = selection.includes(hit.id) ? selection : [hit.id];
      select(ids);
      if (tool === "select" && !e.shiftKey && !byId(hit.id)?.locked) {
        act = { kind: "slide", y: hit.point.y, start: hit.point.clone(), from: selection.map((id) => ({ id, p: groups.get(id).position.clone() })), moved: false };
        canvas.setPointerCapture(e.pointerId);
      }
      return;
    }
    act = { kind: "empty", start: [e.clientX, e.clientY], shift: e.shiftKey };
    if (mouseSwapped()) rig.startLook(e);           // buttons swapped: left drag looks around
    else rig.startOrbit(e, planeHit(e.clientX, e.clientY, 0));
  });

  canvas.addEventListener("pointermove", (e) => {
    lastCursor = [e.clientX, e.clientY];
    const surf = rig.mode === "walk" ? null : surfaceAt(e.clientX, e.clientY);
    if (surf) status.querySelector(".pos").textContent = `x ${surf.point.x.toFixed(1)}  z ${surf.point.z.toFixed(1)}  height ${surf.baseY.toFixed(1)} m`;
    const type = placing();
    if (!act) {
      if (type && surf) {
        if (chain) {
          const end = straighten(chain.last, new THREE.Vector3(snap(surf.point.x), chain.baseY, snap(surf.point.z)), e.shiftKey);
          const len = end.distanceTo(chain.last);
          if (len > 0.05) { showGhost(segmentObject(chain.type, chain.last, end, chain.baseY)); showHint(`${len.toFixed(1)} m. Click to add the next corner. Esc or right-click to finish. Hold Shift for straight lines.`); }
        } else if (TYPES[type].line) { showGhost({ ...defaults(type), pos: [snap(surf.point.x), surf.baseY, snap(surf.point.z)], rot: [0, 0, 0], size: [0.3, defaults(type).size[1], defaults(type).size[2]] }); }
        else { const o = placement(type, surf); showGhost(o); if (o.fitted) showHint(`${TYPES[type].label} will fit the shape below. Click to put it on.`); else showHint(); }
      } else hideGhost();
      if (["paint", "erasePaint", "scatter", "eraser"].includes(tool)) showBrushRing(e);
      return;
    }
    if (act.kind === "place") {
      if (!surf) return;
      const p1 = new THREE.Vector3(snap(surf.point.x), act.surf.baseY, snap(surf.point.z));
      const far = Math.hypot(e.clientX - act.start[0], e.clientY - act.start[1]) > 6;
      if (!far) return;
      if (FIXED.has(act.type)) {
        const o = placement(act.type, act.surf);
        o.rot[1] = deg(Math.atan2(-(p1.x - act.p0.x), -(p1.z - act.p0.z)));
        showGhost(o); act.rotOnly = o.rot[1];
      } else {
        act.rect = [act.p0.x, act.p0.z, p1.x, p1.z];
        const o = placement(act.type, act.surf, act.rect);
        showGhost(o);
        showHint(`${o.size[0]} m × ${o.size[2]} m`);
      }
    } else if (act.kind === "slide") {
      const p = planeHit(e.clientX, e.clientY, act.y); if (!p) return;
      const dx = snap(p.x - act.start.x), dz = snap(p.z - act.start.z);
      if (!act.moved && (dx || dz)) { snapshot(); act.moved = true; }
      act.from.forEach(({ id, p: p0 }) => groups.get(id).position.set(p0.x + dx, p0.y, p0.z + dz));
      updateBoxes();
    } else if (act.kind === "paint") paintAt(e);
    else if (act.kind === "scatter") { scatterAt(e); showBrushRing(e); }
    else if (act.kind === "erase") { eraseAt(e); showBrushRing(e); }
    else if (act.kind === "freehand") freehandAt(e);
  });

  canvas.addEventListener("pointerup", (e) => {
    if (e.button === 2) {
      if (chain && rmbAt && Math.hypot(e.clientX - rmbAt[0], e.clientY - rmbAt[1]) < 5) endChain();
      rmbAt = null; return;
    }
    if (!act) return;
    const a = act; act = null;
    if (a.kind === "place") {
      hideGhost();
      snapshot();
      const o = placement(a.type, a.surf, a.rect);
      if (a.rotOnly != null) o.rot[1] = a.rotOnly;
      delete o.fitted;
      const made = newObject(a.type, o);
      select([made.id]);
      showHint(`${made.name} added. Keep clicking to add more, or press Esc.`);
    } else if (a.kind === "slide") {
      if (a.moved) { selection.forEach((id) => syncFromGroup(byId(id))); markDirty(); drawProps(); }
    } else if (a.kind === "empty") {
      if (Math.hypot(e.clientX - a.start[0], e.clientY - a.start[1]) < 4 && !a.shift) select([]);
    } else if (a.kind === "paint") { composeGround(); markDirty(); }
    refreshOutline();
  });
  canvas.addEventListener("dblclick", () => { if (chain) endChain(); });
  canvas.addEventListener("pointerleave", () => { hideGhost(); ring.visible = false; });

  function endChain() {
    if (!chain) return;
    if (!chain.count) history.pop();
    chain = null; hideGhost(); showHint();
  }
  function straighten(a, b, on) {
    if (!on) return b;
    const dx = b.x - a.x, dz = b.z - a.z, ang = Math.round(Math.atan2(dz, dx) / (Math.PI / 4)) * (Math.PI / 4), len = Math.hypot(dx, dz);
    return new THREE.Vector3(a.x + Math.cos(ang) * len, b.y, a.z + Math.sin(ang) * len);
  }

  // ---------------------------------------------------------------- brushes
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.94, 1, 48).rotateX(-Math.PI / 2), new THREE.MeshBasicMaterial({ color: 0xf0b13a, depthTest: false, transparent: true }));
  ring.renderOrder = 40; ring.visible = false; helpers.add(ring);
  function showBrushRing(e) {
    const p = tool === "paint" || tool === "erasePaint" ? groundPoint(e) : surfaceAt(e.clientX, e.clientY)?.point;
    if (!p) { ring.visible = false; return; }
    ring.visible = true; ring.position.set(p.x, p.y + 0.05, p.z); ring.scale.setScalar(brush.size / 2);
  }
  function groundPoint(e) { setRay(e.clientX, e.clientY); const x = ray.intersectObject(ground)[0]; return x ? x.point : null; }
  let paintHistory = [];
  function snapshotPaint() { paintHistory.push(paintCtx.getImageData(0, 0, PX, PY)); if (paintHistory.length > 15) paintHistory.shift(); }
  function paintAt(e) {
    const p = groundPoint(e); if (!p) return;
    showBrushRing(e);
    const x = (p.x / W) * PX, y = (p.z / H) * PY, r = (brush.size / 2 / W) * PX;
    paintCtx.save();
    if (tool === "erasePaint") paintCtx.globalCompositeOperation = "destination-out";
    const g = paintCtx.createRadialGradient(x, y, r * 0.6, x, y, r);
    const c = new THREE.Color(brush.color);
    const rgb = `${Math.round(c.r * 255)},${Math.round(c.g * 255)},${Math.round(c.b * 255)}`;
    g.addColorStop(0, `rgba(${rgb},${brush.opacity})`); g.addColorStop(1, `rgba(${rgb},0)`);
    paintCtx.fillStyle = g; paintCtx.beginPath(); paintCtx.arc(x, y, r, 0, Math.PI * 2); paintCtx.fill();
    paintCtx.restore();
    composeGround(); markDirty();
  }
  function scatterAt(e) {
    const s = surfaceAt(e.clientX, e.clientY); if (!s) return;
    if (act.last && act.last.distanceTo(s.point) < Math.max(1.2, brush.size * 0.6)) return;
    act.last = s.point.clone();
    const kinds = brush.scatter === "mix" ? ["tree", "tree", "pine", "bush", "bush", "palm"] : [brush.scatter];
    const t = kinds[Math.floor(Math.random() * kinds.length)];
    const k = 0.7 + Math.random() * 0.6, d = defaults(t);
    const jx = (Math.random() - 0.5) * brush.size * 0.6, jz = (Math.random() - 0.5) * brush.size * 0.6;
    const baseY = floorAt(s.point.x + jx, s.point.z + jz, s.baseY + 0.5);
    newObject(t, { size: d.size.map((v) => round(v * k)), pos: [round(s.point.x + jx), baseY, round(s.point.z + jz)], rot: [0, Math.round(Math.random() * 360), 0], color: d.color });
  }
  function freehandAt(e) {
    const s = surfaceAt(e.clientX, e.clientY); if (!s || !act) return;
    const step = brush.freehand === "road" ? 3 : 1.5;
    if (s.point.distanceTo(act.last) < step) return;
    const p = s.point.clone(); p.y = act.baseY;
    newObject(brush.freehand, segmentObject(brush.freehand, act.last, p, act.baseY));
    act.last = p;
  }
  function eraseAt(e) {
    const hit = hitObjects(e.clientX, e.clientY);
    if (!hit?.id) return;
    const id = hit.id;
    const g = groups.get(id); if (tc.object === g) tc.detach();
    world.remove(g); disposeGroup(g); groups.delete(id);
    doc.objects = doc.objects.filter((o) => o.id !== id);
    selection = selection.filter((x) => x !== id);
    markDirty(); updateBoxes();
  }
  function measureClick(e) {
    const s = surfaceAt(e.clientX, e.clientY); if (!s) return;
    const p = s.point.clone();
    if (!measure || measure.done) {
      clearMeasure();
      measure = { a: p };
      showHint("Now click the second point.");
      return;
    }
    const a = measure.a, d = a.distanceTo(p), flat = Math.hypot(p.x - a.x, p.z - a.z), dh = p.y - a.y;
    const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints([a, p]), new THREE.LineBasicMaterial({ color: 0xf0b13a, depthTest: false }));
    line.renderOrder = 40;
    helpers.add(line);
    measure = { done: true, line };
    showHint(`Distance ${d.toFixed(2)} m  (along the ground ${flat.toFixed(2)} m, height change ${dh.toFixed(2)} m). Click again to measure something else.`);
  }
  function clearMeasure() { if (measure?.line) { helpers.remove(measure.line); measure.line.geometry.dispose(); } measure = null; }

  // ---------------------------------------------------------------- object actions
  function duplicate(offset = true) {
    if (!selection.length) return;
    snapshot();
    const made = selection.map((id) => {
      const src = byId(id);
      const o = JSON.parse(JSON.stringify(src));
      o.id = `o${nextId++}`; o.name = src.name;
      if (offset) { o.pos[0] += Math.max(1, src.size[0] * 0.25 + 1); o.pos[2] += 1; }
      doc.objects.push(o); addGroup(o); return o.id;
    });
    markDirty(); select(made);
  }
  function stackCopy() {
    if (!selection.length) return;
    snapshot();
    const box = selBox();
    const made = selection.map((id) => {
      const src = byId(id);
      const o = JSON.parse(JSON.stringify(src));
      o.id = `o${nextId++}`;
      o.pos[1] = round(src.pos[1] + (box.max.y - box.min.y));
      doc.objects.push(o); addGroup(o); return o.id;
    });
    markDirty(); select(made);
    toast("Copy stacked on top");
  }
  function addRoof(type) {
    const host = byId(selection[0]); if (!host) return;
    snapshot();
    const g = groups.get(host.id);
    const topY = new THREE.Box3().setFromObject(g).max.y;
    const over = type === "roofFlat" ? 0 : 0.6;
    const o = newObject(type, { size: [round(host.size[0] + over * 2), type === "roofFlat" ? 0.3 : round(Math.max(1.2, Math.min(host.size[0], host.size[2]) * 0.3)), round(host.size[2] + over * 2)],
      pos: [host.pos[0], round(topY), host.pos[2]], rot: [0, host.rot?.[1] || 0, 0] });
    select([o.id]);
  }
  function addFloorAbove() {
    const o = byId(selection[0]); if (!o) return;
    if (o.type === "building") {
      snapshot();
      const floors = (o.props.floors || 1), fh = o.size[1] / floors;
      o.props.floors = floors + 1; o.size[1] = round(o.size[1] + fh);
      // lift anything that was sitting on top of the building
      const g = groups.get(o.id), box = new THREE.Box3().setFromObject(g), topY = box.max.y;
      for (const other of doc.objects) {
        if (other === o || Math.abs(other.pos[1] - topY) > 0.4) continue;
        if (Math.abs(other.pos[0] - o.pos[0]) < o.size[0] / 2 + 1 && Math.abs(other.pos[2] - o.pos[2]) < o.size[2] / 2 + 1) { other.pos[1] = round(other.pos[1] + fh); rebuild(other); }
      }
      rebuild(o); markDirty(); updateBoxes(); drawProps();
      toast(`${o.name} now has ${o.props.floors} floors`);
    } else stackCopy();
  }
  function addStairsBeside() {
    const o = byId(selection[0]); if (!o) return;
    snapshot();
    const g = groups.get(o.id), box = new THREE.Box3().setFromObject(g);
    const fh = o.type === "building" ? o.size[1] / (o.props.floors || 1) : Math.min(FLOOR_H, box.max.y - box.min.y);
    const yaw = THREE.MathUtils.degToRad(o.rot?.[1] || 0);
    const run = round(fh * 1.6);
    // outside the right-hand end, climbing towards the building's back
    const lx = o.size[0] / 2 + 0.9, lz = 0;
    const x = o.pos[0] + Math.cos(yaw) * lx + Math.sin(yaw) * lz, z = o.pos[2] - Math.sin(yaw) * lx + Math.cos(yaw) * lz;
    const s = newObject("stairs", { size: [1.4, round(fh), run], pos: [round(x), o.pos[1], round(z)], rot: [0, o.rot?.[1] || 0, 0] });
    select([s.id]);
    toast("Stairs added. Turn or move them where you need them.");
  }
  function dropToSurface() {
    if (!selection.length) return;
    snapshot();
    for (const id of selection) {
      const o = byId(id), g = groups.get(id);
      g.visible = false;
      o.pos[1] = round(floorAt(o.pos[0], o.pos[2], o.pos[1] + 0.01));
      g.visible = !o.hidden;
      rebuild(o);
    }
    markDirty(); updateBoxes(); drawProps();
  }
  function nudgeY(dy) {
    if (!selection.length) return;
    snapshot();
    for (const id of selection) { const o = byId(id); o.pos[1] = round(Math.max(0, o.pos[1] + dy)); groups.get(id).position.y = o.pos[1]; }
    markDirty(); updateBoxes(); drawProps();
  }
  async function makeArea() {
    const o = byId(selection[0]); if (!o) return;
    const yaw = THREE.MathUtils.degToRad(o.rot?.[1] || 0), [w, , d] = o.size;
    const corners = [[-w / 2, -d / 2], [w / 2, -d / 2], [w / 2, d / 2], [-w / 2, d / 2]].map(([lx, lz]) =>
      [round(o.pos[0] + Math.cos(yaw) * lx + Math.sin(yaw) * lz, 10), round(o.pos[2] - Math.sin(yaw) * lx + Math.cos(yaw) * lz, 10)]);
    const floors = o.type === "building" ? o.props.floors || 1 : Math.max(1, Math.round(o.size[1] / FLOOR_H));
    try {
      await post("/api/buildings", { name: o.name, kind: ["lawn", "parking", "road", "path"].includes(o.type) ? (o.type === "parking" ? "parking" : "field") : "building",
        polygon: corners, height_m: Math.max(1, o.size[1]), floors, color: o.color });
      mapData.buildings = (await get("/api/map")).buildings;
      drawExtras();
      toast(`${o.name} is now an area. Set who may enter it in the Campus builder.`);
    } catch (e) { fail(e); }
  }

  // ---------------------------------------------------------------- top bar
  const btn = (label, onclick, attrs = {}) => h("button", { class: "small", onclick, ...attrs }, label);
  const saveBtn = btn("Saved", () => save(), { title: "Save the map (Ctrl+S)" });
  const walkBtn = btn("Walk inside", () => setWalk(rig.mode !== "walk"), { "aria-pressed": "false", title: "Walk around at eye height like in a game" });
  const toolSeg = h("div", { class: "seg", role: "group", "aria-label": "Edit tool" });
  const TOOLBAR = [["select", "Select", "V"], ["move", "Move", "G"], ["rotate", "Turn", "R"], ["scale", "Size", "T"]];
  for (const [id, label, key] of TOOLBAR) toolSeg.append(h("button", { "data-tool": id, title: `${label} (${key})`, onclick: () => setTool(id) }, label));
  const snapBox = h("input", { type: "checkbox", checked: doc.settings.snap });
  snapBox.addEventListener("change", () => { doc.settings.snap = snapBox.checked; applySnapToGizmo(); });
  const gridSel = h("select", { "aria-label": "Grid size" }, [0.1, 0.25, 0.5, 1, 2, 5].map((g) => h("option", { value: g, selected: g === doc.settings.grid }, `${g} m`)));
  gridSel.addEventListener("change", () => { doc.settings.grid = +gridSel.value; applySnapToGizmo(); makeGrid(); });
  const levelLbl = h("span", { class: "num" });
  const cutBox = h("input", { type: "checkbox" });
  cutBox.addEventListener("change", () => { cutOn = cutBox.checked; applyCut(); });
  function setLevel(n) {
    level = Math.max(0, Math.min(60, n));
    levelLbl.textContent = level === 0 ? "Ground" : `Floor ${level}`;
    makeGrid(); applyCut();
  }
  function applyCut() {
    renderer.clippingPlanes = cutOn ? [new THREE.Plane(new THREE.Vector3(0, -1, 0), cutY())] : [];
  }
  const speed = h("input", { type: "range", min: 0.2, max: 4, step: 0.1, value: 1, "aria-label": "Camera speed" });
  speed.addEventListener("input", () => (rig.speed = +speed.value));

  top.append(
    h("div", { class: "st-brand" }, logoMark("st-mark"), h("b", {}, "Map Studio")),
    h("div", { class: "st-group" }, btn("Undo", undo, { title: "Undo (Ctrl+Z)" }), btn("Redo", redo, { title: "Redo (Ctrl+Y)" })),
    h("div", { class: "st-group" }, toolSeg),
    h("div", { class: "st-group" }, h("label", { class: "check" }, snapBox, "Snap"), gridSel),
    h("div", { class: "st-group", title: "The floor you are drawing on. Shapes put on empty space go to this height." },
      btn("▼", () => setLevel(level - 1), { "aria-label": "Floor down" }), levelLbl, btn("▲", () => setLevel(level + 1), { "aria-label": "Floor up" }),
      h("label", { class: "check", title: "Hide everything above this floor so you can see inside" }, cutBox, "Cut above")),
    h("div", { class: "st-group" }, btn("Top", () => setView("top")), btn("Front", () => setView("front")), btn("Side", () => setView("side")), btn("3D", () => setView("persp")),
      btn("Focus", focus, { title: "Fly to the chosen shape (F)" }), walkBtn, h("label", { class: "st-speed", title: "Camera speed" }, "Speed", speed)),
    h("div", { class: "st-group st-end" }, btn("Help", showHelp, { title: "Controls (F1)" }), btn("Photo", photo, { title: "Save a picture of the view" }), saveBtn,
      btn("Close", () => close(), { title: "Close Map Studio" })),
  );

  function setTool(t) {
    if (chain) endChain();
    tool = t;
    if (!["select", "move", "rotate", "scale"].includes(t) && (selection.length || selCam != null)) { selection = []; selCam = null; updateBoxes(); drawProps(); }
    hideGhost(); ring.visible = false;
    if (t !== "measure") clearMeasure();
    toolSeg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === t)));
    left.querySelectorAll("[data-tool]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.tool === t)));
    attachGizmo();
    canvas.style.cursor = t.startsWith("place:") || ["paint", "erasePaint", "scatter", "measure", "freehand", "picker"].includes(t) ? "crosshair" : t === "eraser" ? "not-allowed" : "default";
    const type = placing();
    showHint(type ? (TYPES[type].line ? `Click to start the ${TYPES[type].label.toLowerCase()}, then click each corner. Esc to finish.`
      : FIXED.has(type) ? `Click to place a ${TYPES[type].label.toLowerCase()}. Drag while clicking to turn it.${ON_WALL.has(type) ? " Point at a wall to fix it on the wall." : ""}`
      : ROOFLIKE.has(type) ? `Point at the top of a building or block and click: the ${TYPES[type].label.toLowerCase()} fits itself. Or drag to draw its size.`
      : `Click to place, or drag to draw its size. Point at the top of another shape to stack on it.`) : TOOL_HINTS[t]);
    drawBrushPanel();
  }
  function showHint(text) {
    const t = text || TOOL_HINTS[tool] || "";
    hint.textContent = t; hint.classList.toggle("hidden", !t);
  }

  // ---------------------------------------------------------------- left palette
  const thumbs = new Map();
  const leftTabs = h("div", { class: "st-tabs", role: "tablist" });
  const leftBody = h("div", { class: "st-palette" });
  const brushPanel = h("div", { class: "st-brush" });
  const palette = h("div", { class: "st-colours" });
  left.append(leftTabs, leftBody, brushPanel, palette);
  const TABS = [["tools", "Tools"], ...CATS];
  let tab = "build";
  function drawTabs() {
    leftTabs.replaceChildren(...TABS.map(([id, label]) => h("button", { role: "tab", "aria-selected": String(id === tab), onclick: () => { tab = id; drawTabs(); drawPaletteItems(); } }, label)));
  }
  const TOOL_ITEMS = [
    ["select", "Select & drag", "▢"], ["paint", "Paint ground", "🖌"], ["erasePaint", "Rub out paint", "⌫"], ["scatter", "Plant trees", "🌳"],
    ["freehand", "Draw path", "〰"], ["eraser", "Delete brush", "✖"], ["measure", "Measure", "📏"], ["picker", "Copy colour", "💧"],
  ];
  function drawPaletteItems() {
    if (tab === "tools") {
      leftBody.replaceChildren(h("div", { class: "st-items" }, TOOL_ITEMS.map(([id, label, ic]) =>
        h("button", { class: "st-item", "data-tool": id, "aria-pressed": String(tool === id), onclick: () => setTool(id) }, h("span", { class: "st-ic" }, ic), h("span", {}, label)))));
      return;
    }
    const items = Object.entries(TYPES).filter(([, t]) => t.cat === tab);
    leftBody.replaceChildren(h("div", { class: "st-items" }, items.map(([type, t]) => {
      const img = h("img", { alt: "", src: thumbs.get(type) });
      return h("button", { class: "st-item", "data-tool": `place:${type}`, "data-type": type, "aria-pressed": String(tool === `place:${type}`), title: t.label, onclick: () => setTool(`place:${type}`) },
        img, h("span", {}, t.label));
    })));
  }
  function drawBrushPanel() {
    const rows = [];
    if (["paint", "erasePaint", "scatter", "eraser"].includes(tool)) {
      const size = h("input", { type: "range", min: 0.5, max: 30, step: 0.5, value: brush.size });
      size.addEventListener("input", () => (brush.size = +size.value));
      rows.push(h("label", { class: "field" }, h("span", {}, "Brush size"), size));
    }
    if (tool === "paint") {
      const op = h("input", { type: "range", min: 0.1, max: 1, step: 0.05, value: brush.opacity });
      op.addEventListener("input", () => (brush.opacity = +op.value));
      rows.push(h("label", { class: "field" }, h("span", {}, "Strength"), op),
        h("div", { class: "row" }, btn("Undo paint", () => { const d = paintHistory.pop(); if (d) { paintCtx.putImageData(d, 0, 0); composeGround(); } }),
          btn("Clear all paint", async () => { if (await confirmBox("Clear all ground paint?", "This removes everything painted on the ground.", "Clear")) { snapshotPaint(); paintCtx.clearRect(0, 0, PX, PY); composeGround(); markDirty(); } })));
    }
    if (tool === "scatter") {
      const s = h("select", {}, [["mix", "Mixed trees"], ["tree", "Round trees"], ["pine", "Pine trees"], ["palm", "Palm trees"], ["bush", "Bushes"], ["rock", "Rocks"]].map(([v, l]) => h("option", { value: v, selected: v === brush.scatter }, l)));
      s.addEventListener("change", () => (brush.scatter = s.value));
      rows.push(h("label", { class: "field" }, h("span", {}, "Plant"), s));
    }
    if (tool === "freehand") {
      const s = h("select", {}, [["path", "Footpath"], ["road", "Road"], ["hedge", "Hedge"], ["fence", "Fence"], ["wall", "Wall"]].map(([v, l]) => h("option", { value: v, selected: v === brush.freehand }, l)));
      s.addEventListener("change", () => (brush.freehand = s.value));
      rows.push(h("label", { class: "field" }, h("span", {}, "Draw"), s));
    }
    brushPanel.replaceChildren(...rows);
    brushPanel.classList.toggle("hidden", !rows.length);
  }
  function drawPalette() {
    const target = selection.length ? "Colour of chosen shapes" : tool === "paint" ? "Paint colour" : "Colour for new shapes";
    const current = selection.length ? byId(selection[0])?.color : tool === "paint" ? brush.color : brush.newColor;
    const custom = h("input", { type: "color", value: current || "#9fb4c8", "aria-label": "Custom colour" });
    custom.addEventListener("input", () => applyColour(custom.value));
    const matSel = h("select", { "aria-label": "Material" },
      h("option", { value: "" }, selection.length ? "Material..." : "Material: automatic"),
      Object.entries(MATERIALS).map(([k, m]) => h("option", { value: k, selected: (selection.length ? byId(selection[0])?.mat : brush.mat) === k }, m.label)));
    matSel.addEventListener("change", () => applyMaterial(matSel.value || null));
    palette.replaceChildren(h("div", { class: "hint" }, target),
      h("div", { class: "swatches" },
        selection.length || tool === "paint" ? null : h("button", { class: "auto", "aria-pressed": String(!brush.newColor), title: "Each shape's own colour", onclick: () => { brush.newColor = null; drawPalette(); } }, "A"),
        SWATCHES.map((c) => h("button", { style: { background: c }, "aria-label": c, "aria-pressed": String(c === current), onclick: () => applyColour(c) })), custom),
      matSel);
  }
  function applyColour(c) {
    if (tool === "paint" && !selection.length) { brush.color = c; drawPalette(); return; }
    if (!selection.length) { brush.newColor = c; drawPalette(); return; }
    snapshot();
    selection.forEach((id) => { const o = byId(id); o.color = c; rebuild(o); });
    markDirty(); updateBoxes(); drawPalette(); drawProps();
  }
  function applyMaterial(m) {
    if (!selection.length) { brush.mat = m; return; }
    if (!m) return;
    snapshot();
    selection.forEach((id) => { const o = byId(id); o.mat = m; rebuild(o); });
    markDirty(); drawProps();
  }

  // ---------------------------------------------------------------- right panel
  const rightTabs = h("div", { class: "st-tabs", role: "tablist" });
  const rightBody = h("div", { class: "st-props" });
  right.append(rightTabs, rightBody);
  let rtab = "props";
  function drawRightTabs() {
    rightTabs.replaceChildren(...[["props", "Properties"], ["list", "Objects"], ["map", "Map"]].map(([id, l]) =>
      h("button", { role: "tab", "aria-selected": String(rtab === id), onclick: () => { rtab = id; drawRightTabs(); drawProps(); } }, l)));
  }
  const num = (label, value, onchange, step = 0.1, min) => {
    const i = h("input", { type: "number", value: round(value), step, min, "aria-label": label });
    i.addEventListener("change", () => { const v = parseFloat(i.value); if (!Number.isNaN(v)) onchange(v); });
    return h("label", { class: "st-num" }, h("span", {}, label), i);
  };
  const PROP_LABELS = { floors: "Floors", thickness: "Wall thickness (m)", door: "Door opening", floor: "Floor inside", windows: "Window holes", rails: "Handrails",
    parapet: "Edge wall height (m)", lines: "Road markings", bays: "Parking bays", rows: "Rows", cols: "Columns", text: "Text", stand: "On a stand", pillars: "Pillars", style: "Style" };

  function drawProps(light = false) {
    if (rtab === "list") return drawList();
    if (rtab === "map") return drawMapTab();
    if (light && document.activeElement && rightBody.contains(document.activeElement)) return;
    if (selCam != null) return drawCamProps();
    if (!selection.length) {
      rightBody.replaceChildren(h("div", { class: "st-empty" },
        h("h3", {}, "Nothing chosen"),
        h("p", {}, "Pick a shape on the left and click in the view to add it, or click a shape in the view to change it."),
        h("p", { class: "hint" }, `${doc.objects.length} shapes on this map.`),
        h("div", { class: "st-keys" }, ...[["Right-drag", "look around"], ["W A S D", "fly"], ["Q / E", "down / up"], ["Wheel", "zoom"], ["Middle-drag", "slide view"], ["F", "focus"]]
          .map(([k, v]) => h("div", {}, h("kbd", {}, k), v)))));
      drawPalette();
      return;
    }
    if (selection.length > 1) {
      rightBody.replaceChildren(h("div", { class: "stack" },
        h("h3", {}, `${selection.length} shapes chosen`),
        h("div", { class: "st-actions" }, btn("Duplicate", () => duplicate()), btn("Stack copy on top", stackCopy), btn("Drop to surface", dropToSurface),
          btn("Raise", () => nudgeY(doc.settings.grid)), btn("Lower", () => nudgeY(-doc.settings.grid)),
          h("button", { class: "small danger", onclick: () => removeObjects([...selection]) }, "Delete"))));
      drawPalette();
      return;
    }
    const o = byId(selection[0]); if (!o) return;
    const g = groups.get(o.id);
    if (g) { o.pos = [round(g.position.x), round(g.position.y), round(g.position.z)]; }
    const change = (fn, rebuildIt = true) => { snapshot(); fn(); if (rebuildIt) rebuild(o); else groups.get(o.id).position.fromArray(o.pos); markDirty(); updateBoxes(); drawProps(); };
    const name = h("input", { value: o.name, "aria-label": "Name" });
    name.addEventListener("change", () => { o.name = name.value.trim() || TYPES[o.type]?.label || "Shape"; markDirty(); refreshOutline(); });
    const propRows = Object.entries(o.props || {}).map(([k, v]) => {
      if (typeof v === "boolean") {
        const c = h("input", { type: "checkbox", checked: v });
        c.addEventListener("change", () => change(() => (o.props[k] = c.checked)));
        return h("label", { class: "check" }, c, PROP_LABELS[k] || k);
      }
      if (typeof v === "number") return num(PROP_LABELS[k] || k, v, (val) => change(() => {
        if (k === "floors") { const f = Math.max(1, Math.round(val)); const fh = o.size[1] / (o.props.floors || 1); o.props.floors = f; o.size[1] = round(f * fh); }
        else o.props[k] = val;
      }), k === "floors" || k === "bays" || k === "rows" || k === "cols" || k === "windows" ? 1 : 0.1, 0);
      const t = h("input", { value: v });
      t.addEventListener("change", () => change(() => (o.props[k] = t.value)));
      return h("label", { class: "field" }, h("span", {}, PROP_LABELS[k] || k), t);
    });
    const op = h("input", { type: "range", min: 0.15, max: 1, step: 0.05, value: o.opacity ?? 1, "aria-label": "See-through" });
    op.addEventListener("change", () => change(() => (o.opacity = +op.value)));
    const host = ["box", "building", "room", "floor"].includes(o.type);
    const roofMenu = h("select", { "aria-label": "Add a roof" }, h("option", { value: "" }, "Add roof on top..."),
      ["roofGable", "roofHip", "roofMetal", "roofShed", "roofFlat", "roofPyramid", "roofDome"].map((t) => h("option", { value: t }, TYPES[t].label)));
    roofMenu.addEventListener("change", () => { if (roofMenu.value) addRoof(roofMenu.value); });

    rightBody.replaceChildren(h("div", { class: "stack" },
      h("div", { class: "st-head" }, h("img", { src: thumbs.get(o.type), alt: "" }), h("div", {}, name, h("small", { class: "hint" }, TYPES[o.type]?.label || o.type))),
      h("div", { class: "st-sec" }, h("h4", {}, "Size (metres)"),
        h("div", { class: "st-grid3" }, num("Width", o.size[0], (v) => change(() => (o.size[0] = Math.max(0.05, v))), 0.1, 0.05),
          num("Height", o.size[1], (v) => change(() => (o.size[1] = Math.max(0.02, v))), 0.1, 0.02),
          num("Depth", o.size[2], (v) => change(() => (o.size[2] = Math.max(0.02, v))), 0.1, 0.02))),
      h("div", { class: "st-sec" }, h("h4", {}, "Position"),
        h("div", { class: "st-grid3" }, num("X", o.pos[0], (v) => change(() => (o.pos[0] = v), false), doc.settings.grid),
          num("Above ground", o.pos[1], (v) => change(() => (o.pos[1] = Math.max(0, v)), false), 0.1, 0),
          num("Z", o.pos[2], (v) => change(() => (o.pos[2] = v), false), doc.settings.grid)),
        h("div", { class: "st-grid3" }, num("Turn °", o.rot?.[1] || 0, (v) => change(() => (o.rot[1] = v))),
          num("Tilt °", o.rot?.[0] || 0, (v) => change(() => (o.rot[0] = v))), num("Lean °", o.rot?.[2] || 0, (v) => change(() => (o.rot[2] = v))))),
      propRows.length ? h("div", { class: "st-sec" }, h("h4", {}, "Options"), ...propRows) : null,
      h("div", { class: "st-sec" }, h("h4", {}, "Look"), h("label", { class: "field" }, h("span", {}, "See-through"), op)),
      h("div", { class: "st-sec" }, h("h4", {}, "Build"),
        h("div", { class: "st-actions" },
          host ? roofMenu : null,
          host ? btn(o.type === "building" ? "Add a floor" : "Add floor above", addFloorAbove) : null,
          host ? btn("Add stairs", addStairsBeside) : null,
          btn("Stack copy on top", stackCopy), btn("Duplicate", () => duplicate()), btn("Drop to surface", dropToSurface),
          btn("Raise", () => nudgeY(doc.settings.grid)), btn("Lower", () => nudgeY(-doc.settings.grid)))),
      h("div", { class: "st-sec" }, h("h4", {}, "Rules"),
        btn("Make this an access area", makeArea, { title: "Creates an area in the Campus builder so you can choose who may enter it" })),
      h("div", { class: "st-actions" },
        btn(o.locked ? "Unlock" : "Lock", () => { o.locked = !o.locked; markDirty(); attachGizmo(); drawProps(); }),
        btn("Hide", () => { o.hidden = true; groups.get(o.id).visible = false; markDirty(); select([]); }),
        h("button", { class: "small danger", onclick: () => removeObjects([o.id]) }, "Delete")),
    ));
    drawPalette();
  }

  function drawCamProps() {
    const c = mapData.cameras.find((x) => x.id === selCam);
    const g = camMarks.get(selCam);
    const dir = Math.round(((-THREE.MathUtils.radToDeg(g.rotation.y) % 360) + 360) % 360);
    rightBody.replaceChildren(h("div", { class: "stack" },
      h("h3", {}, c?.name || "Camera"),
      h("p", { class: "hint" }, "This is one of your CCTV cameras. Use Move to slide it to where it hangs and Turn to point it. Changes save by themselves."),
      h("div", {}, h("b", {}, "Facing "), `${dir}°`),
      h("div", { class: "st-actions" }, btn("Move", () => setTool("move")), btn("Turn", () => setTool("rotate")))));
  }

  function drawList() {
    const q = h("input", { type: "search", placeholder: "Find a shape", "aria-label": "Find a shape" });
    const list = h("div", { class: "st-list" });
    const fill = () => {
      const term = q.value.trim().toLowerCase();
      list.replaceChildren(...doc.objects.filter((o) => !term || o.name.toLowerCase().includes(term) || o.type.toLowerCase().includes(term)).slice(-400).reverse().map((o) =>
        h("div", { class: `st-row${selection.includes(o.id) ? " on" : ""}` },
          h("button", { class: "ghost name", onclick: (e) => { select(e.shiftKey ? [...selection, o.id] : [o.id]); focus(); } }, o.name, h("small", {}, ` ${TYPES[o.type]?.label || o.type}`)),
          h("button", { class: "ghost small", title: o.hidden ? "Show" : "Hide", onclick: () => { o.hidden = !o.hidden; groups.get(o.id).visible = !o.hidden; markDirty(); fill(); } }, o.hidden ? "Show" : "Hide"),
          h("button", { class: "ghost small", title: o.locked ? "Unlock" : "Lock", onclick: () => { o.locked = !o.locked; markDirty(); fill(); } }, o.locked ? "Locked" : "Lock"))));
      if (!doc.objects.length) list.append(h("p", { class: "hint" }, "No shapes yet."));
    };
    q.addEventListener("input", fill); fill();
    const camsList = mapData.cameras.filter((c) => c.map_x != null).map((c) => h("button", { class: "small", onclick: () => { select([], c.id); focus(); } }, c.name));
    rightBody.replaceChildren(h("div", { class: "stack" }, q, list,
      camsList.length ? h("div", {}, h("h4", {}, "CCTV cameras"), h("div", { class: "st-actions" }, camsList)) : null,
      doc.objects.some((o) => o.hidden) ? btn("Show all hidden", () => { doc.objects.forEach((o) => { o.hidden = false; groups.get(o.id).visible = true; }); markDirty(); fill(); }) : null));
  }
  function refreshOutline() { if (rtab === "list") drawList(); status.querySelector(".count").textContent = `${doc.objects.length} shapes`; }

  function drawMapTab() {
    const areas = h("input", { type: "checkbox", checked: doc.settings.showAreas });
    areas.addEventListener("change", () => { doc.settings.showAreas = areas.checked; drawExtras(); markDirty(); });
    const img = h("input", { type: "checkbox", checked: doc.settings.showImage });
    img.addEventListener("change", () => { doc.settings.showImage = img.checked; composeGround(); markDirty(); });
    const sunR = h("input", { type: "range", min: 0, max: 100, value: doc.settings.sun });
    const shadowBox = h("input", { type: "checkbox", checked: doc.settings.shadows });
    shadowBox.addEventListener("change", () => {
      doc.settings.shadows = shadowBox.checked; renderer.shadowMap.enabled = shadowBox.checked;
      renderer.setPixelRatio(shadowBox.checked ? Math.min(window.devicePixelRatio, 2) : 1);
      scene.traverse((o) => { if (o.material) [].concat(o.material).forEach((m) => (m.needsUpdate = true)); });
      ro.disconnect(); ro.observe(viewBox); markDirty();
    });
    sunR.addEventListener("input", () => { doc.settings.sun = +sunR.value; placeSun(); markDirty(); });
    const fileIn = h("input", { type: "file", accept: ".json,application/json", class: "hidden" });
    fileIn.addEventListener("change", async () => {
      const f = fileIn.files[0]; if (!f) return;
      try {
        const d = JSON.parse(await f.text());
        if (!Array.isArray(d.objects)) throw new Error("That file is not a CAMS map.");
        snapshot();
        doc.objects = d.objects.map((o) => ({ ...o, id: `o${nextId++}` }));
        if (d.paint) { const im = new Image(); im.onload = () => { paintCtx.clearRect(0, 0, PX, PY); paintCtx.drawImage(im, 0, 0, PX, PY); composeGround(); }; im.src = d.paint; }
        rebuildAll(); select([]); markDirty(); toast(`Loaded ${doc.objects.length} shapes`);
      } catch (e) { fail(e); }
    });
    rightBody.replaceChildren(h("div", { class: "stack" },
      h("h3", {}, "Map"),
      h("p", { class: "hint" }, `Site size ${W} m × ${H} m. Change the size or the site picture in the Campus builder.`),
      h("label", { class: "check" }, img, "Show the site picture on the ground"),
      h("label", { class: "check" }, areas, "Show access areas and cameras from the Campus builder"),
      h("label", { class: "field" }, h("span", {}, "Time of day (sun)"), sunR),
      h("label", { class: "check" }, shadowBox, "Shadows (turn off if the view is slow)"),
      h("h4", {}, "File"),
      h("div", { class: "st-actions" },
        btn("Export map file", exportJson), btn("Import map file", () => fileIn.click()), fileIn,
        h("button", { class: "small danger", onclick: async () => {
          if (!(await confirmBox("Clear the whole map?", "Every shape you drew will be removed. Ground paint stays. You can undo this.", "Clear map"))) return;
          snapshot(); doc.objects = []; rebuildAll(); select([]); markDirty();
        } }, "Clear map")),
      h("h4", {}, "Quick start"),
      h("p", { class: "hint" }, "Add a sample block of classrooms to see how shapes, roofs and stairs fit together."),
      btn("Add sample school block", addSample)));
  }

  function placeSun() {
    const t = doc.settings.sun / 100, a = Math.PI * (0.1 + t * 0.8), span = Math.max(W, H);
    sun.position.set(W / 2 + Math.cos(a) * span, Math.sin(a) * span * 1.2 + 20, H / 2 - span * 0.4);
    sun.target.position.set(W / 2, 0, H / 2);
    sun.intensity = 0.6 + Math.sin(a) * 1.5;
    scene.background.set(t < 0.08 || t > 0.92 ? "#e9c9a4" : "#cfe3ee");
  }

  function addSample() {
    snapshot();
    const cx = round(W / 2), cz = round(H / 2);
    const b = newObject("building", { name: "Classroom block", pos: [cx, 0, cz], size: [24, 6.4, 9], props: { floors: 2 } });
    newObject("roofHip", { name: "Block roof", pos: [cx, 6.4, cz], size: [25.2, 2.6, 10.2] });
    newObject("stairs", { name: "Stairs", pos: [cx + 13, 0, cz], size: [1.4, 3.2, 5] });
    newObject("floor", { name: "Landing", pos: [cx + 13, 3, cz - 3.4], size: [1.6, 0.2, 1.8] });
    newObject("path", { name: "Path", pos: [cx, 0, cz + 7.5], size: [30, 0.04, 2.5] });
    newObject("lawn", { name: "Lawn", pos: [cx, 0, cz + 14], size: [30, 0.03, 10] });
    for (let i = 0; i < 5; i++) newObject("tree", { pos: [cx - 12 + i * 6, 0, cz + 18], size: [4, 6, 4] });
    newObject("flag", { pos: [cx, 0, cz + 12], size: [1.6, 8, 0.1] });
    select([b.id]); focus();
  }

  // ---------------------------------------------------------------- save / export / photo
  async function save() {
    doc.view = { pos: camera.position.toArray().map((v) => round(v)), yaw: rig.yaw, pitch: rig.pitch };
    const painted = paintCtx.getImageData(0, 0, PX, PY).data.some((v, i) => i % 4 === 3 && v);
    doc.paint = painted ? paintCanvas.toDataURL("image/png") : null;
    saveBtn.disabled = true; saveBtn.textContent = "Saving...";
    try {
      await put("/api/map/scene", doc);
      dirty = false; saveBtn.classList.remove("primary"); saveBtn.textContent = "Saved";
      toast("Map saved");
      return true;
    } catch (e) { fail(e); saveBtn.textContent = "Save"; return false; }
    finally { saveBtn.disabled = false; }
  }
  function exportJson() {
    const painted = paintCtx.getImageData(0, 0, PX, PY).data.some((v, i) => i % 4 === 3 && v);
    const blob = new Blob([JSON.stringify({ ...doc, paint: painted ? paintCanvas.toDataURL("image/png") : null })], { type: "application/json" });
    download(URL.createObjectURL(blob), "cams-map.json");
  }
  function photo() {
    tc.getHelper().visible = false; helpers.visible = false;
    renderer.render(scene, camera);
    download(canvas.toDataURL("image/png"), "cams-map.png");
    tc.getHelper().visible = true; helpers.visible = true;
  }
  function download(url, name) { const a = h("a", { href: url, download: name }); document.body.append(a); a.click(); a.remove(); }

  function showHelp() {
    const rows = [
      ["Look around", mouseSwapped() ? "Drag empty space with the left mouse button" : "Hold the right mouse button and move the mouse"], ["Fly", "W A S D or the arrow keys (hold Shift to go faster)"],
      ["Up / down", "E / Q"], ["Zoom", "Mouse wheel (zooms to where you point)"], ["Slide the view", "Hold the middle button (wheel) and move"],
      ["Turn around a point", mouseSwapped() ? "Hold the right mouse button and move (or Alt + left drag)" : "Drag empty space with the left button (or Alt + left drag)"],
      ["Mouse buttons", "Swap left and right in Settings > Maps and mouse"], ["Walk inside", "Walk inside button; Esc to stop; walk into a ladder to climb"],
      ["Choose", "Click; Shift-click for more; Ctrl+A for all"], ["Move / Turn / Size", "G / R / T, then drag the coloured handles"],
      ["Slide on the ground", "Drag a chosen shape with the Select tool"], ["Raise / lower", "Page Up / Page Down"],
      ["Copy / paste / duplicate", "Ctrl+C / Ctrl+V / Ctrl+D"], ["Delete", "Delete key"], ["Undo / redo", "Ctrl+Z / Ctrl+Y"],
      ["Focus on chosen shape", "F"], ["Hide chosen", "H"], ["Draw walls, fences, roads", "Click each corner; Esc, double-click or right-click to finish; Shift for straight lines"],
      ["Stack shapes", "Point at the top of a shape when you click: the new one sits on it"],
      ["Roofs", "Choose a roof and point at the top of a building: it fits itself"], ["Upper floors", "Use ▲ to work on Floor 1, 2...; tick Cut above to see inside"],
      ["Brush size", "[ and ]"], ["Save", "Ctrl+S"],
    ];
    const d = h("dialog", { class: "wide" },
      h("div", { class: "d-head" }, h("h2", {}, "Map Studio controls"), h("button", { class: "ghost small", onclick: () => d.close() }, "Close")),
      h("div", { class: "d-body" }, h("table", { class: "st-help" }, rows.map(([a, b]) => h("tr", {}, h("th", {}, a), h("td", {}, b))))));
    d.addEventListener("close", () => d.remove());
    root.append(d); d.showModal();
  }

  // ---------------------------------------------------------------- keyboard
  function onKey(e) {
    if (document.querySelector("dialog[open]") && !root.contains(document.querySelector("dialog[open]"))) return;
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) && document.activeElement.type !== "checkbox" && document.activeElement.type !== "range";
    const ctrl = e.ctrlKey || e.metaKey;
    if (ctrl && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
    if (typing) return;
    const k = e.key;
    if (e.key === "Escape") {
      if (rig.mode === "walk") return setWalk(false);
      if (chain) return endChain();
      if (tool !== "select") return setTool("select");
      return select([]);
    }
    if (ctrl && k.toLowerCase() === "z") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (ctrl && k.toLowerCase() === "y") { e.preventDefault(); redo(); return; }
    if (ctrl && k.toLowerCase() === "d") { e.preventDefault(); duplicate(); return; }
    if (ctrl && k.toLowerCase() === "a") { e.preventDefault(); select(doc.objects.filter((o) => !o.hidden && !o.locked).map((o) => o.id)); return; }
    if (ctrl && k.toLowerCase() === "c") { clipboard = selection.map((id) => JSON.parse(JSON.stringify(byId(id)))); toast(`Copied ${clipboard.length}`); return; }
    if (ctrl && k.toLowerCase() === "v") { paste(); return; }
    if (ctrl) return;
    if (k === "Delete" || k === "Backspace") { e.preventDefault(); removeObjects([...selection]); return; }
    if (k === "Enter" && chain) return endChain();
    if (rig.mode === "walk") return;
    const lower = k.toLowerCase();
    if (lower === "v") setTool("select");
    else if (lower === "g") setTool("move");
    else if (lower === "r") setTool("rotate");
    else if (lower === "t") setTool("scale");
    else if (lower === "f") focus();
    else if (lower === "h" && selection.length) { selection.forEach((id) => { byId(id).hidden = true; groups.get(id).visible = false; }); markDirty(); select([]); }
    else if (k === "PageUp") { e.preventDefault(); nudgeY(selection.length ? doc.settings.grid : 0); if (!selection.length) setLevel(level + 1); }
    else if (k === "PageDown") { e.preventDefault(); nudgeY(selection.length ? -doc.settings.grid : 0); if (!selection.length) setLevel(level - 1); }
    else if (k === "[") { brush.size = Math.max(0.5, brush.size - 0.5); drawBrushPanel(); }
    else if (k === "]") { brush.size = Math.min(30, brush.size + 0.5); drawBrushPanel(); }
    else if (k === "F1" || k === "?") { e.preventDefault(); showHelp(); }
  }
  function paste() {
    if (!clipboard.length) return;
    snapshot();
    const s = lastCursor ? surfaceAt(...lastCursor) : null;
    const cx = clipboard.reduce((a, o) => a + o.pos[0], 0) / clipboard.length, cz = clipboard.reduce((a, o) => a + o.pos[2], 0) / clipboard.length;
    const minY = Math.min(...clipboard.map((o) => o.pos[1]));
    const made = clipboard.map((src) => {
      const o = JSON.parse(JSON.stringify(src)); o.id = `o${nextId++}`;
      if (s) { o.pos[0] = round(snap(s.point.x) + (src.pos[0] - cx)); o.pos[2] = round(snap(s.point.z) + (src.pos[2] - cz)); o.pos[1] = round(s.baseY + (src.pos[1] - minY)); }
      else { o.pos[0] += 2; o.pos[2] += 2; }
      doc.objects.push(o); addGroup(o); return o.id;
    });
    markDirty(); select(made);
  }
  window.addEventListener("keydown", onKey);
  function beforeUnload(e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } }
  window.addEventListener("beforeunload", beforeUnload);

  // ---------------------------------------------------------------- status bar
  status.append(h("span", { class: "pos" }, ""), h("span", { class: "count" }, ""), h("span", { class: "faint" }, "Right-drag to look, W A S D to fly, F1 for all controls"));

  // ---------------------------------------------------------------- render loop
  let running = true, last = performance.now();
  const ro = new ResizeObserver(() => {
    const r = viewBox.getBoundingClientRect();
    if (!r.width || !r.height) return;
    renderer.setSize(r.width, r.height); camera.aspect = r.width / r.height; camera.updateProjectionMatrix();
  });
  ro.observe(viewBox);
  function loop(now) {
    if (!running) return;
    const dt = (now - last) / 1000; last = now;
    rig.update(dt);
    if (boxes.length) boxes.forEach((b) => b.update());
    renderer.render(scene, camera);
    requestAnimationFrame(loop);
  }

  // ---------------------------------------------------------------- close
  async function close() {
    if (dirty) {
      const keep = await new Promise((resolve) => {
        const d = h("dialog", {},
          h("div", { class: "d-head" }, h("h2", {}, "Save your changes?")),
          h("div", { class: "d-body" }, h("p", {}, "You changed the map since it was last saved.")),
          h("div", { class: "d-foot" },
            h("button", { onclick: () => { d.close(); resolve("cancel"); } }, "Keep editing"),
            h("button", { class: "danger", onclick: () => { d.close(); resolve("discard"); } }, "Close without saving"),
            h("button", { class: "primary", onclick: () => { d.close(); resolve("save"); } }, "Save and close")));
        d.addEventListener("close", () => d.remove());
        root.append(d); d.showModal();
      });
      if (keep === "cancel") return;
      if (keep === "save" && !(await save())) return;
    }
    running = false;
    window.removeEventListener("keydown", onKey);
    window.removeEventListener("beforeunload", beforeUnload);
    rig.dispose(); tc.dispose(); ro.disconnect();
    for (const g of groups.values()) disposeGroup(g);
    renderer.dispose();
    root.remove();
    document.body.classList.remove("studio-open");
    onClose?.();
  }

  // ---------------------------------------------------------------- start
  drawTabs(); drawPaletteItems(); drawRightTabs(); drawExtras(); rebuildAll(); setLevel(0); applySnapToGizmo(); placeSun();
  setTool("select"); drawProps();
  requestAnimationFrame(loop);
  makeThumbs().then(() => drawPaletteItems());
  if (!doc.objects.length) showHint("Start here: choose Building on the left, then click in the view. Or open the Map tab and add a sample block.");

  // small 3D pictures of every shape for the palette
  async function makeThumbs() {
    let r;
    try { r = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true }); } catch { return; }
    r.setSize(96, 96);
    const s = new THREE.Scene();
    s.add(new THREE.HemisphereLight(0xffffff, 0x667788, 1.6));
    const l = new THREE.DirectionalLight(0xffffff, 1.6); l.position.set(-3, 5, 4); s.add(l);
    const cam = new THREE.PerspectiveCamera(35, 1, 0.05, 500);
    for (const type of Object.keys(TYPES)) {
      const g = buildObject({ id: "t", ...defaults(type), pos: [0, 0, 0], rot: [0, -30, 0] });
      s.add(g);
      const box = new THREE.Box3().setFromObject(g), c = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3());
      const rad = Math.max(sz.x, sz.y, sz.z, 0.3) * 0.62;
      const dist = rad / Math.sin(THREE.MathUtils.degToRad(17.5));
      cam.position.copy(c).add(new THREE.Vector3(0.55, 0.55, 1).normalize().multiplyScalar(dist));
      cam.lookAt(c);
      r.render(s, cam);
      thumbs.set(type, r.domElement.toDataURL());
      s.remove(g); disposeGroup(g);
      await new Promise((res) => setTimeout(res, 0));
    }
    r.dispose(); r.forceContextLoss?.();
  }

  return { close };
}

function slowGraphics(renderer) {
  try {
    const gl = renderer.getContext();
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    const name = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
    return /swiftshader|llvmpipe|software|basic render/i.test(name);
  } catch { return false; }
}
