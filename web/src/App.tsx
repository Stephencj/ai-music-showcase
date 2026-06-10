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

      {/* All three screens stay mounted so switching tabs never loses your
          in-progress work; only the active one is shown. */}
      <div className={"tab-pane" + (tab === "generate" ? "" : " hidden")}>
        <GenerateScreen initialSpec={editSpec} onSpecConsumed={() => setEditSpec(null)} />
      </div>
      <div className={"tab-pane" + (tab === "compose" ? "" : " hidden")}>
        <ComposeScreen
          active={tab === "compose"}
          onEditInGenerate={(spec) => { setEditSpec(spec); setTab("generate"); }}
        />
      </div>
      <div className={"tab-pane" + (tab === "practice" ? "" : " hidden")}>
        <PracticeScreen isActive={tab === "practice"} />
      </div>

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
