import json
import gzip
import os
import subprocess
import sys


class cd:
    def __init__(self, dirname):
        self.dirname = os.path.expanduser(dirname)

    def __enter__(self):
        self.saved = os.getcwd()
        os.chdir(self.dirname)

    def __exit__(self, etype, value, traceback):
        os.chdir(self.saved)


class Base:
    def __init__(self, gcov, bin_dir, int_dir):
        self.gcov = gcov
        self.bin_dir = bin_dir
        self.int_dir = int_dir

    def preprocess(self, recurse):
        gcno_dirs = {}
        for gcno in recurse(os.path.abspath(self.bin_dir), ".gcno"):
            dirname, filename = os.path.split(gcno)
            if dirname not in gcno_dirs:
                gcno_dirs[dirname] = []
            gcno_dirs[dirname].append(filename)

        for dirname in gcno_dirs:
            int_dir = os.path.relpath(dirname, self.bin_dir).replace(os.sep, "#")
            int_dir = os.path.join(self.int_dir, int_dir)
            os.makedirs(int_dir, exist_ok=True)
            files = [os.path.join(dirname, filen) for filen in gcno_dirs[dirname]]
            with cd(int_dir):
                p = subprocess.Popen(
                    [self.gcov, "-l", "-i", "-p", "-o", dirname] + files,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                _, err = p.communicate()
                if p.returncode:
                    print(err, file=sys.stderr)
                    print("error:", p.returncode, file=sys.stderr)
                    sys.exit(1)

    def ext(self): pass

    def stats(self, bin_dir, gcov_file): pass


class GCOV8(Base):
    def __init__(self, gcov, bin_dir, int_dir):
        Base.__init__(self, gcov, bin_dir, int_dir)

    def ext(self): return '.gcov'

    def stats(self, bin_dir, gcov_file):
        result = {}
        filename = None
        file = None
        with open(gcov_file) as src:
            for line in src:
                split = line.split(':', 1)
                if len(split) < 2:
                    continue
                if split[0] == 'file':
                    if file is not None:
                        result[filename] = file
                    filename = split[1].strip()
                    if not os.path.isabs(filename):
                        filename = os.path.abspath(
                            os.path.join(bin_dir, filename))
                    file = [[], []]
                    continue

                if split[0] == 'function':
                    start, stop, count, name = split[1].split(',')
                    file[0].append(
                        (int(start), int(stop), int(count), name.strip()))
                    continue

                if split[0] == 'lcount':
                    line, count, has_unexecuted = split[1].split(',')
                    file[1].append(
                        (int(line), int(count), int(has_unexecuted)))
                    continue

            if file is not None:
                result[filename] = file
        return result


class JSON1(Base):
    def __init__(self, gcov, bin_dir, int_dir):
        Base.__init__(self, gcov, bin_dir, int_dir)

    def ext(self): return '.gcov.json.gz'

    def stats(self, bin_dir, gcov_file):
        result = {}
        with gzip.open(gcov_file, "rb") as compressed:
            data = json.loads(compressed.read().decode('ascii'))['files']
            for coverage in data:
                filename = coverage['file']
                if not os.path.isabs(filename):
                    filename = os.path.abspath(os.path.join(bin_dir, filename))

                functions = [
                    (fun['start_line'], fun['end_line'],
                     fun['execution_count'], fun['name'])
                    for fun in coverage['functions']
                ]

                lines = [
                    (line['line_number'], line['count'],
                     line['unexecuted_block'])
                    for line in coverage['lines']
                ]

                result[filename] = [functions, lines]
        return result
