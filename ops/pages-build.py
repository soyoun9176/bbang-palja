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

ROOT = Path(__file__).resolve().parents[1]


def main():
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
                request = urllib.request.Request(url[1]+'/api/health', headers={'Cache-Control':'no-cache'})
                with urllib.request.urlopen(request, timeout=10) as response:
                    health = json.load(response)
                if health.get('ok') and health.get('commit') == commit:
                    break
            except (OSError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise SystemExit('Oracle did not confirm this commit. Current Pages deployment is preserved.')
            print('Waiting for the verified Oracle release...', flush=True)
            time.sleep(15)
    subprocess.run([sys.executable,'ops/build-frontend.py'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
