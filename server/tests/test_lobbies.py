import pytest

from gamenight import app as appmod
from gamenight import lobbies as lb
from gamenight.config import base_path
from gamenight.db import Database
from gamenight.romm import Game

from test_server import cfg

SESSION = "AAECAwQFBgcICQoL"   # 12 bytes in base64
RELAY = {"server": "relay.libretro.com", "port": 55435, "session": SESSION}
GAMES = {
    7: Game(7, "Super Mario Bros.", "nes", "1-2", 1, "", "", "smb.nes"),
    8: Game(8, "Super Bomberman", "snes", "1-4", 1, "", "", "sb.sfc"),
    9: Game(9, "Sonic", "gen", "1", 1, "", "", "sonic.md"),
}
MARIO = {"id": "7", "title": "Super Mario Bros.", "console": "nes", "players": "1-2"}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def person(n: int) -> dict:
    return {"id": str(100 + n), "name": f"Friend{n}", "avatar": ""}


@pytest.fixture
def book():
    clock = Clock()
    b = lb.LobbyBook(clock=clock)
    b.clock_ = clock
    return b


def beat(book, code, *who):
    for p in who:
        book.heartbeat(code, p["id"], "running")


# ---------- pure lobby logic ----------

def test_codes():
    seen = set()
    b = lb.LobbyBook()
    for i in range(50):
        view = b.host(person(i), MARIO, True)
        code = view["code"]
        assert lb.CODE_RE.match(code) and len(code) == 6
        assert not set(code) & set("O0I1")
        seen.add(code)
    assert len(seen) == 50
    assert lb.normalise_code("  abc234 ") == "ABC234"
    assert lb.normalise_code("ABC10O") is None
    assert lb.normalise_code("ABC23") is None


def test_host_and_join_play_and_watch(book):
    host = book.host(person(0), MARIO, False)
    code = host["code"]
    assert host["you"] == {"id": "100", "role": "host", "seat": 1}
    assert host["seats"][0]["status"] == "playing" and host["seats"][1]["status"] == "empty"
    v = book.join(code.lower(), person(1), "play")
    assert v["you"] == {"id": "101", "role": "play", "seat": 2}
    v = book.join(code, person(2), "watch")
    assert v["you"]["role"] == "watch" and v["you"]["seat"] is None
    assert [w["id"] for w in v["watchers"]] == ["102"]
    assert v["players"] == 2
    assert book.summary(book.lobbies[code])["watchers"] == 1   # the full Lobby lists them instead


def test_full_seats_and_places(book):
    code = book.host(person(0), MARIO, True)["code"]
    for i in (1, 2, 3):
        book.join(code, person(i), "play")
    with pytest.raises(lb.LobbyError) as e:
        book.join(code, person(4), "play")
    assert e.value.status == 409 and e.value.message == "All 4 seats are taken. You can watch."
    for i in (4, 5, 6, 7):
        book.join(code, person(i), "watch")
    with pytest.raises(lb.LobbyError) as e:
        book.join(code, person(8), "watch")
    assert e.value.status == 409


