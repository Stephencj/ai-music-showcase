import GenerateScreen from "./components/GenerateScreen";

export default function App() {
  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">♪</div>
        <div>
          <h1>AI Music Studio</h1>
          <div className="sub">Generate · Block · Compose</div>
        </div>
      </header>
      <GenerateScreen />
    </div>
  );
}
