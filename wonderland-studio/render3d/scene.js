// Wonder Meadow 3D toon characters (browser side).
//
// Units: one world unit = one design pixel (the stage is always 1080x1920), y up, +z toward
// the camera. Every character is built from primitives in the same local coordinates as the
// 2D rig in wonderland/render/characters.py (feet at the origin, head centre at y=308, ...),
// so the two renderers agree on proportions and anchors.
//
// The Python side is the director: it sends one record per actor per frame (a Pose plus the
// turn angle) and this file only maps Pose -> joints and draws. Nothing here uses time or
// random numbers, so the same input always gives the same pixels.

import * as THREE from 'three';

const DW = 1080, DH = 1920, GROUND_Y = 1340;
const FOCAL = 5200;                 // design px; a long lens keeps big heads undistorted
const AXIS_PITCH = 8 * Math.PI / 180;
const INK = [59 / 255, 51 / 255, 85 / 255];
const D2R = Math.PI / 180;

// Apparent-height calibration: silhouette height at scale 1 equals characters.bounding_height.
// Re-measure with `node driver.mjs --calibrate` after changing a model.
const TARGET_H = { bunny: 630, cat: 500, elephant: 470, bear: 470, duck: 500 };
const FIT = { bunny: 1.0, cat: 1.0, elephant: 1.0, bear: 1.0, duck: 1.0 };
const FOOT_DROP = { bunny: 11, cat: 11, elephant: 11, bear: 11, duck: 11 };   // lift so the soles (not the toes' near edge) sit on the pose's ground line

let renderer, scene, camera, gl, shadowLight, ground, canvas;
let MSAA = 4;
let OW = DW, OH = DH;
const chars = new Map();
const U = {                         // light uniforms shared by every toon material
  uKeyDir: { value: new THREE.Vector3(0, 0, 1) },
  uLit: { value: new THREE.Vector3(1, 1, 1) },
  uShade1: { value: new THREE.Vector3(0.8, 0.78, 0.9) },
  uShade2: { value: new THREE.Vector3(0.65, 0.62, 0.8) },
  uSss: { value: new THREE.Vector3(0.06, 0.02, 0.0) },
  uSpec: { value: 0.3 },
  uRimA: { value: new THREE.Vector3(0.2, 0.8, 0.75) },
  uRimADir: { value: new THREE.Vector3(-1, 0, 0) },
  uRimB: { value: new THREE.Vector3(1.0, 0.6, 0.3) },
  uRimBDir: { value: new THREE.Vector3(1, 0, 0) },
  uBands: { value: new THREE.Vector2(-0.08, -0.6) },
};
const UO = {
  uThick: { value: 4.0 },
  uRes: { value: new THREE.Vector2(DW, DH) },
  uInk: { value: new THREE.Vector3(...INK) },
  uInkMix: { value: 0.62 },
  uDim: { value: new THREE.Vector3(1, 1, 1) },
};

const TOON_VS = `
varying vec3 vN; varying vec3 vP; varying vec3 vO;
void main(){ vec4 mv = modelViewMatrix * vec4(position,1.0); vP = mv.xyz; vO = (modelMatrix * vec4(position,1.0)).xyz;
  vN = normalMatrix * normal; gl_Position = projectionMatrix * mv; }`;
const TOON_FS = `
uniform vec3 uColor; uniform float uGloss; uniform float uRimGain;
uniform vec3 uKeyDir, uLit, uShade1, uShade2, uSss, uRimA, uRimADir, uRimB, uRimBDir; uniform float uSpec; uniform vec2 uBands;
uniform float uMode, uNoise, uNoiseScale, uGlow; uniform vec3 uGlowCol;
varying vec3 vN; varying vec3 vP; varying vec3 vO;
float h3(vec3 p){ return fract(sin(dot(p, vec3(127.1, 311.7, 74.7))) * 43758.5453); }
float vnoise(vec3 p){ vec3 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(mix(h3(i), h3(i + vec3(1,0,0)), f.x), mix(h3(i + vec3(0,1,0)), h3(i + vec3(1,1,0)), f.x), f.y),
             mix(mix(h3(i + vec3(0,0,1)), h3(i + vec3(1,0,1)), f.x), mix(h3(i + vec3(0,1,1)), h3(i + vec3(1,1,1)), f.x), f.y), f.z); }
float fbm(vec3 p){ return 0.5 * vnoise(p) + 0.3 * vnoise(p * 2.03) + 0.2 * vnoise(p * 4.1); }
// Style modes: 0 toon (default), 1 soft 3D, 2 clay, 3 storybook flat, 4 anime cel, 5 hyperreal, 6 sci-fi glow.
vec3 styled(vec3 N, vec3 V, float ndl){
  float lam = clamp(ndl * 0.5 + 0.5, 0.0, 1.0);
  if (uMode > 5.5) {                                   // sci-fi: soft dark body, glowing fresnel edge
    vec3 c = uColor * mix(uShade2 * 0.7, uLit, smoothstep(0.1, 0.95, lam));
    float fr = pow(1.0 - max(dot(N, V), 0.0), 2.5);
    return c + uGlowCol * fr * uGlow + uGlowCol * 0.08 * uGlow;
  }
  if (uMode > 4.5) {                                   // hyperreal: soft wrap light, micro texture, sheen
    float n = fbm(vO * uNoiseScale);
    vec3 c = uColor * (0.86 + 0.28 * n) * mix(uShade2, uLit, smoothstep(0.05, 1.0, lam));
    c += uColor * uSss * 1.6 * exp(-pow((ndl + 0.1) / 0.35, 2.0));
    float fr = pow(1.0 - max(dot(N, V), 0.0), 3.0);
    return c + vec3(1.0) * 0.18 * fr;
  }
  if (uMode > 3.5) {                                   // anime cel: one hard terminator, crisp light
    float b = step(0.02, ndl);
    return uColor * mix(uShade1 * 0.92, uLit, b);
  }
  if (uMode > 2.5) {                                   // storybook: two painted tones and paper grain
    float b = smoothstep(-0.12, 0.0, ndl);
    float g = fbm(vO * uNoiseScale);
    return uColor * mix(uShade1, uLit, b) * (0.93 + 0.12 * g);
  }
  if (uMode > 1.5) {                                   // clay: matte, soft, thumb-pressed surface
    float n = fbm(vO * uNoiseScale);
    vec3 Np = normalize(N + uNoise * (vec3(n, fbm(vO * uNoiseScale + 7.3), fbm(vO * uNoiseScale + 3.1)) - 0.5));
    float l = clamp(dot(Np, uKeyDir) * 0.5 + 0.5, 0.0, 1.0);
    return uColor * mix(uShade2 * 0.95, uLit, smoothstep(0.15, 0.95, l)) * (0.95 + 0.08 * n);
  }
  vec3 c = uColor * mix(uShade2, uLit, smoothstep(0.08, 1.0, lam));     // soft 3D
  return c + uColor * uSss * exp(-pow((ndl + 0.05) / 0.3, 2.0));
}
void main(){
  vec3 N = normalize(vN); vec3 V = normalize(-vP);
  float ndl = dot(N, uKeyDir);
  if (uMode > 0.5) {
    vec3 c = styled(N, V, ndl);
    if (uMode < 2.5 || (uMode > 4.5 && uMode < 5.5)) {   // soft/hyperreal: gentle rim + glossy highlight
      float fr = pow(1.0 - max(dot(N, V), 0.0), 2.0);
      c = c + (vec3(1.0) - c) * uRimA * 0.5 * smoothstep(0.15, 0.6, fr * smoothstep(-0.1, 0.6, dot(N, uRimADir))) * uRimGain;
      float nh = max(dot(N, normalize(uKeyDir + V)), 0.0);
      c = c + (vec3(1.0) - c) * uSpec * pow(nh, 60.0) * 1.3;
    } else if (uMode > 3.5 && uMode < 4.5) {             // anime: small hard highlight
      float nh = dot(N, normalize(uKeyDir + V));
      c = c + (vec3(1.0) - c) * 0.55 * step(uGloss, nh);
    }
    gl_FragColor = vec4(c, 1.0);
    return;
  }
  float w = fwidth(ndl) * 1.5 + 0.03;
  float b1 = smoothstep(uBands.x - w, uBands.x + w, ndl);
  float b2 = smoothstep(uBands.y - w, uBands.y + w, ndl);
  vec3 col = uColor * mix(uShade2, mix(uShade1, uLit, b1), b2);
  float term = exp(-pow((ndl - uBands.x) / 0.2, 2.0));          // warm wrap at the terminator (fake subsurface)
  col += uColor * uSss * term;
  float fr = pow(1.0 - max(dot(N, V), 0.0), 2.0);
  float ra = smoothstep(0.20, 0.36, fr * smoothstep(-0.1, 0.6, dot(N, uRimADir)));
  float rb = smoothstep(0.20, 0.36, fr * smoothstep(-0.1, 0.6, dot(N, uRimBDir)));
  col = col + (vec3(1.0) - col) * uRimA * ra * uRimGain;
  col = col + (vec3(1.0) - col) * uRimB * rb * uRimGain;
  vec3 Hh = normalize(uKeyDir + V);
  float nh = dot(N, Hh);
  float sw = fwidth(nh) * 1.5 + 0.012;
  float sp = smoothstep(uGloss - sw, uGloss + sw, nh);
  col = col + (vec3(1.0) - col) * uSpec * sp;
  gl_FragColor = vec4(col, 1.0);
}`;
const FLAT_VS = `void main(){ gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`;
const FLAT_FS = `uniform vec3 uColor; uniform vec3 uDim; uniform float uUnlit; void main(){ gl_FragColor = vec4(uColor * mix(uDim, vec3(1.0), uUnlit), 1.0); }`;
const HULL_VS = `
uniform float uThick; uniform vec2 uRes; uniform float uScale;
void main(){
  vec4 clip = projectionMatrix * modelViewMatrix * vec4(position,1.0);
  vec3 n = normalMatrix * normal;
  vec2 d = n.xy / max(length(n.xy), 1e-4);
  clip.xy += d * (uThick * uScale) * 2.0 / uRes * clip.w;
  gl_Position = clip;
}`;
const HULL_FS = `uniform vec3 uColor; uniform vec3 uInk; uniform float uInkMix; uniform vec3 uDim;
void main(){ gl_FragColor = vec4(mix(uColor, uInk, uInkMix) * uDim * 0.92, 1.0); }`;

