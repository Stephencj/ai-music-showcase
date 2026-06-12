// A band member as a layered SVG — skin, hair, face/shades, shirt, pants, hat,
// and an instrument badge. Pure vector (no assets), so it renders instantly,
// offline, and recolors live as the Stylist swaps wardrobe items. viewBox is
// 100×140 (head-to-knee bust).
import {
  type Member, PART_ICON,
  skinOf, hairColorOf, topOf, bottomOf, shadesOf, hatOf,
} from "./stylist";

function Hair({ style, color }: { style: string; color: string }) {
  switch (style) {
    case "bald":
      return null;
    case "mohawk":
      return <path d="M50 6 C 47 18 47 24 47 30 L53 30 C53 24 53 18 50 6 Z" fill={color} />;
    case "long":
      return (
        <g fill={color}>
          <path d="M30 30 C28 14 42 6 50 6 C58 6 72 14 70 30 C70 22 60 16 50 16 C40 16 30 22 30 30 Z" />
          <path d="M30 30 C26 46 28 60 30 70 L37 70 C34 56 34 42 36 32 Z" />
          <path d="M70 30 C74 46 72 60 70 70 L63 70 C66 56 66 42 64 32 Z" />
        </g>
      );
    case "bun":
      return (
        <g fill={color}>
          <circle cx="50" cy="10" r="7" />
          <path d="M31 30 C30 16 42 11 50 11 C58 11 70 16 69 30 C69 22 60 17 50 17 C40 17 31 22 31 30 Z" />
        </g>
      );
    case "afro":
      return <path d="M28 28 C24 8 44 2 50 2 C56 2 76 8 72 28 C72 18 60 12 50 12 C40 12 28 18 28 28 Z" fill={color} transform="scale(1.12) translate(-6 -2)" />;
    case "short":
    default:
      return <path d="M32 30 C31 16 42 12 50 12 C58 12 69 16 68 30 C68 23 60 19 50 19 C40 19 32 23 32 30 Z" fill={color} />;
  }
}

function Hat({ id, color }: { id: string; color: string }) {
  switch (id) {
    case "beanie":
      return <path d="M31 26 C31 12 69 12 69 26 L69 30 L31 30 Z" fill={color} />;
    case "cap":
      return (
        <g fill={color}>
          <path d="M31 27 C31 13 69 13 69 27 L31 27 Z" />
          <path d="M31 27 L18 31 L31 31 Z" />
        </g>
      );
    case "fedora":
      return (
        <g fill={color}>
          <ellipse cx="50" cy="27" rx="28" ry="5" />
          <path d="M37 27 C37 14 63 14 63 27 Z" />
        </g>
      );
    case "tophat":
      return (
        <g fill={color}>
          <ellipse cx="50" cy="27" rx="26" ry="4" />
          <rect x="38" y="2" width="24" height="25" rx="2" />
        </g>
      );
    default:
      return null;
  }
}

function Shades({ id, color }: { id: string; color: string }) {
  if (id === "none") return null;
  if (id === "visor")
    return <rect x="36" y="33" width="28" height="7" rx="3" fill={color} opacity="0.9" />;
  if (id === "star")
    return (
      <g fill={color}>
        <text x="41" y="40" fontSize="11" textAnchor="middle">★</text>
        <text x="59" y="40" fontSize="11" textAnchor="middle">★</text>
      </g>
    );
  // round / wayfarer
  const rx = id === "round" ? 4.5 : 4;
  const ry = id === "round" ? 4.5 : 3.2;
  return (
    <g fill={color}>
      <ellipse cx="42" cy="37" rx={rx} ry={ry} />
      <ellipse cx="58" cy="37" rx={rx} ry={ry} />
      <rect x="46" y="36" width="8" height="1.6" />
    </g>
  );
}

export default function BandAvatar({ member, size = 120 }: { member: Member; size?: number }) {
  const skin = skinOf(member);
  const hairColor = hairColorOf(member);
  const top = topOf(member), bottom = bottomOf(member);
  const shades = shadesOf(member), hat = hatOf(member);
  const hasShades = member.shades !== "none";

  return (
    <svg className="band-avatar" width={size} height={size * 1.4} viewBox="0 0 100 140"
      role="img" aria-label={`${member.name}, ${member.part}`}>
      {/* legs / pants */}
      <path d="M40 96 L36 138 L46 138 L50 108 L54 138 L64 138 L60 96 Z" fill={bottom.color} />
      {/* torso / top */}
      <path d="M34 70 C34 66 40 62 50 62 C60 62 66 66 66 70 L70 100 L30 100 Z" fill={top.color} />
      {/* arms */}
      <path d="M34 70 L26 96 L32 98 L40 74 Z" fill={top.color} />
      <path d="M66 70 L74 96 L68 98 L60 74 Z" fill={top.color} />
      {/* neck + head */}
      <rect x="45" y="54" width="10" height="10" fill={skin} />
      <circle cx="50" cy="38" r="18" fill={skin} />
      {/* hair behind, then face features */}
      <Hair style={member.hair} color={hairColor} />
      {!hasShades && (
        <g fill="#2b2b30">
          <circle cx="43" cy="38" r="1.7" />
          <circle cx="57" cy="38" r="1.7" />
        </g>
      )}
      <path d="M46 46 Q50 49 54 46" stroke="#9b5d52" strokeWidth="1.4" fill="none" strokeLinecap="round" />
      <Shades id={member.shades} color={shades.color || "#111"} />
      <Hat id={member.hat} color={hat.color || "#333"} />
      {/* instrument badge */}
      <text x="50" y="120" fontSize="16" textAnchor="middle">{PART_ICON[member.part] || "🎵"}</text>
    </svg>
  );
}
