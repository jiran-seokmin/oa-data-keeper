# PRD — DataKeeper C/S/O 분류·권한 기반 질문 서비스

> 상태: MVP 구현 기준 문서
> 최종 갱신: 2026-08-30
> 상위 개념 문서: docs/CONCEPT.md

## 1. 제품 요약

DataKeeper는 txt 또는 Markdown 문서를 섹션으로 나누고 O/S/C 등급을 부여한다. 사용자는 자신의
access_grade 이하이면서 분류가 확정된 섹션만 원문으로 검색하거나 LLM 답변의 근거로 사용할 수
있다. 접근 결과는 허용 또는 차단이며, 검토 대기 섹션은 사용자 등급과 무관하게 차단한다.

제품은 분류 자동화만 제공하지 않는다. 검토자가 등급을 근거와 함께 확정·수정하고, 이 피드백을
Classification Skill로 축적해 다음 분류에 적용하며, 분류·접근 과정을 내용 없는 감사 로그로
추적한다.

## 2. 목표

### 제품 목표

1. 한 문서 안의 서로 다른 민감도를 섹션 단위로 관리한다.
2. O < S < C라는 하나의 순서로 데이터와 사용자 접근을 설명한다.
3. 권한 밖 원문을 검색 후보나 LLM 컨텍스트로 읽기 전에 제거한다.
4. 자동 분류가 불확실하면 pending_review로 보내고 사용자 확인 전까지 차단한다.
5. 사용자 수정 근거를 재사용 가능한 Skill과 감사 이력으로 남긴다.
6. 질문·답변·원문을 복제하지 않고도 누가 어떤 범위를 사용했는지 감사한다.
7. 기존 DB를 백업과 트랜잭션을 사용해 안전하게 전환한다.

### 성공 지표

- 모든 접근 결정이 allowed 또는 denied로 설명된다.
- 확정되지 않은 섹션이 /api/documents, /api/sections, /api/search, /api/chat에 나타나지 않는다.
- O 사용자는 O만, S 사용자는 O와 S만, C 사용자는 모든 확정 등급을 조회한다.
- 섹션 등급 변경 직후 파생 문서 등급과 접근 결과가 함께 바뀐다.
- 사용자 확정 시 분류 로그와 피드백 Skill이 같은 트랜잭션에서 저장된다.
- 접근 로그 스키마와 레코드에 질문·답변·프롬프트·원문이 없다.
- 마이그레이션 전 기본 백업이 생성되고 문서·섹션·persona 개수가 보존된다.

## 3. 범위

### MVP 범위

- data/samples의 검토된 정적 시드로 결정론적 샘플 DB 생성
- txt, md 런타임 업로드와 Gemini 섹션 분류
- 분류 신뢰도, 상태, 근거, 요약, 키워드, 담당 부서 저장
- 검수 대기 목록과 사용자 등급 확정·수정
- 사용자 피드백 기반 Classification Skill 생성·갱신·활성화
- O/S/C 이진 접근 판정
- 권한 필터 우선 키워드 검색
- 허용된 원문만 이용하는 Gemini 또는 Anthropic 답변
- LLM 실패 시 검색 결과 폴백
- 분류 로그와 접근 로그
- 문서 삭제와 내용 없는 감사 이력 보존
- SQLite 백업·마이그레이션
- FastAPI와 React 19 웹 UI

### 범위 밖

- 로그인, 비밀번호, SSO, 실제 조직 권한 연동
- 관리자와 일반 사용자 역할 기반 API 인가
- persona 생성·접근 등급 관리 UI
- PDF·오피스 문서 파싱
- Slack, Notion, 메일 등 외부 커넥터
- 임베딩 또는 벡터 검색
- 차단된 원문의 일부·대체 표현 제공
- 감사 로그 장기 보존, 서명, 외부 내보내기
- 다중 조직 격리와 운영용 키 관리

## 4. 사용자

현재 MVP는 인증 대신 DB의 데모 persona를 선택한다.

| id | 이름 | access_grade | 부서 | 채널 |
|---|---|---|---|---|
| external | 외부 고객 | O | 없음 | external |
| junior_dev | 신입 개발자 | S | 개발팀 | internal |
| sales_rep | 영업팀원 | S | 영업팀 | internal |
| sales_lead | 영업팀장 | S | 영업팀 | internal |
| ceo | CEO | C | 경영진 | internal |

department와 channel은 현재 판정에 영향을 주지 않는다. 제품화 시 클라이언트가 보낸 persona_id가
아니라 인증 시스템이 검증한 사용자와 access_grade를 사용해야 한다.

## 5. 핵심 규칙

