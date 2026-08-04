// The dress-up character — a full-body layered SVG on a 200×340 viewBox. The
// body is built from a MODEL's measurements (see models.ts) and every garment
// is drawn against that model's ANCHORS, so clothes fit each standard model
// (slim/athletic × girl/boy) instead of being pinned to one silhouette. Head-
// anchored items (hair/hats/glasses/face) sit on the shared head circle.
import { type Member, skinHex, hairHex, colorHex } from "./wardrobe";
import {
  type Model, type HeadDim, resolveModel, anchors, torsoPath, armPath,
  sleeveShort, sleeveLong, legsPath, pantsPath, skirtPath,
  hairCap, hairSides, hairBack, hairShine,
} from "./models";

const EYE_Y = 83;

const darker = (hex: string, f = 0.78) => {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * f), g = Math.round(((n >> 8) & 255) * f), b = Math.round((n & 255) * f);
  return `rgb(${r},${g},${b})`;
};
const lighten = (hex: string, f = 1.4) => {
  const n = parseInt(hex.slice(1), 16);
  const cl = (v: number) => Math.min(255, Math.round(v * f));
  return `rgb(${cl((n >> 16) & 255)},${cl((n >> 8) & 255)},${cl(n & 255)})`;
};

// Hair is authored against the head circle (design coords cx100 cy76 r38, so
// x62–138, y38–114). Cute style: a soft PUFFY crown with a scalloped FRINGE of
// rounded bangs to a low hairline (so no bald forehead), + side locks.
//   fringe(hl): puffy dome + soft bangs dipping to y≈hl at the brow.
//   sideLock(x,dir): a soft lock down the temple past the cheek.
// Hair is built from the HEAD circle's dimensions (like garments from body
// measurements): hairCap covers the crown to a forehead hairline, hairSides
// frames the face, hairBack falls down the back. Everything scales with the
// model's head automatically, so size/fit always matches.
function Hair({ id, color, layer, head }: { id: string; color: string; layer: "back" | "front"; head: HeadDim }) {
  const back = layer === "back";
  const { cx, cy, r } = head;
  const backY = (f: number) => cy + r * f;   // absolute y for the back-hair length
  const R = (fx: number, fy: number) => [cx + r * fx, cy + r * fy] as const;
  switch (id) {
    case "buzz":
      return back ? null : <path d={hairCap(head, 0.4, 0.04)} fill={color} opacity={0.9} />;
    case "short":
      return back ? null : <path d={hairCap(head, 0.34, 0.16)} fill={color} />;
    case "bob":
      if (back) return <path d={hairBack(head, backY(1.15))} fill={color} />;
      return <g fill={color}><path d={hairCap(head, 0.32, 0.18)} /><path d={hairSides(head, 1.3)} /></g>;
    case "long":
      if (back) return <path d={hairBack(head, backY(2.5))} fill={color} />;
      return <g fill={color}><path d={hairCap(head, 0.32, 0.2)} /><path d={hairSides(head, 0.9)} /></g>;
    case "wavy":
      if (back) return <path d={hairBack(head, backY(2.7))} fill={color} />;
      return <g fill={color}><path d={hairCap(head, 0.32, 0.22)} /><path d={hairSides(head, 0.95)} /></g>;
    case "curly":
      if (back) return (<g fill={color}>{([[-1, -0.35], [1, -0.35], [-1.12, 0.25], [1.12, 0.25], [-0.95, 0.8], [0.95, 0.8]] as const).map((f, i) => { const [x, y] = R(f[0], f[1]); return <circle key={i} cx={x} cy={y} r={r * 0.34} />; })}</g>);
      return (<g fill={color}>{([[-0.6, -0.78], [-0.28, -0.92], [0, -0.98], [0.28, -0.92], [0.6, -0.78], [-0.9, -0.35], [0.9, -0.35]] as const).map((f, i) => { const [x, y] = R(f[0], f[1]); return <circle key={i} cx={x} cy={y} r={r * 0.3} />; })}</g>);
    case "pony": {
      const [ax, ay] = R(0.7, -0.15), [bx, by] = R(0.55, -0.15);
      if (back) return <path d={`M${ax} ${ay} C${cx + r * 1.75} ${cy} ${cx + r * 1.7} ${backY(2.4)} ${cx + r * 0.85} ${backY(2.6)} C${cx + r * 1.3} ${cy + r} ${bx} ${cy} ${bx} ${by} Z`} fill={color} />;
      return <g fill={color}><path d={hairCap(head, 0.32, 0.2)} /><path d={hairSides(head, 0.85)} /></g>;
    }
    case "pigtails": {
      const [lx, ly] = R(-1.15, 0.5), [rx, ry] = R(1.15, 0.5);
      if (back) return <g fill={color}><circle cx={lx} cy={ly} r={r * 0.42} /><circle cx={rx} cy={ry} r={r * 0.42} /></g>;
      return <g fill={color}><path d={hairCap(head, 0.32, 0.2)} /><path d={hairSides(head, 0.8)} /></g>;
    }
    case "bun": {
      const [bx, by] = R(0, -1.35);
      if (back) return null;
      return <g fill={color}><circle cx={bx} cy={by} r={r * 0.32} /><path d={hairCap(head, 0.32, 0.14)} /></g>;
    }
    case "braids": {
      const braid = (dir: number) => `M${cx + dir * r * 0.72} ${cy + r * 0.1} C${cx + dir * r * 1.1} ${cy + r} ${cx + dir * r * 1.0} ${backY(2.7)} ${cx + dir * r * 0.68} ${backY(2.9)} C${cx + dir * r * 0.46} ${backY(2.1)} ${cx + dir * r * 0.58} ${cy + r} ${cx + dir * r * 0.48} ${cy + r * 0.2} Z`;
      if (back) return <g fill={color}><path d={braid(-1)} /><path d={braid(1)} /></g>;
      return <path d={hairCap(head, 0.32, 0.16)} fill={color} />;
    }
    case "afro":
      if (back) return <circle cx={cx} cy={cy - r * 0.35} r={r * 1.36} fill={color} />;
      return null;
    case "mohawk": {
      const [x0, y0] = R(-0.22, -0.6), [x1] = R(0.22, -0.6);
      if (back) return null;
      return <g fill={color}><path d={hairCap(head, 0.5, 0.0)} opacity="0.5" /><path d={`M${x0} ${y0} C${x0} ${cy - r * 1.7} ${x1} ${cy - r * 1.7} ${x1} ${y0} L${x1} ${cy - r * 0.3} L${x0} ${cy - r * 0.3} Z`} /></g>;
    }
    case "spiky": {
      const s = (fx: number, fy: number) => { const [x, y] = R(fx, fy); return `${x} ${y}`; };
      if (back) return null;
      return <g fill={color}><path d={hairCap(head, 0.36, 0.1)} /><path d={`M${s(-1, -0.7)} L${s(-0.7, -1.65)} L${s(-0.35, -0.9)} L${s(0, -1.85)} L${s(0.35, -0.9)} L${s(0.7, -1.65)} L${s(1, -0.7)} C${s(0.5, -1.05)} ${s(-0.5, -1.05)} ${s(-1, -0.7)} Z`} /></g>;
    }
    default:
      return back ? null : <path d={hairCap(head, 0.32, 0.18)} fill={color} />;
  }
}

