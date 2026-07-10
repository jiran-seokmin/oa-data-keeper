# TASKS — DataKeeper 현행 구현 및 잔여 작업

> 상위 문서: `docs/PRD-chat-service.md` · 설계 원칙: `docs/CONCEPT.md`
> 현행 코드 기준일: 2026-07-10 · 기준 커밋: `54717a8`

범례: `[ ]` 미착수 · `[~]` 일부 구현 · `[x]` 구현 확인

## 구현 현황 요약

- Phase 1 MVP인 분류·판정·React 시각화는 구현됐다.
- Phase 2의 검색 기반 LLM 답변, 출력 가드, P0 자동 폴백도 구현됐다.
- 문서 뷰어와 판정 매트릭스는 구현됐지만 감사 로그는 미구현이다.
- Streamlit은 레거시 데모이며 현행 기본 UI는 React + TypeScript + Vite다.
- 기본 LLM provider는 Gemini이고, 챗 생성은 Gemini/Anthropic을 지원한다. 런타임 업로드 분류는 Gemini 전용이다.

## A. 데이터 계층 · 구현 완료

- [x] `data/samples/*.md` 4종과 `app/seed_db.py`의 정적 `GRADES`
- [x] 의미 단위 분할, 미매칭 D4 격리, 전역 플레이스홀더 부여
- [x] `data/schema.sql` 및 SQLite 접속 헬퍼
- [x] `python -m app.init_samples --reset` 명시 초기화
- [x] `app/store.py` DB 읽기·문서 삭제 계층
- [x] `.txt`/`.md` 런타임 업로드와 Gemini 분류

## B. 판정과 검색 · 구현 완료

- [x] D×C×Context 결정론적 판정과 D4/외부/default-deny 규칙
- [x] A4 제거 후 A0/A1/A2/A3 표현에서만 키워드 검색
- [x] 검색 결과에 D등급, A모드, gap, 판정 사유 포함
- [x] A3 원문 엔티티 검색 차단 및 A4 존재 은닉 회귀 스크립트

## C. FastAPI · 구현 완료

- [x] `/api/personas`, `/api/documents`, `/api/search`
- [x] `/api/sections`, `/api/matrix`
- [x] `/api/chat`과 출력 가드
- [x] `/api/documents/upload`, `DELETE /api/documents/{doc}`
- [x] 빌드된 React SPA 정적 서빙

## D. React 프런트엔드

- [x] React 19 + TypeScript + Vite 골격
- [x] 페르소나 전환과 판정 그리드
- [x] A0~A4 문서 뷰어
- [x] 섹션 × 페르소나 판정 매트릭스
- [x] `/api/chat` 우선 호출과 `/api/search` 자동 폴백
- [x] 업로드·삭제 UI
- [ ] 판단/집계 목적 토글과 `purpose` 요청 연결
- [ ] P0 폴백의 섹션 카드 렌더·gap·전체 판정 사유 표시
- [ ] 페르소나 변경 시 기존 답변의 페르소나 보존 또는 명시적 재실행
- [ ] 초기 API 오류 상태와 재시도 UI

## E. LLM 답변 레이어

- [x] DB·검색 결과 기반 `pipeline.answer()`
- [x] A4 제외 및 모드별 컨텍스트 조립
- [x] Gemini/Anthropic 챗 생성 provider
- [x] 제한 엔티티 출력 스캔, 1회 재생성, 최종 차단
- [x] API 키 또는 LLM 오류 시 FE 검색 폴백
- [~] 판정 근거 표시: 출처 D/A 배지는 표시하지만 gap·전체 사유 패널은 미구현

## F. 확장 화면

- [x] 문서 뷰어 React 이식 (`/api/sections`)
- [x] 판정 매트릭스 (`/api/matrix`)
- [ ] 감사 로그 테이블, API, 화면
- [ ] 관리자 검수 큐와 재라벨링 UI
- [~] Streamlit 정리: 레거시 구현으로 유지 중이며 폐기 여부 미결정

## G. 검증

- [x] `tests/test_engine.py`: 판정 매트릭스와 불변 규칙
- [x] `tests/test_retrieval.py`: A4/A3 검색 유출 방지와 대표 페르소나
- [x] `tests/test_pipeline.py`: Gemini/Anthropic 생성, A1/A3, 출력 가드, 검색 0건
- [x] `tests/test_upload_pipeline.py`: 배치 분류와 누락 폴백
- [x] `tests/test_document_delete.py`: 문서·섹션·엔티티 삭제
- [x] `npm run build`: TypeScript/Vite 프로덕션 빌드
- [ ] pytest 자동 수집 구조로 전환(현재 `pytest`는 0개 수집)
- [ ] React unit/component/E2E 테스트
- [ ] FastAPI 전체 엔드포인트 계약·오류 경로 테스트

## H. 실서비스화 전 필수 작업

현재 범위는 인증 없는 해커톤 데모다. 아래 항목은 구현된 것으로 간주하지 않는다.

- [ ] 로그인/SSO 및 서버가 검증한 C등급·부서·채널
- [ ] API별 인가와 관리자 전용 업로드·삭제·매트릭스 보호
- [ ] A4 문서/섹션 메타데이터 존재 은닉
- [ ] 검수 필요 분류의 승인 전 default-deny
- [ ] 저장 데이터 암호화 및 감사 로그
- [ ] A1/A3 분류 누락과 비엔티티 유출을 고려한 보안 강화

## 실행 및 검증

```bash
.venv/bin/python -m app.init_samples --reset
cd app/web && npm run build && cd ../..
.venv/bin/uvicorn app.server:app --port 8000

for f in tests/test_*.py; do .venv/bin/python "$f" || exit 1; done
```
