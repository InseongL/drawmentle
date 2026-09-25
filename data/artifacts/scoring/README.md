# 점수표 산출물

이 폴더의 파일은 Git으로 추적하지 않는다(이 README만 추적). 정답 관계를 담은 비공개 자료이며, 연상 축 단어 벡터는 fastText `cc.en.300`(CC BY-SA 3.0) 파생 데이터다.

| 경로 | 만드는 명령 | 내용 |
|---|---|---|
| `label-vectors/cc-en-300-subset.npz`, `.json` | `python scripts/scoring/extract_label_vectors.py` | 라벨 단어 벡터 부분 집합과 출처·해시 |
| `scoring-v1/score-table.npz`, `manifest.json` | `python scripts/scoring/build_score_table.py` | 334×334 관계 점수와 축별 점수, 입력 해시·보정 기준값 |
| `scoring-v1/review-report.md` | `python scripts/scoring/check_score_table.py` | 무결성 검사 결과와 데일리 후보별 가까운 카테고리 |

규칙과 근거는 [점수 계산 규칙 v1](../../../docs/scoring-v1.md)을 따른다.
