# 캄보딜라이트 2026-2 판매빵 이벤트 페이지

빵 구매·주사위 이벤트를 위한 모바일 페이지와 담당자 운영 대시보드입니다.

## 1. 서버와 배포

| 구성 | 현재 운영 방식 |
| --- | --- |
| 프론트 | Cloudflare Pages · HTML/CSS/JavaScript |
| 백엔드 | Oracle Free Ubuntu 인스턴스 · Python HTTP API |
| 연결 | Cloudflare Quick Tunnel |
| DB | Oracle 서버의 SQLite(WAL). 현재 스키마 유지, 로컬·공개 데이터 분리 |
| 자동 배포 | `main` merge → GitHub 검사 → Oracle DB 백업·API 배포 → Pages 공개 |

공개 가안 운영 중: [구매자](https://bbang-palja.pages.dev/) · [관리자](https://bbang-palja.pages.dev/admin/) · [현재 배포 버전](https://bbang-palja.pages.dev/version.json)

현재 공개 데이터는 시연용이며, 입금은 담당자가 직접 확인합니다. [배포·복구](docs/CI_CD.md) · [서버·터널 운영](docs/QUICK_TUNNEL_RUNBOOK.md)

행사 초기화는 품목별 총재고 입력 → 예판 내역 등록 순서로 진행합니다. 현판 가능 수량은 총재고에서 예판 수량을 뺀 값입니다.

## 2. 협업 방법

1. 작업별 브랜치(`feature/작업명`, `fix/작업명`)에서 개발합니다. UI는 `frontend/`, API·DB는 `server/`, 문서는 `docs/`에서 작업합니다.
2. 로컬 확인과 아래 검증을 마친 뒤 PR을 올립니다.
3. 검증된 PR을 `main`에 merge합니다. **merge하면 자동 배포가 즉시 시작되며, 공개 반영까지 수분이 걸립니다.**

로컬 실행: `python3 -m server --port 8000` → [구매자](http://localhost:8000/) · [관리자](http://localhost:8000/admin/)

```bash
python3 -m unittest discover -s tests -v
node --test tests/frontend-check.mjs
python3 ops/build-frontend.py
```

## 3. 기능

- 구매자: 이름·4자리 PIN 가입/로그인, 현장 구매, 예약한 빵 수령, 주문 내역.
- 이벤트: 주사위·점수·순위를 한 페이지에 표시. 10점마다 랜덤 빵 보상과 캐릭터 성장, 캐릭터는 50점까지.
- 판매 담당자: 승인·취소, 수기 현장 판매·예판 수령, 기존 계정 연결, 예판 수령 현황·검색.
- 운영 담당자: 공용 재고·변경 이력, 인스타 인증과 우유·주사위 선택 지급, 인수인계 메모·시간표.

빵 1개(도넛은 1세트)당 주사위 1개를 지급합니다. 우유는 주사위를 지급하지 않습니다. 현판과 랜덤 빵 보상은 같은 재고를 사용합니다.

## 4. 컨셉과 작업 현황

연금술 테마입니다. 구매 화면은 실제 메뉴명을 중심으로, 이벤트는 주사위와 연금술사 성장으로 구성합니다. [메뉴·컨셉](docs/MENU.md) · [화면 구성](docs/DESIGN.md)

**현재 프로젝트는 ChatGPT로 생성·구현한 초안입니다.**

| 상태 (2026-11-03 기준) | 작업 |
| --- | --- |
| 공개 배포 반영 | 구매·이벤트·관리자 기능, 우유 통합, 예판 계정 연결·수령 현황·검색, 자동 배포 |
| 문서 정리 완료 | README, DB 구조, 화면·메뉴·배포 운영 문서 |
| 추가 작업 | 실물 빵 사진, 디자인·캐릭터·주사위 애니메이션 확정, 행사 초기 재고·예판 내역 입력 |

상세 구조: [DB](docs/DATABASE.md) · [API](server/API.md) · [아키텍처](docs/ARCHITECTURE.md)
