#!/usr/bin/env python3
"""Publish a Game Night release for the app's built-in updater (signed, like Roof Rage's).

    python3 gamenight_publish.py <updates folder>                  (run by gamenight_sync.sh)
    python3 gamenight_publish.py --local <setup.exe> <version> <updates folder> [notes.txt]

Run on Jayden's Unraid inside python:3.12-alpine (standard library only). It downloads the newest GitHub
release's GameNightSetup.exe (GITHUB_TOKEN, read-only), writes <updates>/v<version>/GameNightSetup.exe first
and <updates>/latest.json last (renamed into place), so the app never sees a list whose file isn't there yet.

latest.json = {"signed": base64 of the file-list JSON, "signature": base64 ECDSA P-256 / SHA-256, r||s}.
The file list says "app": "gamenight", the version, up to three what's-new lines and the installer's size and
SHA-256. It is signed with the same NAS key as Roof Rage (/mnt/user/appdata/roofrage-sync/signing_key.pem,
mounted read-only as /key/signing_key.pem, never in the served folder). Game Night only accepts signed lists,
so with no key nothing is published.
"""
import base64, hashlib, json, os, re, secrets, shutil, sys, tempfile, urllib.request

REPO = 'FilipinioPapi/GameNight'
ASSET = 'GameNightSetup.exe'
KEY_PATH = os.environ.get('GAMENIGHT_SIGNING_KEY', '/key/signing_key.pem')

# The public half built into the app (app/src-tauri/src/updater.rs), the same key as Roof Rage's.
APP_PUBLIC_KEY = ('MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE4zX4sOgPfXg0T4Ok42sTYgDvmX5F'
                  '3w9ultC1kbHtnGWHRSkWXte+B+8jZxpppMBKcb6VQW0G7xHdqItygt83xw==')


# ECDSA P-256 / SHA-256 signing, standard library only (the NAS's python:3.12-alpine has no crypto library). Only
# signing lives here; the app checks with the p256 crate, and every signature is checked again before use, so
# a mistake here can only make a signature the game refuses, never a weaker one. Kept in this one file because
# gamenight_sync.sh (pasted into Unraid by hand) fetches only this file.
P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
A = P - 3
B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
     0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % P == 0:
        return None
    if p1 == p2:
        m = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        m = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (m * m - x1 - x2) % P
    return x3, (m * (x1 - x3) - y1) % P


def _mul(k, pt):
    out = None
    while k:
        if k & 1:
            out = _add(out, pt)
        pt = _add(pt, pt)
        k >>= 1
    return out


def load_key(pem_text):
    """The private number from an openssl EC key (SEC1 'EC PRIVATE KEY' or PKCS#8 'PRIVATE KEY'), P-256 only."""
    body = re.search(r'-----BEGIN (?:EC )?PRIVATE KEY-----(.*?)-----END', pem_text, re.S)
    if not body:
        raise ValueError('not a PEM private key')
    der = base64.b64decode(''.join(body.group(1).split()))
    if bytes.fromhex('2a8648ce3d030107') not in der:          # OID 1.2.840.10045.3.1.7 = P-256
        raise ValueError('key is not a P-256 key')
    i = der.find(b'\x02\x01\x01\x04\x20')                      # version 1, then the 32-byte private number
    if i < 0:
        raise ValueError('could not find the private number in the key')
    d = int.from_bytes(der[i + 5:i + 37], 'big')
    if not 0 < d < N:
        raise ValueError('bad private number')
    return d


def public_der(d):
    """SubjectPublicKeyInfo DER (what the game has built in as base64)."""
    x, y = _mul(d, G)
    head = bytes.fromhex('3059301306072a8648ce3d020106082a8648ce3d030107034200')
    return head + b'\x04' + x.to_bytes(32, 'big') + y.to_bytes(32, 'big')


def verify(q, data, sig):
    if len(sig) != 64:
        return False
    r, s = int.from_bytes(sig[:32], 'big'), int.from_bytes(sig[32:], 'big')
    if not (0 < r < N and 0 < s < N):
        return False
    e = int.from_bytes(hashlib.sha256(data).digest(), 'big')
    w = pow(s, -1, N)
    pt = _add(_mul(e * w % N, G), _mul(r * w % N, q))
    return pt is not None and pt[0] % N == r


