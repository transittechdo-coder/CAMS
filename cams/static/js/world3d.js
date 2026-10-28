// CAMS world objects: every shape the Map Studio can draw, built as three.js groups.
// Units are metres. x = east, z = south (same as map_x / map_y), y = up.
// Every object stands on its own base: obj.pos is the centre of its bottom face.
import * as THREE from "three";

// ------------------------------------------------------------------ materials
// Textures are drawn in grey on a canvas so one texture can be tinted any colour.
const TEX = {};
function canvasTex(key, size, draw) {
  if (TEX[key]) return TEX[key];
  const c = document.createElement("canvas");
  c.width = c.height = size;
  const g = c.getContext("2d");
  draw(g, size);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  return (TEX[key] = t);
}
function noise(g, s, amt, n = 2600) {
  for (let i = 0; i < n; i++) {
    const v = 255 - Math.random() * amt;
    g.fillStyle = `rgb(${v},${v},${v})`;
    g.fillRect(Math.random() * s, Math.random() * s, 2, 2);
  }
}
// tile = how many metres one copy of the texture covers
export const MATERIALS = {
  plain:    { label: "Plain",        tile: 4,   tex: null },
  concrete: { label: "Concrete",     tile: 3,   tex: () => canvasTex("concrete", 256, (g, s) => { g.fillStyle = "#f2f2f2"; g.fillRect(0, 0, s, s); noise(g, s, 40, 5000); }) },
  brick:    { label: "Brick",        tile: 1.2, tex: () => canvasTex("brick", 256, (g, s) => {
    g.fillStyle = "#d8d8d8"; g.fillRect(0, 0, s, s);
    const rows = 8, h = s / rows, w = s / 4;
    for (let r = 0; r < rows; r++) for (let c = -1; c < 5; c++) {
      const x = c * w + (r % 2 ? w / 2 : 0);
      const v = 225 + Math.random() * 30; g.fillStyle = `rgb(${v},${v},${v})`;
      g.fillRect(x + 3, r * h + 3, w - 6, h - 6);
    }
    noise(g, s, 30);
  }) },
  blocks:   { label: "Blocks",       tile: 2,   tex: () => canvasTex("blocks", 256, (g, s) => {
    g.fillStyle = "#c9c9c9"; g.fillRect(0, 0, s, s);
    for (let r = 0; r < 4; r++) for (let c = -1; c < 3; c++) { g.fillStyle = "#f4f4f4"; g.fillRect(c * 128 + (r % 2 ? 64 : 0) + 3, r * 64 + 3, 122, 58); }
    noise(g, s, 25);
  }) },
  wood:     { label: "Wood",         tile: 1.5, tex: () => canvasTex("wood", 256, (g, s) => {
    g.fillStyle = "#eeeeee"; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 70; i++) { const v = 200 + Math.random() * 40; g.strokeStyle = `rgb(${v},${v},${v})`; g.lineWidth = 1 + Math.random() * 2; const y = Math.random() * s; g.beginPath(); g.moveTo(0, y); g.bezierCurveTo(s / 3, y + 6, s * 2 / 3, y - 6, s, y); g.stroke(); }
    for (let x = 0; x < s; x += 64) { g.fillStyle = "#b8b8b8"; g.fillRect(x, 0, 2, s); }
  }) },
  metal:    { label: "Metal sheet",  tile: 1,   tex: () => canvasTex("metal", 128, (g, s) => {
    for (let x = 0; x < s; x++) { const v = 215 + 35 * Math.sin((x / s) * Math.PI * 8); g.fillStyle = `rgb(${v},${v},${v})`; g.fillRect(x, 0, 1, s); }
  }) },
  tiles:    { label: "Roof tiles",   tile: 1,   tex: () => canvasTex("tiles", 256, (g, s) => {
    g.fillStyle = "#cfcfcf"; g.fillRect(0, 0, s, s);
    for (let r = 0; r < 8; r++) for (let c = -1; c < 9; c++) {
      const x = c * 32 + (r % 2 ? 16 : 0), y = r * 32;
      const grd = g.createLinearGradient(0, y, 0, y + 32); grd.addColorStop(0, "#ffffff"); grd.addColorStop(1, "#c4c4c4");
      g.fillStyle = grd; g.beginPath(); g.moveTo(x, y); g.lineTo(x + 30, y); g.quadraticCurveTo(x + 30, y + 32, x + 15, y + 32); g.quadraticCurveTo(x, y + 32, x, y); g.fill();
    }
  }) },
  glass:    { label: "Glass",        tile: 2,   tex: null, glass: true },
  facade:   { label: "Windows",      tile: 3.2, tex: () => canvasTex("facade", 256, (g, s) => {
    g.fillStyle = "#f0f0f0"; g.fillRect(0, 0, s, s);
    g.fillStyle = "#5d6f80"; g.fillRect(s * 0.18, s * 0.25, s * 0.64, s * 0.45);
    g.fillStyle = "#8aa0b4"; g.fillRect(s * 0.18, s * 0.25, s * 0.64, s * 0.08);
    g.strokeStyle = "#ffffff"; g.lineWidth = 6; g.strokeRect(s * 0.18, s * 0.25, s * 0.64, s * 0.45); g.beginPath(); g.moveTo(s / 2, s * 0.25); g.lineTo(s / 2, s * 0.7); g.stroke();
  }) },
  grass:    { label: "Grass",        tile: 3,   tex: () => canvasTex("grass", 256, (g, s) => {
    g.fillStyle = "#e6e6e6"; g.fillRect(0, 0, s, s);
    for (let i = 0; i < 6000; i++) { const v = 170 + Math.random() * 85; g.strokeStyle = `rgb(${v},${v},${v})`; const x = Math.random() * s, y = Math.random() * s; g.beginPath(); g.moveTo(x, y); g.lineTo(x + Math.random() * 3 - 1.5, y - 4); g.stroke(); }
  }) },
  asphalt:  { label: "Tarmac",       tile: 3,   tex: () => canvasTex("asphalt", 256, (g, s) => { g.fillStyle = "#e0e0e0"; g.fillRect(0, 0, s, s); noise(g, s, 90, 9000); }) },
  paving:   { label: "Paving",       tile: 1.2, tex: () => canvasTex("paving", 256, (g, s) => {
    g.fillStyle = "#bdbdbd"; g.fillRect(0, 0, s, s);
    for (let r = 0; r < 4; r++) for (let c = 0; c < 4; c++) { const v = 230 + Math.random() * 25; g.fillStyle = `rgb(${v},${v},${v})`; g.fillRect(c * 64 + 2, r * 64 + 2, 60, 60); }
    noise(g, s, 30);
  }) },
  sand:     { label: "Sand / soil",  tile: 3,   tex: () => canvasTex("sand", 256, (g, s) => { g.fillStyle = "#efefef"; g.fillRect(0, 0, s, s); noise(g, s, 70, 12000); }) },
  water:    { label: "Water",        tile: 6,   tex: () => canvasTex("water", 256, (g, s) => {
    g.fillStyle = "#e8e8e8"; g.fillRect(0, 0, s, s);
    g.strokeStyle = "#ffffff"; g.lineWidth = 2;
    for (let i = 0; i < 40; i++) { const x = Math.random() * s, y = Math.random() * s; g.beginPath(); g.moveTo(x, y); g.quadraticCurveTo(x + 10, y - 4, x + 20, y); g.stroke(); }
  }), water: true },
  tilesFloor: { label: "Floor tiles", tile: 1.2, tex: () => canvasTex("floortiles", 128, (g, s) => {
    g.fillStyle = "#cccccc"; g.fillRect(0, 0, s, s); g.fillStyle = "#f7f7f7"; g.fillRect(2, 2, s / 2 - 4, s / 2 - 4); g.fillRect(s / 2 + 2, s / 2 + 2, s / 2 - 4, s / 2 - 4);
    g.fillStyle = "#ececec"; g.fillRect(s / 2 + 2, 2, s / 2 - 4, s / 2 - 4); g.fillRect(2, s / 2 + 2, s / 2 - 4, s / 2 - 4);
  }) },
};

