import { useState } from "react";
import GenerateScreen from "./components/GenerateScreen";
import ComposeScreen from "./components/ComposeScreen";
import type { BlockSpec } from "./types";

type Tab = "generate" | "compose";

export default function App() {
  const [tab, setTab] = useState<Tab>("generate");
  const [editSpec, setEditSpec] = useState<BlockSpec | null>(null);

  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">♪</div>
        <div>
          <h1>Music Producer</h1>
          <div className="sub">Generate · Block · Compose</div>
        </div>
      </header>

      {tab === "generate" ? (
        <GenerateScreen initialSpec={editSpec} onSpecConsumed={() => setEditSpec(null)} />
      ) : (
        <ComposeScreen
          onEditInGenerate={(spec) => { setEditSpec(spec); setTab("generate"); }}
        />
      )}

      <nav className="tabbar">
        <button className={tab === "generate" ? "on" : ""} onClick={() => setTab("generate")}>
          <span className="ico">🎲</span>Generate
        </button>
        <button className={tab === "compose" ? "on" : ""} onClick={() => setTab("compose")}>
          <span className="ico">🎬</span>Compose
        </button>
      </nav>
    </div>
  );
}
