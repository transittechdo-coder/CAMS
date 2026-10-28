// Game-style camera for CAMS 3D maps.
//   Right mouse drag ........ look around (like a game)
//   W A S D / arrow keys .... fly forward, left, back, right
//   Q / E ................... down / up        Shift = faster
//   Middle drag ............. slide (pan)      Wheel = zoom to the cursor
//   Left drag (empty space) . orbit around the point you grabbed
//   Walk mode ............... walk at eye height, climb stairs, Space to jump
import * as THREE from "three";

const TYPING = (el) => el && (el.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName));

export class CameraRig {
  constructor(camera, dom, opts = {}) {
    this.camera = camera;
    this.dom = dom;
    this.opts = opts;           // { pick(clientX, clientY) -> Vector3|null, floorAt(x,z,y) -> y|null, blocked(from, dir, dist) -> bool, keysAlways }
    this.yaw = 0; this.pitch = -0.6;
    this.speed = 1;             // user speed multiplier
    this.keys = new Set();
    this.mode = "fly";          // fly | walk
    this.enabled = true;
    this.vy = 0;
    this._hover = false;
    this._drag = null;
    this._anim = null;

    this._onDown = (e) => this._down(e);
    this._onMove = (e) => this._move(e);
    this._onUp = (e) => this._up(e);
    this._onWheel = (e) => this._wheel(e);
    this._onKey = (e) => this._key(e, true);
    this._onKeyUp = (e) => this._key(e, false);
    this._onLockMove = (e) => this._lockMove(e);
    this._onLockChange = () => { if (document.pointerLockElement !== dom && this.mode === "walk") this.opts.onWalkExit?.(); };
    dom.addEventListener("pointerdown", this._onDown);
    dom.addEventListener("wheel", this._onWheel, { passive: false });
    dom.addEventListener("contextmenu", (e) => e.preventDefault());
    dom.addEventListener("pointerenter", () => (this._hover = true));
    dom.addEventListener("pointerleave", () => (this._hover = false));
    window.addEventListener("pointermove", this._onMove);
    window.addEventListener("pointerup", this._onUp);
    window.addEventListener("keydown", this._onKey);
    window.addEventListener("keyup", this._onKeyUp);
    window.addEventListener("blur", () => this.keys.clear());
    document.addEventListener("mousemove", this._onLockMove);
    document.addEventListener("pointerlockchange", this._onLockChange);
  }

  dispose() {
    this.dom.removeEventListener("pointerdown", this._onDown);
    this.dom.removeEventListener("wheel", this._onWheel);
    window.removeEventListener("pointermove", this._onMove);
    window.removeEventListener("pointerup", this._onUp);
    window.removeEventListener("keydown", this._onKey);
    window.removeEventListener("keyup", this._onKeyUp);
    document.removeEventListener("mousemove", this._onLockMove);
    document.removeEventListener("pointerlockchange", this._onLockChange);
    if (document.pointerLockElement === this.dom) document.exitPointerLock();
  }

  // ------------------------------------------------------------ placement
  lookAt(pos, target) {
    this.camera.position.copy(pos);
    const d = new THREE.Vector3().subVectors(target, pos).normalize();
    this.yaw = Math.atan2(-d.x, -d.z);
    this.pitch = Math.asin(THREE.MathUtils.clamp(d.y, -1, 1));
    this._apply();
  }

  // Smoothly fly to a new viewpoint.
  flyTo(pos, target, ms = 600) {
    const from = this.camera.position.clone();
    const fromYaw = this.yaw, fromPitch = this.pitch;
    const d = new THREE.Vector3().subVectors(target, pos).normalize();
    let toYaw = Math.atan2(-d.x, -d.z);
    while (toYaw - fromYaw > Math.PI) toYaw -= Math.PI * 2;
    while (toYaw - fromYaw < -Math.PI) toYaw += Math.PI * 2;
    const toPitch = Math.asin(THREE.MathUtils.clamp(d.y, -1, 1));
    this._anim = { t0: performance.now(), ms, from, to: pos.clone(), fromYaw, toYaw, fromPitch, toPitch };
  }

  frame(box) {
    if (box.isEmpty()) return;
    const c = box.getCenter(new THREE.Vector3()), s = box.getSize(new THREE.Vector3());
    const r = Math.max(s.x, s.y, s.z, 4);
    const dir = new THREE.Vector3(-0.45, 0.75, 0.95).normalize();
    this.flyTo(c.clone().addScaledVector(dir, r * 1.25), c);
  }