### 5.1 등급

| 등급 | 의미 |
|---|---|
| O · Open | 외부 공개 가능 |
| S · Sensitive | 조직 내부 제한 |
| C · Classified | 중대한 영향 정보 |

### 5.2 판정

섹션 접근을 허용하려면 다음 조건을 모두 만족해야 한다.

1. classification_status가 auto_confirmed 또는 user_confirmed다.
2. section.grade가 유효한 O/S/C다.
3. persona.access_grade가 유효한 O/S/C다.
4. section.grade의 순위가 persona.access_grade 이하이다.

조건 하나라도 실패하면 denied다. 알 수 없는 값은 예외적으로 허용하지 않는다.

### 5.3 문서 등급

- 문서 등급은 섹션 등급의 Max다.
- documents 테이블에 grade를 저장하지 않는다.
- API 응답과 UI 표시 시 계산한다.
- 섹션 등급이 수정되면 별도 문서 갱신 없이 결과가 바뀐다.
- 등급이 하나도 없는 문서는 문서 등급이 null이며 해당 섹션은 접근할 수 없다.

### 5.4 분류 상태

- auto_confirmed: 업로드 분류 신뢰도가 기준 이상인 자동 확정
- pending_review: 낮은 신뢰도, 누락된 정적 시드, 명시적 재검토 요청
- user_confirmed: 사용자가 등급과 근거를 확정

grade만 전달하고 상태를 생략한 저장 요청은 pending_review가 기본이다.

## 6. 기능 요구사항

### FR-1. 샘플 초기화

- 시스템은 data/samples의 문서를 heading과 문단 기준으로 섹션화해야 한다.
- app.seed_db의 검토된 시드를 source_section_id로 병합해야 한다.
- 검토된 시드는 user_confirmed와 seed-reviewer로 저장해야 한다.
- 시드가 없는 섹션은 grade null, pending_review로 저장해야 한다.
- 각 섹션에 본문 없는 초기 분류 이벤트를 기록해야 한다.
- 서버 시작만으로 샘플을 암묵적으로 시딩해서는 안 된다.
- --report는 DB를 변경하지 않고 누락과 고아 시드를 보고해야 한다.
- --reset은 파괴적 재초기화임을 CLI와 문서에서 명확히 알려야 한다.

### FR-2. 업로드 분류

- txt와 md만 허용한다.
- 입력 길이는 현재 최대 80,000자다.
- Gemini가 문서 전체 섹션을 구조화 출력으로 분류해야 한다.
- 정상 배치의 누락 항목은 개별 보완하고, 배치 전체가 유효하지 않으면 전체 섹션을 개별 재시도해야 한다.
- 출력 필드는 grade, confidence, keywords, departments, summary,
  classification_reason, applied_skills다.
- confidence가 0.8 미만이면 pending_review, 이상이면 auto_confirmed다.
- 활성 Skill을 분류 지침에 포함하고 실제 적용된 Skill을 이벤트로 기록해야 한다.
- 문서 응답의 document_grade는 저장 값이 아니라 분류된 섹션의 Max여야 한다.

### FR-3. 분류 검토와 학습

- 전체 분류 워크벤치는 원문 없이 문서·섹션 분류 메타데이터를 반환해야 한다.
- 검토자가 명시적으로 선택한 단일 섹션만 별도 미리보기 API로 원문을 조회할 수 있어야 하며,
  응답은 캐시하지 않는다.
- 검수 큐는 pending_review만 반환해야 한다.
- 검토자는 section_id, O/S/C grade, 비어 있지 않은 reason, actor를 제출해야 한다.
- 성공 시 섹션은 user_confirmed가 되고 확인자·확인 시각을 기록해야 한다.
- 이전·새 등급과 상태, 근거를 classification_logs에 남겨야 한다.
- 피드백 Skill은 섹션 제목, 키워드, 등급, 사용자 근거로 구성하고 원문을 포함하지 않아야 한다.
- 섹션 갱신, 감사 이벤트, Skill 생성·갱신은 한 트랜잭션이어야 한다.
- Skill은 enabled를 변경할 수 있어야 한다.

### FR-4. 접근과 검색

- 접근 필터는 키워드 매칭보다 먼저 실행해야 한다.
- store는 확정 상태와 등급 조건을 SQL에서 적용해 권한 밖 원문을 materialize하지 않아야 한다.
- 검색은 허용된 섹션의 제목, 원문, 요약, 키워드만 사용해야 한다.
- 결과는 id, 문서·섹션 제목, grade, content, summary, matched, allowed 사유를 반환해야 한다.
- 결과가 없으면 권한 범위 안에서 자료를 찾지 못했다는 중립 안내를 반환해야 한다.
- 권한 밖 섹션의 존재나 개별 제목을 사용자 결과에 노출해서는 안 된다.