function Hat({ id, color }: { id: string; color: string }) {
  const d = darker(color);
  switch (id) {
    case "beanie": return <g fill={color}><path d="M60 50 C60 24 140 24 140 50 L140 56 L60 56 Z" /><rect x="60" y="52" width="80" height="8" rx="3" fill={d} /></g>;
    case "cap": return <g fill={color}><path d="M62 48 C62 24 138 24 138 48 L62 48 Z" /><path d="M62 48 L36 56 L62 58 Z" fill={d} /></g>;
    case "party": return <g><path d="M100 8 L82 52 L118 52 Z" fill={color} /><circle cx="100" cy="8" r="5" fill="#fde047" /></g>;
    case "crown": return <path d="M70 50 L74 22 L86 40 L100 18 L114 40 L126 22 L130 50 Z" fill="#fde047" stroke="#eab308" strokeWidth="1.5" />;
    case "flower": return <g><g fill={color}><circle cx="68" cy="40" r="7" /><circle cx="80" cy="34" r="7" /><circle cx="80" cy="46" r="7" /><circle cx="92" cy="40" r="7" /></g><circle cx="80" cy="40" r="4" fill="#fde047" /></g>;
    case "bow": return <g fill={color}><path d="M84 30 L70 22 L70 44 L84 36 Z" /><path d="M96 30 L110 22 L110 44 L96 36 Z" /><circle cx="90" cy="33" r="5" fill={d} /></g>;
    case "tophat": return <g fill={color}><ellipse cx="100" cy="44" rx="34" ry="6" /><rect x="80" y="10" width="40" height="36" rx="2" /><rect x="80" y="36" width="40" height="6" fill="#ef4444" /></g>;
    case "cowboy": return <g fill={color}><ellipse cx="100" cy="48" rx="42" ry="8" /><path d="M76 48 C76 22 124 22 124 48 C116 36 84 36 76 48 Z" /></g>;
    case "ears": return <g><g fill={color}><path d="M72 46 L80 16 L94 44 Z" /><path d="M128 46 L120 16 L106 44 Z" /></g><g fill="#fbcfe8"><path d="M78 42 L82 26 L88 42 Z" /><path d="M122 42 L118 26 L112 42 Z" /></g></g>;
    default: return null;
  }
}

