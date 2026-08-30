# CLAUDE.md

## 프로젝트

DataKeeper는 문서를 섹션 단위로 분리해 N2SF 기반 C/S/O 등급을 판정하고,
사용자 등급으로 허용된 섹션만 검색·LLM 컨텍스트에 전달하는 데이터 보안 엔진이다.

- C — Classified · 기밀
- S — Sensitive · 민감
- O — Open · 공개
- 순서: O < S < C
- 레거시 변환: D0→O, D1~D3→S, D4→C
- 문서 등급: 포함 섹션의 최고 등급(Max)

## 기획 기준

- 발표 자료 docs/DataKeeper MVP 1차.pdf의 19페이지 이후가 현재 MVP 기준이다.
- 이전 D0~D4 × C0~C4 → A0~A4 모델은 폐기되었다.
- 권한 밖 섹션은 마스킹·요약하지 않고 조회·검색·LLM 컨텍스트에서 완전히 제외한다.
- 질문·답변 본문은 감사 로그에 저장하지 않는다.

## 핵심 흐름

1. 문서를 섹션으로 분리하고 C/S/O 등급·요약·확신도·근거를 자동 판정한다.
2. 확신도 0.8 미만은 pending_review로 저장하고 모든 사용자에게 기본 차단한다.
3. 사용자가 등급을 확정·수정한다.
4. 수정 근거를 classification_skills에 저장해 다음 자동 분류 프롬프트에 반영한다.
5. 자동 판정·사용자 확정/수정·Skill 생성/적용은 classification_logs에 남긴다.
6. 검색·챗에 실제 사용한 섹션 ID만 access_logs에 남긴다.

## 명령어

    uv venv .venv --relocatable
    uv pip install -r requirements.txt --python .venv/bin/python

    # 기존 D/C/A DB를 보존 백업 후 C/S/O로 변환
    .venv/bin/python -m app.migrate_cso

    # 샘플로 새 DB를 만들 때만 사용(기존 DB 전체 초기화)
    .venv/bin/python -m app.init_samples --reset
    .venv/bin/python -m app.init_samples --report

    # 기본 미리보기, --apply에서만 Skill·채팅 세션·로그 정리
    .venv/bin/python -m app.clear_runtime_data
    .venv/bin/python -m app.clear_runtime_data --apply

    cd app/web && npm install && npm run build && cd ../..
    .venv/bin/uvicorn app.server:app --port 8000

    .venv/bin/python tests/test_engine.py
    .venv/bin/python tests/test_retrieval.py
    .venv/bin/python tests/test_pipeline.py
    .venv/bin/python tests/test_governance.py
    .venv/bin/python tests/test_migration.py
    .venv/bin/python tests/test_server.py
    .venv/bin/python tests/test_upload_pipeline.py
    .venv/bin/python tests/test_document_delete.py
    .venv/bin/python tests/test_clear_runtime_data.py

## 아키텍처 규칙

- 접근 판정은 app/engine.py의 결정론적 이진 판정만 사용한다.
- LLM은 app/upload_pipeline.py의 분류·요약과 app/pipeline.py의 허용 데이터 기반 답변 생성에만 사용한다.
- pending_review, 잘못된 등급, 사용자 등급 누락은 모두 default-deny다.
- 문서 등급은 저장하지 않고 섹션 등급의 Max로 파생한다.
- 사용자 수정은 API/저장 계층을 통해서만 수행해 Skill과 감사 이력을 함께 남긴다.
- DB 스키마를 바꿀 때 기존 런타임 업로드를 지우는 --reset을 마이그레이션으로 사용하지 않는다.
- datakeeper.db는 gitignore 대상이며, 서버는 샘플을 암묵적으로 시딩하지 않는다.

## 작업 방식

기존 사용자 변경을 보존하고, 데이터 삭제·DB 초기화 전에는 대상과 복구 경로를 확인한다.
프로젝트의 기존 로컬 git/worktree 운영 규칙을 따른다.
