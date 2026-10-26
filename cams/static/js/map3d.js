// 3D campus view built from the same plan data as the 2D map.
// Buildings are raised to their height (with floor lines), cameras are drawn
// as small cones looking the way they face, and sightings stand as amber beams.
import * as THREE from "three";
import { OrbitControls } from "/static/vendor/OrbitControls.js";

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#888";
}

export class Campus3D {
  constructor(container) {
    this.container = container;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.5, 20000);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.append(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.maxPolarAngle = Math.PI * 0.48;
    this.groups = { ground: new THREE.Group(), buildings: new THREE.Group(), cameras: new THREE.Group(), marks: new THREE.Group() };
    Object.values(this.groups).forEach((g) => this.scene.add(g));
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.1));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(-200, 400, -150);
    this.scene.add(sun);
    this._ro = new ResizeObserver(() => this._resize());
    this._ro.observe(container);
    this._resize();
    this._running = true;
    const loop = () => {
      if (!this._running) return;
      this.controls.update();
      this._t = (this._t || 0) + 0.03;
      this.groups.marks.children.forEach((m) => { if (m.userData.pulse) m.scale.setScalar(1 + 0.25 * Math.sin(this._t * 3)); });
      this.renderer.render(this.scene, this.camera);
      requestAnimationFrame(loop);
    };
    loop();
  }

  destroy() {
    this._running = false;
    this._ro.disconnect();
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
      c.traverse?.((o) => { o.geometry?.dispose(); if (o.material) [].concat(o.material).forEach((m) => { m.map?.dispose(); m.dispose(); }); });
    }
  }

  setData(data) {
    this.data = data;
    const W = data.width_m, H = data.height_m;
    this.scene.background = new THREE.Color(cssVar("--paper"));

    // ground
    this._clear(this.groups.ground);
    const groundMat = new THREE.MeshLambertMaterial({ color: new THREE.Color(cssVar("--sheet")) });
    const ground = new THREE.Mesh(new THREE.PlaneGeometry(W, H), groundMat);
    ground.rotation.x = -Math.PI / 2;
    ground.position.set(W / 2, 0, H / 2);
    this.groups.ground.add(ground);
    if (data.image) {
      new THREE.TextureLoader().load(data.image, (tex) => {
        tex.colorSpace = THREE.SRGBColorSpace;
        groundMat.map = tex;
        groundMat.color.set(0xffffff);
        groundMat.needsUpdate = true;
      });
    }
    const grid = new THREE.GridHelper(Math.max(W, H), Math.round(Math.max(W, H) / 10), cssVar("--line"), cssVar("--line-2"));
    grid.position.set(Math.max(W, H) / 2, 0.02, Math.max(W, H) / 2);
    grid.material.transparent = true;
    grid.material.opacity = data.image ? 0.25 : 0.6;
    this.groups.ground.add(grid);

    // buildings
    this._clear(this.groups.buildings);
    const edgeColor = new THREE.Color(cssVar("--ink"));
    for (const b of data.buildings) {
      if (b.polygon.length < 3) continue;
      const shape = new THREE.Shape(b.polygon.map(([x, y]) => new THREE.Vector2(x, -y)));
      const flat = b.kind !== "building";
      const height = flat ? 0.15 : Math.max(1, b.height_m || 6);
      const geo = new THREE.ExtrudeGeometry(shape, { depth: height, bevelEnabled: false });
      geo.rotateX(-Math.PI / 2);
      const mat = new THREE.MeshLambertMaterial({ color: new THREE.Color(b.color), transparent: true, opacity: flat ? 0.45 : 0.82 });
      const mesh = new THREE.Mesh(geo, mat);
      this.groups.buildings.add(mesh);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geo, 30), new THREE.LineBasicMaterial({ color: edgeColor }));
      this.groups.buildings.add(edges);
      // floor lines
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
      this.controls.target.set(W / 2, 0, H / 2);
      this.camera.position.set(W / 2 - span * 0.35, span * 0.75, H / 2 + span * 0.85);
      this.controls.update();
    }
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
