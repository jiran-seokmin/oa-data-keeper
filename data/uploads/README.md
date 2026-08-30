# 라이브 업로드 데모 문서

이 폴더의 문서는 샘플 DB 초기화 대상이 아니다. React의 분류·학습 화면에서 드래그 앤 드롭으로
업로드 분류를 시연하기 위한 원문이며 모든 회사명, 인명, 금액, 일정, 계약 조건은 가상 데이터다.

## 60초 권장 세트

| 문서 | 목적 | 예상 섹션 수 | S/C 공통 질문 |
| --- | --- | ---: | --- |
| `00_orion_60s_demo.md` | 검수 대기 S를 C로 수정하고 Skill 생성 후 동일 질문의 권한 차이 비교 | 4 | `서비스 공급 중단 시 어떤 대응을 검토하고 있나요?` |

촬영 전 상태 준비와 초 단위 내레이션은 [60초 데모 시나리오](../../docs/VIDEO-DEMO-60S.md)를
따른다. 라이브 업로드는 본편에서 제외하고 사전 분류된 상태에서 시작한다.

## 5분 확장 세트

| 순서 | 문서 | 목적 | 예상 섹션 수 | 추천 질문 |
| --- | --- | --- | ---: | --- |
| 1 | `01_cso_product_brief.md` | 한 문서의 O/S/C 분류와 사용자 등급별 답변 범위 비교 | 7 | `웹 체험은 10월 12일 어디서 신청하나요?`<br>`Atlas 캠페인 4,800만 원과 QA 4명 배치 계획은?`<br>`Polaris Score 0.52 0.31 0.17 가중치를 알려주세요.` |
| 2 | `02_orion_contract_review.md` | 계약 조항 검수, S→C 등급 수정, pending 확정과 Classification Skill 학습 | 8 | `30일 넘게 중단되면 즉시 해지할 수 있나요?` |

상세한 업로드 흐름, 페르소나 선택, 복구 절차와 예외 대응은
[5분 데모 운영 가이드](../../docs/VIDEO-DEMO-SCENARIO.md)를 따른다.

## 업로드 동작

1. .txt 또는 .md 파일을 업로드한다.
2. 문서를 의미 단위 섹션으로 나눈다.
3. Gemini가 활성 Classification Skill과 키워드 힌트를 적용해 각 섹션의 O/S/C 등급,
   confidence, classification_reason, summary, keywords, departments를 반환한다.
4. confidence가 0.8 미만이면 pending_review로 저장되어 사용자 접근이 차단된다.
5. 기준 이상이면 auto_confirmed로 저장되고 사용자 access_grade와 비교해 접근을 결정한다.
6. 응답의 document_grade는 모든 섹션 등급의 Max로 계산하며 documents 테이블에 저장하지 않는다.

Gemini 분류에는 GEMINI_API_KEY 또는 GOOGLE_API_KEY가 필요하다. ACE_PROVIDER를 Anthropic으로
설정했더라도 업로드 분류 자체는 Gemini 자격 증명을 사용하며, 모델은 필요할 때
GEMINI_CLASSIFICATION_MODEL로 별도 지정한다.

업로드 분류와 실제 Skill 적용은 분류 로그에 기록되지만 섹션 원문은 로그에 복제하지 않는다.
추후 사용자가 등급과 근거를 확정·수정하면 해당 피드백이 새 Skill로 축적되어 다음 업로드에
반영된다.

업로드 문서는 화면의 삭제 버튼이나 DELETE /api/documents/{doc}으로 제거할 수 있다. 삭제 후
원문 섹션은 사라지지만 내용 없는 감사 메타데이터는 유지된다. app.init_samples --reset을
실행하면 업로드 문서와 Skill·로그를 포함한 현재 DB 내용이 모두 초기화된다.