function rgb(hex) {
  if (Array.isArray(hex)) return hex;
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16) / 255, parseInt(h.slice(2, 4), 16) / 255, parseInt(h.slice(4, 6), 16) / 255];
}
const mixc = (a, b, t) => { a = rgb(a); b = rgb(b); return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t]; };
const lighten = (c, t) => mixc(c, [1, 1, 1], t);
const darken = (c, t) => mixc(c, [30 / 255, 25 / 255, 50 / 255], t);

// Per-character art style. Set while a character is built; null = the original toon look.
let STY = null;
function styleUniforms(st) {
  return { uMode: { value: st.mode || 0 }, uNoise: { value: st.noise ?? 0.35 }, uNoiseScale: { value: st.noise_scale ?? 0.05 },
           uGlow: { value: st.glow ?? 0 }, uGlowCol: { value: new THREE.Vector3(...rgb(st.glow_color || '#40E0FF')) } };
}
const NO_STYLE = styleUniforms({});
function toonMat(color, gloss = 0.986, rimGain = 1.0) {
  return new THREE.ShaderMaterial({
    vertexShader: TOON_VS, fragmentShader: TOON_FS,
    uniforms: { ...U, ...(STY ? STY.u : NO_STYLE), uColor: { value: new THREE.Vector3(...rgb(color)) }, uGloss: { value: gloss },
                uRimGain: { value: rimGain } },
  });
}
function flatMat(color, unlit = 0.0) {
  return new THREE.ShaderMaterial({ vertexShader: FLAT_VS, fragmentShader: FLAT_FS,
    uniforms: { uColor: { value: new THREE.Vector3(...rgb(color)) }, uDim: UO.uDim, uUnlit: { value: unlit } } });
}
function hullMat(color, scale = 1.0) {
  return new THREE.ShaderMaterial({ vertexShader: HULL_VS, fragmentShader: HULL_FS, side: THREE.BackSide,
    uniforms: { ...UO, uColor: { value: new THREE.Vector3(...rgb(color)) }, uScale: { value: scale } } });
}

const SPH = new THREE.SphereGeometry(1, 28, 18);
const SPH_HI = new THREE.SphereGeometry(1, 60, 40);
const SPH_LO = new THREE.SphereGeometry(1, 16, 10);
const HEMI = new THREE.SphereGeometry(1, 28, 12, 0, Math.PI * 2, 0, Math.PI / 2);

// part(): one toon mesh plus its inverted-hull outline.
function part(parent, geom, color, o = {}) {
  const mat = o.flat ? flatMat(color, o.unlit || 0) : toonMat(color, o.gloss, o.rim);
  const m = new THREE.Mesh(geom, mat);
  if (o.pos) m.position.set(...o.pos);
  if (o.scale) m.scale.set(...(Array.isArray(o.scale) ? o.scale : [o.scale, o.scale, o.scale]));
  if (o.rot) m.rotation.set(o.rot[0] * D2R, o.rot[1] * D2R, o.rot[2] * D2R);
  m.castShadow = o.cast === true;          // only the big forms cast (cheap shadow pass)
  if (o.outline !== false && !o.flat && !(STY && STY.outline === 0)) {
    const h = new THREE.Mesh(geom, hullMat(o.outlineColor || color, (o.outlineScale || 1) * (STY ? (STY.outline ?? 1) : 1)));
    h.castShadow = false;
    m.add(h);
    m.userData.hull = h;
  }
  if (o.order) m.renderOrder = o.order;
  parent.add(m);
  return m;
}
function group(parent, pos) { const g = new THREE.Group(); if (pos) g.position.set(...pos); parent.add(g); return g; }

