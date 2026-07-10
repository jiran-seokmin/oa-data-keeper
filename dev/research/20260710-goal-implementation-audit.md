---
date: 2026-07-10T08:43:57+09:00
topic: "현재 코드베이스의 목표와 실제 구현 정합성 점검"
tags: [research, codebase, datakeeper, access-control, security]
status: complete
last_updated: 2026-07-10
last_updated_by: Codex
last_updated_note: "Documentation inconsistencies corrected across DESIGN, README, CONCEPT, PRD, and TASKS"
git_commit: 54717a8
---

# Research: 목표와 실제 구현 정합성

**Date**: 2026-07-10T08:43:57+09:00

## Research Question

현재 코드베이스가 문서에 적힌 DataKeeper의 목표를 실제로 제대로 구현했는가?

## Summary

코드는 **해커톤 데모/MVP로서는 핵심을 상당 부분 구현**했다. D×C×Context의 결정론적 판정, 섹션 단위 A0~A4 렌더, 샘플 DB 재생성, 검색 전 A4 제거, 페르소나별 뷰어·매트릭스, LLM 앞단 접근제어와 폴백이 실제 연결돼 있다.

그러나 **실제 접근제어 서비스로는 구현됐다고 볼 수 없다.** 인증·인가가 없고 요청자가 CEO 페르소나와 판단 목적을 직접 선택할 수 있다. 차단 문서/섹션의 존재와 메타데이터를 여러 API가 노출하며, A1은 제한 원문을 LLM 프롬프트에 넣고 출력 가드는 추출된 엔티티의 정확 문자열만 검사한다. 즉 현재 보안 모델은 신뢰할 수 있는 데모 페르소나를 전제로 한다.

또한 제품 기준 문서가 서로 충돌한다. 특히 `DESIGN.md`는 DataKeeper가 아닌 `officeclaw` 설계이고, Phase 1/2 범위와 구현 현황도 README, CONCEPT, PRD, TASKS 사이에서 다르다.

## Detailed Findings

### 1. 문서상 목표

- 핵심 목표는 D0~D4 데이터 등급, C0~C4 사용자 등급, Context를 조합해 섹션별 A0~A4를 판정하고 같은 문서를 페르소나별로 다르게 시각화하는 것이다 (`README.md:1-8`, `docs/CONCEPT.md:1-14`).
- 핵심 안전 불변식은 결정론적 판정, 외부 채널 D0 하드캡, 미분류 default-deny, A4의 검색·LLM 컨텍스트 진입 금지다 (`README.md:105-113`, `docs/PRD-chat-service.md:32-37`).
- Phase 2는 접근제어된 검색 결과만 LLM에 전달하고 출력 가드를 적용하며, 실패 시 무-LLM 검색으로 폴백하는 것이다 (`docs/PRD-chat-service.md:50-54`).

### 2. 제대로 구현된 부분

- `engine.decide()`가 gap, D4 특칙, 외부 채널, 부서 및 판단 목적 보정을 결정론적으로 수행한다 (`app/engine.py:52-135`).
- 샘플 4문서를 정적 등급 시드와 병합해 63개 의미 단위 섹션으로 SQLite에 재생성한다 (`app/seed_db.py:393-443`, `app/init_samples.py`). 조사 시 미매칭은 0건이었다.
- 검색은 판정 후 A4를 제거한 다음 A0 원문/A1 메타데이터/A2 요약/A3 마스킹 표현에서만 토큰을 찾는다 (`app/retrieval.py:42-125`).
- 챗은 검색 결과만 프롬프트에 조립하며, 검색 0건이면 LLM을 호출하지 않는다 (`app/pipeline.py:174-240`).
- React UI에 판정 그리드, 문서 뷰어, 매트릭스, 채팅, 업로드, 삭제, 페르소나 전환이 연결돼 있다 (`app/web/src/App.tsx:300-485`).
- 프런트 프로덕션 빌드는 성공했다. 다섯 Python 실행형 테스트도 모두 통과했다.

### 3. 목표를 훼손하는 핵심 간극

#### Critical: 실사용 인증·인가가 없다

