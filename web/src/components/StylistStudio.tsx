// Stylist track — choose the band's members and dress them. The lineup + each
// member's wardrobe drive the band's "image" multiplier (imageBreakdown), the
// visual counterpart to the producer's production multiplier: a fuller, more
// styled, on-brand lineup earns more fans at gigs. Looks are pure layered SVG
// (BandAvatar), so styling is instant and offline.
import { useMemo, useState } from "react";
import BandAvatar from "./BandAvatar";
import {
  type Member, type Part, PARTS, PART_ICON, THEME_LABEL,
  SKINS, HAIR_STYLES, HAIR_COLORS, TOPS, BOTTOMS, SHADES, HATS,
  defaultMember, imageBreakdown, dominantTheme,
} from "./stylist";

// One wardrobe slot: a labelled row of selectable options (colour swatch when
// the item carries a colour, else its name).
function SlotRow({ label, items, selected, onPick }: {
  label: string; items: { id: string; name: string; color?: string }[];
  selected: string; onPick: (id: string) => void;
}) {
  return (
    <div className="st-slot">
      <div className="st-slot-label">{label}</div>
      <div className="st-slot-opts">
        {items.map((it) => (
          <button key={it.id} type="button"
            className={"st-opt" + (selected === it.id ? " on" : "") + (it.color ? " swatch" : "")}
            title={it.name}
            style={it.color ? { background: it.color } : undefined}
            onClick={() => onPick(it.id)}>
            {it.color ? "" : it.name}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function StylistStudio({ members, onChange, onClose }: {
  members: Member[];
  onChange: (m: Member[]) => void;
  onClose: () => void;
}) {
  const [sel, setSel] = useState(0);
  const bd = useMemo(() => imageBreakdown(members), [members]);
  const cur = members[sel];

  const patch = (p: Partial<Member>) =>
    onChange(members.map((m, i) => (i === sel ? { ...m, ...p } : m)));

  const addMember = () => {
    const used = new Set(members.map((m) => m.part));
    const part = (PARTS.find((p) => !used.has(p)) || "Vocals") as Part;
    const m = defaultMember(part, `Member ${members.length + 1}`, members.length);
    onChange([...members, m]);
    setSel(members.length);
  };
  const quickLineup = () => {
    const lineup: Part[] = ["Vocals", "Guitar", "Bass", "Drums"];
    onChange(lineup.map((p, i) => defaultMember(p, p === "Vocals" ? "Singer" : p, i)));
    setSel(0);
  };
  const removeMember = (i: number) => {
    const next = members.filter((_, j) => j !== i);
    onChange(next);
    setSel((s) => Math.max(0, Math.min(s, next.length - 1)));
  };

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gig-modal st-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">🎨 Stylist</span>
          <button className="cof-close" onClick={onClose}>✕</button>
        </div>

        {/* Image multiplier readout */}
        <div className="st-image">
          <div className="st-image-mult">Image <b>×{bd.image.toFixed(2)}</b></div>
          <div className="st-image-chips">
            <span className="st-chip">Lineup +{Math.round(bd.lineup * 100)}%</span>
            <span className="st-chip">Styled +{Math.round(bd.styled * 100)}%</span>
            <span className="st-chip">{bd.cohesion > 0
              ? <>On-brand +{Math.round(bd.cohesion * 100)}% {bd.theme && `· ${THEME_LABEL[bd.theme]}`}</>
              : "Pick a shared look for a cohesion bonus"}</span>
          </div>
        </div>

        {members.length === 0 ? (
          <div className="st-empty">
            <div className="meta" style={{ marginBottom: 10 }}>
              No band members yet. Build your lineup, then dress them — a fuller, on-brand band earns more fans.
            </div>
            <div className="st-actions">
              <button className="btn" style={{ width: "auto" }} onClick={quickLineup}>⚡ Quick lineup</button>
              <button className="btn ghost" style={{ width: "auto" }} onClick={addMember}>+ Add member</button>
            </div>
          </div>
        ) : (
          <>
            {/* Lineup roster */}
            <div className="st-roster">
              {members.map((m, i) => (
                <button key={m.id} type="button"
                  className={"st-member" + (i === sel ? " on" : "")} onClick={() => setSel(i)}>
                  <BandAvatar member={m} size={58} />
                  <span className="st-member-name">{m.name}</span>
                  <span className="st-member-part">{PART_ICON[m.part]} {m.part}</span>
                  {dominantTheme(m) && <span className="st-member-theme">{THEME_LABEL[dominantTheme(m)!]}</span>}
                </button>
              ))}
              {members.length < 6 && (
                <button type="button" className="st-add" onClick={addMember}>＋<span>Add</span></button>
              )}
            </div>

            {/* Dresser for the selected member */}
            {cur && (
              <div className="st-dresser">
                <div className="st-preview">
                  <BandAvatar member={cur} size={150} />
                  <button className="btn ghost sm" style={{ width: "auto", marginTop: 6 }}
                    onClick={() => removeMember(sel)}>Remove</button>
                </div>
                <div className="st-controls">
                  <div className="st-namepart">
                    <input className="st-name" type="text" value={cur.name}
                      onChange={(e) => patch({ name: e.target.value })} placeholder="Name" />
                    <div className="st-parts">
                      {PARTS.map((p) => (
                        <button key={p} type="button"
                          className={"st-part" + (cur.part === p ? " on" : "")}
                          onClick={() => patch({ part: p })}>{PART_ICON[p]}</button>
                      ))}
                    </div>
                  </div>
                  <SlotRow label="Skin" items={SKINS} selected={cur.skin} onPick={(id) => patch({ skin: id })} />
                  <SlotRow label="Hair" items={HAIR_STYLES} selected={cur.hair} onPick={(id) => patch({ hair: id })} />
                  <SlotRow label="Hair color" items={HAIR_COLORS} selected={cur.hairColor} onPick={(id) => patch({ hairColor: id })} />
                  <SlotRow label="Top" items={TOPS} selected={cur.top} onPick={(id) => patch({ top: id })} />
                  <SlotRow label="Bottom" items={BOTTOMS} selected={cur.bottom} onPick={(id) => patch({ bottom: id })} />
                  <SlotRow label="Shades" items={SHADES} selected={cur.shades} onPick={(id) => patch({ shades: id })} />
                  <SlotRow label="Hat" items={HATS} selected={cur.hat} onPick={(id) => patch({ hat: id })} />
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
