"""Repository-scoped Git profiles and provider authentication helpers."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROFILE_NAME = re.compile(r"^[A-Za-z0-9_-]+$")
PROVIDERS = {"github", "azure"}


@dataclass(frozen=True)
class GitProfile:
    name: str
    provider: str
    account: str
    email: str
    author_name: str


class GitError(ValueError):
    pass


class GitService:
    """Use Git's own configuration while leaving credentials to secure helpers."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def _run(self, *arguments: str, global_config: bool = False) -> str:
        command = ["git"]
        if not global_config:
            command.extend(["-C", str(self.root)])
        command.extend(arguments)
        environment = os.environ.copy()
        environment.setdefault("GIT_TERMINAL_PROMPT", "0")
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        if result.returncode:
            message = result.stderr.strip() or result.stdout.strip() or "Git command failed"
            raise GitError(message)
        return result.stdout.strip()

    def add_profile(self, profile: GitProfile) -> None:
        if not PROFILE_NAME.fullmatch(profile.name):
            raise GitError("Profile names may contain letters, numbers, underscores, and hyphens")
        if profile.provider not in PROVIDERS:
            raise GitError("Provider must be github or azure")
        prefix = f"notebookvim-profile.{profile.name}"
        for key, value in (
            ("provider", profile.provider),
            ("account", profile.account),
            ("email", profile.email),
            ("authorName", profile.author_name),
        ):
            self._run("config", "--global", f"{prefix}.{key}", value, global_config=True)

    def profiles(self) -> list[GitProfile]:
        try:
            output = self._run(
                "config", "--global", "--get-regexp", r"^notebookvim-profile\.", global_config=True
            )
        except GitError as exc:
            if "Git command failed" in str(exc):
                return []
            raise
        values: dict[str, dict[str, str]] = {}
        for line in output.splitlines():
            key, _, value = line.partition(" ")
            parts = key.split(".", 2)
            if len(parts) != 3:
                continue
            values.setdefault(parts[1], {})[parts[2].lower()] = value
        profiles = []
        for name, fields in sorted(values.items()):
            required = {"provider", "account", "email", "authorname"}
            if required <= fields.keys():
                profiles.append(
                    GitProfile(
                        name=name,
                        provider=fields["provider"],
                        account=fields["account"],
                        email=fields["email"],
                        author_name=fields["authorname"],
                    )
                )
        return profiles

    def profile(self, name: str) -> GitProfile:
        profile = next((item for item in self.profiles() if item.name == name), None)
        if profile is None:
            raise GitError(f"Unknown Git profile: {name}")
        return profile

    def use_profile(self, name: str) -> GitProfile:
        profile = self.profile(name)
        self._run("config", "--local", "notebookvim.activeProfile", profile.name)
        self._run("config", "--local", "user.name", profile.author_name)
        self._run("config", "--local", "user.email", profile.email)
        if profile.provider == "github":
            self._run("config", "--local", "credential.https://github.com.username", profile.account)
            self._run("config", "--local", "credential.https://github.com.useHttpPath", "true")
        else:
            self._run("config", "--local", "credential.dev.azure.com.provider", "azure-repos")
            self._run("config", "--local", "credential.azreposCredentialType", "oauth")
        return profile

    def active_profile_name(self) -> str | None:
        try:
            return self._run("config", "--local", "--get", "notebookvim.activeProfile") or None
        except GitError:
            return None

    def status(self) -> str:
        return self._run("status", "--short", "--branch") or "Working tree clean"

    def _prepare_authentication(self) -> None:
        active = self.active_profile_name()
        if active is None:
            return
        profile = self.profile(active)
        if profile.provider != "github" or not shutil.which("gh"):
            return
        result = subprocess.run(
            ["gh", "auth", "switch", "--hostname", "github.com", "--user", profile.account],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise GitError(
                f"GitHub account {profile.account} is not logged in; "
                f"run :git login {profile.name}"
            )

    def pull(self) -> str:
        self._prepare_authentication()
        return self._run("pull") or "Pull complete"

    def push(self) -> str:
        self._prepare_authentication()
        return self._run("push") or "Push complete"

    def login_command(self, name: str) -> str:
        profile = self.use_profile(name)
        if profile.provider == "github":
            if shutil.which("gh"):
                account = shlex.quote(profile.account)
                return (
                    f"(gh auth switch --hostname github.com --user {account} || "
                    "gh auth login --hostname github.com --git-protocol https --web) && "
                    "gh auth setup-git --hostname github.com"
                )
            if shutil.which("git-credential-manager"):
                login = shlex.join(
                    [
                        "git",
                        "credential-manager",
                        "github",
                        "login",
                        "--web",
                        "--username",
                        profile.account,
                    ]
                )
                return "git credential-manager configure && " + login
            raise GitError(
                "GitHub browser login requires GitHub CLI (`gh`) or Git Credential Manager"
            )

        if not shutil.which("git-credential-manager"):
            raise GitError("Azure DevOps browser login requires Git Credential Manager")
        remote = self._run("remote", "get-url", "origin")
        parsed = urlparse(remote)
        path_parts = [part for part in parsed.path.split("/") if part]
        organization = path_parts[0] if parsed.netloc == "dev.azure.com" and path_parts else ""
        bind = ""
        if organization:
            bind = " && " + shlex.join(
                [
                    "git",
                    "credential-manager",
                    "azure-repos",
                    "bind",
                    "--local",
                    organization,
                    profile.account,
                ]
            )
        return "git credential-manager configure && git fetch origin" + bind
