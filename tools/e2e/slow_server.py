#!/usr/bin/env python3
"""CI only: serves the test update folder at about home-internet speed, so the update test sees the download
progress the way Jayden does (a local server sends 45 MB in an instant, which hides progress problems).

    python slow_server.py <folder> <port> <bytes per second>
"""
import functools, http.server, sys, time


class Slow(http.server.SimpleHTTPRequestHandler):
    rate = 3_000_000

    def copyfile(self, source, outputfile):
        step = 64 * 1024
        while True:
            buf = source.read(step)
            if not buf:
                break
            outputfile.write(buf)
            time.sleep(len(buf) / self.rate)

    def log_message(self, *a):
        pass


def main(folder, port, rate):
    Slow.rate = int(rate)
    handler = functools.partial(Slow, directory=folder)
    http.server.ThreadingHTTPServer(('127.0.0.1', int(port)), handler).serve_forever()


if __name__ == '__main__':
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
