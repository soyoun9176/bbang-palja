# 자동 배포 · GitHub → Oracle → Cloudflare Pages

변경은 로컬에서 묶어 확인하고 `main`에 push합니다. PR에서는 검사만 실행하며 운영 배포는 하지 않습니다. PR 병합이나 `main` push는 실제 공개 배포를 시작하므로 검토한 변경만 반영합니다.

```text
local changes → commit/push main
                  ├─ GitHub Actions: Python tests + Node tests + static build
                  └─ Pages build: same tests → wait for matching API commit
                                ↑
Oracle timer (every 3 min) → main + CI success → unprivileged tests
                          → SQLite backup → release switch → API health
                                                    ↓
                              Pages publishes versioned JS/CSS
```

## 활성 설정

- GitHub 검사: `.github/workflows/ci.yml` (`Verify release`). 공개 저장소를 읽고 실행하며 토큰·서버 개인키·Cloudflare API 키를 저장하지 않습니다. 쓰기 권한은 없습니다.
- Oracle 검사 타이머: `bbang-palja-deploy.timer`. GitHub 공개 API로 `main` 커밋과 해당 커밋의 성공한 `push` 검사만 확인합니다. PR·fork·실패·취소·진행 중인 검사는 배포하지 않습니다. GitHub나 네트워크가 응답하지 않으면 현재 서비스는 계속 실행됩니다.
- 제어기: `/usr/local/lib/bbang-palja/deploy.py`, root 소유. 저장소 코드와 테스트는 `nobody`로 실행하고 운영 환경 변수는 전달하지 않습니다. 서비스의 파일 쓰기 범위는 이 프로젝트의 코드·DB·백업·배포 상태 경로로 제한합니다.
- Release: `/opt/bbang-palja/releases/<40자리 SHA>`; `/opt/bbang-palja/app` 링크가 현재 버전을 가리킵니다. 기존 폴더는 최초 전환 때 `bootstrap-<시각>`으로 보존합니다.
- DB: `/etc/bbang-palja/api.env`의 기존 `DB_PATH`를 유지합니다. 배포 전 SQLite 온라인 백업과 `integrity_check`를 실행하며 `/var/backups/bbang-palja/before-deploy-*.sqlite3`에 root 전용으로 저장합니다. 기존 계정·주문·재고·담당자 비밀번호를 초기화하지 않습니다.
- Pages: 빌드 `python3 ops/pages-build.py`, 출력 `dist`, 감시 경로 `*`, 운영 브랜치 `main`. 검사 후 Quick Tunnel API의 `/api/health.commit`이 `CF_PAGES_COMMIT_SHA`와 같아질 때까지 최대 9분 기다립니다. 확인하지 못하면 기존 프론트 배포를 유지합니다.
- 빌드된 JS·CSS·공개 config는 내용 해시가 붙은 `/build/` 파일을 사용합니다. HTML(`/`, `/admin`, `/admin/`)과 `version.json`은 `no-store`로 응답하고, 관리자 JS import도 함께 버전 처리합니다. 배포마다 수동으로 쿼리 버전을 수정하지 않습니다.
- Quick Tunnel은 API 코드 배포 시 재시작하지 않습니다. 터널 주소 변경은 기존 [수동 복구 절차](QUICK_TUNNEL_RUNBOOK.md)를 따릅니다.

평소에는 몇 분 내 반영됩니다. GitHub/Cloudflare 대기열이나 장애가 있으면 늦어질 수 있습니다. 새 기능과 API를 서로 호환되게 유지해야 하며, API를 먼저 갱신하는 짧은 구간에도 이전 프론트가 열려 있을 수 있습니다.

## 상태 확인

```bash
# Mac
git push origin main
# GitHub → Actions → Verify release 에서 성공 확인

# Oracle
sudo systemctl list-timers bbang-palja-deploy.timer
sudo journalctl -u bbang-palja-deploy -n 100 --no-pager
sudo cat /var/lib/bbang-palja-deploy/state.json
curl -fsS http://127.0.0.1:8000/api/health
```

