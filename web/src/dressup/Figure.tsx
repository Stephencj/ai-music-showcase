// The dress-up character — a full-body layered SVG built on ONE coordinate
// system (viewBox 200×340) so every item lands on its anchor: hair/hats on the
// head circle, tops on the torso, bottoms on the legs, shoes on the feet,
// glasses on the eyes. Pure vector — recolors live, works offline. If you tweak
// a garment, re-screenshot the gallery to confirm it still fits.
import {
  type Member, skinHex, hairHex, colorHex,
} from "./wardrobe";

// Shared anchors (the whole body is drawn against these).
const HEAD = { cx: 100, cy: 76, r: 40 };
const EYE_Y = 80;

const darker = (hex: string, f = 0.78) => {
  const n = parseInt(hex.slice(1), 16);
  const r = Math.round(((n >> 16) & 255) * f), g = Math.round(((n >> 8) & 255) * f), b = Math.round((n & 255) * f);
  return `rgb(${r},${g},${b})`;
};

function Hair({ id, color, layer }: { id: string; color: string; layer: "back" | "front" }) {
  const back = layer === "back";
  switch (id) {
    case "buzz":
      return back ? null : <path d="M64 60 C62 38 138 38 136 60 C128 44 72 44 64 60 Z" fill={color} opacity={0.85} />;
    case "short":
      return back ? null : <path d="M62 64 C58 34 142 34 138 64 C138 50 126 42 100 42 C74 42 62 50 62 64 Z" fill={color} />;
    case "bob":
      if (back) return <path d="M58 56 C58 30 142 30 142 56 L142 96 C142 104 132 104 132 92 L132 64 C132 50 68 50 68 64 L68 92 C68 104 58 104 58 96 Z" fill={color} />;
      return <path d="M60 62 C58 34 142 34 140 62 C138 48 126 40 100 40 C74 40 62 48 60 62 Z" fill={color} />;
    case "long":
      if (back) return <path d="M56 56 C56 28 144 28 144 56 L150 150 C150 162 134 162 134 150 L130 80 C130 60 70 60 70 80 L66 150 C66 162 50 162 50 150 Z" fill={color} />;
      return <path d="M60 64 C56 32 144 32 140 64 C138 46 124 38 100 38 C76 38 62 46 60 64 Z" fill={color} />;
    case "wavy":
      if (back) return <path d="M54 54 C54 26 146 26 146 54 C152 100 150 140 154 170 C150 158 140 158 138 148 C142 120 138 90 132 74 C132 58 68 58 68 74 C62 90 58 120 62 148 C60 158 50 158 46 170 C50 140 48 100 54 54 Z" fill={color} />;
      return <path d="M60 64 C56 30 144 30 140 64 C136 46 124 38 100 38 C76 38 64 46 60 64 Z" fill={color} />;
    case "curly":
      if (back) return (
        <g fill={color}>
          <circle cx="62" cy="60" r="14" /><circle cx="138" cy="60" r="14" />
          <circle cx="60" cy="92" r="13" /><circle cx="140" cy="92" r="13" />
          <circle cx="64" cy="120" r="11" /><circle cx="136" cy="120" r="11" />
        </g>
      );
      return (
        <g fill={color}>
          <circle cx="74" cy="44" r="13" /><circle cx="100" cy="38" r="14" /><circle cx="126" cy="44" r="13" />
          <circle cx="62" cy="58" r="12" /><circle cx="138" cy="58" r="12" />
        </g>
      );
    case "pony":
      if (back) return <path d="M132 56 C150 60 156 110 150 150 C148 160 138 158 138 148 C142 120 138 80 124 66 Z" fill={color} />;
      return <path d="M62 62 C58 34 142 34 138 62 C138 48 126 42 100 42 C74 42 62 50 62 62 Z" fill={color} />;
    case "pigtails":
      if (back) return (
        <g fill={color}>
          <ellipse cx="52" cy="78" rx="14" ry="22" /><ellipse cx="148" cy="78" rx="14" ry="22" />
        </g>
      );
      return <path d="M62 60 C58 34 142 34 138 60 C138 46 126 40 100 40 C74 40 62 48 62 60 Z" fill={color} />;
    case "bun":
      if (back) return null;
      return (
        <g fill={color}>
          <circle cx="100" cy="32" r="13" />
          <path d="M62 60 C60 38 140 38 138 60 C138 48 126 42 100 42 C74 42 62 48 62 60 Z" />
        </g>
      );
    case "braids":
      if (back) return (
        <g fill={color}>
          <path d="M64 64 C56 90 58 130 62 150 C64 158 74 156 72 148 C70 120 70 92 74 72 Z" />
          <path d="M136 64 C144 90 142 130 138 150 C136 158 126 156 128 148 C130 120 130 92 126 72 Z" />
          <circle cx="68" cy="96" r="6" /><circle cx="67" cy="120" r="6" /><circle cx="68" cy="142" r="6" />
          <circle cx="132" cy="96" r="6" /><circle cx="133" cy="120" r="6" /><circle cx="132" cy="142" r="6" />
        </g>
      );
      return <path d="M62 62 C58 32 142 32 138 62 C138 46 126 40 100 40 C74 40 62 48 62 62 Z" fill={color} />;
    case "afro":
      if (back) return <circle cx="100" cy="56" r="50" fill={color} />;
      return null;
    case "mohawk":
      if (back) return null;
      return <path d="M92 40 C92 18 108 18 108 40 L108 48 L92 48 Z" fill={color} />;
    case "spiky":
      if (back) return null;
      return (
        <g fill={color}>
          <path d="M62 56 L70 30 L82 50 L96 26 L104 50 L118 28 L130 52 L138 56 C120 44 80 44 62 56 Z" />
        </g>
      );
    default:
      return back ? null : <path d="M62 64 C58 34 142 34 138 64 C138 50 126 42 100 42 C74 42 62 50 62 64 Z" fill={color} />;
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

// Shared torso silhouette — hourglass for "girl" (nipped waist, flared hips),
// broad & straight for "boy". Used by the skin torso and the simple tops so the
// CLOTHED shape (not just hidden skin) reads as the right body type.
export const torsoPath = (body: string) => body === "girl"
  ? "M64 130 C61 148 81 165 79 180 C77 191 72 196 72 206 L128 206 C128 196 123 191 121 180 C119 165 139 148 136 130 C118 121 82 121 64 130 Z"
  : "M60 130 C56 152 74 198 80 206 L120 206 C126 198 144 152 140 130 C120 119 80 119 60 130 Z";

// Top covers the torso (shoulders y130 → hem y206); dress/gown flare into a
// skirt (and imply bottom "none").
function Top({ id, color, body, hasPhoto }: { id: string; color: string; body: string; hasPhoto?: boolean }) {
  const d = darker(color);
  const sleeveS = <><path d="M64 130 C52 138 48 152 52 162 L66 158 C66 144 70 136 74 132 Z" fill={color} /><path d="M136 130 C148 138 152 152 148 162 L134 158 C134 144 130 136 126 132 Z" fill={color} /></>;
  const sleeveL = <><path d="M64 130 C50 144 48 176 52 198 C53 202 62 202 63 198 C64 176 70 148 76 134 Z" fill={color} /><path d="M136 130 C150 144 152 176 148 198 C147 202 138 202 137 198 C136 176 130 148 124 134 Z" fill={color} /></>;
  const body0 = torsoPath(body);
  const tankBody = body === "girl"
    ? "M76 128 C73 148 81 166 80 180 C79 192 76 200 84 206 L116 206 C124 200 121 192 120 180 C119 166 127 148 124 128 C116 140 84 140 76 128 Z"
    : "M76 128 C72 150 80 200 84 206 L116 206 C120 200 128 150 124 128 C116 140 84 140 76 128 Z";
  switch (id) {
    case "tank":
      return <path d={tankBody} fill={color} />;
    case "long":
      return <g>{sleeveL}<path d={body0} fill={color} />{!hasPhoto && <path d="M88 124 C92 134 108 134 112 124" fill={skinFill} />}</g>;
    case "hoodie":
      return <g><path d="M70 120 C70 104 130 104 130 120 C120 116 80 116 70 120 Z" fill={d} />{sleeveL}<path d={body0} fill={color} /><rect x="84" y="170" width="32" height="22" rx="5" fill={d} /><line x1="100" y1="128" x2="100" y2="166" stroke={d} strokeWidth="2" /></g>;
    case "jacket":
      return <g>{sleeveL}<path d={body0} fill={color} /><path d="M100 124 L86 130 L92 200 L100 200 Z" fill={d} /><path d="M100 124 L114 130 L108 200 L100 200 Z" fill={darker(color, 0.6)} /></g>;
    case "stripes":
      return <g>{sleeveS}<path d={body0} fill={color} /><g stroke="#f8fafc" strokeWidth="5" opacity="0.9"><line x1="66" y1="150" x2="134" y2="150" /><line x1="70" y1="168" x2="130" y2="168" /><line x1="74" y1="186" x2="126" y2="186" /></g></g>;
    case "jersey":
      return <g><path d={tankBody} fill={color} /><text x="100" y="180" fontSize="26" fontWeight="700" fill="#f8fafc" textAnchor="middle">7</text></g>;
    case "dress":
      return <g>{sleeveS}<path d="M64 130 C60 152 72 188 74 198 L62 256 C84 264 116 264 138 256 L126 198 C128 188 140 152 136 130 C118 122 82 122 64 130 Z" fill={color} /></g>;
    case "gown":
      return <g><path d="M76 128 C72 150 78 186 78 196 L54 290 C84 300 116 300 146 290 L122 196 C122 186 128 150 124 128 C116 140 84 140 76 128 Z" fill={color} /><g fill="#fef9c3" opacity="0.9"><circle cx="84" cy="230" r="2" /><circle cx="110" cy="250" r="2" /><circle cx="96" cy="270" r="2" /><circle cx="120" cy="225" r="2" /></g></g>;
    case "tutu-top":
      return <path d={tankBody} fill={color} />;
    default: // tee
      return <g>{sleeveS}<path d={body0} fill={color} />{!hasPhoto && <path d="M88 124 C92 134 108 134 112 124" fill={skinFill} opacity="0.001" />}</g>;
  }
}

// chest region used to clip the photo print
const CHEST = { x: 84, y: 140, w: 32, h: 34 };
const skinFill = "transparent";

function Bottom({ id, color, body }: { id: string; color: string; body: string }) {
  const d = darker(color);
  // Girl hips flare wider at the waistband (matches the hourglass torso).
  const oL = body === "girl" ? 74 : 80, oR = body === "girl" ? 126 : 120;
  const pants = `M${oL} 202 L79 298 L97 298 L99 214 L101 214 L103 298 L121 298 L${oR} 202 Z`;
  switch (id) {
    case "shorts":
      return <path d={`M${oL} 202 L80 248 L97 248 L99 214 L101 214 L103 248 L120 248 L${oR} 202 Z`} fill={color} />;
    case "skirt":
      return <g><path d={`M${oL - 2} 202 L60 256 L140 256 L${oR + 2} 202 Z`} fill={color} /><path d="M60 256 L140 256" stroke={d} strokeWidth="2" /></g>;
    case "tutu":
      return <path d="M72 204 C72 204 58 244 56 246 L70 240 L66 250 L80 242 L78 252 L92 244 L92 254 L108 244 L108 254 L122 242 L120 252 L134 242 L130 250 L144 246 C142 244 128 204 128 204 Z" fill={color} opacity="0.92" />;
    case "leggings":
      return <g fill={color}><path d={`M${oL + 8} 204 L83 298 L96 298 L98 212 Z`} /><path d={`M${oR - 8} 204 L117 298 L104 298 L102 212 Z`} /></g>;
    case "none":
      return null;
    case "jeans":
      return <g><path d={pants} fill={color} /><line x1="100" y1="208" x2="100" y2="296" stroke={d} strokeWidth="1.5" /><path d={`M${oL + 4} 212 L96 212`} stroke={d} strokeWidth="1.5" /></g>;
    default: // pants
      return <path d={pants} fill={color} />;
  }
}

function Shoes({ id, color }: { id: string; color: string }) {
  const d = darker(color);
  switch (id) {
    case "barefoot": return null;
    case "boots":
      return <g fill={color}><path d="M80 270 L80 304 C80 308 98 308 98 304 L98 270 Z" /><path d="M102 270 L102 304 C102 308 120 308 120 304 L120 270 Z" /><rect x="78" y="302" width="22" height="6" rx="2" fill={d} /><rect x="100" y="302" width="22" height="6" rx="2" fill={d} /></g>;
    case "sandals":
      return <g fill={color}><ellipse cx="89" cy="306" rx="12" ry="5" /><ellipse cx="111" cy="306" rx="12" ry="5" /><path d="M84 300 L94 300 M106 300 L116 300" stroke={color} strokeWidth="3" /></g>;
    case "flats":
      return <g fill={color}><ellipse cx="89" cy="304" rx="13" ry="6" /><ellipse cx="111" cy="304" rx="13" ry="6" /></g>;
    case "heels":
      return <g fill={color}><path d="M78 300 C78 300 96 300 100 302 L96 308 L80 308 Z" /><path d="M122 300 C122 300 104 300 100 302 L104 308 L120 308 Z" /><rect x="80" y="308" width="3" height="8" fill={d} /><rect x="117" y="308" width="3" height="8" fill={d} /></g>;
    default: // sneakers
      return <g><path d="M78 298 L78 306 C78 310 100 310 100 304 L98 298 Z" fill={color} /><path d="M122 298 L122 306 C122 310 100 310 100 304 L102 298 Z" fill={color} /><rect x="77" y="305" width="23" height="5" rx="2" fill="#f8fafc" /><rect x="100" y="305" width="23" height="5" rx="2" fill="#f8fafc" /></g>;
  }
}

// Boy-only facial hair, coloured to match the hair. Drawn over the lower face.
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

// Makeup — lips and/or eyeshadow. Drawn over the base face features.
function Makeup({ id }: { id: string }) {
  const lips = <path d="M90 96 Q100 105 110 96 Q100 101 90 96 Z" fill="#e11d48" />;
  const shadow = (
    <g fill="#a855f7" opacity="0.55">
      <path d="M80 76 Q86 72 92 75 Q86 74 80 76 Z" />
      <path d="M120 76 Q114 72 108 75 Q114 74 120 76 Z" />
    </g>
  );
  switch (id) {
    case "lips": return lips;
    case "eyeshadow": return shadow;
    case "glam": return <g>{shadow}{lips}<circle cx="80" cy="92" r="6" fill="#fb7185" opacity="0.4" /><circle cx="120" cy="92" r="6" fill="#fb7185" opacity="0.4" /></g>;
    default: return null;
  }
}

function AccessoryBack({ id, color }: { id: string; color: string }) {
  switch (id) {
    case "wings":
      return <g fill={color} opacity="0.85"><path d="M70 150 C30 120 28 180 64 196 C50 176 58 162 70 158 Z" /><path d="M130 150 C170 120 172 180 136 196 C150 176 142 162 130 158 Z" /></g>;
    case "cape":
      return <path d="M66 132 C50 180 48 240 56 280 L144 280 C152 240 150 180 134 132 C120 150 80 150 66 132 Z" fill={color} opacity="0.9" />;
    default: return null;
  }
}

function AccessoryFront({ id, color }: { id: string; color: string }) {
  switch (id) {
    case "necklace":
      return <g fill="none" stroke={color} strokeWidth="3"><path d="M86 122 C92 138 108 138 114 122" /><circle cx="100" cy="138" r="4" fill={color} /></g>;
    case "scarf":
      return <g fill={color}><path d="M80 120 C88 134 112 134 120 120 L122 134 C110 142 90 142 78 134 Z" /><rect x="92" y="130" width="10" height="34" rx="3" /></g>;
    case "bowtie":
      return <g fill={color}><path d="M94 126 L82 120 L82 134 L94 130 Z" /><path d="M106 126 L118 120 L118 134 L106 130 Z" /><rect x="96" y="124" width="8" height="8" rx="2" fill={darker(color)} /></g>;
    case "backpack":
      return <g fill={color}><path d="M74 134 C74 130 78 130 78 134 L80 180 L72 180 Z" /><path d="M126 134 C126 130 122 130 122 134 L120 180 L128 180 Z" /></g>;
    case "headphones":
      return <g fill="none" stroke={color} strokeWidth="4"><path d="M64 76 C64 36 136 36 136 76" /><rect x="58" y="72" width="10" height="18" rx="4" fill={color} /><rect x="132" y="72" width="10" height="18" rx="4" fill={color} /></g>;
    default: return null;
  }
}

export default function Figure({ member, size = 200 }: { member: Member; size?: number }) {
  const skin = skinHex(member);
  const hcol = hairHex(member);
  const clipId = `chest-${member.id}`;

  return (
    <svg className="duf" width={size} height={size * 1.7} viewBox="0 0 200 340" role="img" aria-label={`${member.name}`}>
      <defs>
        <clipPath id={clipId}><rect x={CHEST.x} y={CHEST.y} width={CHEST.w} height={CHEST.h} rx="4" /></clipPath>
      </defs>

      <AccessoryBack id={member.accessory} color={colorHex(member.accessoryColor)} />
      <Hair id={member.hair} color={hcol} layer="back" />

      {/* legs + feet (skin) */}
      <g fill={skin}>
        <path d="M83 200 L82 300 C82 305 98 305 97 300 L99 204 Z" />
        <path d="M101 204 L103 300 C102 305 118 305 118 300 L117 200 Z" />
      </g>
      <Bottom id={member.bottom} color={colorHex(member.bottomColor)} body={member.body} />
      <Shoes id={member.shoes} color={colorHex(member.shoesColor)} />

      {/* torso + arms (skin) — silhouette varies by body type (hourglass vs
          broad); garment anchors stay fixed so clothes still fit both. */}
      <g fill={skin}>
        <path d={torsoPath(member.body)} />
        <path d="M62 130 C52 150 48 176 52 198 C53 202 61 202 62 198 C63 176 68 150 74 134 Z" />
        <path d="M138 130 C148 150 152 176 148 198 C147 202 139 202 138 198 C137 176 132 150 126 134 Z" />
        <circle cx="57" cy="200" r="5" /><circle cx="143" cy="200" r="5" />
      </g>

      <Top id={member.top} color={colorHex(member.topColor)} body={member.body} hasPhoto={!!member.shirtPhoto} />
      {member.shirtPhoto && (
        <image href={member.shirtPhoto} x={CHEST.x} y={CHEST.y} width={CHEST.w} height={CHEST.h}
          preserveAspectRatio="xMidYMid slice" clipPath={`url(#${clipId})`} />
      )}

      {/* neck + head */}
      <rect x="92" y="106" width="16" height="18" rx="4" fill={skin} />
      <circle cx={HEAD.cx} cy={HEAD.cy} r={HEAD.r} fill={skin} />

      {/* face */}
      <g>
        <circle cx="86" cy={EYE_Y} r="3.2" fill="#2b2b30" />
        <circle cx="114" cy={EYE_Y} r="3.2" fill="#2b2b30" />
        {member.body === "girl" ? (
          <g stroke="#2b2b30" strokeWidth="1.6" strokeLinecap="round">
            <path d="M79 76 L82 78 M79 80 L82 80 M80 83 L83 82" fill="none" />
            <path d="M121 76 L118 78 M121 80 L118 80 M120 83 L117 82" fill="none" />
          </g>
        ) : (
          <g stroke="#6b4a2a" strokeWidth="2" strokeLinecap="round">
            <path d="M81 72 L91 72" /><path d="M109 72 L119 72" />
          </g>
        )}
        <circle cx="80" cy="92" r="5" fill="#fb7185" opacity="0.45" />
        <circle cx="120" cy="92" r="5" fill="#fb7185" opacity="0.45" />
        <path d="M90 96 Q100 104 110 96" stroke="#b9525a" strokeWidth="2.4" fill="none" strokeLinecap="round" />
        <Makeup id={member.makeup} />
        {member.body === "boy" && <FacialHair id={member.facialHair} color={hcol} />}
      </g>

      <AccessoryFront id={member.accessory} color={colorHex(member.accessoryColor)} />
      <Hair id={member.hair} color={hcol} layer="front" />
      <Glasses id={member.glasses} />
      <Hat id={member.hat} color={colorHex(member.hatColor)} />
    </svg>
  );
}
