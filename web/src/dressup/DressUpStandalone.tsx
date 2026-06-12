// Standalone dress-up app shell — the entire app is the dress-up game, with no
// band-career, no backend, no other tabs. Manages its own lineup in
// localStorage. This is what ships as the offline Android app / static site.
import { useEffect, useState } from "react";
import DressUp from "./DressUp";
import Performance from "./Performance";
import { type Member, normalizeMember, defaultMember } from "./wardrobe";

const KEY = "dressup.lineup";

function load(): Member[] {
  try {
    const a = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(a) ? a.map(normalizeMember) : [];
  } catch { return []; }
}

const bumpStar = () => {
  const n = Number(localStorage.getItem("dressup.stars") || 0) + 1;
  localStorage.setItem("dressup.stars", String(n));
};

export default function DressUpStandalone() {
  const [members, setMembers] = useState<Member[]>(() => {
    const m = load();
    return m.length ? m : [defaultMember("Vocals", "Star")];
  });
  const [show, setShow] = useState(false);
  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(members)); }, [members]);

  if (show) {
    return <Performance members={members} onComplete={bumpStar} onClose={() => setShow(false)} />;
  }
  return <DressUp members={members} onChange={setMembers} onClose={() => {}} hideClose
    onPerform={() => setShow(true)} />;
}
