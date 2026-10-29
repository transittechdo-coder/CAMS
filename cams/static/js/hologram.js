// "Hologram" look for the 3D maps: see-through walls whose edges glow (an X-ray / rim-light
// shader), every structural edge drawn as a bright line (wireframe), a dark blueprint
// background with a glowing grid and range ring, and a small on-screen legend and compass.
//
// It works on any group of 3D objects without changing them for good: turning it on swaps
// each object's material for the hologram one (and adds glowing edges); turning it off puts
// the original materials back. sync() is called every frame, so shapes added or rebuilt in
// Map Studio while it is on are converted too.
import * as THREE from "three";
import { h, mouseSwapped } from "./util.js";

export const HOLO_CYAN = new THREE.Color("#2ee8ff");
const BG = new THREE.Color("#050b14");

const STYLE_KEY = "cams-3d-style";
export const savedStyle = () => { try { return localStorage.getItem(STYLE_KEY) === "hologram" ? "hologram" : "normal"; } catch { return "normal"; } };
export const saveStyle = (s) => { try { localStorage.setItem(STYLE_KEY, s); } catch {} };

// Rim light: faces looking at you are almost clear, faces seen edge-on glow.
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
uniform float base;
uniform float rim;
uniform float power;
varying vec3 vN;
varying vec3 vV;
void main() {
  #include <clipping_planes_fragment>
  float f = pow(1.0 - abs(dot(normalize(vN), normalize(vV))), power);
  // dark teal glass in the middle of a face, bright cyan where you see it edge-on
  vec3 c = mix(color * 0.32, color * 1.25, f);
  gl_FragColor = vec4(c, clamp(base + rim * f, 0.0, 0.85));
}`;

const cache = new Map();
function rimMaterial(color = HOLO_CYAN, { base = 0.09, rim = 0.5, power = 2.4 } = {}) {
  const key = `${color.getHexString()}:${base}:${rim}:${power}`;
  if (!cache.has(key)) {
    cache.set(key, new THREE.ShaderMaterial({
      uniforms: { color: { value: color.clone() }, base: { value: base }, rim: { value: rim }, power: { value: power } },
      vertexShader: VERT, fragmentShader: FRAG,
      transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.NormalBlending, clipping: true,
    }));
  }
  return cache.get(key);
}
const edgeMat = new THREE.LineBasicMaterial({ color: HOLO_CYAN, transparent: true, opacity: 0.85, depthWrite: false, blending: THREE.AdditiveBlending });
const lineMat = new THREE.LineBasicMaterial({ color: HOLO_CYAN, transparent: true, opacity: 0.55, depthWrite: false });
const solidMat = new THREE.MeshBasicMaterial({ color: HOLO_CYAN });
const noRay = () => {};

export class Hologram {
  constructor(scene, { roots = [], ground = null, hideInHolo = [], container = null, rig = null } = {}) {
    this.scene = scene;
    this.roots = roots;            // groups whose objects become see-through
    this.ground = ground;          // ground mesh: kept, but darkened
    this.hideInHolo = hideInHolo;  // things to hide (outer grass, normal grid...)
    this.container = container;    // element for the legend and compass
    this.rig = rig;
    this.on = false;
    this.converted = new Set();
    this.extra = new THREE.Group();
    this.extra.visible = false;
    scene.add(this.extra);
    this._hud = null;
  }

  // Grid, range ring and glow around the site (sizes in metres).
  setSite(W, H) {
    for (const c of [...this.extra.children]) { this.extra.remove(c); c.geometry?.dispose(); }
    const span = Math.ceil(Math.max(W, H) / 10) * 10 + 20;
    const grid = new THREE.GridHelper(span * 1.6, Math.round((span * 1.6) / 10), 0x1b8fa3, 0x0f4c5c);
    grid.material.transparent = true; grid.material.opacity = 0.55; grid.material.depthWrite = false;
    grid.position.set(W / 2, 0.04, H / 2);
    grid.raycast = noRay;
    this.extra.add(grid);
    const ring = (r, opacity) => {
      const pts = Array.from({ length: 181 }, (_, i) => { const a = (i / 180) * Math.PI * 2; return new THREE.Vector3(W / 2 + Math.cos(a) * r, 0.06, H / 2 + Math.sin(a) * r); });
      const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: HOLO_CYAN, transparent: true, opacity, depthWrite: false }));
      l.raycast = noRay;
      return l;
    };
    const R = Math.hypot(W, H) / 2 + 8;
    this.extra.add(ring(R, 0.7), ring(R * 1.35, 0.25));
    // compass ticks on the outer ring
    for (let i = 0; i < 36; i++) {
      const a = (i / 36) * Math.PI * 2, r0 = R * 1.35, r1 = r0 + (i % 9 === 0 ? 4 : 1.6);
      const l = new THREE.Line(new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(W / 2 + Math.cos(a) * r0, 0.06, H / 2 + Math.sin(a) * r0), new THREE.Vector3(W / 2 + Math.cos(a) * r1, 0.06, H / 2 + Math.sin(a) * r1)]),
        new THREE.LineBasicMaterial({ color: HOLO_CYAN, transparent: true, opacity: 0.5 }));
      l.raycast = noRay;
      this.extra.add(l);
    }
  }

  set(on) {
    if (on === this.on) return;
    this.on = on;
    const s = this.scene;
    if (on) {
      this._bg = s.background; this._fog = s.fog;
      s.background = BG.clone();
      s.fog = new THREE.Fog(BG, 400, 4000);
      if (this.ground) { this._groundColor = this.ground.material.color.clone(); this.ground.material.color.set("#24404d"); }
      this.hideInHolo.forEach((o) => { if (o) { o.userData._wasVisible = o.visible; o.visible = false; } });
      this.extra.visible = true;
      this._showHud();
    } else {
      s.background = this._bg; s.fog = this._fog;
      if (this.ground && this._groundColor) this.ground.material.color.copy(this._groundColor);
      this.hideInHolo.forEach((o) => { if (o) o.visible = o.userData._wasVisible ?? true; });
      this.extra.visible = false;
      for (const o of this.converted) this._restore(o);
      this.converted.clear();
      this._hud?.remove(); this._hud = null;
    }
    this.sync();
  }

  // Call every frame: converts anything new in the groups while the hologram is on.
  sync() {
    if ((this._n = (this._n || 0) + 1) % 240 === 0) for (const o of this.converted) if (!o.parent) this.converted.delete(o);
    if (this.on) {
      const todo = [];
      for (const r of this.roots) r?.traverse((o) => { if (!o.userData.holoEdge && !o.userData.holoDone && (o.isMesh || o.isLine) && !o.isSprite && !o.userData.noHolo) todo.push(o); });
      for (const o of todo) this._convert(o);
    }
    if (this._compass && this.rig) this._compass.style.transform = `rotate(${(this.rig.yaw * 180) / Math.PI}deg)`;
  }

  // A plane hidden under everything still has to count for clicks; walls must stay pickable.
  _convert(o) {
    o.userData.holoDone = true;
    o.userData.holoOrig = o.material;
    this.converted.add(o);
    if (o.isLine) { o.material = lineMat; return; }
    if (o.userData.holoSolid) { o.material = solidMat; return; }
    const orig = [].concat(o.material)[0];
    const faint = orig?.transparent && orig.opacity < 0.35;     // zones, fields, glass: fainter
    o.material = rimMaterial(HOLO_CYAN, faint ? { base: 0.03, rim: 0.22, power: 2.4 } : undefined);
    o.userData.holoShadow = [o.castShadow, o.receiveShadow];
    o.castShadow = false; o.receiveShadow = false;
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
    this._compass = h("div", { class: "holo-needle" }, h("b", {}, "N"));
    const turn = mouseSwapped() ? "left" : "right";
    this._hud = h("div", { class: "holo-hud", "aria-hidden": "true" },
      h("div", { class: "holo-legend" },
        h("span", {}, h("i", { class: "dot" }), "See-through walls"),
        h("span", {}, h("i", { class: "sq" }), "Structure edges"),
        h("span", { class: "faint" }, `Drag with the ${turn} button to look around`)),
      h("div", { class: "holo-compass" }, this._compass),
      h("div", { class: "holo-corner tl" }), h("div", { class: "holo-corner tr" }), h("div", { class: "holo-corner bl" }), h("div", { class: "holo-corner br" }));
    this.container.append(this._hud);
  }

  dispose() {
    this.set(false);
    this.scene.remove(this.extra);
  }
}