function tube(parent, pts, radius, color, o = {}) {
  const curve = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)));
  const geom = new THREE.TubeGeometry(curve, o.segs || 24, radius, o.radial || 12, false);
  const m = part(parent, geom, color, o);
  if (o.caps !== false) {
    part(m, SPH_LO, color, { ...o, pos: pts[0], scale: radius, rot: undefined });
    part(m, SPH_LO, color, { ...o, pos: pts[pts.length - 1], scale: radius, rot: undefined });
  }
  return m;
}

// Ellipsoid helpers: z of the front surface at (x, y), and the outward normal there.
function surf(e, x, y) {
  const k = 1 - ((x - e.c[0]) / e.r[0]) ** 2 - ((y - e.c[1]) / e.r[1]) ** 2;
  const z = e.c[2] + e.r[2] * Math.sqrt(Math.max(0.02, k));
  const n = new THREE.Vector3((x - e.c[0]) / e.r[0] ** 2, (y - e.c[1]) / e.r[1] ** 2, (z - e.c[2]) / e.r[2] ** 2).normalize();
  return { p: new THREE.Vector3(x, y, z), n };
}
// A group sitting on an ellipsoid at (x, y) with its +z along a blend of the normal and "forward".
function onSurf(parent, e, x, y, inset = 0, forward = 0.0) {
  const s = surf(e, x, y);
  const g = new THREE.Group();
  const dir = s.n.clone().lerp(new THREE.Vector3(0, 0, 1), forward).normalize();
  g.position.copy(s.p).addScaledVector(dir, -inset);
  g.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), dir);
  parent.add(g);
  return g;
}

function arc(parent, half, sag, radius, color, z = 0) {
  const curve = new THREE.QuadraticBezierCurve3(new THREE.Vector3(-half, -sag / 2, z), new THREE.Vector3(0, sag * 1.5, z + half * 0.12), new THREE.Vector3(half, -sag / 2, z));
  const m = new THREE.Mesh(new THREE.TubeGeometry(curve, 14, radius, 8, false), flatMat(color));
  for (const sx of [-half, half]) { const c = new THREE.Mesh(SPH_LO, m.material); c.position.set(sx, -sag / 2, z); c.scale.setScalar(radius); m.add(c); }
  parent.add(m);
  return m;
}

// ------------------------------------------------------------------ character -------
function buildCharacter(spec) {
  STY = spec.style ? { ...spec.style, u: styleUniforms(spec.style) } : null;
  try { return buildStyled(spec); } finally { STY = null; }
}

