import argparse
import hashlib
import json
import os
import shutil
import sys
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, cast

from cov import base
from cov.base import ENV, cd, git_log_format, output, recurse
from cov.quess import guess_tool


def file_md5_excl(path: str | Path, excluded):
    m = hashlib.md5()
    lines = 0
    with open(path, "rb") as f:
        for line in f:
            m.update(line)
            lines += 1
    return (m.hexdigest(), lines)


def get_report_header():
    services = [
        ("TRAVIS_JOB_ID", "travis-ci", "Travis-CI"),
        ("APPVEYOR_JOB_ID", "appveyor", "AppVeyor"),
        ("GITHUB_JOB", "github", "GitHub Workflows"),
    ]

    job_id = ""
    service = ""
    for varname, service_id, service_name in services:
        job_id = ENV(varname)
        if not job_id:
            continue

        service = service_id
        sys.stdout.write(
            "Preparing Coveralls for {} job {}.\n".format(service_name, job_id)
        )
        break

    return {
        "service_name": service,
        "service_job_id": job_id,
        "repo_token": ENV("COVERALLS_REPO_TOKEN"),
        "git": {},
        "source_files": [],
    }


def get_git_header(json: dict[str, Any], src_dir: str | Path):
    with cd(src_dir):
        json["git"] = {
            "branch": output(base.GIT_EXECUTABLE, "rev-parse", "--abbrev-ref", "HEAD"),
            "head": {
                "id": git_log_format("H"),
                "author_name": git_log_format("an"),
                "author_email": git_log_format("ae"),
                "committer_name": git_log_format("cn"),
                "committer_email": git_log_format("ce"),
                "message": git_log_format("B"),
            },
            "remotes": [],
        }


def parse_args():
    parser = argparse.ArgumentParser(description="Gather GCOV data for Coveralls")
    handler = parser.add_mutually_exclusive_group(required=True)
    handler.add_argument(
        "--cobertura",
        help="look for .xml cobertura files instead of .gcno gcov files",
        action="store_true",
    )
    handler.add_argument(
        "--gcov", metavar="PATH", help="path to the gcov/llvm-cov program"
    )
    parser.add_argument(
        "--merge", metavar="PATH", help="path to the llvm-profdata program"
    )
    parser.add_argument(
        "--target",
        metavar="FILENAME",
        required=True,
        help="name of the tested application",
    )
    parser.add_argument(
        "--git", metavar="PATH", required=False, help="path to the git binary"
    )
    parser.add_argument(
        "--src_dir", metavar="DIR", required=True, help="directory for source files"
    )
    parser.add_argument(
        "--bin_dir", metavar="DIR", required=True, help="directory for generated files"
    )
    parser.add_argument(
        "--int_dir",
        metavar="DIR",
        required=True,
        help="directory for temporary gcov files",
    )
    parser.add_argument(
        "--dirs",
        metavar="DIR:DIR:...",
        required=True,
        help="directory filters for relevant sources, separated with':'",
    )
    parser.add_argument(
        "--out", metavar="JSON", required=True, help="output JSON file for Coveralls"
    )
    parser.add_argument(
        "--debug",
        required=False,
        help="prints JSON, if present",
        action="store_true",
        default=False,
    )

    return parser.parse_args()