function Glasses({ id }: { id: string }) {
  const f = "#1f2937";
  switch (id) {
    case "round": return <g fill="none" stroke={f} strokeWidth="2.5"><circle cx="86" cy={EYE_Y} r="9" /><circle cx="114" cy={EYE_Y} r="9" /><line x1="95" y1={EYE_Y} x2="105" y2={EYE_Y} /></g>;
    case "square": return <g fill="none" stroke={f} strokeWidth="2.5"><rect x="76" y={EYE_Y - 8} width="18" height="16" rx="3" /><rect x="106" y={EYE_Y - 8} width="18" height="16" rx="3" /><line x1="94" y1={EYE_Y} x2="106" y2={EYE_Y} /></g>;
    case "heart": return <g fill="#ec4899"><text x="86" y={EYE_Y + 6} fontSize="18" textAnchor="middle">♥</text><text x="114" y={EYE_Y + 6} fontSize="18" textAnchor="middle">♥</text></g>;
    case "star": return <g fill="#facc15"><text x="86" y={EYE_Y + 6} fontSize="18" textAnchor="middle">★</text><text x="114" y={EYE_Y + 6} fontSize="18" textAnchor="middle">★</text></g>;
    case "sun": return <g fill={f}><rect x="75" y={EYE_Y - 7} width="20" height="13" rx="5" /><rect x="105" y={EYE_Y - 7} width="20" height="13" rx="5" /><line x1="95" y1={EYE_Y - 3} x2="105" y2={EYE_Y - 3} stroke={f} strokeWidth="2.5" /></g>;
    default: return null;
  }
}

// Chest region used to clip a printed shirt photo (scaled to the model).
function chestRect(m: Model) {
  const w = Math.round(m.waist.w * 1.1);
  return { x: 100 - w / 2, y: m.shoulder.y + 12, w, h: 34 };
}

