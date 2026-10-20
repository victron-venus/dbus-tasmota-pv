"""Exercise the commit helper with failed Git commands and a local bare remote."""

import os
import shutil
import subprocess  # nosec B404 - fixed commands against isolated test repositories.
from pathlib import Path

import pytest


@pytest.fixture
def helper(tmp_path):
    repository = tmp_path / "repository with spaces"
    repository.mkdir()
    script = repository / "commit.sh"
    shutil.copy2(Path(__file__).resolve().parents[1] / "commit.sh", script)
    (repository / "commit.txt").write_text("Commit helper test\n\nBody from file.\n")
    return script


def run_helper(script, environment):
    return subprocess.run(  # nosec B603, B607 - test fixture, no shell interpolation.
        ["bash", str(script)],
        cwd=script.parent.parent,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


@pytest.mark.parametrize(
    ("stage", "status", "expected", "successful"),
    [
        ("add", 17, ["add"], False),
        ("diff", 2, ["add", "diff"], False),
        ("diff", 128, ["add", "diff"], False),
        ("commit", 23, ["add", "diff", "commit"], False),
        ("push", 31, ["add", "diff", "commit", "push"], False),
        ("diff", 0, ["add", "diff"], True),
        ("none", 0, ["add", "diff", "commit", "push"], True),
    ],
)
def test_git_failures_stop_before_later_commands(
    helper, tmp_path, stage, status, expected, successful
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" >> "$TEST_GIT_CALLS"\n'
        'if [ "$1" = "$TEST_FAIL_STAGE" ]; then exit "$TEST_FAIL_STATUS"; fi\n'
        'case "$1" in diff|diff-index) exit 1;; esac\n'
        "exit 0\n"
    )
    git.chmod(0o755)
    calls = tmp_path / "calls"
    environment = dict(
        os.environ,
        PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
        TEST_GIT_CALLS=str(calls),
        TEST_FAIL_STAGE=stage,
        TEST_FAIL_STATUS=str(status),
    )
    result = run_helper(helper, environment)
    operations = calls.read_text().splitlines()
    assert [line.split()[0] for line in operations] == expected
    assert (result.returncode == 0) is successful, result.stdout + result.stderr
    if not successful:
        assert result.returncode == status
    assert ("Done!" in result.stdout) is (successful and stage == "none")
    if stage == "diff" and status == 0:
        assert "No changes to commit" in result.stdout
    if "diff" in expected:
        assert "--cached" in operations[1].split()
        assert "HEAD" not in operations[1].split()


@pytest.mark.parametrize("message", [None, ""])
def test_missing_or_empty_message_does_not_call_git(helper, tmp_path, message):
    message_file = helper.parent / "commit.txt"
    if message is None:
        message_file.unlink()
    else:
        message_file.write_text(message)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "git-called"
    git = bin_dir / "git"
    git.write_text('#!/bin/sh\ntouch "$TEST_GIT_MARKER"\nexit 0\n')
    git.chmod(0o755)
    result = run_helper(
        helper,
        dict(
            os.environ,
            PATH=str(bin_dir) + os.pathsep + os.environ["PATH"],
            TEST_GIT_MARKER=str(marker),
        ),
    )
    assert result.returncode != 0
    assert not marker.exists()
    assert "Done!" not in result.stdout


def test_initial_commit_no_changes_and_updates_reach_local_remote(helper, tmp_path):
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update(
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_ALLOW_PROTOCOL="file",
        GIT_TERMINAL_PROMPT="0",
    )

    def git(*args):
        return subprocess.run(  # nosec B603, B607 - local-only Git fixture.
            ["git", *args],
            cwd=helper.parent,
            env=environment,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        ).stdout.strip()

    remote = tmp_path / "remote.git"
    git("init", "--bare", str(remote))
    git("init", "-b", "main")
    git("config", "user.name", "Commit Helper Test")
    git("config", "user.email", "commit-helper@example.invalid")
    git("config", "commit.gpgsign", "false")
    git("config", "core.hooksPath", str(tmp_path / "no-hooks"))
    git("config", "branch.main.remote", "origin")
    git("config", "branch.main.merge", "refs/heads/main")
    git("remote", "add", "origin", str(remote))
    tracked = helper.parent / "tracked.txt"
    tracked.write_text("initial\n")

    initial = run_helper(helper, environment)
    assert initial.returncode == 0, initial.stdout + initial.stderr
    assert "Done!" in initial.stdout
    first = git("rev-parse", "HEAD")
    assert git("--git-dir", str(remote), "rev-parse", "refs/heads/main") == first
    assert git("log", "-1", "--format=%B") == "Commit helper test\n\nBody from file."

    unchanged = run_helper(helper, environment)
    assert unchanged.returncode == 0, unchanged.stdout + unchanged.stderr
    assert "No changes to commit" in unchanged.stdout
    assert "Done!" not in unchanged.stdout
    assert git("rev-parse", "HEAD") == first

    (helper.parent / "untracked.txt").write_text("new file\n")
    untracked = run_helper(helper, environment)
    assert untracked.returncode == 0, untracked.stdout + untracked.stderr
    assert "Done!" in untracked.stdout
    assert git("--git-dir", str(remote), "show", "main:untracked.txt") == "new file"

    tracked.write_text("updated\n")
    git("add", "tracked.txt")
    updated = run_helper(helper, environment)
    assert updated.returncode == 0, updated.stdout + updated.stderr
    assert "Done!" in updated.stdout
    assert git("rev-parse", "HEAD") != first
    assert git("--git-dir", str(remote), "rev-parse", "refs/heads/main") == git("rev-parse", "HEAD")
    assert git("--git-dir", str(remote), "show", "main:tracked.txt") == "updated"
    assert git("--git-dir", str(remote), "show", "main:untracked.txt") == "new file"
