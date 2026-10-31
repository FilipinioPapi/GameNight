#!/usr/bin/env python3
"""Look for anything sensitive before it reaches GitHub: keys, tokens, passwords, home-network
addresses, Discord ids, personal email addresses. Standard library only, so nothing is downloaded.

  python3 tools/security/scan_secrets.py              every tracked file as it is now
  python3 tools/security/scan_secrets.py --staged     only what is about to be committed (pre-commit hook)
  python3 tools/security/scan_secrets.py --history    every file version in every branch and tag
  python3 tools/security/scan_secrets.py --commits A..B   also checks those commits' emails and messages

Exits 1 when it finds something. A value that is safe on purpose goes in
tools/security/allowlist.txt with the reason (see docs/SECURITY_RULES.md).
"""
import argparse, ipaddress, os, re, subprocess, sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or "."
ALLOWLIST = os.path.join(ROOT, "tools", "security", "allowlist.txt")

# Files this scanner never reads: lock files (thousands of hashes), pictures, and the scanner's own rules.
SKIP_PATH = re.compile(r"(^|/)(package-lock\.json|Cargo\.lock)$|^tools/security/"
                       r"|\.(png|jpe?g|gif|webp|ico|icns|woff2?|ttf|otf|exe|dll|zip|7z|nes|sfc|smc)$", re.I)

RULES = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("Discord bot token", re.compile(r"\b[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}")),
    ("Discord webhook", re.compile(r"discord(app)?\.com/api/webhooks/\d+/[\w-]+")),
    ("Game Night sign-in pass", re.compile(r"\bgn_[A-Za-z0-9_-]{30,}")),
    ("cloud or service key", re.compile(r"\b(AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[abpr]-[A-Za-z0-9-]{10,}"
                                        r"|sk_live_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{32,})")),
    ("password or secret written in", re.compile(
        r"(?i)\b[\w-]*(password|passwd|secret|token|api[_-]?key)[\w-]*\b[\"']?\s*[:=]\s*[\"']([^\"'\s$<{][^\"'\s]{11,})[\"']")),
    ("Discord id", re.compile(r"(?<![\w.:/-])\d{17,20}(?![\w.-])")),
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")),
    ("home-network address", re.compile(r"(?<![\d.])(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?![\d.])")),
]

# Looks like a secret but is a placeholder, a public value or a test value.
PLACEHOLDER = re.compile(r"(?i)paste|your[-_]|example|changeme|placeholder|dummy|madeup|x{6,}|\*{4,}")
SAFE_EMAIL = re.compile(r"(?i)(noreply|no-reply)@|@(example\.(com|org)|users\.noreply\.github\.com|anthropic\.com)$"
                        r"|@\d+x\.(png|jpe?g|webp)$")


def load_allowlist():
    """Lines of `value  # reason`. A value listed here is never reported."""
    out = set()
    try:
        with open(ALLOWLIST, encoding="utf-8") as f:
            for line in f:
                v = line.split("#", 1)[0].strip()
                if v:
                    out.add(v)
    except FileNotFoundError:
        pass
    return out


def is_private_ip(text):
    try:
        ip = ipaddress.ip_address(text)
    except ValueError:
        return False
    # Loopback (127.x) and 0.0.0.0 say "this computer" and are safe. Home and office ranges are not.
    return ip.is_private and not ip.is_loopback and not ip.is_unspecified and not ip.is_link_local


def findings_in(text, allow):
    for n, line in enumerate(text.splitlines(), 1):
        for name, rx in RULES:
            for m in rx.finditer(line):
                value = m.group(0)
                if name == "home-network address":
                    value = m.group(1)
                    if not is_private_ip(value):
                        continue
                elif name == "email address":
                    if SAFE_EMAIL.search(value):
                        continue
                elif name == "password or secret written in":
                    value = m.group(2)
                    # Plain words like "access_token" are names, not secrets.
                    if PLACEHOLDER.search(value) or re.fullmatch(r"[a-z_.-]+", value):
                        continue
                elif name in ("GitHub token", "Game Night sign-in pass", "cloud or service key"):
                    if PLACEHOLDER.search(value):
                        continue
                if value in allow:
                    continue
                yield n, name, value


def git(*args, binary=False):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        sys.exit(f"git {' '.join(args)} failed: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout if binary else r.stdout.decode("utf-8", errors="replace")


def read_text(data):
    if b"\0" in data[:8000]:
        return None  # a binary file
    return data.decode("utf-8", errors="replace")


def targets(mode):
    """Yields (label, text) for each file to check."""
    if mode == "history":
        seen = set()
        for line in git("rev-list", "--all", "--objects").splitlines():
            parts = line.split(" ", 1)
            if len(parts) != 2 or SKIP_PATH.search(parts[1]):
                continue
            sha, path = parts
            if sha in seen or git("cat-file", "-t", sha).strip() != "blob":
                continue
            seen.add(sha)
            text = read_text(git("cat-file", "blob", sha, binary=True))
            if text is not None:
                yield f"{path} (version {sha[:8]})", text
        return
    if mode == "staged":
        names = git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split("\0")
    else:
        names = git("ls-files", "-z").split("\0")
    for path in filter(None, names):
        if SKIP_PATH.search(path):
            continue
        data = git("show", f":{path}", binary=True) if mode == "staged" else open(os.path.join(ROOT, path), "rb").read()
        text = read_text(data)
        if text is not None:
            yield path, text


def commit_targets(rng):
    for sha in git("rev-list", "--no-merges", rng).split():
        meta = git("show", "-s", "--format=%an <%ae>%n%cn <%ce>%n%B", sha)
        yield f"commit {sha[:8]} (author, committer and message)", meta


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true")
    g.add_argument("--history", action="store_true")
    p.add_argument("--commits", metavar="RANGE")
    a = p.parse_args()
    allow = load_allowlist()
    mode = "staged" if a.staged else "history" if a.history else "tree"

    found = 0
    checked = 0
    sources = list(targets(mode))
    if a.commits:
        sources += list(commit_targets(a.commits))
    for label, text in sources:
        checked += 1
        for n, name, value in findings_in(text, allow):
            found += 1
            print(f"{label}:{n}: {name}: {value}")
    if found:
        print(f"\n{found} thing(s) that look sensitive in {checked} checked. Remove them, or if one is safe on purpose,"
              f" add it to tools/security/allowlist.txt with the reason. See docs/SECURITY_RULES.md.")
        return 1
    print(f"Nothing sensitive found ({checked} checked, mode: {mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
