# PRD — DataKeeper 접근제어 챗 서비스 (Phase 2 확장)

> 상태: Draft · 작성일 2026-07-09 · 작성 이석민
> 상위 기준 문서: 발표 슬라이드(최우선) → `docs/CONCEPT.md` → 본 PRD
> 본 PRD는 CONCEPT.md의 **Phase 2 (실시간 AI 질의응답)** 를 실제 웹 서비스로 구체화한 것이다. CONCEPT.md와 충돌하면 CONCEPT.md의 원칙(특히 §4.2, §5, §8)을 우선한다.

---

## 1. 배경 및 목표 전환

### 1.1 현재 상태 (As-Is)
- MVP는 **분류 + 판정 + 시각화**에 초점. 산출물은 `data/sections.json`(고정·커밋)을 Streamlit 뷰어로 페르소나별 렌더링하는 것.
- 판정 엔진(`app/engine.py`)과 질의 파이프라인(`app/pipeline.py`, 출력 가드 포함)은 이미 구현되어 있고, Streamlit에 챗 탭이 보너스로 존재한다.
- 데이터는 전부 JSON 파일. `data/samples/`(신규 기밀 원문 4종)는 **아직 등급 분류·저장되지 않은 원문 상태**다.

### 1.2 목표 (To-Be) — "접근제어 RAG"
`data/samples/`의 문서를 **등급 정책에 맞춰 DB에 저장**하고, **웹에서 특정 접근 등급(C)을 가진 사용자가 질문하면 그 등급으로 볼 수 있게 가공된 데이터만 근거로 답하는 챗 서비스**로 전환한다.

핵심은 **2단계 파이프라인**이다:

```
[1단계 · 검색·조회 · 결정론적, 런타임 LLM 없음]     [2단계 · 답변 생성 · LLM]
질문 → 키워드 검색                                   접근제어된 컨텍스트 + 질문
     → engine.decide()로 접근 가능 섹션만 필터          → LLM 쿼리 → 답변
       (A4 = 검색 인덱스에서 제외)                      → 출력 가드 (유출 스캔)
     → 등급별 렌더                                    + 판정 근거(엔진 산출)를 답변에 부착
       (A0 원문 / A1 배경전용 / A2 요약 / A3 마스킹)
```

**핵심 안전 속성(솔루션의 방어 논리):** LLM에 넣기 전에 접근 제어가 이미 끝나 있다. LLM은 해당 사용자 등급으로 볼 수 있게 마스킹·요약·차단·태깅된 데이터만 받는다. 따라서 질문을 붙여 LLM에 태워도 유출이 구조적으로 차단되며, **판정 근거는 LLM이 아니라 결정론적 엔진이 산출한 값**을 그대로 답변에 부착한다.

### 1.3 성공 기준 (데모 기준)
1. 같은 질문("현재 논의 중인 고객사는 어디인가요?")을 서로 다른 페르소나로 물으면 조회 결과·답변이 등급에 맞게 달라진다 (차단 / 요약 / 마스킹 / 원문).
2. 근거 데이터는 모두 SQLite DB에서 조회되며, 접근 판정은 결정론적 엔진을 100% 경유한다.
3. A4로 판정된 섹션은 검색 결과·LLM 컨텍스트에 애초에 진입하지 않는다.
4. 답변에 **판정 근거**(사용 섹션·D등급·A모드·gap·사유)가 함께 표시된다.
5. **P0(무-LLM 조회)만으로도 데모가 완결**된다 — API 키 없이 결정론적으로 "등급별 다른 조회 결과"를 증명한다. LLM 답변(P1)은 그 위의 상위 레이어.

---

## 2. 범위 (Scope)

