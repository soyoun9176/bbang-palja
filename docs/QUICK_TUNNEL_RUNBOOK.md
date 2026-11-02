# 이틀 행사 가안 · Quick Tunnel 운영 매뉴얼

구매자는 https://bbang-palja.pages.dev/ 에 접속하고, 담당자는 https://bbang-palja.pages.dev/admin 에 접속합니다. Pages의 정적 JS가 Quick Tunnel의 HTTPS 주소로 Oracle API를 호출합니다. 별도 Worker나 도메인 구매는 사용하지 않습니다.

현재는 **가안 테스트 환경**입니다. 상품·계정·예약·주문·재고는 시연용이며 실제 결제 연동은 없습니다. 샘플 DB를 실제 행사 DB로 사용하지 않습니다.

## 배치 위치

| 항목 | 위치·설정 |
| --- | --- |
| Oracle SSH | `ssh oracle-free` (`ubuntu@158.179.171.144`) |
| 서버 Git 체크아웃 | `/home/ubuntu/projects/bbang-palja` |
| API 실행 코드 | `/opt/bbang-palja/app` |
| 가안 DB | `/var/lib/bbang-palja/prototype.sqlite3` |
| 환경 변수·담당자 비밀번호 | `/etc/bbang-palja/api.env`, root 전용 `0600` |
| API 서비스 | `bbang-palja-api.service` |
| Quick Tunnel 서비스 | `bbang-palja-quick-tunnel.service` |
| API 내부 주소 | `http://127.0.0.1:8000` |
| Quick Tunnel 상태 확인 | `http://127.0.0.1:20001/ready` (서버 내부 전용) |
| Pages API 주소 설정 | `frontend/config.js`의 `apiBase` |
| CORS 허용 출처 | `https://bbang-palja.pages.dev` |

두 서비스는 비특권 DynamicUser로 실행하고 부팅 시 자동 시작합니다. DB와 비밀번호는 Git 및 코드 배포 경로 밖에 보관합니다. 기존 방화벽과 다른 서비스는 변경하지 않습니다. 이전에 만든 `cloudflared-bbang-palja.service` Named Tunnel은 별도로 유지되며 현재 Pages 연결에는 사용하지 않습니다.

## 가안 로그인

- 구매자 샘플: `김소연 / 1234`.
- 담당자: 이름은 자유 입력, 비밀번호는 자동 생성한 별도 값입니다.
- 셋업한 Mac에서는 Git에서 제외된 `data/prototype-access.txt`에 접속 정보를 보관합니다. 이 파일을 커밋하거나 공개하지 않습니다.
- 서버 관리자는 `sudoedit /etc/bbang-palja/api.env`로 담당자 비밀번호를 확인·변경할 수 있습니다. 변경 후 API 서비스만 재시작합니다.

샘플 DB는 오프라인에서 초기화하고 공개 API는 `APP_ENV=production`, `DEMO_SEED=0`으로 실행합니다. `/api/config`는 담당자 비밀번호 힌트를 반환하지 않습니다. 프론트의 `prototype: true`는 화면에 테스트 안내만 표시하며, 인증 권한을 부여하지 않습니다.

## 평소 상태 확인

Oracle에 접속한 뒤 실행합니다.

```bash
cd /home/ubuntu/projects/bbang-palja
sudo systemctl status bbang-palja-api bbang-palja-quick-tunnel --no-pager
curl -fsS http://127.0.0.1:8000/api/health
curl -fsS http://127.0.0.1:20001/ready
sudo python3 ops/quick-tunnel-url.py
```

`/api/health`는 `{"ok":true}`를 반환해야 합니다. URL 확인 스크립트는 현재 실행 중인 터널의 로그만 읽으므로 이전 실행의 만료된 주소를 선택하지 않습니다.

```bash
sudo journalctl -u bbang-palja-api -n 80 --no-pager
sudo journalctl -u bbang-palja-quick-tunnel -n 80 --no-pager
```

## 터널 주소가 바뀌었을 때

Quick Tunnel을 새로 시작하면 `https://임의이름.trycloudflare.com` 주소가 새로 생깁니다. 이 프로젝트는 **주소 자동 갱신 기능을 사용하지 않습니다.** 변경 시 다음 순서로 수동 대응합니다.

1. Oracle에서 `sudo python3 ops/quick-tunnel-url.py`로 현재 주소를 확인합니다.
2. 그 주소의 `/api/health`를 열어 API가 응답하는지 확인합니다.
3. **Mac의 레포 폴더**에서 새 주소를 반영하고 push합니다.

```bash
python3 ops/set-api-url.py https://새주소.trycloudflare.com
git diff -- frontend/config.js
git add frontend/config.js
git commit -m "Update Quick Tunnel API address"
git push origin main
```

4. Cloudflare Pages에서 새 커밋의 배포 성공을 확인합니다.
5. 구매자·담당자 페이지를 새로고침하고 로그인과 재고 조회를 확인합니다. 이미 열려 있던 탭은 이전 주소를 계속 사용하므로 반드시 새로고침합니다.

