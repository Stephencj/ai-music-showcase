// Standard body MODELS + the measurement system garments are fitted to.
//
// The old Figure pinned every garment to hardcoded pixels, so clothes only
// really fit one silhouette. Here each model is a small set of MEASUREMENTS
// (shoulders / waist / hips / torso / arms / legs / head) in the 200×340
// viewBox, and garments are authored as functions of a model's ANCHORS — so a
// top drawn once fits every model, and adding a model auto-fits the catalog.

export type Gender = "girl" | "boy";

export interface Model {
  id: string;
  gender: Gender;
  build: string;          // "slim" | "athletic"
  label: string;
  head: { cx: number; cy: number; r: number };
  neckW: number;                       // half-width of the neck
  shoulder: { y: number; w: number };  // w = half-width from centre (cx=100)
  waist: { y: number; w: number };
  hip: { y: number; w: number };
  hemY: number;                        // crotch line — where torso/tops end
  arm: { thickness: number; wristY: number; wristIn: number };  // wristIn = inset from shoulder x
  leg: { footY: number; gap: number; thickness: number };       // gap = half-gap between legs
}

const CX = 100;

// Cute/chibi proportions: a big head over a short, chunky body. The head art
// (face/hair, designed at r=38, cy=76) is scaled to `head` by Figure, so a
// bigger head stays consistent. Build varies shoulders/waist/hips/limb chunk.
export const MODELS: Record<string, Model> = {
  girl_slim: {
    id: "girl_slim", gender: "girl", build: "slim", label: "Slim",
    head: { cx: CX, cy: 62, r: 51 }, neckW: 7,
    shoulder: { y: 128, w: 28 }, waist: { y: 156, w: 23 }, hip: { y: 182, w: 31 },
    hemY: 188, arm: { thickness: 12, wristY: 180, wristIn: 5 },
    leg: { footY: 250, gap: 3, thickness: 17 },
  },
  girl_athletic: {
    id: "girl_athletic", gender: "girl", build: "athletic", label: "Athletic",
    head: { cx: CX, cy: 62, r: 51 }, neckW: 8,
    shoulder: { y: 126, w: 33 }, waist: { y: 156, w: 28 }, hip: { y: 184, w: 34 },
    hemY: 190, arm: { thickness: 14, wristY: 182, wristIn: 6 },
    leg: { footY: 250, gap: 3, thickness: 19 },
  },
  boy_slim: {
    id: "boy_slim", gender: "boy", build: "slim", label: "Slim",
    head: { cx: CX, cy: 62, r: 51 }, neckW: 8,
    shoulder: { y: 128, w: 31 }, waist: { y: 158, w: 28 }, hip: { y: 184, w: 30 },
    hemY: 190, arm: { thickness: 14, wristY: 182, wristIn: 6 },
    leg: { footY: 250, gap: 3, thickness: 19 },
  },
  boy_athletic: {
    id: "boy_athletic", gender: "boy", build: "athletic", label: "Athletic",
    head: { cx: CX, cy: 61, r: 52 }, neckW: 10,
    shoulder: { y: 126, w: 39 }, waist: { y: 160, w: 33 }, hip: { y: 186, w: 34 },
    hemY: 192, arm: { thickness: 16, wristY: 184, wristIn: 7 },
    leg: { footY: 250, gap: 3, thickness: 21 },
  },
};

export const MODEL_IDS = Object.keys(MODELS);
export const modelsFor = (g: Gender) => MODEL_IDS.map((id) => MODELS[id]).filter((m) => m.gender === g);
export const resolveModel = (id?: string, gender?: Gender): Model =>
  (id && MODELS[id]) || modelsFor(gender || "girl")[0] || MODELS.girl_slim;

// ── Derived anchor points every garment can build from ──────────────────────
export interface Anchors {
  cx: number;
  shoulderL: [number, number]; shoulderR: [number, number];
  waistL: [number, number]; waistR: [number, number];
  hipL: [number, number]; hipR: [number, number];
  hemL: [number, number]; hemR: [number, number];
  wristL: [number, number]; wristR: [number, number];
  hemY: number; shoulderY: number;
  legInnerX: number;                         // half-gap
  legOuterL: number; legOuterR: number;      // outer edge of each leg block
  footY: number;
}