공개 프론트 버전은 `https://bbang-palja.pages.dev/version.json`에서 확인합니다. 해당 `commit`과 API의 `commit`이 같아야 합니다. 실제 실행 코드는 버전별 release 폴더이며 `/home/ubuntu/projects/bbang-palja`는 관리 참고용 체크아웃입니다.

타이머가 다음 확인 시각을 기다리는 중이라면 아래 명령으로 즉시 확인할 수 있습니다. CI를 우회하지 않습니다.

```bash
sudo systemctl start bbang-palja-deploy.service
```

## 실패와 복구

배포 전 테스트나 백업에 실패하면 실행 중인 코드를 바꾸지 않습니다. 새 API가 정상 응답하지 않으면 이전 코드 링크로 돌아가 API만 재시작합니다. 자동 복구는 **DB를 과거 백업으로 되돌리지 않습니다**. 배포 중 발생한 주문을 잃지 않기 위해서입니다. DB 마이그레이션이 있는 변경은 이전 코드와 호환되는 방식으로 만들고, 필요 시 백업 복원은 별도 검토합니다. 이번 공용 재고 전환의 이전 코드는 별도 이벤트 재고를 사용하므로 과거 코드로 수동 복구할 경우 운영을 멈추고 재고 구분부터 확인합니다.

실패한 동일 커밋은 반복 배포하지 않고 `state.json`에 기록합니다. 원인을 확인하고 수정 커밋을 push하거나, 일시 장애가 해소된 뒤 다음처럼 명시적으로 재시도합니다.

```bash
sudo systemctl stop bbang-palja-deploy.timer
sudo python3 /usr/local/lib/bbang-palja/deploy.py --retry
sudo systemctl start bbang-palja-deploy.timer
```

안정 버전으로 돌아가려면 수정/되돌림 커밋을 `main`에 push하는 방법을 우선 사용합니다. 직접 링크를 바꾸는 긴급 조치를 했다면 타이머도 중지해야 다음 확인에서 최신 `main`으로 되돌아가지 않습니다. release와 DB 백업은 자동 삭제하지 않습니다.

제어기와 서비스 템플릿은 자동으로 자기 자신을 교체하지 않습니다. 변경 시 검토한 서버 체크아웃에서 아래 설치를 다시 실행합니다. 기존 DB·환경 변수·터널 서비스는 변경하지 않습니다.

```bash
cd /home/ubuntu/projects/bbang-palja
git pull --ff-only origin main
sudo python3 ops/install-autodeploy.py
```

현재 자동 백업은 SQLite용입니다. PostgreSQL로 전환하면 제어기가 배포를 거부하므로 먼저 `pg_dump` 백업·복구 절차를 구현해야 합니다. 저장소를 비공개로 전환해도 현재 공개 API 확인이 실패하므로 읽기 인증을 별도로 설계해야 합니다.

관련 공식 문서: [GitHub workflow runs API](https://docs.github.com/en/rest/actions/workflow-runs), [Pages 빌드 설정](https://developers.cloudflare.com/pages/configuration/build-configuration/).

## 전화번호 계정 DB 재생성 (2026-11-07)

이 변경은 구 DB 자동 이전을 하지 않습니다. 기존 스키마에서는 API 초기화가 실패하므로 운영은 배포 타이머 중지 → CI 확인·새 체크아웃 준비 → 해당 API 중지 → `sudo python3 ops/reset-db.py --yes --env-file /etc/bbang-palja/api.env --backup-dir /var/backups/bbang-palja` → 새 release 배포 → API/Pages SHA 확인 → 타이머 재개 순서로 전환합니다. 다른 서비스와 터널은 중지하지 않습니다. 백업은 보관하고, 이전 코드로 복구할 때는 해당 스키마 백업도 함께 검토합니다. 개발용 기존 clone은 README 절차를 따릅니다. 이후 일반 배포는 DB를 다시 초기화하지 않습니다.
