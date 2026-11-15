# 행사 DB 원격 백업·복원

Oracle SQLite 전체 사본을 Google Drive 비공개 폴더에 보관합니다. 백업은 자동, 복원은 운영자가 시작합니다.

**운영 연결 완료 (2026-11-15):** Google Drive 인증·업로드·별도 DB 복원·토큰 자동 갱신을 검증하고 Oracle 타이머를 활성화했습니다. 재부팅 자동 시작 등록도 확인했습니다.

## 구성과 보관

- 도구: `/usr/local/lib/bbang-palja-backup/db_backup.py`, 전송 도구: 같은 폴더의 공식 `rclone`. 앱 배포 release와 독립적으로 설치합니다.
- DB 설정: 기존 `/etc/bbang-palja/api.env`의 `DB_PATH`. 백업 설정: `/etc/bbang-palja/backup.env`.
- `bbang-palja-backup.timer`: 부팅 약 2분 후 첫 실행, 이후 5분 간격. 재부팅 뒤 밀린 작업을 한꺼번에 실행하지 않습니다.
- SQLite 온라인 사본 → 무결성·외래키 검사 → 저압축 gzip 묶음 → Drive 업로드·크기/MD5 확인 → 최신 포인터 갱신 → 옛 사본 정리.
- `.tar.gz` 하나에 `database.sqlite3`와 `manifest.json`을 넣습니다. DB SHA-256·사본 시각·운영 코드 SHA를 포함합니다. 계정·주문·예판·재고·지급·세션도 모두 포함됩니다.
- 기본 보관: 최근 12개 + 최근 48개 시간대별 최신 1개. 계속 실행하면 약 1시간의 상세 기록과 약 이틀의 시간별 기록입니다. 정상 정리 후 최대 61개이며 실패 중에는 더 남을 수 있습니다.
- **새 업로드 성공 후에만 정리하고 마지막 정상 사본은 보호합니다.** 서버가 멈추면 정리도 멈춥니다. 고정 기간이 지났다고 Drive에서 자동 만료하지 않습니다.
- 해당 환경의 자동 백업 형식에 맞는 파일만 정리합니다. 오래된 사본은 휴지통에 쌓이지 않도록 영구 삭제합니다. 개인 Drive 전체 휴지통 비우기는 실행하지 않습니다.
- 실패 시 기존 포인터·사본을 유지합니다. 자동 복원·서버 전환은 하지 않습니다. 장애 직전 약 5분 + 처리 시간의 공백은 입금·수기 기록과 대조합니다.

## 인증 범위·부하

실제 발급을 확인한 권한은 **`drive.file`**입니다. 앱이 만들었거나 사용자가 앱에 명시적으로 열어준 파일에 접근하며, 기존 Drive 전체 파일을 읽는 권한은 아닙니다. 같은 rclone 앱으로 이전에 만든 파일도 범위에 포함될 수 있습니다.

`root_folder_id`는 프로그램의 작업 위치를 백업 폴더로 고정하는 설정이며, Google 권한 자체를 폴더 하나로 제한하는 설정은 아닙니다. 공유/공개 권한은 추가하지 않습니다.

인증 파일은 `/var/lib/bbang-palja-backup/gdrive/rclone.conf`에 root 소유 `0600`, 상위 폴더는 `0700`으로 저장합니다. 자동 토큰 갱신을 위해 이 폴더는 쓰기 가능해야 합니다. 토큰·DB를 Git·Pages·채팅에 올리지 않습니다. 서버가 없어져도 Drive 계정으로 사본을 내려받을 수 있습니다.

기존 Drive의 남은 공간을 사용하므로 카드 등록·추가 저장소 구독은 필요하지 않습니다. 공간 부족·인증 철회는 오류로 기록합니다. Google Cloud Storage 버킷은 사용하지 않습니다.

API와 별도 프로세스이며 중복 실행을 건너뜁니다. 서비스 제한은 CPU 20%, 메모리 192MB, 낮은 CPU/디스크 우선순위, 최대 120초입니다. DB 기본 제한은 256MiB, SQLite 사본 생성 제한은 45초입니다. 전송은 하나씩 처리하고 재시도·응답 시간을 제한합니다. Drive의 업로드 직후 파일 조회 지연에도 정해진 횟수만 재조회합니다.

