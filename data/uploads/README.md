# Upload Demo Documents

이 폴더의 문서는 **DB에 시딩되지 않는다.** 웹 데모의 drag & drop 업로드 시연용 원문이다.

- 데모 중 문서함의 "문서 추가"에 끌어다 놓으면 Gemini가 업로드 시점에 문단별 보안 등급을
  라이브 분류해 DB에 추가한다 (`app/upload_pipeline.py`, 문서 전체 1회 배치 호출).
- 시딩 대상 기본 코퍼스(`data/samples/`)와 달리 GRADES 등급 시드가 필요 없다.
- 모든 회사명, 인명, 금액, 일정, 계약 조건은 데모용 가상 데이터다.
- 업로드로 추가된 문서는 문서함의 삭제 버튼 또는 `DELETE /api/documents/{doc}`으로 제거할 수 있고,
  `python -m app.init_samples --reset`으로도 기본 코퍼스만 남게 초기화된다.
