<script lang="ts">
  // The lobby (approved boards CQ4 and CQ6): the code, open / closed, the game playing live in a box
  // (the Windows side keeps the game's own window over the empty box here), and 8 seats: 4 to play,
  // 4 to watch. Drop-outs never pause the game: the seat is held, the host decides what happens to it,
  // and a player whose own link dropped can get back in with the same code.
  import { tick } from "svelte";
  import Avatar from "../components/Avatar.svelte";
  import ButtonGuide, { type GuideItem } from "../components/ButtonGuide.svelte";
  import { app } from "../lib/state.svelte";
  import { couch, clockOf, playersFor, type CouchUser, type Lobby, type Seat } from "../lib/couch.svelte";
  import { consoleById } from "../lib/consoles";
  import { listGames, type Game } from "../lib/library";
  import { moveFocus, useScreenButtons, type Dir } from "../lib/gamepad";
  import { PAD_NAME } from "../lib/pads";
  import { inTauri } from "../lib/settings";

  let games = $state<Game[]>([]);
  $effect(() => {
    listGames().then((g) => (games = g));
  });
  $effect(() => {
    void couch.refresh();
  });

  // A clock for the held-seat countdowns.
  let now = $state(Date.now());
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 500);
    return () => clearInterval(t);
  });

  const L = $derived(couch.lobby);
  const isHost = $derived(L?.you.role === "host");
  const youId = $derived(L?.you.id ?? "");
  const max = $derived(L ? playersFor(L.game.id, games) : 4);
  const playing = $derived(L ? L.seats.filter((s) => s.user).length : 0);
  const freeSeat = $derived(L?.seats.find((s) => !s.user)?.n ?? null);
  const first = (u: CouchUser) => u.name.split(/\s/)[0];
  const NAME = (u: CouchUser) => first(u).toUpperCase();
  const COLOURS = ["#5865f2", "#2a5ab8", "#2a8a6a", "#c0662a", "#7a3a8a", "#b8862a"];
  const colour = (u: CouchUser) => COLOURS[[...u.id].reduce((a, c) => a + c.charCodeAt(0), 0) % COLOURS.length];

  // ---- The 8 rows: 4 player seats, then 4 watching places ----
  type Row = { kind: "p" | "w"; lab: string; seat?: Seat; user: CouchUser | null; held: boolean; left: number };
  const rows = $derived.by<Row[]>(() => {
    if (!L) return [];
    const out: Row[] = L.seats.slice(0, 4).map((s) => ({ kind: "p", lab: `P${s.n}`, seat: s, user: s.user, held: s.status === "held", left: couch.heldLeft(s, now) }));
    for (let i = 0; i < 4; i++) out.push({ kind: "w", lab: "WATCH", user: L.watchers[i] ?? null, held: false, left: 0 });
    return out;
  });
  function sub(r: Row): string {
    if (!r.user) return r.kind === "p" ? "Free player seat" : "Free watching seat";
    if (r.held) return `Dropped out · seat held ${clockOf(r.left)}`;
    if (r.user.id === youId) return app.pad.connected ? `${PAD_NAME[app.pad.type]} pad` : "You";
    if (r.kind === "p") return "Playing";
    return freeSeat ? `Watching · can switch to P${freeSeat} any time` : "Watching";
  }
  function tag(r: Row): { text: string; cls: string } | null {
    if (!r.user || r.kind === "w") return null;
    if (r.held) return { text: "HELD", cls: "held" };
    if (r.seat?.n === 1) return { text: "HOST", cls: "host" };
    return { text: "PLAYING", cls: "ok" };
  }
  function hintFor(r: Row | undefined): string {
    if (!L || !r) return "";
    const code = L.code;
    if (r.held && r.user) return isHost ? `${NAME(r.user)} DROPPED OUT. PRESS A FOR SEAT OPTIONS` : `${NAME(r.user)} DROPPED OUT. THE SEAT IS HELD ${clockOf(r.left)}`;
    if (r.user?.id === youId) {
      if (isHost) return "THAT IS YOU. Y GOES FULL SCREEN";
      return r.kind === "w" ? "YOU ARE WATCHING. X TO PLAY ANY TIME" : "THAT IS YOU. X TO WATCH INSTEAD";
    }
    if (r.user) {
      if (r.seat?.n === 1) return `${NAME(r.user)} IS HOSTING`;
      return `${NAME(r.user)} IS ${r.kind === "p" ? "PLAYING" : "WATCHING"}`;
    }
    if (r.kind === "p") {
      if (!isHost) return `${r.lab} IS FREE. ANYONE WATCHING CAN TAKE IT`;
      return L.watchers[0] ? `${r.lab} IS FREE. ${NAME(L.watchers[0])} CAN TAKE IT` : `${r.lab} IS FREE. SHARE CODE ${code} TO FILL IT`;
    }
    return isHost ? `SHARE CODE ${code} TO FILL IT` : "FREE WATCHING SEAT";
  }

  let sel = $state(0);
  let say = $state("");
  let sayTimer: ReturnType<typeof setTimeout> | undefined;
  function tell(text: string, ms = 3000) {
    say = text;
    clearTimeout(sayTimer);
    sayTimer = setTimeout(() => (say = ""), ms);
  }
  const hint = $derived(say || hintFor(rows[sel]));

  // Start on your own seat.
  const seatEls: HTMLButtonElement[] = [];
  let placed = false;
  $effect(() => {
    if (placed || !rows.length) return;
    placed = true;
    const mine = rows.findIndex((r) => r.user?.id === youId);
    sel = Math.max(0, mine);
    void tick().then(() => seatEls[sel]?.focus({ preventScroll: true }));
  });
  const refocus = () => void tick().then(() => seatEls[sel]?.focus({ preventScroll: true }));
  /** After switching play / watch, the highlight follows you to your new seat. */
  async function switchAndFollow(as: "play" | "watch") {
    await couch.switchTo(as);
    await tick();
    const mine = rows.findIndex((r) => r.user?.id === youId);
    if (mine >= 0) {
      sel = mine;
      seatEls[mine]?.focus({ preventScroll: true });
    }
  }

  // ---- What the buttons do ----
  function pickSeat(i: number) {
    sel = i;
    const r = rows[i];
    if (!L || !r) return;
    if (r.held && r.seat && isHost && r.seat.n !== 1) return openMenu(r.seat.n);
    if (!r.user && r.kind === "p" && L.you.role === "watch") return void switchAndFollow("play");
    if (!r.user && r.kind === "w" && L.you.role === "play") return void switchAndFollow("watch");
    tell(hintFor(r));
  }
  function switchRole() {
    if (!L) return;
    if (isHost) return tell("THE HOST ALWAYS PLAYS AS P1");
    if (L.you.role === "watch" && !freeSeat) return tell("ALL 4 SEATS ARE TAKEN. YOU CAN KEEP WATCHING");
    void switchAndFollow(L.you.role === "watch" ? "play" : "watch");
  }
  function toggleOpen() {
    if (L && isHost) void couch.setOpen(!L.open);
  }
  async function toggleFull() {
    await couch.setFullscreen(!couch.fullscreen);
    if (!couch.fullscreen) refocus(); // the seats are back: highlight the one you were on
  }
  /** Start: seat options for a dropped player's seat. */
  function gameMenu() {
    if (!isHost) return;
    const r = rows[sel];
    if (r?.held && r.seat && r.seat.n !== 1) return openMenu(r.seat.n);
    const held = rows.find((x) => x.held && x.seat && x.seat.n !== 1);
    if (held?.seat) return openMenu(held.seat.n);
    tell("NOBODY HAS DROPPED OUT. SEAT OPTIONS SHOW UP HERE WHEN THEY DO");
  }

  // Leaving takes two presses of B, so nobody closes a lobby for everyone by accident.
  let leaveArmed = false;
  let leaveTimer: ReturnType<typeof setTimeout> | undefined;
  function leaveAsk() {
    if (leaveArmed) return void leaveNow();
    leaveArmed = true;
    tell(isHost ? "PRESS B AGAIN TO CLOSE THE LOBBY FOR EVERYONE" : "PRESS B AGAIN TO LEAVE THE LOBBY");
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(() => (leaveArmed = false), 3000);
  }
  async function leaveNow() {
    await couch.leave();
    app.history = [{ name: "menu" }];
    app.route = { name: "couch" };
  }

  // ---- Seat options (host) ----
  let menuSeat = $state<number | null>(null);
  let menuEls: HTMLButtonElement[] = [];
  function openMenu(n: number) {
    menuSeat = n;
    void tick().then(() => menuEls[0]?.focus({ preventScroll: true }));
  }
  function closeMenu() {
    menuSeat = null;
    refocus();
  }
  const menuRow = $derived(menuSeat ? rows.find((r) => r.seat?.n === menuSeat) : undefined);
  type Opt = { label: string; sub: string; go: () => void };
  const opts = $derived.by<Opt[]>(() => {
    const r = menuRow;
    if (!r?.seat || !L) return [];
    const n = r.seat.n;
    const who = r.user ? first(r.user) : "they";
    const out: Opt[] = [];
    if (r.held) out.push({ label: "KEEP HOLDING THE SEAT", sub: `${who} drops straight back into P${n} · ${clockOf(r.left)} left`, go: () => void couch.seat(n, "hold") });
    for (const w of L.watchers) out.push({ label: `GIVE P${n} TO ${NAME(w)}`, sub: `${first(w)} is watching and moves into the game`, go: () => void couch.seat(n, "give", w.id) });
    out.push({ label: `LEAVE P${n} EMPTY`, sub: "Anyone can take it later", go: () => void couch.seat(n, "empty") });
    return out;
  });
  // The seat came back (they rejoined) or was sorted out elsewhere: close the options.
  $effect(() => {
    if (menuSeat && menuRow && !menuRow.held && menuRow.user) closeMenu();
  });

  // ---- A friend dropped out: a note for the host that fades after a few seconds ----
  let toast = $state<{ n: number; name: string } | null>(null);
  let toastTimer: ReturnType<typeof setTimeout> | undefined;
  let seenHeld = new Set<number>();
  $effect(() => {
    const held = new Set(rows.filter((r) => r.held && r.seat && r.user && r.user.id !== youId).map((r) => r.seat!.n));
    if (isHost) {
      for (const n of held) {
        if (seenHeld.has(n)) continue;
        const r = rows.find((x) => x.seat?.n === n);
        toast = { n, name: r?.user ? first(r.user) : "A player" };
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => (toast = null), 8000);
      }
    }
    seenHeld = held;
    if (toast && !held.has(toast.n)) toast = null;
  });
  const toastRow = $derived(toast ? rows.find((r) => r.seat?.n === toast!.n) : undefined);

  // ---- Your own link dropped, or the lobby closed ----
  const mineHeld = $derived(rows.find((r) => r.kind === "p" && r.held && r.user?.id === youId));
  const closedBy = $derived(couch.ended && (couch.ended.reason === "host-left" || couch.ended.reason === "host-ended") ? couch.ended.reason : null);
  const lost = $derived(!closedBy && (!!mineHeld || (!!couch.ended && !isHost)));
  let lostAt = $state(0);
  $effect(() => {
    if (lost && !lostAt) lostAt = Date.now();
    if (!lost) lostAt = 0;
  });
  const lostLeft = $derived(mineHeld ? mineHeld.left : Math.max(0, 120 - (now - lostAt) / 1000));
  let lostEls: HTMLButtonElement[] = [];
  $effect(() => {
    if (lost) void tick().then(() => lostEls[0]?.focus({ preventScroll: true }));
  });
  // Keep trying by itself every few seconds (the Windows side), as the board says.
  $effect(() => {
    if (!lost || !inTauri || !couch.ended) return;
    const t = setInterval(() => void couch.rejoin(), 5000);
    return () => clearInterval(t);
  });
  async function keepTrying() {
    await couch.rejoin();
    refocus();
  }
  let okEl = $state<HTMLButtonElement | null>(null);
  $effect(() => {
    if (!closedBy) return;
    void tick().then(() => okEl?.focus({ preventScroll: true }));
    const t = setTimeout(() => void leaveNow(), 6000);
    return () => clearTimeout(t);
  });
  const modal = $derived(!!menuSeat || lost || !!closedBy);

  // ---- The live game box: tell the Windows side where it is ----
  let boxEl = $state<HTMLDivElement | null>(null);
  $effect(() => {
    const el = boxEl;
    if (!el || couch.fullscreen) return;
    const send = () => couch.box(el.getBoundingClientRect());
    send();
    const ro = new ResizeObserver(send);
    ro.observe(el);
    window.addEventListener("resize", send);
    // Once more after the screen's fade-in has settled.
    const t = setTimeout(() => couch.box(el.getBoundingClientRect(), true), 260);
    return () => {
      ro.disconnect();
      window.removeEventListener("resize", send);
      clearTimeout(t);
    };
  });

  // ---- Controller ----
  $effect(() => {
    useScreenButtons((input) => {
      if (closedBy) {
        if (input === "b") void leaveNow();
        return input !== "a";
      }
      if (lost) return input !== "a"; // only the dialog's buttons
      if (menuSeat) {
        if (input === "b" || input === "menu") closeMenu();
        return input !== "a";
      }
      if (input === "x") return switchRole(), true;
      if (input === "y") return toggleFull(), true;
      if (input === "menu") return gameMenu(), true;
      if (input === "lb") return toggleOpen(), true;
      if (input === "b") return leaveAsk(), true;
      return false;
    });
    return () => useScreenButtons(null);
  });

  // ---- Keyboard backup: arrows, Enter, X, Y / F full screen, Esc ----
  const ARROWS: Record<string, Dir> = { ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right" };
  function onKey(e: KeyboardEvent) {
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key === "Escape") {
      // Instead of the usual "back" (which would leave the lobby running).
      e.stopImmediatePropagation();
      e.preventDefault();
      if (closedBy) void leaveNow();
      else if (menuSeat) closeMenu();
      else if (!lost) leaveAsk();
      return;
    }
    if (ARROWS[e.key]) {
      e.preventDefault();
      moveFocus(ARROWS[e.key]);
      return;
    }
    if (modal) return;
    const k = e.key.toLowerCase();
    if (k === "x") switchRole();
    else if (k === "y" || k === "f") toggleFull();
    else if (k === "o") toggleOpen();
  }

  const guide = $derived<GuideItem[]>([
    { buttons: ["a"], label: "Pick seat" },
    { buttons: ["x"], label: "Switch play / watch" },
    { buttons: ["y"], label: "Full screen" },
    ...(isHost ? ([{ buttons: ["start"], label: "Game menu" }, { buttons: ["lb"], label: "Open / closed" }] satisfies GuideItem[]) : []),
    { buttons: ["b"], label: isHost ? "Close lobby" : "Leave" },
  ]);
  const fsGuide = $derived<GuideItem[]>([
    { buttons: ["y"], label: "Back to lobby view" },
    ...(isHost ? ([{ buttons: ["start"], label: "Game menu" }] satisfies GuideItem[]) : []),
  ]);
  const fsNote = $derived(lost ? "Only your screen stops. The others keep playing." : "Nobody else is paused. The note fades after a few seconds.");
  const hostName = (l: Lobby) => (l.you.role === "host" ? "YOUR" : `${NAME(l.host)}'S`);