// Tops covers the torso (shoulder→hem); dress/gown flare into a skirt.
function Top({ id, color, m }: { id: string; color: string; m: Model }) {
  const d = darker(color);
  const body = torsoPath(m);
  const a = anchors(m);
  const sS = <>{[...(["L", "R"] as const)].map((s) => <path key={s} d={sleeveShort(m, s)} fill={color} />)}</>;
  const sL = <>{[...(["L", "R"] as const)].map((s) => <path key={s} d={sleeveLong(m, s)} fill={color} />)}</>;
  const neckLo = <path d={`M${a.cx - 12} ${a.shoulderY - 2} Q${a.cx} ${a.shoulderY + 10} ${a.cx + 12} ${a.shoulderY - 2}`} fill="none" stroke={d} strokeWidth="2" opacity="0.5" />;
  switch (id) {
    case "tank":
      return <g><path d={body} fill={color} /><g stroke={color} strokeWidth="5" strokeLinecap="round"><line x1={a.cx - 12} y1={a.shoulderY} x2={a.cx - 8} y2={a.shoulderY - 8} /><line x1={a.cx + 12} y1={a.shoulderY} x2={a.cx + 8} y2={a.shoulderY - 8} /></g></g>;
    case "long":
      return <g>{sL}<path d={body} fill={color} />{neckLo}</g>;
    case "hoodie":
      return <g><path d={`M${a.cx - 22} ${a.shoulderY - 4} C${a.cx - 22} ${a.shoulderY - 20} ${a.cx + 22} ${a.shoulderY - 20} ${a.cx + 22} ${a.shoulderY - 4} C${a.cx + 10} ${a.shoulderY - 10} ${a.cx - 10} ${a.shoulderY - 10} ${a.cx - 22} ${a.shoulderY - 4} Z`} fill={d} />{sL}<path d={body} fill={color} /><rect x={a.cx - 16} y={a.hemY - 34} width="32" height="22" rx="5" fill={d} /><line x1={a.cx} y1={a.shoulderY + 4} x2={a.cx} y2={a.hemY - 38} stroke={d} strokeWidth="2" /></g>;
    case "jacket":
      return <g>{sL}<path d={body} fill={color} /><path d={`M${a.cx} ${a.shoulderY} L${a.cx - 12} ${a.shoulderY + 6} L${a.cx - 6} ${a.hemY - 4} L${a.cx} ${a.hemY - 4} Z`} fill={d} /><path d={`M${a.cx} ${a.shoulderY} L${a.cx + 12} ${a.shoulderY + 6} L${a.cx + 6} ${a.hemY - 4} L${a.cx} ${a.hemY - 4} Z`} fill={darker(color, 0.62)} /></g>;
    case "stripes":
      return <g>{sS}<path d={body} fill={color} /><clipPath id={`t-${m.id}`}><path d={body} /></clipPath><g clipPath={`url(#t-${m.id})`} stroke="#f8fafc" strokeWidth="5" opacity="0.9"><line x1="50" y1={a.shoulderY + 18} x2="150" y2={a.shoulderY + 18} /><line x1="50" y1={a.shoulderY + 36} x2="150" y2={a.shoulderY + 36} /><line x1="50" y1={a.shoulderY + 54} x2="150" y2={a.shoulderY + 54} /></g></g>;
    case "jersey":
      return <g><path d={body} fill={color} />{sS}<text x={a.cx} y={(a.shoulderY + a.hemY) / 2 + 6} fontSize="24" fontWeight="700" fill="#f8fafc" textAnchor="middle">7</text></g>;
    case "dress":
      return <g>{sS}<path d={body} fill={color} /><path d={skirtPath(m, 56)} fill={color} /></g>;
    case "gown":
      return <g><path d={body} fill={color} /><path d={skirtPath(m, 96)} fill={color} /><g fill="#fef9c3" opacity="0.9"><circle cx={a.cx - 14} cy="236" r="2" /><circle cx={a.cx + 12} cy="256" r="2" /><circle cx={a.cx - 2} cy="272" r="2" /><circle cx={a.cx + 20} cy="230" r="2" /></g></g>;
    case "crop": {
      const [slx, sly] = a.shoulderL, [srx, sry] = a.shoulderR;
      const [wlx, wy] = a.waistL, [wrx] = a.waistR, cw = (sly + wy) / 2;
      return <g>{sS}<path d={`M${slx} ${sly} C${slx - 2} ${cw} ${wlx - 1} ${cw} ${wlx} ${wy + 8} L${wrx} ${wy + 8} C${wrx + 1} ${cw} ${srx + 2} ${cw} ${srx} ${sry} Z`} fill={color} /></g>;
    }
    case "sweater":
      return <g>{sL}<path d={body} fill={color} /><rect x={a.hemL[0]} y={a.hemY - 8} width={a.hemR[0] - a.hemL[0]} height="9" fill={d} /><path d={`M${a.cx - 13} ${a.shoulderY - 2} Q${a.cx} ${a.shoulderY + 12} ${a.cx + 13} ${a.shoulderY - 2}`} fill="none" stroke={d} strokeWidth="4" /></g>;
    case "flannel":
      return <g>{sL}<path d={body} fill={color} /><clipPath id={`fl-${m.id}`}><path d={body} /></clipPath><g clipPath={`url(#fl-${m.id})`} stroke={d} strokeWidth="3" opacity="0.6"><line x1="50" y1={a.shoulderY + 14} x2="150" y2={a.shoulderY + 14} /><line x1="50" y1={a.shoulderY + 32} x2="150" y2={a.shoulderY + 32} /><line x1="50" y1={a.shoulderY + 50} x2="150" y2={a.shoulderY + 50} /><line x1={a.cx - 15} y1={a.shoulderY} x2={a.cx - 15} y2={a.hemY} /><line x1={a.cx + 15} y1={a.shoulderY} x2={a.cx + 15} y2={a.hemY} /></g></g>;
    case "blazer":
      return <g>{sL}<path d={body} fill={color} /><path d={`M${a.cx} ${a.shoulderY} L${a.cx - 13} ${a.shoulderY + 4} L${a.cx - 7} ${a.shoulderY + 30} L${a.cx} ${a.shoulderY + 20} Z`} fill={d} /><path d={`M${a.cx} ${a.shoulderY} L${a.cx + 13} ${a.shoulderY + 4} L${a.cx + 7} ${a.shoulderY + 30} L${a.cx} ${a.shoulderY + 20} Z`} fill={d} /><circle cx={a.cx} cy={a.shoulderY + 36} r="1.8" fill={d} /><circle cx={a.cx} cy={a.shoulderY + 46} r="1.8" fill={d} /></g>;
    case "puffer":
      return <g>{sL}<path d={body} fill={color} /><clipPath id={`pf-${m.id}`}><path d={body} /></clipPath><g clipPath={`url(#pf-${m.id})`} stroke={d} strokeWidth="2.4" opacity="0.5"><line x1="40" y1={a.shoulderY + 16} x2="160" y2={a.shoulderY + 16} /><line x1="40" y1={a.shoulderY + 32} x2="160" y2={a.shoulderY + 32} /><line x1="40" y1={a.shoulderY + 48} x2="160" y2={a.shoulderY + 48} /></g></g>;
    case "overalls":
      return <g>{sS}<path d={body} fill="#e9edf2" /><path d={`M${a.cx - m.waist.w} ${m.waist.y} L${a.hipL[0]} ${a.hemY} L${a.hipR[0]} ${a.hemY} L${a.cx + m.waist.w} ${m.waist.y} Z`} fill={color} /><rect x={a.cx - 11} y={m.waist.y + 2} width="22" height="15" rx="2" fill={darker(color, 0.85)} /><path d={`M${a.cx - 14} ${a.shoulderY} L${a.cx - 9} ${a.shoulderY} L${a.cx - 9} ${m.waist.y + 4} L${a.cx - 14} ${m.waist.y + 4} Z`} fill={color} /><path d={`M${a.cx + 14} ${a.shoulderY} L${a.cx + 9} ${a.shoulderY} L${a.cx + 9} ${m.waist.y + 4} L${a.cx + 14} ${m.waist.y + 4} Z`} fill={color} /></g>;
    default: // tee
      return <g>{sS}<path d={body} fill={color} />{neckLo}</g>;
  }
}

