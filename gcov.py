import json
import gzip
import os
import subprocess
import sys

class Base:
	def __init__(self):
		pass

	def run(self, tool, dirn, files):
		p = subprocess.Popen([tool, '-l', '-i', '-p', '-o', dirn] + files, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
		out, err = p.communicate()
		if p.returncode:
			print >>sys.stderr, err
			print >>sys.stderr, 'error:', p.returncode
			sys.exit()

	def ext(self): pass

	def stats(self, bin_dir, gcov_file): pass

class GCOV8(Base):
	def __init__(self):
		Base.__init__(self)

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
					if file is not None: result[filename] = file
					filename = split[1].strip()
					if not os.path.isabs(filename):
						filename = os.path.abspath(os.path.join(bin_dir, filename))
					file = [[], []]
					continue

				if split[0] == 'function':
					start, stop, count, name = split[1].split(',')
					file[0].append((int(start), int(stop), int(count), name.strip()))
					continue

				if split[0] == 'lcount':
					line, count, has_unexecuted = split[1].split(',')
					file[1].append((int(line), int(count), int(has_unexecuted)))
					continue

			if file is not None: result[filename] = file
		return result

class JSON1(Base):
	def __init__(self):
		Base.__init__(self)

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
					(fun['start_line'], fun['end_line'], fun['execution_count'], fun['name'])
					for fun in coverage['functions']
				]

				lines = [
					(line['line_number'], line['count'], line['unexecuted_block'])
					for line in coverage['lines']
				]

				result[filename] = [functions, lines]
		return result