export function anchors(m: Model): Anchors {
  const hemW = (m.waist.w + m.hip.w) / 2;    // hem sits between waist and hip
  return {
    cx: CX,
    shoulderL: [CX - m.shoulder.w, m.shoulder.y], shoulderR: [CX + m.shoulder.w, m.shoulder.y],
    waistL: [CX - m.waist.w, m.waist.y], waistR: [CX + m.waist.w, m.waist.y],
    hipL: [CX - m.hip.w, m.hip.y], hipR: [CX + m.hip.w, m.hip.y],
    hemL: [CX - hemW, m.hemY], hemR: [CX + hemW, m.hemY],
    wristL: [CX - m.shoulder.w + m.arm.wristIn, m.arm.wristY],
    wristR: [CX + m.shoulder.w - m.arm.wristIn, m.arm.wristY],
    hemY: m.hemY, shoulderY: m.shoulder.y,
    legInnerX: m.leg.gap,
    legOuterL: CX - m.leg.thickness - m.leg.gap, legOuterR: CX + m.leg.thickness + m.leg.gap,
    footY: m.leg.footY,
  };
}

// ── Path builders (garments call these so they fit any model) ───────────────
const P = (x: number, y: number) => `${x.toFixed(1)} ${y.toFixed(1)}`;

/** The fitted torso silhouette shoulder→waist→hip→hem (used for skin + tops). */
export function torsoPath(m: Model): string {
  const a = anchors(m);
  const [slx, sly] = a.shoulderL, [srx, sry] = a.shoulderR;
  const [wlx, wly] = a.waistL, [wrx, wry] = a.waistR;
  const [hlx, hly] = a.hipL, [hrx] = a.hipR;
  const [hemlx, hemy] = a.hemL, [hemrx] = a.hemR;
  const cwl = (sly + wly) / 2, cwr = (wly + hly) / 2;
  return [
    `M${P(slx, sly)}`,
    `C${P(slx - 2, cwl)} ${P(wlx - 1, cwl)} ${P(wlx, wly)}`,           // shoulder→waist (left)
    `C${P(wlx - 1, cwr)} ${P(hlx + 1, cwr)} ${P(hlx, hly)}`,           // waist→hip (left)
    `L${P(hemlx, hemy)} L${P(hemrx, hemy)}`,                           // hem
    `L${P(hrx, hly)}`,                                                 // up to right hip
    `C${P(wrx + 1, cwr)} ${P(wrx + 1, cwr)} ${P(wrx, wry)}`,           // hip→waist (right)
    `C${P(wrx + 1, cwl)} ${P(srx + 2, cwl)} ${P(srx, sry)}`,           // waist→shoulder (right)
    "Z",
  ].join(" ");
}

/** One arm (skin), from the shoulder socket down to the wrist. */
export function armPath(m: Model, side: "L" | "R"): string {
  const a = anchors(m);
  const [sx, sy] = side === "L" ? a.shoulderL : a.shoulderR;
  const [wx, wy] = side === "L" ? a.wristL : a.wristR;
  const t = m.arm.thickness, dir = side === "L" ? -1 : 1;
  return [
    `M${P(sx, sy)}`,
    `C${P(sx + dir * t, sy + 18)} ${P(wx + dir * t, wy - 18)} ${P(wx + dir * (t - 2), wy)}`,
    `C${P(wx, wy + 4)} ${P(wx - dir, wy + 4)} ${P(wx - dir * 2, wy)}`,
    `C${P(wx, wy - 20)} ${P(sx - dir * 2, sy + 20)} ${P(sx, sy)}`,
    "Z",
  ].join(" ");
}

