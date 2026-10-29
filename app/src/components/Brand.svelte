<script lang="ts">
  // The Game Night lockup: cat logo + "GAME NIGHT, POWERED BY JAYDENATER BOT".
  let { size = "md", words = true }: { size?: "md" | "lg" | "xl"; words?: boolean } = $props();
</script>

<div class="brand {size}">
  <img class="cat" src="/brand/logo.gif" alt="" />
  {#if words}
    <div class="words">
      <span class="wp">GAME NIGHT</span>
      <span class="powered"><span class="pb">POWERED BY</span><span class="jd">JAYDENATER</span><span class="bot">BOT</span></span>
    </div>
  {/if}
</div>

<style>
  .brand { display: flex; align-items: center; gap: 16px; }
  .cat { border-radius: 25%; border: 3px solid var(--red); object-fit: cover; }
  .words { display: flex; flex-direction: column; gap: 4px; align-items: flex-start; }
  .wp {
    font-family: "Luckiest Guy", Inter, sans-serif; color: var(--red); line-height: 1; letter-spacing: 0.03em;
    -webkit-text-stroke: var(--wps) #000; paint-order: stroke fill; text-shadow: 0 var(--wpd) 0 #000; font-size: var(--w);
  }
  .powered { display: inline-flex; align-items: center; gap: calc(var(--w) * 0.18); line-height: 1; margin-top: calc(var(--w) * 0.06); }
  .pb { font-weight: 700; letter-spacing: 0.14em; color: var(--muted); font-size: max(7.5px, calc(var(--w) * 0.25)); }
  .jd {
    font-family: "Luckiest Guy", Inter, sans-serif; color: #fff; letter-spacing: 0.03em; font-size: calc(var(--w) * 0.5);
    -webkit-text-stroke: max(2px, calc(var(--w) * 0.1)) #000; paint-order: stroke fill; text-shadow: 0 max(1px, calc(var(--w) * 0.035)) 0 #000;
  }
  .bot {
    font-family: "Luckiest Guy", Inter, sans-serif; color: #fff; background: var(--red); border: max(1px, calc(var(--w) * 0.03)) solid #000;
    border-radius: 999px; letter-spacing: 0.06em; line-height: 1; font-size: calc(var(--w) * 0.225);
    padding: calc(var(--w) * 0.075) calc(var(--w) * 0.135) calc(var(--w) * 0.0375);
  }
  .md { --w: 24px; --wps: 3.6px; --wpd: 1.7px; }
  .md .cat { width: 44px; height: 44px; border-width: 2px; }
  .lg { --w: 52px; --wps: 7.5px; --wpd: 3.4px; }
  .lg .cat { width: 96px; height: 96px; }
  .xl { --w: 64px; --wps: 9px; --wpd: 4px; flex-direction: column; gap: 20px; }
  .xl .words { align-items: center; gap: 12px; }
  .xl .cat { width: 120px; height: 120px; }
</style>
