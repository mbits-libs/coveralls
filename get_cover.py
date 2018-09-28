# -*- coding: utf-8 -*-

from __future__ import print_function
import io, os, sys, argparse, errno, subprocess, json, hashlib

parser = argparse.ArgumentParser(description='Gather GCOV data for Coveralls')
parser.add_argument('--in',    required=True,  help='Coveralls JSON file', dest='json')
parser.add_argument('--prev',  required=False, help='Coveralls JSON file for previous build')
parser.add_argument('--out',   required=False, help='Output directory')
parser.add_argument('--dirty',   default=False, action='store_true', required=False, help='Output directory')
args = parser.parse_args()

RESULT_GOOD = 90.00
RESULT_OK = 75.00

def escape(s):
	return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')

class cd:
	def __init__(self, dirname):
		self.dirname = os.path.expanduser(dirname)
	def __enter__(self):
		self.saved = os.getcwd()
		os.chdir(self.dirname)
	def __exit__(self, etype, value, traceback):
		os.chdir(self.saved)

def mkdir_p(path):
	try:
		os.makedirs(path)
	except OSError as exc:  # Python >2.5
		if exc.errno == errno.EEXIST and os.path.isdir(path):
			pass
		else:
			raise

def run(*args):
	p = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
	out, err = p.communicate();
	return (out, err, p.returncode)

def output(*args):
	return run(*args)[0].strip().decode('utf-8')

def print_header(git):
	repo_head = git['head']
	author = '{name} <{email}>'.format(name=repo_head['author_name'], email=repo_head['author_email'])
	commiter = '{name} <{email}>'.format(name=repo_head['committer_name'], email=repo_head['committer_email'])

	print('branch: {}'.format(git['branch']))
	print('commit: {}'.format(repo_head['id']))
	print('author: {}'.format(author))
	if author != commiter:
		print('commiter: {}'.format(commiter))
	print('\n   ', '\n    '.join(repo_head['message'].split('\n')))
	print()

def percent(value):
	return '{:.2f}%'.format(value)

def average(value):
	return '{}.{:02}'.format(int(value / 100), int(value % 100))

def diff_(curr, prev, fmt, conv=str):
	if curr == prev:
		return fmt.format(conv(curr), '', '')
	if curr > prev:
		return fmt.format(conv(curr), '+', conv(curr - prev))
	return fmt.format(conv(curr), '-', conv(prev - curr))

updown = u'<span class="ind"><span class="ind-up"></span><span class="ind-down"></span></span>'
def diff_html_(curr, prev, conv=str, klass=None):
	if klass is None: klass = ""
	else: klass = " " + klass
	if curr == prev:
		which="same"
		diff=""
	elif curr > prev:
		which="up"
		diff='<span class="diff">+{}</span>'.format(conv(curr - prev))
	else:
		which="down"
		diff='<span class="diff">-{}</span>'.format(conv(prev - curr))

	return u'<td class="value{clname}">{value}</td><td class="{which}{clname}">{updown}{diff}</td>'.format(
		value=conv(curr), which=which, updown=updown, diff=diff, clname=klass)


class stats:
	def __init__(self):
		self.coverage = 0.0
		self.lines = 0
		self.relevant = 0
		self.covered = 0
		self.visited = 0
		self.average = 0

	def append(self, stat):
		self.lines += 1
		if stat is None: return
		self.relevant += 1
		if stat:
			self.covered += 1
		self.visited += stat
		self.__update()

	def __str__(self):
		return str((self.lines, self.relevant, self.covered, self.visited))

	def __iadd__(self, rhs):
		self.lines += rhs.lines
		self.relevant += rhs.relevant
		self.covered += rhs.covered
		self.visited += rhs.visited
		self.__update()
		return self

	def __add__(self, rhs):
		tmp = stats()
		tmp += self
		tmp += rhs
		return tmp

	def __update(self):
		if self.relevant:
			self.coverage = 100.0 * self.covered / self.relevant
			self.average = 100 * self.visited / self.relevant
		else:
			self.coverage = 0.0
			self.average = 0

	def txt(self, prev):
		if prev is None:
			prev = stats()
			prev += self

		return '{} {} {} {} {}'.format(
			diff_(self.coverage, prev.coverage, '{:>7}{:>2}{:<7}', percent),
			diff_(self.lines, prev.lines, '{:>8}{:>2}{:<8}'),
			diff_(self.relevant, prev.relevant, '{:>8}{:>2}{:<8}'),
			diff_(self.covered, prev.covered, '{:>8}{:>2}{:<8}'),
			diff_(self.average, prev.average, '{:>10}{:>2}{:<10}', average)
			)

	def html(self, prev):
		if prev is None:
			prev = stats()
			prev += self

		missed = self.relevant - self.covered
		return u'{}{}{}{}{}{}'.format(
			diff_html_(self.coverage, prev.coverage, percent,
				"cov cov-good" if self.coverage >= RESULT_GOOD else (\
				"cov cov-ok" if self.coverage >= RESULT_OK else \
				"cov cov-bad")),
			diff_html_(self.lines, prev.lines),
			diff_html_(self.relevant, prev.relevant),
			diff_html_(self.covered, prev.covered),
			diff_html_(missed, prev.relevant - prev.covered, klass=
				"missed missed-nothing" if missed == 0 else "missed missed-lines"),
			diff_html_(self.average, prev.average, average)
			)

