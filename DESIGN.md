# officeclaw UI Design Specification

## 1. 제품 개요

**officeclaw**는 기업 ECM 동기화 폴더를 사용자 PC에서 로컬로 읽고 색인해, 문서를 검색 가능한 지식 레이어로 준비하는 데스크톱 앱이다.

M1의 핵심 경험은 다음과 같다.

- SharePoint, OneDrive for Business, 파일 서버, NetDrive 등으로 로컬에 동기화된 ECM 폴더 등록
- 로컬 문서 읽기 및 색인
- Markdown 변환 및 검색 인덱스 생성
- 검색 테스트를 통한 retrieval 품질 확인
- 지정 사용자만 Eval 기능 접근

## 2. 디자인 컨셉

### 핵심 메시지

보안 위협 탐지가 아니라 다음 메시지에 집중한다.

> 회사 문서를 검색 가능한 지식으로 준비합니다.

### UX 톤

- 친숙한 진행률, 작업 기록, 오류 리포트 구조 사용
- “위협”, “감염”, “치료” 같은 보안 용어는 사용하지 않음
- “빠른 색인”, “문서 읽기”, “검색 인덱스 생성”, “검색 준비 완료” 같은 문구 사용
- 사용자는 “내 PC의 문서를 로컬에서 읽고 검색 가능하게 만드는 앱”으로 이해해야 함

## 3. 정보 구조

좌측 사이드바 기준 IA는 다음과 같다.

1. 상태
2. 폴더
3. 작업 기록
4. 검색 테스트
5. Eval
6. 설정

### Eval 접근 정책

Eval은 일반 사용자에게 항상 노출되지만, 권한 상태에 따라 다르게 표현한다.

#### 권한 없는 사용자

- 사이드바: `Eval` + lock icon + `권한 필요` 또는 `특정 사용자` badge
- 클릭 시 접근 제한 화면 표시
- CTA: `권한 요청`, `홈으로 이동`

#### 권한 있는 사용자

- 사이드바: `Eval` + lock icon + `허용 사용자` badge
- 상단 헤더: `평가 권한` badge 표시
- Eval 리포트 화면 접근 가능

## 4. 공통 레이아웃

### Desktop Window

- Desktop app window chrome 사용
- 상단 title bar에 앱 이름 `officeclaw`
- 우측 상단 window controls 표시

### Top Header

구성:

- 좌측: officeclaw 로고 및 앱명
- 중앙/우측: 서비스 상태
  - green dot
  - `서비스 정상`
  - `officeclaw 서비스가 정상적으로 실행 중입니다.`
- 우측:
  - Help icon
  - 사용자 avatar
  - 사용자명
  - dropdown chevron
  - 권한이 있는 경우 `평가 권한` badge

### Bottom Status Bar

로그인 후 모든 화면에 공통으로 표시되는 하단 상태줄이다.

목적:

- 페이지별 카드 영역을 늘리지 않고, 전체 색인 상태를 한 줄로 반복 확인시킨다.
- 상태 화면뿐 아니라 폴더, 작업 기록, 검색 테스트, Eval, 설정에서도 현재 인덱싱 상태를 유지해서 보여준다.
- 큰 카드나 장식 밴드가 아니라 44px 내외의 얇은 shell chrome으로 취급한다.

구성:

- 상태 chip: `색인 최신` / `인덱싱 중` / `확인 필요` / `오류 있음` / `폴더 없음`
- 감시 범위: `N개 폴더 감시 중`
- 색인 규모: `문서 N개 / 블록 N개`
- 신선도: `마지막 업데이트 오늘 07:16`
- 로컬 저장 안내: `PC 내부에만 저장`
- 액션: `상세 보기 →`로 작업 기록 화면 이동

시각 규칙:

