import { useState } from "react";
import CreateScreen, { type CreateMode } from "./components/CreateScreen";
import PracticeScreen from "./components/PracticeScreen";
import BandScreen from "./components/BandScreen";
import LibraryScreen from "./components/LibraryScreen";
import type { BlockSpec } from "./types";
import DressUpGallery from "./dressup/DressUpGallery";

type Tab = "create" | "library" | "practice" | "band";

export default function App() {
  if (typeof location !== "undefined" && new URLSearchParams(location.search).has("dressupgallery")) {
    return <DressUpGallery />;
  }
  // Deep link: ?block=<name> opens that block straight into Practice (used by
  // the "Open in Music app" button in the LocalAIClient iOS app).
  const deepBlock = typeof location !== "undefined"
    ? new URLSearchParams(location.search).get("block")
    : null;
  const [tab, setTab] = useState<Tab>(deepBlock ? "practice" : "create");
  // Create holds the song workspace (Session / Timeline) plus the full
  // Generate form ("advanced") and the block builder ("blocks", ex-Compose).
  const [createMode, setCreateMode] = useState<CreateMode>("session");
  const [editSpec, setEditSpec] = useState<BlockSpec | null>(null);
  const [practiceBlock, setPracticeBlock] = useState<string | null>(deepBlock);

  return (
    <div className={"app" + (tab === "create" ? " app-create" : "")}>
      {tab !== "create" && (
        <header className="topbar">
          <div className="logo">♪</div>
          <div>
            <h1>Music Producer</h1>
            <div className="sub">Create · Library · Practice · Band</div>
          </div>
        </header>
      )}

      {/* All screens stay mounted so switching tabs never loses your
          in-progress work; only the active one is shown. */}
      <div className={"tab-pane" + (tab === "create" ? "" : " hidden")}>
        <CreateScreen active={tab === "create"} mode={createMode} setMode={setCreateMode}
          editSpec={editSpec} onSpecConsumed={() => setEditSpec(null)}
          onEditInGenerate={(spec) => { setEditSpec(spec); setCreateMode("advanced"); }} />
      </div>
      <div className={"tab-pane" + (tab === "library" ? "" : " hidden")}>
        <LibraryScreen isActive={tab === "library"}
          onOpen={(block) => { setPracticeBlock(block); setTab("practice"); }} />
      </div>
      <div className={"tab-pane" + (tab === "practice" ? "" : " hidden")}>
        <PracticeScreen isActive={tab === "practice"} requestBlock={practiceBlock}
          onBlockConsumed={() => setPracticeBlock(null)} />
      </div>
      <div className={"tab-pane" + (tab === "band" ? "" : " hidden")}>
        <BandScreen isActive={tab === "band"}
          onWriteSong={() => { setCreateMode("advanced"); setTab("create"); }}
          onOpenPractice={(block) => { setPracticeBlock(block); setTab("practice"); }} />
      </div>

      <nav className="tabbar">
        <button className={tab === "create" ? "on" : ""} onClick={() => setTab("create")}>
          <span className="ico">✨</span>Create
        </button>
        <button className={tab === "library" ? "on" : ""} onClick={() => setTab("library")}>
          <span className="ico">📚</span>Library
        </button>
        <button className={tab === "practice" ? "on" : ""} onClick={() => setTab("practice")}>
          <span className="ico">🎹</span>Practice
        </button>
        <button className={tab === "band" ? "on" : ""} onClick={() => setTab("band")}>
          <span className="ico">🎸</span>Band
        </button>
      </nav>
    </div>
  );
}