class file_info:
	def __init__(self):
		self.coverage = stats()
		self.prev = None
		self.digest = ''
		self.lines = []

	def txt(self, name):
		return ' {}     {}'.format(
			self.coverage.txt(self.prev),
			os.path.basename(name)
			)

	def html(self, name):
		line = None
		covered = None
		for ln in range(len(self.lines)):
			val = self.lines[ln]
			if val is None: continue
			if covered is None: covered = ln
			if val == 0:
				line = ln
				break
		if line is None: line = covered
		if line is None: line = 0

		if self.digest is None:
			return u'<tr class="file"><td class="name"><del>{1}</del></td>{0}</tr>'.format(
				self.coverage.html(self.prev), escape(os.path.basename(name))
				)

		return u'<tr class="file"><td class="name"><a href="{2}#L{3}">{1}</a></td>{0}</tr>'.format(
			self.coverage.html(self.prev), escape(os.path.basename(name)), escape(self.digest) + '.html', line+1
			)

class dir_info:
	def __init__(self):
		self.coverage = stats()
		self.prev = None
		self.files = set()

	def append(self, fcovg, fname):
		self.coverage += fcovg
		self.files.add(fname)

	def append_prev(self, fcovg, fname):
		if self.prev is None:
			self.prev = stats()
		self.prev += fcovg
		self.files.add(fname)

	def txt(self, name):
		return ' {} {}'.format(
			self.coverage.txt(self.prev), name
			)

	def html(self, name):
		return u'<tr class="filler"><td colspan="11">&nbsp;</td><tr>\n<tr class="dir"><td class="name">{1}</td>{0}</tr>'.format(
			self.coverage.html(self.prev), escape(name)
			)

class sources:
	def __init__(self, files, with_lines = False):
		self.total = stats()
		self.prev = None
		self.dirs = {}
		self.files = {}

		self.stats = {}
		dirs = {}

		for filedef in files:
			info = file_info()
			info.digest = filedef['source_digest']

			for stat in filedef['coverage']:
				info.coverage.append(stat)

			if with_lines:
				info.lines = filedef['coverage']

			name = filedef['name']
			self.files[name] = info

			dname = os.path.dirname(name)
			if dname not in self.dirs:
				self.dirs[dname] = dir_info()
			self.dirs[dname].append(info.coverage, name)
			self.total += info.coverage

	def txt(self):
		return ' {} TOTAL'.format(
			self.total.txt(self.prev)
			)

	def html(self):
		return u'<tr class="total"><td class="name">(Total)</td>{}</tr>'.format(
			self.total.html(self.prev)
			)

	def diff_to(self, prev):
		self.prev = stats()
		for fname in self.files:
			info = self.files[fname] 
			info.prev = stats()
			dname = os.path.dirname(fname)
			if dname not in self.dirs:
				self.dirs[dname] = dir_info()
			self.dirs[dname].append_prev(stats(), fname)

		for fname in prev.files:
			prev_file = prev.files[fname]
			try:
				info = self.files[fname]
			except:
				info = file_info()
				info.digest = None
				self.files[fname] = info
			self.prev += prev_file.coverage 
			info.prev = prev_file.coverage
			dname = os.path.dirname(fname)
			if dname not in self.dirs:
				self.dirs[dname] = dir_info()
			self.dirs[dname].append_prev(prev_file.coverage, fname)