## 로컬 검증

기존 로컬 DB를 초기화하지 않습니다. `DB_PATH`를 실제 로컬 서버와 맞춥니다.

```bash
export DB_PATH="$PWD/data/shared-inventory-preview.sqlite3"
export DATABASE_URL=''
export BACKUP_STATE_DIR="$PWD/data/backup-check-state"
export BACKUP_PREFIX=cambo-delight/local-check
python3 ops/db_backup.py --local-store data/backup-check-store backup
python3 ops/db_backup.py --local-store data/backup-check-store list
python3 ops/db_backup.py status
python3 ops/db_backup.py --local-store data/backup-check-store restore --destination data/restore-check.sqlite3 --api-stopped
python3 -m unittest discover -s tests -p '*backup*.py' -v
```

`--local-store`는 검증용이며 원격 백업이 아닙니다. `--api-stopped`는 **복원 대상 파일**을 사용하는 API·배포·백업 작업을 멈췄음을 뜻합니다. 새 시험 파일이면 그 파일을 사용하는 프로세스가 없어야 합니다. 도구가 서비스를 자동 종료/시작하지는 않습니다.

## Drive 연결과 설치

1. 공식 rclone의 Mac용·Linux ARM64용 릴리스를 다운로드하고 공식 `SHA256SUMS`와 대조합니다. 사용 버전은 `v1.76.0`입니다.
2. 로컬 Google 로그인으로 `cambo-backup` remote를 만듭니다. **`scope=drive.file`**만 요청합니다. 전체 접근 `drive` scope는 도구에서 거부하며 실제 발급 scope도 확인합니다.
3. rclone으로 `cambo-delight-backups` 폴더를 만들고 그 ID를 인증 파일의 `root_folder_id`에 설정합니다. 웹에서 수동 생성한 폴더는 이 제한 권한으로 보이지 않을 수 있습니다.
4. SSH로 인증 파일을 위 서버 보호 경로에 저장합니다. `ops/backup.env.example`을 `/etc/bbang-palja/backup.env`에 root 소유 `0600`으로 저장합니다. 실제 인증 값은 커밋하지 않습니다.
5. 검증한 바이너리와 도구를 설치합니다. 설치 명령은 API·터널을 재시작하거나 타이머를 켜지 않습니다.

```bash
sudo python3 ops/install-backup.py --rclone-binary /tmp/rclone --rclone-sha256 <검증한_실행파일_SHA256>
sudo /usr/bin/python3 /usr/local/lib/bbang-palja-backup/db_backup.py --env-file /etc/bbang-palja/api.env --env-file /etc/bbang-palja/backup.env backup
```

6. 업로드·다른 경로로의 시험 복원을 확인한 뒤 활성화합니다.

```bash
sudo systemctl enable --now bbang-palja-backup.timer
sudo systemctl list-timers bbang-palja-backup.timer
sudo journalctl -u bbang-palja-backup.service -n 30 --no-pager
sudo /usr/bin/python3 /usr/local/lib/bbang-palja-backup/db_backup.py --env-file /etc/bbang-palja/api.env --env-file /etc/bbang-palja/backup.env status
```

`status`는 최신 사본 시각·마지막 성공·오류 종류를 출력합니다. 사본이 15분 넘게 오래되거나 오류가 있으면 exit 1입니다. 메일/메신저 알림은 연결하지 않았습니다. 도구·템플릿을 수정하면 설치 명령을 다시 실행해야 반영됩니다.

## 수동 복원

복구 중 새 기록이 생기거나 옛 사본이 정리되지 않도록 이 프로젝트의 API·배포·백업 작업을 먼저 중지합니다.

