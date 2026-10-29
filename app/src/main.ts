import { mount } from "svelte";
// Fonts are bundled with the app (no internet needed, nothing loaded from other sites).
import "@fontsource/inter/400.css";
import "@fontsource/inter/500.css";
import "@fontsource/inter/600.css";
import "@fontsource/inter/700.css";
import "@fontsource/luckiest-guy";
import "@fontsource/press-start-2p";
import "@fontsource/pixelify-sans/700.css";
import "@fontsource/orbitron/900.css";
import "@fontsource/silkscreen";
import "@fontsource/monoton";
import "@fontsource/audiowide";
import "@fontsource/russo-one";
import "@fontsource/righteous";
import "@fontsource/michroma";
import "./app.css";
import App from "./App.svelte";
import { app } from "./lib/state.svelte";
import { startGamepad } from "./lib/gamepad";

// Escape goes back, like B on a controller.
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") app.back();
});
// No right-click menu: this is an app, not a web page.
window.addEventListener("contextmenu", (e) => e.preventDefault());

void app.init();
startGamepad();

export default mount(App, { target: document.getElementById("app")! });
