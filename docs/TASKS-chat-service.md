# TASKS — DataKeeper C/S/O 현행 구현과 잔여 작업

> 상위 문서: docs/PRD-chat-service.md
> 설계 원칙: docs/CONCEPT.md
> 현행 코드 기준일: 2026-08-30

범례: [ ] 미착수 · [~] 일부 구현 · [x] 구현 확인

## 구현 현황

- 섹션 단위 O/S/C 분류와 이진 허용·차단 엔진이 구현됐다.
- pending_review는 모든 사용자에게 default-deny다.
- 문서 등급은 섹션 Max로 파생하며 DB에 저장하지 않는다.
- 사용자 등급 확정·수정, Classification Skill 피드백, 분류·접근 로그가 구현됐다.
- 권한 필터 우선 검색과 허용 원문만 사용하는 선택적 LLM 답변이 구현됐다.
- 현행 UI는 React의 분류·학습, 권한 기반 질문, 판정·접근 로그 화면이다.
- 현재 서비스는 인증 없는 해커톤 데모다.

## A. 등급·스키마·저장 계층

- [x] O < S < C 등급 순서와 strict normalization
- [x] allowed 또는 denied만 반환하는 Decision
- [x] 누락·오류 등급과 미확정 상태 fail-closed
- [x] sections.grade와 classification_status 제약
- [x] personas.access_grade 제약
- [x] documents에서 grade 제거
- [x] 섹션 Max 문서 등급 파생
- [x] classification_skills, classification_logs, access_logs
- [x] 질문·답변·프롬프트·원문 없는 접근 로그 스키마
- [x] 외부 connection 전달 시 호출자가 트랜잭션을 관리하는 store API
- [ ] 스키마 제약과 store 오류 경로의 독립 자동화 테스트

## B. 분류 파이프라인

- [x] data/samples의 검토된 정적 O/S/C 시드
- [x] 시드 누락 시 grade null, pending_review
- [x] app.init_samples --report 비파괴 점검
- [x] app.init_samples --reset 명시적 재초기화
- [x] txt, md 업로드와 문서 단위 Gemini 배치 분류
- [x] 누락·형식 오류 항목의 섹션별 보완 분류
- [x] 신뢰도 0.8 미만 pending_review
- [x] 자동 분류와 적용 Skill 이벤트
- [x] 업로드 응답의 파생 document_grade와 pending_review 수
- [ ] 업로드 크기·시간 제한을 UI에 사전 표시
- [ ] 업로드 분류 품질용 고정 평가 데이터셋

## C. 사용자 검토와 Skill

- [x] 검수 대기 API
- [x] O/S/C 등급과 필수 근거를 받는 확정·수정 API
- [x] user_confirmed, confirmed_by, confirmed_at 저장
- [x] 이전·새 등급과 상태를 기록하는 분류 로그
- [x] 원문 없는 피드백 Skill 생성·갱신
- [x] Skill 활성 상태 API
- [x] 섹션 갱신·로그·Skill의 원자적 처리
- [x] React 인라인 검토 편집기와 활성 Skill 레일
- [ ] Skill 전체 관리 화면과 승인·버전 정책
- [ ] 검수 담당자 할당, SLA, 일괄 확정

## D. 접근·검색·답변

- [x] SQL 단계에서 확정 상태와 사용자 등급 선필터
- [x] 권한 밖 원문을 Python 검색 객체로 만들기 전 제외
- [x] 허용 집합 안에서만 제목·원문·요약·키워드 검색
- [x] 매칭 결과와 접근 사유 반환
- [x] 허용 원문만 LLM 시스템 컨텍스트에 조립
- [x] 검색 결과가 없으면 LLM 미호출
- [x] Gemini와 Anthropic 답변 provider
- [x] LLM 자격 증명·호출 실패 시 React 검색 폴백
- [x] browse, search, chat 접근 이벤트 기록
- [ ] 대규모 코퍼스용 등급 필터 선행 검색 인덱스

## E. FastAPI

- [x] GET /api/personas
- [x] GET /api/classifications
- [x] GET /api/review-queue
- [x] PATCH /api/sections/{section_id}/classification
- [x] GET, PATCH /api/skills
- [x] GET /api/logs/classification
- [x] GET /api/logs/access
- [x] GET /api/documents와 GET /api/sections
- [x] POST /api/search와 POST /api/chat
- [x] POST /api/documents/upload
- [x] DELETE /api/documents/{doc}
- [x] 빌드된 React SPA 정적 제공
- [ ] OpenAPI 응답 모델과 전 엔드포인트 계약 테스트
- [ ] 관리자 API와 일반 사용자 API 인가 분리

## F. React 프런트엔드