def test_switch(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    v = book.switch(code, "101", "watch")
    assert v["you"]["role"] == "watch" and v["seats"][1]["user"] is None
    v = book.switch(code, "101", "play")
    assert v["you"] == {"id": "101", "role": "play", "seat": 2}
    with pytest.raises(lb.LobbyError) as e:
        book.switch(code, "100", "watch")
    assert e.value.status == 409
    for i in (2, 3):
        book.join(code, person(i), "play")
    book.join(code, person(4), "watch")
    with pytest.raises(lb.LobbyError) as e:
        book.switch(code, "104", "play")
    assert e.value.status == 409


def test_pause_for_everyone(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    book.join(code, person(2), "watch")
    assert book.view(book.lobbies[code], "100")["paused"] is None
    with pytest.raises(lb.LobbyError) as e:
        book.pause(code, "102", True)          # watchers can't pause
    assert e.value.status == 409
    v = book.pause(code, "101", True)           # a friend pauses
    assert v["paused"] == {"by": person(1), "seconds": 0, "ago": 0.0}
    book.clock_.t += 5
    beat(book, code, person(0), person(1), person(2))
    v = book.pause(code, "100", True)           # already paused: stays the friend's
    assert v["paused"]["by"]["id"] == "101" and v["paused"]["seconds"] == 5 and v["paused"]["ago"] == 5.0
    assert v["resumed_ago"] is None
    with pytest.raises(lb.LobbyError) as e:
        book.pause(code, "102", False)          # someone else can't resume it
    assert e.value.status == 403
    v = book.pause(code, "100", False)          # the host can
    assert v["paused"] is None and v["resumed_ago"] == 0.0
    book.clock_.t += 2.5
    assert book.view(book.lobbies[code], "101")["resumed_ago"] == 2.5   # each PC knows how long ago it ended
    book.clock_.t += 13
    assert book.view(book.lobbies[code], "101")["resumed_ago"] is None  # and after 15 s it's forgotten
    book.pause(code, "101", True)
    assert book.pause(code, "101", False)["paused"] is None   # and so can the one who paused
    # the one who paused drops out, switches to watching or leaves: the game carries on
    book.pause(code, "101", True)
    book.clock_.t += 11
    beat(book, code, person(0))
    assert book.view(book.lobbies[code], "100")["paused"] is None
    book.join(code, person(1), "play")
    book.pause(code, "101", True)
    assert book.switch(code, "101", "watch")["paused"] is None
    book.switch(code, "101", "play")
    book.pause(code, "101", True)
    book.leave(code, "101")
    assert book.view(book.lobbies[code], "100")["paused"] is None
    # a pause ends by itself after 10 minutes
    book.pause(code, "100", True)
    for _ in range(67):
        book.clock_.t += 9
        beat(book, code, person(0))
    assert book.view(book.lobbies[code], "100")["paused"] is None


def test_drop_hold_then_empty(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    book.join(code, person(2), "watch")
    book.clock_.t += 9
    beat(book, code, person(0))
    assert book.view(book.lobbies[code], "100")["seats"][1]["status"] == "playing"
    book.clock_.t += 2     # 11 s without a heartbeat
    beat(book, code, person(0))
    v = book.lookup(code, "100")
    assert v["seats"][1]["status"] == "held"
    assert v["seats"][1]["held_left"] == 119
    assert v["watchers"] == []          # a silent watcher just goes
    for _ in range(11):
        book.clock_.t += 10
        beat(book, code, person(0))
    v = book.lookup(code, "100")
    assert v["seats"][1]["status"] == "held" and v["seats"][1]["held_left"] == 9
    book.clock_.t += 9
    beat(book, code, person(0))
    v = book.lookup(code, "100")
    assert v["seats"][1] == {"n": 2, "user": None, "status": "empty", "held_left": None}
    with pytest.raises(lb.LobbyError) as e:
        book.heartbeat(code, "101", "running")
    assert e.value.status == 404


def test_rejoin_gets_seat_back(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    book.join(code, person(2), "play")
    for _ in range(11):     # 55 s: person 1 is silent, the others keep beating
        book.clock_.t += 5
        beat(book, code, person(0), person(2))
    assert book.lookup(code, "100")["seats"][1]["status"] == "held"
    book.join(code, person(3), "play")        # takes seat 4, not the held seat 2
    v = book.join(code, person(1), "play")
    assert v["you"]["seat"] == 2 and v["seats"][1]["status"] == "playing"
    assert book.lookup(code, "103")["you"]["seat"] == 4


def test_host_seat_actions(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    book.join(code, person(2), "watch")
    book.join(code, person(3), "play")
    with pytest.raises(lb.LobbyError) as e:
        book.seat_action(code, "101", 3, "empty", None)
    assert e.value.status == 403
    with pytest.raises(lb.LobbyError):
        book.seat_action(code, "100", 2, "hold", None)     # nobody is away
    for _ in range(20):     # 100 s: person 1 is silent
        book.clock_.t += 5
        beat(book, code, person(0), person(2), person(3))
    v = book.lookup(code, "100")
    assert v["seats"][1]["status"] == "held" and v["seats"][1]["held_left"] == 30
    v = book.seat_action(code, "100", 2, "hold", None)
    assert v["seats"][1]["held_left"] == 120
    # give the held seat to the watcher
    v = book.seat_action(code, "100", 2, "give", "102")
    assert v["seats"][1]["user"]["id"] == "102" and v["seats"][1]["status"] == "playing"
    assert v["watchers"] == [] and "101" not in book.lobbies[code].members
    assert book.lookup(code, "102")["you"] == {"id": "102", "role": "play", "seat": 2}
    # empty someone who is still here: they become a watcher
    v = book.seat_action(code, "100", 3, "empty", None)
    assert v["seats"][2]["user"] is None and [w["id"] for w in v["watchers"]] == ["103"]
    with pytest.raises(lb.LobbyError):
        book.seat_action(code, "100", 3, "give", "999")
    with pytest.raises(lb.LobbyError):
        book.seat_action(code, "100", 1, "empty", None)


def test_open_and_closed_listing(book):
    a = book.host(person(0), MARIO, True)["code"]
    b = book.host(person(1), MARIO, False)["code"]
    assert [x["code"] for x in book.open_list()] == [a]
    assert "relay" not in book.open_list()[0] and "seats" not in book.open_list()[0]
    book.set_open(b, "101", True)
    assert {x["code"] for x in book.open_list()} == {a, b}
    book.set_open(a, "100", False)
    assert [x["code"] for x in book.open_list()] == [b]
    # a closed lobby is still found by its code
    assert book.lookup(a, "105")["code"] == a


def test_relay_only_for_members(book):
    code = book.host(person(0), MARIO, False)["code"]
    v = book.set_relay(code, "100", "relay.libretro.com", 55435, SESSION)
    assert v["relay"] == {"server": "relay.libretro.com", "port": 55435, "session": SESSION} and v["started"]
    outsider = book.lookup(code, "105")
    assert "relay" not in outsider and "seats" not in outsider and outsider["started"]
    assert book.join(code, person(1), "watch")["relay"]["session"] == SESSION
    with pytest.raises(lb.LobbyError) as e:
        book.set_relay(code, "101", "evil.example", 1, SESSION)
    assert e.value.status == 403


def test_host_timeout_ends_lobby(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.set_relay(code, "100", "relay.libretro.com", 55435, SESSION)
    book.join(code, person(1), "play")
    book.clock_.t += 15
    beat(book, code, person(1))
    v = book.lookup(code, "101")
    assert v["seats"][0]["status"] == "held" and v["seats"][0]["held_left"] == 15
    book.clock_.t += 15
    v = book.heartbeat(code, "101", "running")
    assert v["ended"] == "host-left" and v["relay"] is None
    assert book.open_list() == []
    with pytest.raises(lb.LobbyError) as e:
        book.lookup(code, "105")
    assert e.value.status == 404 and e.value.message == "That code doesn't match an open lobby."
    with pytest.raises(lb.LobbyError):
        book.join(code, person(2), "play")
    book.clock_.t += 61
    with pytest.raises(lb.LobbyError):
        book.lookup(code, "101")
    assert code not in book.lobbies


def test_host_leaves_or_hosts_again(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    book.leave(code, "100")
    assert book.heartbeat(code, "101", "running")["ended"] == "host-ended"
    code2 = book.host(person(0), MARIO, True)["code"]
    code3 = book.host(person(0), MARIO, True)["code"]   # hosting again ends the old one
    assert book.lookup(code2, "100")["ended"] == "host-ended"
    assert [x["code"] for x in book.open_list()] == [code3]
    book.leave("ZZZZZZ", "100")   # a wrong code is fine


def test_player_leaves(book):
    code = book.host(person(0), MARIO, True)["code"]
    book.join(code, person(1), "play")
    book.leave(code, "101")
    assert book.lookup(code, "100")["seats"][1]["status"] == "empty"   # not held: they chose to go


def test_lobby_cap():
    b = lb.LobbyBook()
    for i in range(lb.MAX_LOBBIES):
        b.host(person(i), MARIO, False)
    with pytest.raises(lb.LobbyError) as e:
        b.host(person(999), MARIO, False)
    assert e.value.status == 503


def test_input_checks():
    assert lb.valid_relay_server("relay.libretro.com")
    assert lb.valid_relay_server("1.2.3.4") and lb.valid_relay_server("2001:db8::1")
    for bad in ("", "a" * 254, "-bad.com", "bad-.com", "a..b", "x/y", "x y", "http://x", 5, None, "a.b:1"):
        assert not lb.valid_relay_server(bad), bad
    assert lb.valid_session(SESSION)
    for bad in ("AAECAwQFBgcICQo=", "AAECAwQFBgcICQoLDA==", "AAECAwQFBgcICQo!", "", 12, None):
        assert not lb.valid_session(bad), bad
    assert base_path("") == "" and base_path("/") == ""
    assert base_path("/gamenight/") == "/gamenight" and base_path("gamenight") == "/gamenight"
    for bad in ("/a/b", "/api", "/game night", "/../x", "/" + "a" * 41):
        with pytest.raises(SystemExit):
            base_path(bad)


# ---------- over the web ----------

class FakeRomM:
    def __init__(self, http, cfg):
        pass

    async def games(self):
        return GAMES


async def make_client(aiohttp_client, **kw):
    db = Database(":memory:")
    clock = Clock()
    c = await aiohttp_client(appmod.build(cfg(**kw), db=db, romm_factory=FakeRomM, lobbies=lb.LobbyBook(clock=clock)))
    c.clock = clock
    c.h = {}
    for i in range(6):
        p = person(i)
        db.upsert_user(p["id"], p["name"], p["avatar"])
        c.h[i] = {"Authorization": "Bearer " + db.create_session(p["id"])}
    return c


@pytest.fixture
async def client(aiohttp_client):
    return await make_client(aiohttp_client)


async def test_web_flow(client):
    c, h = client, client.h
    assert (await c.get("/api/lobbies")).status == 401
    r = await c.post("/api/lobbies", json={"game_id": "7", "open": True}, headers=h[0])
    assert r.status == 200
    lobby = await r.json()
    code = lobby["code"]
    assert lobby["game"] == MARIO and lobby["host"]["id"] == "100" and lobby["relay"] is None
    r = await c.post(f"/api/lobbies/{code}/relay", json=RELAY, headers=h[0])
    assert (await r.json())["relay"] == RELAY
    listed = (await (await c.get("/api/lobbies", headers=h[1])).json())["lobbies"]
    assert [x["code"] for x in listed] == [code] and "relay" not in listed[0]
    peek = await (await c.get(f"/api/lobbies/{code.lower()}", headers=h[1])).json()
    assert "relay" not in peek and peek["players"] == 1
    r = await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[1])
    assert (await r.json())["relay"] == RELAY
    for i in (2, 3):
        await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[i])
    r = await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[4])
    assert r.status == 409 and await r.text() == "All 4 seats are taken. You can watch."
    r = await c.post(f"/api/lobbies/{code}/join", json={"as": "watch"}, headers=h[4])
    assert (await r.json())["you"]["role"] == "watch"
    r = await c.post(f"/api/lobbies/{code}/switch", json={"as": "watch"}, headers=h[3])
    assert (await r.json())["you"]["role"] == "watch"
    r = await c.post(f"/api/lobbies/{code}/heartbeat", json={"retroarch": "running"}, headers=h[1])
    assert r.status == 200
    r = await c.patch(f"/api/lobbies/{code}", json={"open": False}, headers=h[1])
    assert r.status == 403 and await r.text() == "Only the host can do that."
    r = await c.patch(f"/api/lobbies/{code}", json={"open": False}, headers=h[0])
    assert (await r.json())["open"] is False
    r = await c.post(f"/api/lobbies/{code}/pause", json={"on": True}, headers=h[1])
    assert (await r.json())["paused"]["by"]["id"] == "101"
    r = await c.post(f"/api/lobbies/{code}/pause", json={"on": "yes"}, headers=h[1])
    assert r.status == 400
    r = await c.post(f"/api/lobbies/{code}/pause", json={"on": False}, headers=h[4])
    assert r.status == 403
    r = await c.post(f"/api/lobbies/{code}/pause", json={"on": False}, headers=h[0])
    assert (await r.json())["paused"] is None
    r = await c.post(f"/api/lobbies/{code}/seat", json={"seat": 4, "action": "give", "user": "103"}, headers=h[0])
    assert (await r.json())["seats"][3]["user"]["id"] == "103"
    r = await c.post(f"/api/lobbies/{code}/leave", headers=h[0])
    assert await r.json() == {"ok": True}
    r = await c.post(f"/api/lobbies/{code}/heartbeat", json={"retroarch": "running"}, headers=h[1])
    assert (await r.json())["ended"] == "host-ended"
    r = await c.get(f"/api/lobbies/{code}", headers=h[5])
    assert r.status == 404 and await r.text() == "That code doesn't match an open lobby."


async def test_web_wrong_games(client):
    for gid, status in (("9", 400), ("55", 404)):
        r = await client.post("/api/lobbies", json={"game_id": gid, "open": True}, headers=client.h[0])
        assert r.status == status
    r = await client.post("/api/lobbies", json={"game_id": "8", "open": True}, headers=client.h[0])
    assert (await r.json())["game"]["console"] == "snes"


async def test_web_bad_input(client):
    c, h = client, client.h
    code = (await (await c.post("/api/lobbies", json={"game_id": "7", "open": True}, headers=h[0])).json())["code"]
    bad_posts = [
        ("/api/lobbies", {"game_id": 7, "open": True}),
        ("/api/lobbies", {"game_id": "7", "open": "yes"}),
        ("/api/lobbies", {"game_id": "7"}),
        ("/api/lobbies", {"game_id": "7", "open": True, "extra": 1}),
        ("/api/lobbies", ["7"]),
        (f"/api/lobbies/{code}/join", {"as": "host"}),
        (f"/api/lobbies/{code}/heartbeat", {"retroarch": "fine"}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "port": 0}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "port": 70000}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "port": True}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "port": "55435"}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "server": "evil.com/x"}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "server": "a" * 254}),
        (f"/api/lobbies/{code}/relay", {**RELAY, "session": "AAAA"}),
        (f"/api/lobbies/{code}/relay", {"server": "relay.libretro.com", "port": 55435}),
        (f"/api/lobbies/{code}/seat", {"seat": 5, "action": "empty"}),
        (f"/api/lobbies/{code}/seat", {"seat": 2, "action": "kick"}),
        (f"/api/lobbies/{code}/seat", {"seat": 2, "action": "give"}),
        (f"/api/lobbies/{code}/seat", {"seat": 2, "action": "give", "user": "<script>"}),
    ]
    for path, body in bad_posts:
        r = await c.post(path, json=body, headers=h[0])
        assert r.status == 400, (path, body)
    r = await c.post(f"/api/lobbies/{code}/join", data="not json", headers=h[1])
    assert r.status == 400
    r = await c.patch(f"/api/lobbies/{code}", json={"open": 1}, headers=h[0])
    assert r.status == 400
    # people outside the lobby get the same answer as a wrong code
    for path in ("heartbeat", "switch"):
        body = {"retroarch": "running"} if path == "heartbeat" else {"as": "play"}
        r = await c.post(f"/api/lobbies/{code}/{path}", json=body, headers=h[5])
        assert r.status == 404
    r = await c.post(f"/api/lobbies/{code}/relay", json=RELAY, headers=h[5])
    assert r.status == 404


