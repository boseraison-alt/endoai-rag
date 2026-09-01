"""
/health reports the commit this PROCESS is running (guardrails-v1 Item 0).

The defect this closes: `endo-ai-noreload` does not pick up code changes by
design, and nothing about a running server said which commit it had imported.
PID 35820 served `grounding-v1` code throughout the whole of `grounding-v2`,
and two batches spent time on "was that answer from the new code?".

The property under test is not "there is a git hash somewhere" — it is that
the hash is FROZEN AT IMPORT. A request-time shell-out would report the
working tree, which is the state you already know and precisely not the state
you are asking the server about. So the tests below check the field exists and
is non-empty, and then check that it does not follow the working tree when the
working tree moves.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


@pytest.fixture
def client():
    import app as app_mod
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


class TestHealthFields:

    def test_health_is_200_and_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.get_json()["status"] == "ok"

    def test_git_revision_present_and_non_empty(self, client):
        """The field exists and carries something. This is the check the
        operator runs; if it is absent or blank the whole mechanism is
        decorative."""
        body = client.get("/health").get_json()
        assert "git_revision" in body, "no git_revision field on /health"
        rev = body["git_revision"]
        assert isinstance(rev, str) and rev.strip(), "git_revision is empty"

    def test_git_revision_looks_like_a_short_hash_or_unknown(self, client):
        """A checkout with no .git (tarball deploy) answers 'unknown' rather
        than omitting the field — a caller can tell 'no git here' from 'field
        not implemented'."""
        rev = client.get("/health").get_json()["git_revision"]
        assert rev == "unknown" or re.fullmatch(r"[0-9a-f]{7,40}", rev), rev

    def test_reports_its_own_pid_and_import_time(self, client):
        """Both are how you tell two servers apart when one is stale."""
        import os
        body = client.get("/health").get_json()
        assert body["pid"] == os.getpid()
        assert body["imported_at"], "imported_at is empty"
        assert "git_dirty" in body


class TestFrozenAtImport:

    def test_revision_does_not_change_between_requests(self, client):
        """Two requests, one process: the same answer. A per-request shell-out
        would still pass this — the next test is the one that separates
        them."""
        a = client.get("/health").get_json()["git_revision"]
        b = client.get("/health").get_json()["git_revision"]
        assert a == b

    def test_revision_is_not_re_read_from_the_working_tree(self, client,
                                                           monkeypatch):
        """THE test. Make a fresh `git rev-parse` return something different,
        then ask again. An import-time constant ignores it; a request-time
        shell-out reports the new value — which is the working tree, not this
        process.

        Mutation check: replace the handler's `GIT_REVISION` with a call to
        `_resolve_git_revision()[0]` and this fails, while every other test in
        the file still passes.
        """
        import subprocess
        import app as app_mod

        before = client.get("/health").get_json()["git_revision"]

        real_run = subprocess.run

        def fake_run(cmd, *a, **kw):
            if isinstance(cmd, (list, tuple)) and "rev-parse" in cmd:
                class R:
                    returncode = 0
                    stdout = "deadbee\n"
                    stderr = ""
                return R()
            return real_run(cmd, *a, **kw)

        monkeypatch.setattr(subprocess, "run", fake_run)

        # Sanity: the fake really would change a fresh resolution.
        assert app_mod._resolve_git_revision()[0] == "deadbee"

        after = client.get("/health").get_json()["git_revision"]
        assert after == before, (
            "git_revision followed the working tree — it is being resolved "
            "per request, which reports the checkout rather than the process"
        )


class TestResolverDegradesQuietly:

    def test_non_git_directory_yields_unknown_not_an_exception(self,
                                                              monkeypatch):
        """A tarball deploy has no .git. The app must still serve."""
        import subprocess
        import app as app_mod

        def boom(*a, **kw):
            raise FileNotFoundError("git not on PATH")

        monkeypatch.setattr(subprocess, "run", boom)
        rev, dirty = app_mod._resolve_git_revision()
        assert rev == "unknown"
        assert dirty is False

    def test_failed_rev_parse_yields_unknown(self, monkeypatch):
        import subprocess
        import app as app_mod

        class R:
            returncode = 128
            stdout = ""
            stderr = "fatal: not a git repository"

        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: R())
        assert app_mod._resolve_git_revision()[0] == "unknown"
