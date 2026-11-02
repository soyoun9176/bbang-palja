# 배포 준비

프론트엔드는 Cloudflare Pages 프로젝트 `bbang-palja`에 Git 연동으로 배포합니다. 공개 주소는 https://bbang-palja.pages.dev 입니다. 가안 API는 Oracle의 전용 systemd 서비스와 Quick Tunnel로 연결합니다. 주소 변경·재시작·백업·실제 행사 전환 절차는 [Quick Tunnel 운영 매뉴얼](QUICK_TUNNEL_RUNBOOK.md)에 정리했습니다.

## 환경 변수

| 변수 | 기본값·의미 |
| --- | --- |
| `APP_ENV` | 미설정 시 `local`; 예제는 `development`, 운영 시 `production` |
| `HOST`, `PORT` | `127.0.0.1`, `8000`; 컨테이너 내부에서는 `0.0.0.0` |
| `STAFF_PASSWORD` | 로컬 기본 `butter2026`; 운영 시 별도 비밀값 필수 |
| `DEMO_SEED` | 로컬 샘플 데이터 생성 여부; 새 DB를 실운영용으로 만들 때 `0` |
| `DB_PATH` | SQLite 파일 위치, 기본 `data/kambodelight.db` |
| `DATABASE_URL` | PostgreSQL 접속 URL; 설정 시 SQLite 대신 사용 |
| `ALLOWED_ORIGINS` | 허용할 프론트엔드 출처를 쉼표로 구분 |

`APP_ENV=production`에서는 기본 담당자 비밀번호와 12자 미만 비밀번호를 거부하고 데모 시딩을 실행하지 않습니다. 기존 데모 데이터는 환경 변수를 바꾼다고 삭제되지 않으므로 운영에는 별도 DB를 사용합니다. `.env`, DB 파일, 백업은 Git에 포함하지 않습니다.

데모를 끈 새 DB에는 기본 빵 목록만 만들고 현판·이벤트 공용 재고·예판·우유 재고는 모두 0으로 시작합니다. 샘플 구매자·예약·판매·시간표는 만들지 않습니다. 실제 상품명·가격 확인과 재고 입력은 행사 전에 완료합니다.

## PostgreSQL

로컬 기본 DB와 운영 DB를 분리합니다. `docker compose up --build`는 테스트용 PostgreSQL과 API를 실행하는 예시이며 공용 인터넷에 그대로 노출하는 구성은 아닙니다. DB 포트는 로컬 루프백에만 바인딩합니다.

서버에서 PostgreSQL을 사용할 때는 `requirements-postgres.txt`를 설치하고 `DATABASE_URL`을 설정합니다. 앱 시작 시 스키마가 준비됩니다. 도메인, DB 비밀번호, 담당자 비밀번호는 환경 변수로 주입하고 저장소에 기록하지 않습니다.

행사 전 예판 등록, 가격과 현판·이벤트 공용 / 예판 재고, 우유 수량, 담당 시간표를 실제 데이터로 확인합니다. 데모 DB를 수정해서 운영하는 것보다 새 운영 DB로 리허설하는 편이 상태 혼동을 줄입니다.

## Oracle 서버의 API

현재 가안에서는 Quick Tunnel이 외부 HTTPS를 처리하고, API는 `127.0.0.1:8000`에서만 받습니다. 서버의 인바운드 80·443·8000 포트는 열지 않습니다. API와 터널은 별도 systemd 서비스이므로 API만 재시작해도 터널 프로세스는 유지됩니다. API 상태와 비밀번호는 코드 체크아웃 밖에 보관합니다.

장기 운영으로 변경한다면 Nginx·Caddy 등의 프록시 또는 고정 터널 구성을 검토합니다. 아래는 별도 운영 DB를 준비할 때 참고할 환경 변수 예시입니다.

실제 비밀값은 서버의 보호된 환경 변수 파일에 저장하며 저장소에는 넣지 않습니다.

```dotenv
APP_ENV=production
HOST=127.0.0.1
PORT=8000
DEMO_SEED=0
STAFF_PASSWORD=<담당자용 별도 비밀번호>
DATABASE_URL=postgresql://<계정>:<비밀번호>@<DB호스트>:5432/kambo
ALLOWED_ORIGINS=https://<프로젝트>.pages.dev,https://<실제프론트도메인>
```