const MAT_CACHE = new Map();
export function material(name = "plain", color = "#cccccc", opacity = 1) {
  const key = `${name}|${color}|${opacity}`;
  if (MAT_CACHE.has(key)) return MAT_CACHE.get(key);
  const def = MATERIALS[name] || MATERIALS.plain;
  const op = def.glass ? Math.min(opacity, 0.35) : def.water ? Math.min(opacity, 0.8) : opacity;
  const m = new THREE.MeshStandardMaterial({
    color: new THREE.Color(color), map: def.tex ? def.tex() : null,
    roughness: def.glass || def.water ? 0.1 : def === MATERIALS.metal ? 0.45 : 0.9,
    metalness: def === MATERIALS.metal ? 0.35 : 0,
    transparent: op < 1, opacity: op, side: op < 1 ? THREE.DoubleSide : THREE.FrontSide,
    depthWrite: op >= 0.6,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
  });
  m.userData.tile = def.tile;
  MAT_CACHE.set(key, m);
  return m;
}

// World-space box-projected UVs, so textures keep their real size on any shape.
function boxUV(geo, tile = 2, tileV = tile) {
  geo = geo.index ? geo.toNonIndexed() : geo;
  if (!geo.attributes.normal) geo.computeVertexNormals();
  const p = geo.attributes.position, n = geo.attributes.normal;
  const uv = new Float32Array(p.count * 2);
  for (let i = 0; i < p.count; i++) {
    const ax = Math.abs(n.getX(i)), ay = Math.abs(n.getY(i)), az = Math.abs(n.getZ(i));
    let u, v;
    if (ay >= ax && ay >= az) { u = p.getX(i) / tile; v = p.getZ(i) / tile; }
    else if (ax >= az) { u = p.getZ(i) / tile; v = p.getY(i) / tileV; }
    else { u = p.getX(i) / tile; v = p.getY(i) / tileV; }
    uv[i * 2] = u; uv[i * 2 + 1] = v;
  }
  geo.setAttribute("uv", new THREE.BufferAttribute(uv, 2));
  return geo;
}

function mesh(geo, mat, tileV) {
  const tile = mat.userData.tile || 2;
  const m = new THREE.Mesh(boxUV(geo, tile, tileV || tile), mat);
  m.castShadow = true; m.receiveShadow = true;
  return m;
}
const boxGeo = (w, h, d, x = 0, y = 0, z = 0) => new THREE.BoxGeometry(Math.max(w, 0.01), Math.max(h, 0.01), Math.max(d, 0.01)).translate(x, y + h / 2, z);

// A profile drawn in the (z, y) plane, pushed out along x by `width` (centred).
// profile points are [z, y]; holes optional.
function prism(profile, width, holes = []) {
  const shape = new THREE.Shape(profile.map(([z, y]) => new THREE.Vector2(z, y)));
  for (const hpts of holes) shape.holes.push(new THREE.Path(hpts.map(([z, y]) => new THREE.Vector2(z, y))));
  const g = new THREE.ExtrudeGeometry(shape, { depth: Math.max(width, 0.01), bevelEnabled: false, curveSegments: 16 });
  // extruded along +Z; turn so the extrusion runs along X and the profile's first axis is Z
  g.rotateY(Math.PI / 2); // (x,y,z) -> (z, y, -x)
  g.translate(-width / 2, 0, 0);
  return g;
}
// The same but profile in the (x, y) plane, pushed out along z by depth (for walls with holes).
function slab(profile, depth, holes = []) {
  const shape = new THREE.Shape(profile.map(([x, y]) => new THREE.Vector2(x, y)));
  for (const hpts of holes) shape.holes.push(new THREE.Path(hpts.map(([x, y]) => new THREE.Vector2(x, y))));
  const g = new THREE.ExtrudeGeometry(shape, { depth: Math.max(depth, 0.01), bevelEnabled: false, curveSegments: 16 });
  g.translate(0, 0, -depth / 2);
  return g;
}