### 2.1 In Scope — P0 (무-LLM, 데모 반드시 동작)
- **`data/samples/*.md`(4종)만** 대상: 섹션 분리 → D등급·엔티티·A2 요약 부여 → **SQLite에 직접 시딩** (`app/seed_db.py` 실행 시 파싱+등급 병합+INSERT가 한 번에). 등급은 Claude 개발단계 분석을 사람이 검토해 코드에 커밋, 런타임 분류 없음. (구 `data/seed/`·`data/labels.json`·`data/sections.json` 레거시 파이프라인은 2026-07-09 정리로 삭제됨.)
- **접근제어 키워드 검색·조회**: 질문 → 접근 가능 섹션 필터(A4 제외) → 등급별 렌더 → 결과 반환
- **FastAPI 백엔드** + **경량 프론트(HTML/JS)**: 페르소나 선택 + 검색/조회 챗 UI + 판정 근거 표시
- 접근 판정은 기존 `engine.py` 재사용, 저장은 SQLite
- 데모 재현성: DB는 커밋되거나 재생성 스크립트로 결정론적 복원 가능

### 2.2 In Scope — P1 (더 나아간 목표, LLM 답변 레이어)
- 1단계에서 조회된 **접근제어된 컨텍스트 + 사용자 질문 → LLM 답변 생성** (기존 `pipeline.py` 재사용)
- **출력 가드**(제한 엔티티 유출 스캔·재생성·차단)
- 답변 하단에 판정 근거 패널 + 출력가드 상태
- `ANTHROPIC_API_KEY` 있을 때 켜지는 상위 기능. 키가 없으면 FE는 자동으로 P0(조회) 모드로 폴백.

### 2.3 In Scope — P2 (시간 남으면)
- 문서 뷰어(등급별 섹션 렌더) 웹 이식 / 판정 매트릭스 뷰 / 감사 로그

### 2.4 Out of Scope
- 계정 로그인/비밀번호 인증 → **페르소나 선택으로 대체** (드롭다운 전환)
- 벡터 DB / 임베딩 기반 RAG → SQLite 메타데이터 필터 + 키워드 검색으로 충분 (코퍼스 소규모)
- 실서비스 커넥터(Slack/Notion/메일), SSO, 실조직도 연동
- 관리자 콘솔(검수 큐 UI, 재라벨링, 키워드 규칙 편집)
- 이메일/챗 전송 시점 DLP (Phase 3)

---

## 3. 사용자 (페르소나)

로그인 없이 **페르소나 선택**으로 C등급·부서·채널을 결정한다. 초기값은 기존 `app/personas.yaml` 5종을 DB로 이관.

| id | 이름 | C | 부서 | 채널 |
|---|---|---|---|---|
| external | 외부 고객 | C0 | — | external |
| junior_dev | 신입 개발자 | C1 | 개발팀 | internal |
| sales_rep | 영업팀원 | C2 | 영업팀 | internal |
| sales_lead | 영업팀장 | C3 | 영업팀 | internal |
| ceo | CEO | C4 | 경영진 | internal |

> 페르소나 전환은 서비스 관점에서 "다른 사용자로 로그인"과 동치다. 데모에서 같은 질문을 페르소나만 바꿔 반복하는 것이 킬러 장면.

---

## 4. 핵심 시나리오

`data/samples/` 문서 기준 대표 질의 (P0 조회 결과 / P1 답변 모두 아래 등급 규칙을 따름):

| 질문 | C0 외부 | C1 신입 | C2 영업원 | C3 영업팀장 | C4 CEO |
|---|---|---|---|---|---|
| "논의 중인 고객사는?" | 접근 권한 필요 안내 | "10개 이상"(A2 요약) | 18개사·사명(A0, 부서 보정) | 원문 | 원문 |
| "예상 계약 규모는?" | 차단 | "수십억원 규모"(A2) | 총 52억·사별(A0) | 원문 | 원문 |
| "인수 검토 중인 건 있나?" | 차단 | 차단(D4→A4) | "[기업명] 검토 중"(A3 마스킹) | 내용 비공개·추론 반영(A1) | 전체(A0) |

C3×인수검토 칸(A1 노출 제한)이 P1 LLM 답변의 백미다: **AI가 기밀을 발설하지 않으면서 기밀을 반영한 더 나은 조언을 한다.**

각 결과/답변에 **판정 근거**(사용된 섹션·D등급·A모드·gap·사유)를 함께 반환해 투명성을 확보한다. 세부 접근 규칙은 `docs/CONCEPT.md §3`(gap 매트릭스 + D4 특칙 + 부서 보정 + 판단/집계 A1 완화)를 그대로 따른다. **엔진 코드/정책은 변경하지 않는다.**