/** Short sleeve cap at the shoulder. */
export function sleeveShort(m: Model, side: "L" | "R"): string {
  const a = anchors(m);
  const [sx, sy] = side === "L" ? a.shoulderL : a.shoulderR;
  const dir = side === "L" ? -1 : 1, t = m.arm.thickness + 3;
  return `M${P(sx, sy)} C${P(sx + dir * t, sy + 6)} ${P(sx + dir * t, sy + 26)} ${P(sx + dir * (t - 3), sy + 32)} L${P(sx - dir * 2, sy + 24)} C${P(sx - dir, sy + 12)} ${P(sx, sy + 4)} ${P(sx, sy)} Z`;
}

/** Long sleeve down the arm. */
export function sleeveLong(m: Model, side: "L" | "R"): string {
  const a = anchors(m);
  const [sx, sy] = side === "L" ? a.shoulderL : a.shoulderR;
  const [wx, wy] = side === "L" ? a.wristL : a.wristR;
  const dir = side === "L" ? -1 : 1, t = m.arm.thickness + 3;
  return `M${P(sx, sy)} C${P(sx + dir * t, sy + 16)} ${P(wx + dir * t, wy - 16)} ${P(wx + dir * (t - 2), wy + 3)} L${P(wx - dir * 2, wy + 3)} C${P(wx - dir, wy - 16)} ${P(sx - dir * 2, sy + 18)} ${P(sx, sy)} Z`;
}

/** Both legs (skin), from the hem to the feet. */
export function legsPath(m: Model): string {
  const a = anchors(m);
  const t = m.leg.thickness, g = a.legInnerX, ty = a.hemY - 4, fy = a.footY;
  const L = `M${P(a.cx - g - t, ty)} L${P(a.cx - g - t + 1, fy)} C${P(a.cx - g - t + 1, fy + 4)} ${P(a.cx - g - 1, fy + 4)} ${P(a.cx - g - 1, fy)} L${P(a.cx - g, ty)} Z`;
  const R = `M${P(a.cx + g + t, ty)} L${P(a.cx + g + t - 1, fy)} C${P(a.cx + g + t - 1, fy + 4)} ${P(a.cx + g + 1, fy + 4)} ${P(a.cx + g + 1, fy)} L${P(a.cx + g, ty)} Z`;
  return `${L} ${R}`;
}

/** Trousers fitted to the hips + legs. `crop` shortens them (shorts). */
export function pantsPath(m: Model, crop = 0): string {
  const a = anchors(m);
  const [hlx] = a.hipL, [hrx] = a.hipR;
  const t = m.leg.thickness, g = a.legInnerX;
  const fy = a.footY - crop, waistY = a.hemY - 6;
  const outL = a.cx - g - t, outR = a.cx + g + t;
  return [
    `M${P(hlx, waistY)}`,
    `L${P(outL, fy)} L${P(outL + t - 1, fy)} L${P(a.cx - g, waistY + (a.hipL[1] - waistY) * 0.7)}`,
    `L${P(a.cx + g, waistY + (a.hipL[1] - waistY) * 0.7)} L${P(outR - t + 1, fy)} L${P(outR, fy)}`,
    `L${P(hrx, waistY)} Z`,
  ].join(" ");
}

// ── Head-fitted HAIR builders (hair tracks the head circle, like garments
//    track the body) ─────────────────────────────────────────────────────────
export interface HeadDim { cx: number; cy: number; r: number; }
const HP = (x: number, y: number) => `${x.toFixed(1)} ${y.toFixed(1)}`;

/** A hair cap fitted to the head: fully covers the crown (control points sit
 *  well above the head so the cubic doesn't sag and expose skin) down to a
 *  forehead hairline with soft scalloped bangs. `hairlineF`/`volumeF` are
 *  fractions of the head radius. */
