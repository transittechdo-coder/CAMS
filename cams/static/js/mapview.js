// A map panel with a 2D / 3D switch. Both views share the same data, pins and trail.
import { h, get } from "./util.js";
import { SiteMap } from "./map2d.js";

export class MapView {
  constructor(container, { height = "tall", editable = false, mapOpts = {}, allow3d = true } = {}) {
    this.wrap = h("div", { class: `map-wrap ${height}` });
    container.append(this.wrap);
    this.mode = localStorage.getItem("cams-map-mode") === "3d" && allow3d ? "3d" : "2d";
    this.map2d = new SiteMap(this.wrap, { editable, ...mapOpts });
    this.marks = { pins: [], trail: [] };
    this.allow3d = allow3d;
    if (allow3d) {
      this.seg = h("div", { class: "seg", role: "group", "aria-label": "Map view" },
        h("button", { "aria-pressed": String(this.mode === "2d"), onclick: () => this.setMode("2d") }, "Plan"),
        h("button", { "aria-pressed": String(this.mode === "3d"), onclick: () => this.setMode("3d") }, "3D"),
      );
      this.wrap.append(h("div", { class: "map-tools right" }, this.seg,
        h("button", { class: "small", onclick: () => this.fit(), title: "Show the whole site" }, "Fit")));
    }
  }

  async load() {
    this.data = await get("/api/map");
    this.map2d.setData(this.data);
    if (this.view3d) this.view3d.setData(this.data);
    if (this.mode === "3d") await this.setMode("3d");
    return this.data;
  }

  async setMode(mode) {
    this.mode = mode;
    try { localStorage.setItem("cams-map-mode", mode); } catch {}
    this.seg?.querySelectorAll("button").forEach((b, i) => b.setAttribute("aria-pressed", String((i === 0) === (mode === "2d"))));
    if (mode === "3d") {
      this.map2d.svg.classList.add("hidden");
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
      this.view3d.setMarks(this.marks);
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
    if (this.view3d && this.mode === "3d") this.view3d.setMarks(this.marks);
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