function Bottom({ id, color, m }: { id: string; color: string; m: Model }) {
  const d = darker(color);
  const a = anchors(m);
  switch (id) {
    case "shorts":
      return <path d={pantsPath(m, 60)} fill={color} />;
    case "skirt":
      return <g><path d={skirtPath(m, 50)} fill={color} /><path d={`M${a.cx - m.hip.w - 6} ${a.hemY - 6 + 50} L${a.cx + m.hip.w + 6} ${a.hemY - 6 + 50}`} stroke={d} strokeWidth="2" /></g>;
    case "tutu":
      return <path d={skirtPath(m, 30)} fill={color} opacity="0.92" />;
    case "leggings":
      return <path d={pantsPath(m)} fill={color} />;
    case "none":
      return null;
    case "jeans":
      return <g><path d={pantsPath(m)} fill={color} /><line x1={a.cx} y1={a.hemY - 4} x2={a.cx} y2={a.footY - 6} stroke={d} strokeWidth="1.5" /></g>;
    case "cargo": {
      const outL = a.cx - a.legInnerX - m.leg.thickness, outR = a.cx + a.legInnerX + m.leg.thickness, py = a.hemY + 26;
      return <g><path d={pantsPath(m)} fill={color} /><rect x={outL} y={py} width="9" height="13" rx="2" fill={d} /><rect x={outR - 9} y={py} width="9" height="13" rx="2" fill={d} /></g>;
    }
    case "joggers": {
      const t = m.leg.thickness, g = a.legInnerX, fy = a.footY;
      return <g><path d={pantsPath(m)} fill={color} /><rect x={a.cx - g - t} y={fy - 14} width={t} height="8" rx="2" fill={d} /><rect x={a.cx + g} y={fy - 14} width={t} height="8" rx="2" fill={d} /></g>;
    }
    case "midiskirt":
      return <g><path d={skirtPath(m, 92)} fill={color} /></g>;
    default: // pants
      return <path d={pantsPath(m)} fill={color} />;
  }
}

function Shoes({ id, color, m }: { id: string; color: string; m: Model }) {
  const a = anchors(m);
  const d = darker(color);
  const fl = a.cx - a.legInnerX - m.leg.thickness / 2;
  const fr = a.cx + a.legInnerX + m.leg.thickness / 2;
  const y = a.footY;
  const feet = [fl, fr];
  switch (id) {
    case "barefoot": return null;
    case "boots":
      return <g fill={color}>{feet.map((fx, i) => <g key={i}><path d={`M${fx - 9} ${y - 34} L${fx - 9} ${y + 2} C${fx - 9} ${y + 6} ${fx + 9} ${y + 6} ${fx + 9} ${y + 2} L${fx + 9} ${y - 34} Z`} /><rect x={fx - 10} y={y} width="20" height="6" rx="2" fill={d} /></g>)}</g>;
    case "sandals":
      return <g fill={color}>{feet.map((fx, i) => <g key={i}><ellipse cx={fx} cy={y + 4} rx="11" ry="5" /><path d={`M${fx - 6} ${y - 2} L${fx + 6} ${y - 2}`} stroke={color} strokeWidth="3" /></g>)}</g>;
    case "flats":
      return <g fill={color}>{feet.map((fx, i) => <ellipse key={i} cx={fx} cy={y + 2} rx="12" ry="6" />)}</g>;
    case "heels":
      return <g fill={color}>{feet.map((fx, i) => <g key={i}><path d={`M${fx - 10} ${y - 2} C${fx - 10} ${y - 2} ${fx + 6} ${y - 2} ${fx + 10} ${y} L${fx + 6} ${y + 6} L${fx - 8} ${y + 6} Z`} /><rect x={fx - 8} y={y + 6} width="3" height="8" fill={d} /></g>)}</g>;
    case "hightops":
      return <g>{feet.map((fx, i) => <g key={i}><path d={`M${fx - 10} ${y - 18} L${fx - 10} ${y + 2} C${fx - 10} ${y + 6} ${fx + 10} ${y + 6} ${fx + 10} ${y} L${fx + 8} ${y - 18} Z`} fill={color} /><rect x={fx - 11} y={y + 1} width="22" height="5" rx="2" fill="#f8fafc" /><rect x={fx - 9} y={y - 18} width="18" height="6" rx="2" fill={d} /></g>)}</g>;
    case "maryjanes":
      return <g fill={color}>{feet.map((fx, i) => <g key={i}><ellipse cx={fx} cy={y + 2} rx="12" ry="6" /><path d={`M${fx - 10} ${y - 2} L${fx + 10} ${y - 2}`} stroke={color} strokeWidth="3" /><circle cx={fx} cy={y - 2} r="1.6" fill={d} /></g>)}</g>;
    default: // sneakers
      return <g>{feet.map((fx, i) => <g key={i}><path d={`M${fx - 10} ${y - 4} L${fx - 10} ${y + 2} C${fx - 10} ${y + 6} ${fx + 10} ${y + 6} ${fx + 10} ${y} L${fx + 8} ${y - 4} Z`} fill={color} /><rect x={fx - 11} y={y + 1} width="22" height="5" rx="2" fill="#f8fafc" /></g>)}</g>;
  }
}