---

## 5. 시스템 아키텍처

```
data/samples/*.md (4종)          app/seed_db.py 내 등급 시드(GRADES, 커밋·검토됨)
      │                                 │
      └──────────────┬──────────────────┘
                     ▼  app.init_samples 명시 실행 (samples 파싱 + 등급 병합 + 플레이스홀더 → INSERT. 런타임 LLM 없음)
  SQLite  datakeeper.db
   ├─ documents(문서)
   ├─ sections(섹션 + D등급·요약·키워드·부서·신뢰도·검수)
   ├─ entities(마스킹용 엔티티 text/placeholder/type)
   └─ personas(데모 사용자)
      │
      ▼
  app/store.py  (DB 접근 계층: sections/personas/documents 로드 + 키워드 검색)
      │
      ├──────────────── 1단계 · 검색·조회 (결정론적, LLM 없음) ─────────────
      │   app/retrieval.py
      │     search(question, persona, purpose):
      │       키워드 매칭 → engine.decide()로 접근 필터(A4 제외)
      │       → 등급별 렌더된 섹션 리스트 + 판정 근거 반환
      │
      └──────────────── 2단계 · 답변 생성 (LLM, P1) ──────────────────────
          app/pipeline.py  (기존 재사용, 소스를 DB·검색결과로 전환)
            접근제어된 컨텍스트 + 질문 → LLM → 출력 가드 → 답변 + 판정 근거
      │
      ▼
  app/engine.py   (결정론적 판정 — 변경 없음)
      │
      ▼
  app/server.py  (FastAPI)
   GET  /api/personas
   GET  /api/documents?persona_id=
   POST /api/search          {persona_id, question, purpose}   ← P0 핵심 (무-LLM)
   POST /api/chat            {persona_id, question, purpose}   ← P1 (LLM 답변)
   GET  /api/documents/{doc}?persona_id=&purpose=   (P2 뷰어)
   GET  /api/matrix / /api/audit                    (P2)
      │
      ▼
  app/web/  (정적 프론트: index.html + app.js + style.css)
   페르소나 선택 · 검색/챗 · 판정 근거 패널 · (P2) 뷰어/매트릭스
```

**설계 원칙 재확인 (불변):**
- 접근 판정은 `engine.py` + `policy.yaml`의 결정론적 코드만 수행. LLM은 수집(개발단계 분류)과 P1 답변 생성에만 사용.
- **접근 제어는 항상 LLM보다 먼저 일어난다.** LLM은 이미 등급에 맞게 변환된 데이터만 받는다.
- A4 섹션은 검색/컨텍스트 진입 차단 (default-deny). 미분류 섹션도 검수 전 차단.
- 외부 채널은 D0만 허용 (하드 캡).

---

## 6. 데이터 모델 (SQLite)

`data/samples/*.md` 원문을 문단/의미 단위 보안 객체로 분해해 저장한다. 기존 heading 단위 등급 시드는
`source_section_id`로 연결해 추적한다. 스키마(초안):

```sql
CREATE TABLE documents (
  doc          TEXT PRIMARY KEY,   -- 파일 stem (예: ai_sales_strategy_report)
  doc_title    TEXT NOT NULL,
  source_path  TEXT NOT NULL       -- data/samples/xxx.md
);

CREATE TABLE sections (
  id                  TEXT PRIMARY KEY,   -- "<doc>#<index>"
  doc                 TEXT NOT NULL REFERENCES documents(doc),
  seq                 INTEGER NOT NULL,   -- 문서 내 순서
  title               TEXT NOT NULL,
  parent_title        TEXT NOT NULL,      -- 원문 ## heading
  source_section_id   TEXT NOT NULL,      -- 사람이 검수한 heading 단위 등급 시드 id
  text                TEXT NOT NULL,
  security_level      INTEGER,            -- D0~D4, NULL=미분류(default-deny)
  confidence          REAL,
  needs_review        INTEGER DEFAULT 0,
  keywords            TEXT,               -- JSON 배열 (검색·매칭용)
  departments         TEXT,               -- JSON 배열 (부서 보정용)
  summary_generalized TEXT                -- A2용 일반화 요약
);

CREATE TABLE entities (
  section_id  TEXT NOT NULL REFERENCES sections(id),
  text        TEXT NOT NULL,              -- 원문 표기 (마스킹 대상)
  placeholder TEXT NOT NULL,              -- [고객사A] 등
  type        TEXT                        -- 고객사/금액/인명/일정 ...
);

CREATE TABLE personas (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  clearance   INTEGER NOT NULL,           -- C0~C4
  department  TEXT,
  channel     TEXT NOT NULL               -- internal | external
);
```