```bash
sudo systemctl stop bbang-palja-deploy.timer bbang-palja-deploy.service
sudo systemctl stop bbang-palja-backup.timer bbang-palja-backup.service
sudo systemctl stop bbang-palja-api.service
sudo /usr/bin/python3 /usr/local/lib/bbang-palja-backup/db_backup.py --env-file /etc/bbang-palja/api.env --env-file /etc/bbang-palja/backup.env list
sudo /usr/bin/python3 /usr/local/lib/bbang-palja-backup/db_backup.py --env-file /etc/bbang-palja/api.env --env-file /etc/bbang-palja/backup.env restore --destination /var/lib/bbang-palja/prototype.sqlite3 --replace --api-stopped
```

기본은 `latest`이며, 과거 사본은 `--key 'cambo-delight/production/snapshots/목록의_파일명.tar.gz'`로 고릅니다. 다운로드·SHA-256·SQLite 검사를 먼저 수행합니다. 기존 DB가 있으면 WAL 기록까지 `before-restore/`에 보존하고 저널 정리 후 원자적으로 교체합니다. 검증 실패 시 대상 DB를 교체하지 않습니다. root 실행 시 기존 파일 소유자를 유지합니다.

반환된 `code_commit`에 맞는 코드를 준비한 뒤 API를 시작합니다. 수기 주문·입금·재고 대조 후 타이머를 재개합니다. `before-restore/`는 자동 삭제하지 않습니다.

```bash
sudo systemctl start bbang-palja-api.service
curl -fsS http://127.0.0.1:8000/api/health
# 수기 기록 대조 후
sudo systemctl start bbang-palja-backup.timer
sudo systemctl start bbang-palja-deploy.timer
```

다른 서버에서는 코드·Python·rclone·Drive 인증을 준비하고 `--destination`을 새 DB 경로로 바꿉니다. 새 파일이면 `--replace`는 생략합니다. 서버 설정·SSH 키·OS는 DB 사본에 포함되지 않습니다. 새 DB의 소유자를 API 계정에 맞춥니다. Quick Tunnel 주소가 달라지면 [터널 운영 문서](QUICK_TUNNEL_RUNBOOK.md)에 따라 API 주소를 갱신합니다.

## 검증 기록 (2026-11-15)

- Python 회귀 검사 **195개**, 그중 백업 관련 **33개**와 프론트 검사 **125개**가 통과했습니다. 사용하지 않는 R2 코드·SDK 의존성을 제거하고 Drive 설정·응답 검증을 보완한 결과입니다.
- Oracle 실제 운영 DB 약 1.58MB → 압축 약 144KB. Drive에서 내려받아 별도 경로에 복원한 31개 테이블·DB 무결성을 확인했습니다. 운영 DB는 교체하지 않았습니다.
- 한국 시간 19:44 타이머 자동 백업, 강제 만료 표시 후 토큰 자동 갱신, Google 서버에서 갱신 토큰의 실제 `drive.file` 범위, 인증 파일 `0600`, 기존 API·터널 정상 상태를 확인했습니다.
- 검증 시 운영 앱 SHA는 `143a0292c2ea174493ce0b98c09d673563c63f32`이며 백업 도구 설치 중 앱 release를 변경하지 않았습니다.
- 행사 스키마의 계정·승인 주문·주사위·지급·재고를 복원하고 SQL 덤프 일치·API 재실행을 확인했습니다.
- 잠금·동시 쓰기·용량/시간 제한·손상 파일·업로드/포인터/정리 실패·기존 DB 보존·Drive 인증 범위·중복 이름·조회 지연 재시도를 자동 검증합니다.
- 실제 Drive에서 임시 DB 업로드·크기/체크섬 확인·옛 사본 정리·다운로드·복원을 확인했습니다.
- 합성 주문 10,000건·품목 행 30,000건: DB 약 2.60MB → 압축 약 0.38MB. 개발 Mac의 로컬 백업 약 0.061초, 복원 약 0.025초이며 네트워크·Oracle 자원 제한을 제외한 수치입니다.

백업 Python 코드는 표준 라이브러리만 사용합니다. 설치·전송에는 별도로 검증한 rclone 바이너리를 사용합니다.

공식 문서: [SQLite 백업](https://www.sqlite.org/backup.html) · [Drive 권한](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) · [rclone Drive](https://rclone.org/drive/) · [서버 인증](https://rclone.org/remote_setup/).
