#!/usr/bin/env python3

import os
import errno
import sys
import argparse
import subprocess
import json
import hashlib

parser = argparse.ArgumentParser(description='Gather GCOV data for Coveralls')
handler = parser.add_mutually_exclusive_group(required=True)
handler.add_argument('--cobertura',
                     help='look for .xml cobertura files instead of .gcno gcov files',
                     action='store_true')
handler.add_argument('--gcov', metavar='PATH',
                     help='path to the gcov program')
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


def file_md5(path):
    m = hashlib.md5()
    lines = 0
    with open(path, 'rb') as f:
        for line in f:
            m.update(line)
            lines += 1
    return (m.hexdigest(), lines)


job_id = ENV('TRAVIS_JOB_ID')
service = ''
if job_id:
    service = 'travis-ci'
    sys.stdout.write(
        "Preparing Coveralls for Travis-CI job {}.\n".format(job_id))
else:
    job_id = ENV('APPVEYOR_JOB_ID')
    if job_id:
        service = 'appveyor'
        sys.stdout.write(
            "Preparing Coveralls for AppVeyor job {}.\n".format(job_id))

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

gcda_dirs = {}
for gcda in recurse(os.path.abspath(args.bin_dir), '.gcno'):
    dirn, filen = os.path.split(gcda)
    if dirn not in gcda_dirs:
        gcda_dirs[dirn] = []
    gcda_dirs[dirn].append(filen)


def cov_version(tool):
    out, err, retcode = run(tool, "--version")
    if retcode:
        return (None, [0])
    out = out.split(b'\n')
    if out[0].split(b' ', 1)[0] == b'gcov':
        # gcov (<space-having comment>) <version>, or
        # gcov (<space-having comment>) <version> <date> (prerelease) [gcc-?-branch revision <rev>]
        bver = out[0].split(b')', 1)[1].lstrip().split(b' ')[0]
        ver = [int(chunk) for chunk in bver.split(b'.')]
        return ('gcov', ver)
    return (None, [0])


if args.gcov is None and args.cobertura:
    tool_id, version = 'cobertura', ['xml']
else:
    tool_id, version = cov_version(args.gcov)

if tool_id == 'gcov':
    import gcov
    if version[0] < 9:
        cov_tool = gcov.GCOV8()
    else:
        cov_tool = gcov.JSON1()
elif tool_id == 'cobertura':
    import cobertura
    cov_tool = cobertura.CoberturaXML(args.cobertura)
else:
    print('Unrecognized coverage tool:', tool_id, '.'.join(
        [str(chunk) for chunk in version]), file=sys.stderr)
    sys.exit(1)

for dirn in gcda_dirs:
    int_dir = os.path.relpath(dirn, args.bin_dir).replace(os.sep, '#')
    int_dir = os.path.join(args.int_dir, int_dir)
    mkdir_p(int_dir)
    with cd(int_dir):
        cov_tool.run(args.gcov, dirn, [os.path.join(
            dirn, filen) for filen in gcda_dirs[dirn]])

src_dir = os.path.abspath(args.src_dir)
src_dir_len = len(src_dir)
coverage = {}
maps = {}
for stats in recurse(args.int_dir, cov_tool.ext()):
    gcov_data = cov_tool.stats(args.bin_dir, stats)
    for src in gcov_data:
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
        fns, lines = gcov_data[src]
        # Build the report with generic paths
        if os.sep != '/':
            name = name.replace(os.sep, '/')
        for ln in lines:
            if name not in coverage:
                coverage[name] = {}
                maps[name] = src
            if ln[0] not in coverage[name]:
                coverage[name][ln[0]] = 0
            coverage[name][ln[0]] += ln[1]

for src in sorted(coverage.keys()):
    lines = coverage[src]
    digest, line_count = file_md5(maps[src])
    size = max(line_count, max(lines.keys()))
    cvg = [None] * size
    for line in lines:
        cvg[line-1] = lines[line]

    JSON['source_files'].append({
        'name': src,
        'source_digest': digest,
        'coverage': cvg
    })

with open(args.out, 'w') as j:
    json.dump(JSON, j)
