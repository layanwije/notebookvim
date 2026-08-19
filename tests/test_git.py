from pathlib import Path

import pytest

from notebookcli.git import GitError, GitProfile, GitService


def init_repository(path: Path) -> GitService:
    path.mkdir()
    service = GitService(path)
    service._run("init")
    return service


def test_profile_can_be_saved_and_selected(tmp_path, monkeypatch):
    repository = init_repository(tmp_path / "repo")
    global_config = tmp_path / "global.gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    profile = GitProfile("work", "github", "octocat", "octocat@example.com", "Octo Cat")

    repository.add_profile(profile)
    selected = repository.use_profile("work")

    assert selected == profile
    assert repository.active_profile_name() == "work"
    assert repository._run("config", "--local", "user.name") == "Octo Cat"
    assert repository._run("config", "--local", "user.email") == "octocat@example.com"
    assert repository._run(
        "config", "--local", "credential.https://github.com.username"
    ) == "octocat"


def test_profile_rejects_unknown_provider(tmp_path):
    repository = init_repository(tmp_path / "repo")

    with pytest.raises(GitError, match="Provider"):
        repository.add_profile(GitProfile("work", "gitlab", "me", "me@example.com", "Me"))


def test_status_reports_repository_branch(tmp_path):
    repository = init_repository(tmp_path / "repo")

    assert "No commits yet" in repository.status()


def test_github_login_uses_named_account(tmp_path, monkeypatch):
    repository = init_repository(tmp_path / "repo")
    global_config = tmp_path / "global.gitconfig"
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setattr("notebookcli.git.shutil.which", lambda command: "/usr/bin/gh" if command == "gh" else None)
    repository.add_profile(
        GitProfile("personal", "github", "octocat", "octo@example.com", "Octo Cat")
    )

    command = repository.login_command("personal")

    assert "gh auth switch" in command
    assert "--user octocat" in command
    assert "gh auth setup-git" in command
