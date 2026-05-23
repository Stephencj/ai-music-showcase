import { useState } from "react";
import GenerateScreen from "./components/GenerateScreen";
import ComposeScreen from "./components/ComposeScreen";

type Tab = "generate" | "compose";

export default function App() {
  const [tab, setTab] = useState<Tab>("generate");
  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">♪</div>
        <div>
          <h1>AI Music Studio</h1>
          <div className="sub">Generate · Block · Compose</div>
        </div>
      </header>

      {tab === "generate" ? <GenerateScreen /> : <ComposeScreen />}

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
