// The in-game menu's own page (Game Night's see-through window over the game; src-tauri/src/ingame.rs).
// Fonts are bundled with the app (nothing loaded from other sites).
import { mount } from "svelte";
import "@fontsource/inter/400.css";
import "@fontsource/inter/600.css";
import "@fontsource/press-start-2p";
import "@fontsource/vt323";
import InGameMenu from "./InGameMenu.svelte";

// No right-click menu: this is an app, not a web page.
window.addEventListener("contextmenu", (e) => e.preventDefault());

export default mount(InGameMenu, { target: document.getElementById("menu")! });