with open(args.json) as data_file:
	data = json.load(data_file)

print_header(data['git'])
curr = sources(data['source_files'], True)

if args.prev is not None:
	try:
		with open(args.prev) as prev_file:
			prev = json.load(prev_file)
			prev = sources(prev['source_files'])
	except:
		prev = sources({})
	curr.diff_to(prev)

print('COVERAGE             TOTAL           RELEVANT            COVERED            HITS/LINE             NAME')
print(curr.txt())
print()

for dname in sorted(curr.dirs.keys()):
	dinfo = curr.dirs[dname]
	print(dinfo.txt(dname))
	for fname in sorted(dinfo.files):
		finfo = curr.files[fname]
		print(finfo.txt(fname))
	print()

css = u'''*, td, th {
	box-sizing: border-box;
}

body, td, th {
    font-family: "Segoe UI", Candara, "Bitstream Vera Sans", "DejaVu Sans", "Bitstream Vera Sans", "Trebuchet MS", Verdana, "Verdana Ref", sans-serif;
}

div.content {
	max-width: 1000px;
	margin: 0 auto;
}

table.listing {
	width: 100%;
	padding: 1em;
	border-collapse: separate;
	border-spacing: 0;
}

table.listing tr td {
	color: #555;
	font-family: monospace;
	padding: 0 1em;
	background: rgba(192,192,192,0.1);
}

table.listing tr.success td {
	background: rgba(208,233,153,0.2);
}

table.listing tr.error td {
	background: rgba(216,134,123,0.2);
}

table.listing a {
	color: inherit;
	text-decoration: none;
}

table.listing td:nth-child(odd) {
	text-align: right;
}

table.listing td:nth-child(1) {
	border-right: solid 1px #ddd;
}

table.listing td:nth-child(2) {
	border-left: solid 1px #fff;
}

table.listing td:nth-child(3) {
	font-size: smaller;
}

table.listing pre {
	word-wrap: break-word;
}

table.stats { border-collapse: collapse; font-size: .9em; width: 100% }
table.stats th { font-size: 1.1em }
table.stats th, table.stats td { padding: 0.2em }
table.stats th, td.value { text-align: right; padding-left: .5em }
table.stats th:first-child { text-align: left; padding-left: .2em }
table.stats th, tr.total td.name { font-variant: small-caps }

td.same, td.up, td.down { padding-right: .83333em; padding-left: .33333em; font-size: .7em }

.ind { color: gray; font-size: 2em; font-family: monospace; margin-right: .3em }
.ind-up:before { content: "\\25b2" }
.ind-down:before { content: "\\25bc" }

td.same .ind { display: none }

td.up { color: green }
td.down { color: red }

td.up .ind-up { color: #4a4 }
td.down .ind-down { color: red }
td.up .ind-down, td.down .ind-up { display: none }

tr.total td.name { font-style: italic }
tr.filler td { padding-top: .5em; padding-bottom: .5em; }
tr.file td.name a, tr.file td.name del {
    padding-left: 2.2em;
    display: inline-block;
    min-width: 100%
}
tr.file td.name a {
    color: inherit;
    text-decoration: none;
}
tr.file td.name del {
    color: #555;
}
tr.file td.name a:hover { text-decoration: underline; }

tr.total td, tr.dir td { font-weight: bolder }

thead tr { background: #111; color: #f5f5f5 }
tr.dir, tr.total { background: #eee }
tr.file:nth-child(odd) { background: #f5f5f5 }
tr.file:nth-child(even) { background: #fcfcfc }

tr td.cov-bad { background: rgba(255, 0, 0, .1)}
tr td.cov-ok { background: rgba(255, 255, 0, .1)}
tr td.cov-good { background: rgba(0, 255, 0, .1)}
tr td.value.cov-bad { color: #c44 }
tr td.value.cov-ok { color: #883 }
tr td.value.cov-good { color: #080 }

tr td.value.missed-lines { font-style: italic }

table#commit { border-collapse: collapse; width: 100%; margin-bottom: 2em; }

table#commit td.label {
  color: silver;
  text-align: right;
  padding-right: 1em;
  font-size: .8em;
  font-weight: bold;
}

table#commit h4 { padding-top: 1em; }

#author img, #commiter img {
  border-radius: 50%;
  box-shadow: 1px 1px 5px 0px rgba(0,0,0,0.5);
  vertical-align: middle;
  width: 1em;
  height: 1em;
}'''