**메타데이터 사전 필터**: 검색 시 `SELECT ... FROM sections`에 코스 필터를 건다.
- 외부 채널(persona.channel='external') → `WHERE security_level = 0`
- 그 외 → 후보 로드 후 `engine.decide()`로 A4 섹션 제외
- (섹션 수가 커지면 `security_level <= clearance + 여유` 형태로 확장)

> **호환성**: `store.py`가 반환하는 섹션 dict는 기존 `sections.json` 항목과 동일한 키 형태(`id, doc, doc_title, title, text, security_level, confidence, departments, keywords, summary_generalized, entities, needs_review`)를 유지하고, 추가로 `parent_title`, `source_section_id`를 제공한다. 그래야 `engine.decide()` / `pipeline.render_block()`을 수정 없이 재사용한다.

---

## 7. 검색·조회 로직 (1단계, 무-LLM) — 핵심

**유출 방지가 검색 설계의 제1 원칙이다.** 순서를 반드시 지킨다:

1. **후보 선별**: DB에서 섹션 로드 (외부 채널은 D0만).
2. **접근 필터 우선**: 각 섹션에 `engine.decide(section, persona, policy, purpose)` 적용 → **A4 섹션은 여기서 완전히 제거**(검색 인덱스 진입 자체 차단, 존재 은닉).
3. **등급별 렌더**: 남은 섹션을 A모드에 맞게 변환 — A0 원문 / A1 배경전용(내용 태깅) / A2 요약(summary_generalized) / A3 마스킹(entities 치환).
4. **키워드 매칭**: 질문 토큰을 **렌더된 텍스트 + 제목 + keywords 필드**에 대해 부분일치/토큰 매칭. → 숨겨진 엔티티(A3에서 치환된 원문 값)로는 히트가 나지 않는다.
   - 예: C0가 "실드락" 검색 → 해당 섹션이 A4라 0건. C2(A3)가 "실드락" 검색 → 마스킹된 `[기업명]`만 있어 0건이지만 "인수"로는 마스킹 섹션이 히트.
5. **결과 반환**: 매칭 섹션 + 각 판정 근거(D/A/gap/reasons). 매칭 0건이면 "권한 내 관련 정보 없음" 안내.

> FTS5 없이 SQLite `LIKE` 또는 파이썬 토큰 매칭으로 충분(코퍼스 소규모). 상태 비저장(질의마다 독립).

---

## 8. API 명세 (초안)

| Method | Path | 입력 | 출력 | 비고 |
|---|---|---|---|---|
| GET | `/api/personas` | — | `[{id,name,clearance,department,channel}]` | 프론트 셀렉터 |
| GET | `/api/documents` | `persona_id` | `[{doc,doc_title,lock_state}]` | lock_state: open/partial/locked |
| POST | `/api/search` | `{persona_id, question, purpose}` | `{results[], persona}` | **P0 핵심 (무-LLM)** |
| POST | `/api/chat` | `{persona_id, question, purpose}` | `{answer, used_sections[], guard, persona}` | **P1 (LLM 답변)** |
| GET | `/api/documents/{doc}` | `persona_id, purpose` | `[{section, decision}]` | P2 뷰어 |
| GET | `/api/matrix` / `/api/audit` | — | 격자 / 로그 | P2 |

