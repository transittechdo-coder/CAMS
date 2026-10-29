// "Hologram" look for the 3D maps, like a digital blueprint:
//   - see-through teal walls ("translucent enclosure") with an X-ray / rim-light shader,
//   - floors, slabs and roofs a deeper teal ("structural core"),
//   - every structural edge drawn as a thin bright line (wireframe),
//   - cameras as small solid glowing cubes,
//   - a near-black background with a faint grid and a large range circle (no ground picture),
//   - the model turns slowly by itself (pause button), drag to turn it yourself,
//   - a legend along the top and a small "SYS.LOC" line with the site position.
//
// It works on any group of 3D objects without changing them for good: turning it on swaps
// each object's material for the hologram one (and adds glowing edges); turning it off puts
// the original materials back. sync() is called every frame, so shapes added or rebuilt in
// Map Studio while it is on are converted too.
import * as THREE from "three";
import { h, icon } from "./util.js";

export const HOLO_CYAN = new THREE.Color("#3ff4ff");
const FILL = new THREE.Color("#1fbfb4");
const CORE = new THREE.Color("#0f8c84");
const BG = new THREE.Color("#060a12");

const STYLE_KEY = "cams-3d-style";
export const savedStyle = () => { try { return localStorage.getItem(STYLE_KEY) === "hologram" ? "hologram" : "normal"; } catch { return "normal"; } };
export const saveStyle = (s) => { try { localStorage.setItem(STYLE_KEY, s); } catch {} };

// Glass with a rim: an even teal tint everywhere, a little brighter where a face is seen edge-on.
const VERT = `
#include <common>
#include <clipping_planes_pars_vertex>
varying vec3 vN;
varying vec3 vV;
void main() {
  vec4 pos = vec4(position, 1.0);
  vec3 nrm = normal;
#ifdef USE_INSTANCING
  pos = instanceMatrix * pos;
  nrm = mat3(instanceMatrix) * nrm;
#endif
  vec4 mvPosition = modelViewMatrix * pos;
  vN = normalize(normalMatrix * nrm);
  vV = normalize(-mvPosition.xyz);
  gl_Position = projectionMatrix * mvPosition;
  #include <clipping_planes_vertex>
}`;
const FRAG = `
#include <common>
#include <clipping_planes_pars_fragment>
uniform vec3 color;
uniform vec3 rimColor;
uniform float base;
uniform float rim;
uniform float power;
varying vec3 vN;
varying vec3 vV;
void main() {
  #include <clipping_planes_fragment>
  float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), power);
  gl_FragColor = vec4(mix(color, rimColor, f), clamp(base + rim * f, 0.0, 0.9));
}`;

const cache = new Map();
function glassMaterial(color, { base, rim, power = 3.0 }) {
  const key = `${color.getHexString()}:${base}:${rim}:${power}`;
  if (!cache.has(key)) {
    cache.set(key, new THREE.ShaderMaterial({
      uniforms: { color: { value: color.clone() }, rimColor: { value: HOLO_CYAN.clone() }, base: { value: base }, rim: { value: rim }, power: { value: power } },
      vertexShader: VERT, fragmentShader: FRAG,
      transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.NormalBlending, clipping: true,
    }));
  }
  return cache.get(key);
}
const WALL = () => glassMaterial(FILL, { base: 0.13, rim: 0.22 });
const SLAB = () => glassMaterial(CORE, { base: 0.32, rim: 0.2 });
const FAINT = () => glassMaterial(FILL, { base: 0.04, rim: 0.1 });
const edgeMat = new THREE.LineBasicMaterial({ color: HOLO_CYAN, transparent: true, opacity: 0.75, depthWrite: false });
const lineMat = new THREE.LineBasicMaterial({ color: HOLO_CYAN, transparent: true, opacity: 0.45, depthWrite: false });
const solidMat = new THREE.MeshBasicMaterial({ color: HOLO_CYAN });
const noRay = () => {};
const _box = new THREE.Box3(), _size = new THREE.Vector3();

