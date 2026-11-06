#!/usr/bin/env python3
"""Pages publishes only after tests and the same Oracle release are healthy."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def deployment_project(environment=None):
    environment = os.environ if environment is None else environment
    project = json.loads((ROOT/'ops/pages-project.json').read_text())
    origin = f"https://{project['name']}.pages.dev"
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',project['name']) or project['production_origin'] != origin:
        raise SystemExit('Invalid Pages project origin in ops/pages-project.json.')
    if environment.get('CF_PAGES_BRANCH',project['production_branch']) != project['production_branch']:
        raise SystemExit('Preview deployments require a separate API; only the production branch is enabled.')
    if environment.get('CF_PAGES_URL'):
        actual = urlsplit(environment['CF_PAGES_URL'])
        host = urlsplit(origin).hostname
        if actual.scheme != 'https' or not (actual.hostname == host or (actual.hostname or '').endswith('.'+host)):
            raise SystemExit(f"This repository deploys to {origin}; refusing a different Pages project.")
    return project


def api_ready(base_url, commit, origin):
    request = urllib.request.Request(base_url+'/api/health',headers={'Cache-Control':'no-cache','Origin':origin})
    with urllib.request.urlopen(request,timeout=10) as response:
        health = json.load(response)
        if not health.get('ok') or health.get('commit') != commit or response.headers.get('Access-Control-Allow-Origin') != origin:
            return False
    preflight = urllib.request.Request(base_url+'/api/orders',method='OPTIONS',headers={
        'Origin':origin,'Access-Control-Request-Method':'POST',
        'Access-Control-Request-Headers':'Authorization, Content-Type'})
    with urllib.request.urlopen(preflight,timeout=10) as response:
        methods = {part.strip().upper() for part in response.headers.get('Access-Control-Allow-Methods','').split(',')}
        headers = {part.strip().lower() for part in response.headers.get('Access-Control-Allow-Headers','').split(',')}
        return (response.status == 204 and response.headers.get('Access-Control-Allow-Origin') == origin
                and 'POST' in methods and {'authorization','content-type'} <= headers)


def main():
    project = deployment_project()
    subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'], cwd=ROOT, check=True)
    subprocess.run(['node','--test','tests/frontend-check.mjs'], cwd=ROOT, check=True)
    commit = os.environ.get('CF_PAGES_COMMIT_SHA')
    if commit:
        config = (ROOT / 'frontend/config.js').read_text()
        url = re.search(r'"apiBase":\s*"(https://[a-z0-9-]+\.trycloudflare\.com)"', config)
        if not url:
            raise SystemExit('Expected a Quick Tunnel origin in frontend/config.js.')
        deadline = time.monotonic()+540
        while True:
            try:
                if api_ready(url[1],commit,project['production_origin']):
                    break
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise SystemExit('Oracle did not confirm this commit and Pages CORS. Current Pages deployment is preserved.')
            print('Waiting for the verified Oracle release and Pages CORS...', flush=True)
            time.sleep(15)
    subprocess.run([sys.executable,'ops/build-frontend.py'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
