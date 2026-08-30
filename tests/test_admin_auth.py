"""
Admin route authentication (WORKLIST 4.1).

The gated routes — /admin/costs, /admin/evidence-mapping, /cache/clear and
DELETE /learn_history/<filename> — are operator-only: two read telemetry logs,
one deletes cached answers from the database, one permanently deletes an
archived curriculum from disk.

The property under test is DENY BY DEFAULT. HANDOVER.md bug class (d) is "a
check that fails open"; the specific failure this file pins is an auth guard
that, when ADMIN_TOKEN is unset, lets everything through instead of nothing.

DELETE /learn_history/<filename> is called by the UI, so gating it required a
UI change: app.index() renders ADMIN_TOKEN into a <meta name="admin-token">
tag and the sidebar delete button sends it as X-Admin-Token. The UI half of
bug class (d) is pinned in the template itself — the row is removed only on an
explicit 200 + {"ok": true}; a 403 leaves the row and shows an error, so a
delete can never look like it worked while the file survives on disk.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

TOKEN = "test-admin-secret"

# (method, path) for every route behind require_admin_token.
# The learn_history path names a file that does not exist: with a valid token
# the handler answers 404, so these parametrized cases can never delete data.
GATED_ROUTES = [
    ("get",    "/admin/costs"),
    ("get",    "/admin/evidence-mapping"),
    ("post",   "/cache/clear"),
    ("delete", "/learn_history/no_such_file_ever.json"),
]


@pytest.fixture
def client():
    import app as app_mod
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


def _call(client, method, path, token=None):
    headers = {}
    if token is not None:
        headers["X-Admin-Token"] = token
    kwargs = {"headers": headers}
    if method == "post":
        kwargs["json"] = {}
    return getattr(client, method)(path, **kwargs)


class TestDenyByDefault:

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_unset_env_denies_even_with_a_header(self, client, monkeypatch,
                                                 method, path):
        """No ADMIN_TOKEN configured -> 403 for everyone, header or not.
        This is the fail-open case: a naive guard that compares header ==
        env would pass '' == '' or skip the check when env is missing."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        assert _call(client, method, path).status_code == 403
        assert _call(client, method, path, token="anything").status_code == 403

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_empty_env_token_denies_empty_header(self, client, monkeypatch,
                                                 method, path):
        """ADMIN_TOKEN='' must behave as unset — '' matching '' would be a
        fail-open guard wearing a costume."""
        monkeypatch.setenv("ADMIN_TOKEN", "")
        resp = _call(client, method, path, token="")
        assert resp.status_code == 403

    def test_unset_env_message_names_the_fix(self, client, monkeypatch):
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = _call(client, "get", "/admin/costs")
        assert resp.status_code == 403
        assert "ADMIN_TOKEN" in (resp.get_json() or {}).get("error", "")