function buildStyled(spec) {
  const sp = spec.species, col = spec.colors;
  const body = rgb(col.body), belly = rgb(col.belly), inner = rgb(col.inner_ear), accent = rgb(col.accent), nose = rgb(col.nose);
  const accessory = (spec.clothing || {}).accessory;
  const ink = INK, mouthDark = [122 / 255, 46 / 255, 59 / 255], tongueC = [1, 138 / 255, 150 / 255];
  const R = { species: sp, id: spec.id };

  R.root = new THREE.Group();
  R.leanN = group(R.root); R.squashN = group(R.leanN); R.yawN = group(R.squashN);
  const B = R.yawN;

  // ---- body
  const duck = sp === 'duck';
  const BODY = { c: [0, 120, 0], r: duck ? [104, 116, 96] : [110, 114, 98] };
  part(B, SPH_HI, body, { pos: BODY.c, scale: BODY.r, cast: true });
  // belly: a slightly smaller copy of the body pushed forward, so it hugs the curvature
  part(B, SPH_HI, belly, { pos: [0, 112, 10], scale: [BODY.r[0] - 10, BODY.r[1] - 12, BODY.r[2] - 6], outline: false, cast: false });

  // ---- feet
  R.feet = [];
  const boots = accessory === 'boots';
  const footCol = boots ? accent : (duck ? nose : darken(body, 0.12));
  for (const side of [-1, 1]) {
    const f = group(B, [side * 54, 0, 8]);
    if (boots) {
      part(f, new THREE.CapsuleGeometry(27, 30, 8, 20), footCol, { pos: [0, 40, -4] });
      part(f, SPH, footCol, { pos: [side * 4, 19, 16], scale: [36, 22, 50], cast: true });
      part(f, new THREE.TorusGeometry(27, 7, 10, 28), lighten(footCol, 0.35), { pos: [0, 62, -4], rot: [90, 0, 0], outline: false });
    } else {
      part(f, SPH, footCol, { pos: [side * 2, 18, 14], scale: [42, 22, 58], cast: true });
    }
    R.feet.push({ g: f, side });
  }

  // ---- arms (pivot at the shoulder; the limb hangs down -y)
  R.arms = {};
  for (const side of [-1, 1]) {
    const piv = group(B, [side * 92, 182, 10]);
    if (duck) part(piv, SPH, body, { pos: [0, -50, 0], scale: [30, 62, 15], cast: true });
    else {
      part(piv, new THREE.CapsuleGeometry(22, 96, 6, 16), body, { pos: [0, -48, 0], cast: true });
    }
    const hand = group(piv, [0, -96, 0]);
    R.arms[side] = { piv, hand, side };
  }

  // ---- tail (lives in tailN so it can swing to the trailing side)
  R.tailN = group(B, [0, 0, 0]);
  if (sp === 'bunny') part(R.tailN, SPH, lighten(belly, 0.3), { pos: [0, 70, -112], scale: [38, 36, 36], outlineColor: body });
  else if (sp === 'bear') part(R.tailN, SPH, body, { pos: [0, 74, -106], scale: [26, 25, 25] });
  else if (sp === 'duck') part(R.tailN, new THREE.ConeGeometry(34, 78, 24, 1), body, { pos: [0, 118, -108], rot: [-62, 0, 0] });
  else if (sp === 'elephant') {
    tube(R.tailN, [[0, 92, -92], [0, 76, -128], [0, 46, -142]], 6, darken(body, 0.3), { outline: false });
    part(R.tailN, SPH_LO, darken(body, 0.36), { pos: [0, 38, -144], scale: [12, 15, 12], outline: false });
  } else if (sp === 'cat') {
    R.catTail = group(R.tailN, [0, 58, -78]);
    const pts = [[0, 0, 0], [-58, 10, -34], [-98, 60, -44], [-100, 122, -36], [-76, 166, -22]];
    tube(R.catTail, pts, 17, body, { segs: 40, radial: 16 });
    const stripe = rgb(col.stripe || darken(body, 0.15));
    const curve = new THREE.CatmullRomCurve3(pts.map(p => new THREE.Vector3(...p)));
    for (const u of [0.42, 0.62, 0.82]) {
      const p = curve.getPoint(u), t = curve.getTangent(u);
      const ring = part(R.catTail, new THREE.TorusGeometry(15.5, 4.2, 8, 24), stripe, { pos: [p.x, p.y, p.z], outline: false, cast: false });
      ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), t);
    }
  }

  // ---- clothing on the body
  if (accessory === 'overalls') {
    const OV = { c: BODY.c, r: [BODY.r[0] + 6, BODY.r[1] + 4, BODY.r[2] + 7] };
    const lower = new THREE.SphereGeometry(1, 48, 20, 0, Math.PI * 2, Math.PI * 0.53, Math.PI * 0.47);
    part(B, lower, accent, { pos: OV.c, scale: OV.r, outlineScale: 0.8 });
    const pocket = onSurf(B, OV, 0, 78, 3, 0.1);
    part(pocket, SPH_LO, lighten(accent, 0.18), { scale: [30, 22, 5], outlineColor: accent, outlineScale: 0.5, cast: false });
    for (const side of [-1, 1]) {
      tube(B, [[side * 56, 112, 92], [side * 56, 160, 84], [side * 54, 200, 56], [side * 52, 222, 4], [side * 48, 196, -64], [side * 44, 140, -96]], 8.5, accent, { segs: 24, radial: 10, outlineScale: 0.6 });
      const bt = onSurf(B, OV, side * 56, 116, -2, 0.1);
      part(bt, SPH_LO, '#FFD95A', { scale: [9, 9, 5], outlineColor: darken(accent, 0.3), outlineScale: 0.5, cast: false });
    }
  }
  if (accessory === 'scarf') {
    part(B, new THREE.TorusGeometry(80, 23, 14, 40), accent, { pos: [0, 204, 4], rot: [90, 0, 0], scale: [1, 0.94, 0.85] });
    const sc = group(B, [52, 196, 78]);
    part(sc, new THREE.CapsuleGeometry(21, 52, 8, 18), accent, { pos: [6, -36, 6], rot: [14, 0, 10], scale: [1, 1, 0.42] });
    part(sc, SPH_LO, accent, { pos: [0, 2, 4], scale: [24, 20, 16] });
  } else if (accessory === 'bandana') {
    part(B, new THREE.TorusGeometry(78, 15, 12, 40), accent, { pos: [0, 206, 4], rot: [90, 0, 0], scale: [1, 0.94, 0.8] });
    const bd = group(B, [0, 196, 84]);
    const tri = part(bd, new THREE.ConeGeometry(52, 72, 3, 1), accent, { pos: [0, -30, 4], rot: [8, 0, 180], scale: [1.15, 1, 0.22] });
    tri.geometry.computeVertexNormals();
    for (const [dx, dy] of [[-20, -8], [20, -10], [0, -34]]) part(bd, SPH_LO, lighten(accent, 0.55), { pos: [dx, dy, 13 - Math.abs(dx) * 0.1], scale: [6, 6, 3], outline: false, cast: false });
  }

  // ---- head
  R.headPivot = group(B, [0, 212, 0]);
  const Hd = group(R.headPivot, [0, -212, 0]);
  const HEAD = { c: [0, 308, 6], r: [154, 138, 134] };
  part(Hd, SPH_HI, body, { pos: HEAD.c, scale: HEAD.r, cast: true });

  let eyeY = 304, eyeDx = 62, mouthY = 244, faceE = HEAD, mouthX = 0;
  if (sp === 'duck') { eyeY = 316; eyeDx = 56; }
  if (sp === 'elephant') { eyeY = 318; eyeDx = 68; }
  if (sp === 'bear') mouthY = 238;

  // muzzle
  let MUZ = null;
  if (sp === 'bunny' || sp === 'cat' || sp === 'bear') {
    const mr = sp === 'bear' ? [66, 50, 40] : [58, 40, 34];
    const s0 = surf(HEAD, 0, sp === 'bear' ? 256 : 254);
    MUZ = { c: [0, s0.p.y, s0.p.z - mr[2] + (sp === 'bear' ? 26 : 18)], r: mr };
    part(Hd, SPH_HI, sp === 'bear' ? belly : lighten(belly, 0.2), { pos: MUZ.c, scale: MUZ.r, outline: false, cast: false, rim: 0.3 });
    faceE = MUZ;
  }

  // cheeks
  const blush = mixc(body, [1, 120 / 255, 150 / 255], 0.5);
  for (const side of [-1, 1]) {
    const cg = onSurf(Hd, HEAD, side * (eyeDx + 48), eyeY - 48, 5, 0.1);
    part(cg, SPH_LO, blush, { scale: [25, 15, 7], outline: false, cast: false, rim: 0 });
  }

  // eyes
  R.eyes = [];
  for (const side of [-1, 1]) {
    const eg = onSurf(Hd, HEAD, side * eyeDx, eyeY, 7, 0.55);
    const sizeN = group(eg);
    const open = group(sizeN);
    part(open, SPH, [1, 1, 1], { scale: [31, 35, 13], outlineColor: ink, gloss: 0.99, rim: 0.25, cast: false });
    const look = group(open, [0, 0, -44]);
    const pup = group(look, [0, 0, 44]);
    part(pup, SPH, ink, { pos: [0, 0, 10.5], scale: [18.5, 21.5, 5], flat: true, unlit: 0.6 });
    part(pup, SPH_LO, mixc(ink, body, 0.35), { pos: [0, -5, 12.2], scale: [13, 13, 4], flat: true, unlit: 0.4 });
    part(pup, SPH_LO, ink, { pos: [0, 0, 13.2], scale: [9.5, 11, 4], flat: true, unlit: 0.6 });
    part(pup, SPH_LO, [1, 1, 1], { pos: [-6.5, 8.5, 15], scale: [7.2, 7.2, 3], flat: true, unlit: 1 });
    part(pup, SPH_LO, [0.86, 0.86, 0.95], { pos: [7, -8.5, 15], scale: [3.6, 3.6, 2.5], flat: true, unlit: 1 });
    // sleepy upper lid
    const lid = group(sizeN);
    part(lid, HEMI, body, { pos: [0, 9, 0], scale: [33.5, 28, 15.5], cast: false, rim: 0.3 });
    const lash = arc(lid, 31, 2.2, 2.8, darken(body, 0.5), 15.5); lash.position.y = 9.5;
    // closed
    const closed = group(sizeN);
    part(closed, SPH, body, { scale: [32, 36, 12], outline: false, cast: false, rim: 0.3 });
    const arcG = group(closed, [0, 0, 12.5]);
    arc(arcG, 24, 8, 3.6, ink, 0);
    R.eyes.push({ side, sizeN, open, look, lid, closed, arcG });
  }
  // brows (only shown when sad)
  R.brows = [];
  for (const side of [-1, 1]) {
    const bg = onSurf(Hd, HEAD, side * (eyeDx - 4), eyeY + 56, -2, 0.3);
    const b = part(bg, new THREE.CapsuleGeometry(4, 26, 6, 10), darken(body, 0.5), { rot: [0, 0, 90 - side * 22], flat: true, unlit: 0.3 });
    b.scale.z = 0.6;
    bg.visible = false;
    R.brows.push(bg);
  }

  // mouth
  const mk = (anchorE, mx, my, inset = -1.5) => {
    const mg = onSurf(Hd, anchorE, mx, my, inset, 0.35);
    const M = { g: mg };
    M.smile = arc(mg, 23, -7.5, 3.2, ink, 1); M.smile.position.y = -1;
    M.sad = arc(mg, 19, 5.5, 3.2, ink, 1); M.sad.position.y = -2;
    M.o = group(mg);
    part(M.o, SPH_LO, ink, { scale: [13.5, 15.5, 4], flat: true, unlit: 0.3 });
    part(M.o, SPH_LO, mouthDark, { pos: [0, 0, 1.5], scale: [10.5, 12.5, 4], flat: true, unlit: 0.3 });
    M.open = group(mg);
    M.openInk = part(M.open, SPH, ink, { scale: [1, 1, 4], flat: true, unlit: 0.3 });
    M.openIn = part(M.open, SPH, mouthDark, { pos: [0, 0, 1.6], scale: [1, 1, 4], flat: true, unlit: 0.3 });
    M.tongue = part(M.open, SPH_LO, tongueC, { pos: [0, 0, 3.4], scale: [1, 1, 3.4], flat: true, unlit: 0.3 });
    return M;
  };

  if (sp === 'bunny') {
    R.mouth = mk(MUZ, 0, mouthY - 4);
    R.teeth = group(R.mouth.g, [0, -2, 1]);
    for (const sx of [-6.2, 6.2]) part(R.teeth, new THREE.CapsuleGeometry(4.6, 8, 4, 10), [1, 1, 1], { pos: [sx, -9, 1.5], scale: [1, 1, 0.5], outlineColor: ink, outlineScale: 0.55, cast: false, rim: 0 });
    const ng = onSurf(Hd, MUZ, 0, 268, 3, 0.4);
    part(ng, SPH_LO, nose, { scale: [13, 10, 9], outlineScale: 0.6, cast: false });
  } else if (sp === 'cat') {
    R.mouth = mk(MUZ, 0, mouthY - 3);
    const ng = onSurf(Hd, MUZ, 0, 268, 3, 0.4);
    part(ng, new THREE.ConeGeometry(13, 15, 3, 1), nose, { rot: [0, 0, 180], scale: [1.1, 1, 0.55], outlineScale: 0.6, cast: false });
    const wk = darken(body, 0.5);
    for (const side of [-1, 1]) for (const dy of [-13, 0, 13]) {
      const a = surf(HEAD, side * 78, 258 + dy * 0.4).p;
      tube(Hd, [[a.x, a.y, a.z - 2], [side * 150, 262 + dy, a.z - 14]], 1.9, wk, { flat: true, unlit: 0.2, caps: false, segs: 2, radial: 6 });
    }
    const stripe = rgb(col.stripe || darken(body, 0.15));
    for (const [dx, top] of [[-27, 430], [0, 438], [27, 430]]) {
      const sg = onSurf(Hd, HEAD, dx * 0.9, top - 17, 3.5, 0);
      part(sg, SPH_LO, stripe, { scale: [6.5, 21, 6], rot: [0, 0, -dx * 0.25], outline: false, cast: false, rim: 0.3 });
    }
  } else if (sp === 'bear') {
    R.mouth = mk(MUZ, 0, mouthY);
    const ng = onSurf(Hd, MUZ, 0, 272, 5, 0.3);
    part(ng, SPH_LO, nose, { scale: [21, 15, 12], outline: false, gloss: 0.95, cast: false });
    part(ng, SPH_LO, lighten(nose, 0.4), { pos: [-6, 5, 10.5], scale: [6, 4, 2.5], flat: true, unlit: 0.7 });
  } else if (sp === 'elephant') {
    R.mouthSlide = group(Hd);
    R.mouth = mk(HEAD, 0, 224, -1.5);
    R.elMouthAt = (x) => { const s = surf(HEAD, x, 224); R.mouth.g.position.copy(s.p).addScaledVector(s.n, 1.5);
      R.mouth.g.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), s.n.clone().lerp(new THREE.Vector3(0, 0, 1), 0.35).normalize()); };
    const t0 = surf(HEAD, 0, 284).p;
    R.trunk = group(Hd, [0, 284, t0.z - 22]);
    R.trunkCurl = group(R.trunk);
    const tp = [[0, 0, 0], [0, -26, 18], [1, -56, 32], [6, -80, 40], [20, -92, 44], [34, -88, 44], [40, -74, 42]];
    tube(R.trunkCurl, tp, 19, body, { segs: 44, radial: 18 });
    const tc = new THREE.CatmullRomCurve3(tp.map(p => new THREE.Vector3(...p)));
    for (const u of [0.22, 0.36, 0.5]) {
      const p = tc.getPoint(u), t = tc.getTangent(u);
      const ring = part(R.trunkCurl, new THREE.TorusGeometry(18.8, 2.0, 6, 28), darken(body, 0.16), { pos: [p.x, p.y, p.z], outline: false, cast: false });
      ring.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), t);
    }
    const te = tp[tp.length - 1];
    part(R.trunkCurl, SPH_LO, inner, { pos: [te[0], te[1] + 6, te[2]], scale: [12, 4, 12], outline: false, cast: false });
  } else if (duck) {
    const b0 = surf(HEAD, 0, 262).p;
    R.beak = group(Hd, [0, 262, b0.z - 26]);
    R.beakLower = group(R.beak);
    part(R.beakLower, SPH, darken(nose, 0.18), { pos: [0, -14, 22], scale: [40, 13, 40], outlineColor: darken(nose, 0.25) });
    R.beakIn = part(R.beak, SPH_LO, mouthDark, { pos: [0, -9, 22], scale: [30, 8, 34], flat: true, unlit: 0.3 });
    part(R.beak, SPH, nose, { pos: [0, 4, 26], scale: [54, 19, 52], outlineColor: darken(nose, 0.25) });
    for (const sx of [-15, 15]) part(R.beak, SPH_LO, darken(nose, 0.45), { pos: [sx, 17, 50], scale: [4, 2.5, 3], flat: true, unlit: 0.2 });
    R.mouth = null;
  }

  // ---- ears / tuft
  R.ears = [];
  if (sp === 'bunny') {
    for (const side of [-1, 1]) {
      const piv = group(Hd, [side * 62, 404, -4]);
      const e = group(piv);
      part(e, SPH, body, { pos: [0, 104, 0], scale: [41, 124, 24], cast: true });
      part(e, SPH, inner, { pos: [0, 100, 13], scale: [21, 92, 15], outline: false, cast: false, rim: 0.3 });
      R.ears.push({ piv, side });
    }
  } else if (sp === 'cat') {
    for (const side of [-1, 1]) {
      const piv = group(Hd, [side * 96, 398, -2]);
      const cone = new THREE.ConeGeometry(52, 104, 20, 3);
      part(piv, cone, body, { cast: true, pos: [side * 8, 46, 0], rot: [0, 0, -side * 18], scale: [1, 1, 0.55] });
      part(piv, new THREE.ConeGeometry(32, 66, 20, 2), inner, { pos: [side * 7, 40, 17], rot: [-9, 0, -side * 18], scale: [1, 1, 0.3], outline: false, cast: false, rim: 0.3 });
      R.ears.push({ piv, side });
    }
  } else if (sp === 'elephant') {
    for (const side of [-1, 1]) {
      const piv = group(Hd, [side * 116, 318, -8]);
      const e = group(piv);
      e.rotation.y = side * 20 * D2R;
      part(e, SPH, body, { pos: [side * 70, 4, 0], scale: [100, 116, 17], cast: true });
      part(e, SPH, inner, { pos: [side * 68, 8, 10], scale: [68, 84, 10], outline: false, cast: false, rim: 0.3 });
      R.ears.push({ piv, side });
    }
  } else if (sp === 'bear') {
    for (const side of [-1, 1]) {
      const piv = group(Hd, [side * 112, 410, -4]);
      part(piv, SPH, body, { scale: [52, 50, 30], cast: true });
      part(piv, SPH, inner, { pos: [0, -2, 19], scale: [30, 28, 14], outline: false, cast: false, rim: 0.3 });
      R.ears.push({ piv, side });
    }
  } else if (duck) {
    R.tuft = [];
    for (const [rot, dx] of [[-24, -16], [0, 0], [24, 16]]) {
      const piv = group(Hd, [dx, 438, 0]);
      part(piv, SPH_LO, body, { pos: [0, 24, 0], scale: [12, 30, 10] });
      piv.userData.base = rot;
      R.tuft.push(piv);
    }
  }

  // ---- bow
  if (accessory === 'bow') {
    const bw = group(Hd, [-104, 424, 38]);
    bw.rotation.set(-0.25, -0.35, 18 * D2R);
    for (const side of [-1, 1]) part(bw, new THREE.ConeGeometry(36, 60, 20, 4), accent, { pos: [side * 32, 0, 0], rot: [0, 0, side * 90], scale: [1, 1, 0.5] });
    part(bw, SPH_LO, lighten(accent, 0.2), { scale: [17, 17, 14], outlineColor: accent });
  }

  // ---- anchors
  R.loc = { headTop: group(Hd, [0, 450, 0]), mouth: group(Hd, [0, mouthY, HEAD.c[2] + HEAD.r[2]]), feet: group(R.root, [0, 0, 0]),
            chin: group(Hd, [0, HEAD.c[1] - HEAD.r[1], 0]) };
  R.root.traverse(o => { o.frustumCulled = false; });
  // style proportions: body (uniform or [x, y, z]) scales the figure; head and eyes scale on top of it
  const st = spec.style || {};
  const bs = Array.isArray(st.body) ? st.body : [st.body || 1, st.body || 1, st.body || 1];
  R.yawN.scale.set(...bs);
  const hk = st.head || 1;
  R.headPivot.scale.set(hk / bs[0], hk / bs[1], hk / bs[2]);
  R.eyeK = st.eye || 1;
  return R;
}

