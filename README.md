# Game Night

Play Jayden's retro game library with friends, like being back on the couch.
Friends sign in with Discord, browse the library from Jayden's RomM server, and play.
Couch co-op with controller handoff comes in step 2.

Build plan: https://claude.ai/artifact/4TEFzFihPHjE2wm9ibw2yi

## What's here

| Folder | What it is |
| --- | --- |
| `app/` | The Windows app (Tauri: web-page screens in a small, locked-down Windows shell) |
| `app/src/screens/` | One file per screen: sign-in, first-time setup, main menu, library, game page, settings, controllers |
| `app/src/lib/` | Shared pieces: console list, controller layouts, settings, the game library |
| `app/public/ctl/` | Jayden's approved controller diagrams. Never recolour, crop, mirror or redraw them. |
| `app/src-tauri/` | The Windows side (Rust): window, folder picker, games-folder tools |

## Trying it

Every push builds a Windows installer on GitHub. Open the **Actions** tab, pick the latest
"Windows app" run, and download **Game-Night-windows** at the bottom.
It isn't code-signed yet, so Windows will warn "Windows protected your PC": click
**More info** then **Run anyway**.

## For developers

```
cd app
npm ci
npm run dev          # screens in a browser at http://localhost:1420 (sample data)
npx tauri dev        # the real app window
npm run check        # type checks
cd src-tauri && cargo test
```
