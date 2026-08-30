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


class TestTemplateCarriesTheToken:
    """The UI can only send the header if the server puts the token in the
    page. These pin the injection contract that deleteLearnReport() reads."""

    def test_index_renders_the_token_into_a_meta_tag(self, client, monkeypatch):
        monkeypatch.setenv("ADMIN_TOKEN", TOKEN)
        html = client.get("/").get_data(as_text=True)
        assert '<meta name="admin-token" content="%s"' % TOKEN in html

    def test_index_renders_empty_meta_when_token_unset(self, client, monkeypatch):
        """Unset ADMIN_TOKEN must render an empty value, not the literal
        'None' — a 'None' token would be sent as a header and read as a
        deliberate (wrong) credential rather than 'not configured'."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        html = client.get("/").get_data(as_text=True)
        assert '<meta name="admin-token" content=""' in html
        assert 'content="None"' not in html
