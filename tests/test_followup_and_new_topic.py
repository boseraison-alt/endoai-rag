"""
A21 — every answer ends with a follow-up composer and a New topic button, in
all three modes.

This is NOT a contradiction of A20. A20 stops Curo interviewing the clinician;
A21 lets the clinician carry on if they want to. There are no suggested-question
chips, because those are Curo prompting by another name.

WHAT WAS ALREADY THERE, measured before writing anything. Review threading is
built and well covered by `test_review_context.py`: the thread store, the
context block, the cache's `context_hash` partition, "New topic", and the
continues-from line. A21c's two directions are asserted there, over the real
route. This file covers only what A21 adds:

  * Curriculum had neither control. Its New topic button was explicitly
    hidden, and it had no follow-up path at all.
  * A curriculum follow-up must not rebuild the curriculum — a median $1.33
    and several minutes to answer one sentence is a broken affordance. It is
    answered as a scoped literature question over the curriculum's own cited
    evidence.
  * An answer opened out of HISTORY was invisible to all of this: a follow-up
    on it was answered cold and inherited whatever thread the page was last
    on. Both wrong, in opposite directions, which is why `/thread/seed`
    clears and seeds in one step.
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

ROOT = Path(__file__).parent.parent
SRC  = (ROOT / "templates" / "index.html").read_text(encoding="utf-8")

CURRICULUM = """## Module 1 — Anatomy

The inferior alveolar nerve block is the primary technique [[PMID:11111111]].
Articaine infiltration is a supplement [[PMID:22222222]].

## Module 2 — Technique

Intraosseous injection remains effective [[PMID:33333333]].
"""

REVIEW_ANSWER = """## CLINICAL RECOMMENDATION

Single-visit treatment is equivalent [[PMID:44444444]].
"""


@pytest.fixture
def app_mod(monkeypatch, tmp_path):
    import app as app_mod
    app_mod.app.config["TESTING"] = True
    app_mod.review_threads.clear()
    monkeypatch.setattr(app_mod, "_LEARN_HISTORY_DIR", str(tmp_path))
    return app_mod


@pytest.fixture
def archived(app_mod, tmp_path):
    """One archived curriculum on disk, exactly as the app writes them."""
    rec = {"question": "anesthesia for endodontics",
           "answer": CURRICULUM,
           "timestamp": "20260901_203619",
           "total_papers": 100,
           "papers": [{"pmid": "11111111"}, {"pmid": "99999999"}]}
    p = tmp_path / "20260901_203619_anesthesia_for_endodontics.json"
    p.write_text(json.dumps(rec), encoding="utf-8")
    return p.name


# ── A21b — the seed, and what it carries ──────────────────

class TestSeedingAThreadFromAStoredAnswer:

    def test_a_curriculum_seeds_the_thread_with_the_papers_it_cited(
            self, app_mod, archived):
        c = app_mod.app.test_client()
        r = c.post("/thread/seed", json={"thread_id": "t-a", "learn_file": archived})
        assert r.status_code == 200
        # the three it CITED, not the retrieval pool: 99999999 was retrieved
        # and never used, and carrying it would put a paper the curriculum
        # rejected into the follow-up's evidence.
        assert r.get_json()["carried_papers"] == 3
        carried = app_mod._thread_exchanges("t-a")
        assert [e["question"] for e in carried] == ["anesthesia for endodontics"]
        assert set(carried[0]["pmids"]) == {"11111111", "22222222", "33333333"}

    def test_seeding_replaces_rather_than_appends(self, app_mod, archived):
        """Two topics in one thread would answer the follow-up out of both."""
        c = app_mod.app.test_client()
        c.post("/thread/seed", json={"thread_id": "t-b", "learn_file": archived})
        c.post("/thread/seed", json={"thread_id": "t-b", "learn_file": archived})
        assert len(app_mod._thread_exchanges("t-b")) == 1

    def test_the_client_cannot_dictate_what_the_context_says(self, app_mod, archived):
        """It sends a reference; the server reads the stored answer. A page
        that could post its own `recommendation` could put words into the next
        answer's prompt."""
        c = app_mod.app.test_client()
        c.post("/thread/seed", json={"thread_id": "t-c", "learn_file": archived,
                                     "question": "something else entirely",
                                     "pmids": ["55555555"],
                                     "recommendation": "extract every tooth"})
        e = app_mod._thread_exchanges("t-c")[0]
        assert e["question"] == "anesthesia for endodontics"
        assert "55555555" not in e["pmids"]
        assert "extract" not in (e["recommendation"] or "")

    @pytest.mark.parametrize("bad", ["../secrets.json", "a/b.json", "notes.txt"])
    def test_a_filename_cannot_escape_the_archive(self, app_mod, bad):
        c = app_mod.app.test_client()
        r = c.post("/thread/seed", json={"thread_id": "t-d", "learn_file": bad})
        assert r.status_code == 400

    def test_a_missing_archive_is_a_404_not_an_empty_thread(self, app_mod):
        c = app_mod.app.test_client()
        r = c.post("/thread/seed",
                   json={"thread_id": "t-e", "learn_file": "no_such_file.json"})
        assert r.status_code == 404

    def test_a_reference_to_nothing_is_refused(self, app_mod):
        c = app_mod.app.test_client()
        assert c.post("/thread/seed", json={"thread_id": "t-f"}).status_code == 400
        assert c.post("/thread/seed", json={"learn_file": "x.json"}).status_code == 400


