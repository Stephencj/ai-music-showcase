// Entry point for the standalone offline dress-up build (Android app / static
// site). Mounts only the dress-up game and registers an offline service worker.
import { createRoot } from "react-dom/client";
import DressUpStandalone from "./DressUpStandalone";
import "../styles.css";

createRoot(document.getElementById("root")!).render(<DressUpStandalone />);

// Only register the service worker for a real web/PWA deploy. In the native
// Android WebView the app is served from bundled assets (appassets origin /
// file://) — it's already offline, and a SW there just risks serving a stale
// cached shell after an app update (→ blank screen). Skip it.
const nativeShell = location.protocol === "file:" || /androidplatform|capacitor|localhost/.test(location.hostname);
if ("serviceWorker" in navigator) {
  if (nativeShell) {
    navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister())).catch(() => {});
  } else {
    window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
  }
}
