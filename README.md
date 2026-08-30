# DataKeeper — C/S/O 데이터 분류·접근 제어 MVP

**All Data, Safe for Everyone (모든 데이터를, 모두가 안전하게)** · 지란지교소프트

DataKeeper는 문서를 의미 단위 섹션으로 나누고 각 섹션을 N2SF 기반 `O`, `S`, `C`로 분류한 뒤,
사용자의 `access_grade`에 따라 원문 접근을 결정하는 데모다. 접근 결과는 **허용 또는 차단**뿐이며,
권한 밖이거나 분류가 확정되지 않은 섹션은 검색 결과와 LLM 컨텍스트에 들어가지 않는다.

## 핵심 모델

등급 순서는 다음과 같다.

| 등급 | 이름 | 의미 |
|---|---|---|
| `O` | Open · 공개 | 외부 공개가 가능한 정보 |
| `S` | Sensitive · 민감 | 조직 내부에서 제한적으로 다뤄야 하는 정보 |
| `C` | Classified · 기밀 | 유출 시 조직에 중대한 영향을 줄 수 있는 정보 |

판정 규칙은 단순하고 결정론적이다.

```text
confirmed = classification_status ∈ {auto_confirmed, user_confirmed}
allowed   = confirmed AND section.grade <= persona.access_grade
```

- 등급 비교는 `O < S < C`다.
- `pending_review`, 알 수 없는 상태, 누락·오류 등급은 모두 차단한다.
- 허용된 섹션은 원문을 제공하고, 차단된 섹션은 검색·응답 컨텍스트에서 제외한다.
- 문서 등급은 소속 섹션 등급의 최댓값으로 매번 계산하며 `documents` 테이블에는 저장하지 않는다.
- LLM은 업로드 문서 분류와 선택적 답변 생성에만 사용한다. 접근 판정에는 참여하지 않는다.

## 데모 사용자와 접근 범위

기본 샘플에는 5개 프로필이 있다. 현재 접근 판정은 `access_grade`만 사용하며 부서와 채널은
화면 표시용 메타데이터다. 따라서 같은 S 등급인 세 프로필은 같은 질문에 동일한 접근 결과가
나오는 것이 정상이다.

| 확정 섹션 | 외부 고객 `O` | 신입 개발자 `S` | 영업팀원 `S` | 영업팀장 `S` | CEO `C` |
|---|---:|---:|---:|---:|---:|
| `O` | 허용 | 허용 | 허용 | 허용 | 허용 |
| `S` | 차단 | 허용 | 허용 | 허용 | 허용 |
| `C` | 차단 | 차단 | 차단 | 차단 | 허용 |
| `pending_review` | 차단 | 차단 | 차단 | 차단 | 차단 |

## 빠른 시작

요구 환경:

- Python 3.10 이상과 [uv](https://docs.astral.sh/uv/)
- Node.js `^20.19.0` 또는 `>=22.12.0`과 npm

```bash
uv venv .venv --relocatable
uv pip install -r requirements.txt --python .venv/bin/python

# 샘플 등급과 섹션 매칭만 점검한다. DB는 변경하지 않는다.
.venv/bin/python -m app.init_samples --report

# 샘플 DB를 새로 만든다. 기존 업로드·수정·로그·Skill은 삭제되므로 데모 초기화 때만 사용한다.
.venv/bin/python -m app.init_samples --reset

# React 의존성 설치와 프로덕션 빌드
npm --prefix app/web ci
npm --prefix app/web run build

# FastAPI와 빌드된 React 앱 실행
.venv/bin/uvicorn app.server:app --reload --port 8000
```

브라우저에서 `http://127.0.0.1:8000`을 연다. 샘플 초기화와 권한 기반 검색은 API 키 없이
동작한다. 문서 업로드 분류 또는 LLM 답변을 사용하려면 `.env`를 설정한다.

`datakeeper.db`가 없으면 서버는 빈 최신 스키마만 만들며 샘플은 자동으로 넣지 않는다. 위의
`app.init_samples --reset`이 샘플을 넣는 명시적 명령이다. 촬영이나 장기 실행에서는 서버 재시작을
피하도록 `uvicorn`의 `--reload`를 생략할 수 있다.

```bash
cp .env.example .env

# 기본 provider: Gemini
ACE_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
ACE_MODEL=gemini-2.5-flash
```

Gemini 키는 `GEMINI_API_KEY` 대신 `GOOGLE_API_KEY`로도 지정할 수 있다. 저장소 루트의 `.env`는
기존 셸 환경변수를 덮어쓰지 않는다.

챗 생성은 Anthropic도 선택할 수 있다. 런타임 문서 업로드 분류는 Gemini를 사용한다.

```bash
ACE_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-anthropic-api-key
ACE_MODEL=claude-opus-4-8

# 업로드 분류는 계속 Gemini를 사용한다.
GEMINI_API_KEY=your-gemini-api-key
GEMINI_CLASSIFICATION_MODEL=gemini-2.5-flash
```

개발용 프런트엔드는 별도로 실행할 수 있다.

```bash
npm --prefix app/web run dev
# http://127.0.0.1:5173, /api 요청은 FastAPI 8000번으로 프록시
```

React 앱과 별도로 간단한 Streamlit 검수 콘솔도 제공한다. 먼저 샘플 초기화, 마이그레이션 또는
FastAPI 실행으로 최신 DB 스키마를 준비해야 한다.

```bash
.venv/bin/streamlit run app/ui.py
```

## 데모 흐름

1. **분류·학습**
   - 샘플 또는 업로드 문서를 섹션별 `O/S/C` 등급, 신뢰도, 근거, 요약, 키워드로 확인한다.
   - 업로드 분류의 신뢰도가 `0.8` 미만이면 `pending_review`로 남아 접근이 차단된다.
   - 사용자가 섹션 등급과 근거를 확정·수정하면 `user_confirmed`가 되고, 그 피드백은 활성
     Classification Skill로 저장되어 이후 업로드 분류 프롬프트에 반영된다.
   - 화면의 문서 등급은 섹션 등급 중 가장 높은 값이다.
2. **권한 기반 질문**
   - 페르소나를 선택하면 해당 `access_grade` 이하의 확정 섹션만 SQL 단계에서 읽는다.
   - 키워드 검색은 이 허용 집합 안에서만 수행한다.
   - 같은 브라우저 탭에서는 persona별 완료 대화를 복원하고, 최근 질문 최대 5개로 생략된 후속
     질문의 검색 문맥을 보완한다. 과거 답변은 API에 다시 보내지 않는다.
   - `/api/chat`은 허용된 원문만 LLM에 전달한다. 자격 증명이 없거나 호출이 실패하면 UI가
     `/api/search` 결과로 폴백한다.
3. **판정·접근 로그**
   - 자동 분류, 사용자 확정·수정, Skill 적용 이력을 확인한다.
   - 접근 로그는 사용자, 동작, 문서·섹션 식별자, 허용·차단 개수만 기록한다.
   - 질문, 답변, 프롬프트, 섹션 원문은 감사 로그에 저장하지 않는다.

### 5개 프로필로 같은 질문 비교

[`00_orion_60s_demo.md`](data/uploads/00_orion_60s_demo.md)를 업로드하고 실제 분류 결과를 확인한
뒤 각 행의 질문을 5개 프로필에 문장 그대로 반복한다. 이 파일은 샘플 초기화 대상이 아니며 Gemini
결과는 실행마다 달라질 수 있으므로, 촬영 전 각 카드의 상태를 확인하고 필요한 등급을 사용자 확정한다.

| 검증 대상 | 동일 질문 | 기대 결과 |
|---|---|---|
| 확정 `O` | `소개 페이지는 누구나 볼 수 있나요?` | 5개 프로필 모두 O 근거 1건 |
| 확정 `S` | `사내 출시 준비에 필요한 예산과 인력 계획은 무엇인가요?` | 외부 고객 O만 0건, S 3명과 CEO C는 S 근거 1건 |
| 확정 `C` | `최소 보장액과 매출 배분율 수치를 알려주세요.` | CEO C만 C 근거 1건, 나머지 4명은 0건 |
| 검수 대기 | `서비스 공급 중단 시 어떤 대응을 검토하고 있나요?` | C 확정 전에는 5명 모두 0건 |
| `C` 확정 후 | 위와 같은 질문 | CEO C만 `해지 조건 검토 메모` 1건, 나머지 4명은 0건 |

`0건`은 권한 밖 정보의 존재를 노출하지 않는 중립적인 **관련 자료 없음** 결과를 뜻한다.
정확한 준비 순서와 수정 근거는 [60초 데모 시나리오](docs/VIDEO-DEMO-60S.md)를 따른다.

더 긴 업로드 흐름, 상세한 백업·복구와 예외 대응은
[5분 데모 운영 가이드](docs/VIDEO-DEMO-SCENARIO.md)에 정리되어 있다.

콘솔에서도 판정 결과를 확인할 수 있다.

```bash
.venv/bin/python -m app.view_access --list-docs
.venv/bin/python -m app.view_access --doc enterprise_contract_negotiation --grade O
.venv/bin/python -m app.view_access --doc enterprise_contract_negotiation --persona sales_rep
```

## 채팅 세션과 기록 범위

채팅 기억은 로그인 계정에 연결된 서버 세션이 아니라 **현재 브라우저 탭의 `sessionStorage`**다.

| 대상 | 저장·전송 범위 | 초기화 방식 |
|---|---|---|
| 화면 transcript | 프로필별 완료 대화 최대 50건. 같은 탭의 새로고침과 프로필 전환에서 복원되며 다른 탭·브라우저·기기와 공유하지 않음 | 화면의 `현재 대화 지우기`는 선택한 프로필만 삭제 |
| 후속 질문 문맥 | 현재 질문과 최근 성공 질문 최대 5개만 API로 전송. 과거 답변은 재전송하지 않음 | transcript에서 자동 파생 |
| SQLite 접근 로그 | 프로필·등급·동작·문서/섹션 ID·허용/차단 개수만 저장 | `app.clear_runtime_data --apply`로 삭제 |

- 서버의 채팅 세션 세대를 확인하기 전에는 기존 transcript를 표시하거나 새 질문을 보내지 않는다.
- 전체 정리 명령이 세대를 교체하면 모든 프로필의 로컬 transcript가 무효화된다.
- 정리 중이던 이전 세대 요청은 서버에서 `409`로 거절하며 접근 로그도 남기지 않는다.

## 기존 DB 마이그레이션

기존 스키마의 섹션 등급은 `D0 → O`, `D1~D3 → S`, `D4 → C`로 변환한다. 기존 사용자 숫자
clearance는 `0 → O`, `1~3 → S`, `4 → C`로 변환한다. 기존 `needs_review` 섹션은 보수적으로
`pending_review`가 된다.

```bash
# 기본값은 변경 전에 datakeeper.backup-<timestamp>.db 백업을 만든다.
.venv/bin/python -m app.migrate_cso --db datakeeper.db

# 백업 위치를 직접 지정할 수도 있다.
.venv/bin/python -m app.migrate_cso \
  --db datakeeper.db \
  --backup-path datakeeper.pre-cso.db
```

- 마이그레이션은 문서·섹션·페르소나를 한 트랜잭션으로 보존하고 외래 키를 검사한다.
- 각 기존 섹션에 본문 없는 `legacy_migrated` 분류 로그를 남긴다.
- 이미 최신 스키마이면 변경하지 않으며, 빈 DB이면 최신 스키마를 초기화한다.
- `--no-backup`은 폐기 가능한 테스트 DB에서만 사용한다.
- 서버는 레거시 D0~D4/C0~C4 스키마를 자동으로 C/S/O로 변환하지 않는다. 레거시 DB를 발견하면
  먼저 위 명령을 실행해야 한다.

## Skill·채팅 세션·로그 정리

정리 중 새 로그나 Skill이 생성되지 않도록 API 서버를 먼저 중지한다. 기본 명령은 대상 건수만
표시하고 DB를 변경하지 않는다.

```bash
# 삭제 대상과 보존 대상 확인
.venv/bin/python -m app.clear_runtime_data --db datakeeper.db

# 타임스탬프 DB 백업 후 실제 삭제
.venv/bin/python -m app.clear_runtime_data --db datakeeper.db --apply

# 백업 위치를 직접 지정
.venv/bin/python -m app.clear_runtime_data \
  --db datakeeper.db \
  --backup-path datakeeper.before-runtime-clear.db \
  --apply
```

- 삭제: `classification_skills`, `classification_logs`, `access_logs`의 모든 행
- 보존: 문서, 섹션과 현재 분류 등급·근거, 페르소나
- 채팅 transcript는 브라우저 탭의 `sessionStorage`에 있으므로 명령이 서버의 세션 세대를
  교체한다. 실행 후 열린 탭은 서버 연결이 가능하면 약 5초 주기로 확인하고, 중지된 탭은 다시
  열거나 포커스할 때 모든 프로필의 transcript를 로컬에서 삭제한다.
- 기본 백업에는 삭제 전 Skill과 로그가 포함된다. 복구가 필요 없는 폐기용 DB에서만
  `--no-backup --apply`를 사용한다.
- 백업 생성 후 정리가 실패하면 DB 변경은 롤백하고 복구용 백업은 유지한다. 오류 메시지에 남은
  백업 경로가 표시된다.
- 서버를 다시 사용하면 새 Skill과 로그가 생성될 수 있다.

## 주요 API

| Method | Path | 용도 |
|---|---|---|
| `GET` | `/api/personas` | 데모 사용자와 `access_grade` 조회 |
| `GET` | `/api/runtime/chat-session` | 브라우저 transcript 무효화 세대 조회 |
| `GET` | `/api/classifications` | 문서·섹션 분류 메타데이터와 파생 문서 등급 조회 |
| `GET` | `/api/review-queue` | `pending_review` 섹션 조회 |
| `GET` | `/api/review/sections/{section_id}/preview` | 분류 검토 화면에서 선택한 섹션 원문 미리 보기 |
| `PATCH` | `/api/sections/{section_id}/classification` | 등급과 근거를 사용자 확정·수정하고 Skill 생성·갱신 |
| `GET` | `/api/skills` | Classification Skill 조회 |
| `PATCH` | `/api/skills/{skill_id}` | Skill 활성화 상태 변경 |
| `GET` | `/api/logs/classification` | 본문 없는 분류 감사 로그 조회 |
| `GET` | `/api/logs/access` | 질문·답변 없는 접근 감사 로그 조회 |
| `GET` | `/api/documents?persona_id=...` | 현재 사용자에게 보이는 문서 조회 |
| `GET` | `/api/sections?persona_id=...` | 현재 사용자에게 허용된 섹션 원문 조회 |
| `POST` | `/api/search` | 권한 필터 우선 키워드 검색 |
| `POST` | `/api/chat` | 허용된 섹션만 사용하는 LLM 답변 |
| `POST` | `/api/documents/upload` | 최대 80,000자의 `.txt`/`.md` 업로드와 Gemini 분류 |
| `DELETE` | `/api/documents/{doc}` | 문서와 섹션 삭제, 내용 없는 감사 이력 보존 |

FastAPI의 대화형 API 문서는 서버 실행 후 `http://127.0.0.1:8000/docs`에서 확인할 수 있다.

> **보안 경계:** 현재 MVP 전체에는 사용자 인증이 없으며 검색·챗 API도 클라이언트가 보낸
> `persona_id`를 신뢰한다. 누구나 `ceo`를 지정할 수 있고 CORS도 개발 편의를 위해 전체 허용되어
> 있으므로 인터넷에 노출하면 안 된다. 실서비스에서는 SSO 토큰의 서버 검증 결과로 프로필과 등급을
> 결정하고, 분류 검토·원문 미리보기·Skill·로그·업로드·삭제 API에 별도 관리자 인가를 적용해야 한다.

## 프로젝트 구조

```text
app/
  config.py          루트 .env와 LLM·업로드 분류 모델 설정
  engine.py          O/S/C 순서, 레거시 매핑, 이진 접근 판정
  db.py              SQLite 연결·초기화·백업·마이그레이션·세션 세대
  clear_runtime_data.py Skill·채팅 세션·감사 로그 정리 CLI
  migrate_cso.py     안전한 마이그레이션 CLI
  store.py           문서·섹션·persona·Skill·감사 로그 저장 계층
  seed_db.py         검토된 샘플 등급과 결정론적 시딩
  init_samples.py    명시적 샘플 초기화 CLI
  upload_pipeline.py Gemini 업로드 분류와 Skill 적용
  governance.py      사용자 등급 확정과 피드백 Skill의 원자적 저장
  retrieval.py       권한 필터 이후 키워드 검색
  pipeline.py        허용 원문만 사용하는 선택적 LLM 답변
  server.py          FastAPI와 빌드된 React 앱 제공
  ui.py              선택형 Streamlit 분류 검수 콘솔
  web/               React 19 + TypeScript + Vite
data/
  schema.sql         CSO 스키마
  samples/           결정론적 시딩 대상 원문
  uploads/           라이브 업로드 시연용 원문
tests/               실행형 회귀 시나리오
```

## 검증

현재 Python 테스트는 `main()`을 실행하는 회귀 스크립트 형식이다.

```bash
for test_file in tests/test_*.py; do
  .venv/bin/python "$test_file" || exit 1
done

npm --prefix app/web run build
```

검증 범위는 기존 등급의 정확한 변환과 백업, 등급 비교, 검수 대기 차단, 사용자 확정→Skill 학습,
권한 밖 원문의 검색·LLM 제외, API 계약, 업로드 분류, 문서 삭제 후 감사 이력 보존, TypeScript
프로덕션 빌드, 동시 쓰기 중 안전한 런타임 백업·정리, 프로필별 채팅 세션 무효화다. DB 관련
테스트는 임시 파일에서 실행된다.