class TestAFreshCurriculumJoinsTheThreadToo:
    """The archive path is covered above. This is the other one: a curriculum
    just built, in the tab it was built in. A mutant that recorded only
    `review` at this call site survived every test in this file until it was
    written — the seed route made the archived case look covered."""

    def test_building_a_curriculum_records_it_for_the_next_question(
            self, app_mod, monkeypatch, tmp_path):
        import endo_ai

        evidence = {"_summary": {"all_scored": []}}
        monkeypatch.setattr(app_mod, "build_deep_learning_module",
                            lambda q, progress_cb=None: (CURRICULUM, 0.0, evidence),
                            raising=False)
        monkeypatch.setattr(app_mod, "get_cached_answer", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(app_mod, "save_query_cache", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(app_mod, "save_answer", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(app_mod, "write_citation_audit", lambda *a, **k: None,
                            raising=False)
        monkeypatch.setattr(endo_ai, "_invoke_claude",
                            lambda *a, **k: (_ for _ in ()).throw(
                                RuntimeError("no model calls in this test")),
                            raising=False)

        c = app_mod.app.test_client()
        r = c.post("/ask", json={"question": "anesthesia for endodontics",
                                 "mode": "learn", "thread_id": "t-fresh",
                                 "skip_clarify": True})
        job_id = r.get_json()["job_id"]
        for _ in range(400):
            if c.get("/status/%s" % job_id).get_json().get("status") in (
                    "complete", "error", "aborted"):
                break
            time.sleep(0.05)

        carried = app_mod._thread_exchanges("t-fresh")
        assert carried, "a freshly built curriculum left no trace in the thread"
        assert carried[0]["question"] == "anesthesia for endodontics"
        assert set(carried[0]["pmids"]) == {"11111111", "22222222", "33333333"}


class TestWhatACurriculumCarries:

    def test_a_curriculum_carries_more_papers_than_a_review_answer(self, app_mod):
        """12 is the right carry for a review exchange and far too thin for a
        curriculum, whose whole point is the breadth of its bibliography."""
        assert app_mod.THREAD_PMIDS_LEARN > app_mod.THREAD_PMIDS_REVIEW

    @pytest.mark.parametrize("mode,expected", [("review", 12), ("learn", 60)])
    def test_the_cap_is_applied_per_kind(self, app_mod, mode, expected):
        answer = " ".join("[[PMID:%08d]]" % i for i in range(1, 91))
        app_mod._thread_record("t-cap-" + mode, "q", answer, [], mode=mode)
        assert len(app_mod._thread_exchanges("t-cap-" + mode)[0]["pmids"]) == expected

    def test_a_cap_that_fires_says_what_it_dropped(self, app_mod, capsys):
        """Standing rule 5. Ninety cited papers silently becoming sixty is the
        same class as the module cap and the stitcher budget."""
        answer = " ".join("[[PMID:%08d]]" % i for i in range(1, 91))
        app_mod._thread_record("t-loud", "q", answer, [], mode="learn")
        out = capsys.readouterr().out
        assert "60 of 90" in out, out

    def test_nothing_is_logged_when_nothing_is_dropped(self, app_mod, capsys):
        """The counterpart, so the log line cannot become noise that is always
        there and therefore never read."""
        app_mod._thread_record("t-quiet", "q", "[[PMID:11111111]]", [], mode="learn")
        assert "carrying" not in capsys.readouterr().out


# ── A21a/A21b in the page ─────────────────────────────────

class TestTheTwoControlsOnEveryAnswer:

    def test_both_controls_are_in_the_answer_card(self):
        card = SRC[SRC.index('<div class="answer-card" id="answerCard">'):]
        card = card[:card.index("<!-- Welcome")]
        assert 'id="followupInput"' in card
        assert 'id="newTopicBtn2"' in card
        assert 'onclick="submitFollowUp()"' in card
        assert 'onclick="newTopic()"' in card

    def test_no_mode_is_denied_them(self):
        """Curriculum used to get neither: `newTopicBtn` was hidden on
        `learn`, and there was no follow-up path at all."""
        assert "(mode === 'learn') ? 'none' : 'block'" not in SRC
        body = SRC[SRC.index("function showResult("):]
        body = body[:body.index("\nfunction ")]
        assert "fr.style.display = 'flex'" in body

    def test_there_are_no_suggested_question_chips(self):
        """A21: those are Curo prompting by another name, which is the thing
        A20 just removed. Matched on identifiers rather than on prose, so the
        comment saying they are forbidden does not itself trip it."""
        # A15e's mode-suggestion strip is a different thing and stays: it
        # offers a MODE, once, and never a question to ask.
        A15E = {"mode-suggest", "modeSuggest", "modeSuggestText", "modeSuggestGo",
                "suggest-text", "suggest-go", "suggest-stay"}
        idents = set(re.findall(r'(?:id|class)="([^"]+)"', SRC))
        idents = {w for group in idents for w in group.split()}
        offenders = [w for w in idents
                     if "suggest" in w.lower() and w not in A15E]
        assert not offenders, offenders

    def test_a_curriculum_follow_up_is_answered_as_a_literature_question(self):
        """A21b — the whole point. Rebuilding the curriculum would cost a
        median $1.33 and several minutes to answer one sentence."""
        body = SRC[SRC.index("function showResult("):]
        body = body[:body.index("\nfunction ")]
        assert "_followUpMode = 'review';" in body
        sub = SRC[SRC.index("function submitFollowUp()"):]
        sub = sub[:sub.index("\n}")]
        assert "_postAsk(q, '', true, _followUpMode)" in sub

    def test_the_ask_carries_the_mode_it_is_answered_in(self):
        body = SRC[SRC.index("function _postAsk("):]
        body = body[:body.index("\n  })")]
        assert "function _postAsk(q, context, skipClarify, askMode)" in body
        assert "mode: (askMode || mode)" in body

    def test_new_topic_puts_the_clinician_back_on_an_empty_composer(self):
        """`startNewTopic` owns the context half and is left alone — it is
        covered in test_review_context.py. This is the view half."""
        body = SRC[SRC.index("function newTopic() {"):]
        body = body[:body.index("\n}")]
        assert "startNewTopic();" in body
        assert "setLandingVisible(true)" in body
        assert "ac.style.display = 'none'" in body

    def test_opening_a_stored_answer_starts_a_fresh_thread_from_it(self):
        """A21c in both directions, at the point it was missing: an answer
        opened from history."""
        for opener in ("function openLearnHistoryItem(", "function loadHistoryItem("):
            body = SRC[SRC.index(opener):]
            body = body[:body.index("\n}")]
            assert "_seedThreadFrom(" in body, opener
        seed = SRC[SRC.index("function _seedThreadFrom("):]
        seed = seed[:seed.index("\n}")]
        assert "reviewThreadId = 'th-'" in seed, "the thread was not rotated"
        assert "'/thread/seed'" in seed


# ── A21e — a follow-up answer is an answer ────────────────

class TestAFollowUpIsAnAnswer:

    def test_the_route_has_no_separate_follow_up_branch(self):
        """The verification banner, the quarantine block, the citation checks
        and the bibliography rules apply because a follow-up goes down the
        same function, not because a second path remembers to call them."""
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        body = app_src[app_src.index("def run_question("):]
        body = body[:body.index("\ndef ")]
        for shape in ("if context_block:", "if thread_id:", "if is_follow"):
            assert ("%s\n" % shape) not in body.replace("    ", ""), (
                "run_question branches on being a follow-up: %r" % shape)
        assert "finalise_answer_text" in body

    def test_a_curriculum_follow_up_takes_the_review_path(self, app_mod, archived,
                                                          monkeypatch):
        """mode='review' is what makes it a literature answer. If the page
        ever sent 'learn' the server would build a whole curriculum.

        `monkeypatch`, not a bare assignment: an unrestored stub on
        `run_question` leaks into every later test that drives /ask, and
        `test_end_to_end.py` then passes on nothing having run at all."""
        c = app_mod.app.test_client()
        c.post("/thread/seed", json={"thread_id": "t-fu", "learn_file": archived})
        seen = {}
        monkeypatch.setattr(
            app_mod, "run_question",
            lambda job_id, q, mode="review", **k: seen.update(
                mode=mode, prior=k.get("prior_pmids"), ctx=k.get("context_block")))
        c.post("/ask", json={"question": "What about articaine?",
                             "mode": "review", "thread_id": "t-fu",
                             "skip_clarify": True})
        for _ in range(50):
            if seen:
                break
            time.sleep(0.02)
        assert seen.get("mode") == "review"
        assert set(seen.get("prior") or []) == {"11111111", "22222222", "33333333"}, (
            "the follow-up was not scoped to the curriculum's own evidence")
        assert "anesthesia for endodontics" in (seen.get("ctx") or "")
