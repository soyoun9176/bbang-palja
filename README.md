# 캄보딜라이트 · 빵과 주사위

캄보딜라이트 빵 판매를 위한 로컬 실행형 프로토타입입니다. 모바일 구매 화면과 노트북용 담당자 화면을 같은 서버에서 실행합니다. Python 표준 라이브러리와 SQLite만으로 시작할 수 있고, PostgreSQL 연결도 지원합니다.

공개 가안은 [구매자 화면](https://bbang-palja.pages.dev/)과 [담당자 화면](https://bbang-palja.pages.dev/admin)에서 확인합니다. 시연용 데이터이며 실제 결제는 처리하지 않습니다. Oracle API·Quick Tunnel 실행과 주소 변경 시 수동 복구 방법은 [운영 매뉴얼](docs/QUICK_TUNNEL_RUNBOOK.md)에 정리했습니다. 가안 담당자 비밀번호는 저장소에 넣지 않습니다.

## 바로 실행

Python 3.10 이상이 필요합니다. 프로젝트 폴더에서 실행합니다.

```bash
python3 -m server --port 8000
```

- 구매자: [http://localhost:8000](http://localhost:8000)
- 담당자: [http://localhost:8000/admin](http://localhost:8000/admin)
- 모바일 디자인 미리보기: [http://localhost:8000/preview.html](http://localhost:8000/preview.html)
- 데모 구매자: **김소연 / 1234**
- 데모 예판 조회: **김소연 / 01012345678**
- 담당자: 이름 자유 입력 / **butter2026**

첫 실행 시 `data/kambodelight.db`에 샘플 빵·예판·계정·시간표가 생성됩니다. 브라우저를 새로 열거나 서버를 재시작해도 데이터가 유지됩니다. 다른 구매자 계정은 이름과 숫자 네 자리 PIN으로 가입할 수 있습니다. 같은 이름으로 중복 가입할 수 없습니다.

설정을 바꾸려면 `.env.example`을 `.env`로 복사해 환경 변수로 불러옵니다. 서버가 `.env`를 자동으로 읽지는 않습니다.

```bash
cp .env.example .env
set -a
source .env
set +a
python3 -m server
```

## 확인할 수 있는 흐름

1. 구매 화면에서 김소연으로 로그인합니다.
2. 예판을 조회하고 수령 요청을 보냅니다. 담당자 화면에서 내역을 승인하면 구매자에게 빵 수량만큼 주사위가 생깁니다.
3. 현판에서 빵과 수량을 선택해 주문합니다. 이때 재고가 선점되며, 담당자가 승인하면 주사위를 지급하고 취소하면 재고를 복구합니다.
4. 주사위를 굴려 점수와 순위를 확인합니다. 30점마다 이벤트 빵 한 개를 받을 수 있습니다. 추첨 확률은 이벤트 재고 수량에 비례합니다.
5. 담당자 화면에서 수기 판매, 인스타 이벤트, 재고 조정·이력, 메모·인수인계, 담당 시간표를 확인합니다.

담당자의 승인은 현장에서 입금을 직접 확인한 뒤 누르는 방식입니다. 계좌 이체나 결제사의 실제 결제 처리는 연결되어 있지 않습니다. 알림은 화면이 열려 있는 동안 API를 주기적으로 조회해 갱신합니다.

## 파일 구조

```text
frontend/                 구매자·담당자 화면, 빌드 없는 HTML/CSS/JS
server/                   HTTP API, 인증, 재고·주문·이벤트 처리
server/API.md             요청·응답 계약
tests/test_api.py         실제 HTTP 요청과 동시성 검증
docs/ARCHITECTURE.md      데이터 흐름, 재고·트랜잭션 규칙
docs/DEPLOYMENT.md        PostgreSQL·Oracle·Cloudflare 배포 준비
docs/DESIGN.md            디자인팀 전달 사항과 후속 아이디어
```

같은 와이파이의 휴대폰에서 확인하려면 `python3 -m server --host 0.0.0.0 --port 8000`으로 실행하고 `http://맥의내부IP:8000`에 접속합니다. 이 옵션은 로컬 네트워크에서만 사용하세요.

프론트엔드의 API 주소는 `frontend/config.js`의 `window.KAMBO_CONFIG.apiBase`로 지정합니다. 기본값 `''`은 현재 페이지와 같은 출처의 서버를 사용합니다.

## 검증

```bash
python3 -m unittest discover -s tests -v
```

테스트는 임시 SQLite DB와 별도 포트에서 서버를 실행하므로 평소 사용하는 데이터를 변경하지 않습니다. 마지막 재고의 동시 주문, 승인·취소 재시도, 주사위 중복 지급, 권한·소유권, 예판 수령, 보상 재고 등을 검증합니다.

Node.js가 있다면 브라우저 상태 갱신과 재시도 회귀 검사 6개도 실행할 수 있습니다. 재고·랭킹 자동 갱신, 모달 중 도착한 변경 반영, 요청 ID 대체 생성, 통신 오류 후 동일 주문 재시도, 이전 세션 응답 격리를 확인합니다. 앱 실행에는 Node.js가 필요하지 않습니다.

```bash
node --test tests/frontend-check.mjs
```

## PostgreSQL로 로컬 확인

Docker가 설치되어 있다면 다음 명령으로 앱과 PostgreSQL을 함께 실행합니다.

```bash
docker compose up --build
```

접속 주소와 데모 로그인은 기본 실행과 같습니다. 데이터는 Docker의 `postgres_data` 볼륨에 유지됩니다. 실행 중인 8000번 포트 서버가 있다면 먼저 종료해야 합니다. Docker 예제의 DB 비밀번호는 로컬 테스트용입니다.

기존 PostgreSQL을 사용하려면 다음과 같이 실행합니다.

```bash
python3 -m pip install -r requirements-postgres.txt
DATABASE_URL='postgresql://user:password@localhost:5432/kambo' python3 -m server
```

운영 이전의 설정·백업·출처 분리는 [배포 문서](docs/DEPLOYMENT.md)를 참고하세요. 프론트엔드와 API는 한 저장소에서 관리하며, Cloudflare Pages와 Oracle로 나누어 배포할 수 있습니다.

## 현재 범위와 다음 결정

이름+네 자리 PIN과 공용 담당자 비밀번호는 요청하신 행사 운영 방식을 반영합니다. 네 자리 PIN은 강한 인증 수단이 아니므로 외부 운영 전에는 로그인 시도 제한, 개별 담당자 계정, 세션 만료 정책 등을 결정해야 합니다. 동명이인은 현재 가입할 수 없습니다.

서버에는 실제 결제 연동, 문자 인증, 자동 주문 만료·재고 반환, 푸시 알림이 없습니다. 대기 주문은 담당자가 직접 승인하거나 취소합니다. 후속 디자인과 이벤트 확장 항목은 [디자인·기획 문서](docs/DESIGN.md)에 정리했습니다.

## 화면 가안

브라우저에서 확인한 [구매자 데스크톱 화면](docs/screenshots/buyer-desktop.jpg), [모바일 화면](docs/screenshots/buyer-mobile.jpg), [담당자 화면](docs/screenshots/staff-desktop.jpg)을 저장했습니다.

실제 상품명·가격·판매 시간은 확정 전 시연용 구성입니다.