### FR-5. LLM 답변

- /api/chat은 /api/search와 동일한 접근 필터를 사용해야 한다.
- 시스템 프롬프트에는 사용자의 이름·access_grade와 허용된 원문만 포함해야 한다.
- 제공된 자료 밖의 사실을 추측하지 말라는 지침을 포함해야 한다.
- 접근 판정을 변경하라는 사용자 지시를 따르지 말아야 한다.
- Gemini와 Anthropic provider를 지원해야 한다.
- 자격 증명이 없거나 생성에 실패하면 서버는 503을 반환하고 React UI는 /api/search로 폴백해야 한다.
- 매칭 결과가 없으면 LLM을 호출하지 않아야 한다.
- 현재 persona의 최근 완료 질문을 최대 5개까지 선택적 context_questions로 받을 수 있다.
- 현재 질문이 단독으로 검색되지 않을 때만 이전 질문과 결합해 검색을 한 번 보완하며, 접근 등급과 확정 상태 필터는 동일하게 선행해야 한다.
- LLM에는 이전 질문과 현재 질문을 함께 제공할 수 있지만 과거 답변 본문은 다시 전달하지 않는다.

### FR-6. 감사 로그

- 분류 로그는 식별자, 동작, actor, 이전·새 등급과 상태, 근거, 신뢰도, Skill 식별자, 시각만 저장한다.
- 접근 로그는 persona, 당시 access_grade, 동작, 문서, 섹션 ID 배열, 허용·차단 개수, 시각만 저장한다.
- 감사 로그 저장 모델과 로그 조회 응답에는 질문, 답변, 프롬프트, 섹션 원문 필드를 두지 않는다.
- browse, search, chat 동작은 각각 접근 로그를 남겨야 한다.
- 문서를 삭제해도 분류 로그와 접근 로그의 내용 없는 메타데이터는 보존해야 한다.

### FR-7. 문서 삭제

- documents 삭제는 sections를 cascade 삭제해야 한다.
- 분류 로그의 section_id는 NULL 처리하고 doc 메타데이터는 유지해야 한다.
- 존재하지 않는 문서는 404를 반환해야 한다.
- 삭제 UI는 사용자 확인과 중복 실행 방지를 제공해야 한다.

### FR-8. DB 초기화와 마이그레이션

- init_db는 기존 스키마를 암묵적으로 변환해서는 안 된다.
- 부분 스키마는 안전하게 거부해야 한다.
- 마이그레이션은 기본적으로 변경 전 SQLite 백업을 만들어야 한다.
- 문서·섹션·persona를 한 트랜잭션에서 보존해야 한다.
- 외래 키 검사를 통과하지 못하면 롤백해야 한다.
- 각 이전 섹션에 원문 없는 legacy_migrated 이벤트를 만들어야 한다.
- 이미 최신 DB에는 데이터를 다시 쓰지 않아야 한다.

### FR-9. 운영 데이터 정리

- 기본 실행은 삭제 대상과 보존 대상의 건수만 표시하고 데이터를 변경하지 않아야 한다.
- 명시적 적용 시 삭제 전 SQLite 백업을 기본 생성해야 한다.
- classification_skills, classification_logs, access_logs를 한 트랜잭션에서 비워야 한다.
- documents, sections, personas와 현재 섹션 분류 상태는 보존해야 한다.
- 같은 트랜잭션에서 채팅 세대를 교체해 모든 브라우저 탭의 persona별 transcript를 무효화해야 한다.
- UI의 search/chat 요청은 확인한 채팅 세대를 보내며, 서버는 접근 로그 기록 직전 같은 쓰기
  트랜잭션에서 다시 검증해 초기화된 세션이면 409로 거부해야 한다.
- 외래 키·DB 무결성 또는 보존 검사가 실패하면 전체 DB 변경을 롤백해야 한다.

