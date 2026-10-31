// 2D site plan: shows buildings, cameras, sightings and a person's trail.
// In builder mode it also lets you draw shapes and drag cameras into place.
// World units are metres; x to the right, y down (same as the map image).

import { mouseSwapped } from "./util.js";

const NS = "http://www.w3.org/2000/svg";
const FOV_RANGE_M = 14;

function s(tag, attrs = {}) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) el.setAttribute(k, v);
  return el;
}

export class SiteMap {
  constructor(container, opts = {}) {
    this.opts = opts;
    this.editable = !!opts.editable;
    this.data = { width_m: 200, height_m: 150, image: null, buildings: [], cameras: [] };
    this.pins = [];
    this.trail = [];
    this.route = [];               // stops of a person's route, oldest first
    this.routeSel = null;
    this.mode = "select";
    this.selected = null;          // {kind: "building"|"camera", id}
    this.draft = null;             // points being drawn
    this.view = { x: 0, y: 0, w: 200, h: 150 };
    this.svg = s("svg", { class: "map-svg", role: "img", "aria-label": "Campus site plan" });
    this.root = s("g");
    this.svg.append(this.root);
    container.append(this.svg);
    this._bind();
    this._ro = new ResizeObserver(() => this._applyView());
    this._ro.observe(this.svg);
  }

  destroy() { this._ro.disconnect(); this.svg.remove(); }

  // ----------------------------------------------------------- data
  setData(data) {
    this.data = data;
    if (!this._fitted) { this.fit(); this._fitted = true; }
    this.render();
  }
  setPins(pins) { this.pins = pins || []; this.render(); }
  setTrail(points) { this.trail = points || []; this.render(); }
  setRoute(stops) { this.route = stops || []; if (this.routeSel != null && this.routeSel >= this.route.length) this.routeSel = null; this.render(); }
  selectStop(i) { this.routeSel = i; this.render(); }
  setMode(mode) { this.mode = mode; this.draft = null; this.svg.style.cursor = mode === "select" ? "" : "crosshair"; this.render(); }
  select(sel) { this.selected = sel; this.render(); }

  fit() {
    const { width_m: w, height_m: hgt } = this.data;
    const pad = Math.max(w, hgt) * 0.04;
    this.view = { x: -pad, y: -pad, w: w + pad * 2, h: hgt + pad * 2 };
    this._applyView();
  }

  focus(x, y, span = 60) {
    this.view = { x: x - span / 2, y: y - span / 2, w: span, h: span };
    this._applyView();
  }

  _applyView() {
    const r = this.svg.getBoundingClientRect();
    if (!r.width || !r.height) return;
    // keep aspect ratio of the element
    const aspect = r.width / r.height;
    let { x, y, w, h } = this.view;
    if (w / h > aspect) { const nh = w / aspect; y -= (nh - h) / 2; h = nh; }
    else { const nw = h * aspect; x -= (nw - w) / 2; w = nw; }
    this.view = { x, y, w, h };
    this.svg.setAttribute("viewBox", `${x} ${y} ${w} ${h}`);
    this.px = w / r.width;   // metres per screen pixel
    this.render();
  }

  toWorld(evt) {
    const pt = this.svg.createSVGPoint();
    pt.x = evt.clientX; pt.y = evt.clientY;
    const m = this.svg.getScreenCTM();
    const p = pt.matrixTransform(m.inverse());
    return [p.x, p.y];
  }

