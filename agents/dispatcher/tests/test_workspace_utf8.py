import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import dispatch


def test_workspace_is_a_dedicated_dir_not_the_human_checkout(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(dispatch.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    cfg = dispatch.Config({"NEWSROOM_WORKSPACES_DIR": str(tmp_path),
                           "NEWSROOM_REPO_DIR": str(tmp_path / "human")})
    ws = cfg.ensure_workspace("reporter")
    assert ws == tmp_path / "reporter" / "repo"
    assert ws != cfg.root
    assert calls[0][:2] == ["git", "clone"]


def test_existing_workspace_is_only_fetched(tmp_path, monkeypatch):
    (tmp_path / "copydesk" / "repo" / ".git").mkdir(parents=True)
    calls = []
    monkeypatch.setattr(dispatch.subprocess, "run",
                        lambda argv, **k: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    dispatch.Config({"NEWSROOM_WORKSPACES_DIR": str(tmp_path)}).ensure_workspace("copydesk")
    assert "fetch" in calls[0] and "clone" not in calls[0]


def test_agent_output_with_non_cp1252_bytes_is_decoded(tmp_path):
    # 0x8f is undefined in cp1252: this used to crash the reader thread on Windows.
    script = "import sys; sys.stdout.buffer.write('ok \\u2192 \\u2713'.encode('utf-8') + b'\\x8f')"
    out = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=False,
                         encoding="utf-8", errors="replace")
    assert "ok" in out.stdout


def test_log_and_state_files_are_written_as_utf8(tmp_path):
    state = dispatch.State(tmp_path)
    state.save("k", {"last_error": "boom → ✓ \U0001f4a5"})
    assert state.load("k")["last_error"].startswith("boom")
    (tmp_path / "logs" / "x.log").write_text("\U0001f4a5 →", encoding="utf-8")


def test_prompt_names_the_workspace_and_forbids_other_checkouts(tmp_path, monkeypatch):
    seen = {}

    def fake_run(argv, **k):
        seen["argv"], seen["cwd"] = argv, k.get("cwd")
        return subprocess.CompletedProcess(argv, 0, "", "")

    cfg = dispatch.Config({"NEWSROOM_STATE_DIR": str(tmp_path),
                           "NEWSROOM_DISPATCH_STATE_DIR": str(tmp_path / "state"),
                           "NEWSROOM_WORKSPACES_DIR": str(tmp_path / "ws"),
                           "NEWSROOM_CMD_REPORTER": "agent-cli {prompt}"})
    monkeypatch.setattr(dispatch.subprocess, "run", fake_run)
    monkeypatch.setattr(cfg, "ensure_workspace", lambda a: tmp_path / "ws" / a / "repo")
    d = dispatch.Dispatcher(cfg, gh=None)
    ticket = dispatch.lifecycle.Ticket(12, "t", "", {"status:ready", "agent:reporter"})
    d._run_subprocess("reporter", "12", dispatch.prompt_for("reporter", 12, ticket))
    prompt = seen["argv"][-1]
    assert str(tmp_path / "ws" / "reporter" / "repo") in prompt
    assert "{workspace}" not in prompt and "belongs to the human" in prompt
    assert seen["cwd"] == tmp_path / "ws" / "reporter" / "repo"
