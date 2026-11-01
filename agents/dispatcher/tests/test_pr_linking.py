import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch


def test_pr_title_closes_keyword_links_issue(monkeypatch):
    gh = dispatch.GitHub("o/r")
    raw = '[{"number": 13, "title": "Closes #12", "body": "no keyword here", "labels": [],' \
          ' "closingIssuesReferences": []}]'
    monkeypatch.setattr(gh, "_gh", lambda *a, **k: raw)
    assert gh.open_prs()[0]["closingIssuesReferences"] == [{"number": 12}]


def test_github_links_are_kept_when_present(monkeypatch):
    gh = dispatch.GitHub("o/r")
    raw = '[{"number": 1, "title": "x", "body": "", "labels": [],' \
          ' "closingIssuesReferences": [{"number": 9}]}]'
    monkeypatch.setattr(gh, "_gh", lambda *a, **k: raw)
    assert gh.open_prs()[0]["closingIssuesReferences"] == [{"number": 9}]