def sign(d, data):
    """64 bytes r||s (IEEE P1363), checked against the public key before it is returned."""
    e = int.from_bytes(hashlib.sha256(data).digest(), 'big')
    while True:
        k = secrets.randbelow(N - 1) + 1
        r = _mul(k, G)[0] % N
        if r == 0:
            continue
        s = pow(k, -1, N) * (e + r * d) % N
        if s == 0:
            continue
        sig = r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
        if not verify(_mul(d, G), data, sig):
            raise RuntimeError('signature failed its own check')
        return sig


def sign_listing(listing, key_path=KEY_PATH, public_key=APP_PUBLIC_KEY):
    if not os.path.exists(key_path):
        sys.exit('no signing key at ' + key_path + ': not publishing (Game Night only accepts signed updates)')
    with open(key_path, encoding='ascii') as f:
        d = load_key(f.read())
    if base64.b64encode(public_der(d)).decode() != public_key:
        sys.exit('signing key does not match the public key built into the app: not publishing')
    body = json.dumps(listing, indent=1).encode('utf-8')
    return {'signed': base64.b64encode(body).decode(), 'signature': base64.b64encode(sign(d, body)).decode()}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def clean_version(tag):
    v = tag.strip().lstrip('vV')
    if not re.fullmatch(r'\d{1,4}\.\d{1,4}\.\d{1,4}', v):
        sys.exit('odd version ' + repr(tag) + ': not publishing')
    return v


def clean_notes(text):
    lines = [l.strip(' -*\t') for l in (text or '').splitlines()]
    return [l[:80] for l in lines if l][:3]


def publish(setup, version, out, notes):
    """Version folder first, latest.json last. A version already published is left alone."""
    vdir = os.path.join(out, 'v' + version)
    target = os.path.join(vdir, ASSET)
    if not os.path.exists(target):
        os.makedirs(vdir, exist_ok=True)
        tmp = target + '.part'
        shutil.copyfile(setup, tmp)
        os.replace(tmp, target)
    listing = {'app': 'gamenight', 'version': version, 'notes': notes,
               'file': {'path': 'v' + version + '/' + ASSET, 'size': os.path.getsize(target), 'sha256': sha256(target)}}
    doc = sign_listing(listing)
    tmp = os.path.join(out, 'latest.json.part')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f)
    os.replace(tmp, os.path.join(out, 'latest.json'))
    print('published v' + version + ' (' + str(listing['file']['size']) + ' bytes, signed)')


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    """GitHub sends release files from another host: never forward the token there."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.headers.pop('Authorization', None)
            new.unredirected_hdrs.pop('Authorization', None)
        return new


def github(url, accept='application/vnd.github+json'):
    token = os.environ.get('GITHUB_TOKEN', '')
    req = urllib.request.Request(url, headers={'Accept': accept, 'X-GitHub-Api-Version': '2022-11-28',
                                               'User-Agent': 'gamenight-sync'})
    req.add_unredirected_header('Authorization', 'Bearer ' + token)
    return urllib.request.build_opener(_NoAuthOnRedirect).open(req, timeout=120)


def from_github(out):
    with github('https://api.github.com/repos/' + REPO + '/releases/latest') as r:
        rel = json.load(r)
    version = clean_version(rel.get('tag_name', ''))
    asset = next((a for a in rel.get('assets', []) if a.get('name') == ASSET), None)
    if not asset:
        sys.exit('release ' + rel.get('tag_name', '?') + ' has no ' + ASSET + ': not publishing')
    with tempfile.TemporaryDirectory() as tmp:
        setup = os.path.join(tmp, ASSET)
        with github(asset['url'], 'application/octet-stream') as r, open(setup, 'wb') as f:
            shutil.copyfileobj(r, f)
        if os.path.getsize(setup) != asset.get('size'):
            sys.exit('download was the wrong size: not publishing')
        publish(setup, version, out, clean_notes(rel.get('body')))


def main(argv):
    if len(argv) >= 4 and argv[0] == '--local':
        notes = open(argv[4], encoding='utf-8').read() if len(argv) > 4 else ''
        publish(argv[1], clean_version(argv[2]), argv[3], clean_notes(notes))
    elif len(argv) == 1:
        from_github(argv[0])
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main(sys.argv[1:])
