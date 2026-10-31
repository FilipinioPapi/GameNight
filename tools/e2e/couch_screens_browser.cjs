// Couch Play screens in a plain browser (sample lobbies), driven by a pretend controller.
// Run: cd app && npm run build && npx vite preview --port 4317 --strictPort, then
//      node tools/e2e/couch_screens_browser.cjs [folder for screenshots]   (needs Playwright)
// Prints PASS / FAIL for each check.
const { chromium } = require("playwright");
const OUT = process.argv[2] || "couch-shots";
const BASE = "http://localhost:4317/";
const fs = require("fs");
fs.mkdirSync(OUT, { recursive: true });

const B = { a: 0, b: 1, x: 2, y: 3, lb: 4, rb: 5, start: 9, up: 12, down: 13, left: 14, right: 15 };
const log = [];

async function setup(browser, view) {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on("console", (m) => { if (m.type() === "error") log.push(`[${view}] console error: ${m.text()}`); });
  page.on("pageerror", (e) => log.push(`[${view}] page error: ${e.message}`));
  await page.addInitScript(() => {
    const now = Date.now();
    localStorage.setItem("gn.settings", JSON.stringify({
      firstRunDone: true, romsFolder: "D:\\Games\\Game Night", mappings: {}, presets: {}, consoles: {}, favourites: [],
      recent: [{ id: "nes-smb", at: now - 3600e3, minutes: 42 }, { id: "gen-sor2", at: now - 86400e3 }, { id: "snes-smw", at: now - 3 * 86400e3, minutes: 75 }],
      layout: "controller", autoLayout: false, steamTipSeen: true,
    }));
    const pad = { buttons: Array(17).fill(false), axes: [0, 0, 0, 0] };
    window.__pad = pad;
    navigator.getGamepads = () => [{ id: "Xbox Wireless Controller (pretend)", connected: true, buttons: pad.buttons.map((p) => ({ pressed: p, value: p ? 1 : 0 })), axes: pad.axes }];
  });
  await page.goto(BASE + (view ? `?couch=${view}` : ""));
  await page.getByRole("button", { name: /Log in with Discord/ }).click();
  await page.waitForTimeout(600);
  return page;
}
async function hold(page, ms) {
  await page.evaluate(() => { window.__pad.buttons[8] = true; window.__pad.buttons[9] = true; });
  await page.waitForTimeout(ms);
  await page.evaluate(() => { window.__pad.buttons[8] = false; window.__pad.buttons[9] = false; });
  await page.waitForTimeout(200);
}
const box = (page) => page.evaluate(() => globalThis.__gnCouchBox || "");
const shown = (page) => page.evaluate(() => { const b = globalThis.__gnCouchBox || ""; return !!b && b !== "0,0,0,0"; });
async function press(page, name, times = 1) {
  for (let i = 0; i < times; i++) {
    await page.evaluate((i) => (window.__pad.buttons[i] = true), B[name]);
    await page.waitForTimeout(70);
    await page.evaluate((i) => (window.__pad.buttons[i] = false), B[name]);
    await page.waitForTimeout(160);
  }
}
const focused = (page) => page.evaluate(() => {
  const el = document.activeElement;
  return el ? `${el.tagName.toLowerCase()}.${el.className.split(" ")[0]} "${(el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 40)}"` : "none";
});
async function shot(page, name) {
  await page.waitForTimeout(700);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  log.push(`${name}: focused ${await focused(page)}`);
}
async function expect(page, what, test) {
  const ok = await page.evaluate(test);
  log.push(`${ok ? "PASS" : "FAIL"} ${what}`);
}

