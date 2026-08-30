---
date: 2026-08-30T16:24:34+09:00
topic: "권한 기반 질문에서 사용자별 마지막 채팅 세션을 기억하는지"
tags: [research, codebase, chat, session, frontend, api, audit]
status: complete
last_updated: 2026-08-30
last_updated_by: Codex
last_updated_note: "Added persona-scoped transcript persistence and recent-question follow-up context"
git_commit: 95d7c8e
---

# Research: 권한 기반 질문의 채팅 세션 기억 범위

**Date**: 2026-08-30T16:24:34+09:00
**Follow-up implemented**: 2026-08-30T16:35:23+09:00

## Research Question

권한 기반 질문 시 해당 사용자의 마지막 채팅 세션을 기억할 수 있는가?

## Summary

후속 구현으로 프런트엔드는 완료된 화면 transcript를 프로필별로 브라우저 탭의
`sessionStorage`에 저장한다. 같은 탭에서 프로필을 왕복하거나 새로고침하면 각 프로필의 마지막
완료 대화가 격리된 상태로 복원된다. `현재 대화 지우기`는 선택한 프로필의 transcript와 진행 중
응답만 제거하고 다른 프로필에는 영향을 주지 않는다.

저장 범위는 브라우저 탭 세션으로 제한된다. 새 탭에는 공유되지 않고 탭을 닫으면 사라지며,
미전송 입력·대기 중 질문·로딩 상태는 저장하지 않는다. 저장된 데이터가 손상됐거나 프로필의
이름·access_grade가 달라졌거나 출처 등급이 현재 권한을 넘으면 해당 캐시를 폐기한다.

백엔드는 세션을 저장하지 않는 stateless 구조를 유지하지만, 프런트엔드가 현재 프로필의 최근
완료 질문 최대 5개를 `context_questions`로 매 요청에 전달한다. 현재 질문이 단독 검색되지 않을
때만 이전 질문으로 검색을 한 번 보완하고, LLM에는 이전 질문과 현재 질문을 함께 제공한다. 과거
답변 본문은 다시 보내지 않으며 DB와 감사 로그에도 질문·답변·세션을 저장하지 않는다.

## Detailed Findings

### 프로필별 프런트엔드 transcript

- 저장 모델은 `Record<personaId, StoredChatSession>`이며 각 항목에 저장 당시 프로필 이름,
  access_grade와 완료 메시지 배열을 둔다 (`app/web/src/App.tsx:84-100`).
- 저장 envelope는 버전을 포함하고 최근 완료 메시지를 프로필당 최대 50개로 제한한다
  (`app/web/src/App.tsx:117-125`).
- `sessionStorage`의 JSON은 신뢰하지 않는다. 루트 구조, 버전, 프로필 키, 메시지와 출처의 필드 및
  O/S/C 등급을 런타임에서 검증하고, 읽기·파싱·쓰기 실패 시 앱은 메모리 상태로 계속 동작한다
  (`app/web/src/App.tsx:141-206`).
- React 상태는 프로필별 map으로 초기화되고 변경 때마다 하나의 versioned envelope로 저장된다
  (`app/web/src/App.tsx:296-317`, `app/web/src/App.tsx:372-399`).
- `/api/personas`를 받은 뒤 존재하지 않는 프로필, 이름이나 access_grade가 달라진 세션, 현재
  접근 등급보다 높은 출처가 섞인 메시지를 폐기한다 (`app/web/src/App.tsx:375-399`). 이는 같은
  persona ID의 권한이 낮아졌을 때 과거 고권한 답변이 다시 보이는 것을 막는다.
- 현재 표시 대화는 선택 프로필의 저장 항목에서 파생한다 (`app/web/src/App.tsx:401-405`).
- 답변 성공, 검색 폴백과 최종 오류는 모두 요청을 시작한 프로필의 세션에 추가한다
  (`app/web/src/App.tsx:507-577`). 새 요청에는 현재 프로필의 최근 정상 완료 질문 최대 5개만
  포함하고 과거 답변은 포함하지 않는다 (`app/web/src/App.tsx:511-542`).

### 프로필 전환·삭제와 비동기 응답

- 프로필 전환은 기존 transcript를 삭제하지 않고 현재 입력·pending·loading만 초기화한다
  (`app/web/src/App.tsx:497-504`). 선택 프로필이 바뀌면 해당 map 항목이 즉시 표시된다.
- 전환할 때 `chatSessionRef` 세대 번호를 증가시키므로 전환 전에 시작된 늦은 응답은 어느 저장
  세션에도 추가되지 않는다 (`app/web/src/App.tsx:499-517`, `app/web/src/App.tsx:531-569`).
- 대화 삭제도 세대 번호를 증가시키고 현재 프로필 key만 제거한다. 진행 중 요청이 삭제 후
  완료돼 transcript를 되살리는 것도 막는다 (`app/web/src/App.tsx:483-495`).
- 질문 화면은 완료 메시지나 진행 중 질문이 있으면 `현재 대화 지우기`를 제공하고, 이 탭에서
  현재 프로필의 완료 대화를 기억한다는 범위를 표시한다 (`app/web/src/App.tsx:708-717`).

### API와 LLM의 대화 문맥

- 검색·채팅 요청 모델은 `persona_id`, 현재 `question`과 선택적 `context_questions` 최대 5개를
  가진다 (`app/server.py:54-60`). 서버는 이 문맥을 처리하지만 저장하지 않는다.
- 검색은 현재 질문을 먼저 실행하고 결과가 없을 때만 정규화된 최근 질문과 현재 질문을 결합해
  한 번 더 수행한다 (`app/retrieval.py:32-65`, `app/retrieval.py:105-119`). 두 경로 모두 SQL에서
  먼저 현재 persona에게 허용된 확정 섹션만 읽는다.