// ------------------------------------------------------------------ posing ----------
const _v = new THREE.Vector3(), _q = new THREE.Quaternion(), DOWN = new THREE.Vector3(0, -1, 0);

function armElevation(a) {          // big heads: above ~125 deg the arm opens outward instead of into the head
  return a <= 125 ? a : 125 + (a - 125) * 0.55;
}

function unprojectToStage(x, y) {
  _v.set(x / DW * 2 - 1, 1 - y / DH * 2, 0.5).unproject(camera);
  const o = camera.position, d = _v.sub(o).normalize();
  const t = -o.z / d.z;
  return new THREE.Vector3(o.x + d.x * t, o.y + d.y * t, 0);
}

const POSE_DEFAULTS = { x: 540, y: GROUND_Y, scale: 1, side: 1, yaw: 0, lift: 0, squash: 0, head_tilt: 0, arm_l: 18, arm_r: 18,
  look: 0, look_y: 0, blink: 0, mouth: 0, mood: 'happy', ear: 0, step: 0, lean: 0 };

function poseCharacter(R, a) {
  const s = a.scale * FIT[R.species];
  const g = unprojectToStage(a.x, a.y);
  const elev = Math.atan2(camera.position.y - g.y, camera.position.z);
  R.root.position.set(g.x, g.y + (a.lift || 0) / Math.cos(elev) + FOOT_DROP[R.species] * a.scale, 0);
  R.root.scale.setScalar(s);
  R.leanN.rotation.z = -(a.lean || 0) * D2R;
  const sq = a.squash || 0;
  R.squashN.scale.set(1 + sq * 0.45, 1 - sq * 0.45, 1 + sq * 0.45);
  const yaw = (a.yaw || 0) * D2R;
  R.yawN.rotation.set((a.pitch || 0) * D2R, yaw, 0, 'XYZ');
  const side = a.side;                                   // +1 faces right .. -1 faces left (continuous while turning)
  const m = (1 + side) / 2;

  // arms: 2D semantics (arm_r is the screen-right arm unless flipped)
  const angP = m * a.arm_r + (1 - m) * a.arm_l, angN = m * a.arm_l + (1 - m) * a.arm_r;
  for (const [sd, ang] of [[1, angP], [-1, angN]]) {
    const e = armElevation(ang) * D2R;
    const beta = (14 + 22 * Math.min(1, Math.max(0, ang) / 130)) * D2R;
    _v.set(sd * Math.sin(e) * Math.cos(beta), -Math.cos(e), Math.sin(e) * Math.sin(beta) + 0.1).normalize();
    R.arms[sd].piv.quaternion.setFromUnitVectors(DOWN, _v);
  }

  // feet
  for (const f of R.feet) {
    const ph = (a.step || 0) + (f.side < 0 ? 0 : Math.PI);
    const up = Math.max(0, Math.sin(ph)) * 16;
    const walking = a.step ? 1 : 0;
    f.g.position.set(f.side * 54, up, 8 + walking * Math.cos(ph) * 14);
    f.g.rotation.x = -up * 0.012;
  }

  // head
  const tilt = (a.head_tilt || 0) * D2R;
  const lookY = a.look_y || 0, lookX = a.look || 0;
  R.headPivot.rotation.set(lookY * 0.13, (a.head_yaw || 0) * D2R + lookX * 0.16, -tilt * side, 'YXZ');

  // ears, tail
  const wig = (a.ear || 0);
  for (const e of R.ears) {
    if (R.species === 'bunny') e.piv.rotation.set(-0.06, 0, -e.side * (7 + wig) * D2R);
    else if (R.species === 'cat') e.piv.rotation.z = -e.side * wig * 0.5 * D2R;
    else if (R.species === 'elephant') e.piv.rotation.y = -e.side * (10 + wig * 3.5) * D2R;
  }
  if (R.tuft) for (const t of R.tuft) t.rotation.z = -(t.userData.base + wig) * D2R;
  if (R.catTail) {
    R.catTail.scale.x = side >= 0 ? Math.max(0.25, side) : Math.min(-0.25, side);
    R.catTail.rotation.z = -wig * 1.4 * D2R * Math.sign(R.catTail.scale.x);
    R.catTail.rotation.y = wig * 0.8 * D2R;
  } else R.tailN.rotation.y = wig * 1.5 * D2R;

  // eyes
  const mood = a.mood || 'happy';
  const asleep = mood === 'asleep', shut = asleep || (a.blink || 0) >= 0.5;
  const grow = mood === 'wow' ? 1.14 : 1.0;
  for (const e of R.eyes) {
    e.sizeN.scale.set(grow * (R.eyeK || 1), grow * (R.eyeK || 1), 1);
    e.open.visible = !shut;
    e.closed.visible = shut;
    e.lid.visible = !shut && mood === 'sleepy';
    e.arcG.rotation.z = asleep ? Math.PI : 0;
    e.arcG.position.y = asleep ? -2 : 2;
    e.look.rotation.set((lookY * 0.15) + (mood === 'sad' ? 0.07 : 0), lookX * 0.2, 0);
  }
  R.brows.forEach((b, i) => { b.visible = mood === 'sad' && !shut; });

  // mouth
  const mo = Math.max(0, Math.min(1, a.mouth || 0));
  if (R.elMouthAt) R.elMouthAt(-44 * side);
  if (R.mouth) {
    const M = R.mouth, openM = mo >= 0.12;
    M.smile.visible = !openM && mood !== 'sad' && mood !== 'wow';
    M.sad.visible = !openM && mood === 'sad';
    M.o.visible = !openM && mood === 'wow';
    M.open.visible = openM;
    if (openM) {
      const rx = 18 + 7 * mo, ry = 5 + 17 * mo;
      M.open.position.y = -ry * 0.45;
      M.openInk.scale.set(rx + 3.4, ry + 3.4, 4);
      M.openIn.scale.set(rx, ry, 4);
      M.tongue.visible = mo > 0.35;
      M.tongue.scale.set(rx * 0.62, ry * 0.36, 3.4);
      M.tongue.position.y = -ry * 0.56;
    }
    if (R.teeth) R.teeth.visible = !openM && mood !== 'sad' && mood !== 'wow';
  }
  if (R.trunk) {
    R.trunk.scale.x = side >= 0 ? 1 : -1;
    R.trunkCurl.rotation.x = -(6 + mo * 14 + (mood === 'wow' ? 14 : 0)) * D2R;
  }
  if (R.beak) {
    R.beakLower.rotation.x = mo * 0.42;
    R.beakLower.position.y = -mo * 5;
    R.beakIn.visible = mo > 0.2;
    R.beakIn.scale.set(30, 6 + mo * 9, 34);
    R.beakIn.position.y = -8 - mo * 8;
  }
}

