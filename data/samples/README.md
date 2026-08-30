# 검토된 샘플 문서

이 폴더에는 app.init_samples가 결정론적으로 DB에 넣는 기본 코퍼스 원문을 보관한다. 현재
샘플은 계약 협상, 인사·보상, 보안 점검 문서 3종이며 모든 내용은 데모용 가상 데이터다.

## 작성 규칙

- 문서는 UTF-8 Markdown이어야 한다.
- 첫 번째 # heading은 문서 제목, ## heading은 시드 연결 단위다.
- ## 아래의 빈 줄로 구분된 각 문단은 독립 섹션이 된다.
- 원문에 O/S/C 등급이나 분류 상태를 직접 적지 않는다.
- 문서를 추가하거나 heading 순서를 바꾸면 app/seed_db.py의 GRADES 시드를 함께 갱신한다.
- 각 시드에는 grade, keywords, departments, summary와 필요 시 confidence·근거를 둔다.
- 시드가 없는 섹션은 grade null, pending_review로 저장되어 사용자 접근이 차단된다.
- 사용자 검토 전 자동 공개를 피하기 위해 누락 시 임의의 기본 등급을 넣지 않는다.

## 점검과 초기화

다음 명령은 DB를 변경하지 않고 섹션·시드 매칭과 고아 시드를 점검한다.

    .venv/bin/python -m app.init_samples --report

다음 명령은 datakeeper.db의 CSO 테이블을 재생성하고 샘플·persona를 다시 넣는다.

    .venv/bin/python -m app.init_samples --reset

--reset은 업로드 문서, 사용자가 수정한 등급, Classification Skill, 감사 로그를 제거한다. 데모
초기화가 명확히 필요할 때만 실행하고, 보존할 데이터가 있으면 먼저 DB를 백업한다.

시딩된 샘플은 사람이 검토한 값으로 간주해 user_confirmed로 저장되며 각 섹션에 본문 없는 분류
이벤트가 생성된다. 문서 등급은 저장하지 않고 시딩된 섹션 등급의 Max로 계산한다.

라이브 분류로 시연할 원문은 data/uploads에 둔다.