- `/api/search`와 `/api/chat`은 동일한 context_questions를 검색에 사용한다
  (`app/server.py:276-325`). 세션 생성·조회·갱신 단계는 없다.
- LLM 입력에는 이전 질문을 생략 표현 이해용 참고로 명시하고, 현재 접근 등급으로 다시 검색한
  허용 원문만 시스템 컨텍스트에 둔다 (`app/pipeline.py:19-31`, `app/pipeline.py:79-133`). 과거
  assistant 답변은 LLM에 다시 전달하지 않는다.

### DB와 감사 로그

- 현재 스키마에는 채팅 세션이나 메시지 테이블이 없다 (`data/schema.sql:5-98`).
- 접근 로그는 페르소나, 당시 접근 등급, 동작, 문서, 사용 섹션 ID, 허용·차단 개수와 시각만
  저장한다. 질문·답변·프롬프트·원문 필드는 의도적으로 제외돼 있다
  (`data/schema.sql:87-104`).
- 저장 함수도 위 메타데이터만 입력받아 기록한다 (`app/store.py:744-778`). 페르소나별 최신 접근
  이벤트 조회는 가능하지만 세션 식별자와 본문이 없어 마지막 대화를 재구성할 수 없다
  (`app/store.py:781-803`).
- 질문을 응답의 `query`로 돌려줄 수는 있지만 접근 로그에는 저장하지 않는다는 정책이 유지된다
  (`docs/PRD-chat-service.md:286-293`).

### 상태 수명 요약

| 상황 | 화면 transcript | 다음 질문의 LLM 문맥 |
| --- | --- | --- |
| 같은 프로필, 같은 탭 | 유지 | 최근 질문 최대 5개 사용 |
| 앱 내부 메뉴 이동 후 복귀 | 유지 | 최근 질문 최대 5개 사용 |
| A → B → A 프로필 전환 | A와 B를 격리해 각각 복원 | 선택 프로필 질문만 사용 |
| 같은 탭 새로고침 | 프로필별로 복원 | 복원된 최근 질문 사용 |
| 현재 대화 지우기 | 현재 프로필만 삭제 | 현재 프로필 문맥도 초기화 |
| 새 탭 또는 탭 종료 후 재접속 | 복원하지 않음 | 이전 문맥 없음 |

## Code References

- `app/web/src/App.tsx:84-206` - 저장 타입, 런타임 검증, sessionStorage 읽기·쓰기
- `app/web/src/App.tsx:296-405` - 프로필별 상태, 영속화, 권한 변경 시 폐기, 현재 대화 파생
- `app/web/src/App.tsx:467-504` - 프로필별 추가·삭제·전환
- `app/web/src/App.tsx:507-577` - 최근 질문 전달과 비동기 응답 격리
- `app/server.py:54-60` - 선택적 최근 질문을 받는 요청 모델
- `app/server.py:276-325` - 문맥을 받지만 저장하지 않는 검색·채팅 API
- `app/retrieval.py:32-65` - 최근 질문 정규화와 접근 필터 우선 검색
- `app/retrieval.py:105-119` - 현재 질문 실패 시에만 수행하는 문맥 보완 검색
- `app/pipeline.py:79-133` - 이전 질문과 현재 질문을 조립하는 LLM 입력
- `data/schema.sql:87-104` - 내용 없는 접근 로그 스키마
- `DESIGN.md:121-142` - 프로필별 transcript 수명과 삭제 동작
- `docs/PRD-chat-service.md:305-314` - 권한 기반 질문 UI 요구사항

## Architecture Insights

화면 transcript 기억은 브라우저 탭에 있고 서버는 세션을 저장하지 않는다. 프런트엔드가 선택한
프로필의 최근 질문만 매 요청에 다시 전달해 후속 질문을 보완하며, 서버는 매번 현재 권한으로
허용 원문을 새로 계산한다. 과거 답변을 다시 입력하지 않아 이전 고권한 답변이나 오래된 생성
문장이 새 답변 근거로 재유입되지 않는다. 프로필 전환 및 삭제 시 요청 세대 번호를 바꿔 서로
다른 접근 등급의 늦은 응답도 transcript에 섞이지 않게 한다.

## Historical Context (from dev/log/)

현재 저장소에는 `dev/log/` 디렉터리가 없다. 과거 코드베이스 조사에서는 인증·로그인 세션 없이
호출자가 데모 페르소나를 선택하는 구조라고 기록했다
(`dev/research/20260710-goal-implementation-audit.md:47-52`). 이 전제는 현재도 같으며 transcript
복원은 인증된 사용자 계정 저장소가 아니라 데모 브라우저 탭에 한정된다.

## Related Research

- `dev/research/20260830-orion-ceo-chat-no-answer.md` - 단일 채팅 요청에서 접근 필터와 검색이
  답변 생성까지 이어지는 경로

## Follow-up Research 2026-08-30T16:35:23+09:00

사용자 요청에 따라 단일 메모리 배열을 프로필별 versioned sessionStorage map으로 교체했다.
후속 질문도 동작하도록 API 계약에 선택적 `context_questions`를 추가했지만 서버에는 저장하지
않는다. 현재 질문이 독립적으로 검색되면 과거 질문을 검색에 섞지 않고, 독립 검색이 실패한
경우에만 현재 프로필의 최근 질문으로 보완한다. LLM에는 질문 문맥만 전달하며 과거 답변은
전달하지 않는다.

## Open Questions

현재 구현 범위에서 남은 미확인 사항은 없다.