// ------------------------------------------------------------------ scene ----------
function toDesign(v) {
  v.project(camera);
  return [Math.round(((v.x + 1) / 2 * DW) * 100) / 100, Math.round(((1 - v.y) / 2 * DH) * 100) / 100];
}

export function init(width, height, opts) {
  opts = opts || {};
  OW = width; OH = height;
  canvas = document.getElementById('c');
  MSAA = opts.antialias === false ? 0 : (opts.samples || 4);
  canvas.width = 16; canvas.height = 16;           // everything is drawn into off-screen targets
  renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true, premultipliedAlpha: true, preserveDrawingBuffer: false, powerPreference: 'low-power' });
  renderer.setPixelRatio(1);
  renderer.setSize(16, 16, false);
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.LinearSRGBColorSpace;
  THREE.ColorManagement.enabled = false;
  gl = renderer.getContext();
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(2 * Math.atan(DH / 2 / FOCAL) / D2R, DW / DH, 800, 12000);
  const off = GROUND_Y - DH / 2;
  camera.position.set(0, off * Math.cos(AXIS_PITCH) + FOCAL * Math.sin(AXIS_PITCH), -off * Math.sin(AXIS_PITCH) + FOCAL * Math.cos(AXIS_PITCH));
  camera.rotation.set(-AXIS_PITCH, 0, 0);
  camera.updateMatrixWorld(true);
  camera.updateProjectionMatrix();

  shadowLight = new THREE.DirectionalLight(0xffffff, 1);
  shadowLight.castShadow = true;
  shadowLight.shadow.mapSize.set(1024, 1024);
  renderer.shadowMap.autoUpdate = true;
  const sc = shadowLight.shadow.camera;
  sc.left = -760; sc.right = 760; sc.top = 700; sc.bottom = -500; sc.near = 200; sc.far = 5200;
  shadowLight.shadow.radius = 9; shadowLight.shadow.blurSamples = 16; shadowLight.shadow.bias = -0.0006;
  scene.add(shadowLight); scene.add(shadowLight.target);
  ground = new THREE.Mesh(new THREE.PlaneGeometry(6000, 3000), new THREE.ShadowMaterial({ opacity: 0.3, color: 0x1e1932 }));
  ground.rotation.x = -Math.PI / 2;
  ground.receiveShadow = true;
  ground.frustumCulled = false;
  scene.add(ground);
  setLights({});
  const e = gl.getExtension('WEBGL_debug_renderer_info');
  return { version: gl.getParameter(gl.VERSION), renderer: e ? gl.getParameter(e.UNMASKED_RENDERER_WEBGL) : '?', three: THREE.REVISION };
}

