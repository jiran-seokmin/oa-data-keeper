# DataKeeper — 접근 제어 엔진 MVP

**All Data, Safe for Everyone (모든 데이터를, 모두가 안전하게)** · 지란지교소프트

데이터 보안 등급(D0~D4) × 사용자 접근 등급(C0~C4) × 상황(부서·목적·채널)을 조합해
**원문 문서의 문단/의미 단위 섹션별로 5단계 접근 모드(A0~A4)를 판정**하는 접근 제어 엔진 데모.
해커톤 MVP의 초점은 **입력 데이터의 등급 분류와 페르소나별 접근 제어를 시각적으로 보여주는 것**이다
(실시간 질의응답은 Phase 2). 설계 배경과 로드맵은 [docs/CONCEPT.md](docs/CONCEPT.md) 참조.

## 빠른 시작

```bash
uv venv .venv --relocatable  # --relocatable: 저장소를 옮겨도 스크립트 shebang이 깨지지 않음
uv pip install -r requirements.txt --python .venv/bin/python

# 1) .env 설정 (서비스 실행 시 필수)
cp .env.example .env
# .env 파일에 GEMINI_API_KEY 값을 입력

# 2) 샘플 DB 초기화 (명시적으로 실행할 때만 data/samples 반영, LLM/API 불필요)
.venv/bin/python -m app.init_samples --reset

# 3) assistant-ui 기반 웹 챗
cd app/web && npm install && npm run build && cd ../..
.venv/bin/uvicorn app.server:app --reload --port 8000

# 콘솔에서 문서별 접근 결과 확인 (LLM/API 불필요)
.venv/bin/python -m app.view_access --list-docs
.venv/bin/python -m app.view_access --doc ai_sales_strategy_report --clearance 1
.venv/bin/python -m app.view_access --doc ai_sales_strategy_report --persona sales_rep --summary
```

- **MVP 데모(문서 뷰어, 판정 매트릭스)는 API 호출 없이 결정론적으로 동작**한다.
- 등급은 `app/seed_db.py`의 `GRADES`(개발단계 Claude 분석을 사람이 검토·커밋한 정적 시드)에서 나온다. 샘플 문서를 수정하면 GRADES도 함께 갱신하고 `python -m app.init_samples --report`로 미매칭을 점검한다.
- 서버 실행만으로는 `data/samples` 문서를 DB에 넣거나 보안 등급 분류하지 않는다. 샘플 반영은 `python -m app.init_samples --reset`을 명시적으로 실행할 때만 수행한다.
- **서비스 실행 시 `.env` 설정(API 키)은 필수다.** Phase E LLM 답변 모드(`/api/chat`)가 `.env` 또는 쉘 환경변수의 API 키를 사용하며, 키가 없거나 모델 호출이 실패하면 웹 FE가 자동으로 `/api/search` 조회 모드로 폴백한다.
- 기본 provider는 Gemini다. `GEMINI_API_KEY` 또는 `GOOGLE_API_KEY`를 설정하면 Gemini SDK가 자동으로 사용한다.
- 모델 변경: `ACE_MODEL` (Gemini 기본 `gemini-3.5-flash`, Anthropic 기본 `claude-opus-4-8`).

`.env` 예시:

```bash
cp .env.example .env
# .env 파일에 GEMINI_API_KEY 값을 입력
ACE_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
ACE_MODEL=gemini-3.5-flash
```

Anthropic을 쓰려면:

```bash
ACE_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key
ACE_MODEL=claude-opus-4-8
```

프론트엔드 개발 서버:

```bash
cd app/web
npm install
npm run dev  # http://127.0.0.1:5173, /api는 FastAPI 8000번으로 프록시
```

## 데모 흐름

**킬러 장면: 같은 문서를 열어 둔 채 사이드바에서 페르소나만 바꾸면, 문단/의미 단위별 렌더링이 실시간으로 바뀐다.**

