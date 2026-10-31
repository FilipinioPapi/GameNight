"""Checks that the secret scan catches what it should and leaves normal code alone.

  python3 -m unittest tools/security/test_scan_secrets.py

The fake secrets are glued together at run time, so this file never contains one itself.
"""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(__file__))
import scan_secrets as s  # noqa: E402


def names(text, allow=frozenset()):
    return [name for _, name, _ in s.findings_in(text, allow)]


class Catches(unittest.TestCase):
    def test_private_key(self):
        self.assertIn("private key", names("-----BEGIN " + "EC PRIVATE KEY-----"))

    def test_github_token(self):
        self.assertIn("GitHub token", names('TOKEN="' + "ghp_" + "a1B2c3D4" * 5 + '"'))

    def test_discord_bot_token(self):
        fake = "M" + "T" * 25 + "." + "Gabcde" + "." + "x1" * 15
        self.assertIn("Discord bot token", names(fake))

    def test_discord_webhook(self):
        self.assertIn("Discord webhook", names("https://discord.com/api/" + "webhooks/123/abc-def"))

    def test_sign_in_pass(self):
        self.assertIn("Game Night sign-in pass", names("gn_" + "Zq9" * 12))

    def test_written_in_password(self):
        self.assertIn("password or secret written in", names('ROMM_PASSWORD = "' + "hunter2" + "-and-more" + '"'))

    def test_discord_id(self):
        self.assertIn("Discord id", names("DISCORD_GUILD_ID=" + "1234567890" + "12345678"))

    def test_personal_email(self):
        self.assertIn("email address", names("contact: someone" + "@" + "proton.me"))

    def test_home_network_address(self):
        self.assertIn("home-network address", names("http://" + "192.168." + "0.20:8094"))
        self.assertIn("home-network address", names("10.0." + "0.5"))


class LeavesAlone(unittest.TestCase):
    def test_normal_code(self):
        self.assertEqual(names('let token = token.ok_or("signed-out")?;'), [])
        self.assertEqual(names('data={"token": token, "token_type_hint": "access_token"}'), [])
        self.assertEqual(names('TOKEN="PASTE-YOUR-GITHUB-TOKEN-HERE"'), [])
        self.assertEqual(names("http://127.0.0.1:8094 and 0.0.0.0 and 8.8.8.8"), [])
        self.assertEqual(names("Co-Authored-By: Claude <noreply" + "@anthropic.com>"), [])
        self.assertEqual(names('"icons/128x128@2x.png"'), [])
        self.assertEqual(names("version 1.22.2 and 0.3.3"), [])

    def test_allowlist(self):
        self.assertEqual(names("http://" + "192.168.1.33:8094", {"192.168.1.33"}), [])


if __name__ == "__main__":
    unittest.main()