- API는 `persona_id`를 요청 본문/쿼리에서 그대로 받아 DB 페르소나를 선택한다 (`app/server.py:44-59`). 로그인, 세션, SSO, 조직도 연동, 토큰 검증이 없다.
- `/api/personas`가 CEO를 포함한 모든 페르소나 ID를 공개한다 (`app/server.py:62-64`). 따라서 호출자는 최고 권한을 자칭할 수 있다.
- 업로드, 삭제, 전체 매트릭스 조회도 인증 없이 가능하고 CORS가 `*`다 (`app/server.py:35-39`, `app/server.py:87-108`, `app/server.py:144-164`).
- 결론적으로 C등급은 보안 주체의 검증된 속성이 아니라 데모용 UI 선택값이다.

#### Critical: 존재 은닉이 검색 경로 밖에서는 깨진다

- `/api/documents`는 접근 불가 문서도 제목, 경로, 섹션 수, 잠금 상태로 열거한다 (`app/server.py:67-82`).
- `/api/sections`는 A4 섹션도 ID, 제목, D등급, 키워드, 요약, 부서와 함께 반환한다 (`app/server.py:119-139`, `app/views.py:62-81`).
- `/api/matrix`는 전 섹션과 전 페르소나 판정을 공개한다 (`app/server.py:144-164`).
- 이는 A4의 “존재 자체를 노출하지 않음”과 충돌한다. 시각화 데모 목적이라는 코드 주석은 있으나 API 보안 경계가 분리돼 있지 않다.

#### High: A1/A3/출력 가드는 완전한 기밀성 경계가 아니다

- A1은 제한 원문 전체를 LLM 프롬프트에 전달한다 (`app/pipeline.py:91-102`, `app/pipeline.py:203-220`).
- 출력 가드는 제한 섹션에서 추출된 엔티티의 정확 문자열만 찾는다 (`app/pipeline.py:105-118`, `app/pipeline.py:225-238`). 누락 엔티티, 변형 표현, 비엔티티 민감 문장이나 추론 유출은 탐지하지 않는다.
- 뷰어 A1 응답의 `blur_text`도 엔티티만 치환한 나머지 원문을 API로 전송한다 (`app/views.py:50-53`, `app/views.py:85-86`). CSS blur는 접근통제가 아니다.
- A3 역시 분류기가 완전하게 찾은 엔티티만 치환하므로 분류 누락이 곧 원문 노출이 된다 (`app/pipeline.py:84-101`).

#### High: 검수 플래그가 승인 게이트가 아니다

- 업로드 분류 결과에서 낮은 신뢰도 또는 D3/D4는 `needs_review`로 표시하지만 이미 security level을 가진 채 DB에 저장된다 (`app/upload_pipeline.py:378-480`).
- 엔진의 default-deny는 등급이 `None`일 때만 적용되므로 검수 전 자료도 즉시 검색/열람 대상이다 (`app/engine.py:81-85`).

#### Medium: 정책·공급자 설정과 실제 동작 불일치

- 기본 gap 매트릭스는 `policy.yaml`에도 있지만 엔진 함수가 하드코딩해 YAML 변경이 반영되지 않는다 (`app/engine.py:52-59`, `app/engine.py:105`).
- 챗은 Gemini/Anthropic을 지원하지만 업로드 분류는 Gemini 전용이다 (`app/pipeline.py:121-156`, `app/upload_pipeline.py:261-264`). Anthropic 설정에서 서비스 기능이 일관되게 동작하지 않는다.
- 저장 DB는 원문과 민감 엔티티를 평문으로 보관하며 암호화, 감사 로그, 문서 ACL 스키마가 없다 (`data/schema.sql:1-40`).

### 4. 프런트 요구사항 대비 간극

- README/PRD가 요구한 판단·집계 목적 토글이 없고 모든 웹 요청이 `purpose: "info"`로 고정된다 (`app/web/src/App.tsx:332`). 엔진 기능은 있으나 UI에서 시연할 수 없다.
- 무-LLM 폴백은 섹션 카드의 렌더 본문·요약·마스킹·gap·판정 사유를 보여주지 않고, 최대 3개 출처 칩으로 축약한다 (`app/web/src/App.tsx:343-350`, `app/web/src/App.tsx:720-729`). PRD의 판정 투명성 요구를 충족하지 못한다.
- 페르소나 변경 시 기존 챗을 재계산하지 않지만 화면은 재계산된다고 안내하고, 과거 메시지에도 현재 페르소나 아바타를 붙인다 (`app/web/src/App.tsx:307-313`, `app/web/src/App.tsx:698-713`).
- README가 현재 데모 흐름으로 열거한 감사 로그 화면은 React 앱에 없다 (`README.md:66-76`, `app/web/src/App.tsx:432-437`).

