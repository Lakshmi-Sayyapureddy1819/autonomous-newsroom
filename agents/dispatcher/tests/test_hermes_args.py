import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dispatch import Config


def test_hermes_extra_args_are_appended_for_hermes_roles_only():
    cfg = Config({"NEWSROOM_HERMES_EXTRA_ARGS": "-m gemini-2.5-flash --provider gemini"})
    copydesk = cfg.command("copydesk", "12", "do it")
    assert copydesk[-4:] == ["-m", "gemini-2.5-flash", "--provider", "gemini"]
    assert "-p" in copydesk and "copydesk" in copydesk
    assert "--provider" not in cfg.command("reporter", "12", "do it")


def test_no_extra_args_by_default():
    assert "--provider" not in Config({}).command("editor", "1", "x")


def test_openclaw_roles_get_a_fresh_session_per_invocation():
    cmd = Config({}).command("reporter", "12", "do it")
    assert "--session-id" in cmd
    assert cmd[cmd.index("--session-id") + 1].startswith("newsroom-reporter-12-")


def test_openclaw_extra_args_apply_to_openclaw_roles_only():
    cfg = Config({"NEWSROOM_OPENCLAW_EXTRA_ARGS": "--model google/gemini-3.7-flash"})
    assert cfg.command("reporter", "1", "x")[-2:] == ["--model", "google/gemini-3.7-flash"]
    assert "--model" not in cfg.command("copydesk", "1", "x")
