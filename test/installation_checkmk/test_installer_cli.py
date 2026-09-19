"""Tests for installer.py's --interactive argument handling.

Regression test for the bug found 2026-08-03: README.md documents
"./installer.py init --interactive", but the global --interactive flag was
only declared on the top-level parser, so argparse rejected it after the
subcommand ("unrecognized arguments: --interactive"). Fixed by also
accepting --interactive on the init/bootstrap/install subparsers (using a
separate dest, since argparse subparser defaults silently overwrite an
already-set same-named attribute - a shared dest would have broken the
"--interactive bootstrap" order instead).
"""


def _effective_interactive(args):
    return bool(args.interactive) or bool(getattr(args, "sub_interactive", False))


def test_interactive_before_subcommand_still_works(installer_module):
    args = installer_module.build_parser().parse_args(["--interactive", "bootstrap"])
    assert _effective_interactive(args) is True


def test_interactive_after_bootstrap_now_works(installer_module):
    args = installer_module.build_parser().parse_args(["bootstrap", "--interactive"])
    assert _effective_interactive(args) is True


def test_interactive_after_install_alias_now_works(installer_module):
    args = installer_module.build_parser().parse_args(["install", "--interactive"])
    assert _effective_interactive(args) is True


def test_interactive_after_init_no_longer_errors(installer_module):
    # init always prompts interactively regardless of this flag (see
    # init_env() in installer.py) - what matters here is that parsing no
    # longer raises "unrecognized arguments", matching README.md's
    # documented "init --interactive" usage.
    args = installer_module.build_parser().parse_args(["init", "--interactive"])
    assert args.cmd == "init"


def test_bootstrap_without_flag_is_not_interactive(installer_module):
    args = installer_module.build_parser().parse_args(["bootstrap"])
    assert _effective_interactive(args) is False


def test_interactive_flag_does_not_leak_across_unrelated_commands(installer_module):
    args = installer_module.build_parser().parse_args(["verify"])
    assert bool(args.interactive) is False
    assert getattr(args, "sub_interactive", False) is False


# --- --env-file default location ---------------------------------------------
# Regression test for the bug found 2026-08-03: the default env file used to
# live next to installer.py inside /opt/checkmk-tools, the auto-git-sync
# target. A stray sync mechanism (installed by install-checkmk-agent-linux.py
# before it gets reconciled away) runs "git clean -fd" on that directory,
# which wiped it twice live on ubntmarzio. The default now points outside the
# repo entirely so no git operation on it can ever touch the env file.

def test_env_file_default_is_outside_the_repo(installer_module):
    args = installer_module.build_parser().parse_args(["verify"])
    assert "checkmk-tools" not in args.env_file
    assert args.env_file == "/etc/checkmk-installer.env"


def test_env_file_still_overridable(installer_module):
    args = installer_module.build_parser().parse_args(["--env-file", "/tmp/custom.env", "verify"])
    assert args.env_file == "/tmp/custom.env"