**`POST /api/search` 응답 (P0)**
```json
{
  "results": [
    {"id":"ai_sales_strategy_report#1","title":"고객 파이프라인 현황",
     "security_level":2, "mode":0, "mode_name":"A0 전체 접근", "gap":0,
     "rendered":"관련 고객은 총 18개사다 …",
     "reasons":["기본 매트릭스: gap=0 → A0 전체 접근","부서 관련성(+1)…"]}
  ],
  "persona": {"id":"sales_rep","name":"영업팀원","clearance":2}
}
```
- A4 섹션은 결과에 미포함(존재 은닉). A2는 `rendered`에 요약, A3는 마스킹본, A1은 배경전용 표시.

**`POST /api/chat` 응답 (P1)**
```json
{
  "answer": "…LLM 답변…",
  "used_sections": [ /* /api/search results와 동일 구조 */ ],
  "guard": {"triggered":false, "leaked":[], "blocked":false},
  "persona": {"id":"sales_rep","name":"영업팀원","clearance":2}
}
```
- `ANTHROPIC_API_KEY` 없으면 503 → FE는 자동으로 `/api/search`(조회 모드)로 폴백.
- `used_sections`/`reasons`는 판정 투명성을 위해 항상 반환.

---

## 9. 프론트엔드 요구사항 (경량 HTML/JS)

- **상단 바**: 페르소나 셀렉터(드롭다운) + "판단/집계 목적(A1 완화)" 토글. 전환 즉시 세션 컨텍스트 갱신.
- **챗 화면**:
  - 질문 입력 → 사용자 메시지 버블.
  - 응답 버블: **P1 모드**면 LLM 답변, **P0/폴백**이면 조회된 섹션 카드 리스트(A모드별 렌더 — 원문/요약카드/마스킹 하이라이트/배경전용 배지).
  - 응답 하단에 접이식 **"판정 근거"** 패널(used_sections: D등급 배지·A모드·gap·사유). 출력 가드 발동 시 경고 배지.
  - API 미설정 시 "조회 모드로 동작 중" 안내.
- **(P2) 문서 뷰어 탭**: 현재 Streamlit `render_section` 규칙을 웹으로 이식.
- **(P2) 매트릭스 탭**: 섹션×페르소나 히트맵.
- 스타일: 기존 UI의 모드 색상(A0 초록 … A4 회색) 팔레트 재사용. 프레임워크 없이 vanilla JS + fetch.

---

## 10. 데이터 준비 — samples 직접 DB 시딩 (samples만)

대상은 **`data/samples/*.md` 4종뿐**이다(seed/·labels.json·sections.json 미사용). 중간 산출물(`labels.json → sections.json`) 없이 **`app.init_samples` 명령이 `app/seed_db.py`의 정적 시드를 사용해 DB를 채운다.**

시딩 절차(`python -m app.init_samples --reset` 명시 실행):
1. `split_semantic_sections()`로 `data/samples/*.md` 파싱 → `##` heading 아래 빈 줄로 분리된 문단을 독립 보안 객체로 저장. 각 row는 `id = <파일stem>#<chunk_i>`, `parent_title`, `source_section_id = <파일stem>#<heading_i>`, text를 갖는다.
2. `seed_db.py` 내 **등급 시드(GRADES)** 를 `source_section_id`로 병합 → security_level·confidence·keywords·departments·summary_generalized·entities(text/type). 라벨 없는 heading은 해당 문단을 D4 격리(default-deny).
3. `assign_placeholders()`로 엔티티 플레이스홀더를 **코퍼스 전역 일관** 부여. (기존 헬퍼 재사용, 시드에는 placeholder 미포함)
4. 스키마 생성 후 documents/sections/entities/personas 테이블에 **직접 INSERT** (`--reset` 명령으로 재생성).

**등급 시드(GRADES) 작성:** Claude(개발단계)가 samples를 분석해 초안 작성 → 사람이 **발표 슬라이드 등급표와 대조·검토** → `seed_db.py`에 커밋. 이 파이썬 시드가 유일한 원천이자 재현 수단이며, git-diff로 등급 변경을 리뷰한다. **등급 시드 id는 heading 단위 `source_section_id`에 맞춰 부여**하고, DB에는 그 아래 문단들이 독립 보안 객체로 저장된다(불일치 시 해당 문단들이 D4로 격리됨).