// Boy-only facial hair, coloured to match the hair.
function FacialHair({ id, color }: { id: string; color: string }) {
  switch (id) {
    case "stubble":
      return <path d="M64 84 C66 108 82 122 100 122 C118 122 134 108 136 84 C132 100 120 108 100 108 C80 108 68 100 64 84 Z" fill={color} opacity="0.28" />;
    case "mustache":
      return <path d="M86 92 Q100 88 114 92 Q108 99 100 96 Q92 99 86 92 Z" fill={color} />;
    case "goatee":
      return <g fill={color}><path d="M88 92 Q100 89 112 92 Q106 98 100 96 Q94 98 88 92 Z" /><path d="M93 104 Q100 120 107 104 Q100 110 93 104 Z" /></g>;
    case "beard":
      return <g fill={color}><path d="M63 80 C63 112 82 126 100 126 C118 126 137 112 137 80 C133 100 120 109 100 109 C80 109 67 100 63 80 Z" /><path d="M86 91 Q100 87 114 91 Q108 98 100 95 Q92 98 86 91 Z" /></g>;
    default: return null;
  }
}

function Makeup({ id }: { id: string }) {
  const lips = <path d="M92 99 Q100 105 108 99 Q100 102.5 92 99 Z" fill="#e11d48" />;
  const shadow = (
    <g fill="#a855f7" opacity="0.5">
      <path d="M79 78 Q85 74 91 77 Q85 76 79 78 Z" />
      <path d="M121 78 Q115 74 109 77 Q115 76 121 78 Z" />
    </g>
  );
  switch (id) {
    case "lips": return lips;
    case "eyeshadow": return shadow;
    case "glam": return <g>{shadow}{lips}<circle cx="80" cy="91" r="5" fill="#fb7185" opacity="0.4" /><circle cx="120" cy="91" r="5" fill="#fb7185" opacity="0.4" /></g>;
    default: return null;
  }
}

function AccessoryBack({ id, color, m }: { id: string; color: string; m: Model }) {
  const a = anchors(m);
  switch (id) {
    case "wings":
      return <g fill={color} opacity="0.85"><path d={`M${a.cx - 30} 150 C${a.cx - 70} 120 ${a.cx - 72} 180 ${a.cx - 36} 196 C${a.cx - 50} 176 ${a.cx - 42} 162 ${a.cx - 30} 158 Z`} /><path d={`M${a.cx + 30} 150 C${a.cx + 70} 120 ${a.cx + 72} 180 ${a.cx + 36} 196 C${a.cx + 50} 176 ${a.cx + 42} 162 ${a.cx + 30} 158 Z`} /></g>;
    case "cape":
      return <path d={`M${a.shoulderL[0]} ${a.shoulderY + 2} C${a.cx - 50} 180 ${a.cx - 52} 240 ${a.cx - 44} 280 L${a.cx + 44} 280 C${a.cx + 52} 240 ${a.cx + 50} 180 ${a.shoulderR[0]} ${a.shoulderY + 2} C${a.cx - 20} ${a.shoulderY + 16} ${a.cx + 20} ${a.shoulderY + 16} ${a.shoulderL[0]} ${a.shoulderY + 2} Z`} fill={color} opacity="0.9" />;
    default: return null;
  }
}

