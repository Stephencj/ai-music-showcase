// Standalone dress-up app shell — the entire app is the dress-up game, with no
// band-career, no backend, no other tabs. Manages its own lineup in
// localStorage. This is what ships as the offline Android app / static site.
import { useEffect, useState } from "react";
import DressUp from "./DressUp";
import { type Member, normalizeMember, defaultMember } from "./wardrobe";

const KEY = "dressup.lineup";

function load(): Member[] {
  try {
    const a = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(a) ? a.map(normalizeMember) : [];
  } catch { return []; }
}

export default function DressUpStandalone() {
  const [members, setMembers] = useState<Member[]>(() => {
    const m = load();
    return m.length ? m : [defaultMember("Vocals", "Star")];
  });
  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(members)); }, [members]);

  return <DressUp members={members} onChange={setMembers} onClose={() => {}} hideClose />;
}
