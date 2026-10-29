# Game Night updates

Game Night updates itself the same way Roof Rage does (RoofRageRE `re/UPDATER_SPEC.md`), and it uses the same
signing key.

## How a release happens
1. A pull request raises the version in `app/src-tauri/tauri.conf.json` (and `app/package.json`,
   `app/src-tauri/Cargo.toml`, `app/src/lib/version.ts`). `app/UPDATE_NOTES.txt` holds up to three short
   "what's new" lines.
2. Jayden merges it. GitHub Actions builds the Windows installer and makes a GitHub release `v<version>` with
   `GameNightSetup.exe`.
3. Within 5 minutes the NAS User Script `tools/unraid/gamenight_sync.sh` sees the release. It runs
   `tools/unraid/gamenight_publish.py` (always the newest copy from main), which downloads the installer and
   writes it to `/mnt/user/JJsNAS/RoofRage-Updates/gamenight/v<version>/GameNightSetup.exe`. It writes a signed
   `latest.json` last. Log: `/mnt/user/appdata/gamenight-sync/sync.log`.
4. Every Game Night app checks `https://updates.jjsnas.xyz/gamenight/latest.json` when it opens and on the
   main menu (at most every 30 minutes). The menu then shows **Update ready**, and one click downloads,
   checks, installs quietly and reopens.
5. The install runs from a small helper script after Game Night closes. It writes each step to
   `%LOCALAPPDATA%\xyz.jjsnas.gamenight\update\update.log` (old version, installer result, new version), which
   is the first thing to read if an update doesn't take.

The install link for friends is always the newest version:
`https://updates.jjsnas.xyz/gamenight/v<version>/GameNightSetup.exe`.

## Security
- `latest.json` contains only `signed` (base64 of the file list) and `signature` (base64 ECDSA P-256 /
  SHA-256, r||s). The app checks it against Jayden's public key built into `app/src-tauri/src/updater.rs`.
  That is the same key as Roof Rage's. The secret half is only at
  `/mnt/user/appdata/roofrage-sync/signing_key.pem`. The container gets it read-only, and it is never in the
  served folder, git or chat.
- The signed list says `"app": "gamenight"`, so a Roof Rage list (same key) is refused. It carries the
  installer's size and SHA-256, so the one signature covers the download too. Only a newer version is
  offered, so an old signed list can't be replayed to downgrade anyone.
- With no key on the NAS, nothing is published, because the app would refuse an unsigned list anyway.
- Test builds can use `GAMENIGHT_UPDATE_URL` and `GAMENIGHT_UPDATE_KEY`. Release builds ignore both.
- Known limit (same as Roof Rage): anyone who can merge to `main` gets a release signed.

## When Roof Rage's downloads get locked (RoofRageRE `re/UPDATES_LOCK_SETUP.md` Part C)
That guide puts a friends-token check at the top of the whole `server { }`, which would also lock
`/gamenight/`. The Game Night app holds no secrets, so it can't send that token. When locking, put the check
inside `location / { ... }` instead, and add an open `location /gamenight/ { }` block. Game Night's files are
protected by the signature, and its installer contains nothing private.

## One-time NAS setup (Jayden)
1. **GitHub token.** Go to github.com, then Settings, Developer settings, Fine-grained tokens, and edit the
   token Roof Rage's sync uses. Under Repository access, add **GameNight**. It needs read-only Contents. A
   new token with the same rights works too.
2. **User Script.** In Unraid, go to Settings, then User Scripts, then **Add New Script**. Name it
   `gamenight-sync`, paste `tools/unraid/gamenight_sync.sh` and put the token in the `TOKEN` line. Set the
   schedule to **Custom** with `*/5 * * * *`.
3. **Check.** After the next release, `/mnt/user/appdata/gamenight-sync/sync.log` says
   `published v... (... bytes, signed)`, and `https://updates.jjsnas.xyz/gamenight/latest.json` opens.