function AccessoryFront({ id, color, m }: { id: string; color: string; m: Model }) {
  const a = anchors(m);
  const ny = a.shoulderY - 4;
  switch (id) {
    case "necklace":
      return <g fill="none" stroke={color} strokeWidth="3"><path d={`M${a.cx - 14} ${ny} C${a.cx - 8} ${ny + 16} ${a.cx + 8} ${ny + 16} ${a.cx + 14} ${ny}`} /><circle cx={a.cx} cy={ny + 16} r="4" fill={color} /></g>;
    case "scarf":
      return <g fill={color}><path d={`M${a.cx - 20} ${ny - 2} C${a.cx - 12} ${ny + 12} ${a.cx + 12} ${ny + 12} ${a.cx + 20} ${ny - 2} L${a.cx + 22} ${ny + 12} C${a.cx + 10} ${ny + 20} ${a.cx - 10} ${ny + 20} ${a.cx - 22} ${ny + 12} Z`} /><rect x={a.cx - 8} y={ny + 8} width="10" height="34" rx="3" /></g>;
    case "bowtie":
      return <g fill={color}><path d={`M${a.cx - 6} ${ny + 4} L${a.cx - 18} ${ny - 2} L${a.cx - 18} ${ny + 12} L${a.cx - 6} ${ny + 8} Z`} /><path d={`M${a.cx + 6} ${ny + 4} L${a.cx + 18} ${ny - 2} L${a.cx + 18} ${ny + 12} L${a.cx + 6} ${ny + 8} Z`} /><rect x={a.cx - 4} y={ny + 2} width="8" height="8" rx="2" fill={darker(color)} /></g>;
    case "backpack":
      return <g fill={color}><path d={`M${a.shoulderL[0] + 6} ${a.shoulderY + 2} C${a.shoulderL[0] + 6} ${a.shoulderY - 2} ${a.shoulderL[0] + 10} ${a.shoulderY - 2} ${a.shoulderL[0] + 10} ${a.shoulderY + 2} L${a.shoulderL[0] + 12} ${a.shoulderY + 48} L${a.shoulderL[0] + 4} ${a.shoulderY + 48} Z`} /><path d={`M${a.shoulderR[0] - 6} ${a.shoulderY + 2} C${a.shoulderR[0] - 6} ${a.shoulderY - 2} ${a.shoulderR[0] - 10} ${a.shoulderY - 2} ${a.shoulderR[0] - 10} ${a.shoulderY + 2} L${a.shoulderR[0] - 12} ${a.shoulderY + 48} L${a.shoulderR[0] - 4} ${a.shoulderY + 48} Z`} /></g>;
    case "headphones":
      return <g fill="none" stroke={color} strokeWidth="4"><path d="M64 76 C64 36 136 36 136 76" /><rect x="58" y="72" width="10" height="18" rx="4" fill={color} /><rect x="132" y="72" width="10" height="18" rx="4" fill={color} /></g>;
    default: return null;
  }
}