(async () => {
  const browser = await chromium.launch();

  // CQ1 -> CQ2 -> CQ3 -> CQ4 host
  let p = await setup(browser, "");
  await press(p, "right");
  await expect(p, "menu: right lands on COUCH PLAY", () => document.activeElement?.textContent?.includes("COUCH PLAY"));
  await expect(p, "menu: couch card says 3 LOBBIES OPEN", () => document.body.textContent.includes("3 LOBBIES OPEN"));
  await shot(p, "cq1-main-menu");
  await press(p, "rb");
  await expect(p, "menu: RB shows Jump back in (focus stays on the card)", () => document.querySelector(".btab.on")?.textContent.includes("JUMP") && document.activeElement?.textContent?.includes("COUCH PLAY"));
  await shot(p, "cq1-main-menu-jump-back-in");
  await press(p, "lb");
  await press(p, "down");
  await press(p, "down");
  await expect(p, "menu: down, down reaches a lobby card", () => !!document.activeElement?.closest(".recs"));
  await press(p, "up", 2);
  await expect(p, "menu: up, up from the first lobby lands on LIBRARY (same column)", () => document.activeElement?.textContent?.includes("LIBRARY"));
  await press(p, "right");
  await press(p, "a");
  await expect(p, "couch play screen opened", () => document.body.textContent.includes("HOST A GAME"));
  await shot(p, "cq2-couch-play");
  await press(p, "right");
  await expect(p, "couch: right picks JOIN WITH A CODE", () => document.activeElement?.textContent?.includes("JOIN WITH A CODE"));
  await press(p, "left");
  await press(p, "a");
  await expect(p, "host pick opened", () => document.body.textContent.includes("PICK A GAME TO HOST"));
  await press(p, "rb");
  await expect(p, "host pick: RB goes to SNES", () => document.querySelector(".htab.cur")?.textContent.includes("SNES"));
  await press(p, "right");
  await shot(p, "cq3-host-pick");
  await press(p, "up");
  await expect(p, "host pick: up lands on the console showing (SNES)", () => document.activeElement?.classList.contains("cur"));
  await press(p, "right");
  await expect(p, "host pick: GENESIS says coming soon", () => document.querySelector(".hdesc")?.textContent.includes("GENESIS ONLINE IS COMING SOON"));
  await shot(p, "cq3-host-pick-soon");
  await press(p, "left");
  await press(p, "down");
  await press(p, "a");
  await expect(p, "lobby opened as host", () => document.body.textContent.includes("YOUR LOBBY"));
  await shot(p, "cq4-lobby-host");
  // Your game is running and you hold P1: the lobby ignores the pad.
  await expect(p, "lobby: the game box was sent (not hidden)", () => { const b = globalThis.__gnCouchBox || ""; return !!b && b !== "0,0,0,0"; });
  await expect(p, "lobby: hint says hold VIEW + MENU", () => document.body.textContent.includes("VIEW + MENU to open lobby controls"));
  const before = await focused(p);
  await press(p, "down");
  await press(p, "x"); await press(p, "start"); await press(p, "lb"); await press(p, "b"); await press(p, "y");
  await p.waitForTimeout(200);
  await expect(p, "locked: X/Start/LB/B/Y/down did nothing", () => !document.body.textContent.includes("THE HOST ALWAYS") && !document.body.textContent.includes("KEEP HOLDING") && !document.body.textContent.includes("PRESS B AGAIN") && document.body.textContent.includes("OPEN") && !document.querySelector(".page.full"));
  log.push(`${(await focused(p)) === before ? "PASS" : "FAIL"} locked: the highlight didn't move`);
  await hold(p, 450);
  await expect(p, "locked: a short View + Menu doesn't open lobby controls", () => !document.body.textContent.includes("Lobby controls on"));
  await hold(p, 1150);
  await expect(p, "holding View + Menu 1 s opens lobby controls", () => document.body.textContent.includes("Lobby controls on. Your presses also reach the game."));
  await expect(p, "lobby controls: the game window is hidden (box 0,0,0,0)", () => globalThis.__gnCouchBox === "0,0,0,0");
  await shot(p, "cq4-lobby-controls");
  await press(p, "down", 4);
  await press(p, "x");
  await expect(p, "lobby controls: X works (host plays P1 hint)", () => document.body.textContent.includes("THE HOST ALWAYS PLAYS AS P1"));
  await expect(p, "lobby controls close after the action", () => !document.body.textContent.includes("Lobby controls on"));
  log.push(`${(await shown(p)) ? "PASS" : "FAIL"} the game window comes back after (box ${await box(p)})`);
  await hold(p, 1150);
  await press(p, "lb");
  await expect(p, "lobby controls: LB closes the lobby (code only), then controls close", () => document.body.textContent.includes("CLOSED") && !document.body.textContent.includes("Lobby controls on"));
  await shot(p, "cq4-lobby-host-closed");
  await hold(p, 1150);
  await press(p, "b");
  await expect(p, "lobby controls: B closes them", () => !document.body.textContent.includes("Lobby controls on") && !document.body.textContent.includes("PRESS B AGAIN"));
  await hold(p, 1150);
  await p.waitForTimeout(8500);
  await expect(p, "lobby controls close after 8 s with no press", () => !document.body.textContent.includes("Lobby controls on"));
  await hold(p, 1150);
  await press(p, "y");
  await expect(p, "lobby controls: Y goes full screen", () => !!document.querySelector(".page.full"));
  await shot(p, "cq4-lobby-host-fullscreen");
  await press(p, "y");
  await expect(p, "locked again in full screen: Y does nothing", () => !!document.querySelector(".page.full"));
  await p.keyboard.press("y");
  await p.waitForTimeout(300);
  await expect(p, "keyboard always works: Y on the keyboard leaves full screen", () => !document.querySelector(".page.full"));
  await p.keyboard.press("Escape");
  await expect(p, "keyboard: Escape asks again and hides the game window", () => document.body.textContent.includes("PRESS B AGAIN") && globalThis.__gnCouchBox === "0,0,0,0");
  await p.keyboard.press("Escape");
  await p.waitForTimeout(300);
  await expect(p, "keyboard: second Escape leaves to Couch Play", () => document.body.textContent.includes("JOIN WITH A CODE") && !document.body.textContent.includes("YOUR LOBBY"));
  await p.close();

  // CQ5 -> CQ4 guest
  p = await setup(browser, "guest");
  await press(p, "right");
  await press(p, "a");
  await press(p, "right");
  await press(p, "a");
  await expect(p, "join screen opened", () => document.body.textContent.includes("TYPE THE 6-LETTER CODE"));
  // Type K with the pad keyboard (A is the first key; K is the 10th letter: down 1, right 0 -> J? count it)
  await press(p, "down");
  await press(p, "a");
  await expect(p, "pad keyboard typed a letter", () => document.querySelector(".cb")?.textContent.trim().length === 1);
  await press(p, "x");
  await expect(p, "X deleted it", () => document.querySelector(".cb")?.textContent.trim() === "");
  await p.keyboard.type("k7qm2");
  await shot(p, "cq5-join-typing");
  await p.keyboard.type("x");
  await p.waitForTimeout(300);
  await expect(p, "the code found Jayden's lobby", () => document.body.textContent.includes("JAYDEN'S LOBBY"));
  await shot(p, "cq5-join");
  await press(p, "right");
  await press(p, "a");
  await p.waitForTimeout(300);
  await expect(p, "joined to watch", () => document.body.textContent.includes("JAYDEN'S LOBBY") && document.body.textContent.includes("YOU ARE WATCHING"));
  await shot(p, "cq4-lobby-guest");
  await expect(p, "watcher: no lock hint, full pad control", () => !document.body.textContent.includes("to open lobby controls"));
  await press(p, "x");
  await expect(p, "X switched to playing (P4) and the highlight followed", () => [...document.querySelectorAll(".seat")][3]?.textContent.includes("Player 1") && document.activeElement === [...document.querySelectorAll(".seat")][3]);
  await shot(p, "cq4-lobby-guest-playing");
  await press(p, "x");
  await expect(p, "guest playing: the pad is locked now (X didn't switch back)", () => [...document.querySelectorAll(".seat")][3]?.textContent.includes("Player 1"));
  await p.close();

  // CQ6: a friend drops (host), seat options, your own link drops, the host closes
  p = await setup(browser, "dropped");
  await press(p, "right"); await press(p, "a"); await press(p, "a"); await press(p, "a");
  await expect(p, "host sees SAM DROPPED OUT", () => document.body.textContent.includes("SAM DROPPED OUT"));
  await expect(p, "dropped note: the game window stays showing", () => { const b = globalThis.__gnCouchBox || ""; return !!b && b !== "0,0,0,0"; });
  await expect(p, "dropped note sits outside the box", () => { const t = document.querySelector(".toast").getBoundingClientRect(), g = document.querySelector(".gamebox").getBoundingClientRect(); return t.left >= g.right || t.right <= g.left || t.top >= g.bottom || t.bottom <= g.top; });
  await shot(p, "cq6-dropped");
  await press(p, "start");
  await expect(p, "locked: Start alone does nothing", () => !document.body.textContent.includes("KEEP HOLDING THE SEAT"));
  await hold(p, 1150);
  await press(p, "start");
  await expect(p, "lobby controls + Start opens seat options (controls stay on)", () => document.body.textContent.includes("KEEP HOLDING THE SEAT") && document.body.textContent.includes("Lobby controls on"));
  await press(p, "down");
  await shot(p, "cq6-seat-options");
  await press(p, "a");
  await expect(p, "gave P2 to Alex, lobby controls closed", () => [...document.querySelectorAll(".seat")][1]?.textContent.includes("Alex") && !document.body.textContent.includes("Lobby controls on"));
  await p.waitForTimeout(8500);
  log.push(`${(await shown(p)) ? "PASS" : "FAIL"} after the note fades the game window is back (box ${await box(p)})`);
  await p.close();

  p = await setup(browser, "lost");
  await press(p, "right"); await press(p, "a"); await press(p, "right"); await press(p, "a");
  await p.keyboard.type("K7QM2X");
  await p.waitForTimeout(400);
  await press(p, "a");
  await p.waitForTimeout(300);
  await expect(p, "connection lost dialog", () => document.body.textContent.includes("CONNECTION LOST"));
  await shot(p, "cq6-connection-lost");
  await press(p, "a");
  await expect(p, "keep trying puts you back in", () => !document.body.textContent.includes("CONNECTION LOST"));
  await p.close();

  // Your own game stopped / lost its link (lobby.you.game) while the lobby carries on: Rejoin.
  p = await setup(browser, "stopped");
  await press(p, "right"); await press(p, "a"); await press(p, "right"); await press(p, "a");
  await p.keyboard.type("K7QM2X");
  await p.waitForTimeout(400);
  await press(p, "a");
  await p.waitForTimeout(300);
  await expect(p, "game disconnected: the rejoin dialog shows", () => document.body.textContent.includes("CONNECTION LOST") && document.body.textContent.includes("KEEP TRYING"));
  await expect(p, "game disconnected: the pad isn't locked (dialog works)", () => !document.body.textContent.includes("to open lobby controls"));
  await press(p, "a");
  await expect(p, "keep trying gets you back in", () => !document.body.textContent.includes("CONNECTION LOST"));
  await p.close();

  p = await setup(browser, "closed");
  await press(p, "right"); await press(p, "a"); await press(p, "right"); await press(p, "a");
  await p.keyboard.type("K7QM2X");
  await p.waitForTimeout(400);
  await press(p, "right"); await press(p, "a");
  await p.waitForTimeout(300);
  await expect(p, "closed dialog", () => document.body.textContent.includes("JAYDEN CLOSED THE LOBBY"));
  await shot(p, "cq6-closed");
  await press(p, "a");
  await expect(p, "OK goes back to Couch Play", () => document.body.textContent.includes("HOST A GAME"));
  await p.close();

  // Smallest window
  p = await setup(browser, "");
  await p.setViewportSize({ width: 1100, height: 700 });
  await press(p, "right"); await press(p, "a"); await press(p, "a"); await press(p, "a");
  await shot(p, "small-1100x700-lobby");
  await p.close();

  await browser.close();
  console.log(log.join("\n"));
})();
