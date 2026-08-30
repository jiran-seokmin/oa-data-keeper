---
date: 2026-08-30T16:23:01+09:00
topic: "CEO가 00_orion_60s_demo의 해지 질문에 답하지 못하는 이유"
tags: [research, codebase, retrieval, access-control, chat, orion]
status: complete
last_updated: 2026-08-30
---

# Research: Orion 해지 질문의 CEO 답변 실패

**Date**: 2026-08-30T16:23:01+09:00

## Research Question

`00_orion_60s_demo.md` 문서에 대해 CEO가 `해지는 언제 가능한가요?`라고 물었을 때 왜 답을 하지 못하는가?

## Summary

현재 답변 실패에는 서로 독립적인 원인이 두 개 있다.

1. 현재 DB의 `해지 조건 검토 메모` 섹션은 등급 제안이 C이지만 상태가
   `pending_review`다. CEO의 접근 등급도 C이지만 검수 대기 섹션은 모든 사용자에게
   기본 차단되므로 검색 후보에 들어가지 않는다.
2. 해당 섹션을 메모리에서 C·`user_confirmed`로 가정해도 질문은 검색되지 않는다. 현재
   검색은 한국어 형태소 분석 없이 `해지는`, `언제`, `가능한가요`를 제목·원문·요약·키워드의
   단순 부분 문자열로 비교하며, 세 토큰 모두 문서 표현과 일치하지 않는다.

검색 후보가 0건이면 LLM을 호출하지 않고 관련 자료 없음 응답을 바로 반환한다. 현재 Gemini
자격 증명은 설정되어 있으므로 이 사례는 API 키나 모델 호출 실패가 직접 원인이 아니다.

## Detailed Findings

### 현재 문서와 DB 상태

- 원문에는 `서비스 공급이 30일 넘게 중단되면 즉시 해지할 수 있다`는 검토 내용이 실제로
  존재한다 (`data/uploads/00_orion_60s_demo.md:3-4`).
- 런타임 DB는 `datakeeper.db`다 (`app/db.py:11-13`).
- 현재 섹션 `00_orion_60s_demo#0`의 저장값은 다음과 같다.
  - title: `해지 조건 검토 메모 · 문단 1`
  - grade: `C`
  - confidence: `0.75`
  - classification_status: `pending_review`
  - confirmed_by: `NULL`
  - confirmed_at: `NULL`
- CEO 페르소나는 `id=ceo`, `access_grade=C`다.

업로드 분류는 신뢰도가 0.8 미만이면 등급과 무관하게 `pending_review`를 설정하고 기존
확정자·확정 시각을 비운다 (`app/upload_pipeline.py:513-520`).

### 접근 제어에서 제외되는 지점

`load_accessible_sections`는 SQL에서 `auto_confirmed` 또는 `user_confirmed`인 섹션만 읽는다
(`app/store.py:177-208`). 따라서 현재 대상 섹션의 원문은 CEO용 Python 객체나 검색 후보로
로드되지 않는다.

별도의 정책 판정도 `pending_review`를 사용자 등급과 무관하게 default-deny한다
(`app/engine.py:129-146`). C 배지는 접근 가능 상태가 아니라 제안된 등급이며, 현재 DB에는
이 섹션의 최신 사용자 확정값이 없다.

### 질문 문자열이 검색되지 않는 지점

질문 `해지는 언제 가능한가요?`의 현재 토큰화 결과는 다음과 같다.

```text
["해지는", "언제", "가능한가요"]
```

토큰화는 공백과 문장부호만 분리하고 조사·어미·어간을 정규화하지 않는다
(`app/retrieval.py:25-27`). 검색은 각 토큰이 제목, 원문, 요약 또는 키워드 결합 문자열에
그대로 포함되는지만 검사한다 (`app/retrieval.py:46-64`). 원문 표현은 `해지 조건`,
`해지할 수 있다는`, `30일 넘게 중단되면`이므로 위 세 토큰은 모두 불일치한다.

