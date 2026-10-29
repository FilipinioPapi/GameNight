<script lang="ts">
  import Brand from "../components/Brand.svelte";
  import { app } from "../lib/state.svelte";
  import { VERSION } from "../lib/version";

  // Milestone 1 preview: the real Discord sign-in arrives with the Game Night server (milestone 2).
  function signIn() {
    app.user = { id: "preview", name: "Player 1" };
    app.history = [];
    app.route = app.settings.firstRunDone ? { name: "menu" } : { name: "firstrun", step: 2 };
  }
</script>

<div class="page">
  <Brand size="xl" />
  <div class="card">
    <div class="title">Sign in to play</div>
    <div class="step"><span class="num">1</span><span>Click the button. Discord opens in your web browser.</span></div>
    <div class="step"><span class="num">2</span><span>Press <b>Authorize</b>. Game Night only sees your Discord name and picture.</span></div>
    <div class="step"><span class="num">3</span><span>Come back here. You stay signed in, even offline.</span></div>
    <button class="discord" onclick={signIn}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M19.5 5.5A16 16 0 0 0 15.6 4.3l-.5 1a14.7 14.7 0 0 0-6.2 0l-.5-1a16 16 0 0 0-3.9 1.2C2 9.2 1.3 12.8 1.6 16.3a16 16 0 0 0 4.8 2.4l1-1.6a10.4 10.4 0 0 1-1.6-.8l.4-.3a11.4 11.4 0 0 0 11.6 0l.4.3c-.5.3-1 .6-1.6.8l1 1.6a16 16 0 0 0 4.8-2.4c.4-4-.6-7.6-2.9-10.8zM8.7 14.2c-.9 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2zm6.6 0c-.9 0-1.7-.9-1.7-2s.8-2 1.7-2 1.7.9 1.7 2-.8 2-1.7 2z"/></svg>
      Log in with Discord
    </button>
    <div class="preview">Preview build: Discord sign-in is switched on in the next update. For now this button just lets you look around.</div>
    <div class="help">Not working? You need the <b>Game Night</b> role on Jayden's Discord server. Ask Jayden to add it.</div>
  </div>
  <div class="foot">Private to friends on Jayden's Discord · v{VERSION}</div>
</div>

<style>
  .page { height: 100%; background: radial-gradient(ellipse at 50% 30%, #2a1718 0%, var(--bg) 60%); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 28px; }
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
  .foot { font-size: 12px; color: var(--muted-2); }
</style>