- [x] React 19 + TypeScript + Vite
- [x] 분류 문서·섹션·문서 최고 등급 표시
- [x] 업로드·삭제와 진행·오류 상태
- [x] 검토 대기 강조와 등급 확정·수정
- [x] 활성 Skill 표시
- [x] persona 선택과 O/S/C 접근 범위 패널
- [x] 권한 기반 질문과 사용 근거 표시
- [x] sessionStorage 기반 persona별 완료 대화 격리·복원
- [x] 최근 질문 기반 후속 질문 검색 문맥과 LLM 입력 연결
- [x] 분류·접근 로그 탭
- [x] 데스크톱·태블릿·모바일 반응형
- [ ] Skill 활성화 변경 UI
- [ ] persona·접근 등급 관리 UI
- [ ] React unit, component, E2E 테스트
- [ ] 키보드 포커스와 스크린 리더 회귀 점검

## G. DB 마이그레이션·복구

- [x] 빈 DB, 최신 DB, 기존 DB, 부분 DB 상태 판별
- [x] 기존 DB의 보수적인 O/S/C 매핑
- [x] 기본 SQLite 백업
- [x] datakeeper.backup-타임스탬프.db 파일명
- [x] 문서·섹션·persona 보존
- [x] 검토 필요 상태의 pending_review 유지
- [x] 섹션별 legacy_migrated 분류 이벤트
- [x] 단일 트랜잭션과 외래 키 검사
- [x] python -m app.migrate_cso CLI
- [ ] 저장소에 포함되는 migration 자동화 테스트
- [ ] 운영 백업 복원 리허설과 체크리스트

## H. 감사와 데이터 수명주기

- [x] 분류 이력 API와 UI
- [x] 접근 메타데이터 API와 UI
- [x] 질문·답변·프롬프트·원문 비기록
- [x] 문서 삭제 후 분류 감사 메타데이터 보존
- [x] Skill·분류 로그·접근 로그 안전 정리 CLI와 자동 백업
- [x] 서버 세대 교체를 통한 모든 persona 채팅 transcript 무효화
- [ ] 로그 조회 관리자 인가
- [ ] 보존 기간과 자동 삭제 정책
- [ ] 로그 무결성 보호와 내보내기
- [ ] persona 삭제 시 감사 식별자 보존 정책 확정

## I. 현재 검증

- [x] tests/test_engine.py: 등급 순서, 이진 판정, 검수 대기 차단, 문서 Max
- [x] tests/test_retrieval.py: 권한 밖·검수 대기 섹션의 검색 제외
- [x] tests/test_pipeline.py: 허용 원문만 LLM 컨텍스트에 포함, 검색 없음 처리
- [x] tests/test_governance.py: 사용자 확정, Skill 생성·갱신, 내용 없는 감사 로그
- [x] tests/test_migration.py: 자동 백업, 정확한 등급 변환, 보존, 외래 키 검증
- [x] tests/test_server.py: 분류 수정·Skill·검색·로그 API 계약
- [x] tests/test_upload_pipeline.py: 업로드 분류, 검수 임계값, Skill 적용
- [x] tests/test_document_delete.py: cascade 삭제와 내용 없는 감사 보존
- [x] tests/test_clear_runtime_data.py: 자동 백업, 대상 삭제, 핵심 데이터 보존, 롤백, 반복 실행
- [x] npm run build: TypeScript/Vite 프로덕션 빌드
- [~] 테스트는 현재 main 함수를 실행하는 스크립트 형식
- [ ] pytest 자동 수집 구조로 전환
- [x] 마이그레이션·분류 검토·Skill·로그 전용 회귀 테스트
- [ ] 동시 수정 충돌과 중간 장애 rollback fault-injection 테스트

## J. 제품화 전 필수 작업

- [ ] 로그인·SSO
- [ ] 서버가 검증한 access_grade
- [ ] 관리자 역할과 API별 인가
- [ ] 테넌트 격리
- [ ] 저장 데이터 암호화와 운영 키 관리
- [ ] 감사 로그 보존·무결성·개인정보 정책
- [ ] rate limit, 요청 크기 제한, 보안 헤더
- [ ] 백업·복구·마이그레이션 배포 자동화
- [ ] 분류 품질, 검수 적체, 접근 거부율 모니터링

## 실행 및 검증

    .venv/bin/python -m app.init_samples --report
    .venv/bin/python -m app.init_samples --reset
    cd app/web && npm run build && cd ../..
    .venv/bin/uvicorn app.server:app --port 8000

    for test_file in tests/test_*.py; do
      .venv/bin/python "$test_file" || exit 1
    done

기존 DB 전환은 운영 파일이 아닌 복제본에서 먼저 검증한다.

    .venv/bin/python -m app.migrate_cso --db datakeeper.db