- 상단 헤더와 같은 공통 shell 레벨에 둔다.
- 전체 화면 하단에 고정된 높이로 배치한다.
- 배경은 `paper` 계열, 상단 1px border, 작은 상태 chip만 색을 사용한다.
- 페이지 컨텐츠보다 시각 우선순위를 낮게 유지한다.

### Sidebar

폭은 약 240px 기준.

구성:

- 로고 영역
- 메뉴 목록
- 하단 엔진 상태 카드

하단 상태 카드 문구:

- `인덱싱 엔진 정상`
- `버전 1.3.0`
- `업데이트 확인`

## 5. Visual Style

### 색상

| 용도 | 색상 방향 |
|---|---|
| Primary | Blue 계열 |
| Success | Green / Teal |
| Warning | Orange |
| Error | Red |
| Background | #F7F9FC 계열의 매우 연한 회색 |
| Card | White |
| Border | #E5EAF1 계열 |
| Text Primary | Navy / Charcoal |
| Text Secondary | Gray |

### 형태

- Card 기반 레이아웃
- 12~16px rounded corner
- 약한 shadow
- 충분한 white space
- 테이블은 row hover 또는 selected state 사용
- 상태 chip은 pill 형태 사용

### 아이콘

권장 아이콘 의미:

- 상태: home
- 폴더: folder
- 작업 기록: clock/history
- 검색 테스트: search
- Eval: lock
- 설정: gear
- 문서: file/document
- 블록: stacked layers
- 오류: warning triangle
- 성공: check circle
- 진행 중: spinner/progress circle

## 6. 공통 문구 가이드

기술 용어는 사용자 친화적으로 변환한다.

| 내부 용어 | UI 문구 |
|---|---|
| Indexing | 문서를 검색 가능한 상태로 준비 |
| Markdown extraction | 문서 내용을 읽는 중 / Markdown 변환 |
| SQLite FTS/BM25 | 로컬 검색 인덱스 |
| LLM-Wiki | 지식 지도 |
| Source block | 검색 근거 |
| Eval harness | 품질 평가 |
| Placeholder file | 온라인 전용 파일 |
| Reconcile | 변경 사항 다시 확인 |

## 7. 주요 상태 표현

| 상태 | Badge 문구 | 색상 |
|---|---|---|
| Ready | 준비 완료 / 검색 준비 완료 | Green |
| Indexing | 인덱싱 중 | Blue |
| Warning | 경고 / 확인 필요 | Orange |
| Error | 오류 / 색인 실패 | Red |
| Paused | 일시정지 | Gray |
| Skipped | 건너뜀 | Orange or Gray |

## 8. 온라인 전용 파일 안내

OneDrive Files On-Demand, SharePoint placeholder, NetDrive 캐시 파일 등 로컬에 실제 내용이 없는 파일은 기본적으로 인덱싱하지 않는다.

공통 안내 문구:

> 온라인 전용 파일은 현재 인덱싱에서 건너뛰어질 수 있습니다.  
> 중요한 문서를 빠짐없이 인덱싱하려면 파일을 “항상 이 장치에 유지”로 설정해 주세요.

## 9. 권한 및 보안 메시지

M1 기준 데이터는 로컬에만 저장된다.

권장 보안 문구:

> 문서 내용과 검색 인덱스는 사용자 PC에만 저장됩니다.

Eval 관련 문구:

> Eval은 품질 검증과 성능 측정을 위한 고급 기능입니다. 관리자 또는 평가 권한이 있는 사용자에게만 제공됩니다.

## 10. 화면 목록

이 디자인 스펙에 포함되는 화면:

1. `screen-01-status.md` — 상태 대시보드
2. `screen-02-folders.md` — 폴더 관리
3. `screen-04-scan-history.md` — 작업 기록 / 검색 준비 결과
4. `screen-05-search-test.md` — 검색 테스트
5. `screen-06-eval-report-authorized.md` — Eval 리포트, 권한 있음
6. `screen-07-eval-restricted.md` — Eval 접근 제한, 권한 없음
