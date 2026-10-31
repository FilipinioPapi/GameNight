# Handoff: the main menu (design A21)

Read `docs/STATUS.md` first. Jayden approved mockup A21 on 2026-10-31, with the card icons left out for now.
Spec: project files `gamenight/main-menu/A21-approved.dc.html` and `A21-approved.png`.

## What's on the screen (`app/src/screens/MainMenu.svelte`)
- Header: Jayden's CRT TV cat logo (`app/public/brand/crt-logo.gif`, his file byte for byte, only shown
  smaller), the red 8-bit "GAME NIGHT" wordmark with a neon flicker, "POWERED BY JAYDENATER [BOT]".
  Right side: update / preview / offline chips (only when they apply), a clock, the signed-in user.
- Four cards: LIBRARY, COUCH PLAY (with "COMING NEXT"; A does nothing yet), SETTINGS, QUIT.
  The picked card grows (460 px vs 217 px in the 1280-wide window, shared the same way if wider),
  lifts, glows gold and shows its extra line. Titles are left-aligned at the same spot on every card.
- A line under the cards says what the picked card does, with a blinking cursor.
- "Jump back in": the last three games played (from `settings.recent`), each opens its game page.
  Hidden when nothing has been played yet.
- The last game's box art, blurred and drifting slowly, glows behind the top of the screen. None if it
  has no cover. Game art is never shipped in the app; it comes from RomM through the server as before.
- Retro button guide at the bottom (A Select, ◄ ► Move, ▼ Jump back in) and the version.
- The Steam tip (first run with Steam open) floats top right.

## Controls
- D-pad / stick / arrow keys move along the cards; down goes to Jump back in, up comes back (same column).
- With a controller, the gliding gold frame from PR #14 is the highlight (the card's own glow steps aside,
  so there's only one). With the mouse, hovering picks a card and the card's own gold glow shows.
- Coming back from another screen lands on the card you last used.
- "Reduce animations" in Windows turns off the flicker, the drift, the blinking cursor and the growing.

## Checked
- Confirmed: `npm run check` and `npm run build` clean. Chromium at 1280x800: matches A21 side by side;
  arrow keys move right/left/down/up as above; A on LIBRARY opens the Library, Escape comes back to LIBRARY;
  COUCH PLAY does nothing; no console errors.
- Windows: the pretend-controller test (`tools/e2e/pad_test.py menus`) now presses right, right, left,
  left, A, B and screenshots each step. See the PR for the run.
- Unknown: how it feels on Jayden's PC with his real pad.

## Later
- Card icons (Jayden is making them; prompt in project files `main-menu/chatgpt-prompt-A21-icons.md`).
- COUCH PLAY opens online play once that's built.
