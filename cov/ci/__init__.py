# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import datetime
import re

from cov.base import ENV


def travis_header():
    if not ENV("TRAVIS"):
        return

    pull_request = ENV("TRAVIS_PULL_REQUEST")

    return {
        "__name__": f"Travis CI job {ENV("TRAVIS_JOB_NUMBER")}",
        "service_name": "travis-ci",
        "service_number": ENV("TRAVIS_BUILD_NUMBER"),
        "service_branch": ENV("TRAVIS_BRANCH"),
        "service_job_id": ENV("TRAVIS_JOB_NUMBER"),
        "service_build_url": ENV("TRAVIS_BUILD_WEB_URL"),
        "service_pull_request": None if pull_request == "false" else pull_request,
    }


def appveyor_header():
    if not ENV("APPVEYOR"):
        return

    build_url = (
        "https://ci.appveyor.com/project/"
        f"{ENV("APPVEYOR_REPO_NAME")}/build/"
        f"{ENV("APPVEYOR_BUILD_VERSION")}"
    )

    return {
        "__name__": f"Appveyor job {ENV("APPVEYOR_BUILD_ID")}",
        "service_name": "appveyor",
        "service_number": ENV("APPVEYOR_BUILD_VERSION"),
        "service_job_number": ENV("APPVEYOR_BUILD_NUMBER"),
        "service_job_id": ENV("APPVEYOR_BUILD_ID"),
        "service_branch": ENV("APPVEYOR_REPO_BRANCH"),
        "commit_sha": ENV("APPVEYOR_REPO_COMMIT"),
        "service_build_url": build_url,
    }


def github_header():
    if not ENV("GITHUB_ACTIONS"):
        return None

    build_url = None
    if ENV("GITHUB_SERVER_URL") and ENV("GITHUB_REPOSITORY") and ENV("GITHUB_RUN_ID"):
        build_url = (
            f"{ENV('GITHUB_SERVER_URL')}/"
            f"{ENV('GITHUB_REPOSITORY')}/actions/runs/"
            f"{ENV('GITHUB_RUN_ID')}"
        )

    match = re.match(r"^refs\/pull\/(\d+)", ENV("GITHUB_REF", ""))
    pull_request = match[1] if match else None

    return {
        "__name__": (
            f"GitHub job {ENV("GITHUB_JOB")} #{ENV("GITHUB_RUN_NUMBER")} (PR#{pull_request})"
        ),
        "service_name": "github",
        "repo_name": ENV("GITHUB_REPOSITORY"),
        "service_number": ENV("GITHUB_RUN_ID"),
        "service_job_id": ENV("GITHUB_JOB"),
        "service_branch": (ENV("GITHUB_HEAD_REF") or ENV("GITHUB_REF_NAME")),
        "service_build_url": build_url,
        "service_job_url": build_url,
        "service_pull_request": pull_request,
        "service_event_type": ENV("GITHUB_EVENT_NAME"),
        "service_attempt": ENV("GITHUB_RUN_ATTEMPT"),
        "commit_sha": ENV("GITHUB_SHA"),
    }


def local_header():
    return {
        "__name__": "Local Build",
        "service_job_id": None,
        "service_name": "coveralls-universal",
        "service_event_type": "manual",
    }


def get_service_header():
    services = [travis_header, appveyor_header, github_header, local_header]

    for service in services:
        header = service()
        if header is None:
            continue
        name = header["__name__"]
        del header["__name__"]
        print(f"Preparing Coveralls for {name}.\n")
        return header

    return {}


def get_base_header():
    return {
        "git": {},
        "source_files": [],
    }


def get_report_header(flag_name: str | None, parallel: bool = False):
    header = get_service_header()
    base = get_base_header()
    dt = datetime.datetime.now(datetime.timezone.utc)
    timestamp = dt.isoformat(timespec="seconds")
    props: dict[str, str | bool | None] = {
        "repo_token": ENV("COVERALLS_REPO_TOKEN"),
        "run_at": re.sub(r"\+00:00$", "Z", timestamp),
    }

    if parallel:
        props["parallel"] = True
    if flag_name:
        props["flag_name"] = flag_name

    return {
        **header,
        **props,
        **base,
    }