export class Hologram {
  constructor(scene, { roots = [], ground = null, hideInHolo = [], container = null, rig = null, spin = true, info = "" } = {}) {
    this.scene = scene;
    this.roots = roots;            // groups whose objects become see-through
    this.ground = ground;          // ground mesh (site picture): hidden in the hologram
    this.hideInHolo = hideInHolo;  // more things to hide (outer grass, normal grid...)
    this.container = container;    // element for the legend and buttons
    this.rig = rig;
    this.spinWanted = spin;        // turn the model slowly by itself
    this.spinning = false;
    this.info = info;
    this.on = false;
    this.converted = new Set();
    this.sprites = new Set();
    this.extra = new THREE.Group();
    this.extra.visible = false;
    scene.add(this.extra);
    this.centre = new THREE.Vector3();
    this._hud = null;
    this._t = performance.now();
    this._stopSpin = () => this.setSpin(false);
  }

  // Faint grid and range circles around the site (sizes in metres).
  setSite(W, H) {
    this.centre.set(W / 2, 0, H / 2);
    this.siteR = Math.hypot(W, H) / 2;
    for (const c of [...this.extra.children]) { this.extra.remove(c); c.geometry?.dispose(); }
    const R = Math.hypot(W, H) / 2 + 10;
    const grid = new THREE.GridHelper(R * 2.6, Math.max(8, Math.round((R * 2.6) / 12)), 0x12424c, 0x0b2a32);
    grid.material.transparent = true; grid.material.opacity = 0.7; grid.material.depthWrite = false;
    grid.position.set(W / 2, 0.02, H / 2);
    grid.raycast = noRay;
    this.extra.add(grid);
    const ring = (r, opacity) => {
      const pts = Array.from({ length: 241 }, (_, i) => { const a = (i / 240) * Math.PI * 2; return new THREE.Vector3(W / 2 + Math.cos(a) * r, 0.04, H / 2 + Math.sin(a) * r); });
      const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x1fa6b3, transparent: true, opacity, depthWrite: false }));
      l.raycast = noRay;
      return l;
    };
    this.extra.add(ring(R, 0.45), ring(R * 1.3, 0.18));
  }

  setInfo(text) { this.info = text; if (this._info) this._info.textContent = text; }

  set(on) {
    if (on === this.on) return;
    this.on = on;
    const s = this.scene;
    if (on) {
      this._bg = s.background; this._fog = s.fog;
      s.background = BG.clone();
      s.fog = new THREE.Fog(BG, 600, 5000);
      [this.ground, ...this.hideInHolo].forEach((o) => { if (o) { o.userData._wasVisible = o.visible; o.visible = false; } });
      this.extra.visible = true;
      this._showHud();
      this.setSpin(this.spinWanted);
    } else {
      s.background = this._bg; s.fog = this._fog;
      [this.ground, ...this.hideInHolo].forEach((o) => { if (o) o.visible = o.userData._wasVisible ?? true; });
      this.extra.visible = false;
      for (const o of this.converted) this._restore(o);
      this.converted.clear();
      for (const sp of this.sprites) { if (sp.userData.holoSprite) { sp.material.color.copy(sp.userData.holoSprite[0]); sp.material.opacity = sp.userData.holoSprite[1]; delete sp.userData.holoSprite; } }
      this.sprites.clear();
      this.setSpin(false);
      this._hud?.remove(); this._hud = null;
    }
    this.sync();
  }

  // ------------------------------------------------------------ turning by itself
  setSpin(on) {
    this.spinning = on && this.on;
    if (this._spinBtn) {
      this._spinBtn.replaceChildren(icon(this.spinning ? "pause" : "play"));
      this._spinBtn.setAttribute("aria-label", this.spinning ? "Stop turning" : "Turn the model");
      this._spinBtn.title = this.spinning ? "Stop turning" : "Turn the model slowly";
    }
    const dom = this.rig?.dom;
    if (dom) {
      dom.removeEventListener("pointerdown", this._stopSpin);
      dom.removeEventListener("wheel", this._stopSpin);
      if (this.spinning) {
        dom.addEventListener("pointerdown", this._stopSpin);
        dom.addEventListener("wheel", this._stopSpin, { passive: true });
        // look at the middle of the site before turning around it
        // circle around the whole site, a little above it, like a model on a turntable
        const cam = this.rig.camera, to = this.centre.clone();
        const off = cam.position.clone().sub(to);
        const R = Math.max(this.siteR || 50, 15);
        this._radius = R * 1.55;
        this._height = R * 0.95;
        this._angle = Math.atan2(off.z, off.x);
        this.rig.flyTo(new THREE.Vector3(to.x + Math.cos(this._angle) * this._radius, this._height, to.z + Math.sin(this._angle) * this._radius), to, 500);
        this._spinFrom = performance.now() + 520;
      }
    }
  }

  _spinStep(dt) {
    if (!this.spinning || !this.rig || performance.now() < this._spinFrom || this.rig.mode === "walk") return;
    this._angle += dt * 0.18;
    const c = this.centre;
    this.rig.lookAt(new THREE.Vector3(c.x + Math.cos(this._angle) * this._radius, this._height, c.z + Math.sin(this._angle) * this._radius), c);
  }

  // ------------------------------------------------------------ every frame
  sync() {
    const now = performance.now(), dt = Math.min(0.1, (now - this._t) / 1000);
    this._t = now;
    if ((this._n = (this._n || 0) + 1) % 240 === 0) {
      for (const o of this.converted) if (!o.parent) this.converted.delete(o);
      for (const o of this.sprites) if (!o.parent) this.sprites.delete(o);
    }
    if (this.on) {
      const todo = [];
      for (const r of this.roots) r?.traverse((o) => {
        if (o.userData.holoEdge || o.userData.holoDone || o.userData.noHolo) return;
        if (o.isSprite) { if (!o.userData.holoSprite) this._tintSprite(o); return; }
        if (o.isMesh || o.isLine) todo.push(o);
      });
      for (const o of todo) this._convert(o);
      this._spinStep(dt);
    }
  }

  _tintSprite(sp) {
    sp.userData.holoSprite = [sp.material.color.clone(), sp.material.opacity];
    sp.material.color.set("#6fe9f2");
    sp.material.opacity = 0.75;
    this.sprites.add(sp);
  }

  _convert(o) {
    o.userData.holoDone = true;
    o.userData.holoOrig = o.material;
    this.converted.add(o);
    if (o.isLine) { o.material = lineMat; return; }
    o.userData.holoShadow = [o.castShadow, o.receiveShadow];
    o.castShadow = false; o.receiveShadow = false;
    if (o.userData.holoSolid) { o.material = solidMat; return; }
    const orig = [].concat(o.material)[0];
    // floors, slabs and roofs: flat and wide -> the darker "structural core"
    _box.setFromObject(o).getSize(_size);
    const flat = _size.y < 0.7 && Math.max(_size.x, _size.z) > 1.5;
    const faint = o.userData.holoFaint || (orig?.transparent && orig.opacity < 0.35);     // zones, fields, glass
    o.material = faint ? FAINT() : flat ? SLAB() : WALL();
    if (o.geometry && !o.isInstancedMesh && o.geometry.attributes.position.count < 60000) {
      const e = new THREE.LineSegments(new THREE.EdgesGeometry(o.geometry, 28), edgeMat);
      e.userData.holoEdge = true;
      e.raycast = noRay;
      o.add(e);
      o.userData.holoEdgeObj = e;
    }
  }

  _restore(o) {
    if (o.userData.holoOrig) o.material = o.userData.holoOrig;
    if (o.userData.holoShadow) [o.castShadow, o.receiveShadow] = o.userData.holoShadow;
    const e = o.userData.holoEdgeObj;
    if (e) { o.remove(e); e.geometry.dispose(); }
    delete o.userData.holoOrig; delete o.userData.holoEdgeObj; delete o.userData.holoDone; delete o.userData.holoShadow;
  }

  _showHud() {
    if (!this.container) return;
    this._spinBtn = h("button", { class: "holo-spin", onclick: () => { this.spinWanted = !this.spinning; this.setSpin(!this.spinning); } });
    this._info = h("div", { class: "holo-info" }, this.info);
    this._hud = h("div", { class: "holo-hud" },
      h("div", { class: "holo-legend", "aria-hidden": "true" },
        h("span", {}, h("i", { class: "dot" }), "See-through walls"),
        h("span", {}, h("i", { class: "sq" }), "Floors and structure"),
        h("span", {}, h("i", { class: "cam" }), "Cameras"),
        h("span", { class: "faint" }, "⟲ Drag to turn the model")),
      this._spinBtn, this._info);
    this.container.append(this._hud);
  }

  dispose() {
    this.set(false);
    this.scene.remove(this.extra);
  }
}
