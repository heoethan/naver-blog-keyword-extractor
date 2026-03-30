# CHANGELOG

모든 변경 이력을 이 파일에 기록합니다.
형식: `[버전] YYYY-MM-DD — 변경 내용`

---

## [v0.4.0] 2026-03-30

### 추가
- `server.py` — 히스토리 API 추가
  - `GET /api/history` : 히스토리 목록 반환 (날짜·실행시각·키워드 수)
  - `GET /api/history/<date>` : 특정 날짜 상세 데이터 반환
  - `_save_history()` : 파이프라인 실행 완료 시 `history/YYYY-MM-DD.json` 자동 저장, 최대 7개 보관
- `result.html` — 히스토리 탭 UI 추가
  - `최신 데이터` 탭 + 날짜별 탭 (키워드 수 배지 표시, 0개는 점선 스타일)
  - `loadHistory()` : 서버에서 탭 목록 로드
  - `selectTab()` / `loadHistoryDetail()` : 탭 클릭 시 해당 날짜 데이터 렌더링
- `.claude/settings.json` — git commit 전 CLAUDE.md·CHANGELOG.md 자동 업데이트 훅 (PreToolUse agent)
- `history/` 디렉터리 — 실행 히스토리 JSON 저장소

### 수정
- **날짜 미갱신 버그 수정**: 파이프라인 실행 결과가 0개일 때도 엑셀을 빈 DataFrame으로 덮어써 `updated_at` 갱신
- `_run_status`에 `last_run` 필드 추가 → 파이프라인 실행 완료 시각 별도 추적

---

## [v0.3.0] 2026-03-27

### 추가
- `server.py` — Flask 로컬 웹 대시보드 서버 (port 8765)
  - `GET /` : result.html 서빙
  - `GET /api/data` : 엑셀 파일 → JSON 반환
  - `POST /api/run` : 파이프라인 백그라운드 실행
  - `GET /api/status` : 실행 상태 폴링
- `result.html` — 라이브 대시보드 (server.py API 연동)
  - 🔄 데이터 업데이트 버튼: 클릭 시 파이프라인 실행 → 완료 후 자동 갱신
  - 3초 간격 폴링으로 실행 완료 감지
  - 테이블 컬럼 클릭 정렬 기능

### 변경
- 포트를 5000 → **8765**로 변경 (macOS AirPlay Receiver가 5000 점유)

### 비고
- `result.html`은 반드시 `python server.py` 실행 후 `http://localhost:8765`로 접속
- `file://`로 직접 열면 CORS 제한으로 API 호출 불가

---

## [v0.2.0] 2026-03-26

### 추가
- `agent.py` — 확장 파이프라인
  - `generate_html_report()` : 황금 키워드 데이터를 기반으로 `golden_keywords_report.html` 생성
  - `get_bio_catalysts()` : ClinicalTrials.gov에서 한국 Phase 3 임상 (90일 내 완료 예정) 수집
  - `get_bio_news()` : 네이버 뉴스 API로 바이오 호재 뉴스 4개 쿼리 수집
  - `_build_topic_recommendations()` : 트렌드 점수·경쟁률 기반 블로그 주제 3개 추천
  - `_trend_bar()` : 트렌드 점수를 HTML 프로그레스 바로 시각화
  - `_competition_badge()` : 경쟁률 수준을 색상 배지로 표시

### 변경
- `main.py`에 `run_pipeline()` 함수 추가 (agent.py, server.py에서 import해서 재사용)
- 결과 컬럼명 동적화: `{RECENT_DAYS}일 블로그 발행 수`, `{RECENT_DAYS}일 경쟁률`

---

## [v0.1.0] 2026-03-26 (초기 버전)

### 추가
- `main.py` — 핵심 파이프라인
  - `get_related_keywords()` : 네이버 검색광고 API로 연관 검색어 + 월간 검색량 수집
  - `get_recent_blog_count()` : 네이버 블로그 API로 최근 N일 발행 수 수집 (병렬 처리)
  - `get_trend_scores()` : 네이버 데이터랩 API로 트렌드 점수 계산 (5개 배치)
  - `is_finance_keyword()` : 금융 카테고리 분류
  - HMAC-SHA256 서명 생성 (`generate_signature`)
- `config.py` — API 인증키 분리 관리
- `input_keywords.xlsx` — 시드 키워드 입력 파일
- `golden_keywords_output.xlsx` — 결과 엑셀 출력

### 핵심 필터 조건 (초기 설정)
| 조건 | 값 |
|---|---|
| 월간 검색량 | 500 ~ 500,000 |
| 최근 2일 경쟁률 | ≤ 0.05 |
| 최근 2일 발행 수 | ≤ 99 |
| 트렌드 점수 | ≥ 1.0 |
| 금융 카테고리 | 주식/증권 (관련주, 테마주, 주도주) |
