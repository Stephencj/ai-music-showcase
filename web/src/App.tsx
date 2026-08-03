import { useState } from "react";
import GenerateScreen from "./components/GenerateScreen";
import ComposeScreen from "./components/ComposeScreen";
import PracticeScreen from "./components/PracticeScreen";
import BandScreen from "./components/BandScreen";
import LibraryScreen from "./components/LibraryScreen";
import type { BlockSpec } from "./types";
import DressUpGallery from "./dressup/DressUpGallery";

type Tab = "generate" | "compose" | "practice" | "band" | "library";

export default function App() {
  if (typeof location !== "undefined" && new URLSearchParams(location.search).has("dressupgallery")) {
    return <DressUpGallery />;
  }
  // Deep link: ?block=<name> opens that block straight into Practice (used by
  // the "Open in Music app" button in the LocalAIClient iOS app).
  const deepBlock = typeof location !== "undefined"
    ? new URLSearchParams(location.search).get("block")
    : null;
  const [tab, setTab] = useState<Tab>(deepBlock ? "practice" : "generate");
  const [editSpec, setEditSpec] = useState<BlockSpec | null>(null);
  const [practiceBlock, setPracticeBlock] = useState<string | null>(deepBlock);

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
        <PracticeScreen isActive={tab === "practice"} requestBlock={practiceBlock}
          onBlockConsumed={() => setPracticeBlock(null)} />
      </div>
      <div className={"tab-pane" + (tab === "band" ? "" : " hidden")}>
        <BandScreen isActive={tab === "band"} onWriteSong={() => setTab("generate")}
          onOpenPractice={(block) => { setPracticeBlock(block); setTab("practice"); }} />
      </div>
      <div className={"tab-pane" + (tab === "library" ? "" : " hidden")}>
        <LibraryScreen isActive={tab === "library"}
          onOpen={(block) => { setPracticeBlock(block); setTab("practice"); }} />
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
        <button className={tab === "band" ? "on" : ""} onClick={() => setTab("band")}>
          <span className="ico">🎸</span>Band
        </button>
        <button className={tab === "library" ? "on" : ""} onClick={() => setTab("library")}>
          <span className="ico">📚</span>Library
        </button>
      </nav>
    </div>
  );
}