  // ----------------------------------------------------------- render
  render() {
    const d = this.data;
    const px = this.px || 0.3;
    const g = this.root;
    g.replaceChildren();

    // paper + image
    g.append(s("rect", { x: 0, y: 0, width: d.width_m, height: d.height_m, fill: "var(--paper)" }));
    if (d.image) {
      const img = s("image", { x: 0, y: 0, width: d.width_m, height: d.height_m, preserveAspectRatio: "none", opacity: 0.85 });
      img.setAttributeNS("http://www.w3.org/1999/xlink", "href", d.image);
      img.setAttribute("href", d.image);
      g.append(img);
    }
    // survey grid every 10 m (50 m when zoomed out)
    const step = px > 0.6 ? 50 : 10;
    for (let x = 0; x <= d.width_m; x += step) g.append(s("line", { class: "gridline", x1: x, y1: 0, x2: x, y2: d.height_m }));
    for (let y = 0; y <= d.height_m; y += step) g.append(s("line", { class: "gridline", x1: 0, y1: y, x2: d.width_m, y2: y }));
    g.append(s("rect", { x: 0, y: 0, width: d.width_m, height: d.height_m, fill: "none", stroke: "var(--line)", "vector-effect": "non-scaling-stroke" }));

    // buildings
    for (const b of d.buildings) {
      const sel = this.selected?.kind === "building" && this.selected.id === b.id;
      const poly = s("polygon", {
        class: `bld ${b.kind}${sel ? " sel" : ""}${(b.access_mode && b.access_mode !== "everyone") || b.closed_hours ? " ruled" : ""}`, fill: b.color,
        points: b.polygon.map((p) => p.join(",")).join(" "), "data-bid": b.id,
      });
      poly.style.cursor = this.editable && this.mode === "select" ? "pointer" : "";
      g.append(poly);
      const [cx, cy] = centroid(b.polygon);
      const t = s("text", { class: "bld-label", x: cx, y: cy, "text-anchor": "middle", "dominant-baseline": "middle", "font-size": 12 * px });
      t.textContent = b.name;
      t.style.fontSize = `${12 * px}px`;
      t.style.strokeWidth = `${3 * px}px`;
      g.append(t);
      if (sel && this.editable) {
        b.polygon.forEach((p, i) => g.append(s("circle", { class: "handle", cx: p[0], cy: p[1], r: 5 * px, "data-vertex": i, "data-bid": b.id })));
      }
    }

    // cameras
    for (const c of d.cameras) {
      if (c.map_x == null || c.map_y == null) continue;
      const sel = this.selected?.kind === "camera" && this.selected.id === c.id;
      g.append(s("path", { class: "cam-fov", d: wedge(c.map_x, c.map_y, c.direction || 0, c.fov || 90, FOV_RANGE_M) }));
      const status = c.live?.status || "stopped";
      g.append(s("circle", {
        class: `cam-dot ${status === "offline" ? "offline" : ""} ${c.restricted ? "restricted" : ""} ${sel ? "sel" : ""}`,
        cx: c.map_x, cy: c.map_y, r: 6 * px, "data-cid": c.id,
      }));
      const lbl = s("text", { class: "cam-label", x: c.map_x + 9 * px, y: c.map_y + 4 * px });
      lbl.style.fontSize = `${11 * px}px`;
      lbl.style.strokeWidth = `${3 * px}px`;
      lbl.textContent = c.name;
      g.append(lbl);
      if (sel && this.editable) {
        const a = ((c.direction || 0) * Math.PI) / 180;
        const hx = c.map_x + Math.sin(a) * FOV_RANGE_M, hy = c.map_y - Math.cos(a) * FOV_RANGE_M;
        g.append(s("line", { x1: c.map_x, y1: c.map_y, x2: hx, y2: hy, stroke: "var(--amber)", "stroke-width": 1.5, "vector-effect": "non-scaling-stroke" }));
        g.append(s("circle", { class: "handle", cx: hx, cy: hy, r: 5 * px, "data-rotate": c.id }));
      }
    }

    // a person's route: arrows from place to place, numbered stops, small pictures
    if (this.route.length) this._renderRoute(g, px);
    // trail of a person's movement
    else if (this.trail.length > 1) {
      g.append(s("polyline", { class: "trail", points: this.trail.map((p) => `${p.x},${p.y}`).join(" ") }));
    }
    // pins (last-seen markers)
    for (const p of this.pins) {
      if (p.x == null) continue;
      if (p.pulse) g.append(s("circle", { class: "pin-ring", cx: p.x, cy: p.y, r: 9 * px }));
      g.append(s("circle", { class: "pin", cx: p.x, cy: p.y, r: (p.small ? 4 : 7) * px }));
      if (p.label) {
        const t = s("text", { class: "bld-label", x: p.x, y: p.y - 12 * px, "text-anchor": "middle" });
        t.style.fontSize = `${12 * px}px`;
        t.style.strokeWidth = `${3 * px}px`;
        t.textContent = p.label;
        g.append(t);
      }
    }

    // shape being drawn
    if (this.draft && this.draft.length) {
      const pts = this.draft.concat(this._hover ? [this._hover] : []);
      g.append(s("polygon", { class: "draft", points: pts.map((p) => p.join(",")).join(" ") }));
      this.draft.forEach((p) => g.append(s("circle", { class: "handle", cx: p[0], cy: p[1], r: 4 * px })));
    }

    // scale bar
    const bar = niceLength(this.view.w * 0.18);
    const sx = this.view.x + this.view.w - bar - 16 * px, sy = this.view.y + this.view.h - 16 * px;
    const sg = s("g", { class: "scale" });
    sg.append(s("line", { x1: sx, y1: sy, x2: sx + bar, y2: sy }));
    sg.append(s("line", { x1: sx, y1: sy - 4 * px, x2: sx, y2: sy + 4 * px }));
    sg.append(s("line", { x1: sx + bar, y1: sy - 4 * px, x2: sx + bar, y2: sy + 4 * px }));
    const st = s("text", { x: sx + bar / 2, y: sy - 6 * px, "text-anchor": "middle" });
    st.style.fontSize = `${11 * px}px`;
    st.textContent = `${bar} m`;
    sg.append(st);
    g.append(sg);
  }

