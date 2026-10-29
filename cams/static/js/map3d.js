// 3D campus view built from the same plan data as the 2D map.
// Buildings are raised to their height (with floor lines), cameras are drawn
// as small cones looking the way they face, and sightings stand as amber beams.
import * as THREE from "three";
import { get } from "./util.js";
import { buildWorld, disposeGroup, setupLights, fitSunShadow } from "./world3d.js";
import { CameraRig } from "./camrig.js";
import { Hologram, savedStyle } from "./hologram.js";

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export class Campus3D {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.1, 20000);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = !/swiftshader|llvmpipe|software|basic render/i.test(rendererName(this.renderer));
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    container.append(this.renderer.domElement);
    this.groups = { ground: new THREE.Group(), world: new THREE.Group(), buildings: new THREE.Group(), cameras: new THREE.Group(), marks: new THREE.Group() };
    Object.values(this.groups).forEach((g) => this.scene.add(g));
    this.sun = setupLights(this.scene);
    const ray = new THREE.Raycaster();
    // free camera: right-drag to look, W A S D to fly (while the mouse is over the map), left-drag to orbit
    this.controls = new CameraRig(this.camera, this.renderer.domElement, {
      leftOrbit: true,
      pick: (cx, cy) => {
        const r = this.renderer.domElement.getBoundingClientRect();
        ray.setFromCamera(new THREE.Vector2(((cx - r.left) / r.width) * 2 - 1, -((cy - r.top) / r.height) * 2 + 1), this.camera);
        const hit = ray.intersectObjects([this.groups.world, this.groups.ground], true).find((x) => !x.object.isSprite && !x.object.isLine);
        return hit ? hit.point : null;
      },
    });
    this.holo = new Hologram(this.scene, { roots: [this.groups.world, this.groups.buildings, this.groups.cameras], container, rig: this.controls });
    this.reloadScene();
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(container);
    this._resize();
    this._running = true;
    const loop = () => {
      if (!this._running) return;
      const now = performance.now();
      this.controls.update((now - (this._last || now)) / 1000);
      this.holo.sync();
      this._last = now;
      this._t = (this._t || 0) + 0.03;
      this.groups.marks.children.forEach((m) => { if (m.userData.pulse) m.scale.setScalar(1 + 0.25 * Math.sin(this._t * 3)); });
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    loop();
  }

  destroy() {
    this._running = false;
    this.holo.dispose();
    this._ro.disconnect();
    this.controls.dispose();
    disposeGroup(this.groups.world);
    this.renderer.dispose();
    this.renderer.domElement.remove();
  }

  _resize() {
    const r = this.container.getBoundingClientRect();
    if (!r.width || !r.height) return;
    this.renderer.setSize(r.width, r.height);
    this.camera.aspect = r.width / r.height;
    this.camera.updateProjectionMatrix();
  }

  _clear(g) {
    for (const c of [...g.children]) {
      g.remove(c);
      c.traverse?.((o) => {
        if (o.userData.holoEdge) return;                       // shared hologram materials stay
        o.geometry?.dispose();
        const mats = [].concat(o.userData.holoOrig || o.material || []);
        mats.forEach((m) => { m.map?.dispose(); m.dispose(); });
      });
    }
  }

  setData(data) {
    this.data = data;
    const W = data.width_m, H = data.height_m;
    if (this.holo.on) this.holo._bg = new THREE.Color(cssVar("--paper"));
    else this.scene.background = new THREE.Color(cssVar("--paper"));
    this.holo.setSite(W, H);

    // ground
    this._clear(this.groups.ground);
    const groundMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(cssVar("--sheet")), roughness: 1 });
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(W, H), groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(W / 2, 0, H / 2);
    ground.receiveShadow = true;
    this.groups.ground.add(ground);
    this._groundMat = groundMat;
    this._paintGround();
    fitSunShadow(this.sun, W / 2, H / 2, Math.max(W, H));
    const grid = new THREE.GridHelper(Math.max(W, H), Math.round(Math.max(W, H) / 10), cssVar("--line"), cssVar("--line-2"));
    grid.position.set(Math.max(W, H) / 2, 0.02, Math.max(W, H) / 2);
    grid.material.transparent = true;
    grid.material.opacity = data.image ? 0.25 : 0.6;
    this.groups.ground.add(grid);
    this.holo.ground = ground; this.holo.hideInHolo = [grid];
    if (this.holo.on) { [ground, grid].forEach((o) => { o.userData._wasVisible = true; o.visible = false; }); }
    const site = document.title.replace(/^CAMS - /, "");
    this.holo.setInfo(`SYS.LOC: ${data.geo ? `${data.geo.lat.toFixed(5)}, ${data.geo.lng.toFixed(5)}` : "GRID " + Math.round(W) + "x" + Math.round(H) + " M"} // ${site.toUpperCase()} // CAMS BLUEPRINT`);

    // buildings
    this._clear(this.groups.buildings);
    const edgeColor = new THREE.Color(cssVar("--ink"));
    for (const b of data.buildings) {
      if (b.polygon.length < 3) continue;
      const shape = new THREE.Shape(b.polygon.map(([x, y]) => new THREE.Vector2(x, -y)));
      // a building already drawn in Map Studio is shown by that drawing; the others stand up as boxes
      const drawn = this._hasWorld && this._covers(b.polygon);
      const flat = b.kind !== "building" || drawn;
      const height = flat ? 0.15 : Math.max(1, b.height_m || 6);
      const geo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      const mat = new THREE.MeshLambertMaterial({ color: new THREE.Color(b.color), transparent: true, opacity: drawn ? 0.22 : flat ? 0.45 : 0.82, depthWrite: !drawn });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData.holoFaint = flat;          // zones, fields, gates: faint in the hologram
      this.groups.buildings.add(mesh);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 30), new THREE.LineBasicMaterial({ color: edgeColor }));
      this.groups.buildings.add(edges);
      // floor lines
      if (drawn) { this.groups.buildings.add(this._label(b.name, ...centerOf(b.polygon), 2)); continue; }
      if (!flat && b.floors > 1) {
        for (let f = 1; f < b.floors; f++) {
          const y = (height / b.floors) * f;
          const pts = b.polygon.concat([b.polygon[0]]).map(([x, z]) => new THREE.Vector3(x, y, z));
          const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: edgeColor, transparent: true, opacity: 0.35 }));
          this.groups.buildings.add(line);
        }
      }
      this.groups.buildings.add(this._label(b.name, ...centerOf(b.polygon), height + 2.5));
    }

    // cameras
    this._clear(this.groups.cameras);
    const teal = new THREE.Color(cssVar("--teal"));
    const red = new THREE.Color(cssVar("--red"));
    for (const c of data.cameras) {
      if (c.map_x == null) continue;
      const bld = data.buildings.find((b) => b.id === c.building_id);
      const floorH = bld && bld.kind === "building" ? (bld.height_m / Math.max(1, bld.floors)) : 3;
      const y = Math.max(2.5, (c.floor || 0) * floorH + 2.5);
      const cone = new THREE.Mesh(new THREE.ConeGeometry(0.9, 2.2, 16), new THREE.MeshLambertMaterial({ color: c.live?.status === "offline" ? red : teal }));
      cone.position.set(c.map_x, y, c.map_y);
      const a = ((c.direction || 0) * Math.PI) / 180;
      cone.lookAt(c.map_x + Math.sin(a), y - 0.4, c.map_y - Math.cos(a));
      cone.rotateX(Math.PI / 2);
      cone.userData.holoSolid = true;          // cameras glow solid in the hologram view
      this.groups.cameras.add(cone);
      const pole = new THREE.Line(
        new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(c.map_x, 0, c.map_y), new THREE.Vector3(c.map_x, y, c.map_y)]),
        new THREE.LineBasicMaterial({ color: teal, transparent: true, opacity: 0.6 }),
      );
      this.groups.cameras.add(pole);
    }

    if (!this._framed) {
      this._framed = true;
      const span = Math.max(W, H);
      const v = this._scene?.view;
      if (v?.pos && !this._usedView) { this._usedView = true; this.camera.position.fromArray(v.pos); this.controls.yaw = v.yaw; this.controls.pitch = v.pitch; this.controls._apply(); }
      else this.controls.lookAt(new THREE.Vector3(W / 2 - span * 0.35, span * 0.75, H / 2 + span * 0.85), new THREE.Vector3(W / 2, 0, H / 2));
    }
  }

  // The 3D world drawn in Map Studio (buildings, roofs, stairs, trees, paint...)
  async reloadScene() {
    try { this._scene = await get("/api/map/scene"); } catch { this._scene = null; }
    if (!this._running) return;
    for (const c of [...this.groups.world.children]) { this.groups.world.remove(c); disposeGroup(c); }
    const w = buildWorld(this._scene);
    this._hasWorld = w.children.length > 0;
    // where the Map Studio shapes stand (ground position of each), to know which buildings it covers
    this._worldPts = w.children.map((c) => { const bb = new THREE.Box3().setFromObject(c); const m = bb.getCenter(new THREE.Vector3()); return [m.x, m.z]; });
    for (const c of [...w.children]) this.groups.world.add(c);
    this._paintImg = null;
    if (this._scene?.paint) { const im = new Image(); im.onload = () => { this._paintImg = im; this._paintGround(); }; im.src = this._scene.paint; }
    if (this.data) { if (this._scene?.view?.pos && !this._usedView) this._framed = false; this.setData(this.data); }
  }

  _paintGround() {
    const mat = this._groundMat, data = this.data;
    if (!mat || !data) return;
    const showImage = this._scene?.settings?.showImage !== false;
    const draw = (img) => {
      const W = 2048, H = Math.max(256, Math.round((2048 * data.height_m) / data.width_m));
      const c = Object.assign(document.createElement("canvas"), { width: W, height: H });
      const g = c.getContext("2d");
      g.fillStyle = this._hasWorld ? "#dfe7d8" : cssVar("--sheet"); g.fillRect(0, 0, W, H);
      if (img) g.drawImage(img, 0, 0, W, H);
      if (this._paintImg) g.drawImage(this._paintImg, 0, 0, W, H);
      const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; tex.anisotropy = 8;
      mat.map?.dispose(); mat.map = tex; mat.color.set(0xffffff); mat.needsUpdate = true;
    };
    if (data.image && showImage) { const im = new Image(); im.onload = () => draw(im); im.onerror = () => draw(null); im.src = data.image; }
    else if (this._paintImg || this._hasWorld) draw(null);
  }

  setStyle(style) { this.holo.set(style === "hologram"); }

  _covers(poly) {
    return (this._worldPts || []).some(([x, z]) => inside(x, z, poly));
  }

  setMarks({ pins = [], trail = [] } = {}) {
    this._clear(this.groups.marks);
    const amber = new THREE.Color(cssVar("--amber"));
    for (const p of pins) {
      if (p.x == null) continue;
      const beamH = p.small ? 6 : 18;
      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.25, 0.25, beamH, 8), new THREE.MeshBasicMaterial({ color: amber, transparent: true, opacity: 0.55 }));
      beam.position.set(p.x, beamH / 2, p.y);
      const ball = new THREE.Mesh(new THREE.SphereGeometry(p.small ? 0.9 : 1.8, 20, 14), new THREE.MeshLambertMaterial({ color: amber, emissive: amber, emissiveIntensity: 0.35 }));
      ball.position.set(p.x, beamH, p.y);
      ball.userData.pulse = !!p.pulse;
      this.groups.marks.add(beam, ball);
      if (p.label) this.groups.marks.add(this._label(p.label, p.x, p.y, beamH + 4));
    }
    if (trail.length > 1) {
      const pts = trail.map((t) => new THREE.Vector3(t.x, 0.6, t.y));
      const curve = new THREE.CatmullRomCurve3(pts, false, "centripetal");
      const tube = new THREE.Mesh(new THREE.TubeGeometry(curve, Math.max(20, pts.length * 12), 0.35, 6), new THREE.MeshBasicMaterial({ color: amber }));
      this.groups.marks.add(tube);
    }
  }

  _label(text, x, z, y) {
    const c = document.createElement("canvas");
    const ctx = c.getContext("2d");
    const font = "600 44px Bahnschrift, 'Segoe UI', sans-serif";
    ctx.font = font;
    const w = Math.ceil(ctx.measureText(text).width) + 28;
    c.width = w; c.height = 64;
    ctx.font = font;
    ctx.fillStyle = cssVar("--sheet");
    ctx.globalAlpha = 0.9;
    ctx.fillRect(0, 0, w, 64);
    ctx.globalAlpha = 1;
    ctx.fillStyle = cssVar("--ink");
    ctx.textBaseline = "middle";
    ctx.fillText(text, 14, 34);
    const tex = new THREE.CanvasTexture(c);
    tex.colorSpace = THREE.SRGBColorSpace;
    const spr = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false }));
    const scale = 0.06;
    spr.scale.set(w * scale, 64 * scale, 1);
    spr.position.set(x, y, z);
    spr.renderOrder = 10;
    return spr;
  }
}

function centerOf(poly) {
  let x = 0, y = 0;
  for (const p of poly) { x += p[0]; y += p[1]; }
  return [x / poly.length, y / poly.length];
}

function rendererName(r) {
  try { const gl = r.getContext(), e = gl.getExtension("WEBGL_debug_renderer_info"); return e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : ""; } catch { return ""; }
}

function inside(x, y, poly) {
  let c = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi || 1e-9) + xi) c = !c;
  }
  return c;
}
