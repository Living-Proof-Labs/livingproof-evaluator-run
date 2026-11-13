"""Build the manual and validate its local rendered destinations."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
REPO = 'https://github.com/Living-Proof-Labs/livingproof-evaluator-run'


def git(*args):
    return subprocess.check_output(['git', *args], text=True).strip()


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids, self.links = set(), []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if 'id' in attrs:
            self.ids.add(attrs['id'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append(attrs[key])


stage = Path('.build/docs')
shutil.rmtree('.build', ignore_errors=True)
shutil.rmtree('site', ignore_errors=True)
shutil.copytree('docs', stage)
lock = json.loads(Path('docs-brand.lock.json').read_text())
url = f"https://raw.githubusercontent.com/{lock['repository']}/{lock['commit']}/{lock['path']}"
with urlopen(url, timeout=30) as response:
    brand = response.read()
if hashlib.sha256(brand).hexdigest() != lock['sha256']:
    raise SystemExit('Brand checksum mismatch')
(stage / 'assets').mkdir()
(stage / 'assets/brand.css').write_bytes(brand)
sha = git('rev-parse', 'HEAD')
identity = {'source_commit': sha, 'source_dirty': bool(git('status', '--porcelain')), 'brand': lock}
run_id = os.environ.get('GITHUB_RUN_ID')
if run_id:
    identity['workflow_run'] = f'{REPO}/actions/runs/{run_id}'
(stage / 'version.md').write_text(f'''# Version and source

Docs: development · [{sha[:7]}]({REPO}/tree/{sha})

Full source commit: `{sha}`. Uncommitted source changes: `{identity['source_dirty']}`.
This manual describes the initial repository scaffold, not a released evaluator.
The documentation build package's `0.0.0` is not a product release.

[Source tree]({REPO}/tree/{sha}) ·
[Verification workflow]({REPO}/actions/workflows/docs.yml) ·
[Machine-readable build identity](build.json)

Only a moving development manual is planned. Historical rendered manuals are not
maintained; consult [source tags]({REPO}/tags) and Git history for older revisions.

Brand: guidelines {lock['version']} at `{lock['commit']}`, verified by SHA-256.
''')
subprocess.run(['zensical', 'build', '--clean'], check=True)
Path('site/build.json').write_text(json.dumps(identity, indent=2) + '\n')
site = Path('site').resolve()
pages = {p.resolve(): Page(p.read_text()) for p in site.rglob('*.html')}
errors = []
for path, page in pages.items():
    text = path.read_text()
    if 'assets/brand.css' not in text or 'data-md-color-primary="indigo"' in text:
        errors.append(f'{path.relative_to(site)}: missing brand or stock indigo')
    for link in page.links:
        parsed = urlsplit(link)
        if parsed.scheme or parsed.netloc or parsed.path.startswith('/'):
            continue
        target = (path.parent / unquote(parsed.path)).resolve() if parsed.path else path
        if target.is_dir():
            target /= 'index.html'
        if not target.is_relative_to(site) or not target.exists():
            errors.append(f'{path.relative_to(site)}: missing local destination {link}')
        elif parsed.fragment and target in pages and unquote(parsed.fragment) not in pages[target].ids:
            errors.append(f'{path.relative_to(site)}: missing fragment {link}')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'PASS: {len(pages)} HTML pages; local links/fragments and shared brand checked.')
