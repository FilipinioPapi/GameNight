# Notes for Claude working on Game Night

- Jayden is not a coder. Talk in plain English, no jargon.
- Security is the top priority. Keep the app's permissions minimal (`app/src-tauri/capabilities/default.json`),
  keep the strict content security policy in `tauri.conf.json`, and never put secrets in the app.
- Nothing sensitive in the repo, PRs or logs: follow `docs/SECURITY_RULES.md`. Turn on the pre-commit
  secret check first thing: `git config core.hooksPath .githooks`.
- The app only ever touches files inside its own "Game Night" folder (see `src-tauri/src/lib.rs`).
- Controller diagrams in `app/public/ctl/` are Jayden's approved pack: never recolour, crop, mirror or
  redraw them. Hover highlights are separate boxes placed on each label tag (`src/lib/controllers.ts`).
- Look and feel follows the approved mockups (Watch Party colours, Luckiest Guy + Inter, console-styled fonts).
- Controller mappings are per person, per console, per pad type (Xbox / DualSense), and stay on that PC.
