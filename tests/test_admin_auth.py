"""
Admin route authentication (WORKLIST 4.1).

The gated routes — /admin/costs, /admin/evidence-mapping, /cache/clear — are
operator-only: two read telemetry logs, one deletes cached answers from the
database. None is called by the UI (grepped templates/index.html), so a shared
secret costs nothing in UX.

The property under test is DENY BY DEFAULT. HANDOVER.md bug class (d) is "a
check that fails open"; the specific failure this file pins is an auth guard
that, when ADMIN_TOKEN is unset, lets everything through instead of nothing.

DELETE /learn_history/<filename> is deliberately NOT gated: the UI sidebar's
delete button calls it directly (templates/index.html, fetch with
method:'DELETE'), and the route is already path-validated and scoped to the
learn_history/ archive. A test below pins that it stays reachable without a
token, so gating it later is a conscious decision that must also touch the UI.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

TOKEN = "test-admin-secret"

# (method, path) for every route behind require_admin_token
GATED_ROUTES = [
    ("get",  "/admin/costs"),
    ("get",  "/admin/evidence-mapping"),
    ("post", "/cache/clear"),
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


class TestUiRoutesStayOpen:

    def test_learn_history_delete_is_not_token_gated(self, client, monkeypatch):
        """Deliberate exception (WORKLIST 4.1): the UI sidebar delete button
        calls DELETE /learn_history/<file> with no header. It must not 403;
        404 for a nonexistent file is the expected answer."""
        monkeypatch.delenv("ADMIN_TOKEN", raising=False)
        resp = client.delete("/learn_history/no_such_file_ever.json")
        assert resp.status_code == 404
