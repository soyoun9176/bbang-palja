#!/usr/bin/env python3
"""Install only the reviewed, fixed-scope deployment controller and timer."""
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
if os.geteuid() != 0:
    raise SystemExit('Run with sudo on Oracle.')
for folder,mode in [('/usr/local/lib/bbang-palja',0o755),('/var/lib/bbang-palja-deploy',0o700),
                    ('/var/backups/bbang-palja',0o700)]:
    Path(folder).mkdir(mode=mode,parents=True,exist_ok=True)
target = Path('/usr/local/lib/bbang-palja/deploy.py')
shutil.copyfile(ROOT/'ops/deploy.py',target)
target.chmod(0o644)
for unit in ('bbang-palja-deploy.service','bbang-palja-deploy.timer'):
    target = Path('/etc/systemd/system')/unit
    shutil.copyfile(ROOT/'ops/systemd'/unit,target)
    target.chmod(0o644)
subprocess.run(['systemd-analyze','verify','/etc/systemd/system/bbang-palja-deploy.service',
                '/etc/systemd/system/bbang-palja-deploy.timer'], check=True)
subprocess.run(['systemctl','daemon-reload'], check=True)
subprocess.run(['systemctl','enable','--now','bbang-palja-deploy.timer'], check=True)
print('Installed reviewed controller. Only bbang-palja-api can be switched/restarted by this controller.')