### 5. 테스트와 검증 상태

- `npm run build`: 성공.
- `python tests/test_engine.py`, `test_retrieval.py`, `test_pipeline.py`, `test_upload_pipeline.py`, `test_document_delete.py`: 모두 성공.
- 그러나 `pytest -q`: **0 tests collected**. 파일들이 pytest 테스트 함수가 아니라 `main()` 실행형 스크립트여서 일반 CI의 자동 회귀 검증에 잡히지 않는다.
- 프런트 unit/component/E2E 테스트는 없고, 서버 API 계약·인가·오류 경로·뷰 payload 유출 불변식도 자동 테스트되지 않는다.

## Architecture Insights

현재 구조는 “보안 제품”보다는 “접근 판정 아이디어를 보여주는 신뢰 환경의 데모”로 일관되게 이해하면 잘 맞는다. 엔진과 검색 경로의 규칙은 비교적 명료하지만, 인증된 사용자 컨텍스트와 API 데이터 경계가 없어서 실제 공격자를 상정한 접근통제는 성립하지 않는다.

검색은 의미/벡터 검색이 아니라 렌더된 문자열에 대한 단순 부분 일치다 (`app/retrieval.py:36-39`, `app/retrieval.py:102-124`). 수집도 외부 ECM 커넥터가 아니라 정적 Markdown 시드와 txt/md 수동 업로드다.

## Documentation Consistency

- `DESIGN.md:1-14`는 별도 제품 `officeclaw`의 로컬 ECM 색인 데스크톱 앱 설계로, 이 저장소의 DataKeeper 목표와 무관하다.
- `docs/CONCEPT.md`는 Phase 1 시각화를 현재 범위로 두지만 README는 React 챗을 기본 경로로 설명하고 실제 코드는 Phase 2 일부까지 구현했다.
- `docs/TASKS-chat-service.md:9-12`는 E/F가 남았다고 하지만 E와 F의 뷰어·매트릭스가 코드에 있다. 반대로 모든 세부 체크박스는 미완료 상태다.
- CONCEPT/PRD/README 사이에 Streamlit vs React, Claude vs Gemini, vanilla JS vs React 등 기술 스택 설명이 충돌한다.
- `dev/` 역사 문서는 기존에 없었고, 이번 조사 문서가 첫 항목이다.

## Code References

- `app/engine.py:76` — 핵심 판정 함수
- `app/retrieval.py:83` — 접근제어 후 검색
- `app/pipeline.py:174` — LLM 답변 및 출력 가드
- `app/server.py:35` — 인증 없는 API 애플리케이션 경계
- `app/views.py:62` — 제한 모드의 UI payload 조립
- `app/upload_pipeline.py:378` — 업로드 분류·저장
- `app/web/src/App.tsx:300` — FE 데이터/API 연결
- `data/schema.sql:1` — 현재 4개 테이블 스키마

## Open Questions

- `CLAUDE.md`는 발표 슬라이드를 최상위 기준으로 지정하지만 최신 외부 슬라이드는 이번 로컬 조사 범위에 없었다. 따라서 발표본과의 최종 정합성은 확인하지 못했다.
- 의도한 평가 기준이 해커톤 데모인지, 내부 PoC인지, 실제 보안 서비스인지에 따라 “완료”의 의미가 크게 달라진다.

## Follow-up Research 2026-07-10T08:55:00+09:00

사용자 요청에 따라 문서 불일치를 현행 코드 기준으로 정리했다.

- `DESIGN.md`를 무관한 officeclaw 사양에서 DataKeeper React UI 현행 설계로 교체했다.
- `README.md`에서 미구현 감사 로그와 판단 목적 토글을 현재 제공 기능처럼 설명하던 부분을 정정했다.
- `docs/CONCEPT.md`의 Phase 2를 “추후 구현”에서 “키워드 검색 기반 선택 기능 구현”으로 현행화하고, React/Gemini/SQLite 스택과 미구현 거버넌스를 명시했다.
- `docs/PRD-chat-service.md`의 JSON/Streamlit/vanilla JS/Anthropic-only 과거 상태를 SQLite/React/provider 선택 구조에 맞춰 갱신했다.
- `docs/TASKS-chat-service.md`를 실제 완료·부분 구현·미구현 상태가 드러나는 체크리스트로 재작성했다.
