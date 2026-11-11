import "./styles/style.css";
import "./styles/tugun.css";
import "virtual:tugun-app";

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => { navigator.serviceWorker.register("/sw.js").catch(() => {}); });
}
