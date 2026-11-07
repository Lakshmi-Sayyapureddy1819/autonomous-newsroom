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
