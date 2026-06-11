import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Register the service worker → installable PWA on Android/iOS + cached shell.
// Also drive auto-update so a new deploy reaches the installed PWA without a
// manual cache-clear: check for updates on load (and when refocused), tell a
// freshly-installed worker to activate immediately, and reload the page once
// when the new worker takes control so it picks up the new bundle.
if ("serviceWorker" in navigator) {
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (reloading) return;
    reloading = true;
    window.location.reload();
  });

  window.addEventListener("load", () => {
    navigator.serviceWorker.register("sw.js").then((reg) => {
      const promote = (w: ServiceWorker | null) => {
        if (w && navigator.serviceWorker.controller) w.postMessage("SKIP_WAITING");
      };
      reg.update().catch(() => {});
      promote(reg.waiting);
      reg.addEventListener("updatefound", () => {
        const nw = reg.installing;
        if (!nw) return;
        nw.addEventListener("statechange", () => {
          if (nw.state === "installed") promote(nw);
        });
      });
      // Re-check for a new build whenever the user returns to the app.
      document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") reg.update().catch(() => {});
      });
    }).catch(() => {});
  });
}