  _renderRoute(g, px) {
    const stops = this.route;
    // stops at the same camera are fanned out so each number can be read
    const seen = new Map();
    const pos = stops.map((st) => {
      const k = `${st.x.toFixed(1)},${st.y.toFixed(1)}`;
      const n = seen.get(k) || 0; seen.set(k, n + 1);
      if (!n) return [st.x, st.y];
      const a = n * 2.1, r = (12 + 4 * Math.floor(n / 3)) * px;
      return [st.x + Math.cos(a) * r, st.y + Math.sin(a) * r];
    });
    const lines = s("g", { class: "route" });
    for (let i = 1; i < pos.length; i++) {
      const [ax, ay] = pos[i - 1], [bx, by] = pos[i];
      const len = Math.hypot(bx - ax, by - ay);
      if (len < 2 * px) continue;
      const late = i === pos.length - 1;
      lines.append(s("line", { class: `route-under`, x1: ax, y1: ay, x2: bx, y2: by }));
      // older parts of the route are fainter, so the order in time can be seen on the map
      lines.append(s("line", { class: `route-line${late ? " last" : ""}`, x1: ax, y1: ay, x2: bx, y2: by,
        opacity: (0.3 + 0.7 * (i / (pos.length - 1))).toFixed(2) }));
      // arrow head half way: shows which way the person went
      const ux = (bx - ax) / len, uy = (by - ay) / len, mx = ax + (bx - ax) * 0.55, my = ay + (by - ay) * 0.55;
      const L = 9 * px, W = 5.5 * px;
      lines.append(s("polygon", { class: "route-arrow", points: [
        [mx + ux * L / 2, my + uy * L / 2], [mx - ux * L / 2 - uy * W, my - uy * L / 2 + ux * W], [mx - ux * L / 2 + uy * W, my - uy * L / 2 - ux * W],
      ].map((p) => p.join(",")).join(" ") }));
    }
    g.append(lines);
    const showPics = stops.length <= 14;
    const marks = s("g", { class: "route-stops" });
    stops.forEach((st, i) => {
      const [x, y] = pos[i];
      const first = i === 0, last = i === stops.length - 1, sel = this.routeSel === i;
      const grp = s("g", { class: `stop${first ? " first" : ""}${last ? " last" : ""}${sel ? " sel" : ""}`, "data-stop": i, tabindex: 0 });
      grp.style.cursor = "pointer";
      const title = s("title"); title.textContent = `${st.n}. ${st.label}${st.sub ? `, ${st.sub}` : ""}${st.clip ? " (click to watch)" : ""}`;
      grp.append(title);
      if (last) grp.append(s("circle", { class: "pin-ring", cx: x, cy: y, r: 12 * px }));
      if ((showPics || sel || last) && st.thumb) {
        const w = (sel ? 64 : 36) * px, hgt = w;
        const ix = x + 8 * px, iy = y - 8 * px - hgt;
        grp.append(s("rect", { class: "stop-pic-frame", x: ix - 1.5 * px, y: iy - 1.5 * px, width: w + 3 * px, height: hgt + 3 * px, rx: 4 * px }));
        const im = s("image", { x: ix, y: iy, width: w, height: hgt, preserveAspectRatio: "xMidYMid slice" });
        im.setAttribute("href", st.thumb);
        grp.append(im);
        if (st.clip) {
          const cx = ix + w - 8 * px, cy = iy + hgt - 8 * px;
          grp.append(s("circle", { class: "stop-play-bg", cx, cy, r: 7 * px }));
          grp.append(s("polygon", { class: "stop-play", points: `${cx - 2.5 * px},${cy - 4 * px} ${cx - 2.5 * px},${cy + 4 * px} ${cx + 4 * px},${cy}` }));
        }
      }
      grp.append(s("circle", { class: "stop-dot", cx: x, cy: y, r: 9 * px }));
      const num = s("text", { class: "stop-num", x, y: y + 0.5 * px, "text-anchor": "middle", "dominant-baseline": "middle" });
      num.style.fontSize = `${10 * px}px`;
      num.textContent = st.n;
      grp.append(num);
      if (first || last || sel) {
        // the start label goes to the left so it never covers the "Now" label when someone came back
        const left = first && !last && !sel;
        const t = s("text", { class: "bld-label stop-label", x: x + (left ? -12 : 12) * px, y: y + 16 * px, "text-anchor": left ? "end" : "start" });
        t.style.fontSize = `${11.5 * px}px`;
        t.style.strokeWidth = `${3 * px}px`;
        t.textContent = `${first && !last ? "From " : last ? "Now: " : ""}${st.label}${st.sub ? `  ${st.sub}` : ""}`;
        grp.append(t);
      }
      marks.append(grp);
    });
    g.append(marks);
  }

