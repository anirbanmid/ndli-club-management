"""
tests/test_r52_redaction_single_token.py

R52 Part A -- one redaction token for the WHOLE assistant surface.

The queued mismatch: `ai/llm_gateway.py` masked the API key with a PRIVATE
literal "[REDACTED]" (upper-case) while every other path -- ai.redaction,
ai.assistant_guard, ai.assistant_learning, the learning store, the audit
trail -- used the shared constant `redaction.SECRET_REDACTION` = "[redacted]"
(lower-case, pinned by tests/test_r45_redaction_unified.py). Same meaning,
two spellings: a reader of the logs could not tell whether two lines came
from one rule set or two, and the "ONE token" contract of R45 was quietly
broken inside the gateway.

These pins close it for good:

  * behaviour -- llm_gateway._redact must mask with the SHARED constant
    (identity, not a look-alike string);
  * source lock -- the upper-case "[REDACTED]" literal must never come back
    anywhere in ai/, and SECRET_REDACTION must stay defined exactly once
    (in ai/redaction.py), same style as test_r45's def-once lock.
"""
import _seed_env  # noqa: F401  (seed test credentials before config import)
import re
import unittest
from pathlib import Path
from unittest import mock

import ai.redaction as redaction
from ai import llm_gateway

ROOT = Path(__file__).resolve().parent.parent
FAKE_KEY = "TESTKEY-r52-not-a-real-secret"


class TestGatewayUsesTheSharedToken(unittest.TestCase):
    """Behaviour: the gateway's mask IS redaction.SECRET_REDACTION."""

    def _redact_with_key(self, text):
        with mock.patch.object(llm_gateway, "_get_api_key", return_value=FAKE_KEY):
            return llm_gateway._redact(text)

    def test_gateway_token_is_the_shared_constant(self):
        out = self._redact_with_key("leak %s here" % FAKE_KEY)
        self.assertEqual(out, "leak %s here" % redaction.SECRET_REDACTION,
                         "llm_gateway._redact must mask with ai.redaction.SECRET_REDACTION")

    def test_shared_token_literal_is_the_pinned_spelling(self):
        # the constant itself stays pinned (same literal test_r45 pins)
        self.assertEqual(redaction.SECRET_REDACTION, "[redacted]")

    def test_redact_without_key_is_identity(self):
        # no key configured -> nothing to mask, text passes through untouched
        with mock.patch.object(llm_gateway, "_get_api_key", return_value=""):
            self.assertEqual(llm_gateway._redact("plain %s text" % FAKE_KEY),
                             "plain %s text" % FAKE_KEY)

    def test_every_repeated_occurrence_is_masked(self):
        out = self._redact_with_key("%s and %s" % (FAKE_KEY, FAKE_KEY))
        self.assertNotIn(FAKE_KEY, out)
        self.assertEqual(out.count(redaction.SECRET_REDACTION), 2)


class TestSingleTokenSourceLock(unittest.TestCase):
    """Source locks: the mismatch must never silently come back."""

    def test_no_uppercase_redaction_literal_in_ai(self):
        # The whole point of R52: "[REDACTED]" (upper-case) is NOT a token this
        # codebase emits. A private literal anywhere in ai/ re-opens the split.
        offenders = []
        for p in sorted((ROOT / "ai").glob("*.py")):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if '"[REDACTED]"' in line or "'[REDACTED]'" in line:
                    offenders.append("%s:%d" % (p.name, n))
        self.assertEqual(offenders, [],
                         "ai/ must not carry a private upper-case redaction "
                         "literal; use redaction.SECRET_REDACTION: %s" % offenders)

    def test_token_constant_defined_exactly_once_in_ai(self):
        # SECRET_REDACTION is DEFINED only in ai/redaction.py; every other
        # module imports it (assistant_guard/assistant_learning re-export).
        defs = []
        for p in sorted((ROOT / "ai").glob("*.py")):
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if re.match(r"\s*SECRET_REDACTION\s*=", line):
                    defs.append("%s:%d" % (p.name, n))
        self.assertEqual(defs, ["redaction.py:%d" % self._definition_line()],
                         "SECRET_REDACTION must be DEFINED exactly once "
                         "(in ai/redaction.py); found: %s" % defs)

    def test_gateway_masks_with_imported_constant_not_a_literal(self):
        # llm_gateway must import the constant (so the pin above binds it) --
        # a re-spelled local literal would satisfy the behaviour tests while
        # still being a second definition in disguise.
        src = (ROOT / "ai" / "llm_gateway.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"from ai\.redaction import .*SECRET_REDACTION",
                         "llm_gateway must import SECRET_REDACTION from ai.redaction")

    def _definition_line(self):
        for n, line in enumerate(
                (ROOT / "ai" / "redaction.py").read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*SECRET_REDACTION\s*=", line):
                return n
        raise AssertionError("ai/redaction.py has no SECRET_REDACTION definition")


if __name__ == "__main__":
    unittest.main()
