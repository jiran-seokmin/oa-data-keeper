# TASKS — DataKeeper 접근제어 챗 서비스 전환

> 상위 문서: `docs/PRD-chat-service.md` · 기준: `docs/CONCEPT.md`, 발표 슬라이드
> 작업 방식: 각 작업은 워크트리 단위 (`git worktree add .worktrees/<작업명> -b <브랜치>` → 작업·커밋 → main에서 `git merge --no-ff`).
> 규모 표기: S(~1h) / M(~반나절) / L(~하루). 우선순위: P0(무-LLM 조회, 데모 필수) / P1(LLM 답변, 더 나아간 목표) / P2(시간 남으면).

범례: `[ ]` 미착수 · `[~]` 진행 · `[x]` 완료

> **구현 현황 (2026-07-09):** Phase A~D + G3 완료·main 머지(커밋 `76bff0f`). 무-LLM 접근제어 검색 챗 동작.
> 실행: `python -m app.seed_db --reset` → `uvicorn app.server:app --port 8000` → 브라우저에서 페르소나 전환·검색.
> 검증: `python tests/test_engine.py`, `python tests/test_retrieval.py` 통과. Playwright로 C2 마스킹·C3 노출제한 렌더 확인.
> 남은 것: **Phase E(LLM 답변 레이어 · P1)**, Phase F(뷰어/매트릭스/감사로그 · P2).

**아키텍처 요약 — 접근제어 RAG 2단계:**
`질문 → [1단계] 키워드 검색 + engine.decide() 접근 필터(A4 제외) + 등급별 렌더 → [2단계] 접근제어 컨텍스트 + 질문 → LLM 답변` · 각 단계 결과에 판정 근거 부착. 접근 제어는 항상 LLM보다 먼저 일어난다.

---

## Phase A — 데이터 계층 (SQLite 직접 시딩, samples만) · P0

> 방침: **DB에는 `data/samples/*.md` 4종만** 넣는다. `data/seed/`·`labels.json`·`sections.json`은 건드리지 않는다.
> **중간 산출물(labels.json→sections.json) 없이 `app/seed_db.py` 하나가 DB를 직접 채운다.**

### A1. samples 등급 시드 작성 — P0 · M
- [ ] `split_sections()`를 `data/samples/*.md`에 먼저 돌려 실제 섹션 `id = <stem>#<i>`·title·text 확보 (손으로 인덱싱 금지 — 불일치 시 조용히 D4 격리)
- [ ] Claude(개발단계) 분석으로 섹션 id별 등급 시드 초안 작성: security_level·confidence·keywords·departments·summary_generalized·entities(**text/type만, placeholder 제외**)
- [ ] 발표 슬라이드 등급표와 대조·검토 후 `app/seed_db.py`의 `GRADES` 딕셔너리로 커밋 (별도 JSON 없음 — 이 파이썬 시드가 유일한 원천)
- 산출물: `app/seed_db.py`의 `GRADES`
- 검증: PRD §10 등급 배치 초안 반영 (인수검토=D4, 보상=D4 등)
- 의존성: 없음 · **런타임 LLM 아님 — 커밋되는 정적 시드**

### A2. SQLite 스키마 + 접속 헬퍼 — P0 · S
- [ ] PRD §6 스키마로 `data/schema.sql` 작성 (documents/sections/entities/personas)
- [ ] `app/db.py`: DB 연결·초기화 헬퍼 (`get_conn()`, `init_db()`, `--reset` 지원)
- 산출물: `data/schema.sql`, `app/db.py`
- 의존성: 없음 (A1과 병행 가능)

### A3. 직접 시딩 스크립트 (seed_db.py) — P0 · M
- [ ] `app/seed_db.py`: `split_sections()`(samples 파싱) → `GRADES` 병합(라벨 없으면 D4 격리) → `assign_placeholders()`(코퍼스 전역 일관) → 스키마 생성 → documents/sections/entities에 **직접 INSERT**
- [ ] `app/personas.yaml` → `personas` 테이블 시딩
- [ ] `python -m app.seed_db [--reset]` idempotent 실행, 미매칭 섹션 경고 출력
- [ ] `ingest.py`의 `split_sections`/`assign_placeholders`는 import 재사용(중복 구현 금지), 대상 디렉터리만 `data/samples`
- 산출물: 생성되는 `datakeeper.db`, 재생성 명령
- 검증: `SELECT count(*)` 섹션 수, 엔티티 placeholder 일관성, 미매칭 0건
- 의존성: A1, A2

### A4. DB 접근 계층 (store.py) — P0 · M
- [ ] `app/store.py`: `load_sections()`, `load_personas()`, `load_documents()`, `sections_for_doc(doc)`
- [ ] 반환 dict가 **기존 `sections.json` 항목과 동일 키 스키마**를 갖도록 보장 (engine/pipeline 무수정 재사용의 핵심)
- [ ] 외부 채널용 코스 메타데이터 필터(`WHERE security_level=0`) 옵션 제공
- 산출물: `app/store.py`
- 의존성: A2, A3

