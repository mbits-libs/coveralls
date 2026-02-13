# Copyright (c) 2026 Marcin Zdun
# This code is licensed under MIT license (see LICENSE for details)

import sys
from pathlib import Path

from cov.base import BaseTool, run
from cov.tools.cobertura import CoberturaXML
from cov.tools.gcov import GCOV8, JSON1
from cov.tools.llvm import LLVM


def cov_version(tool: str) -> tuple[str | None, list[int]]:
    out, _, retcode = run(tool, "--version")
    if retcode:
        return (None, [0])
    out = out.split(b"\n")
    if out[0].split(b" ", 1)[0] == b"gcov":
        # gcov (<space-having comment>) <version>, or
        # gcov (<space-having comment>) <version> <date> (prerelease) [gcc-?-branch revision <rev>]
        bver = out[0].split(b")", 1)[1].lstrip().split(b" ")[0]
        ver = [int(chunk) for chunk in bver.split(b".")]
        return ("gcov", ver)
    if out[0].split(b" ", 2)[1] == b"LLVM":
        # Ubuntu LLVM version <version>
        bver = out[0].split(b" ", 4)[3].strip()
        ver = [int(chunk) for chunk in bver.split(b".")]
        return ("llvm", ver)
    return (None, [0])


def guess_tool(
    gcov: str | None,
    cobertura: str | None,
    merge: str,
    target: str,
    bin_dir: Path,
    int_dir: Path,
) -> BaseTool:
    if cobertura:
        return CoberturaXML(cobertura)
    if gcov:
        tool_id, version = cov_version(gcov)
    else:
        tool_id, version = None, [0]
        gcov = ""

    if tool_id == "gcov":
        if version[0] < 9:
            return GCOV8(gcov, bin_dir, int_dir)

        return JSON1(gcov, bin_dir, int_dir)

    if tool_id == "llvm":
        return LLVM(gcov, merge, target, bin_dir, int_dir)

    print(
        "Unrecognized coverage tool:",
        tool_id,
        ".".join([str(chunk) for chunk in version]),
        file=sys.stderr,
    )
    sys.exit(1)
