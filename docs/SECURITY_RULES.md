# Keeping secrets out of Game Night's code

Standing rules for every thread and every change. Written 2026-10-31 for the "could the repo go public?"
check. Findings and the verdict are in `docs/HANDOFF_SECURITY.md`.

## Never in the repo, a PR, an issue, a commit message or a test log
- Passwords, tokens, API keys, private keys, signing keys, Discord bot tokens or client secrets, webhook links.
- Real Discord ids (server, role, user) and invite links.
- Personal details: email addresses, real names beyond "Jayden", home address, phone numbers.
- New home-network details: LAN addresses, NAS folder paths, router or port-forward setup, proxy (NPM) setup,
  Roof Rage's server setup. The one known LAN address is listed in `tools/security/allowlist.txt` until
  Jayden decides on it.
- Notes about weak spots that aren't fixed yet (for example "is this NAS service locked down? Unknown").
  Those go in the project's private notes (the project files folder), not in the repo.
- Game ROMs, BIOS files, or art that isn't ours to share.

## Where secrets live instead
| Secret | Where it lives |
|---|---|
| Discord client secret, RomM token or password | The Game Night container's settings on Unraid (masked fields in `server/unraid/gamenight.xml`) |
| GitHub token for the update sync | Pasted into the Unraid User Script by Jayden. The repo copy only has `PASTE-YOUR-GITHUB-TOKEN-HERE` |
| Update signing key | `/mnt/user/appdata/roofrage-sync/` on the NAS, read-only to the publish container. Only the public half is in the app |
| A friend's sign-in pass | Windows Credential Manager on their PC. The server keeps only a fingerprint |
| Anything CI ever needs | GitHub's encrypted Actions secrets (`${{ secrets.NAME }}`), never typed into a workflow file |

The app itself holds no secrets. Anything shipped in the app can be read by anyone who has the installer.

## The checks that enforce this
- **Secret check** (`tools/security/scan_secrets.py`): looks for keys, tokens, written-in passwords, Discord ids,
  personal emails and home-network addresses. Standard Python only, nothing downloaded.
  - Runs on every push and PR (`.github/workflows/secrets.yml`), including the PR's commit names, emails and messages.
  - Runs before every commit once turned on: `git config core.hooksPath .githooks`. Every Claude thread turns
    this on at the start.
  - Whole-history audit: `python3 tools/security/scan_secrets.py --history`.
- **False alarm?** Only if the value is truly safe (a placeholder, a public key, a test value), add it to
  `tools/security/allowlist.txt` with the reason. A real secret is never allowlisted: remove it instead.
- **GitHub's own protection** (Jayden turns these on, free on public repos): Settings, Code security,
  Secret scanning and Push protection. Push protection blocks a push that contains a known token type.
- **Jayden's GitHub email**: Settings, Emails, "Keep my email addresses private" and "Block command line pushes
  that expose my email". Then merges are recorded with a GitHub no-reply address instead of his real one.

## If a secret ever does get in
1. Treat it as leaked, even if it was only there a minute. Deleting the file doesn't remove it from history.
2. Tell Jayden straight away, and give him the steps to change it at the source (Discord portal, RomM,
   GitHub tokens page, or a new signing key). Jayden does the NAS and Unraid steps.
3. Only then clean the repo. Rewriting history needs Jayden's explicit OK.

## If the repo is public
- Only Jayden and the Claude threads merge. Never merge a pull request from someone outside without Jayden
  reading it first: anything merged to `main` becomes a release signed with Jayden's key.
- Settings, Actions, General: "Require approval for all outside collaborators" for fork pull requests.
- Test artifacts (installers, screenshots) and logs can be seen by anyone. Tests must only ever print test data.