export function setCharacters(specs) {
  for (const [, R] of chars) scene.remove(R.root);
  chars.clear();
  for (const spec of specs) {
    const R = buildCharacter(spec);
    R.root.visible = false;
    scene.add(R.root);
    chars.set(spec.id, R);
  }
  return chars.size;
}

const viewDir = (d) => new THREE.Vector3(...d).normalize().transformDirection(camera.matrixWorldInverse);

export function setLights(p) {
  const L = Object.assign({
    key_dir: [-0.55, 0.62, 0.56], lit: [1.0, 1.0, 1.0], shade1: [0.80, 0.77, 0.90], shade2: [0.66, 0.62, 0.80], bands: [-0.08, -0.6],
    sss: [0.07, 0.025, 0.0], spec: 0.22,
    rim_a: [0.20, 0.78, 0.74], rim_a_dir: [-0.8, 0.25, -0.55], rim_b: [1.0, 0.62, 0.30], rim_b_dir: [0.8, 0.3, -0.5],
    ink: INK, ink_mix: 0.62, dim: [1, 1, 1], outline: 4.0,
    shadow_dir: [-0.22, 1.0, 0.34], shadow_opacity: 0.30, shadow_color: [0.12, 0.10, 0.20], shadow_soft: 9,
  }, p || {});
  U.uKeyDir.value.copy(viewDir(L.key_dir));
  U.uLit.value.set(...L.lit); U.uShade1.value.set(...L.shade1); U.uShade2.value.set(...L.shade2);
  U.uBands.value.set(...L.bands);
  U.uSss.value.set(...L.sss); U.uSpec.value = L.spec;
  U.uRimA.value.set(...L.rim_a); U.uRimADir.value.copy(viewDir(L.rim_a_dir));
  U.uRimB.value.set(...L.rim_b); U.uRimBDir.value.copy(viewDir(L.rim_b_dir));
  UO.uInk.value.set(...L.ink); UO.uInkMix.value = L.ink_mix; UO.uDim.value.set(...L.dim); UO.uThick.value = L.outline;
  const d = new THREE.Vector3(...L.shadow_dir).normalize();
  shadowLight.position.copy(d).multiplyScalar(3000);
  shadowLight.target.position.set(0, 0, 0);
  shadowLight.userData.dir = d;
  shadowLight.shadow.radius = L.shadow_soft;
  ground.material.opacity = L.shadow_opacity;
  ground.material.color.setRGB(...L.shadow_color);
  return true;
}