export default function Figure({ member, size = 200 }: { member: Member; size?: number }) {
  const skin = skinHex(member);
  const hcol = hairHex(member);
  const m = resolveModel(member.model, member.body === "boy" ? "boy" : "girl");
  const a = anchors(m);
  const clipId = `chest-${member.id}`;
  const cr = chestRect(m);
  // Map the head art (authored at cy76 r38) onto this model's head.
  const hs = m.head.r / 38;
  const headTf = `translate(${m.head.cx} ${m.head.cy}) scale(${hs}) translate(-100 -76)`;
  const skinG = `skin-${member.id}`;
  const skinFill = `url(#${skinG})`;

  return (
    <svg className="duf" width={size} height={size * 1.45} viewBox="0 0 200 290" role="img" aria-label={`${member.name}`}>
      <defs>
        <clipPath id={clipId}><rect x={cr.x} y={cr.y} width={cr.w} height={cr.h} rx="4" /></clipPath>
        {/* Soft rounded shading so skin isn't a flat fill. */}
        <radialGradient id={skinG} cx="42%" cy="32%" r="72%">
          <stop offset="0%" stopColor={lighten(skin, 1.1)} />
          <stop offset="62%" stopColor={skin} />
          <stop offset="100%" stopColor={darker(skin, 0.9)} />
        </radialGradient>
        {/* Colour-agnostic garment shade: sheen at the top, shadow at the hem. */}
        <linearGradient id="gShade" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fff" stopOpacity="0.14" />
          <stop offset="34%" stopColor="#fff" stopOpacity="0" />
          <stop offset="100%" stopColor="#000" stopOpacity="0.22" />
        </linearGradient>
      </defs>

      <AccessoryBack id={member.accessory} color={colorHex(member.accessoryColor)} m={m} />
      {/* Hair is built from the head's dimensions (model coords), so it tracks
          the head like garments track the body. Back hair falls behind the body. */}
      <Hair id={member.hair} color={hcol} layer="back" head={m.head} />

      {/* legs (skin) + bottoms + shoes */}
      <path d={legsPath(m)} fill={skinFill} />
      <Bottom id={member.bottom} color={colorHex(member.bottomColor)} m={m} />
      <Shoes id={member.shoes} color={colorHex(member.shoesColor)} m={m} />

      {/* torso + arms (skin), fitted to the model */}
      <g fill={skinFill}>
        <path d={torsoPath(m)} />
        <path d={armPath(m, "L")} />
        <path d={armPath(m, "R")} />
        <circle cx={a.wristL[0]} cy={a.wristL[1] + 2} r={m.arm.thickness / 2 + 1} />
        <circle cx={a.wristR[0]} cy={a.wristR[1] + 2} r={m.arm.thickness / 2 + 1} />
      </g>

      <Top id={member.top} color={colorHex(member.topColor)} m={m} />
      {member.shirtPhoto && (
        <image href={member.shirtPhoto} x={cr.x} y={cr.y} width={cr.w} height={cr.h}
          preserveAspectRatio="xMidYMid slice" clipPath={`url(#${clipId})`} />
      )}
      {/* garment shading — sheen at the shoulders, shadow at the hem */}
      <path d={torsoPath(m)} fill="url(#gShade)" />
      {(member.top === "dress" || member.top === "gown") && (
        <path d={skirtPath(m, member.top === "gown" ? 96 : 56)} fill="url(#gShade)" />
      )}

      <AccessoryFront id={member.accessory} color={colorHex(member.accessoryColor)} m={m} />

      {/* neck (short & chunky, tucked under the big head) */}
      <rect x={100 - m.neckW} y={m.head.cy + m.head.r - 12} width={m.neckW * 2}
        height={m.shoulder.y - (m.head.cy + m.head.r) + 16} rx={m.neckW} fill={skinFill} />

      {/* head + face + front hair + glasses + hat, all scaled to the model head */}
      <g transform={headTf}>
      <circle cx="100" cy="76" r="38" fill={skinFill} />
      <g>
        {member.body === "girl" ? (
          <g stroke={darker(hcol, 0.85)} strokeWidth="2" strokeLinecap="round" fill="none">
            <path d="M78 70 Q85 67.5 92 69.5" />
            <path d="M108 69.5 Q115 67.5 122 70" />
          </g>
        ) : (
          <g stroke={darker(hcol, 0.8)} strokeWidth="2.8" strokeLinecap="round" fill="none">
            <path d="M77 69 Q85 66 93 69" />
            <path d="M107 69 Q115 66 123 69" />
          </g>
        )}
        {/* Big, defined eyes — large dark iris + catch-lights + a bold upper
            lid (not a wide white stare). */}
        <g>
          <ellipse cx="85" cy={EYE_Y} rx="7.4" ry="8.6" fill="#fdfdff" />
          <ellipse cx="115" cy={EYE_Y} rx="7.4" ry="8.6" fill="#fdfdff" />
          <circle cx="85" cy={EYE_Y + 1} r="5.9" fill="#4a3524" />
          <circle cx="115" cy={EYE_Y + 1} r="5.9" fill="#4a3524" />
          <circle cx="85" cy={EYE_Y + 1.6} r="3" fill="#20160e" />
          <circle cx="115" cy={EYE_Y + 1.6} r="3" fill="#20160e" />
          <circle cx="87.4" cy={EYE_Y - 2.4} r="2.3" fill="#fff" />
          <circle cx="117.4" cy={EYE_Y - 2.4} r="2.3" fill="#fff" />
          <circle cx="82.6" cy={EYE_Y + 3.4} r="1.1" fill="#fff" opacity="0.85" />
          <circle cx="112.6" cy={EYE_Y + 3.4} r="1.1" fill="#fff" opacity="0.85" />
          <path d="M77.6 77 Q85 73.4 92.4 77" stroke="#241a12" strokeWidth="2.6" fill="none" strokeLinecap="round" />
          <path d="M107.6 77 Q115 73.4 122.4 77" stroke="#241a12" strokeWidth="2.6" fill="none" strokeLinecap="round" />
          {member.body === "girl" && (
            <g stroke="#241a12" strokeWidth="1.6" strokeLinecap="round">
              <path d="M77.6 77 L74.8 75.2" />
              <path d="M122.4 77 L125.2 75.2" />
            </g>
          )}
        </g>
        <path d="M99 88 Q100 91 102 91" stroke={darker(skin, 0.8)} strokeWidth="1.3"
          fill="none" strokeLinecap="round" opacity="0.4" />
        <ellipse cx="78" cy="95" rx="5.4" ry="3.4" fill="#fb7185" opacity="0.3" />
        <ellipse cx="122" cy="95" rx="5.4" ry="3.4" fill="#fb7185" opacity="0.3" />
        <path d="M92 99 Q100 105 108 99" stroke="#c15563" strokeWidth="2.2" fill="none" strokeLinecap="round" />
        <Makeup id={member.makeup} />
        {member.body === "boy" && <FacialHair id={member.facialHair} color={hcol} />}
      </g>
      </g>
      <Hair id={member.hair} color={hcol} layer="front" head={m.head} />
      {member.hair !== "afro" && member.hair !== "buzz" && (
        <path d={hairShine(m.head)} fill="none" stroke={lighten(hcol, 1.5)}
          strokeWidth={m.head.r * 0.12} strokeLinecap="round" opacity="0.45" />
      )}
      <g transform={headTf}>
        <Glasses id={member.glasses} />
        <Hat id={member.hat} color={colorHex(member.hatColor)} />
      </g>
    </svg>
  );
}
