#!/usr/bin/env python3
"""Build only public frontend files, with content-addressed JS and CSS."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def build(output, commit=None):
    source = ROOT / 'frontend'
    if (output.is_symlink() or output.resolve() in (ROOT, source)
            or output.resolve() in ROOT.parents or source in output.resolve().parents):
        raise ValueError('Output must be outside frontend and must not be the repository root.')
    if output.exists():
        if not (output / '.bbang-frontend-build').is_file():
            raise ValueError('Refusing to replace an unmanaged output directory.')
        shutil.rmtree(output)
    shutil.copytree(source, output)
    (output / '.bbang-frontend-build').touch()
    assets = output / 'build'
    assets.mkdir()

    def asset(name, content=None):
        content = (source / name).read_bytes() if content is None else content
        version = hashlib.sha256(content).hexdigest()[:16]
        path = Path(name)
        target = f'{path.stem}.{version}{path.suffix}'
        (assets / target).write_bytes(content)
        (output / name).unlink()
        return '/build/' + target

    admin, profile = asset('admin.js'), asset('profile.js')
    app_source = (source / 'app.js').read_text().replace("'./admin.js'", repr(admin)).replace("'./profile.js'", repr(profile))
    app = asset('app.js', app_source.encode())
    config, css = asset('config.js'), asset('styles.css')
    index = (source / 'index.html').read_text()
    index = re.sub(r'/app\.js(?:\?[^"\s]+)?', app, index)
    index = index.replace('/config.js', config).replace('/styles.css', css)
    (output / 'index.html').write_text(index)
    commit = commit or os.environ.get('CF_PAGES_COMMIT_SHA') or os.environ.get('GITHUB_SHA')
    if not commit:
        commit = subprocess.check_output(['git','rev-parse','HEAD'], cwd=ROOT, text=True).strip()
    (output / 'version.json').write_text(json.dumps({'commit':commit,'app':app,'config':config,'css':css})+'\n')
    (output / '_headers').write_text('''/
  Cache-Control: no-store
/admin
  Cache-Control: no-store
/admin/
  Cache-Control: no-store
/index.html
  Cache-Control: no-store
/version.json
  Cache-Control: no-store
/build/*
  Cache-Control: public, max-age=31536000, immutable
''')
    print(f'Frontend built: {output} · {commit}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    args = parser.parse_args()
    build(args.output)