if args.out is not None:
	mkdir_p(args.out)

	if args.dirty:
		git_root = output('git', 'rev-parse', '--show-toplevel')
	with cd(args.out):
		head = data['git']['head']
		commit = head['id']
		author = (head['author_name'], head['author_email'])
		commiter = (head['committer_name'], head['committer_email'])
		message = head['message'].split('\n\n', 1)
		subject = escape(message[0])
		try:
			details = '<pre>{}</pre>'.format(escape(message[1]))
		except:
			details = ''

		title_fmt = '<tr><td class="label">{title}</td><td id="{kind}" title="{email}"><img src="https://www.gravatar.com/avatar/{hash}?s=96&d=mp" width="16px" height="16px"/> {name}</td></tr>'
		author_ = title_fmt.format(title='Author', kind='author', name=escape(author[0]), email=escape(author[1]), hash=hashlib.md5(author[1].lower()).hexdigest())
		commiter_ = title_fmt.format(title='Commited&nbsp;by', kind='commiter', name=escape(commiter[0]), email=escape(commiter[1]), hash=hashlib.md5(commiter[1].lower()).hexdigest())

		if author == commiter:
			author_ = ''
			author_icon = ''


		with io.open('index.html', 'w', encoding='utf-8') as out:
			print(u'''<html>
<head>
<title>Coverage</title>
<style type="text/css">
{css}
</style>
</head>
<body>
<div class="content">
<h1>Coverage</h1>

<table id='commit'>
{author}
{commiter}
<tr><td class="label">Commit</td><td>{commit}</td></tr>
<tr><td class="label">Branch</td><td>{branch}</td></tr>
<tr><td class="label">&nbsp;</td><td><h4>{subject}</h4>
{details}</td></tr>
</table>

<table class="stats">'''.format(css=css, subject=subject, details=details, author=author_, commiter=commiter_, commit=commit, branch=data['git']['branch']), file=out)
			print(u'<thead><tr><th>Name</th><th>Coverage</th><th>&nbsp;</th><th>Total</th><th>&nbsp;</th><th>Relevant</th><th>&nbsp;</th><th>Covered</th><th>&nbsp;</th><th>Missed</th><th>&nbsp;</th><th>Hits/Line</th><th>&nbsp;</th></tr></thead>', file=out)
			print(curr.html(), file=out)
			for dname in sorted(curr.dirs.keys()):
				dinfo = curr.dirs[dname]
				print(dinfo.html(dname), file=out)
				for fname in sorted(dinfo.files):
					finfo = curr.files[fname]
					print(finfo.html(fname), file=out)
			print(u'''</table>
</div>
</body>
</html>''', file=out)

		for fname in sorted(curr.files.keys()):
			finfo = curr.files[fname]
			if finfo.digest is None:
				continue
			# print(finfo.digest, fname)
			if args.dirty:
				with io.open(os.path.join(git_root, fname), encoding="utf-8") as f:
					content = f.readlines()
			else:
				content = output('git', 'show', '%s:%s' % (commit, fname)).split('\n')
			with io.open(finfo.digest + '.html', 'w', encoding='utf-8') as out:
				print(u'''<html>
<head>
<title>{fname} &mdash; Coverage</title>
<style type="text/css">
{css}
</style>
</head>
<body>
<h1>{fname}</h1>
<div class="content">
<table class="listing">'''.format(fname=escape(fname), css=css, lines=len(finfo.lines)), file=out)
				for lineno in range(len(content)):
					stat = None
					if lineno < len(finfo.lines):
						stat = finfo.lines[lineno]
					klass = ''
					if stat is None:
						stat = ''
					else:
						klass = 'success' if stat else 'error'
						if not stat: stat = ''
						else: stat = '<a href="#L{lineno}">{stat}&times;</a>'.format(stat=stat, lineno=(lineno + 1))
					if klass: klass = ' class="{}"'.format(klass)
					print(u'<tr{klass}><td><a name="L{lineno}"></a><a href="#L{lineno}">{lineno}</a></td><td><a href="#L{lineno}"><pre>{code}</pre></a></td><td>{stat}</td></tr>'.format(
						klass=klass, lineno=(lineno + 1), code=escape(content[lineno]), stat=stat
						), file=out
					)

				print(u'''</table>
</div>
</body>
</html>''', file=out)