  forward() { return new THREE.Vector3(0, 0, -1).applyQuaternion(this.camera.quaternion); }

  _apply() {
    this.pitch = THREE.MathUtils.clamp(this.pitch, -Math.PI / 2 + 0.01, Math.PI / 2 - 0.01);
    this.camera.rotation.set(this.pitch, this.yaw, 0, "YXZ");
  }

  // ------------------------------------------------------------ walking
  startWalk() {
    this.mode = "walk";
    this.vy = 0;
    const p = this.camera.position;
    const fy = this.opts.floorAt?.(p.x, p.z, 1e4) ?? 0;
    p.y = fy + 1.65;
    this.pitch = 0; this._apply();
    this.dom.requestPointerLock?.();
  }

  stopWalk() {
    this.mode = "fly";
    if (document.pointerLockElement === this.dom) document.exitPointerLock();
  }

  _lockMove(e) {
    if (this.mode !== "walk" || document.pointerLockElement !== this.dom) return;
    this.yaw -= e.movementX * 0.0022;
    this.pitch -= e.movementY * 0.0022;
    this._apply();
  }

  // ------------------------------------------------------------ mouse
  startOrbit(e, pivot) {
    this._drag = { kind: "orbit", x: e.clientX, y: e.clientY, pivot: pivot || this._pivotAhead() };
    this.dom.setPointerCapture?.(e.pointerId);
  }

  _pivotAhead() {
    // point on the ground straight ahead, or 30 m in front
    const f = this.forward(), p = this.camera.position;
    if (f.y < -0.05) { const t = -p.y / f.y; if (t > 0 && t < 5000) return p.clone().addScaledVector(f, t); }
    return p.clone().addScaledVector(f, 30);
  }

  _down(e) {
    if (!this.enabled || this.mode === "walk") return;
    if (e.button === 2) { this._drag = { kind: "look", x: e.clientX, y: e.clientY }; this.dom.setPointerCapture?.(e.pointerId); }
    else if (e.button === 1) {
      e.preventDefault();
      const hit = this.opts.pick?.(e.clientX, e.clientY);
      const dist = hit ? hit.distanceTo(this.camera.position) : 30;
      this._drag = { kind: "pan", x: e.clientX, y: e.clientY, dist };
    } else if (e.button === 0 && (e.altKey || this.opts.leftOrbit)) {
      this.startOrbit(e, this.opts.pick?.(e.clientX, e.clientY));
    }
  }