const _box = new THREE.Box3();
function bounds(R, acc, withShadow) {
  _box.setFromObject(R.root);
  const d = shadowLight.userData.dir;
  const mn = _box.min, mx = _box.max;
  for (let i = 0; i < 8; i++) {
    const p = new THREE.Vector3(i & 1 ? mx.x : mn.x, i & 2 ? mx.y : mn.y, i & 4 ? mx.z : mn.z);
    if (withShadow && p.y > 0) {
      const g = p.clone().addScaledVector(d, -p.y / d.y);
      const sp = toDesign(g);
      acc[0] = Math.min(acc[0], sp[0]); acc[1] = Math.min(acc[1], sp[1]); acc[2] = Math.max(acc[2], sp[0]); acc[3] = Math.max(acc[3], sp[1]);
    }
    const q = toDesign(p);
    acc[0] = Math.min(acc[0], q[0]); acc[1] = Math.min(acc[1], q[1]); acc[2] = Math.max(acc[2], q[0]); acc[3] = Math.max(acc[3], q[1]);
  }
}

function b64(u8) {
  if (u8.toBase64) return u8.toBase64();
  let s = '';
  for (let i = 0; i < u8.length; i += 0x8000) s += String.fromCharCode.apply(null, u8.subarray(i, i + 0x8000));
  return btoa(s);
}

let pix = null, rle = null;
const targets = new Map();
function target(w, h) {
  const key = w + 'x' + h;
  let rt = targets.get(key);
  if (!rt) {
    if (targets.size > 24) { for (const t of targets.values()) t.dispose(); targets.clear(); }
    rt = new THREE.WebGLRenderTarget(w, h, { samples: MSAA, depthBuffer: true, colorSpace: THREE.NoColorSpace });
    targets.set(key, rt);
  }
  return rt;
}
// Render one frame. actors: [{id, x, y, scale, yaw, side, lift, ...pose}]. opts: {shadow, full, raw}
export function renderFrame(actors, opts) {
  opts = opts || {};
  const T = [performance.now()];
  const used = new Set();
  const acc = [1e9, 1e9, -1e9, -1e9];
  const anchors = {};
  ground.visible = opts.shadow !== false;
  actors = actors.map(a => Object.assign({}, POSE_DEFAULTS, a));
  for (const a of actors) {
    const R = chars.get(a.id);
    if (!R) throw new Error('unknown character ' + a.id);
    used.add(a.id);
    R.root.visible = true;
    poseCharacter(R, a);
    R.root.updateMatrixWorld(true);
  }
  for (const [id, R] of chars) if (!used.has(id)) R.root.visible = false;
  for (const a of actors) {
    const R = chars.get(a.id);
    bounds(R, acc, ground.visible);
    const hp = toDesign(R.arms[1].hand.getWorldPosition(new THREE.Vector3()));
    const hn = toDesign(R.arms[-1].hand.getWorldPosition(new THREE.Vector3()));
    const right = a.side >= 0;
    anchors[a.id] = {
      hand_r: right ? hp : hn, hand_l: right ? hn : hp,
      head_top: toDesign(R.loc.headTop.getWorldPosition(new THREE.Vector3())),
      mouth: toDesign(R.loc.mouth.getWorldPosition(new THREE.Vector3())),
      chin: toDesign(R.loc.chin.getWorldPosition(new THREE.Vector3())),
      feet: [a.x, a.y - (a.lift || 0)],
    };
  }
  if (!actors.length) { renderer.render(scene, camera); return { box: [0, 0, 0, 0], anchors, data: '', runs: 0 }; }
  const k = OW / DW, pad = 18;
  let x0 = Math.floor((acc[0] - pad) * k), y0 = Math.floor((acc[1] - pad) * k), x1 = Math.ceil((acc[2] + pad) * k), y1 = Math.ceil((acc[3] + pad) * k);
  if (opts.full) { x0 = 0; y0 = 0; x1 = OW; y1 = OH; }
  x0 = Math.max(0, x0); y0 = Math.max(0, y0); x1 = Math.min(OW, x1); y1 = Math.min(OH, y1);
  const w = Math.max(0, x1 - x0), h = Math.max(0, y1 - y0);
  if (!w || !h) return { box: [0, 0, 0, 0], anchors, data: '', runs: 0 };
  // Rasterise ONLY the characters' box: an off-screen multisampled target the size of the crop
  // (rounded up to 64 px so targets are reused), with the camera's view offset set to that box.
  const rt = target(Math.ceil(w / 64) * 64, Math.ceil(h / 64) * 64);
  camera.setViewOffset(OW, OH, x0, y0, rt.width, rt.height);
  renderer.setRenderTarget(rt);
  renderer.setClearColor(0x000000, 0);
  renderer.clear();
  T.push(performance.now());
  renderer.render(scene, camera);
  if (opts.timing) { gl.finish(); T.push(performance.now()); }
  const n = w * h;
  if (!pix || pix.length < n * 4) { pix = new Uint8Array(n * 4); rle = new Uint32Array(n * 2); }
  renderer.readRenderTargetPixels(rt, 0, rt.height - h, w, h, pix);
  renderer.setRenderTarget(null);
  camera.clearViewOffset();
  T.push(performance.now());
  const px = new Uint32Array(pix.buffer, 0, n);
  let j = 0, cur = px[0], cnt = 1;
  for (let i = 1; i < n; i++) {
    const v = px[i];
    if (v === cur) cnt++;
    else { rle[j++] = cnt; rle[j++] = cur; cur = v; cnt = 1; }
  }
  rle[j++] = cnt; rle[j++] = cur;
  T.push(performance.now());
  const data = b64(new Uint8Array(rle.buffer, 0, j * 4));
  T.push(performance.now());
  const out = { box: [x0, y0, w, h], anchors, data, runs: j / 2 };
  if (opts.timing) out.timing = T.slice(1).map((t, i) => Math.round((t - T[i]) * 10) / 10);
  return out;
}

export const info = { TARGET_H, FIT, GROUND_Y };
