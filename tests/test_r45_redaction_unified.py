"""
tests/test_r45_redaction_unified.py

R45 — single-source secret redaction.

BEFORE R45 there were two different `redact_secrets()` implementations
(ai.assistant_guard for outbound answers, ai.assistant_learning for the learning
store + audit trail). They disagreed on 8 of 10 probe strings, so each path
leaked exactly what the other caught: an outbound answer could carry
`password: hunter2` while the store persisted `pbkdf2_sha256$...`.

This is the redaction twin of the R37 counting drift that R38 fixed by
single-sourcing db/counting_rules.py. These pins make the drift impossible to
reintroduce: the two entry points must stay THE SAME FUNCTION, and both must
agree on every string in a tricky corpus.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path

import ai.redaction as redaction
from ai import assistant_guard, assistant_learning

ROOT = Path(__file__).resolve().parent.parent

# Every string that used to make the two implementations disagree, plus the
# cases both already handled and the prose that must stay readable.
CORPUS = [
    # --- the 8 that DIVERGED before R45 ---
    "password: hunter2",
    "my password: hunter2 is wrong",
    "the seed password is Seed#Prod9x!",
    "pbkdf2_sha256$36000$abc$deadbeefcafe",
    "$pbkdf2-sha256$36000$xyz$0123456789abcdef",
    "Authorization: Bearer eyJhbGciOi.abc.def",
    "set NDLI_QR_SIGNING_KEY=abc123 in the env",
    "api_key = sk-live-1234567890",
    "relay_key: rk_secret_value",
    "access_key: AKIA-EXAMPLE-1234",
    "private_key = -----BEGIN RSA PRIVATE KEY-----",
    "token=abc123xyz",
    "passwd: hunter2",
    "pwd=letmein",
    "secret: s3cr3t",
    # --- must stay readable (documentation prose) ---
    "invalid pbkdf2 password or inactive employee account",
    "Please enter your password to continue.",
    "401 unauthorized on login: invalid pbkdf2 password or inactive employee "
    "account. Re-provision credentials via the admin portal.",
    "how many renewals are due in the East zone?",
    "The relay reported failure; check auth/config, not connectivity.",
]

# Shapes that MUST be masked after R45 (the superset of both old rule sets).
MUST_MASK = [
    ("password: hunter2", "hunter2"),
    ("api_key = sk-live-1234567890", "sk-live-1234567890"),
    ("relay_key: rk_secret_value", "rk_secret_value"),
    ("Authorization: Bearer eyJhbGciOi.abc.def", "eyJhbGciOi.abc.def"),
    ("the seed password is Seed#Prod9x!", "Seed#Prod9x!"),
    ("pbkdf2_sha256$36000$abc$deadbeefcafe", "pbkdf2_sha256$36000$abc$deadbeefcafe"),
    ("$pbkdf2-sha256$36000$xyz$0123456789abcdef", "$pbkdf2-sha256$36000$xyz$0123456789abcdef"),
    ("set NDLI_QR_SIGNING_KEY=abc123 in the env", "abc123"),
    ("token=abc123xyz", "abc123xyz"),
    ("access_key: AKIA-EXAMPLE-1234", "AKIA-EXAMPLE-1234"),
]


class TestSingleSource(unittest.TestCase):
    """The core structural fix: there is only ONE rule set."""

    def test_guard_and_learning_are_the_same_function(self):
        self.assertIs(assistant_guard.redact_secrets, redaction.redact_secrets,
                      "assistant_guard.redact_secrets must delegate to ai.redaction")
        self.assertIs(assistant_learning.redact_secrets, redaction.redact_secrets,
                      "assistant_learning.redact_secrets must delegate to ai.redaction")

    def test_redaction_token_is_one_constant(self):
        self.assertIs(assistant_guard.SECRET_REDACTION, redaction.SECRET_REDACTION)
        self.assertIs(assistant_learning.SECRET_REDACTION, redaction.SECRET_REDACTION)
        self.assertEqual(redaction.SECRET_REDACTION, "[redacted]")

    def test_only_one_redact_secrets_definition_in_ai(self):
        """Source lock: a second implementation must never come back."""
        defs = []
        for p in sorted((ROOT / "ai").glob("*.py")):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.match(r"\s*def redact_secrets\b", line):
                    defs.append("%s:%d" % (p.name, n))
        self.assertEqual(
            defs, ["redaction.py:%d" % self._redaction_def_line()],
            "redact_secrets must be DEFINED exactly once (in ai/redaction.py); "
            "found: %s" % defs)

    def _redaction_def_line(self):
        for n, line in enumerate(
                (ROOT / "ai" / "redaction.py").read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*def redact_secrets\b", line):
                return n
        raise AssertionError("ai/redaction.py has no redact_secrets definition")

    def test_rule_sets_are_not_duplicated_in_the_twins(self):
        """The twin modules must carry rules, not re-implement them."""
        for name in ("assistant_guard.py", "assistant_learning.py"):
            src = (ROOT / "ai" / name).read_text(encoding="utf-8")
            self.assertNotIn("pbkdf2", src,
                             "%s must not re-declare redaction rules (R45 single source)" % name)
            self.assertNotIn("_SECRET_PATTERNS", src, name)
            self.assertNotIn("_KEY_ASSIGN_RE", src, name)


class TestCrossPathAgreement(unittest.TestCase):
    """The invariant that was violated before R45."""

    def test_every_path_agrees_on_the_corpus(self):
        for text in CORPUS:
            with self.subTest(text=text):
                g = assistant_guard.redact_secrets(text)
                l = assistant_learning.redact_secrets(text)
                self.assertEqual(g, l, "outbound and storage paths disagree on %r" % text)

    def test_corpus_produces_identical_output_from_the_module(self):
        for text in CORPUS:
            with self.subTest(text=text):
                self.assertEqual(redaction.redact_secrets(text),
                                 assistant_guard.redact_secrets(text))


class TestSupersetBehaviour(unittest.TestCase):
    """Both old rule sets still fire - nothing that was masked before is unmasked."""

    def test_everything_once_masked_is_still_masked(self):
        for raw, secret in MUST_MASK:
            with self.subTest(raw=raw):
                out = redaction.redact_secrets(raw)
                self.assertNotIn(secret, out, "secret leaked: %r -> %r" % (raw, out))
                self.assertIn(redaction.SECRET_REDACTION, out)

    def test_key_name_is_preserved_for_readability(self):
        self.assertEqual(redaction.redact_secrets("password: hunter2"),
                         "password: [redacted]")
        self.assertEqual(redaction.redact_secrets("token=abc123xyz"),
                         "token=[redacted]")

    def test_seed_and_hash_string_masks_exactly_twice(self):
        out = redaction.redact_secrets(
            "use Seed#Abc999! then store $pbkdf2-sha256$29000$abc$def")
        self.assertEqual(out.count(redaction.SECRET_REDACTION), 2)


class TestDocumentationProseUnchanged(unittest.TestCase):
    """Redaction must never mangle the manuals' legitimate explanations."""

    def test_prose_stays_readable(self):
        prose = ("401 unauthorized on login: invalid pbkdf2 password or "
                 "inactive employee account. Re-provision credentials via the "
                 "admin portal.")
        self.assertEqual(redaction.redact_secrets(prose), prose)

    def test_ordinary_question_untouched(self):
        text = "how many renewals are due in the East zone?"
        self.assertEqual(redaction.redact_secrets(text), text)

    def test_none_and_empty_are_safe(self):
        self.assertEqual(redaction.redact_secrets(None), "")
        self.assertEqual(redaction.redact_secrets(""), "")


if __name__ == "__main__":
    unittest.main()
