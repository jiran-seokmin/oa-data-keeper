---
date: 2026-07-10T09:16:23+09:00
topic: "다크 테마 적용 준비 상태"
tags: [research, codebase, frontend, react, css, dark-theme]
status: complete
last_updated: 2026-07-10
git_commit: 88ad03d
---

# Research: 다크 테마 적용 준비 상태

**Date**: 2026-07-10T09:16:23+09:00

## Research Question

현재 React 프런트엔드가 다크 테마를 바로 적용할 수 있는 상태인가?

## Summary

구조적으로는 적용 가능하지만 **바로 활성화할 수 있는 상태는 아니다**. React/CSS 기반이라 구조 변경은 필요 없으나, 현재 색상 시스템이 라이트 테마 리터럴에 강하게 결합되어 있어 의미 기반 디자인 토큰화가 선행되어야 한다. 예상 난이도는 중간이다.

## Detailed Findings

### 테마 인프라 부재

- CSS custom property와 `var()` 사용이 없다 (`app/web/src/styles.css`).
- `prefers-color-scheme`, `color-scheme`, `[data-theme]`, 테마 클래스가 없다.
- React에 theme state, 토글, `matchMedia`, `localStorage`, 루트 속성 변경 코드가 없다 (`app/web/src/App.tsx:1-819`).
- `index.html`에도 초기 테마 적용이나 color-scheme 메타가 없다 (`app/web/index.html:1-18`).

### 라이트 팔레트 결합도

- CSS에는 hex 색상 리터럴이 100회 사용되며 body, 앱 셸, 헤더, 카드, 채팅, 업로드 상태가 라이트 색상으로 고정돼 있다 (`app/web/src/styles.css:4-10`, `475-546`).
- TSX에는 hex 리터럴이 111회, 인라인 `style` 객체가 91회 사용된다 (`app/web/src/App.tsx`). 인라인 스타일은 단순한 CSS dark override보다 우선하므로 CSS만 추가해서는 완전한 다크 테마가 되지 않는다.
- A모드/D등급 팔레트도 고정값이다 (`app/web/src/App.tsx:59-72`). 상태 의미색은 다크 배경에서 대비를 별도로 검증해야 한다.

### 영향 범위

- 공통 배지와 엔티티 세그먼트 (`app/web/src/App.tsx:85-166`)
- 문서 사이드바 (`app/web/src/App.tsx:177-246`)
- 판정 그리드와 셀 (`app/web/src/App.tsx:510-564`)
- 문서 뷰어 (`app/web/src/App.tsx:575-630`)
- 채팅과 출력 가드 상태 (`app/web/src/App.tsx:634-749`)
- 판정 매트릭스 (`app/web/src/App.tsx:751-813`)

## Architecture Insights

테마 전환을 막는 프레임워크 제약은 없다. 주요 작업은 배경·surface·text·muted·border·shadow·status 색상을 semantic CSS 변수로 바꾸고, 인라인 리터럴도 해당 변수 참조로 전환하는 것이다. 그 다음 `[data-theme="dark"]` 또는 OS 설정 기반 오버라이드와 React 토글/저장 상태를 연결할 수 있다.

현재 상태를 분류하면 다음과 같다.

- 단순 다크 CSS 추가만으로 완료: 불가능
- 기존 화면 구조를 유지한 채 토큰화 후 적용: 가능
- 전체 UI 재작성 필요: 아님

## Code References

- `app/web/src/styles.css:4` — 전역 라이트 배경과 본문색
- `app/web/src/styles.css:475` — 앱 셸 라이트 배경
- `app/web/src/styles.css:485` — 헤더/경계선 라이트 팔레트
- `app/web/src/App.tsx:59` — A/D 상태 팔레트
- `app/web/src/App.tsx:85` — 고정 색상 공통 chip 스타일
- `app/web/src/App.tsx:440` — 테마 속성 없는 앱 루트

## Historical Context

`dev/`에는 다크 테마 관련 이전 조사나 구현 기록이 없다.

## Related Research

- `dev/research/20260710-goal-implementation-audit.md`

## Open Questions

- 초기 정책을 시스템 자동 추종으로 할지, 라이트/다크/시스템 3상태 토글로 할지는 현재 코드에 결정돼 있지 않다.
- A0~A4와 D0~D4 상태색의 다크 테마 팔레트도 아직 정의돼 있지 않다.