class TestTokenChecking:

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_missing_header_denies(self, client, monkeypatch, method, path):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        assert _call(client, method, path).status_code == 403

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_wrong_token_denies(self, client, monkeypatch, method, path):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        assert _call(client, method, path, token="wrong-token").status_code == 403

    def test_right_token_reaches_admin_costs(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        resp = _call(client, "get", "/admin/costs", token=TOKEN)
        assert resp.status_code == 200
        assert "total_cost_usd" in resp.get_json()

    def test_right_token_reaches_evidence_mapping(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        resp = _call(client, "get", "/admin/evidence-mapping", token=TOKEN)
        assert resp.status_code == 200
        assert "total_attempts" in resp.get_json()

    def test_right_token_reaches_cache_clear_handler(self, client, monkeypatch):
        """With a valid token an empty body must reach the handler's own
        validation (400 'Question required') — NOT the guard's 403. This
        proves the guard passes without letting the test delete real cache
        rows."""
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        resp = _call(client, "post", "/cache/clear", token=TOKEN)
        assert resp.status_code == 400
        assert "Question" in (resp.get_json() or {}).get("error", "")


class TestLearnHistoryDeleteIsGated:
    """DELETE /learn_history/<file> is now token-gated. THE GATING DECISION
    CHANGED: an earlier pass left this route open because the UI sidebar
    delete button called it with no header and that pass could not edit
    templates/index.html. It is closed now because it is the most destructive
    route in the app — each archived curriculum costs roughly $1 of Claude
    calls to regenerate, and the archive is the only copy — and because the UI
    can now send the header: app.index() renders ADMIN_TOKEN into a
    <meta name="admin-token"> tag which deleteLearnReport() forwards as
    X-Admin-Token. The test that used to assert this route stays reachable
    without a token has been inverted into the cases below.
    """

    def test_no_header_denies(self, client, monkeypatch):
        """The exact call the old UI made — DELETE, no header — must 403."""
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        resp = client.delete("/learn_history/no_such_file_ever.json")
        assert resp.status_code == 403

    def test_wrong_token_denies(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        resp = _call(client, "delete", "/learn_history/no_such_file_ever.json",
                     token="wrong-token")
        assert resp.status_code == 403

    def test_unset_env_denies(self, client, monkeypatch):
        """Deny by default survives the gating change: with ADMIN_TOKEN unset
        the route refuses everyone, header or not — it never falls back to
        'no token configured, so no auth' (bug class (d))."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        assert client.delete(
            "/learn_history/no_such_file_ever.json").status_code == 403
        assert _call(client, "delete", "/learn_history/no_such_file_ever.json",
                     token="anything").status_code == 403

    def test_right_token_reaches_handler(self, client, monkeypatch):
        """With a valid token the request reaches the handler's own logic:
        404 for a file that does not exist, NOT the guard's 403. Proves the
        guard passes without deleting anything."""
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        resp = _call(client, "delete", "/learn_history/no_such_file_ever.json",
                     token=TOKEN)
        assert resp.status_code == 404

    def test_right_token_actually_deletes(self, client, monkeypatch, tmp_path):
        """Success path, against a throwaway archive directory so the real
        learn_history/ entries (≈$1 each to regenerate) are never touched:
        200 + {"ok": true} and the file is gone from disk."""
        import app as app_mod
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        monkeypatch.setattr(app_mod, "_LEARN_HISTORY_DIR", str(tmp_path))
        victim = tmp_path / "20260101_000000_throwaway_fixture.json"
        victim.write_text(json.dumps({
            "question": "throwaway", "timestamp": "2026-01-01T00:00:00",
            "answer": "", "papers": [], "total_papers": 0, "cost_usd": 0.0,
        }), encoding="utf-8")

        resp = _call(client, "delete", "/learn_history/" + victim.name,
                     token=TOKEN)
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}
        assert not victim.exists()

    def test_denied_delete_leaves_the_file_on_disk(self, client, monkeypatch,
                                                   tmp_path):
        """The phantom-success guard, server side: a refused delete must not
        remove the file. If this ever fails, the UI's 'row stays put on 403'
        logic is hiding a real deletion."""
        import app as app_mod
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        monkeypatch.setattr(app_mod, "_LEARN_HISTORY_DIR", str(tmp_path))
        survivor = tmp_path / "20260101_000000_throwaway_fixture.json"
        survivor.write_text("{}", encoding="utf-8")

        assert client.delete("/learn_history/" + survivor.name).status_code == 403
        assert _call(client, "delete", "/learn_history/" + survivor.name,
                     token="wrong-token").status_code == 403
        assert survivor.exists()


class TestTheTokenStaysOutOfPageSource:
    """WORKLIST C4 inverted the old contract. The token used to be rendered
    into a <meta name="admin-token"> tag, which meant anyone who could load /
    could read it. The page must now be secret-free: the UI authenticates via
    POST /admin/login and a signed session cookie instead."""

    def test_index_never_contains_the_token(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        html = client.get("/").get_data(as_text=True)
        assert TOKEN not in html, \
            "ADMIN_TOKEN is readable in the page source again"

    def test_index_carries_no_admin_token_meta_tag_at_all(self, client,
                                                          monkeypatch):
        """Not even an empty one — its presence invites the pattern back."""
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        html = client.get("/").get_data(as_text=True)
        assert 'name="admin-token"' not in html

    def test_index_javascript_calls_the_login_route(self, client, monkeypatch):
        """The delete button's auth path now runs through /admin/login."""
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        html = client.get("/").get_data(as_text=True)
        assert "/admin/login" in html


SECRET = "test-flask-secret-key"


@pytest.fixture
def session_app(monkeypatch):
    """App with both ADMIN_TOKEN and a session signing key configured."""
    import app as app_mod
    monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
    monkeypatch.setattr(app_mod.app, "secret_key", SECRET)
    app_mod.app.config["TESTING"] = True
    return app_mod.app.test_client()


class TestAdminSession:
    """The signed-session path: the X-Admin-Token guarantee, held by a cookie
    the operator earned once through /admin/login."""

    def test_login_with_the_right_token_sets_a_session(self, session_app):
        resp = session_app.post("/admin/login",
                                headers={"X-Admin-Token": TOKEN})
        assert resp.status_code == 200
        assert resp.get_json() == {"ok": True}

    def test_login_with_a_wrong_token_denies(self, session_app):
        resp = session_app.post("/admin/login",
                                headers={"X-Admin-Token": "wrong"})
        assert resp.status_code == 403

    def test_a_failed_login_leaves_no_usable_session_behind(self, session_app):
        """The 403 alone is not enough: a login that writes the session
        BEFORE checking the token would answer 403 and still hand the caller
        an authenticated cookie. The gated routes must stay closed after a
        rejected login."""
        session_app.post("/admin/login", headers={"X-Admin-Token": "wrong"})
        assert session_app.get("/admin/costs").status_code == 403
        with session_app.session_transaction() as s:
            assert not s.get("admin_fp"), \
                "a rejected login still wrote an admin fingerprint"

    def test_login_without_a_header_denies(self, session_app):
        assert session_app.post("/admin/login").status_code == 403

    def test_login_denies_when_admin_token_unset(self, monkeypatch):
        """Deny by default survives on the login route too."""
        import app as app_mod
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        monkeypatch.setattr(app_mod.app, "secret_key", SECRET)
        client = app_mod.app.test_client()
        resp = client.post("/admin/login", headers={"X-Admin-Token": "anything"})
        assert resp.status_code == 403
        assert "ADMIN_TOKEN" in (resp.get_json() or {}).get("error", "")

    def test_login_fails_closed_without_a_secret_key(self, monkeypatch):
        """FLASK_SECRET_KEY unset => no signing key => never issue a cookie,
        even to the RIGHT token. An unsigned/forgeable session would be worse
        than none; the header path still works. This is the fail-closed
        requirement — a constant fallback key would pass the other tests and
        be silently forgeable."""
        import app as app_mod
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        monkeypatch.setattr(app_mod.app, "secret_key", "")
        client = app_mod.app.test_client()
        resp = client.post("/admin/login", headers={"X-Admin-Token": TOKEN})
        assert resp.status_code == 403
        assert "FLASK_SECRET_KEY" in (resp.get_json() or {}).get("error", "")

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_a_session_passes_every_gated_route_without_the_header(
            self, session_app, method, path):
        """The X-Admin-Token-equivalent guarantee: after one login the cookie
        alone authenticates. The learn_history path names a file that does
        not exist, so with auth passing the handler answers 404/400/200 —
        anything but the guard's 403."""
        session_app.post("/admin/login", headers={"X-Admin-Token": TOKEN})
        resp = getattr(session_app, method)(
            path, **({"json": {}} if method == "post" else {}))
        assert resp.status_code != 403, \
            f"{method.upper()} {path} still 403s with a valid admin session"

    @pytest.mark.parametrize("method,path", GATED_ROUTES)
    def test_no_session_and_no_header_still_denies(self, session_app,
                                                   method, path):
        resp = getattr(session_app, method)(
            path, **({"json": {}} if method == "post" else {}))
        assert resp.status_code == 403

    def test_rotating_the_token_invalidates_existing_sessions(
            self, session_app, monkeypatch):
        """The session stores a fingerprint of the token it was issued for;
        a session earned under the old token must die with it."""
        session_app.post("/admin/login", headers={"X-Admin-Token": TOKEN})
        assert session_app.get("/admin/costs").status_code == 200
        monkeypatch.setenv("ADMIN_TOKEN", "rotated-" + TOKEN)
        assert session_app.get("/admin/costs").status_code == 403

    def test_unsetting_the_token_kills_sessions_too(self, session_app,
                                                    monkeypatch):
        """Deny-by-default outranks any cookie: ADMIN_TOKEN unset => 403,
        never 'this session was valid once'."""
        session_app.post("/admin/login", headers={"X-Admin-Token": TOKEN})
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        assert session_app.get("/admin/costs").status_code == 403

    def test_the_session_cookie_is_httponly_and_not_the_token(self, session_app):
        resp = session_app.post("/admin/login",
                                headers={"X-Admin-Token": TOKEN})
        set_cookie = resp.headers.get("Set-Cookie", "")
        assert set_cookie, "login did not set a cookie"
        assert "HttpOnly" in set_cookie

    def test_the_session_stores_a_keyed_fingerprint_not_the_token(self,
                                                                  session_app):
        """Flask session cookies are signed but READABLE (base64 JSON), so a
        raw Set-Cookie substring check proves nothing. Decode the actual
        session: it must not hold the token, and not a bare unkeyed hash of
        it either — sha256(token) in a readable cookie is an offline
        brute-force target. What it must hold is HMAC(secret_key, token)."""
        import hashlib, hmac as _hmac
        session_app.post("/admin/login", headers={"X-Admin-Token": TOKEN})
        with session_app.session_transaction() as s:
            values = "".join(str(v) for v in s.values())
            assert TOKEN not in values, "the raw token is in the session"
            bare = hashlib.sha256(TOKEN.encode()).hexdigest()
            assert bare not in values, "an unkeyed hash of the token is in the session"
            expected = _hmac.new(SECRET.encode(), TOKEN.encode(),
                                 hashlib.sha256).hexdigest()
            assert s.get("admin_fp") == expected

    def test_a_forged_unsigned_cookie_does_not_pass(self, session_app):
        """A hand-built cookie that was never signed by the server must be
        rejected by Flask's signature check and fall to 403."""
        session_app.set_cookie("session", "eyJhZG1pbl9mcCI6ICJmb3JnZWQifQ.forged")
        assert session_app.get("/admin/costs").status_code == 403

    def test_import_time_has_no_fallback_secret_key(self):
        """The fail-closed requirement at its root: with FLASK_SECRET_KEY
        absent from the environment, importing the app must leave
        secret_key EMPTY — never a baked-in constant, which anyone with the
        source could use to forge admin cookies. Checked in a subprocess
        because this process imported app long ago. (The other session tests
        monkeypatch secret_key directly, so only this one can see an
        import-time fallback.)"""
        import subprocess, sys as _sys
        code = (
            "import os, sys\n"
            "os.environ.pop('FLASK_SECRET_KEY', None)\n"
            "sys.path.insert(0, r'%s')\n"
            "import app as app_mod\n"
            "sys.exit(1 if app_mod.app.secret_key else 0)\n"
        ) % str(Path(__file__).parent.parent)
        r = subprocess.run([_sys.executable, "-c", code],
                           capture_output=True, text=True, timeout=300)
        assert r.returncode == 0, (
            "app.secret_key is truthy with FLASK_SECRET_KEY unset — a "
            "fallback signing key exists.\n" + r.stderr[-800:])