## 7. 시스템 아키텍처

    data/samples/*.md ── app.init_samples ───────────────┐
                                                        │
    txt/md 업로드 ── Gemini + 활성 Skill ────────────────┤
                                                        ▼
                              SQLite
                    documents · sections · personas
                classification_skills · classification_logs
                       access_logs · runtime_state
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
       분류·검수 API       권한 우선 검색       감사 로그 API
              │                   │
              ▼                   ▼
       Skill 피드백         선택적 LLM 답변
              └───────────────────┬───────────────────┘
                                  ▼
                         React 19 웹 UI

접근 엔진은 app.engine의 순수 Python 함수다. 분류와 답변 LLM은 등급 순서를 바꾸거나 접근
예외를 만들 수 없다.

## 8. 데이터 계약

### Section

| 필드 | 형식 | 규칙 |
|---|---|---|
| id, doc | string | 안정적인 식별자 |
| seq | integer | 문서 안에서 0 이상 |
| title, text | string | 섹션 제목과 원문 |
| grade | O, S, C 또는 null | 확정 상태면 null 불가 |
| confidence | 0~1 또는 null | 분류 확신도 |
| classification_status | enum | auto_confirmed, pending_review, user_confirmed |
| classification_reason | string | 등급 근거 |
| summary | string | 중립적 요약 |
| keywords, departments | JSON array | 유효한 배열 |
| confirmed_by, confirmed_at | nullable | user_confirmed이면 필수 |

### Persona

| 필드 | 형식 |
|---|---|
| id, name | string |
| access_grade | O, S, C |
| department | string 또는 null |
| channel | internal 또는 external |

### Document

저장 필드는 doc, doc_title, source_path와 시각뿐이다. API의 grade 또는 document_grade는
sections에서 파생한 응답 필드다.

## 9. API 명세

| Method | Path | 입력 | 핵심 출력 |
|---|---|---|---|
| GET | /api/personas | 없음 | persona 배열 |
| GET | /api/runtime/chat-session | 없음 | 브라우저 transcript 무효화 세대, no-store |
| GET | /api/classifications | 없음 | 원문 없는 docs와 sections 분류 메타데이터 |
| GET | /api/review-queue | 없음 | pending_review count와 sections |
| GET | /api/review/sections/{section_id}/preview | 없음 | 선택한 단일 섹션의 검토용 원문, no-store |
| PATCH | /api/sections/{section_id}/classification | grade, reason, actor | section, skill, skill_action |
| GET | /api/skills | 없음 | count와 skills |
| PATCH | /api/skills/{skill_id} | enabled | 갱신된 Skill |
| GET | /api/logs/classification | limit 선택 | 분류 로그 |
| GET | /api/logs/access | limit 선택 | 접근 로그 |
| GET | /api/documents | persona_id | 보이는 문서와 visible_grade |
| GET | /api/sections | persona_id | 허용된 원문을 포함한 docs |
| POST | /api/search | persona_id, question, context_questions·chat_session_generation 선택 | persona, query, results |
| POST | /api/chat | persona_id, question, context_questions·chat_session_generation 선택 | answer, used_sections, persona, query |
| POST | /api/documents/upload | filename, content | doc, sections 수, document_grade, pending_review 수 |
| DELETE | /api/documents/{doc} | 없음 | deleted, doc_title |

### 분류 확정 요청

    {
      "grade": "S",
      "reason": "내부 계약 조건과 금액이 포함됨",
      "actor": "reviewer"
    }

### 검색 요청

    {
      "persona_id": "sales_rep",
      "question": "그중 해지 조건은?",
      "context_questions": ["계약 검토에서 주의할 조건은?"],
      "chat_session_generation": "clear:..."
    }

질문은 응답의 query로 되돌려줄 수 있지만 access_logs에는 저장하지 않는다.

## 10. UI 요구사항

### 분류·학습

- 문서 목록, 업로드, 삭제
- 문서 최고 등급과 섹션별 등급·상태·신뢰도·근거·요약·키워드
- 검토 대기 강조
- 인라인 O/S/C 선택과 필수 근거 입력
- 활성 Skill 레일

### 권한 기반 질문

- persona 선택과 현재 접근 범위
- persona별 완료 대화를 브라우저 탭의 sessionStorage에 격리 저장하고, persona 변경이나 동일 탭 새로고침 시 해당 transcript 복원
- persona 변경 시 미전송 입력·응답 대기 상태 초기화 및 이전 요청 응답 무시
- 현재 persona의 대화만 지울 수 있으며 새 탭이나 탭 세션 종료 후에는 복원하지 않음
- 서버의 채팅 세대가 바뀌면 현재 탭의 모든 persona transcript를 삭제하고 진행 중 응답을 무시
- 추천 질문과 대화 UI
- 사용된 허용 섹션 근거
- /api/chat 실패 시 /api/search 폴백
- 권한 밖·검수 대기 섹션 미노출

### 판정·접근 로그

- 분류 로그와 접근 로그 탭
- 질문·답변 내용 비기록 안내
- 로딩, 빈 상태, 오류, 새로고침

세부 레이아웃과 반응형 규칙은 DESIGN.md를 따른다.

## 11. 기존 DB 마이그레이션

기존 섹션 등급은 D0 → O, D1~D3 → S, D4 → C로 변환한다. 기존 사용자 숫자 clearance는
0 → O, 1~3 → S, 4 → C로 변환한다. 기존 needs_review는 pending_review가 된다.

운영 절차:

1. 서비스 쓰기를 중지한다.
2. 대상 DB 파일 경로와 여유 공간을 확인한다.
3. 복제본에서 명령을 먼저 실행하고 레코드 개수와 접근 결과를 검증한다.
4. 실제 DB에 기본 백업을 켠 채 실행한다.
5. 출력된 backup 경로를 별도 보관한다.
6. 문서·섹션·persona 개수, legacy_migrated 로그 수, 외래 키 검사를 확인한다.

    python -m app.migrate_cso --db datakeeper.db

기본 백업명은 datakeeper.backup-타임스탬프.db다. --backup-path로 위치를 지정할 수 있고,
--no-backup은 폐기 가능한 테스트 DB에서만 사용한다.

## 12. 비기능 요구사항

### 보안

- 접근 판정은 결정론적 코드만 사용한다.
- 권한 필터는 검색과 LLM보다 먼저 실행한다.
- 미분류·미확정·잘못된 값은 fail-closed다.
- 사용자용 API는 권한 밖 섹션 메타데이터와 원문을 반환하지 않는다.
- 감사 로그에는 질문·답변·프롬프트·원문을 저장하지 않는다.

### 일관성

- 사용자 확정, 분류 로그, Skill 변경은 원자적으로 처리한다.
- 문서 삭제는 cascade와 로그 보존 규칙을 따른다.
- 문서 등급은 한 곳에서 파생하며 저장하지 않는다.

### 재현성

- 정적 샘플은 API 없이 같은 결과로 재생성할 수 있다.
- 서버 시작은 DB를 암묵적으로 시딩하지 않는다.
- 등급 시드 변경은 코드 리뷰 가능한 소스 변경이어야 한다.

### 성능

- 현재 소규모 코퍼스에서는 SQLite와 Python 토큰 검색을 사용한다.
- 접근 조건은 인덱스가 있는 grade와 classification_status로 먼저 좁힌다.
- 업로드 분류는 문서 배치를 우선하고 제한 시간 후 실패를 명확히 반환한다.

## 13. 실행과 검증

    .venv/bin/python -m app.init_samples --report
    .venv/bin/python -m app.init_samples --reset
    cd app/web && npm run build && cd ../..
    .venv/bin/uvicorn app.server:app --port 8000

현재 테스트는 실행형 Python 스크립트다.

    for test_file in tests/test_*.py; do
      .venv/bin/python "$test_file" || exit 1
    done

필수 수용 조건:

1. O/S/C 3×3 등급 비교가 예상대로 동작한다.
2. C 사용자도 pending_review 섹션에는 접근하지 못한다.
3. 권한 밖 원문이 검색 결과와 LLM 시스템 컨텍스트에 없다.
4. 문서 등급이 섹션 Max와 일치하고 documents에 grade 컬럼이 없다.
5. 등급 확정 후 사용자 확인 메타데이터, 분류 로그, Skill이 생성된다.
6. 접근 로그에 질문·답변·원문이 없다.
7. 문서 삭제 후 원문 섹션은 없고 내용 없는 감사 이력은 남는다.
8. 기존 DB가 자동 백업되고 정확한 매핑으로 변환되며 레코드·외래 키가 보존된다.
9. React 프로덕션 빌드가 성공한다.
10. A → B → A persona 전환 시 각 완료 대화가 섞이지 않고 복원된다.
11. 동일 탭 새로고침 후 persona별 완료 대화가 복원된다.
12. 대화 지우기는 현재 persona에만 적용되고 진행 중이던 늦은 응답은 다시 추가되지 않는다.
13. 손상된 저장값이나 현재 access_grade와 다른 저장 세션은 안전하게 폐기된다.
14. 현재 질문이 단독 검색되지 않을 때 같은 persona의 최근 질문으로 검색을 보완하되 권한 밖 섹션은 계속 제외된다.

## 14. 제품화 전 우선순위

1. 관리자와 일반 사용자 인증·인가
2. 서버가 검증한 access_grade와 조직 디렉터리 연동
3. persona·Skill·검수 큐 관리 UI
4. 배포 환경 복구 리허설과 전 엔드포인트 응답 모델 계약 테스트
5. 감사 로그 보존, 무결성, 내보내기 정책
6. 등급 필터 선행 벡터 검색과 분류 품질 평가