function hipRoofGeo(w, h, d) {
  const pts = [];
  const tri = (a, b, c) => pts.push(...a, ...b, ...c);
  const x0 = -w / 2, x1 = w / 2, z0 = -d / 2, z1 = d / 2;
  if (w >= d) {
    const r = (w - d) / 2;
    const A = [-r, h, 0], B = [r, h, 0];
    tri([x0, 0, z1], [x1, 0, z1], B); tri([x0, 0, z1], B, A);           // south slope
    tri([x1, 0, z0], [x0, 0, z0], A); tri([x1, 0, z0], A, B);           // north slope
    tri([x1, 0, z1], [x1, 0, z0], B);                                  // east hip
    tri([x0, 0, z0], [x0, 0, z1], A);                                  // west hip
  } else {
    const r = (d - w) / 2;
    const A = [0, h, -r], B = [0, h, r];
    tri([x1, 0, z1], [x1, 0, z0], A); tri([x1, 0, z1], A, B);
    tri([x0, 0, z0], [x0, 0, z1], B); tri([x0, 0, z0], B, A);
    tri([x0, 0, z1], [x1, 0, z1], B);
    tri([x1, 0, z0], [x0, 0, z0], A);
  }
  tri([x0, 0, z0], [x1, 0, z0], [x1, 0, z1]); tri([x0, 0, z0], [x1, 0, z1], [x0, 0, z1]); // underside
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pts, 3));
  return g;
}

function textSprite(text, color = "#14304a", bg = "rgba(255,255,255,0.92)") {
  const c = document.createElement("canvas");
  const g = c.getContext("2d");
  const font = "600 56px Bahnschrift, 'Segoe UI', sans-serif";
  g.font = font;
  const w = Math.ceil(g.measureText(text || " ").width) + 40;
  c.width = w; c.height = 84;
  g.font = font;
  if (bg) { g.fillStyle = bg; g.beginPath(); g.roundRect(0, 0, w, 84, 14); g.fill(); }
  g.fillStyle = color; g.textBaseline = "middle"; g.fillText(text || " ", 20, 46);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace;
  const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: t, depthTest: false, transparent: true }));
  s.userData.aspect = w / 84;
  s.renderOrder = 20;
  return s;
}

