#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import subprocess
import sys
import re
from fnmatch import fnmatch

parser = argparse.ArgumentParser(description='Gather GCOV data for Coveralls')
handler = parser.add_mutually_exclusive_group(required=True)
handler.add_argument('--cobertura',
                     help='look for .xml cobertura files instead of .gcno gcov files',
                     action='store_true')
handler.add_argument('--gcov', metavar='PATH',
                     help='path to the gcov/llvm-cov program')
parser.add_argument('--merge', metavar='PATH',
                     help='path to the llvm-profdata program')
parser.add_argument('--git', metavar='PATH', required=True,
                    help='path to the git binary')
parser.add_argument('--src_dir', metavar='DIR', required=True,
                    help='directory for source files')
parser.add_argument('--bin_dir', metavar='DIR', required=True,
                    help='directory for generated files')
parser.add_argument('--int_dir', metavar='DIR', required=True,
                    help='directory for temporary gcov files')
parser.add_argument('--dirs', metavar='DIR:DIR:...', required=True,
                    help='directory filters for relevant sources, separated with\':\'')
parser.add_argument('--out', metavar='JSON', required=True,
                    help='output JSON file for Coveralls')
parser.add_argument('--ignore-files', required=False,
                    help='adds a glob.glob mask for files to ignore',
                    action='append', metavar='MASK', default=[])
parser.add_argument('--debug', required=False,
                    help='prints JSON, if present',
                    action='store_true', default=False)

args = parser.parse_args()
args.dirs = args.dirs.split(':')
for idx in range(len(args.dirs)):
    dname = args.dirs[idx].replace('\\', os.sep).replace('/', os.sep)
    if dname[len(dname) - 1] != os.path.sep:
        dname += os.path.sep
    args.dirs[idx] = dname


class cd:
    def __init__(self, dirname):
        self.dirname = os.path.expanduser(dirname)

    def __enter__(self):
        self.saved = os.getcwd()
        os.chdir(self.dirname)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.saved)


def mkdir_p(path):
    os.makedirs(path, exist_ok=True)


def run(*args):
    p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = p.communicate()
    return (out, err, p.returncode)


def output(*args):
    return run(*args)[0].strip().decode('utf-8')


def git_log_format(fmt):
    return output(args.git, 'log', '-1', '--pretty=format:%' + fmt)


def gcov(dir_name, gcdas):
    out, err, code = run(args.gcov, '-l', '-i', '-p', '-o', dir_name, *gcdas)
    if code:
        print(err, file=sys.stderr)
        print('error:', code, file=sys.stderr)
        sys.exit()


def recurse(root, ext):
    for dirname, ign, files in os.walk(root):
        for f in files:
            if f[-len(ext):] == ext:
                yield os.path.join(dirname, f)


def ENV(name):
    try:
        return os.environ[name]
    except KeyError:
        return ''


try:
    OS_EXCL = {
        'nt': [b'WIN32'],
        'posix': [b'POSIX', b'GCC']
    }[os.name]
except KeyError:
    OS_EXCL = []


def file_md5_excl(path):
    m = hashlib.md5()
    lines = 0
    excludes = []
    inside_exclude = False
    with open(path, 'rb') as f:
        for line in f:
            m.update(line)
            valid_for_os = True
            match = re.search(
                rb"(G|L|GR)COV_EXCL_(START|LINE)\[([^]]+)\]", line)
            if match:
                valid_for_os = match.group(3) in OS_EXCL

            if valid_for_os:
                switch_off = False
                if re.search(b"(G|L|GR)COV_EXCL_STOP", line):
                    switch_off = True
                elif re.search(b"(G|L|GR)COV_EXCL_START", line):
                    inside_exclude = True

                if inside_exclude or re.search(b"(G|L|GR)COV_EXCL_LINE", line):
                    excludes.append([lines, line.decode('UTF-8').rstrip()])

                if switch_off:
                    inside_exclude = False
            lines += 1
    return (m.hexdigest(), lines, excludes)


services = [
    ('TRAVIS_JOB_ID', 'travis-ci', 'Travis-CI'),
    ('APPVEYOR_JOB_ID', 'appveyor', 'AppVeyor'),
    # ('GITHUB_RUN_ID', 'github', 'GitHub Workflows'),
]

job_id = ''
service = ''
for varname, service_id, service_name in services:
    job_id = ENV(varname)
    if not job_id:
        continue

    service = service_id
    sys.stdout.write(
        "Preparing Coveralls for {} job {}.\n".format(service_name, job_id))
    break

JSON = {
    'service_name': service,
    'service_job_id': job_id,
    'repo_token': ENV('COVERALLS_REPO_TOKEN'),
    'git': {},
    'source_files': []
}

with cd(args.src_dir):
    JSON['git'] = {
        'branch': output(args.git, 'rev-parse', '--abbrev-ref', 'HEAD'),
        'head': {
            'id': git_log_format('H'),
            'author_name': git_log_format('an'),
            'author_email': git_log_format('ae'),
            'committer_name': git_log_format('cn'),
            'committer_email': git_log_format('ce'),
            'message': git_log_format('B')
        },
        'remotes': []
    }

if args.debug:
    from pprint import pprint
    pprint(JSON)