  // ----------------------------------------------------------- interaction
  _bind() {
    const svg = this.svg;
    let drag = null;

    svg.addEventListener("wheel", (e) => {
      e.preventDefault();
      const [wx, wy] = this.toWorld(e);
      const k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
      const v = this.view;
      const nw = Math.min(Math.max(v.w * k, 5), Math.max(this.data.width_m, this.data.height_m) * 4);
      const ratio = nw / v.w;
      this.view = { x: wx - (wx - v.x) * ratio, y: wy - (wy - v.y) * ratio, w: nw, h: v.h * ratio };
      this._applyView();
    }, { passive: false });

    svg.addEventListener("contextmenu", (e) => e.preventDefault());
    svg.addEventListener("pointerdown", (e) => {
      const t = e.target;
      const [wx, wy] = this.toWorld(e);
      // moving the map: middle button always; the right button when the mouse buttons are swapped
      if (e.button === 1 || (e.button === 2 && mouseSwapped())) {
        e.preventDefault();
        drag = { type: "pan", sx: e.clientX, sy: e.clientY, view: { ...this.view } };
        svg.setPointerCapture(e.pointerId);
        return;
      }
      if (e.button !== 0) return;
      const stop = t.closest?.("[data-stop]");
      if (stop && !this.editable) {
        const i = +stop.dataset.stop;
        this.selectStop(i);
        this.opts.onStop?.(this.route[i], i);
        return;
      }
      if (this.editable && this.mode === "polygon") {
        if (this.draft && this.draft.length >= 3 && near(this.draft[0], [wx, wy], 8 * this.px)) return this._finishDraft();
        (this.draft ||= []).push([round1(wx), round1(wy)]);
        return this.render();
      }
      if (this.editable && this.mode === "rect") {
        drag = { type: "rect", start: [wx, wy] };
        this.draft = [[wx, wy], [wx, wy], [wx, wy], [wx, wy]];
        svg.setPointerCapture(e.pointerId);
        return;
      }
      if (this.editable && this.mode === "camera") {
        this.opts.onPlaceCamera?.(round1(wx), round1(wy));
        return;
      }
      if (this.editable && t.dataset.vertex !== undefined) {
        drag = { type: "vertex", bid: +t.dataset.bid, i: +t.dataset.vertex };
      } else if (this.editable && t.dataset.rotate) {
        drag = { type: "rotate", cid: +t.dataset.rotate };
      } else if (t.dataset.cid) {
        const id = +t.dataset.cid;
        this.select({ kind: "camera", id });
        this.opts.onSelect?.({ kind: "camera", id });
        if (this.editable) drag = { type: "camera", cid: id };
      } else if (t.dataset.bid) {
        const id = +t.dataset.bid;
        this.select({ kind: "building", id });
        this.opts.onSelect?.({ kind: "building", id });
        if (this.editable) drag = { type: "building", bid: id, last: [wx, wy] };
      } else {
        // left drag on empty ground moves the map (unless the buttons are swapped: then the right button does)
        if (!mouseSwapped()) drag = { type: "pan", sx: e.clientX, sy: e.clientY, view: { ...this.view } };
        if (this.selected) { this.select(null); this.opts.onSelect?.(null); }
        if (!drag) return;
      }
      svg.setPointerCapture(e.pointerId);
    });

    svg.addEventListener("pointermove", (e) => {
      if (this.opts.onHover) this.opts.onHover(this.toWorld(e));
      if (this.mode === "polygon" && this.draft) { this._hover = this.toWorld(e); this.render(); }
      if (!drag) return;
      const [wx, wy] = this.toWorld(e);
      if (drag.type === "pan") {
        const dx = (e.clientX - drag.sx) * this.px, dy = (e.clientY - drag.sy) * this.px;
        this.view = { ...drag.view, x: drag.view.x - dx, y: drag.view.y - dy };
        this.svg.setAttribute("viewBox", `${this.view.x} ${this.view.y} ${this.view.w} ${this.view.h}`);
        return;
      }
      drag.moved = true;
      if (drag.type === "rect") {
        const [x0, y0] = drag.start;
        this.draft = [[x0, y0], [wx, y0], [wx, wy], [x0, wy]].map((p) => p.map(round1));
      } else if (drag.type === "vertex") {
        const b = this.data.buildings.find((x) => x.id === drag.bid);
        b.polygon[drag.i] = [round1(wx), round1(wy)];
      } else if (drag.type === "building") {
        const b = this.data.buildings.find((x) => x.id === drag.bid);
        const dx = wx - drag.last[0], dy = wy - drag.last[1];
        b.polygon = b.polygon.map(([x, y]) => [round1(x + dx), round1(y + dy)]);
        drag.last = [wx, wy];
      } else if (drag.type === "camera") {
        const c = this.data.cameras.find((x) => x.id === drag.cid);
        c.map_x = round1(wx); c.map_y = round1(wy);
      } else if (drag.type === "rotate") {
        const c = this.data.cameras.find((x) => x.id === drag.cid);
        c.direction = Math.round(((Math.atan2(wx - c.map_x, -(wy - c.map_y)) * 180) / Math.PI + 360) % 360);
      }
      this.render();
    });

    const end = () => {
      if (!drag) return;
      const dr = drag;
      drag = null;
      if (dr.type === "rect") {
        const [a, , c] = this.draft || [];
        if (a && c && Math.abs(a[0] - c[0]) > 1 && Math.abs(a[1] - c[1]) > 1) this._finishDraft();
        else { this.draft = null; this.render(); }
      } else if (dr.moved && (dr.type === "vertex" || dr.type === "building")) {
        this.opts.onBuildingChanged?.(this.data.buildings.find((x) => x.id === dr.bid));
      } else if (dr.moved && (dr.type === "camera" || dr.type === "rotate")) {
        this.opts.onCameraChanged?.(this.data.cameras.find((x) => x.id === dr.cid));
      }
    };
    svg.addEventListener("pointerup", end);
    svg.addEventListener("pointercancel", end);
    svg.addEventListener("pointerleave", () => this.opts.onHover?.(null));
    svg.addEventListener("keydown", (e) => {
      const stop = e.target.closest?.("[data-stop]");
      if (stop && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); const i = +stop.dataset.stop; this.selectStop(i); this.opts.onStop?.(this.route[i], i); }
    });
    svg.addEventListener("dblclick", (e) => { if (this.mode === "polygon" && this.draft?.length >= 3) { e.preventDefault(); this._finishDraft(); } });
    window.addEventListener("keydown", (this._key = (e) => {
      if (e.key === "Escape" && this.draft) { this.draft = null; this.render(); }
      if (e.key === "Enter" && this.mode === "polygon" && this.draft?.length >= 3) this._finishDraft();
    }));
  }

  _finishDraft() {
    const pts = this.draft;
    this.draft = null;
    this._hover = null;
    this.render();
    this.opts.onShapeDrawn?.(pts);
  }
}