  _move(e) {
    const d = this._drag;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    d.x = e.clientX; d.y = e.clientY;
    if (d.kind === "look") {
      this.yaw -= dx * 0.0035; this.pitch -= dy * 0.0035; this._apply();
    } else if (d.kind === "pan") {
      const h = this.dom.clientHeight || 600;
      const k = (2 * d.dist * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))) / h;
      const right = new THREE.Vector3(1, 0, 0).applyQuaternion(this.camera.quaternion);
      const up = new THREE.Vector3(0, 1, 0).applyQuaternion(this.camera.quaternion);
      this.camera.position.addScaledVector(right, -dx * k).addScaledVector(up, dy * k);
    } else if (d.kind === "orbit") {
      const p = this.camera.position, P = d.pivot;
      const off = p.clone().sub(P);
      const qYaw = new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), -dx * 0.006);
      off.applyQuaternion(qYaw);
      const right = new THREE.Vector3(1, 0, 0).applyQuaternion(this.camera.quaternion).applyQuaternion(qYaw);
      const newPitch = this.pitch + qYaw.y * 0 - dy * 0.006;
      if (newPitch > -Math.PI / 2 + 0.05 && newPitch < Math.PI / 2 - 0.05) off.applyQuaternion(new THREE.Quaternion().setFromAxisAngle(right, -dy * 0.006));
      p.copy(P).add(off);
      if (p.y < 0.3) p.y = 0.3;
      this.lookAt(p.clone(), P);
    }
  }

  _up() { this._drag = null; }

  _wheel(e) {
    if (!this.enabled || this.mode === "walk") return;
    e.preventDefault();
    this._anim = null;
    const amount = THREE.MathUtils.clamp(-e.deltaY * (e.deltaMode === 1 ? 33 : 1), -400, 400) / 400; // -1 .. 1
    const hit = this.opts.pick?.(e.clientX, e.clientY);
    const p = this.camera.position;
    if (hit) {
      const dist = hit.distanceTo(p);
      const step = dist * 0.3 * amount;
      if (amount > 0 && dist - step < 0.8) return;
      p.addScaledVector(hit.clone().sub(p).normalize(), step);
    } else {
      p.addScaledVector(this.forward(), Math.max(3, p.y) * 0.4 * amount);
    }
  }

  _key(e, down) {
    if (!down) { this.keys.delete(e.code); return; }
    if (!this.enabled || e.ctrlKey || e.metaKey || e.altKey || TYPING(document.activeElement)) return;
    if (!this.opts.keysAlways && !this._hover && this.mode !== "walk") return;
    const MOVE = ["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "ShiftLeft", "ShiftRight", "Space"];
    if (!MOVE.includes(e.code)) return;
    if (e.code === "Space" && this.mode !== "walk") return;
    this.keys.add(e.code);
    if (e.code.startsWith("Arrow") || e.code === "Space") e.preventDefault();
  }

  moving() { return [...this.keys].some((k) => !k.startsWith("Shift")); }

  // ------------------------------------------------------------ per frame
  update(dt) {
    dt = Math.min(dt, 0.1);
    if (this._anim) {
      const a = this._anim, t = Math.min(1, (performance.now() - a.t0) / a.ms), s = t * t * (3 - 2 * t);
      this.camera.position.lerpVectors(a.from, a.to, s);
      this.yaw = a.fromYaw + (a.toYaw - a.fromYaw) * s;
      this.pitch = a.fromPitch + (a.toPitch - a.fromPitch) * s;
      this._apply();
      if (t >= 1) this._anim = null;
      return true;
    }
    const k = this.keys;
    const fast = k.has("ShiftLeft") || k.has("ShiftRight");
    let fx = 0, fz = 0, fy = 0;
    if (k.has("KeyW") || k.has("ArrowUp")) fz += 1;
    if (k.has("KeyS") || k.has("ArrowDown")) fz -= 1;
    if (k.has("KeyD") || k.has("ArrowRight")) fx += 1;
    if (k.has("KeyA") || k.has("ArrowLeft")) fx -= 1;
    if (k.has("KeyE")) fy += 1;
    if (k.has("KeyQ")) fy -= 1;
    const p = this.camera.position;

    if (this.mode === "walk") return this._walk(dt, fx, fz, fast);

    if (!fx && !fz && !fy) return false;
    this._anim = null;
    // fly speed grows with height so big campuses are quick to cross
    const v = Math.max(6, Math.min(p.y, 400) * 0.9) * this.speed * (fast ? 3 : 1) * dt;
    const f = this.forward();
    const right = new THREE.Vector3(1, 0, 0).applyQuaternion(this.camera.quaternion);
    p.addScaledVector(f, fz * v).addScaledVector(right, fx * v);
    p.y += fy * v;
    if (p.y < 0.4) p.y = 0.4;
    return true;
  }

  _walk(dt, fx, fz, fast) {
    const p = this.camera.position;
    const speed = (fast ? 5 : 2) * this.speed;
    const flat = new THREE.Vector3(-Math.sin(this.yaw), 0, -Math.cos(this.yaw));
    const right = new THREE.Vector3(-flat.z, 0, flat.x);
    const move = flat.multiplyScalar(fz).add(right.multiplyScalar(fx));
    if (move.lengthSq() > 0) {
      move.normalize().multiplyScalar(speed * dt);
      const knee = new THREE.Vector3(p.x, p.y - 1.1, p.z);
      const dir = move.clone().normalize();
      const b1 = this.opts.blocked?.(knee, dir, move.length() + 0.35), b2 = this.opts.blocked?.(p, dir, move.length() + 0.35);
      if ((b1 === "ladder" || b2 === "ladder") && fz > 0) {
        p.y += 2.2 * dt; this.vy = 0;            // climbing a ladder
        return true;
      }
      if (!b1 && !b2) p.add(move);
    }
    const floor = this.opts.floorAt?.(p.x, p.z, p.y - 1.65 + 0.6) ?? 0; // can step up 0.6 m (stairs)
    const eye = floor + 1.65;
    if (this.keys.has("Space") && p.y <= eye + 0.01) { this.vy = 4.2; }
    this.vy -= 12 * dt;
    p.y += this.vy * dt;
    if (p.y <= eye) {
      if (eye - p.y < 0.65) p.y = THREE.MathUtils.lerp(p.y, eye, 0.5); else p.y = eye;
      if (p.y < eye) p.y = eye;
      this.vy = Math.max(0, this.vy);
    }
    return true;
  }
}