Pages의 주소는 바뀌지 않습니다. CORS의 허용 출처 역시 Pages 주소이므로 터널 주소가 바뀌었다는 이유만으로 CORS를 변경할 필요는 없습니다. 담당자 비밀번호를 `frontend/config.js`에 넣지 않습니다.

GitHub SSH 인증이 거부되면 Mac에서 `ssh-add --apple-use-keychain ~/.ssh/github_personal`로 개인 키를 등록한 뒤 push합니다. 서버에는 GitHub 개인키를 복사하지 않습니다.

## 재시작과 종료

API만 문제가 있으면 API만 재시작합니다. 이 작업은 Quick Tunnel 서비스를 재시작하지 않으므로 보통 터널 주소를 유지합니다.

```bash
sudo systemctl restart bbang-palja-api
```

터널 자체가 연결되지 않을 때만 재시작하고, 이후 위의 주소 변경 절차를 확인합니다. 서버 재부팅이나 터널 장애 후 자동 재시작 때에도 같은 확인이 필요합니다.

```bash
sudo systemctl restart bbang-palja-quick-tunnel
sudo python3 ops/quick-tunnel-url.py
```

행사 종료 후 공개 접속만 중단하려면 Quick Tunnel을 중지합니다. 다시 시작하면 새 주소를 확인합니다.

```bash
sudo systemctl stop bbang-palja-quick-tunnel
```

행사가 끝나 더 이상 자동 시작하지 않으려면 **이 프로젝트의 두 서비스만** 중지·비활성화합니다. 이 명령은 DB를 삭제하지 않습니다.

```bash
sudo systemctl disable --now bbang-palja-quick-tunnel bbang-palja-api
```

## DB 백업

SQLite는 WAL을 사용하므로 실행 중인 DB 파일 하나만 복사하지 않습니다. 서버에서 아래 백업 API를 사용하면 서비스를 중지하지 않고 일관된 백업을 만들 수 있습니다.

```bash
sudo python3 - <<'PY'
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3

os.umask(0o077)
folder = Path('/var/backups/bbang-palja')
folder.mkdir(mode=0o700, parents=True, exist_ok=True)
target = folder / ('prototype-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.sqlite3')
source = sqlite3.connect('file:/var/lib/bbang-palja/prototype.sqlite3?mode=ro', uri=True)
backup = sqlite3.connect(target)
source.backup(backup)
backup.close()
source.close()
print(target)
PY
```

실제 행사 DB로 전환한 뒤에는 백업 대상 경로도 변경합니다. DB와 백업에는 구매자 정보가 포함될 수 있으므로 공개 저장소·정적 호스팅에 올리지 않습니다.

## 실제 행사 전 전환

1. 가안 DB를 백업하고 `/etc/bbang-palja/api.env`의 `DB_PATH`를 새로운 `/var/lib/bbang-palja/event.sqlite3`로 변경합니다. `APP_ENV=production`, `DEMO_SEED=0`은 유지합니다.
2. API만 재시작합니다. 새 DB는 샘플 구매자·주문·예약 없이 시작하고 재고는 0입니다.
3. 실제 상품·가격·재고·예판을 준비하고 담당자와 리허설합니다. 4자리 PIN 로그인 시도 제한 등 공개 운영 전 점검은 [배포 문서](DEPLOYMENT.md)를 참고합니다.
4. `python3 ops/set-api-url.py https://현재주소.trycloudflare.com --live`로 테스트 안내를 끄고, 변경을 리뷰한 뒤 push합니다. `--live`는 화면 안내만 바꾸며 DB를 변경하지 않습니다.

가안 DB를 초기화하려고 운영 DB를 삭제하거나 설치 스크립트를 무작정 재실행하지 않습니다.

## 설치·코드 갱신 참고

최초 가안 설치는 공식 ARM64 `cloudflared` 설치 후 서버 레포에서 `sudo python3 ops/install-oracle.py --prototype`으로 재현할 수 있습니다. 기존 가안 DB와 비밀번호가 있으면 보존합니다. 운영 DB가 설정된 경우 가안 설치를 거부합니다.

API 코드를 갱신할 때는 레포를 pull한 뒤 코드만 복사하고 API만 재시작합니다. DB·비밀번호·터널 프로세스는 유지합니다.

```bash
cd /home/ubuntu/projects/bbang-palja
git pull --ff-only origin main
sudo python3 ops/install-oracle.py --sync-code-only
sudo systemctl restart bbang-palja-api
```

Pages는 `main`의 `frontend/` 변경에 자동 배포됩니다. `ops/` 변경만으로 API 서버가 자동 배포되지는 않습니다. 로컬 `localhost`·`127.0.0.1`에서는 `config.js`가 같은 출처 API를 사용하므로 평소처럼 `python3 -m server`로 개발할 수 있습니다.

Quick Tunnel은 [공식적으로 테스트·개발용](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)이며, 재생성 시 주소 변경·가동 보장 없음·동시 처리 중인 요청 200개 제한이 있습니다. 200개는 사용자 수가 아니라 아직 응답이 끝나지 않은 요청 수입니다. 행사 전 예상 인원으로 확인하고, 주소가 바뀌면 이 매뉴얼로 복구합니다.
