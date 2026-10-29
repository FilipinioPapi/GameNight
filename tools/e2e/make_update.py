#!/usr/bin/env python3
"""CI only: publish a test update the way Jayden's NAS does, but signed with a throwaway key made on the spot.

    python make_update.py <setup.exe> <version> <updates folder>

Writes <folder>/v<version>/GameNightSetup.exe and <folder>/latest.json, and prints the throwaway public key
(base64 DER) for GAMENIGHT_UPDATE_KEY. Only the "e2e" test build of the app accepts another key.
"""
import base64, json, os, secrets, shutil, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'unraid'))
import gamenight_publish as pub  # noqa: E402


def main(setup, version, out):
    d = secrets.randbelow(pub.N - 1) + 1
    vdir = os.path.join(out, 'v' + version)
    os.makedirs(vdir, exist_ok=True)
    target = os.path.join(vdir, pub.ASSET)
    shutil.copyfile(setup, target)
    listing = {'app': 'gamenight', 'version': version, 'notes': ['Windows update test'],
               'file': {'path': 'v' + version + '/' + pub.ASSET, 'size': os.path.getsize(target),
                        'sha256': pub.sha256(target)}}
    body = json.dumps(listing, indent=1).encode('utf-8')
    doc = {'signed': base64.b64encode(body).decode(), 'signature': base64.b64encode(pub.sign(d, body)).decode()}
    with open(os.path.join(out, 'latest.json'), 'w', encoding='utf-8') as f:
        json.dump(doc, f)
    print(base64.b64encode(pub.public_der(d)).decode())


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
