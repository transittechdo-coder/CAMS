// A map panel with a 2D / 3D switch. Both views share the same data, pins and trail.
// When the campus is placed on Earth (Campus builder > Real satellite map), the panel
// shows the GPS position under the mouse and the satellite picture's credit.
import { h, get, toLatLng, fmtLatLng, copyText } from "./util.js";
import { SiteMap } from "./map2d.js";

export class MapView {
  constructor(container, { height = "tall", editable = false, mapOpts = {}, allow3d = true } = {}) {
    this.wrap = h("div", { class: `map-wrap ${height}` });
    container.append(this.wrap);
    this.mode = localStorage.getItem("cams-map-mode") === "3d" && allow3d ? "3d" : "2d";
    this.coords = h("button", { class: "map-coords hidden", title: "GPS position under the mouse. Click to copy it.",
      onclick: () => this._hoverLL && copyText(fmtLatLng(this._hoverLL), "Position copied") });
    this.credit = h("div", { class: "map-credit hidden" });
    this.map2d = new SiteMap(this.wrap, {
      editable, ...mapOpts,
      onHover: (p) => { this._hover(p); mapOpts.onHover?.(p); },
    });
    this.marks = { pins: [], trail: [] };
    this.route = [];
    this.allow3d = allow3d;
    this.wrap.append(this.coords, this.credit);
    if (allow3d) {
      this.seg = h("div", { class: "seg", role: "group", "aria-label": "Map view" },
        h("button", { "aria-pressed": String(this.mode === "2d"), onclick: () => this.setMode("2d") }, "Plan"),
        h("button", { "aria-pressed": String(this.mode === "3d"), onclick: () => this.setMode("3d") }, "3D"),
      );
      this.wrap.append(h("div", { class: "map-tools right" }, this.seg,
        h("button", { class: "small", onclick: () => this.fit(), title: "Show the whole site" }, "Fit")));
    }
  }

  _hover(p) {
    const ll = p && this.data?.geo && this.mode === "2d" ? toLatLng(this.data, p[0], p[1]) : null;
    this._hoverLL = ll || this._hoverLL;
    if (ll) { this.coords.textContent = fmtLatLng(ll); this.coords.classList.remove("hidden"); }
    else if (!p) this.coords.classList.add("hidden");
  }

  async load() {
    this.data = await get("/api/map");
    this.map2d.setData(this.data);
    if (this.view3d) this.view3d.setData(this.data);
    if (this.mode === "3d") await this.setMode("3d");
    this.credit.textContent = this.data.attribution || "";
    this.credit.classList.toggle("hidden", !this.data.attribution);
    return this.data;
  }

  latLng(x, y) { return toLatLng(this.data, x, y); }

  async setMode(mode) {
    this.mode = mode;
    try { localStorage.setItem("cams-map-mode", mode); } catch {}
    this.seg?.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String((i === 0) === (mode === "2d"))));
    if (mode === "3d") {
      this.map2d.svg.classList.add("hidden");
      this.coords.classList.add("hidden");
      if (!this.view3d) {
        this.box3d = h("div", { class: "map-3d" });
        this.wrap.append(this.box3d);
        try {
          const { Campus3D } = await import("./map3d.js");
          this.view3d = new Campus3D(this.box3d);
        } catch (e) {
          this.box3d.append(h("div", { class: "empty" }, "3D view needs graphics support (WebGL) that this PC does not provide. The plan view still works."));
          return;
        }
      }
      this.box3d.classList.remove("hidden");
      if (this.data) this.view3d.setData(this.data);
      this.view3d.setMarks(this._marks3d());
    } else {
      this.map2d.svg.classList.remove("hidden");
      this.box3d?.classList.add("hidden");
      this.map2d._applyView();
    }
  }

  setMarks({ pins = [], trail = [] }) {
    this.marks = { pins, trail };
    this.map2d.setPins(pins);
    this.map2d.setTrail(trail);
    if (this.view3d && this.mode === "3d") this.view3d.setMarks(this._marks3d());
  }

  // A person's route: stops oldest first ({x, y, n, label, sub, thumb, clip}).
  setRoute(stops) {
    this.route = stops || [];
    this.map2d.setRoute(this.route);
    if (this.view3d && this.mode === "3d") this.view3d.setMarks(this._marks3d());
  }

  selectStop(i) { this.map2d.selectStop(i); }

  _marks3d() {
    if (!this.route.length) return this.marks;
    const last = this.route[this.route.length - 1];
    return {
      pins: [...this.marks.pins.filter((p) => !p.pulse), { x: last.x, y: last.y, label: last.label, pulse: true },
        ...this.route.slice(0, -1).map((s) => ({ x: s.x, y: s.y, small: true, label: String(s.n) }))],
      trail: this.route.map((s) => ({ x: s.x, y: s.y }))
        .filter((p, i, a) => !i || Math.hypot(p.x - a[i - 1].x, p.y - a[i - 1].y) > 0.5),
    };
  }

  fit() {
    this.map2d.fit();
    if (this.view3d) { this.view3d._framed = false; this.view3d.setData(this.data); }
  }

  destroy() {
    this.map2d.destroy();
    this.view3d?.destroy();
  }
}