---

## Phase B — 검색·조회 (1단계, 무-LLM) · P0

### B1. 접근제어 키워드 검색 — P0 · M
- [ ] `app/retrieval.py`: `search(question, persona, policy, purpose) -> results[]`
- [ ] **순서 강제(유출 방지, PRD §7)**: 후보 로드 → `engine.decide()` 접근 필터(**A4 제거**) → 등급별 렌더(A0/A1/A2/A3) → 렌더된 텍스트+제목+keywords에 키워드 매칭
- [ ] 각 result에 판정 근거(id/title/security_level/mode/mode_name/gap/reasons) + `rendered` 텍스트 포함
- [ ] 매칭 0건 시 "권한 내 관련 정보 없음" 처리
- 산출물: `app/retrieval.py`
- 의존성: A4

### B2. 렌더 헬퍼 공용화 — P0 · S
- [ ] A모드별 렌더(원문/배경전용/요약/마스킹)를 `pipeline.render_block`/UI `masked_html`과 중복 없이 공유하도록 정리 (마스킹은 긴 엔티티부터 치환 규칙 유지)
- 산출물: 공용 렌더 함수
- 의존성: B1

### B3. 검색 유출·판정 회귀 테스트 — P0 · S
- [ ] `tests/test_engine.py` 실행해 판정 불변 확인 (JSON→DB 전환 무영향)
- [ ] 유출 테스트 추가: C0가 A4 섹션 키워드 검색 시 0건, C2가 마스킹된 원문 엔티티로 검색 시 0건 (PRD §7 예시)
- [ ] 대표 시나리오(PRD §4) 검색 스냅샷
- 산출물: 통과하는 테스트
- 의존성: B1

---

## Phase C — FastAPI 백엔드 · P0

### C1. FastAPI 스캐폴드 — P0 · S
- [ ] `app/server.py`: FastAPI 앱, CORS, 정적 파일(app/web) 서빙
- [ ] `requirements.txt`에 `fastapi`, `uvicorn` 추가, 실행 명령 문서화(`uvicorn app.server:app --reload`)
- 산출물: 뜨는 서버
- 의존성: A4

### C2. 조회 API — P0 · S
- [ ] `GET /api/personas`
- [ ] `GET /api/documents?persona_id=` (lock_state: 전 섹션 A4=locked, 일부=partial, 그 외 open)
- 산출물: 동작하는 엔드포인트
- 의존성: C1, A4

### C3. 검색 API — P0 · M
- [ ] `POST /api/search {persona_id, question, purpose}` → `retrieval.search()` → `{results, persona}`
- [ ] 외부 채널/미분류 default-deny 경로 확인
- 산출물: **P0 핵심 엔드포인트 (무-LLM)**
- 의존성: C1, B1

---

## Phase D — 프론트엔드 (경량 HTML/JS) · P0

### D1. 페이지 골격 + 페르소나 셀렉터 — P0 · S
- [ ] `app/web/index.html`, `style.css`, `app.js`
- [ ] 상단 페르소나 드롭다운(`/api/personas`) + "판단/집계(A1 완화)" 토글, 세션 상태 관리
- 산출물: 페르소나 전환 UI
- 의존성: C2

### D2. 검색 챗 UI + 판정 근거 — P0 · M
- [ ] 질문 입력 → 사용자 버블 / 응답 버블에 조회된 섹션 카드 리스트(A모드별 렌더: 원문/요약카드/마스킹 하이라이트/배경전용 배지)
- [ ] 응답 하단 접이식 "판정 근거" 패널(D배지·A모드·gap·사유)
- [ ] `/api/search` 연동, 매칭 0건 안내
- 산출물: **동작하는 P0 조회 챗 (데모 완결)**
- 의존성: D1, C3

### D3. 스타일 정리 — P0 · S
- [ ] 모드 색상 팔레트(A0 초록 … A4 회색) 기존 UI와 통일, 반응형 최소 대응
- 산출물: 데모 가능한 외형
- 의존성: D2

---

## Phase E — LLM 답변 레이어 (2단계) · P1 (더 나아간 목표)

### E1. pipeline 소스를 DB·검색결과로 전환 — P1 · M
- [ ] `app/pipeline.py`의 `load_sections`/`load_personas`가 `store.py` 사용하도록 교체 (policy는 YAML 유지)
- [ ] 컨텍스트를 전 섹션이 아니라 **B1 검색 결과(접근제어된 관련 섹션)** 로 조립하도록 연결
- [ ] `engine.py`는 변경 금지
- 산출물: 검색 기반 `pipeline.answer()`
- 의존성: B1, A4

