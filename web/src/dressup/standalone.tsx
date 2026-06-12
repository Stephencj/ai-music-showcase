// Entry point for the standalone offline dress-up build (Android app / static
// site). Mounts only the dress-up game and registers an offline service worker.
import { createRoot } from "react-dom/client";
import DressUpStandalone from "./DressUpStandalone";
import "../styles.css";

createRoot(document.getElementById("root")!).render(<DressUpStandalone />);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").catch(() => {});
  });
}