async def test_web_code_rate_limit(client):
    c, h = client, client.h
    code = (await (await c.post("/api/lobbies", json={"game_id": "7", "open": False}, headers=h[0])).json())["code"]
    for _ in range(20):
        assert (await c.get("/api/lobbies/ZZZZZZ", headers=h[1])).status == 404
    assert (await c.get(f"/api/lobbies/{code}", headers=h[1])).status == 429
    assert (await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[1])).status == 429
    # someone else isn't affected, and members looking at their own lobby aren't counted
    for _ in range(25):
        assert (await c.get(f"/api/lobbies/{code}", headers=h[0])).status == 200
    assert (await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[2])).status == 200


async def test_web_heartbeat_timings(client):
    c, h = client, client.h
    code = (await (await c.post("/api/lobbies", json={"game_id": "7", "open": True}, headers=h[0])).json())["code"]
    await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[1])
    for _ in range(4):
        c.clock.t += 3
        await c.post(f"/api/lobbies/{code}/heartbeat", json={"retroarch": "running"}, headers=h[0])
    lobby = await (await c.get(f"/api/lobbies/{code}", headers=h[0])).json()
    assert lobby["seats"][1]["status"] == "held" and lobby["seats"][1]["held_left"] == 118
    r = await c.post(f"/api/lobbies/{code}/join", json={"as": "play"}, headers=h[1])
    assert (await r.json())["you"]["seat"] == 2
    c.clock.t += 31
    r = await c.post(f"/api/lobbies/{code}/heartbeat", json={"retroarch": "running"}, headers=h[1])
    assert (await r.json())["ended"] == "host-left"