// ------------------------------------------------------------------ catalogue
// size = default [width, height, depth] in metres. line = drawn by clicking points (walls, fences, roads).
export const TYPES = {
  // shapes
  box:       { cat: "shapes", label: "Block",        size: [4, 3, 4],     mat: "plain",    color: "#9fb4c8" },
  cylinder:  { cat: "shapes", label: "Cylinder",     size: [3, 4, 3],     mat: "plain",    color: "#9fb4c8" },
  sphere:    { cat: "shapes", label: "Ball",         size: [3, 3, 3],     mat: "plain",    color: "#9fb4c8" },
  cone:      { cat: "shapes", label: "Cone",         size: [3, 4, 3],     mat: "plain",    color: "#9fb4c8" },
  pyramid:   { cat: "shapes", label: "Pyramid",      size: [4, 3, 4],     mat: "plain",    color: "#9fb4c8" },
  wedge:     { cat: "shapes", label: "Wedge / ramp", size: [3, 1.5, 5],   mat: "concrete", color: "#b8b8b0" },
  prism:     { cat: "shapes", label: "Triangle",     size: [4, 3, 4],     mat: "plain",    color: "#9fb4c8" },
  hemi:      { cat: "shapes", label: "Half ball",    size: [4, 2, 4],     mat: "plain",    color: "#9fb4c8" },
  tube:      { cat: "shapes", label: "Pipe / tank",  size: [3, 4, 3],     mat: "metal",    color: "#b9c2c8", props: { thickness: 0.2 } },
  arch:      { cat: "shapes", label: "Arch",         size: [4, 4, 1],     mat: "brick",    color: "#c27a5a" },
  // building parts
  building:  { cat: "build", label: "Building",      size: [20, 6.4, 10], mat: "facade",   color: "#e9e4da", props: { floors: 2 } },
  room:      { cat: "build", label: "Room",          size: [6, 3, 5],     mat: "blocks",   color: "#e6e1d6", props: { thickness: 0.2, door: true, floor: true } },
  wall:      { cat: "build", label: "Wall",          size: [4, 3, 0.2],   mat: "blocks",   color: "#e6e1d6", line: true, props: { door: false, windows: 0 } },
  floor:     { cat: "build", label: "Floor / slab",  size: [6, 0.2, 6],   mat: "tilesFloor", color: "#d8d2c6" },
  column:    { cat: "build", label: "Column",        size: [0.4, 3, 0.4], mat: "concrete", color: "#d9d4ca" },
  beam:      { cat: "build", label: "Beam",          size: [6, 0.4, 0.3], mat: "concrete", color: "#d9d4ca" },
  door:      { cat: "build", label: "Door",          size: [1, 2.1, 0.12], mat: "wood",    color: "#8a5a36" },
  window:    { cat: "build", label: "Window",        size: [1.5, 1.2, 0.1], mat: "glass",  color: "#9ccbe8", lift: 1 },
  stairs:    { cat: "build", label: "Stairs",        size: [1.4, 3.2, 5], mat: "concrete", color: "#cfc8bb", props: { rails: true } },
  ladder:    { cat: "build", label: "Ladder",        size: [0.6, 3.2, 0.1], mat: "metal",  color: "#9aa3aa" },
  railing:   { cat: "build", label: "Railing",       size: [4, 1, 0.06],  mat: "metal",    color: "#5b6670", line: true },
  // roofs
  roofGable: { cat: "roof", label: "Gable roof",     size: [10, 2.5, 8],  mat: "tiles",    color: "#b5533c" },
  roofHip:   { cat: "roof", label: "Hip roof",       size: [10, 2.5, 8],  mat: "tiles",    color: "#b5533c" },
  roofShed:  { cat: "roof", label: "Slope (shed)",   size: [10, 1.5, 8],  mat: "metal",    color: "#8e9ba5" },
  roofFlat:  { cat: "roof", label: "Flat roof",      size: [10, 0.3, 8],  mat: "concrete", color: "#bdb7ad", props: { parapet: 0.6 } },
  roofPyramid:{ cat: "roof", label: "Pyramid roof",  size: [8, 3, 8],    mat: "tiles",    color: "#8f3f30" },
  roofDome:  { cat: "roof", label: "Dome",           size: [8, 4, 8],     mat: "metal",    color: "#c9b067" },
  roofMetal: { cat: "roof", label: "Iron sheet roof",size: [10, 1.8, 8],  mat: "metal",    color: "#a7b0b5" },
  // outdoor
  road:      { cat: "outdoor", label: "Road",        size: [10, 0.05, 6], mat: "asphalt",  color: "#55595e", line: true, props: { lines: true } },
  path:      { cat: "outdoor", label: "Footpath",    size: [10, 0.04, 2], mat: "paving",   color: "#c9bfae", line: true },
  fence:     { cat: "outdoor", label: "Fence",       size: [6, 2, 0.08],  mat: "metal",    color: "#6f7b84", line: true },
  hedge:     { cat: "outdoor", label: "Hedge",       size: [6, 1.2, 0.8], mat: "grass",    color: "#3f7d3a", line: true },
  lawn:      { cat: "outdoor", label: "Grass area",  size: [12, 0.03, 12], mat: "grass",   color: "#6aa84f" },
  water:     { cat: "outdoor", label: "Water",       size: [10, 0.05, 8], mat: "water",    color: "#3d8fd1" },
  parking:   { cat: "outdoor", label: "Parking bays",size: [15, 0.04, 5], mat: "asphalt",  color: "#5b5f64", props: { bays: 6 } },
  tree:      { cat: "outdoor", label: "Tree",        size: [4, 6, 4],     mat: "plain",    color: "#3f8a3a", props: { style: "round" } },
  pine:      { cat: "outdoor", label: "Pine tree",   size: [3, 7, 3],     mat: "plain",    color: "#2f6b3a" },
  palm:      { cat: "outdoor", label: "Palm tree",   size: [4, 8, 4],     mat: "plain",    color: "#4f9a3c" },
  bush:      { cat: "outdoor", label: "Bush",        size: [1.6, 1.1, 1.6], mat: "grass",  color: "#4c8c3f" },
  rock:      { cat: "outdoor", label: "Rock",        size: [1.5, 1, 1.2], mat: "concrete", color: "#8d8a84" },
  gate:      { cat: "outdoor", label: "Gate",        size: [5, 2.2, 0.15], mat: "metal",   color: "#3c4a55", props: { pillars: true } },
  // objects
  car:       { cat: "things", label: "Car",          size: [1.8, 1.5, 4.3], mat: "plain",  color: "#c23a2b" },
  bus:       { cat: "things", label: "Bus",          size: [2.5, 3, 11],   mat: "plain",   color: "#e3a21a" },
  bench:     { cat: "things", label: "Bench",        size: [1.8, 0.9, 0.6], mat: "wood",   color: "#8a5a36" },
  table:     { cat: "things", label: "Table",        size: [1.6, 0.75, 0.8], mat: "wood",  color: "#9a6a42" },
  desk:      { cat: "things", label: "Class desks",  size: [6, 0.75, 5],   mat: "wood",    color: "#9a6a42", props: { rows: 4, cols: 3 } },
  lamp:      { cat: "things", label: "Street light", size: [0.6, 6, 0.6],  mat: "metal",   color: "#59636b" },
  flag:      { cat: "things", label: "Flag pole",    size: [1.6, 8, 0.1],  mat: "metal",   color: "#2f8a4c" },
  tank:      { cat: "things", label: "Water tank",   size: [2.4, 5, 2.4],  mat: "plain",   color: "#2d2f33", props: { stand: true } },
  goal:      { cat: "things", label: "Football goal",size: [7.3, 2.4, 2],  mat: "plain",   color: "#f4f4f4" },
  sign:      { cat: "things", label: "Sign board",   size: [2, 2.2, 0.1],  mat: "plain",   color: "#0b7a75", props: { text: "Sign" } },
  label:     { cat: "things", label: "Text label",   size: [6, 1.4, 0.1],  mat: "plain",   color: "#14304a", props: { text: "Label" } },
  person:    { cat: "things", label: "Person (scale)", size: [0.5, 1.7, 0.3], mat: "plain", color: "#5b8def" },
};

export const CATS = [
  ["shapes", "Shapes"], ["build", "Building"], ["roof", "Roofs"], ["outdoor", "Outdoor"], ["things", "Objects"],
];

// ------------------------------------------------------------------ builders
const darker = (c, f = 0.7) => "#" + new THREE.Color(c).multiplyScalar(f).getHexString();

function wallGeo(w, h, t, { door = false, windows = 0 } = {}) {
  const holes = [];
  const dw = Math.min(1.0, w * 0.4), dh = Math.min(2.1, h * 0.85);
  if (door) holes.push([[-dw / 2, 0.001], [dw / 2, 0.001], [dw / 2, dh], [-dw / 2, dh]].map(([x, y]) => [x, y]));
  const n = Math.max(0, Math.min(20, windows | 0));
  if (n && h > 1.6) {
    const ww = Math.min(1.4, (w / n) * 0.55), y0 = Math.min(1.0, h * 0.35), y1 = Math.min(h - 0.3, y0 + 1.2);
    for (let i = 0; i < n; i++) {
      const cx = -w / 2 + (w / n) * (i + 0.5);
      if (door && Math.abs(cx) < dw / 2 + ww / 2 + 0.1) continue;
      holes.push([[cx - ww / 2, y0], [cx + ww / 2, y0], [cx + ww / 2, y1], [cx - ww / 2, y1]]);
    }
  }
  if (door) {
    // a door touching the bottom edge cannot be a hole, so draw the outline around it
    const pts = [[-w / 2, 0], [-dw / 2, 0], [-dw / 2, dh], [dw / 2, dh], [dw / 2, 0], [w / 2, 0], [w / 2, h], [-w / 2, h]];
    return slab(pts, t, holes.slice(1));
  }
  return slab([[-w / 2, 0], [w / 2, 0], [w / 2, h], [-w / 2, h]], t, holes);
}

