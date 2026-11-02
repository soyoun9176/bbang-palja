#!/usr/bin/env python3
"""Update the public Pages API address; never put credentials in this file."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('url', help='The HTTPS origin printed by Quick Tunnel.')
parser.add_argument('--live', action='store_true', help='Remove the prototype notice for the actual event.')
args = parser.parse_args()
parsed = urlsplit(args.url)
if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
        or parsed.query or parsed.fragment or parsed.path not in ('', '/') or parsed.port not in (None, 443)):
    parser.error('Use an HTTPS origin without credentials, path, query, or fragment.')
url = args.url.rstrip('/')
target = Path(__file__).resolve().parents[1] / 'frontend/config.js'
config = {'apiBase': url, 'prototype': not args.live}
target.write_text('// Public API address only. Never add passwords or DB credentials here.\n'
                  + 'window.KAMBO_CONFIG = ' + json.dumps(config, ensure_ascii=False, indent=2) + ';\n'
                  + "if (['localhost', '127.0.0.1', '::1', '[::1]'].includes(window.location.hostname)) {\n"
                  + "  window.KAMBO_CONFIG.apiBase = '';\n}\n")
print('Updated frontend/config.js: ' + url)