### E2. 챗 API (LLM) — P1 · M
- [ ] `POST /api/chat {persona_id, question, purpose}` → `pipeline.answer()` → `{answer, used_sections, guard, persona}`
- [ ] `ANTHROPIC_API_KEY` 없거나 LLM 오류 시 503
- [ ] 출력 가드(유출 스캔·재생성·차단) 동작 확인
- 산출물: LLM 답변 엔드포인트
- 의존성: E1, C1

### E3. FE 답변 모드 + 자동 폴백 — P1 · M
- [ ] FE가 우선 `/api/chat` 시도 → 503(키 없음/오류)이면 `/api/search`로 폴백하고 "조회 모드" 안내
- [ ] LLM 답변 + 판정 근거 패널 + 출력가드 상태 배지
- 산출물: P1/P0 자동 전환 챗
- 의존성: E2, D2

---

## Phase F — 확장 · P2 (시간 남으면)

### F1. 문서 뷰어 웹 이식 — P2 · M
- [ ] `GET /api/documents/{doc}?persona_id=&purpose=` (렌더된 섹션+decision)
- [ ] Streamlit `render_section` 규칙(원문/블러+배지/요약카드/마스킹 하이라이트/잠금) 웹 이식
- 의존성: C1, A4, B2

### F2. 판정 매트릭스 뷰 — P2 · S
- [ ] `GET /api/matrix` + 섹션×페르소나 히트맵
- 의존성: F1

### F3. 감사 로그 — P2 · M
- [ ] 질의/열람 로그 테이블 + `GET /api/audit` + 화면 (누가·무엇을·어떤 모드로)
- 의존성: C3

### F4. Streamlit UI 정리 — P2 · S
- [ ] 기존 `app/ui.py`를 DB 소스로 전환하거나 웹앱으로 대체 후 유지/폐기 결정
- 의존성: A4

---

## Phase G — 리허설 · P0

### G1. 전수 검증 — P0 · S
- [ ] 페르소나 5종 × 대표 질의 3종(PRD §4) = 15개 조회 결과 사전 확인, 어색한 판정은 A1 라벨 조정
- [ ] 유출 방지 케이스(C0 A4 검색 0건, C2 마스킹 엔티티 검색 0건) 재현
- [ ] (P1 켜졌으면) 출력 가드 발동 시나리오 1개 재현
- 의존성: D2 (P1이면 E3)

### G2. 데모 대본 + 백업 — P0 · S
- [ ] 데모 순서 대본화(같은 질문 페르소나 순회)
- [ ] API 장애 대비: P0 조회 모드를 기본 시연 경로로, P1은 "가능하면" 시연. 응답 캐시/스크린샷 백업
- 의존성: G1

---

## 크리티컬 패스 (P0 최단 경로 — 무-LLM으로 데모 완결)

```
A1 ─┐
A2 ─┼─► A3 ─► A4 ─► B1 ─► B2 ─► C3 ─► D2 ─► G1 ─► G2
    │              └─► B3(병행)
    └─► (A1·A2 병행 착수)
C1 ─► C2 ─► D1 ─► D2

P1(LLM 답변)은 P0 완료 후: B1 ─► E1 ─► E2 ─► E3
```

P0만으로 "같은 질문, 등급별 다른 조회 결과 + 판정 근거"가 완결된다. P1(LLM 답변)은 그 위 상위 레이어이며 실패해도 P0가 데모를 지킨다.

---

## 기존 자산 재사용 체크리스트 (새로 만들지 말 것)
- `app/engine.py` — 판정 엔진, **변경 금지**
- `app/policy.yaml` — 정책, YAML 유지
- `app/ingest.py`의 `split_sections()` / `assign_placeholders()` — seed_db.py에서 import 재사용 (파서·플레이스홀더 로직 중복 구현 금지)
- `app/pipeline.py` — 질의 파이프라인·출력 가드, 소스만 DB·검색결과로 교체 (P1)
- `app/personas.yaml` — personas 테이블 seed 원본
- `tests/test_engine.py` — 회귀 기준
- Streamlit UI의 렌더링 규칙(`render_section`, `masked_html`)·색상 팔레트 — 웹 이식 시 참고

## 신규 파일 (요약)
- `app/seed_db.py` — samples 직접 시딩 + `GRADES` 등급 시드 (A1·A3)
- `app/db.py`, `data/schema.sql` — 스키마·접속 (A2)
- `app/store.py` — DB 접근 계층 (A4)
- `app/retrieval.py` — 접근제어 키워드 검색 (B1)
- `app/server.py` — FastAPI (C)
- `app/web/{index.html,app.js,style.css}` — 프론트 (D)
- `datakeeper.db` — 산출물, **.gitignore** (seed_db.py로 재생성)
