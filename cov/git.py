# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

from pathlib import Path
from typing import Any

from cov.base import GIT_EXECUTABLE, cd, output


def git_pretty(fmt: str):
    return output(
        GIT_EXECUTABLE,
        "log",
        "-1",
        f"--pretty=format:{fmt}",
    )


def get_git_header(
    json: dict[str, Any], src_dir: str | Path, /, only_hash: bool = False
):
    with cd(src_dir):
        branch = output(GIT_EXECUTABLE, "rev-parse", "--abbrev-ref", "HEAD")
        commit_id, author_name, author_email, committer_name, committer_email = (
            git_pretty("%H%n%aN%n%aE%n%cN%n%cE").split("\n")
        )
        message = git_pretty("%B")
        if only_hash:
            json["git"] = {
                "branch": branch,
                "head": commit_id,
            }
            return

        json["git"] = {
            "branch": branch,
            "head": {
                "id": commit_id,
                "author_name": author_name,
                "author_email": author_email,
                "committer_name": committer_name,
                "committer_email": committer_email,
                "message": message,
            },
            "remotes": [],
        }
