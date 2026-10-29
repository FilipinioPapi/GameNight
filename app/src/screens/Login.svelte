<script lang="ts">
  import Brand from "../components/Brand.svelte";
  import { app } from "../lib/state.svelte";
  import { inTauri } from "../lib/settings";
  import { setServer, shortAddress } from "../lib/account";
  import { VERSION } from "../lib/version";

  // Outside the Windows app (only while building screens) there's no Discord: just look around.
  function preview() {
    app.signedIn({ id: "preview", name: "Player 1" });
  }

  let editing = $state(false);
  let address = $state("");
  let addressError = $state("");
  function editServer() {
    address = app.server;
    addressError = "";
    editing = true;
  }
  const focus = (el: HTMLInputElement) => {
    el.focus();
    el.select();
  };
  async function saveServer() {
    try {
      app.server = await setServer(address);
      editing = false;
    } catch (e) {
      addressError = String(e);
    }
  }
</script>

<div class="page">
  <Brand size="xl" />
  <div class="card">
    <div class="title">Sign in to play</div>
    <div class="step"><span class="num">1</span><span>Click the button. Discord opens in your web browser.</span></div>
    <div class="step"><span class="num">2</span><span>Press <b>Authorize</b>. Game Night only sees your Discord name and picture.</span></div>
    <div class="step"><span class="num">3</span><span>Come back here. You stay signed in, even offline.</span></div>
    {#if !inTauri}
      <button class="discord" onclick={preview}>{@render logo()}Log in with Discord</button>
      <div class="preview">Screen preview: this only lets you look around. Sign-in works in the Windows app.</div>
    {:else if app.signIn.waiting}
      <div class="waiting"><span class="spin" aria-hidden="true"></span><span>Finish signing in in your web browser. If your browser asks, allow it to open Game Night.</span></div>
      <button class="btn" onclick={() => app.startSignIn()}>Open the browser again</button>
    {:else}
      <button class="discord" onclick={() => app.startSignIn()}>{@render logo()}Log in with Discord</button>
    {/if}
    {#if app.signIn.error}<div class="help" role="alert">{app.signIn.error}</div>{/if}
    <div class="help">Not working? You need the <b>Game Night</b> role on Jayden's Discord server. Ask Jayden to add it.</div>
    {#if inTauri && !app.signIn.waiting}
      {#if editing}
        <form class="server" onsubmit={(e) => { e.preventDefault(); void saveServer(); }}>
          <label for="addr">Game Night server</label>
          <div class="row"><input id="addr" bind:value={address} use:focus spellcheck="false" autocomplete="off" /><button class="btn small" type="submit">Save</button><button class="btn small" type="button" onclick={() => (editing = false)}>Cancel</button></div>
          {#if addressError}<span class="bad">{addressError}</span>{/if}
        </form>
      {:else}
        <div class="server-line">Server: {shortAddress(app.server)} · <button class="link" onclick={editServer}>Change</button></div>
      {/if}
    {/if}
  </div>
  <div class="foot">Private to friends on Jayden's Discord · v{VERSION}</div>
</div>

{#snippet logo()}
  <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19.5 5.5A16 16 0 0 0 15.6 4.3l-.5 1a14.7 14.7 0 0 0-6.2 0l-.5-1a16 16 0 0 0-3.9 1.2C2 9.2 1.3 12.8 1.6 16.3a16 16 0 0 0 4.8 2.4l1-1.6a10.4 10.4 0 0 1-1.6-.8l.4-.3a11.4 11.4 0 0 0 11.6 0l.4.3c-.5.3-1 .6-1.6.8l1 1.6a16 16 0 0 0 4.8-2.4c.4-4-.6-7.6-2.9-10.8zM8.7 14.2c-.9 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2zm6.6 0c-.9 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2z"/></svg>
{/snippet}

<style>
  .page { height: 100%; overflow: auto; padding: 24px 0; background: radial-gradient(ellipse at 50% 30%, #2a1718 0%, var(--bg) 60%); display: flex; flex-direction: column; align-items: center; justify-content: safe center; gap: 22px; }
  .card { width: 460px; border-radius: 16px; background: var(--panel); border: 1px solid var(--line); padding: 24px; display: flex; flex-direction: column; gap: 18px; box-shadow: 0 20px 50px rgba(0, 0, 0, 0.5); }
  .title { font-size: 18px; font-weight: 700; }
  .step { display: flex; gap: 14px; align-items: flex-start; font-size: 14px; line-height: 1.5; color: var(--text-2); }
  .step b { color: #fff; }
  .num { width: 32px; height: 32px; border-radius: 50%; background: var(--btn); border: 1px solid var(--line-2); display: inline-flex; align-items: center; justify-content: center; font-size: 14px; font-weight: 700; flex-shrink: 0; margin-top: -4px; }
  .discord { height: 52px; border-radius: 10px; border: 0; background: var(--discord); color: #fff; font-size: 16px; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; gap: 10px; }
  .discord:hover { background: #6b76f5; }
  .preview { border-radius: 10px; padding: 12px 14px; font-size: 13px; background: #2a1f14; border: 1px solid var(--amber); color: var(--text-2); }
  .help { border-radius: 10px; padding: 12px 14px; font-size: 13px; background: #3a1416; border: 1px solid var(--red-2); color: var(--text-2); }
  .help b { color: #fff; }
  .waiting { display: flex; gap: 12px; align-items: center; border-radius: 10px; padding: 14px; font-size: 14px; line-height: 1.5; background: var(--btn); border: 1px solid var(--line-2); color: var(--text-2); }
  .spin { width: 20px; height: 20px; border-radius: 50%; border: 3px solid var(--line-2); border-top-color: var(--discord); animation: spin 0.9s linear infinite; flex-shrink: 0; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .server-line { font-size: 12px; color: var(--muted); text-align: center; }
  .link { border: 0; background: none; color: var(--link); font-size: 12px; padding: 0; text-decoration: underline; cursor: pointer; }
  .server { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--muted); }
  .server .row { display: flex; gap: 8px; }
  .server input { flex: 1; min-width: 0; height: 34px; border-radius: 8px; border: 1px solid var(--line-2); background: var(--bg); color: var(--text); padding: 0 10px; font: inherit; font-size: 13px; }
  .bad { color: var(--link); }
  .foot { font-size: 12px; color: var(--muted-2); }
</style>