const B = {
  box: (o, m) => [mesh(boxGeo(...o.size), m)],
  cylinder: (o, m) => { const [w, h, d] = o.size; return [mesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 40).scale(w, h, d).translate(0, h / 2, 0), m)]; },
  cone: (o, m) => { const [w, h, d] = o.size; return [mesh(new THREE.CylinderGeometry(0, 0.5, 1, 40).scale(w, h, d).translate(0, h / 2, 0), m)]; },
  sphere: (o, m) => { const [w, h, d] = o.size; return [mesh(new THREE.SphereGeometry(0.5, 32, 20).scale(w, h, d).translate(0, h / 2, 0), m)]; },
  hemi: (o, m) => { const [w, h, d] = o.size; return [mesh(new THREE.SphereGeometry(0.5, 32, 12, 0, Math.PI * 2, 0, Math.PI / 2).scale(w, h * 2, d), m)]; },
  pyramid: (o, m) => { const [w, h, d] = o.size; return [mesh(new THREE.ConeGeometry(Math.SQRT1_2, 1, 4).rotateY(Math.PI / 4).scale(w, h, d).translate(0, h / 2, 0), m)]; },
  wedge: (o, m) => { const [w, h, d] = o.size; return [mesh(prism([[d / 2, 0], [-d / 2, 0], [-d / 2, h]], w), m)]; },
  prism: (o, m) => { const [w, h, d] = o.size; return [mesh(prism([[d / 2, 0], [-d / 2, 0], [0, h]], w), m)]; },
  tube: (o, m) => {
    const [w, h, d] = o.size, t = Math.min(o.props?.thickness ?? 0.2, w / 2 - 0.01);
    const s = new THREE.Shape(); s.absarc(0, 0, w / 2, 0, Math.PI * 2);
    const hole = new THREE.Path(); hole.absarc(0, 0, w / 2 - t, 0, Math.PI * 2, true); s.holes.push(hole);
    return [mesh(new THREE.ExtrudeGeometry(s, { depth: h, bevelEnabled: false, curveSegments: 40 }).rotateX(-Math.PI / 2).scale(1, 1, d / w), m)];
  },
  arch: (o, m) => {
    const [w, h, d] = o.size, r = Math.min(w * 0.35, h * 0.6);
    const hole = [[-r, 0.001]];
    for (let i = 0; i <= 16; i++) { const a = Math.PI - (i / 16) * Math.PI; hole.push([Math.cos(a) * r, h - r - 0.25 + Math.sin(a) * r]); }
    hole.push([r, 0.001]);
    const pts = [[-w / 2, 0], ...hole, [w / 2, 0], [w / 2, h], [-w / 2, h]];
    return [mesh(slab(pts, d), m)];
  },
  building: (o, m) => {
    const [w, h, d] = o.size, floors = Math.max(1, o.props?.floors | 0 || 1), fh = h / floors;
    const out = [mesh(boxGeo(w - 0.1, h, d - 0.1), m, fh)];
    const slabMat = material("concrete", darker(o.color, 0.92));
    for (let f = 1; f <= floors; f++) out.push(mesh(boxGeo(w + 0.3, 0.18, d + 0.3, 0, f * fh - 0.18), slabMat));
    out.push(mesh(boxGeo(w - 0.12, 0.05, d - 0.12), material("tilesFloor", "#d8d2c6")));
    return out;
  },
  room: (o, m) => {
    const [w, h, d] = o.size, t = Math.max(0.05, o.props?.thickness ?? 0.2);
    const out = [];
    const front = mesh(wallGeo(w, h, t, { door: o.props?.door !== false }), m); front.position.z = d / 2 - t / 2; out.push(front);
    const back = mesh(wallGeo(w, h, t), m); back.position.z = -d / 2 + t / 2; out.push(back);
    const left = mesh(wallGeo(d - 2 * t, h, t).rotateY(Math.PI / 2), m); left.position.x = -w / 2 + t / 2; out.push(left);
    const right = mesh(wallGeo(d - 2 * t, h, t).rotateY(Math.PI / 2), m); right.position.x = w / 2 - t / 2; out.push(right);
    if (o.props?.floor !== false) out.push(mesh(boxGeo(w, 0.06, d), material("tilesFloor", "#d8d2c6")));
    return out;
  },
  wall: (o, m) => { const [w, h, d] = o.size; return [mesh(wallGeo(w, h, d, o.props || {}), m)]; },
  floor: (o, m) => [mesh(boxGeo(...o.size), m)],
  column: (o, m) => { const [w, h, d] = o.size; return [mesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 24).scale(w, h, d).translate(0, h / 2, 0), m)]; },
  beam: (o, m) => [mesh(boxGeo(...o.size), m)],
  door: (o, m) => {
    const [w, h, d] = o.size, f = 0.08;
    const frame = material("plain", darker(o.color, 0.6));
    return [mesh(boxGeo(w - 2 * f, h - f, d * 0.6), m),
      mesh(boxGeo(f, h, d, -w / 2 + f / 2), frame), mesh(boxGeo(f, h, d, w / 2 - f / 2), frame), mesh(boxGeo(w, f, d, 0, h - f), frame),
      mesh(new THREE.SphereGeometry(0.05, 10, 8).translate(w / 2 - 0.2, h * 0.48, d * 0.35), material("metal", "#d6c27a"))];
  },
  window: (o, m) => {
    const [w, h, d] = o.size, f = 0.07, frame = material("plain", "#f2f2f2");
    return [mesh(boxGeo(w - 2 * f, h - 2 * f, d * 0.3, 0, f), m),
      mesh(boxGeo(f, h, d, -w / 2 + f / 2), frame), mesh(boxGeo(f, h, d, w / 2 - f / 2), frame),
      mesh(boxGeo(w, f, d), frame), mesh(boxGeo(w, f, d, 0, h - f), frame), mesh(boxGeo(f * 0.6, h, d * 0.8), frame)];
  },
  stairs: (o, m) => {
    const [w, h, d] = o.size, n = Math.max(2, Math.round(h / 0.17)), rise = h / n, run = d / n;
    // rises towards the back (-z); you walk up from the front
    const pts = [[-d / 2, 0], [d / 2, 0]];
    for (let i = 0; i < n; i++) { pts.push([d / 2 - i * run, (i + 1) * rise]); pts.push([d / 2 - (i + 1) * run, (i + 1) * rise]); }
    // prism maps profile z -> world -z, so mirror the profile to keep the bottom step at +z
    const g = prism(pts.map(([z, y]) => [-z, y]), w);
    const out = [mesh(g, m)];
    if (o.props?.rails !== false) {
      const railMat = material("metal", "#5b6670");
      const len = Math.hypot(d, h), ang = Math.atan2(h, d);
      for (const sx of [-1, 1]) {
        const rail = mesh(new THREE.BoxGeometry(0.05, 0.05, len), railMat);
        rail.position.set(sx * (w / 2 - 0.03), h / 2 + 0.95, 0); rail.rotation.x = ang; out.push(rail);
        for (let i = 0; i <= 3; i++) {
          const t = i / 3, z = d / 2 - t * d, y = t * h;
          const post = mesh(boxGeo(0.04, 0.95, 0.04, sx * (w / 2 - 0.03), y, z), railMat); out.push(post);
        }
      }
    }
    return out;
  },
  ladder: (o, m) => {
    const [w, h, d] = o.size, out = [];
    out.push(mesh(boxGeo(0.06, h, Math.max(d, 0.06), -w / 2 + 0.03), m), mesh(boxGeo(0.06, h, Math.max(d, 0.06), w / 2 - 0.03), m));
    for (let y = 0.3; y < h - 0.05; y += 0.3) out.push(mesh(new THREE.CylinderGeometry(0.02, 0.02, w, 8).rotateZ(Math.PI / 2).translate(0, y, 0), m));
    return out;
  },
  railing: (o, m) => {
    const [w, h] = o.size, out = [mesh(boxGeo(w, 0.05, 0.05, 0, h - 0.05), m), mesh(boxGeo(w, 0.03, 0.03, 0, h * 0.5), m)];
    const n = Math.max(1, Math.round(w / 1.2));
    for (let i = 0; i <= n; i++) out.push(mesh(boxGeo(0.04, h, 0.04, -w / 2 + (w / n) * i), m));
    return out;
  },
  roofGable: (o, m) => { const [w, h, d] = o.size; return [mesh(prism([[d / 2, 0], [-d / 2, 0], [0, h]], w), m)]; },
  roofMetal: (o, m) => {
    const [w, h, d] = o.size, t = 0.08;
    const pts = [[d / 2, 0], [0, h], [-d / 2, 0], [-d / 2, t], [0, h + t], [d / 2, t]].reverse();
    return [mesh(prism(pts, w), m)];
  },
  roofHip: (o, m) => { const [w, h, d] = o.size; return [mesh(hipRoofGeo(w, h, d), m)]; },
  roofShed: (o, m) => { const [w, h, d] = o.size; return [mesh(prism([[d / 2, 0], [-d / 2, 0], [-d / 2, h], [d / 2, Math.min(0.15, h * 0.2)]], w), m)]; },
  roofFlat: (o, m) => {
    const [w, h, d] = o.size, p = o.props?.parapet ?? 0.6, t = 0.2, out = [mesh(boxGeo(w, h, d), m)];
    if (p > 0) {
      const pm = material("concrete", darker(o.color, 0.9));
      out.push(mesh(boxGeo(w, p, t, 0, h, d / 2 - t / 2), pm), mesh(boxGeo(w, p, t, 0, h, -d / 2 + t / 2), pm),
        mesh(boxGeo(t, p, d - 2 * t, w / 2 - t / 2, h), pm), mesh(boxGeo(t, p, d - 2 * t, -w / 2 + t / 2, h), pm));
    }
    return out;
  },
  roofPyramid: (o, m) => B.pyramid(o, m),
  roofDome: (o, m) => B.hemi(o, m),
  road: (o, m) => {
    const [w, h, d] = o.size, out = [mesh(boxGeo(w, h, d), m)];
    if (o.props?.lines !== false && d >= 3) {
      const lm = material("plain", "#f2f2f2");
      for (let x = -w / 2 + 1; x < w / 2 - 1; x += 4) out.push(mesh(boxGeo(Math.min(2, w / 2 - x), 0.01, 0.15, x + 1, h), lm));
    }
    return out;
  },
  path: (o, m) => [mesh(boxGeo(...o.size), m)],
  fence: (o, m) => {
    const [w, h] = o.size, out = [];
    const n = Math.max(1, Math.round(w / 2.5));
    for (let i = 0; i <= n; i++) out.push(mesh(boxGeo(0.08, h, 0.08, -w / 2 + (w / n) * i), m));
    const mesh2 = new THREE.MeshStandardMaterial({ color: new THREE.Color(o.color), transparent: true, opacity: 0.35, side: THREE.DoubleSide, wireframe: false });
    const net = new THREE.Mesh(new THREE.PlaneGeometry(w, h * 0.9).translate(0, h * 0.5, 0), mesh2); out.push(net);
    out.push(mesh(boxGeo(w, 0.05, 0.05, 0, h - 0.05), m));
    return out;
  },
  hedge: (o, m) => [mesh(new THREE.BoxGeometry(1, 1, 1, 2, 2, 2).scale(...o.size).translate(0, o.size[1] / 2, 0), m)],
  lawn: (o, m) => [mesh(boxGeo(...o.size), m)],
  water: (o, m) => [mesh(boxGeo(...o.size), m)],
  parking: (o, m) => {
    const [w, h, d] = o.size, n = Math.max(1, o.props?.bays | 0 || 6), out = [mesh(boxGeo(w, h, d), m)], lm = material("plain", "#f2f2f2");
    for (let i = 0; i <= n; i++) out.push(mesh(boxGeo(0.12, 0.01, d * 0.9, -w / 2 + (w / n) * i, h, -d * 0.05), lm));
    return out;
  },
  tree: (o) => {
    const [w, h, d] = o.size;
    const trunk = mesh(new THREE.CylinderGeometry(0.12 * w / 4 + 0.08, 0.18 * w / 4 + 0.1, h * 0.45, 10).translate(0, h * 0.225, 0), material("wood", "#6b4a2f"));
    const crown = mesh(new THREE.IcosahedronGeometry(0.5, 1).scale(w, h * 0.65, d).translate(0, h * 0.62, 0), material("plain", o.color));
    return [trunk, crown];
  },
  pine: (o) => {
    const [w, h, d] = o.size, out = [mesh(new THREE.CylinderGeometry(0.12, 0.18, h * 0.3, 8).translate(0, h * 0.15, 0), material("wood", "#5b3e27"))];
    for (let i = 0; i < 3; i++) out.push(mesh(new THREE.ConeGeometry(0.5 * (1 - i * 0.22), 0.45, 12).scale(w, h, d).translate(0, h * (0.42 + i * 0.18), 0), material("plain", o.color)));
    return out;
  },
  palm: (o) => {
    const [w, h] = o.size, out = [];
    const trunk = new THREE.CylinderGeometry(0.14, 0.22, h, 8).translate(0, h / 2, 0);
    out.push(mesh(trunk, material("wood", "#8a6a45")));
    const leafMat = new THREE.MeshStandardMaterial({ color: new THREE.Color(o.color), side: THREE.DoubleSide, roughness: 0.9 });
    for (let i = 0; i < 8; i++) {
      const leaf = new THREE.Mesh(new THREE.PlaneGeometry(w * 0.5, 0.45).translate(w * 0.25, 0, 0), leafMat);
      leaf.position.y = h; leaf.rotation.y = (i / 8) * Math.PI * 2; leaf.rotation.z = -0.45; leaf.castShadow = true;
      out.push(leaf);
    }
    return out;
  },
  bush: (o, m) => [mesh(new THREE.IcosahedronGeometry(0.5, 1).scale(...o.size).translate(0, o.size[1] * 0.45, 0), m)],
  rock: (o, m) => [mesh(new THREE.DodecahedronGeometry(0.5, 0).scale(...o.size).translate(0, o.size[1] * 0.4, 0), m)],
  gate: (o, m) => {
    const [w, h, d] = o.size, out = [];
    const bars = Math.max(4, Math.round(w / 0.25));
    out.push(mesh(boxGeo(w, 0.08, 0.06, 0, h - 0.1), m), mesh(boxGeo(w, 0.08, 0.06, 0, 0.15), m));
    for (let i = 0; i <= bars; i++) out.push(mesh(boxGeo(0.03, h - 0.1, 0.03, -w / 2 + (w / bars) * i), m));
    if (o.props?.pillars !== false) {
      const pm = material("brick", "#c27a5a");
      out.push(mesh(boxGeo(0.6, h + 0.5, 0.6, -w / 2 - 0.3), pm), mesh(boxGeo(0.6, h + 0.5, 0.6, w / 2 + 0.3), pm));
    }
    return out;
  },
  car: (o, m) => {
    const [w, h, d] = o.size, glass = material("glass", "#2a3a48"), tyre = material("plain", "#1d1f22");
    const out = [mesh(boxGeo(w, h * 0.45, d, 0, h * 0.2), m), mesh(boxGeo(w * 0.9, h * 0.35, d * 0.5, 0, h * 0.65, -d * 0.05), glass)];
    for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]])
      out.push(mesh(new THREE.CylinderGeometry(h * 0.2, h * 0.2, 0.25, 16).rotateZ(Math.PI / 2).translate(x * (w / 2 - 0.1), h * 0.2, z * d * 0.32), tyre));
    return out;
  },
  bus: (o, m) => {
    const [w, h, d] = o.size, glass = material("glass", "#2a3a48"), tyre = material("plain", "#1d1f22");
    const out = [mesh(boxGeo(w, h * 0.85, d, 0, h * 0.15), m), mesh(boxGeo(w + 0.02, h * 0.28, d * 0.92, 0, h * 0.55), glass)];
    for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]])
      out.push(mesh(new THREE.CylinderGeometry(0.5, 0.5, 0.3, 16).rotateZ(Math.PI / 2).translate(x * (w / 2 - 0.1), 0.5, z * d * 0.33), tyre));
    return out;
  },
  bench: (o, m) => {
    const [w, h, d] = o.size, legs = material("metal", "#3c4a55");
    return [mesh(boxGeo(w, 0.06, d * 0.7, 0, h * 0.48, d * 0.1), m), mesh(boxGeo(w, h * 0.45, 0.05, 0, h * 0.55, -d / 2 + 0.05), m),
      mesh(boxGeo(0.06, h * 0.5, d * 0.7, -w / 2 + 0.1, 0, d * 0.1), legs), mesh(boxGeo(0.06, h * 0.5, d * 0.7, w / 2 - 0.1, 0, d * 0.1), legs)];
  },
  table: (o, m) => {
    const [w, h, d] = o.size, out = [mesh(boxGeo(w, 0.05, d, 0, h - 0.05), m)];
    for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) out.push(mesh(boxGeo(0.05, h - 0.05, 0.05, x * (w / 2 - 0.08), 0, z * (d / 2 - 0.08)), m));
    return out;
  },
  desk: (o, m) => {
    const [w, h, d] = o.size, rows = Math.max(1, o.props?.rows | 0 || 4), cols = Math.max(1, o.props?.cols | 0 || 3), out = [];
    const cw = w / cols, rd = d / rows;
    for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
      const x = -w / 2 + cw * (c + 0.5), z = -d / 2 + rd * (r + 0.5);
      out.push(mesh(boxGeo(cw * 0.75, 0.04, rd * 0.4, x, h - 0.04, z - rd * 0.1), m), mesh(boxGeo(cw * 0.7, h - 0.04, 0.04, x, 0, z - rd * 0.28), m),
        mesh(boxGeo(cw * 0.35, 0.45, rd * 0.25, x, 0, z + rd * 0.22), material("metal", "#5b6670")));
    }
    return out;
  },
  lamp: (o, m) => {
    const [w, h] = o.size;
    const bulb = new THREE.MeshStandardMaterial({ color: 0xfff3c4, emissive: 0xffe08a, emissiveIntensity: 0.8 });
    return [mesh(new THREE.CylinderGeometry(0.06, 0.1, h, 10).translate(0, h / 2, 0), m), mesh(boxGeo(w, 0.06, 0.06, w / 2, h - 0.06), m),
      mesh(boxGeo(0.35, 0.12, 0.25, w, h - 0.18), bulb)];
  },
  flag: (o, m) => {
    const [w, h] = o.size;
    const cloth = new THREE.Mesh(new THREE.PlaneGeometry(w, w * 0.62).translate(w / 2, h - w * 0.35, 0),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(o.color), side: THREE.DoubleSide }));
    return [mesh(new THREE.CylinderGeometry(0.04, 0.06, h, 10).translate(0, h / 2, 0), material("metal", "#c9ced2")), cloth];
  },
  tank: (o, m) => {
    const [w, h, d] = o.size, stand = o.props?.stand !== false, sh = stand ? h * 0.5 : 0, out = [];
    out.push(mesh(new THREE.CylinderGeometry(0.5, 0.5, 1, 32).scale(w, h - sh, d).translate(0, sh + (h - sh) / 2, 0), m));
    if (stand) {
      const sm = material("metal", "#6f7b84");
      for (const [x, z] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) out.push(mesh(boxGeo(0.12, sh, 0.12, x * w * 0.35, 0, z * d * 0.35), sm));
      out.push(mesh(boxGeo(w * 0.9, 0.12, d * 0.9, 0, sh - 0.12), sm));
    }
    return out;
  },
  goal: (o, m) => {
    const [w, h, d] = o.size;
    const net = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.25, side: THREE.DoubleSide });
    return [mesh(boxGeo(0.12, h, 0.12, -w / 2), m), mesh(boxGeo(0.12, h, 0.12, w / 2), m), mesh(boxGeo(w + 0.12, 0.12, 0.12, 0, h - 0.12), m),
      new THREE.Mesh(new THREE.PlaneGeometry(w, h).translate(0, h / 2, -d), net)];
  },
  sign: (o, m) => {
    const [w, h, d] = o.size;
    const s = textSprite(o.props?.text || "Sign", "#ffffff", o.color);
    s.scale.set(Math.min(w, (h * 0.4) * s.userData.aspect), h * 0.4, 1); s.position.y = h * 0.78; s.material.depthTest = true;
    return [mesh(boxGeo(0.08, h * 0.6, 0.08, -w * 0.35), material("metal", "#59636b")), mesh(boxGeo(0.08, h * 0.6, 0.08, w * 0.35), material("metal", "#59636b")),
      mesh(boxGeo(w, h * 0.42, d, 0, h * 0.57), m), s];
  },
  label: (o) => {
    const [, h] = o.size;
    const s = textSprite(o.props?.text || "Label", o.color);
    s.scale.set(h * s.userData.aspect, h, 1); s.position.y = h / 2;
    return [s];
  },
  person: (o, m) => {
    const [w, h, d] = o.size;
    return [mesh(new THREE.CapsuleGeometry(w * 0.32, h * 0.5, 4, 10).translate(0, h * 0.42, 0), m), mesh(new THREE.SphereGeometry(w * 0.26, 16, 12).translate(0, h * 0.88, 0), material("plain", "#c99a72"))];
  },
};