export function hairCap(h: HeadDim, hairlineF = 0.30, volumeF = 0.18): string {
  const { cx, cy, r } = h;
  // Rounded, WIDE crown (two cubics meeting at a flat top) so the head reads
  // round, not a cone. Top sits just above the head so the crown is covered.
  const topY = cy - r * (1.02 + volumeF);
  const sx = r * 1.08;
  const midY = cy + r * 0.3;
  const hl = cy - r * hairlineF;
  const up = r * 0.12, dn = r * 0.05;
  return [
    `M${HP(cx - sx, midY)}`,
    `C${HP(cx - sx, cy - r * 0.86)} ${HP(cx - r * 0.5, topY)} ${HP(cx, topY)}`,     // left → flat top
    `C${HP(cx + r * 0.5, topY)} ${HP(cx + sx, cy - r * 0.86)} ${HP(cx + sx, midY)}`, // right
    `C${HP(cx + sx, hl + dn)} ${HP(cx + r * 0.6, hl - up)} ${HP(cx + r * 0.42, hl + dn)}`,
    `C${HP(cx + r * 0.3, hl - up)} ${HP(cx + r * 0.14, hl - up)} ${HP(cx, hl + dn)}`,
    `C${HP(cx - r * 0.14, hl - up)} ${HP(cx - r * 0.3, hl - up)} ${HP(cx - r * 0.42, hl + dn)}`,
    `C${HP(cx - r * 0.6, hl - up)} ${HP(cx - sx, hl + dn)} ${HP(cx - sx, midY)} Z`,
  ].join(" ");
}

/** Face-framing locks down each temple to `dropF`·r below the head centre. */
export function hairSides(h: HeadDim, dropF = 0.7): string {
  const { cx, cy, r } = h;
  const topY = cy - r * 0.2, botY = cy + r * dropF;
  const oL = cx - r * 1.04, iL = cx - r * 0.82;
  const oR = cx + r * 1.04, iR = cx + r * 0.82;
  return `M${HP(oL, topY)} C${HP(oL - r * 0.12, cy)} ${HP(oL, botY)} ${HP(iL, botY)} C${HP(iL - r * 0.02, cy)} ${HP(iL, topY)} ${HP(oL, topY)} Z `
    + `M${HP(oR, topY)} C${HP(oR + r * 0.12, cy)} ${HP(oR, botY)} ${HP(iR, botY)} C${HP(iR + r * 0.02, cy)} ${HP(iR, topY)} ${HP(oR, topY)} Z`;
}

/** Long hair falling down the BACK (drawn behind the body), reaching `lenY`.
 *  A SOLID mass so it covers behind the head AND the neck (no skin gap). */
export function hairBack(h: HeadDim, lenY: number): string {
  const { cx, cy, r } = h;
  const sx = r * 1.16, top = cy - r * 1.5, bx = r * 1.02;
  return [
    `M${HP(cx - sx, cy - r * 0.2)}`,
    `C${HP(cx - sx, top)} ${HP(cx + sx, top)} ${HP(cx + sx, cy - r * 0.2)}`,       // over the crown
    `C${HP(cx + sx + 3, cy + r * 0.9)} ${HP(cx + bx + 4, lenY - 26)} ${HP(cx + bx, lenY)}`, // right side flows down
    `C${HP(cx + bx, lenY + 16)} ${HP(cx - bx, lenY + 16)} ${HP(cx - bx, lenY)}`,   // rounded bottom
    `C${HP(cx - bx - 4, lenY - 26)} ${HP(cx - sx - 3, cy + r * 0.9)} ${HP(cx - sx, cy - r * 0.2)} Z`, // left side up
  ].join(" ");
}

/** A glossy sheen streak across the upper hair (draw in a lightened colour). */
export function hairShine(h: HeadDim): string {
  const { cx, cy, r } = h;
  return `M${HP(cx - r * 0.55, cy - r * 0.5)} Q${HP(cx - r * 0.15, cy - r * 1.02)} ${HP(cx + r * 0.5, cy - r * 0.62)}`;
}

/** A-line skirt from the hips. */
export function skirtPath(m: Model, len = 52): string {
  const a = anchors(m);
  const [hlx] = a.hipL, [hrx] = a.hipR;
  const waistY = a.hemY - 6, hemY = waistY + len;
  return `M${P(hlx, waistY)} L${P(a.cx - m.hip.w - 8, hemY)} L${P(a.cx + m.hip.w + 8, hemY)} L${P(hrx, waistY)} Z`;
}