> 재현성: DB 파일(`datakeeper.db`)은 산출물이므로 `.gitignore` 처리하고, `seed_db.py`(파서·헬퍼·등급 시드)와 `init_samples.py`(명시 초기화 CLI)만 커밋한다. 서버 실행만으로 samples는 DB에 반영되지 않으며, 데모 전 `python -m app.init_samples --reset`을 1회 실행해 DB를 결정론적으로 생성.

**등급 배치(초안, 발표 슬라이드 기준으로 검토 필요):**
- `ai_sales_strategy_report.md`: 개요 D0 · 파이프라인 D2 · 계약규모 D2/D3 · 가격전략 D3 · 인수검토 **D4** · 재무전망 D3
- `enterprise_contract_negotiation.md`: 계약 조건·금액 D3
- `hr_compensation_retention_plan.md`: 보상·인사 D4
- `security_incident_review.md`: 인시던트 상세 D3

---

## 11. 비기능 요구

- **재현성**: DB는 스크립트로 결정론적으로 재생성 가능. 데모 중 라이브 분류 금지. P0(조회)는 API 키 불필요.
- **감사 가능성**: 판정 사유(reasons)가 모든 결과/답변에 노출. 판정 로직에 LLM 미개입.
- **인젝션 내성**: 접근 제어가 LLM 앞단에서 완료(LLM은 변환된 데이터만 수신) + 시스템 프롬프트 우선(기존 `pipeline.SYSTEM_TEMPLATE`) + 출력 가드가 최종 방어선.
- **성능**: 코퍼스 소규모 → 전체 섹션 로드 후 판정으로 충분. P1 지연은 LLM 호출이 지배적.
- **장애 대응**: API 키 없거나 LLM 오류 시 FE는 P0(조회)로 폴백. 뷰어/매트릭스(P2)는 API 없이 동작.

---

## 12. 리스크

| 리스크 | 대응 |
|---|---|
| samples 등급 오분류 → 데모 판정 어색 | Claude 개발단계 분석 + 사람 검토 + 리허설 시 매트릭스로 전수 확인 |
| P1(LLM 답변)이 데모 중 실패 | P0(무-LLM 조회)를 완결된 백업 경로로 확보, FE 자동 폴백, 응답 캐시/스크린샷 |
| 검색으로 상위 등급 정보 유출 | **접근 필터 우선 → 렌더 → 그 위에서 키워드 매칭** 순서 강제 (§7) |
| A1(노출 제한) 프롬프트 인젝션 유출 | LLM은 배경전용 태깅본만 수신 + 출력 가드 |
| 섹션 id 불일치로 등급 시드가 무시됨(D4 격리) | 등급 시드의 id를 `split_sections()` 출력에 맞춰 부여, 시딩 시 미매칭 경고 출력 |
| store.py 반환 필드 불일치로 엔진 깨짐 | store.py가 기존 `sections.json`과 동일 dict 스키마 반환(§6) + 기존 `tests/test_engine.py` 회귀 |
| DB 파일 커밋 vs .gitignore 충돌 | `seed_db.py`(파서+등급 시드)만 커밋, DB(`datakeeper.db`)는 .gitignore 산출물 |

---

## 13. 마일스톤

| 단계 | 내용 | 산출물 |
|---|---|---|
| M1 데이터 계층 | samples 등급 시드 → `init_samples` 명시 초기화, store.py | `app/seed_db.py`, `app/init_samples.py`, `datakeeper.db`, `app/store.py` |
| M2 검색·조회 (P0) | 접근제어 키워드 검색 로직 + 회귀 테스트 | `app/retrieval.py`, 통과하는 `tests/` |
| M3 API | FastAPI 검색/페르소나/문서 엔드포인트 | `app/server.py` (`/api/search`) |
| M4 프론트 (P0) | 페르소나 셀렉터 + 검색 챗 UI + 판정 근거 | `app/web/` |
| M5 LLM 답변 (P1) | pipeline DB 연결 + `/api/chat` + FE 답변/폴백 | LLM 답변 레이어 |
| M6 (P2) | 뷰어·매트릭스·감사 로그 이식 | 추가 API/화면 |
| M7 리허설 | 페르소나×대표질의 전수 확인 | 데모 대본 |

세부 작업은 `docs/TASKS-chat-service.md` 참조.