// ------------------------------------------------------------- geometry
export function centroid(poly) {
  let x = 0, y = 0;
  for (const p of poly) { x += p[0]; y += p[1]; }
  return [x / poly.length, y / poly.length];
}

function wedge(x, y, dir, fov, r) {
  const a0 = ((dir - fov / 2) * Math.PI) / 180, a1 = ((dir + fov / 2) * Math.PI) / 180;
  const p0 = [x + Math.sin(a0) * r, y - Math.cos(a0) * r];
  const p1 = [x + Math.sin(a1) * r, y - Math.cos(a1) * r];
  const large = fov > 180 ? 1 : 0;
  return `M${x},${y} L${p0[0]},${p0[1]} A${r},${r} 0 ${large} 1 ${p1[0]},${p1[1]} Z`;
}

function niceLength(m) {
  const steps = [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000, 2000];
  return steps.reduce((best, s) => (s <= m ? s : best), 1);
}

const round1 = (v) => Math.round(v * 10) / 10;
const near = (a, b, d) => Math.hypot(a[0] - b[0], a[1] - b[1]) <= d;

// Turn a person's sightings (newest first) into map points, oldest first.
export function trailFromSightings(rows) {
  return rows
    .filter((r) => r.map_x != null && r.map_y != null)
    .slice()
    .reverse()
    .map((r) => ({ x: r.map_x, y: r.map_y, t: r.last_seen }));
}
