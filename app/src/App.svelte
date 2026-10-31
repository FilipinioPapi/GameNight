<script lang="ts">
  import { app } from "./lib/state.svelte";
  import Login from "./screens/Login.svelte";
  import FirstRun from "./screens/FirstRun.svelte";
  import MainMenu from "./screens/MainMenu.svelte";
  import Library from "./screens/Library.svelte";
  import GamePage from "./screens/GamePage.svelte";
  import Settings from "./screens/Settings.svelte";
  import UpdateBox from "./components/UpdateBox.svelte";

  const r = $derived(app.route);
</script>

{#if app.ready}
  {#key r.name}<div class="screen-fade">
  {#if r.name === "login"}<Login />
  {:else if r.name === "firstrun"}<FirstRun step={r.step} />
  {:else if r.name === "menu"}<MainMenu />
  {:else if r.name === "library"}<Library console={r.console} />
  {:else if r.name === "game"}<GamePage id={r.id} />
  {:else if r.name === "settings"}<Settings tab={r.tab} console={r.console} />
  {/if}
  </div>{/key}
  <UpdateBox />
{/if}
