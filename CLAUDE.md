# 네이버 블로그 황금 키워드 자동 추출기 — Claude 개발 가이드

> **이 파일은 Claude가 대화 시작 시 반드시 읽는 컨텍스트 파일입니다.**
> 현재 개발 상태, 아키텍처, 히스토리를 기록합니다.
> 변경사항이 생길 때마다 이 파일과 `CHANGELOG.md`를 함께 업데이트하세요.

---

## 현재 개발 상태 (2026-03-27 기준)

| 항목 | 내용 |
|---|---|
| 버전 | v0.3.0 |
| 상태 | 운영 중 (기능 추가 단계) |
| 마지막 주요 변경 | 로컬 웹 대시보드 + 업데이트 버튼 추가 |
| 다음 예정 작업 | 없음 (사용자 요청 대기) |

---

## 파일 구조 (전체)

```
naver blog extractor/
│
├── CLAUDE.md                      ← Claude 컨텍스트 파일 (이 파일)
├── CHANGELOG.md                   ← 버전별 변경 이력
├── README.md                      ← 사용자용 실행 가이드
│
├── config.py                      ← API 인증키 설정 (소스 코드와 분리, git 제외)
├── main.py                        ← 핵심 파이프라인 (키워드 추출 엔진)
├── agent.py                       ← 확장 파이프라인 (바이오 데이터 + HTML 리포트 생성)
├── server.py                      ← 로컬 웹 대시보드 서버 (Flask, port 8765)
│
├── result.html                    ← 라이브 대시보드 (server.py와 연동, API fetch)
├── golden_keywords_report.html    ← 정적 HTML 리포트 (agent.py 실행 시 생성)
│
├── input_keywords.xlsx            ← 시드 키워드 입력 파일 (최대 100개)
└── golden_keywords_output.xlsx    ← 결과 출력 파일 (실행 후 생성)
```

---

## 아키텍처 개요

### 실행 방법 2가지

#### 방법 A — 대시보드 서버 (권장)
```
python server.py   → http://localhost:8765 접속 → 🔄 버튼으로 업데이트
```
- `server.py`가 Flask 서버로 동작
- `result.html`을 서빙하고 `/api/data`, `/api/run`, `/api/status` 엔드포인트 제공
- 업데이트 버튼 클릭 시 `main.run_pipeline()` 백그라운드 실행 → 완료 후 자동 갱신

#### 방법 B — 정적 리포트 생성
```
python agent.py   → golden_keywords_report.html 생성 (브라우저에서 열기)
```
- 바이오 임상 데이터(ClinicalTrials.gov) + 바이오 뉴스도 포함
- 완전한 스냅샷 리포트

---

## 핵심 파이프라인 (main.py)

```
input_keywords.xlsx
    ↓ (시드 키워드 최대 100개)
get_related_keywords()   ← 네이버 검색광고 API (HMAC-SHA256 서명)
    ↓ (연관 검색어 + 월간 PC/모바일 검색량)
검색량 필터: 500 ≤ total_search ≤ 500,000
    ↓
get_recent_blog_count()  ← 네이버 블로그 검색 API (병렬 처리, workers=2)
    ↓ (최근 N일 블로그 발행 수, 기본 RECENT_DAYS=2)
경쟁률 필터: competition ≤ 0.05, blog_count ≤ 99
is_finance_keyword()     ← 금융 카테고리 필터
    ↓
get_trend_scores()       ← 네이버 데이터랩 API (5개씩 배치)
    ↓ (트렌드 점수 = 최근 3일 평균 / 최근 30일 평균)
최종 필터: trend_score ≥ 1.0
정렬: 트렌드 점수 내림차순, 경쟁률 오름차순
    ↓
golden_keywords_output.xlsx
```

---

## 사용 API

| API | 용도 | 인증 |
|---|---|---|
| 네이버 검색광고 API | 연관 검색어 + 월간 검색량 | CUSTOMER_ID, ACCESS_LICENSE, SECRET_KEY (HMAC-SHA256) |
| 네이버 블로그 검색 API | 최근 N일 블로그 발행 수 | SEARCH_CLIENT_ID, SEARCH_CLIENT_SECRET |
| 네이버 데이터랩 API | 트렌드 점수 (검색 트렌드) | SEARCH_CLIENT_ID, SEARCH_CLIENT_SECRET |
| ClinicalTrials.gov API | 한국 Phase 3 임상 데이터 | 불필요 (공개 API) |

---

## 주요 설정값 (main.py 상단)

| 변수 | 현재값 | 설명 |
|---|---|---|
| `MIN_SEARCH_COUNT` | 500 | 월간 검색량 최소 기준 |
| `MAX_SEARCH_COUNT` | 500,000 | 월간 검색량 최대 기준 |
| `MAX_RECENT_COMPETITION` | 0.05 | 최근 N일 경쟁률 상한 |
| `MAX_RECENT_BLOG_COUNT` | 99 | 최근 N일 발행 수 상한 |
| `MIN_TREND_SCORE` | 1.0 | 트렌드 점수 하한 |
| `RECENT_DAYS` | 2 | 최근 N일 기준 |
| `BLOG_API_WORKERS` | 2 | 병렬 처리 수 (429 방지) |
| `DATALAB_BATCH_SIZE` | 5 | 데이터랩 배치 크기 |

---

## 금융 카테고리 정의 (main.py)

```python
FINANCE_CATEGORIES = {
    "주식/증권": ["관련주", "테마주", "주도주"],
}
```
- 카테고리 추가 시 `FINANCE_CATEGORIES`에 항목 추가
- `CATEGORY_COLORS` (agent.py)에 색상도 추가 필요

---

## server.py 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/` | result.html 서빙 |
| GET | `/api/data` | golden_keywords_output.xlsx → JSON 반환 |
| POST | `/api/run` | main.run_pipeline() 백그라운드 실행 시작 |
| GET | `/api/status` | 실행 상태 조회 (`running`, `message`) |

- 포트: **8765** (macOS AirPlay가 5000 사용 중이므로 변경됨)
- 동시 실행 방지: `_run_lock` + `_run_status["running"]` 플래그

---

## 예외 처리 원칙

- API 오류, 개별 키워드 오류 → 해당 항목 생략, 콘솔 출력 후 계속 진행
- Rate limit 준수: API 호출 간 0.5초 sleep
- `run_pipeline()` 함수는 DataFrame 반환 (server.py, agent.py에서 재사용)

---

## config.py 구조

```python
# 네이버 검색광고 API
AD_API_BASE_URL = "https://api.naver.com"
CUSTOMER_ID = "여기에_입력"
ACCESS_LICENSE = "여기에_입력"
SECRET_KEY = "여기에_입력"

# 네이버 검색 API + 데이터랩 API
SEARCH_CLIENT_ID = "여기에_입력"
SEARCH_CLIENT_SECRET = "여기에_입력"
```

---

## 개발 환경

- Python 3.x
- 필수 라이브러리: `pandas`, `requests`, `openpyxl`, `flask`
- 포트: 8765 (macOS AirPlay와 충돌 방지)

---

## 히스토리 참고

전체 변경 이력은 [CHANGELOG.md](CHANGELOG.md)를 참조하세요.
