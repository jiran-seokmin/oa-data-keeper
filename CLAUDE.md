# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트

**DataKeeper** (지란지교소프트 해커톤) — 데이터 보안 등급(D0~D4) × 사용자 접근 등급(C0~C4) × 상황을 조합해 섹션 단위 5단계 접근 모드(A0~A4)를 판정하는 접근 제어 엔진.
**해커톤 MVP의 초점은 실시간 질의응답이 아니라, 입력 데이터의 등급 분류와 페르소나별 접근 제어를 시각적으로 보여주는 것**이다.

## 참고 문서 — 계속 참조할 것 (수시 업데이트됨)

- **발표 슬라이드 (기획의 원본, 최우선 기준)**: https://docs.google.com/presentation/d/12m7Axmfq5JvCH3ikzh-Idx35PtxiDr2YtSZKGFxULmY/edit?usp=sharing
  - 이 슬라이드는 **작업 중에도 계속 보강·수정된다.** 컨셉·범위·데모 시나리오에 관련된 작업을 시작하기 전에 반드시 Google Drive 도구(`read_file_content`, fileId: `12m7Axmfq5JvCH3ikzh-Idx35PtxiDr2YtSZKGFxULmY`)로 최신 내용을 다시 읽을 것. 이전 세션에서 읽은 내용이 최신이라고 가정하지 말 것.
  - 슬라이드와 `docs/CONCEPT.md`가 어긋나면 **슬라이드가 우선**이며, 발견 즉시 CONCEPT.md 갱신을 제안한다.
- `docs/CONCEPT.md` — 설계 문서 (슬라이드 내용을 구조화한 것. 판정 매트릭스, 아키텍처, Phase 1/2/3 로드맵)

## 작업 방식 (git)

- 로컬 git 전용 (원격/push/PR 없음). **모든 작업은 워크트리 단위**:
  `git worktree add .worktrees/<작업명> -b <브랜치>` → 작업·커밋 → **main 트리로 이동 후** `git merge <브랜치> --no-ff` → `git worktree remove` → `git branch -d`
- 주의: 머지는 반드시 main 트리(저장소 루트)에서 실행한다. 워크트리 디렉터리 안에서 merge하면 자기 브랜치에 머지된다.

## 명령어

```bash
uv venv .venv && uv pip install -r requirements.txt --python .venv/bin/python  # 셋업
.venv/bin/python -m app.ingest --offline    # 수집: 사전 라벨(data/labels.json) 병합, API 불필요
.venv/bin/python -m app.ingest              # 수집: Claude 라이브 분류 (ANTHROPIC_API_KEY 필요)
.venv/bin/python tests/test_engine.py       # 판정 엔진 시나리오 테스트 (pytest 아님, 직접 실행)
.venv/bin/streamlit run app/ui.py           # 데모 UI
```

## 아키텍처 핵심 (파일 여러 개에 걸친 규칙)

- **판정은 결정론적 코드만**: `app/engine.py` + `app/policy.yaml`. 접근 판정을 LLM에 맡기지 말 것 (감사 가능성·인젝션 내성). LLM은 수집 단계의 분류·요약·엔티티 추출(`app/ingest.py`)에만 사용.
- **판정 규칙**: 최신 슬라이드 기준 A모드는 `A0 전체 접근`, `A1 노출 제한`, `A2 의미 제한`, `A3 정보 마스킹`, `A4 접근 차단`. `gap = C − D` 매트릭스(≥0→A0, −1→A2, −2→A3, ≤−3→A4) + D4 특칙(C0/C1→A4, C2→A3, C3→A1, C4→A0) + 부서 보정 1단계 완화 + 판단/집계 질의 시 A1 완화. 불변 규칙: D4는 보정 상승 불가, 미분류 섹션은 관리자 검수 전 접근 차단(default-deny), 외부 채널은 D0만 허용.
- **분류 결과는 고정·커밋**: `data/labels.json`(사전 라벨) → `data/sections.json`(산출물). 데모 재현성을 위해 데모 직전에 라이브 분류를 돌리지 않는다. 시드 문서(`data/seed/`)를 수정하면 labels.json의 해당 섹션 키(`<파일stem>#<섹션인덱스>`)도 함께 갱신해야 한다.
- **실시간 질의응답(`app/pipeline.py`)은 Phase 2** — MVP 데모의 필수 경로가 아니며, API 키가 있을 때만 동작하는 보너스. 엔진 출력의 1차 소비자는 UI의 문서 렌더링이다.
- 엔티티 마스킹은 긴 문자열부터 치환(부분 문자열 겹침 방지), 같은 엔티티는 코퍼스 전체에서 같은 플레이스홀더를 갖는다(`app/ingest.py`의 `assign_placeholders`).
