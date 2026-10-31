# Handoff: is the repo safe to make public? (checked 2026-10-31)

Why: GitHub Actions stopped running on 2026-10-31 because the private repo's paid minutes ran out. Public repos
get free Actions minutes, so Jayden asked whether making `FilipinioPapi/GameNight` public is safe.
Standing rules that came out of this: `docs/SECURITY_RULES.md`.

## What was checked
- Every file version in the whole history: 10 branches, 6 tags, 67 commits, 295 text file versions.
  Pictures and lock files were left out. Commit names, emails and messages too.
- All 18 pull request descriptions, the 6 release notes, issues (there are none), the workflow files on
  `main`, the 0.3.3 branch and the netplay branch, and one full recent Windows test log.
- Run in a cloud sandbox with `git` and `grep`, then with `tools/security/scan_secrets.py --history`.
  Off-the-shelf scanners (gitleaks, trufflehog) weren't allowed to download here, so the repo has its own.

## Findings
| # | Finding | Label |
|---|---|---|
| 1 | No passwords, tokens, private keys, Discord tokens, Discord ids or webhook links anywhere in history. The only keys are the **public** halves of the update signing key (meant to be public) and a test public key. Test signing keys are made fresh during each test. | Confirmed |
| 2 | Real secrets live outside the repo: Unraid container settings (masked), the Unraid User Script (repo copy is a placeholder), the NAS signing key folder, Windows Credential Manager. | Confirmed (code and docs); where they really sit on the NAS is Unknown |
| 3 | **Jayden's personal email** (his proton.me address) is on 17 merge commits. GitHub records the merging account's email. On a public repo anyone can see it. | Confirmed |
| 4 | **Home network details**: the NAS LAN address 192.168.1.33, with port 8094 (Game Night) and 8084 (RomM), the domain jjsnas.xyz with the updates, gamenight and play names, NAS folder paths (including where the signing key file sits), the PC name JJsPC. A LAN address can't be reached from the internet. The domain names are already public through DNS. | Confirmed (present). Low risk: Strongly inferred |
| 5 | **Notes about Jayden's server setup and open weak spots**, mostly about Roof Rage: `docs/HANDOFF_ONLINE.md` names Roof Rage's online board on play.jjsnas.xyz, its topic names, that it uses NPM and nginx, and says "ntfy should be deny-all, but whether it really is on the NAS is Unknown". `docs/UPDATES.md` explains the planned download lock and that Game Night and Roof Rage share one signing key. That's a map for someone looking for a way in. | Confirmed (present). Risk: Strongly inferred |
| 6 | Workflows only use GitHub's own machines, use no stored secrets, are read-only by default, and don't use `pull_request_target`. Releases and the container publish only run on pushes to `main`. A stranger's fork PR can't reach anything secret. | Confirmed |
| 7 | Test logs and artifacts only hold test data (pretend pads, a test cartridge, test updates). One full Windows log was read. Others are the same scripts. | Confirmed for that log; Strongly inferred for the rest |
| 8 | PR descriptions mention JJsPC, the Razer keyboard and the Discord server rule. Nothing secret. The claude.ai links in docs are private pages that need Jayden's sign-in. | Confirmed |
| 9 | The NAS update sync runs `tools/unraid/gamenight_publish.py` from `main` with the signing key, so anything merged to `main` gets signed. That's already true today. Making the repo public doesn't let strangers merge, but it does let them open PRs, so "never merge outsiders' PRs unread" becomes important. | Confirmed (already noted as a known limit in `docs/UPDATES.md`) |
| 10 | No game ROMs, BIOS files or RetroArch files are in the repo (RetroArch is downloaded during the build, and the test cartridges are generated). | Confirmed |
| 11 | Pictures that would become downloadable: the controller diagrams (Dropbox pack), the 13 console pictures, the Xbox/PlayStation button prompts (copied from Roof Rage once, with OK), and the logo. Whether all of these are OK to share publicly is up to Jayden. | Unknown |
| 12 | The server container on GitHub's package store has its own visibility setting and stays private unless changed. The image holds no secrets. | Strongly inferred (from the Dockerfile and workflow) |

## Verdict
Nothing secret is in the code or the history, so going public **won't leak a password or key**.
It isn't risk-free as it stands, because of #3 (email), #5 (server setup notes) and #11 (pictures).

Before going public:
1. Done 2026-10-31 (Jayden): "Keep my email addresses private" is on, so new merges don't show it.
2. Done 2026-10-31: the server-setup notes (#5) moved to the project's private notes
   (`gamenight/private-notes/server-setup.md`), with pointers in the docs. ntfy: signed-out reads are refused
   with 403 (Confirmed), so deny-all is Strongly inferred. Jayden confirms the setting.
3. Done 2026-10-31: Jayden says all the pictures (#11) can be public.
4. After going public: turn on secret scanning and push protection, require approval for outside PRs,
   and add branch protection on `main` (free for public repos: Strongly inferred, from GitHub's plan rules).

Old versions of #3, #4 and #5 stay readable in the history unless it's rewritten. A rewrite changes every
commit id and breaks the 6 open PRs and their branches, so it needs Jayden's explicit OK.

## Not done here (needs Jayden)
- Changing repo visibility or any GitHub setting.
- Rewriting history or deleting anything.
- Changing the project instructions (proposed wording is in the thread).