async def test_base_path(aiohttp_client):
    c = await make_client(aiohttp_client, public_url="https://play.jjsnas.xyz/gamenight", base_path="/gamenight")
    h = c.h
    for prefix in ("", "/gamenight"):
        assert (await c.get(prefix + "/healthz")).status == 200
        assert (await c.get(prefix + "/api/me")).status == 401
        assert (await (await c.get(prefix + "/api/me", headers=h[0])).json())["id"] == "100"
        assert (await c.get(prefix + "/api/lobbies")).status == 401
        assert (await c.get(prefix + "/api/lobbies", headers=h[0])).status == 200
    r = await c.post("/gamenight/api/lobbies", json={"game_id": "7", "open": True}, headers=h[0])
    code = (await r.json())["code"]
    r = await c.post(f"/gamenight/api/lobbies/{code}/join", json={"as": "watch"}, headers=h[1])
    assert r.status == 200
    assert (await c.get(f"/api/lobbies/{code}", headers=h[1])).status == 200
    # sign-in pages answer under it too, and Discord is sent back to the address with the folder
    assert (await c.post("/gamenight/api/session", json={"code": "x", "verifier": "y"})).status == 401
    r = await c.get("/gamenight/app/login", params={"challenge": "a" * 43}, allow_redirects=False)
    assert r.status == 302 and "redirect_uri=https://play.jjsnas.xyz/gamenight/auth/callback&" in r.headers["Location"]
    assert (await c.get("/other/api/me", headers=h[0])).status == 404