1. **📄 문서 뷰어** — "2026 하반기 AI 보안 사업 전략 보고서" 문서를 열고 외부 고객 → 신입 → 영업팀원 → 팀장 → CEO 순회:
   - ✅ A0 원문 · 🧠 A1 블러+"AI 추론 전용" 배지 · 🔍 A2 요약 카드 · 🎭 A3 엔티티 마스킹 하이라이트 · 🚫 A4 잠금
   - 문단마다 D등급 배지와 판정 사유(gap, 부서 보정)가 함께 표시됨
2. **🗺️ 판정 매트릭스** — 의미 단위 섹션 63개 × 페르소나 5개 판정을 색상 히트맵 한 화면으로
3. **⚙️ 판정 그리드** — 문서가 문단/의미 단위·등급·키워드·엔티티·A2 요약으로 분해된 산출물과 현재 페르소나 판정
4. **💬 질의응답 (Phase 2 선택 기능)** — 판정 결과를 LLM 컨텍스트 조립에 적용한 실시간 답변 + 출력 가드 (API 키 필요, 실패 시 조회 모드 폴백)

판단/집계 목적에 따른 A1 완화는 엔진과 API가 지원하지만 현재 React UI에는 토글이 연결되어 있지 않다.

## 구조

```
app/
  engine.py      판정 엔진 (순수 파이썬 — LLM 미사용, 감사 가능)
  policy.yaml    gap 매트릭스 + 컨텍스트 보정 정책
  personas.yaml  데모 페르소나 (실서비스: SSO/조직도 연동)
  keywords.yaml  관리자 등록 키워드 → 등급 힌트 (업로드 문서 분류용)
  ingest.py      분류 공용 자산 (분류 프롬프트, 엔티티 플레이스홀더)
  init_samples.py 명시적 샘플 DB 초기화 CLI
  seed_db.py     samples 원문 → 문단/의미 단위 보안 객체 변환 내부 모듈
  upload_pipeline.py  런타임 문서 업로드 → Gemini 분류 → DB 추가
  pipeline.py    [Phase 2] 질의: 판정 → 모드별 변환 → 생성 → 출력 가드
  ui.py          레거시 Streamlit 데모 (현행 기본 UI는 React)
  server.py      FastAPI 백엔드 (/api/search, /api/chat, 빌드된 React FE 서빙)
  web/           React + assistant-ui 프론트엔드
  view_access.py CLI 문서 접근 결과 뷰어 (LLM/API 미사용)
data/
  samples/       DB 시딩 대상 기본 코퍼스 원문 4개 (GRADES 등급 시드 필수)
  uploads/       drag & drop 업로드 데모용 원문 (시딩 안 됨, 라이브 분류)
  schema.sql     SQLite 스키마 (documents/sections/entities/personas)
tests/
  test_engine.py 판정 시나리오 테스트: python tests/test_engine.py
```

## 판정 규칙 요약

- A모드: `A0 전체 접근`, `A1 노출 제한`, `A2 의미 제한`, `A3 정보 마스킹`, `A4 접근 차단`
- `gap = C − D`: `≥0 → A0`, `−1 → A2`, `−2 → A3`, `≤−3 → A4`
- D4 최고 접근 정보는 최신 발표 매트릭스 특칙 적용: `C0/C1 → A4`, `C2 → A3`, `C3 → A1`, `C4 → A0`
- 담당 부서 데이터 `1단계 완화`, 판단/집계 목적은 A2/A3 → **A1(추론 근거 전용)** 완화
- 외부 채널은 D0만 A0, 나머지 전부 A4 (하드 캡)
- **D4는 어떤 보정으로도 상승 불가**, 미분류 섹션은 관리자 검수 전 접근 차단 (default-deny)
- 판정은 결정론적 코드로만 — LLM은 분류·요약·엔티티 추출(등급 시드 작성, 업로드 분류)과 챗 답변 생성에만 사용