</script>

<svelte:window onkeydowncapture={onKey} />

{#snippet signal()}
  <span class="sig" aria-hidden="true"><i class="l" style="height: 5px"></i><i style="height: 10px"></i><i style="height: 14px"></i><i style="height: 18px"></i></span>
{/snippet}
{#snippet dots()}
  <span class="dots" aria-hidden="true"><i></i><i></i><i></i></span>
{/snippet}

{#if L}
  {@const c = consoleById(L.game.console)}
  <div class="page" class:full={couch.fullscreen}>
    {#if !couch.fullscreen}
      <header>
        <img class="tvlogo" src="/brand/crt-logo.gif" alt="Game Night logo" />
        <div class="hcol"><span class="crumb">GAME NIGHT › COUCH PLAY ›</span><span class="ttl">{hostName(L)} LOBBY</span></div>
        <div class="right">
          <div class="code"><small>CODE</small><b>{L.code}</b></div>
          {#if isHost}
            <button class="tog" onclick={toggleOpen} aria-label="Lobby open or closed">
              {#if L.open}<b><i class="dotg"></i>OPEN</b><span>Discord friends see it on their menu</span>
              {:else}<b><i class="dotc"></i>CLOSED</b><span>Hidden. Only people with the code</span>{/if}
            </button>
          {:else}
            <div class="tog">
              {#if L.open}<b><i class="dotg"></i>OPEN</b><span>Discord friends see it on their menu</span>
              {:else}<b><i class="dotc"></i>CLOSED</b><span>Hidden. Only people with the code</span>{/if}
            </div>
          {/if}
        </div>
      </header>
    {/if}

    <section class="screen" aria-label="Live game">
      {#if !inTauri}
        <!-- Screen preview only: a stand-in picture where the game will be. -->
        <div class="scene" aria-hidden="true">
          <span class="cloud" style="left: 70%"></span><span class="cloud" style="left: 125%; top: 22%"></span>
          <span class="blk" style="left: 43%; bottom: 42%"></span><span class="blk" style="left: 48%; bottom: 42%"></span><span class="blk" style="left: 53%; bottom: 42%"></span>
          <span class="hero" style="left: 25%"></span><span class="hero" class:ghost={rows[1]?.held} style="left: 35%; background: #2aa040"></span><span class="hero" style="left: 44%; background: #2a5ad0"></span>
        </div>
      {/if}
      <!-- The game's own window sits exactly over this empty box. -->
      <div class="gamebox" bind:this={boxEl}></div>
      {#if !couch.fullscreen}
        {#if L.started}<span class="ov live"><i></i>LIVE · {playing} PLAYING · {L.watchers.length} WATCHING</span>{/if}
        <span class="ov fs"><img src={app.pad.type === "dualsense" ? "/prompts/ps/ps_y.png" : "/prompts/xbox/xbox_y.png"} alt={app.pad.type === "dualsense" ? "Triangle" : "Y"} />FULL SCREEN</span>
        {#if !L.started}
          <div class="waitscr"><b>NOT STARTED YET</b><span>{isHost ? "The game is starting up. Friends can join now" : `Waiting for ${first(L.host)}'s game to start`}</span></div>
        {/if}
      {/if}
    </section>

    {#if !couch.fullscreen}
      <div class="info">
        <span class="gname">{L.game.title}</span><span class="chip">{c.short.toUpperCase()}</span><span class="chip">{max === 1 ? "1 PLAYER" : `UP TO ${max} PLAYERS`}</span>
        {#if couch.error}<span class="ping bad">{couch.error}</span>{/if}
      </div>

      <aside class="side" aria-label="Seats">
        <span class="sh2">&gt; 8 SEATS <small>4 playing, 4 watching · switch any time</small></span>
        <div class="seats" data-nav-group>
          {#each rows as r, i (i)}
            {@const t = tag(r)}
            <button class="seat {r.kind}" class:e={!r.user} class:ghost={r.held} bind:this={seatEls[i]} onfocus={() => (sel = i)} onmouseenter={() => (sel = i)} onclick={() => pickSeat(i)}>
              <span class={r.kind === "p" ? "pn" : "wn"}>{r.lab}</span>
              {#if r.user}
                <Avatar name={r.user.name} src={r.user.avatar ?? undefined} size={28} color={colour(r.user)} />
                <span class="who"><b>{r.user.name}</b><span class="ss">{sub(r)}</span></span>
              {:else}
                <span class="ss">{sub(r)}</span>
              {/if}
              {#if t}<span class="tagr {t.cls}">{t.text}</span>{/if}
            </button>
          {/each}
        </div>
        <span class="vt hint">&gt; {hint}<span class="cursor">_</span></span>
      </aside>
    {/if}

    {#if toast && toastRow && !menuSeat}
      <section class="toast" role="status">
        <span class="tt">{@render signal()}{toast.name.toUpperCase()} DROPPED OUT</span>
        <span class="tl">The game keeps going. P{toast.n} stands still until {toast.name} is back.</span>
        <span class="tm">{@render dots()} Holding P{toast.n} for {toast.name} · {clockOf(toastRow.left)}</span>
        <span class="tg"><img src={app.pad.type === "dualsense" ? "/prompts/ps/ps_start.png" : "/prompts/xbox/xbox_start.png"} alt="" />Seat options</span>
      </section>
    {/if}

    {#if menuSeat && menuRow}
      <div class="menu" role="dialog" aria-label="Seat options" aria-modal="true">
        <span class="mt">P{menuSeat} · {menuRow.user ? NAME(menuRow.user) : "SEAT"} {menuRow.held ? "DROPPED" : ""}</span>
        <span class="ms">The game keeps running behind this. Pick what happens to {menuRow.user ? `${first(menuRow.user)}'s` : "this"} seat.</span>
        <div class="opts" data-nav-group>
          {#each opts as o, i (o.label)}
            <button class="opt" bind:this={menuEls[i]} onclick={() => { o.go(); closeMenu(); }}><b>{o.label}</b><span>{o.sub}</span></button>
          {/each}
        </div>
        <span class="ms foot-note">{menuRow.user ? first(menuRow.user) : "They"} can rejoin with the same code any time and pick Play or Watch again.</span>
      </div>
    {/if}

    {#if lost}
      <div class="center" role="alertdialog" aria-label="Connection lost" aria-modal="true">
        <span class="ct">CONNECTION LOST</span>
        <span class="cb">Your link to {L.you.role === "host" ? "your" : `${first(L.host)}'s`} lobby dropped. Everyone else keeps playing. Game Night is getting you back in, and your seat is held.</span>
        <span class="tm">{@render dots()} Rejoining · {clockOf(lostLeft)}</span>
        <div class="opts" data-nav-group>
          <button class="opt" bind:this={lostEls[0]} onclick={keepTrying}><b>KEEP TRYING</b><span>You land back in your seat when it works</span></button>
          <button class="opt" bind:this={lostEls[1]} onclick={leaveNow}><b>LEAVE</b><span>Back to Couch Play</span></button>
        </div>
      </div>
    {/if}

    {#if closedBy}
      <div class="center" role="alertdialog" aria-label="Lobby closed" aria-modal="true">
        <span class="ct">{NAME(L.host)} CLOSED THE LOBBY</span>
        <span class="cb">Thanks for playing! Same message if {first(L.host)}'s PC drops. Back to Couch Play in a few seconds.</span>
        <div class="opts"><button class="opt" bind:this={okEl} onclick={leaveNow}><b>OK</b><span>Go now</span></button></div>
      </div>
    {/if}

    <div class="foot">
      {#if couch.fullscreen}<ButtonGuide items={fsGuide} retro note={fsNote} />{:else}<ButtonGuide items={guide} retro />{/if}
    </div>
  </div>
{:else}
  <div class="page"><div class="vt empty">&gt; LOOKING FOR YOUR LOBBY<span class="cursor">_</span></div></div>
{/if}

<style>
  /* Sizes and colours follow the approved boards CQ4 and CQ6 (canvas "Couch Play round 2"). */
  .page {
    height: 100%; position: relative; overflow: hidden; isolation: isolate; color: var(--text);
    background: radial-gradient(ellipse at 50% 38%, #3b1417 0% 12%, #2d1012 12% 24%, #210c0e 24% 38%, #170a0b 38% 54%, #0e0707 54% 72%, #070404 72% 100%);
  }
  .page.full { background: #000; }
  .vt { font-family: VT323, monospace; letter-spacing: 0.06em; }
  .empty { position: absolute; left: 50px; top: 160px; font-size: 26px; color: #ffd6d6; }
  header { position: absolute; left: 48px; right: 48px; top: 32px; display: flex; align-items: center; gap: 16px; }
  .tvlogo { display: block; flex-shrink: 0; width: 66px; height: 80px; margin: -6px 2px -6px 0; filter: drop-shadow(0 0 10px rgba(236, 40, 46, 0.35)) drop-shadow(0 4px 0 #000); }
  .hcol { display: flex; flex-direction: column; gap: 8px; }
  .crumb { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.12em; color: var(--muted); }
  .ttl { font-family: "Press Start 2P", monospace; font-size: 24px; line-height: 1.1; white-space: nowrap; color: #ff2a32; text-shadow: 0 0 3px #ff5a60, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.85), 3px 3px 0 #000; }
  .right { margin-left: auto; display: flex; align-items: center; gap: 14px; }
  .code { display: flex; align-items: center; gap: 12px; height: 56px; padding: 0 16px; border-radius: 10px; border: 2px solid var(--amber); background: rgba(10, 6, 6, 0.85); box-shadow: 0 0 14px rgba(242, 180, 90, 0.35); box-sizing: border-box; }
  .code small { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.1em; color: var(--muted); }
  .code b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 24px; letter-spacing: 0.18em; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 3px 3px 0 #000; }
  .tog { display: flex; flex-direction: column; align-items: flex-start; gap: 2px; height: 56px; box-sizing: border-box; justify-content: center; padding: 0 14px; border-radius: 10px; border: 2px solid var(--line-2); background: rgba(30, 20, 21, 0.9); color: var(--text); font: inherit; min-width: 200px; text-align: left; }
  button.tog:hover { border-color: #ffd36b; }
  .tog b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 11px; display: flex; align-items: center; gap: 8px; }
  .tog span { font-family: VT323, monospace; font-size: 16px; letter-spacing: 0.04em; color: var(--muted); }
  .dotg { width: 9px; height: 9px; border-radius: 50%; background: var(--green); box-shadow: 0 0 6px var(--green); }
  .dotc { width: 9px; height: 9px; border-radius: 2px; background: var(--muted); }
  @keyframes neonGold {
    0%, 100% { box-shadow: 0 0 0 1px #fff3c4, 0 0 8px 2px #ffb21e, 0 0 22px 4px rgba(255, 150, 0, 0.65), 0 0 44px 8px rgba(255, 120, 0, 0.25), inset 0 0 12px rgba(255, 170, 40, 0.45); }
    50% { box-shadow: 0 0 0 1px #fff3c4, 0 0 10px 3px #ffc23e, 0 0 28px 6px rgba(255, 160, 0, 0.8), 0 0 56px 12px rgba(255, 130, 0, 0.35), inset 0 0 16px rgba(255, 180, 60, 0.55); }
  }
  @keyframes blink { 50% { opacity: 0; } }
  .cursor { animation: blink 1.1s steps(1) infinite; }

  /* ---- The live game box ---- */
  .screen { position: absolute; left: 48px; top: 140px; width: 608px; height: 456px; border-radius: 12px; border: 3px solid #000; overflow: hidden; box-shadow: 0 0 0 2px var(--line-2), 0 10px 0 rgba(0, 0, 0, 0.5), 0 0 40px rgba(236, 40, 46, 0.2); background: #000; }
  .full .screen { left: 0; top: 0; width: 100%; height: 100%; border: 0; border-radius: 0; box-shadow: none; }
  .gamebox { position: absolute; inset: 0; }
  .scene {
    position: absolute; inset: 0; image-rendering: pixelated; overflow: hidden;
    background:
      repeating-linear-gradient(90deg, #b0521c 0 30px, #5c240a 30px 32px) 0 100% / 100% 14% no-repeat,
      linear-gradient(#56c456, #2f8f36) 0 86% / 100% 2.2% no-repeat,
      radial-gradient(ellipse 26% 26% at 80% 100%, #2b8c44 98%, transparent 100%) 0 83.8% / 100% 31% no-repeat,
      radial-gradient(ellipse 40% 37% at 30% 100%, #37a456 98%, transparent 100%) 0 83.8% / 100% 31% no-repeat,
      linear-gradient(180deg, #3f7cf0 0%, #7fb6ff 62%, #bfe3ff 100%);
  }
  .cloud { position: absolute; top: 13%; width: 96px; height: 28px; background: #fff; border-radius: 14px; box-shadow: 24px -12px 0 -2px #fff; animation: drift 18s linear infinite; }
  @keyframes drift { from { transform: translateX(0); } to { transform: translateX(-700px); } }
  .blk { position: absolute; width: 32px; height: 32px; background: #d8901e; border: 3px solid #6a3a08; box-sizing: border-box; }
  .hero { position: absolute; bottom: 16.2%; width: 24px; height: 32px; background: #d02a2a; box-shadow: inset 0 10px 0 #f0c090; animation: hop 1.2s steps(2) infinite; }
  .hero.ghost { opacity: 0.35; filter: grayscale(1); animation: none; }
  @keyframes hop { 50% { transform: translateY(-40px); } }
  .ov { position: absolute; display: flex; align-items: center; gap: 8px; font-family: VT323, monospace; font-size: 19px; letter-spacing: 0.08em; background: rgba(10, 6, 6, 0.82); border-radius: 6px; padding: 2px 10px; color: #ffe0e0; }
  .ov.live { left: 12px; top: 12px; }
  .ov.live i { width: 9px; height: 9px; border-radius: 50%; background: #ff2a32; box-shadow: 0 0 6px #ff2a32; animation: blink 1.4s steps(1) infinite; }
  .ov.fs { right: 12px; bottom: 12px; }
  .ov.fs img { image-rendering: pixelated; width: 22px; height: 22px; }
  .waitscr { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; background: rgba(10, 6, 6, 0.78); text-align: center; }
  .waitscr b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 16px; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 3px 3px 0 #000; }
  .waitscr span { font-family: VT323, monospace; font-size: 22px; letter-spacing: 0.05em; color: #ffd6d6; }
  .info { position: absolute; left: 48px; top: 612px; width: 608px; display: flex; align-items: center; gap: 10px; }
  .chip { font-family: VT323, monospace; font-size: 16px; letter-spacing: 0.08em; color: var(--text-2); border: 1px solid var(--line-2); border-radius: 999px; padding: 1px 9px; white-space: nowrap; }
  .gname { font-family: "Press Start 2P", monospace; font-size: 13px; color: #fff6d8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ping { margin-left: auto; font-family: VT323, monospace; font-size: 19px; letter-spacing: 0.05em; color: #9fdcb0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ping.bad { color: #ffd36b; }

  /* ---- The 8 seats ---- */
  .side { position: absolute; left: 688px; right: 48px; top: 140px; display: flex; flex-direction: column; gap: 8px; }
  .sh2 { font-family: VT323, monospace; font-size: 21px; letter-spacing: 0.06em; color: var(--link); text-shadow: 0 0 6px rgba(255, 90, 90, 0.8); display: flex; align-items: baseline; gap: 10px; }
  .sh2 small { font-size: 16px; color: var(--muted-2); text-shadow: none; }
  .seats { display: flex; flex-direction: column; gap: 6px; }
  .seat { height: 50px; display: flex; align-items: center; gap: 12px; padding: 0 14px; box-sizing: border-box; border-radius: 12px; border: 1px solid #4a2427; background: rgba(30, 20, 21, 0.88); color: var(--text); font: inherit; text-align: left; width: 100%; flex-shrink: 0; }
  .seat:hover { border-color: #ffd36b; }
  :global(body.glide.pad-mode) .seat:focus { border-color: transparent; }
  .seat.e { border-style: dashed; background: rgba(18, 12, 12, 0.55); color: var(--muted-2); }
  .seat.ghost :global(.av), .seat.ghost :global(img) { opacity: 0.45; filter: grayscale(1); }
  .pn { font-family: "Press Start 2P", monospace; font-size: 14px; color: var(--link); text-shadow: 0 0 6px rgba(236, 40, 46, 0.7), 2px 2px 0 #000; width: 38px; flex-shrink: 0; }
  .wn { font-family: VT323, monospace; font-size: 16px; letter-spacing: 0.06em; color: var(--muted); width: 38px; flex-shrink: 0; }
  .who { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .who b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ss { font-family: VT323, monospace; font-size: 17px; letter-spacing: 0.04em; color: var(--muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .tagr { margin-left: auto; font-family: VT323, monospace; font-size: 16px; letter-spacing: 0.08em; padding: 1px 8px; border-radius: 4px; flex-shrink: 0; }
  .ok { color: #9fdcb0; border: 1px solid #3f7a52; }
  .host { color: #ffd36b; border: 1px solid var(--amber); }
  .held { color: var(--link); border: 1px solid var(--red); }
  .hint { font-size: 20px; color: #ffd6d6; margin-top: 6px; }

  /* ---- Drop-outs (CQ6) ---- */
  .toast { position: absolute; right: 28px; top: 28px; z-index: 10; width: 420px; border-radius: 12px; border: 2px solid #5a2225; background: rgba(20, 12, 13, 0.94); box-shadow: 0 8px 0 rgba(0, 0, 0, 0.5), 0 0 24px rgba(236, 40, 46, 0.3); padding: 16px 18px; box-sizing: border-box; display: flex; flex-direction: column; gap: 8px; }
  .tt { display: flex; align-items: center; gap: 12px; font-family: "Press Start 2P", monospace; font-size: 13px; color: #ff5a60; text-shadow: 0 0 8px rgba(236, 40, 46, 0.8), 2px 2px 0 #000; }
  .tl { font-family: VT323, monospace; font-size: 20px; letter-spacing: 0.04em; color: #ffe0e0; line-height: 1.1; }
  .tm { font-family: VT323, monospace; font-size: 19px; letter-spacing: 0.05em; color: #ffd36b; text-shadow: 0 0 6px rgba(242, 180, 90, 0.6); }
  .tg { display: flex; align-items: center; gap: 8px; font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.05em; color: var(--muted); }
  .tg img { image-rendering: pixelated; height: 18px; width: auto; }
  .sig { display: inline-flex; align-items: flex-end; gap: 2px; height: 18px; }
  .sig i { display: block; width: 4px; background: var(--line-2); }
  .sig i.l { background: var(--red); }
  .dots { display: inline-flex; gap: 5px; }
  .dots i { width: 8px; height: 8px; background: #ffd36b; display: block; animation: dot 1.2s steps(1) infinite; }
  .dots i:nth-child(2) { animation-delay: 0.4s; }
  .dots i:nth-child(3) { animation-delay: 0.8s; }
  @keyframes dot { 0%, 100% { opacity: 0.2; } 33% { opacity: 1; } }
  .center { position: absolute; z-index: 20; left: 50%; top: 150px; width: 620px; margin-left: -310px; border-radius: 14px; border: 2px solid #5a2225; background: linear-gradient(180deg, #1e1415, #150d0e); box-shadow: 0 12px 0 rgba(0, 0, 0, 0.6), 0 0 40px rgba(236, 40, 46, 0.25); padding: 28px 30px; box-sizing: border-box; display: flex; flex-direction: column; gap: 14px; }
  .ct { font-family: "Press Start 2P", monospace; font-size: 19px; line-height: 1.3; color: #ff2a32; text-shadow: 0 0 3px #ff5a60, 0 0 12px #ec282e, 0 0 26px rgba(236, 40, 46, 0.85), 3px 3px 0 #000; }
  .cb { font-family: VT323, monospace; font-size: 23px; letter-spacing: 0.03em; line-height: 1.15; color: #ffe0e0; }
  .menu { position: absolute; z-index: 15; right: 0; top: 0; bottom: 0; width: 440px; background: linear-gradient(180deg, #1e1415, #150d0e); border-left: 2px solid #5a2225; box-shadow: -12px 0 40px rgba(0, 0, 0, 0.6); padding: 32px 28px 92px; box-sizing: border-box; display: flex; flex-direction: column; gap: 14px; }
  .mt { font-family: "Press Start 2P", monospace; font-size: 15px; color: #fff6d8; text-shadow: 0 0 4px #ffd36b, 0 0 14px #ffb21e, 3px 3px 0 #000; }
  .ms { font-family: VT323, monospace; font-size: 20px; letter-spacing: 0.04em; color: #ffe0e0; }
  .foot-note { margin-top: auto; color: var(--muted-2); }
  .opts { display: flex; flex-direction: column; gap: 8px; }
  .opt { height: 62px; flex-shrink: 0; display: flex; flex-direction: column; justify-content: center; gap: 5px; padding: 0 16px; box-sizing: border-box; border-radius: 10px; border: 1px solid #4a2427; background: rgba(30, 20, 21, 0.85); color: var(--text); font: inherit; text-align: left; width: 100%; }
  .opt:hover { border-color: #ffd36b; }
  :global(body.glide.pad-mode) .opt:focus { border-color: transparent; }
  .opt b { font-family: "Press Start 2P", monospace; font-weight: 400; font-size: 11px; }
  .opt span { font-family: VT323, monospace; font-size: 18px; letter-spacing: 0.04em; color: var(--muted); }

  .foot { position: absolute; left: 0; right: 0; bottom: 0; z-index: 16; }
  .foot :global(.guide) { height: 64px; }
  .full .foot :global(.guide) { height: 56px; padding: 0 32px; background: rgba(10, 6, 6, 0.85); border-top: 0; box-shadow: none; font-size: 19px; }

  @media (max-height: 799px) {
    header { top: 22px; }
    .screen:not(.full .screen) { top: 116px; width: 560px; height: 420px; }
    .info { top: 548px; width: 560px; }
    .side { top: 116px; left: 640px; }
    .seat { height: 46px; }
  }
  @media (prefers-reduced-motion: reduce) {
    .cloud, .hero, .ov.live i, .cursor, .dots i { animation: none; }
  }
</style>