def tool():
    base.GIT_EXECUTABLE = shutil.which("git") or "git"

    args = parse_args()
    dirs = [Path(dirname) for dirname in args.dirs.split(":")]

    JSON = get_report_header()
    get_git_header(JSON, args.src_dir)
    if args.debug:
        from pprint import pprint

        pprint(JSON)

    cov_tool = guess_tool(
        args.gcov,
        args.cobertura,
        args.merge,
        args.target,
        Path(args.bin_dir),
        Path(args.int_dir),
    )

    try:
        EXCL_LIST = {"win32": ["WIN32"], "linux": ["POSIX"]}[sys.platform]
    except KeyError:
        EXCL_LIST = []

    EXCL_LIST.extend(cov_tool.exclude())

    cov_tool.preprocess()

    src_dir = Path(args.src_dir).absolute()
    coverage: dict[str, list[dict]] = {}
    maps: dict[str, Path] = {}
    for intermediate_file in recurse(Path(args.int_dir), cov_tool.ext()):
        data = cov_tool.stats(intermediate_file)
        if not data:
            continue
        for src, info in data.items():
            if not src.is_relative_to(src_dir):
                continue
            name = src.relative_to(src_dir)
            relevant = False
            for dirname in dirs:
                if name.is_relative_to(dirname):
                    relevant = True
                    break
            if not relevant:
                continue

            info.append_as(name.as_posix(), src, coverage=coverage, paths=maps)

    relevant = 0
    covered = 0
    excluded = 0
    excluded_visited = 0
    excluded_unvisited = 0
    patches = []

    for src in sorted(coverage.keys()):
        lines, functions = coverage[src]
        digest, line_count = file_md5_excl(maps[src], EXCL_LIST)

        cleaned = {}
        fn_set = {line + 1 for line, _ in []}
        for key, fn in functions.items():
            start_line = fn.get("start_line", 0)
            end_line = fn.get("end_line", start_line)
            excluded = True
            for line in range(start_line, end_line + 1):
                if line in lines and line not in fn_set:
                    excluded = False
                    break
            if not excluded:
                cleaned[key] = fn
        functions = cleaned

        size = max(line_count, max(lines.keys())) if len(lines) else 0
        cvg = [None] * size
        relevant += len(lines)
        for line in lines:
            val = lines[line]
            if val:
                covered += 1
            cvg[line - 1] = val
        excluded += 0
        patch_lines = []
        for line, text in []:
            val = cvg[line]
            if val is not None:
                relevant -= 1
                if not val:
                    excluded_unvisited += 1
                else:
                    excluded_visited += 1
                    covered -= 1
            cvg[line] = None
            patch_lines.append((line, str(val) if val is not None else "", text))
        if len(patch_lines):
            patches.append((src, patch_lines))

        JSON["source_files"].append(
            {
                "name": src,
                "source_digest": digest,
                "coverage": cvg,
                "functions": [functions[key] for key in sorted(functions.keys())],
            }
        )

    with open(args.out, "w") as j:
        json.dump(JSON, j, sort_keys=True)

    if excluded:
        counter_width = 0
        for file, lines in patches:
            for linno, count, line in lines:
                length = len(count)
                if length > counter_width:
                    counter_width = length

        color = "\033[2;49;30m"
        reset = "\033[m"

        # for file, lines in patches:
        #     prev = -10
        #     for num, counter, line in lines:
        #         if num - prev > 1:
        #             if os.name == "nt":
        #                 print(
        #                     "{}({})".format(
        #                         os.path.abspath(os.path.join(args.src_dir, file)), num + 1
        #                     )
        #                 )
        #             else:
        #                 print("--   {}:{}".format(file, num + 1))
        #         prev = num
        #         print(
        #             "     {:>{}} | {}{}{}".format(
        #                 counter, counter_width, color, line, reset
        #             )
        #         )

    percentage = int(covered * 10000 / relevant + 0.5) / 100 if relevant else 0
    print("-- Coverage reported: {}/{} ({}%)".format(covered, relevant, percentage))

    if excluded:

        def counted(counter: int, when_one: str, otherwise: str):
            if counter == 0:
                return when_one.format(counter)
            return otherwise.format(counter)

        excl_str = counted(
            excluded_unvisited + excluded_visited, "one line", "{} lines"
        )
        unv_str = counted(excluded_unvisited, "one line", "{} lines")
        print("-- Excluded relevant: {}".format(excl_str))
        print("-- Excluded missing:  {}".format(unv_str))
        relevant += excluded_unvisited + excluded_visited
        covered += excluded_visited
        percentage = int(covered * 10000 / relevant + 0.5) / 100
        print("-- Revised coverage:  {}/{} ({}%)".format(covered, relevant, percentage))