def cov_version(tool):
    out, _, retcode = run(tool, "--version")
    if retcode:
        return (None, [0])
    out = out.split(b'\n')
    if out[0].split(b' ', 1)[0] == b'gcov':
        # gcov (<space-having comment>) <version>, or
        # gcov (<space-having comment>) <version> <date> (prerelease) [gcc-?-branch revision <rev>]
        bver = out[0].split(b')', 1)[1].lstrip().split(b' ')[0]
        ver = [int(chunk) for chunk in bver.split(b'.')]
        return ('gcov', ver)
    if out[0].split(b' ', 2)[1] == b'LLVM':
        # Ubuntu LLVM version <version>
        bver = out[0].split(b' ', 4)[3].strip()
        ver = [int(chunk) for chunk in bver.split(b'.')]
        return ('llvm', ver)
    return (None, [0])


if args.gcov is None and args.cobertura:
    tool_id, version = 'cobertura', ['xml']
else:
    tool_id, version = cov_version(args.gcov)

if tool_id == 'gcov':
    import gcov
    if version[0] < 9:
        cov_tool = gcov.GCOV8(args.gcov, args.bin_dir, args.int_dir)
    else:
        cov_tool = gcov.JSON1(args.gcov, args.bin_dir, args.int_dir)
elif tool_id == 'llvm':
    import llvm
    cov_tool = llvm.LLVM(args.gcov, args.merge, args.bin_dir, args.int_dir)
elif tool_id == 'cobertura':
    import cobertura
    cov_tool = cobertura.CoberturaXML(args.cobertura)
else:
    print('Unrecognized coverage tool:', tool_id, '.'.join(
        [str(chunk) for chunk in version]), file=sys.stderr)
    sys.exit(1)

cov_tool.preprocess(recurse)

src_dir = os.path.abspath(args.src_dir)
src_dir_len = len(src_dir)
coverage = {}
maps = {}
for intermediate in recurse(args.int_dir, cov_tool.ext()):
    data = cov_tool.stats(intermediate)
    for src in data:
        if src[:src_dir_len] != src_dir:
            continue
        name = src[len(src_dir):]
        if name[0] != os.sep:
            continue
        name = name[1:]
        relevant = False
        for dname in args.dirs:
            if len(dname) < len(name) and name[:len(dname)] == dname:
                relevant = True
                break
        if relevant:
            for ign in args.ignore_files:
                if fnmatch(name, ign):
                    relevant = False
                    break
        if not relevant:
            continue
        fns, lines = data[src]
        # Build the report with generic paths
        if os.sep != '/':
            name = name.replace(os.sep, '/')
        for line, count, _ in lines:
            if name not in coverage:
                coverage[name] = {}
                maps[name] = src
            if line not in coverage[name]:
                coverage[name][line] = 0
            coverage[name][line] += count

relevant = 0
covered = 0
excluded = 0
excluded_visited = 0
excluded_unvisited = 0
patches = []

for src in sorted(coverage.keys()):
    lines = coverage[src]
    digest, line_count, excl = file_md5_excl(maps[src])
    size = max(line_count, max(lines.keys()))
    cvg = [None] * size
    relevant += len(lines)
    for line in lines:
        val = lines[line]
        if val:
            covered += 1
        cvg[line-1] = val
    excluded += len(excl)
    patch_lines = []
    for line, text in excl:
        val = cvg[line]
        if val is not None:
            relevant -= 1
            if not val:
                excluded_unvisited += 1
            else:
                excluded_visited += 1
                covered -= 1
        cvg[line] = None
        patch_lines.append((line, str(val) if val is not None else '', text))
    if len(patch_lines):
        patches.append((src, patch_lines))

    JSON['source_files'].append({
        'name': src,
        'source_digest': digest,
        'coverage': cvg
    })

with open(args.out, 'w') as j:
    json.dump(JSON, j)

if excluded:
    counter_width = 0
    for file, lines in patches:
        for linno, count, line in lines:
            length = len(count)
            if length > counter_width:
                counter_width = length

    color = '\033[2;49;30m'
    reset = '\033[m'

    for file, lines in patches:
        prev = -10
        for num, counter, line in lines:
            if num - prev > 1:
                if os.name == 'nt':
                    print("{}({})".format(os.path.abspath(
                        os.path.join(args.src_dir, file)), num + 1))
                else:
                    print("--   {}:{}".format(file, num + 1))
            prev = num
            print("     {:>{}} | {}{}{}".format(
                counter, counter_width, color, line, reset))

percentage = int(covered*10000 / relevant + 0.5) / 100 if relevant else 0
print("-- Coverage reported: {}/{} ({}%)".format(covered, relevant, percentage))

if excluded:
    def counted(counter, when_one, otherwise):
        if counter == 0:
            return when_one.format(counter)
        return otherwise.format(counter)
    excl_str = counted(excluded_unvisited + excluded_visited, "one line", "{} lines")
    unv_str = counted(excluded_unvisited, "one line", "{} lines")
    print("-- Excluded relevant: {}".format(excl_str))
    print("-- Excluded missing:  {}".format(unv_str))
    relevant += excluded_unvisited + excluded_visited
    covered += excluded_visited
    percentage = int(covered*10000 / relevant + 0.5) / 100
    print(
        "-- Revised coverage:  {}/{} ({}%)".format(covered, relevant, percentage))