export function defaults(type) {
  const t = TYPES[type];
  return { type, name: t.label, size: [...t.size], color: t.color, mat: t.mat, opacity: 1, props: { ...(t.props || {}) } };
}

// Build the three.js group for one object.
export function buildObject(o) {
  const g = new THREE.Group();
  g.userData.objId = o.id;
  if (o.hidden) g.visible = false;
  const builder = B[o.type] || B.box;
  const m = material(o.mat, o.color, o.opacity ?? 1);
  for (const part of builder(o, m)) { part.userData.objId = o.id; g.add(part); }
  g.position.set(o.pos[0], o.pos[1], o.pos[2]);
  g.rotation.set(THREE.MathUtils.degToRad(o.rot?.[0] || 0), THREE.MathUtils.degToRad(o.rot?.[1] || 0), THREE.MathUtils.degToRad(o.rot?.[2] || 0), "YXZ");
  return g;
}

export function disposeGroup(g) {
  g.traverse((c) => {
    c.geometry?.dispose();
    if (c.isSprite) { c.material.map?.dispose(); c.material.dispose(); }
    else if (c.material && !c.material.userData?.tile) [].concat(c.material).forEach((mm) => mm.dispose());
  });
}

// Lights, sky and ground shared by the studio and the 3D map view.
export function setupLights(scene) {
  scene.add(new THREE.HemisphereLight(0xdfefff, 0x5a5348, 1.0));
  const sun = new THREE.DirectionalLight(0xffffff, 1.9);
  sun.position.set(-120, 220, -80);
  sun.castShadow = true;
  sun.shadow.mapSize.set(2048, 2048);
  sun.shadow.bias = -0.0005;
  scene.add(sun, sun.target);
  return sun;
}

export function fitSunShadow(sun, cx, cz, span) {
  const s = Math.max(30, span * 0.75);
  Object.assign(sun.shadow.camera, { left: -s, right: s, top: s, bottom: -s, near: 1, far: 1200 });
  sun.shadow.camera.updateProjectionMatrix();
  sun.target.position.set(cx, 0, cz);
  sun.position.set(cx - 120, 260, cz - 80);
}

// Render every object of a scene document into a group (used by the 3D map view).
export function buildWorld(doc) {
  const g = new THREE.Group();
  for (const o of doc?.objects || []) if (!o.hidden) g.add(buildObject(o));
  return g;
}
