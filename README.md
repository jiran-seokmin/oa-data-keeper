# DataKeeper — 접근 제어 엔진 MVP

**All Data, Safe for Everyone (모든 데이터를, 모두가 안전하게)** · 지란지교소프트

데이터 보안 등급(D0~D4) × 사용자 접근 등급(C0~C4) × 상황(부서·목적·채널)을 조합해
**섹션 단위로 5단계 접근 모드(A0~A4)를 판정**하는 접근 제어 엔진 데모.
해커톤 MVP의 초점은 **입력 데이터의 등급 분류와 페르소나별 접근 제어를 시각적으로 보여주는 것**이다
(실시간 질의응답은 Phase 2). 설계 배경과 로드맵은 [docs/CONCEPT.md](docs/CONCEPT.md) 참조.

## 빠른 시작

```bash
uv venv .venv
uv pip install -r requirements.txt --python .venv/bin/python

# 1) 수집 파이프라인 (사전 분류 라벨 사용 — API 불필요)
.venv/bin/python -m app.ingest --offline

# 2) 데모 UI — 뷰어·매트릭스는 API 키 없이 완전 동작
.venv/bin/streamlit run app/ui.py
```

- **MVP 데모(문서 뷰어, 판정 매트릭스)는 API 호출 없이 결정론적으로 동작**한다.
- 라이브 분류로 라벨을 다시 만들려면: `.venv/bin/python -m app.ingest` (`ANTHROPIC_API_KEY` 필요).
- Phase 2 질의응답 탭도 `ANTHROPIC_API_KEY` 필요. 모델 변경: `ACE_MODEL` (기본 `claude-opus-4-8`).

## 데모 흐름

**킬러 장면: 같은 문서를 열어 둔 채 사이드바에서 페르소나만 바꾸면, 섹션별 렌더링이 실시간으로 바뀐다.**

1. **📄 문서 뷰어** — "영업 파이프라인 현황" 문서를 열고 외부 고객 → 신입 → 영업팀원 → 팀장 → CEO 순회:
   - ✅ A4 원문 · 🔍 A2 요약 카드 · 🎭 A1 엔티티 마스킹 하이라이트 · 🧠 A3 블러+"AI 추론 전용" 배지 · 🚫 A0 잠금
   - 섹션마다 D등급 배지와 판정 사유(gap, 부서 보정)가 함께 표시됨
2. **🗺️ 판정 매트릭스** — 섹션 32개 × 페르소나 5개 판정을 색상 히트맵 한 화면으로
3. **⚙️ 수집 결과** — 문서가 섹션·등급·키워드·엔티티·A2 요약으로 분해된 산출물
4. **📋 감사 로그** — 누가 어떤 문서를 어떤 모드 조합으로 열람했는지
5. **💬 질의응답 (Phase 2 미리보기)** — 판정 결과를 LLM 컨텍스트 조립에 적용한 실시간 답변 + 출력 가드 (보너스, API 키 필요)

사이드바의 "판단/집계 목적" 토글을 켜면 A1/A2 섹션이 A3로 승격되는 것도 시연할 수 있다.

## 구조

```
app/
  engine.py      판정 엔진 (순수 파이썬 — LLM 미사용, 감사 가능)
  policy.yaml    gap 매트릭스 + 컨텍스트 보정 정책
  personas.yaml  데모 페르소나 (실서비스: SSO/조직도 연동)
  keywords.yaml  관리자 등록 키워드 → 등급 힌트 (라이브 분류용)
  ingest.py      수집: 섹션 분리 → 분류 → sections.json
  pipeline.py    [Phase 2] 질의: 판정 → 모드별 변환 → 생성 → 출력 가드
  ui.py          Streamlit 데모 (문서 뷰어 + 매트릭스 + 수집 결과 + 감사 로그)
data/
  seed/          가상 회사 문서 12개 (D0~D4 혼재)
  labels.json    사전 분류 라벨 (데모 재현성용으로 커밋)
  sections.json  수집 산출물 (ingest 실행 결과)
tests/
  test_engine.py 판정 시나리오 테스트: python tests/test_engine.py
```

## 판정 규칙 요약

- `gap = C − D`: `≥0 → A4`, `−1 → A2`, `−2 → A1`, `≤−3 → A0`
- D4 최고 접근 정보는 최신 발표 매트릭스 특칙 적용: `C0/C1 → A0`, `C2 → A1`, `C3 → A3`, `C4 → A4`
- 담당 부서 데이터 `+1단계`, 판단/집계 목적은 A1/A2 → **A3(추론 근거 전용)** 승격
- 외부 채널은 D0만 A4, 나머지 전부 A0 (하드 캡)
- **D4는 어떤 보정으로도 상승 불가**, 미분류 섹션은 관리자 검수 전 접근 차단 (default-deny)
- 판정은 결정론적 코드로만 — LLM은 수집 단계의 분류·요약·엔티티 추출에만 사용
