import { useState } from "react";
import GenerateScreen from "./components/GenerateScreen";
import ComposeScreen from "./components/ComposeScreen";
import PracticeScreen from "./components/PracticeScreen";
import type { BlockSpec } from "./types";

type Tab = "generate" | "compose" | "practice";

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
      ) : tab === "compose" ? (
        <ComposeScreen
          onEditInGenerate={(spec) => { setEditSpec(spec); setTab("generate"); }}
        />
      ) : (
        <PracticeScreen />
      )}

      <nav className="tabbar">
        <button className={tab === "generate" ? "on" : ""} onClick={() => setTab("generate")}>
          <span className="ico">🎲</span>Generate
        </button>
        <button className={tab === "compose" ? "on" : ""} onClick={() => setTab("compose")}>
          <span className="ico">🎬</span>Compose
        </button>
        <button className={tab === "practice" ? "on" : ""} onClick={() => setTab("practice")}>
          <span className="ico">🎹</span>Practice
        </button>
      </nav>
    </div>
  );
}
