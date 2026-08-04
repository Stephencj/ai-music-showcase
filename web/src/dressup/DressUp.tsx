// Full-screen, kid-friendly dress-up — the "big tap board": a big character,
// a row of category buttons, and a grid of big item buttons you tap to wear
// instantly (no reading, no dragging required). Photo-on-shirt, boy/girl body,
// and a star-collecting progression. SELF-CONTAINED & OFFLINE (no backend) so
// it can spin off into a standalone app. Persists its own star progress in
// localStorage; the band's image multiplier is derived from the members.
import { useRef, useState } from "react";
import Figure from "./Figure";
import CropModal from "./CropModal";
import { modelsFor } from "./models";
import {
  type Member, type BodyType, type Part, type Swatch, type Shape,
  PARTS, PART_ICON, SKINS, COLORS, HAIR_COLORS,
  HAIR, HATS, GLASSES, TOPS, BOTTOMS, SHOES, ACCESSORIES, FACIAL_HAIR, MAKEUP, defaultMember,
} from "./wardrobe";

interface Cat {
  id: string; label: string; icon: string;
  shapes: Shape[]; shapeKey: keyof Member;
  colors?: Swatch[]; colorKey?: keyof Member;
  photo?: boolean;
}
const CATS: Cat[] = [
  { id: "hair", label: "Hair", icon: "💇", shapes: HAIR, shapeKey: "hair", colors: HAIR_COLORS, colorKey: "hairColor" },
  { id: "hat", label: "Hat", icon: "🎩", shapes: HATS, shapeKey: "hat", colors: COLORS, colorKey: "hatColor" },
  { id: "glasses", label: "Glasses", icon: "👓", shapes: GLASSES, shapeKey: "glasses" },
  { id: "makeup", label: "Makeup", icon: "💄", shapes: MAKEUP, shapeKey: "makeup" },
  { id: "beard", label: "Beard", icon: "🧔", shapes: FACIAL_HAIR, shapeKey: "facialHair", colors: HAIR_COLORS, colorKey: "hairColor" },
  { id: "top", label: "Top", icon: "👕", shapes: TOPS, shapeKey: "top", colors: COLORS, colorKey: "topColor", photo: true },
  { id: "bottom", label: "Bottom", icon: "👖", shapes: BOTTOMS, shapeKey: "bottom", colors: COLORS, colorKey: "bottomColor" },
  { id: "shoes", label: "Shoes", icon: "👟", shapes: SHOES, shapeKey: "shoes", colors: COLORS, colorKey: "shoesColor" },
  { id: "acc", label: "Extra", icon: "✨", shapes: ACCESSORIES, shapeKey: "accessory", colors: COLORS, colorKey: "accessoryColor" },
  { id: "skin", label: "Skin", icon: "🖐", shapes: [], shapeKey: "skin", colors: SKINS, colorKey: "skin" },
];

const STAR_KEY = "dressup.stars";
const TRIED_KEY = "dressup.tried";
const loadTried = (): Set<string> => {
  try { return new Set(JSON.parse(localStorage.getItem(TRIED_KEY) || "[]")); } catch { return new Set(); }
};
const LEVELS = ["New Stylist", "Style Star", "Fashionista", "Glam Guru", "Style Legend"];

