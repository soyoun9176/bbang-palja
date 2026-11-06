# 캄보딜라이트 2026-2 판매빵 이벤트 페이지

빵 구매·주사위 이벤트를 위한 모바일 페이지와 담당자 운영 대시보드입니다.

## 1. 서버와 배포

| 구성 | 현재 운영 방식 |
| --- | --- |
| 프론트 | Cloudflare Pages `cambo-delight` · HTML/CSS/JavaScript |
| 백엔드 | Oracle Free Ubuntu 인스턴스 · Python HTTP API |
| 연결 | Cloudflare Quick Tunnel |
| DB | Oracle 서버의 SQLite(WAL). 전화번호 계정 스키마, 로컬·공개 데이터 분리 |
| 자동 배포 | `main` merge → GitHub 검사 → Oracle DB 백업·API 배포 → Pages 공개 |

공개 가안 운영 중: [구매자](https://cambo-delight.pages.dev/) · [관리자](https://cambo-delight.pages.dev/admin/) · [현재 배포 버전](https://cambo-delight.pages.dev/version.json)

현재 공개 데이터는 시연용이며, 입금은 담당자가 직접 확인합니다. [배포·복구](docs/CI_CD.md) · [서버·터널 운영](docs/QUICK_TUNNEL_RUNBOOK.md)

행사 초기화는 품목별 총재고 입력 → 예판 내역 등록 순서로 진행합니다. 현판 가능 수량은 총재고에서 예판 수량을 뺀 값입니다.

## 2. 협업 방법

1. 작업별 브랜치(`feature/작업명`, `fix/작업명`)에서 개발합니다. UI는 `frontend/`, API·DB는 `server/`, 문서는 `docs/`에서 작업합니다.
2. 로컬 확인과 아래 검증을 마친 뒤 PR을 올립니다.
3. 검증된 PR을 `main`에 merge합니다. **merge하면 자동 배포가 즉시 시작되며, 공개 반영까지 수분이 걸립니다.**

로컬 실행: `DEMO_SEED=0 python3 -m server --port 8000` → [구매자](http://localhost:8000/) · [관리자](http://localhost:8000/admin/)

```bash
python3 -m unittest discover -s tests -v
node --test tests/frontend-check.mjs
python3 ops/build-frontend.py
```

### 기존 clone의 DB 다시 세팅

**2026-11-07 전화번호 계정으로 변경했습니다. 기존 DB는 자동 이전하지 않으며 재생성이 필요합니다.** 서버를 종료한 뒤 실행합니다.

```bash
git switch main
git pull --ff-only
python3 ops/reset-db.py --yes
DEMO_SEED=0 python3 -m server --port 8000
```

계정·세션·주문·예판·점수·재고를 비우고 메뉴 13종을 수량 0으로 생성합니다. 기존 DB는 `data/backups/before-reset-*.sqlite3`에 자동 백업합니다. 재고와 예판은 다시 입력합니다. `.env`를 사용했다면 초기화에 `--env-file .env`를 추가하고 서버에도 같은 환경 변수를 적용합니다. `DB_PATH`가 다르면 반드시 기존과 같은 경로를 지정합니다. 명령은 SQLite 전용이며 PostgreSQL은 변경하지 않습니다. 로컬 샘플이 필요할 때만 초기화에 `--demo`를 추가하고 `DEMO_SEED=1`로 실행합니다.

## 3. 기능

- 구매자: 닉네임·전화번호·4자리 PIN 가입, 전화번호·PIN 로그인. 번호는 `010-NNNN-NNNN` 저장, 사용자 화면에는 닉네임만 표시. 현장 구매, 예약한 빵 수령, 주문 내역.
- 비회원: 로그인·가입 화면에서 이름만 입력해 구매. 주문 번호·승인 상태를 같은 기기에서 확인하며 이벤트 주사위는 미지급. 담당자 수기 판매·예약 수령도 계정 없이 처리 가능.
- 프로필: 얼굴·표정·꾸미기, 승인 구매로 빵 머리핀 해제, 15점 보상으로 선글라스 해제, 계정별 저장·순위표 프로필 사진.
- 이벤트: 종류별 주사위·서버 추첨·점수·순위. 5·10·15·20·30점 보상과 캐릭터 성장.
- 판매 담당자: 승인·취소, 수기 현장 판매·예판 수령, 기존 계정 연결, 예판 수령 현황·검색.
- 운영 담당자: 이벤트 물품 지급 승인·취소, 빵·상품·점수 임의 지급, 비회원 물품 지급 기록, 인스타 인증, 공용 재고·변경 이력, 인수인계 메모·시간표.

현판은 빵 1개(도넛은 1세트)당 1개, 예판은 예약 1건당 금액 등급의 주사위 1개를 지급합니다. 우유·두유는 각각 재고를 관리하며 구매 주사위를 지급하지 않습니다. 현판과 랜덤 빵 보상은 같은 재고를 사용합니다.

## 4. 컨셉과 작업 현황

연금술 테마입니다. 구매 화면은 실제 메뉴명을 중심으로, 이벤트는 주사위와 연금술사 성장으로 구성합니다. [메뉴·컨셉](docs/MENU.md) · [화면 구성](docs/DESIGN.md)

**현재 프로젝트는 ChatGPT로 생성·구현한 초안입니다.**

| 상태 (2026-11-07 기준) | 작업 |
| --- | --- |
| 공개 배포 반영 | 전화번호 계정, 캐릭터 프로필, 종류별 주사위·보상 말풍선, 이벤트 지급 승인/취소, 우유·두유 선택, 자동 배포 |
| 공개 배포 반영 | 비회원 구매·수기 판매·예약 수령, 이벤트 임의 지급·담당자 기록 |
| DB 재세팅 | 백업 후 새 DB 생성 명령, 기존 clone 재설정 안내 |
| 문서 정리 완료 | README, DB 구조, 화면·메뉴·배포 운영 문서 |
| 추가 작업 | 실물 빵 사진, 디자인·캐릭터·주사위 애니메이션 확정, 행사 초기 재고·예판 내역 입력 |

운영 규칙: [담당자 인수인계](docs/STAFF_HANDOVER.md)

상세 구조: [DB](docs/DATABASE.md) · [API](server/API.md) · [아키텍처](docs/ARCHITECTURE.md)
