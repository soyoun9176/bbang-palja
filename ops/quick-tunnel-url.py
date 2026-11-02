#!/usr/bin/env python3
"""Print the URL from the current Quick Tunnel process, never an older run."""
import re
import subprocess
import sys

unit = 'bbang-palja-quick-tunnel.service'
invocation = subprocess.check_output(
    ['systemctl', 'show', unit, '--property=InvocationID', '--value'], text=True).strip()
if not invocation:
    sys.exit('Quick Tunnel is not running.')
log = subprocess.check_output(
    ['journalctl', '_SYSTEMD_INVOCATION_ID=' + invocation, '--no-pager', '-o', 'cat'], text=True)
urls = re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com\b', log)
if not urls:
    sys.exit('The current tunnel has not reported its URL yet. Inspect its journal.')
print(urls[-1])