export default function DressUp({ members, onChange, onClose, onPerform, hideClose }: {
  members: Member[];
  onChange: (m: Member[]) => void;
  onClose: () => void;
  onPerform?: () => void;
  hideClose?: boolean;   // standalone app: no "close" (it's the whole app)
}) {
  const [sel, setSel] = useState(0);
  const [cat, setCat] = useState("top");
  const [crop, setCrop] = useState(false);
  const [stars, setStars] = useState<number>(() => Number(localStorage.getItem(STAR_KEY) || 0));
  const [pop, setPop] = useState(false);                 // star celebration
  const triedRef = useRef<Set<string>>(loadTried());
  const fileRef = useRef<HTMLInputElement | null>(null);
  const [photoSrc, setPhotoSrc] = useState<string | null>(null);

  const cur = members[sel] || null;
  const category = CATS.find((c) => c.id === cat)!;

  const reward = (key: string) => {
    if (triedRef.current.has(key)) return;
    triedRef.current.add(key);
    localStorage.setItem(TRIED_KEY, JSON.stringify([...triedRef.current]));
    setStars((s) => { const n = s + 1; localStorage.setItem(STAR_KEY, String(n)); return n; });
    setPop(true); setTimeout(() => setPop(false), 700);
  };

  const patch = (p: Partial<Member>, rewardKey?: string) => {
    onChange(members.map((m, i) => (i === sel ? { ...m, ...p } : m)));
    if (rewardKey) reward(rewardKey);
  };

  // Wear an item, keeping top/bottom sensible: a dress/gown hides the bottom;
  // switching off a dress restores pants; picking a bottom under a dress swaps
  // the dress for a tee so the bottom shows.
  const wear = (key: keyof Member, id: string) => {
    const p: Partial<Member> = { [key]: id } as Partial<Member>;
    if (key === "top") {
      if (id === "dress" || id === "gown") p.bottom = "none";
      else if (cur && cur.bottom === "none") p.bottom = "pants";
    }
    if (key === "bottom" && id !== "none" && cur && (cur.top === "dress" || cur.top === "gown")) p.top = "tee";
    patch(p, `${cat}:${id}`);
  };
  // Switching to a girl clears facial hair (girls never have it) and bumps off
  // the Beard tab if it was open.
  const setBody = (body: BodyType) => {
    const model = modelsFor(body)[0].id;   // keep the model consistent with the gender
    patch(body === "girl" ? { body, model, facialHair: "none" } : { body, model });
    if (body === "girl" && cat === "beard") setCat("top");
  };
  const visibleCats = CATS.filter((c) => c.id !== "beard" || cur?.body === "boy");

  const addMember = () => {
    const used = new Set(members.map((m) => m.part));
    const part = (PARTS.find((p) => !used.has(p)) || "Vocals") as Part;
    onChange([...members, defaultMember(part, `Member ${members.length + 1}`)]);
    setSel(members.length);
  };

  const onFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]; if (!f) return;
    const r = new FileReader();
    r.onload = () => { setPhotoSrc(String(r.result)); setCrop(true); };
    r.readAsDataURL(f);
    e.target.value = "";
  };

  const level = LEVELS[Math.min(LEVELS.length - 1, Math.floor(stars / 8))];

  if (!cur) {
    return (
      <div className="dressup-screen">
        <div className="du-top"><span className="du-title">🎨 Dress Up</span>
          {!hideClose && <button className="du-x" onClick={onClose}>✕</button>}</div>
        <div className="du-empty">
          <p>Make your band, then dress them up!</p>
          <button className="du-big-btn" onClick={addMember}>➕ Add a band member</button>
        </div>
      </div>
    );
  }

  return (
    <div className="dressup-screen">
      <div className="du-top">
        <span className="du-title">🎨 Dress Up</span>
        <span className={"du-stars" + (pop ? " pop" : "")}>⭐ {stars} · {level}</span>
        {!hideClose && <button className="du-x" onClick={onClose}>✕</button>}
      </div>

      <div className="du-main">
        <div className="du-stage">
          {/* member switcher */}
          <div className="du-members">
            {members.map((m, i) => (
              <button key={m.id} className={"du-mini" + (i === sel ? " on" : "")} onClick={() => setSel(i)}>
                <Figure member={m} size={34} />
                <span>{PART_ICON[m.part]}</span>
              </button>
            ))}
            {members.length < 6 && <button className="du-mini add" onClick={addMember}>＋</button>}
          </div>

          <div className="du-figure"><Figure member={cur} size={210} /></div>

          {/* body type */}
          <div className="du-body-toggle">
            <button className={cur.body === "girl" ? "on" : ""} onClick={() => setBody("girl")}>👧 Girl</button>
            <button className={cur.body === "boy" ? "on" : ""} onClick={() => setBody("boy")}>👦 Boy</button>
          </div>

          {/* build (body model) */}
          <div className="du-body-toggle">
            {(() => {
              const builds = modelsFor(cur.body);
              const curModel = cur.model ?? builds[0]?.id;   // fall back to the gender's default
              return builds.map((mdl) => (
                <button key={mdl.id} className={curModel === mdl.id ? "on" : ""} onClick={() => patch({ model: mdl.id })}>
                  {mdl.label}
                </button>
              ));
            })()}
          </div>
          {onPerform && (
            <button className="du-perform" onClick={onPerform}>🎬 Put on a show!</button>
          )}
        </div>

        <div className="du-board">
          {/* category tabs */}
          <div className="du-cats">
            {visibleCats.map((c) => (
              <button key={c.id} className={"du-cat" + (cat === c.id ? " on" : "")} onClick={() => setCat(c.id)}>
                <span className="du-cat-ic">{c.icon}</span><span className="du-cat-lb">{c.label}</span>
              </button>
            ))}
          </div>

          {/* item grid — each a mini figure wearing that option */}
          {category.shapes.length > 0 && (
            <div className="du-items">
              {category.shapes.map((s) => {
                const worn = cur[category.shapeKey] === s.id;
                const preview: Member = { ...cur, [category.shapeKey]: s.id } as Member;
                return (
                  <button key={s.id} className={"du-item" + (worn ? " on" : "")}
                    onClick={() => wear(category.shapeKey, s.id)}>
                    <Figure member={preview} size={52} />
                    <span className="du-item-lb">{s.name}</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* photo-on-shirt (Top category) */}
          {category.photo && (
            <div className="du-photo-row">
              <input ref={fileRef} type="file" accept="image/*" capture="environment"
                style={{ display: "none" }} onChange={onFile} />
              <button className="du-photo-btn" onClick={() => fileRef.current?.click()}>📷 Put a photo on the shirt</button>
              {cur.shirtPhoto && <button className="du-photo-clear" onClick={() => patch({ shirtPhoto: undefined })}>Remove photo</button>}
            </div>
          )}

          {/* color strip for the current slot */}
          {category.colors && category.colorKey && (
            <div className="du-colors">
              {category.colors.map((sw) => (
                <button key={sw.id} title={sw.name}
                  className={"du-color" + (cur[category.colorKey!] === sw.id ? " on" : "")}
                  style={{ background: sw.hex }}
                  onClick={() => patch({ [category.colorKey!]: sw.id } as Partial<Member>, `${category.id}c:${sw.id}`)} />
              ))}
            </div>
          )}
        </div>
      </div>

      {crop && photoSrc && (
        <CropModal src={photoSrc} onCancel={() => setCrop(false)}
          onDone={(dataUrl) => { patch({ shirtPhoto: dataUrl }, "photo"); setCrop(false); }} />
      )}
    </div>
  );
}