담당자 비밀번호와 운영 계정 정보는 HTTPS 환경에서만 전달합니다. PostgreSQL을 선택하면 API 서버에서만 접근 가능하게 설정합니다. 현재 가안은 SQLite를 사용하며 별도 DB 포트를 공개하지 않습니다.

Python의 내장 HTTP 서버는 프로토타입 실행용입니다. 외부 공개 전에는 요청 크기 제한·타임아웃·속도 제한을 프록시에 설정하고, 운영용 앱 서버 구성과 오류 모니터링을 검토합니다. 4자리 PIN 로그인은 추측 시도 제한이 특히 필요합니다.

## Cloudflare Pages 프론트엔드

프론트엔드는 Python 스크립트로 공개 정적 파일을 만들고 JS·CSS 파일명에 내용 해시를 붙입니다. 별도 번들러 설치는 필요 없습니다. GitHub의 `soyoun9176/bbang-palja` 저장소를 Pages에 연결했으며, 설정은 다음과 같습니다.

| 항목 | 설정 |
| --- | --- |
| 운영 브랜치 | `main`, 자동 배포 활성화 |
| 프레임워크 | `None` |
| 루트 디렉터리 | 저장소 최상위, 입력란은 비움 |
| 빌드 명령 | `python3 ops/pages-build.py` |
| 출력 디렉터리 | `dist` |
| 빌드 감시 경로 | `*` |
| 미리보기 자동 배포 | 비활성화; 테스트 API 준비 후 별도로 연결 |

`main`에 push하면 GitHub Actions가 Python·Node 테스트와 정적 빌드를 검사합니다. Oracle은 성공한 동일 커밋을 배포하고, Pages 빌드는 API의 커밋 확인 후 프론트를 공개합니다. 자세한 절차와 장애 복구는 [자동 배포 문서](CI_CD.md)를 참고합니다. `frontend/config.js`의 Quick Tunnel 주소와 실제 터널 주소가 다르면 연결 오류가 발생합니다.

`ops/set-api-url.py`로 실제 API의 HTTPS 주소를 설정합니다. 가안에서는 `prototype: true`로 테스트 안내를 표시합니다. 이 플래그는 인증 권한과 무관합니다.

```bash
python3 ops/set-api-url.py https://현재주소.trycloudflare.com
```

이 설정은 브라우저에 공개됩니다. API 주소만 넣고 DB URL이나 담당자 비밀번호를 넣지 않습니다. API 서버의 `ALLOWED_ORIGINS`에는 Pages의 **정확한 출처**를 넣습니다. 경로나 마지막 `/` 없이 `https://프로젝트.pages.dev` 형태입니다. 별도 미리보기 도메인을 사용할 경우 해당 출처도 지정해야 합니다.

`frontend/_redirects`의 `/admin / 200`, `/admin/ / 200` 규칙은 주소를 유지하면서 담당자 화면에 루트 HTML을 제공합니다. 기본 담당자 진입 링크는 `/admin/`으로 통일해 초기 배포 때 브라우저에 저장된 `/admin` 이동 캐시와 구분합니다. 대상을 `/index.html`로 지정하면 Pages의 기본 URL 정규화로 `/`에 이동하여 담당자 경로를 잃을 수 있습니다. Pages 배포 후 구매자 페이지와 담당자 페이지를 각각 직접 새로고침하고 API 호출·로그인·CORS를 확인합니다. HTTPS 프론트엔드는 HTTPS API에 연결해야 합니다.

## 데이터 보존과 리허설

행사 전 DB 백업과 복원 리허설을 진행합니다. SQLite는 서버를 정지한 상태에서 DB를 복사하거나 SQLite 백업 기능을 사용합니다. PostgreSQL은 `pg_dump`/`pg_restore`로 별도 보관하고, 백업 파일도 개인정보로 취급합니다.

승인·취소·보상은 재고와 연동되므로 DB를 수기로 일부만 바꾸지 않습니다. 테스트 실패·서버 재시작·중복 클릭·마지막 재고 동시 주문·예판 재조회·우유 소진·보상 소진을 리허설 항목에 포함합니다. 대기 주문 자동 만료는 현재 없으므로 담당자가 수시로 확인하고 취소해야 합니다.
