<script lang="ts">
  import { app } from "./lib/state.svelte";
  import Login from "./screens/Login.svelte";
  import FirstRun from "./screens/FirstRun.svelte";
  import MainMenu from "./screens/MainMenu.svelte";
  import Library from "./screens/Library.svelte";
  import GamePage from "./screens/GamePage.svelte";
  import Settings from "./screens/Settings.svelte";
  import CouchPlay from "./screens/CouchPlay.svelte";
  import Lobby from "./screens/Lobby.svelte";
  import JoinCode from "./screens/JoinCode.svelte";
  import UpdateBox from "./components/UpdateBox.svelte";

  const r = $derived(app.route);
</script>

{#if app.ready}
  {#key r.name}<div class="screen-fade">
  {#if r.name === "login"}<Login />
  {:else if r.name === "firstrun"}<FirstRun step={r.step} />
  {:else if r.name === "menu"}<MainMenu />
  {:else if r.name === "library"}<Library console={r.console} host={r.host ?? false} />
  {:else if r.name === "game"}<GamePage id={r.id} />
  {:else if r.name === "settings"}<Settings tab={r.tab} console={r.console} />
  {:else if r.name === "couch"}<CouchPlay />
  {:else if r.name === "lobby"}<Lobby />
  {:else if r.name === "join"}<JoinCode code={r.code ?? ""} />
  {/if}
  </div>{/key}
  <UpdateBox />
{/if}