대상 섹션만 메모리에서 C·`user_confirmed`로 바꾼 읽기 전용 재현 결과는 다음과 같다.

| 질문 | 대상 섹션 결과 | 일치 토큰 |
|---|---:|---|
| `해지는 언제 가능한가요?` | 0건 | 없음 |
| `서비스 공급 중단 시 어떤 대응을 검토하고 있나요?` | 1건 | 공급, 서비스, 중단 |
| `30일 넘게 중단되면 즉시 해지할 수 있나요?` | 1건 | 30일, 넘게, 중단되면, 즉시, 해지할 |
| `해지 조건은 무엇인가요?` | 1건 | 해지 |

### 채팅 응답 경로

`POST /api/chat`은 CEO를 조회한 뒤 `pipeline.answer`를 실행한다
(`app/server.py:293-329`). 파이프라인은 접근 가능한 확정 섹션만 로드하고 검색 결과가
0건이면 `NO_MATCH_MESSAGE`를 즉시 반환한다 (`app/pipeline.py:77-110`). 이 경우 LLM 생성
함수까지 도달하지 않는다.

프런트엔드는 `/api/chat` 자체가 실패하면 `/api/search`로 전환하지만, 검색 방식과 접근
필터는 동일하므로 이 질문은 역시 0건이다 (`app/web/src/App.tsx:370-419`).

### 분류 이력과 현재 상태의 차이

DB 감사 이력에는 2026-08-30 06:37:29Z에 이 섹션이 S·`pending_review`에서
C·`user_confirmed`로 수정되고 Skill이 생성된 기록이 있다. 이후 동일 문서가 다시 적재된
이력이 여러 번 있으며, 최신 적재 시각 07:02:49Z의 현재 섹션은 Skill을 적용한 C 제안이지만
신뢰도 0.75·`pending_review`로 다시 저장됐다. 즉 과거 확정 이력과 현재 활성 섹션 상태가
다르다.

## Code References

- `data/uploads/00_orion_60s_demo.md:3-4` - 해지 조건 원문
- `app/db.py:11-13` - 런타임 SQLite 경로
- `app/upload_pipeline.py:513-520` - 신뢰도에 따른 검수 대기 설정
- `app/store.py:177-208` - 확정 상태와 사용자 등급을 적용한 SQL 선필터
- `app/engine.py:129-159` - 검수 대기 default-deny 정책
- `app/retrieval.py:25-79` - 토큰화와 단순 부분 문자열 검색
- `app/pipeline.py:77-110` - 검색 0건일 때 LLM 미호출
- `app/server.py:293-329` - 채팅 API 경로
- `app/web/src/App.tsx:370-419` - 채팅 실패 시 검색 폴백
- `docs/VIDEO-DEMO-60S.md:58-67` - 1분 데모의 검증된 공식 질문
- `docs/VIDEO-DEMO-60S.md:91-93` - C 확정 전후의 기대 접근 결과

## Architecture Insights

권한 판정은 LLM보다 먼저 수행된다. 확정되지 않았거나 권한 밖인 섹션은 검색과 LLM
컨텍스트 양쪽에서 제외된다. 그 다음 검색은 의미 기반 검색이 아니라 하나 이상의 표면 토큰이
문서 필드에 포함되는지 확인하는 결정적 문자열 검색이다. 따라서 사용자 권한, 분류 확정 상태,
질문 표면어가 모두 충족되어야 LLM 호출 단계에 도달한다.

## Historical Context (from dev/log/)

이 원인과 관련된 `dev/log/` 기록은 현재 저장소에 없다. 기존 `dev/research/` 문서는 이 질문과
직접 관련되지 않으며, 위 분류 이력은 런타임 DB의 감사 로그에서 확인했다.

## Related Research

직접 관련된 기존 조사 문서는 없다.

## Open Questions

현재 코드와 DB 상태만으로 답변 실패 원인은 모두 재현됐으며 남은 미확인 사항은 없다.
