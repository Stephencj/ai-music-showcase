import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";

// A modular field control: renders as a compact button showing the current
// selection, and on tap opens a popup with a (optionally searchable) list. This
// is the list-picker sibling of CircleOfFifths (the visual key picker) — both
// share the same popup chrome (.pf-* mirrors .cof-*), so every "field" in the
// app reads as a button that opens a focused chooser, mobile and desktop alike.

export interface PickerOption {
  id: string;
  label: string;
  sub?: string;     // small secondary line (e.g. tempo, note count)
  group?: string;   // optional section header to bucket options under
  icon?: ReactNode; // leading glyph (e.g. an instrument icon)
}

export default function PickerField({
  value, options, onChange, label, placeholder, icon,
  searchable, disabled, title, className, fullWidth = true,
}: {
  value: string;
  options: PickerOption[];
  onChange: (id: string) => void;
  label?: string;                 // popup title (defaults to placeholder/“Select”)
  placeholder?: string;           // button text when nothing is selected
  icon?: ReactNode;               // leading glyph on the button
  searchable?: boolean;           // force on/off (default: auto when >8 options)
  disabled?: boolean;
  title?: string;                 // native tooltip on the button
  className?: string;             // extra class on the trigger button
  fullWidth?: boolean;            // stretch button to container (default true)
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const current = options.find((o) => o.id === value);
  const wantSearch = searchable ?? options.length > 8;
  const grouped = options.some((o) => o.group);

  const filtered = useMemo(() => {
    const s = q.trim().toLowerCase();
    if (!s) return options;
    return options.filter((o) =>
      o.label.toLowerCase().includes(s)
      || o.sub?.toLowerCase().includes(s)
      || o.group?.toLowerCase().includes(s));
  }, [q, options]);

  // Bucket into groups (preserving first-seen order) when any option is grouped.
  const sections = useMemo(() => {
    if (!grouped) return [{ group: "", items: filtered }];
    const order: string[] = [];
    const map = new Map<string, PickerOption[]>();
    for (const o of filtered) {
      const g = o.group ?? "";
      if (!map.has(g)) { map.set(g, []); order.push(g); }
      map.get(g)!.push(o);
    }
    return order.map((g) => ({ group: g, items: map.get(g)! }));
  }, [filtered, grouped]);

  useEffect(() => {
    if (!open) return;
    setQ("");
    const t = setTimeout(() => searchRef.current?.focus(), 40);
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => { clearTimeout(t); window.removeEventListener("keydown", onKey); };
  }, [open]);

  return (
    <>
      <button type="button" disabled={disabled} title={title}
        className={"pickfield" + (fullWidth ? " pf-full" : "") + (className ? " " + className : "")}
        onClick={() => setOpen(true)}>
        {(icon ?? current?.icon) && <span className="pf-icon">{icon ?? current?.icon}</span>}
        <span className="pf-val">{current?.label ?? placeholder ?? "Select…"}</span>
        <span className="pf-caret">▾</span>
      </button>
      {open && (
        <div className="cof-backdrop" onClick={() => setOpen(false)}>
          <div className="pf-popup" onClick={(e) => e.stopPropagation()}>
            <div className="cof-head">
              <span className="cof-title">{label ?? placeholder ?? "Select"}</span>
              <button className="cof-close" onClick={() => setOpen(false)} aria-label="Close">✕</button>
            </div>
            {wantSearch && (
              <input ref={searchRef} className="pf-search" type="text" placeholder="Search…"
                value={q} onChange={(e) => setQ(e.target.value)} />
            )}
            <div className="pf-list">
              {sections.map((sec) => (
                <div key={sec.group} className="pf-group">
                  {sec.group && <div className="pf-group-label">{sec.group}</div>}
                  {sec.items.map((o) => (
                    <button key={o.id} type="button"
                      className={"pf-opt" + (o.id === value ? " sel" : "")}
                      onClick={() => { onChange(o.id); setOpen(false); }}>
                      {o.icon && <span className="pf-opt-ic">{o.icon}</span>}
                      <span className="pf-opt-label">{o.label}</span>
                      {o.sub && <span className="pf-opt-sub">{o.sub}</span>}
                      {o.id === value && <span className="pf-opt-check">✓</span>}
                    </button>
                  ))}
                </div>
              ))}
              {filtered.length === 0 && <div className="pf-empty">No matches</div>}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
