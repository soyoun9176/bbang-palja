#!/usr/bin/env python3
"""Install only this project's backup tool and disabled systemd timer on Oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TOOL = Path('/usr/local/lib/bbang-palja-backup')
STATE = Path('/var/lib/bbang-palja-backup')
SYSTEMD = Path('/etc/systemd/system')


def install_file(source, destination, mode=0o644):
    descriptor, name = tempfile.mkstemp(prefix='.install-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(source.read_bytes())
            output.flush()
            os.fsync(output.fileno())
            os.fchmod(output.fileno(), mode)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rclone-binary', type=Path, help='Official Linux rclone binary verified with release SHA256SUMS')
    parser.add_argument('--rclone-sha256', help='Expected SHA-256 of the rclone executable')
    args = parser.parse_args()
    if os.geteuid() != 0 or not Path('/run/systemd/system').is_dir():
        parser.error('Oracle의 systemd 서버에서 sudo로 실행하세요. 로컬 서비스는 변경하지 않습니다.')
    if not Path('/etc/bbang-palja/api.env').is_file():
        parser.error('기존 프로젝트 api.env가 없습니다. 다른 서버에는 설치하지 않습니다.')
    TOOL.mkdir(mode=0o755, parents=True, exist_ok=True)
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE.chmod(0o700)
    if args.rclone_binary:
        actual = hashlib.sha256(args.rclone_binary.read_bytes()).hexdigest()
        if not args.rclone_sha256 or actual != args.rclone_sha256:
            parser.error('rclone 바이너리 체크섬이 일치하지 않습니다.')
        install_file(args.rclone_binary, TOOL / 'rclone', mode=0o755)
    if not (TOOL / 'rclone').is_file():
        parser.error('공식 체크섬을 검증한 Linux rclone 바이너리를 지정하세요.')
    subprocess.run([str(TOOL / 'rclone'), 'version'], check=True, timeout=15)
    install_file(ROOT / 'ops/db_backup.py', TOOL / 'db_backup.py')
    for name in ('bbang-palja-backup.service', 'bbang-palja-backup.timer'):
        install_file(ROOT / 'ops/systemd' / name, SYSTEMD / name)
    subprocess.run(['systemd-analyze', 'verify', str(SYSTEMD / 'bbang-palja-backup.service'),
                    str(SYSTEMD / 'bbang-palja-backup.timer')], check=True, timeout=30)
    subprocess.run(['systemctl', 'daemon-reload'], check=True, timeout=30)
    print(json.dumps({'installed': str(TOOL / 'db_backup.py'),
                      'sha256': hashlib.sha256((TOOL / 'db_backup.py').read_bytes()).hexdigest(),
                      'timer_started_by_installer': False, 'api_restarted': False}))


if __name__ == '__main__':
    main()
