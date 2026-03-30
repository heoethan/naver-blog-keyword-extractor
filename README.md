# 네이버 블로그 황금 키워드 자동 추출기

시드 키워드 기반으로 네이버 검색 데이터를 분석해 **상위 노출에 유리한 황금 키워드**를 자동 추출하는 도구입니다.

---

## 빠른 시작

### 1. 사전 준비

```bash
pip install pandas requests openpyxl flask
```

`config.py`에 API 키 입력:

```python
AD_API_BASE_URL = "https://api.naver.com"
CUSTOMER_ID     = "your_customer_id"
ACCESS_LICENSE  = "your_access_license"
SECRET_KEY      = "your_secret_key"

SEARCH_CLIENT_ID     = "your_client_id"
SEARCH_CLIENT_SECRET = "your_client_secret"
```

### 2. 시드 키워드 입력

`input_keywords.xlsx` A열에 분석할 키워드 입력 (최대 100개)

---

## 실행 방법

### 방법 A — 웹 대시보드 (권장)

```bash
python server.py
```

브라우저에서 `http://localhost:8765` 접속 → **🔄 데이터 업데이트** 버튼 클릭

- 실행 중 상태 표시, 완료 후 자동 화면 갱신
- 테이블 컬럼 클릭으로 정렬 가능
- **히스토리 탭**: 과거 최대 7회 실행 기록을 날짜별 탭으로 조회 가능

### 방법 B — 정적 리포트 생성

```bash
python agent.py
```

`golden_keywords_report.html` 파일 생성 → 브라우저에서 열기

- 바이오 임상 데이터 + 뉴스 포함

### 방법 C — 엑셀만 추출

```bash
python main.py
```

`golden_keywords_output.xlsx` 파일 생성

---

## 황금 키워드 필터 조건

| 조건 | 기준값 |
|---|---|
| 월간 검색량 | 500 ~ 500,000 |
| 최근 2일 블로그 발행 수 | 99개 이하 |
| 최근 2일 경쟁률 | 0.05 이하 |
| 트렌드 점수 | 1.0 이상 |

**트렌드 점수** = 최근 3일 평균 검색지수 ÷ 최근 30일 평균 검색지수
- 1.5 이상: 급상승
- 1.0~1.5: 상승 중
- 1.0 미만: 하락 중

---

## 결과 파일 컬럼

| 컬럼 | 설명 |
|---|---|
| 기준 시드 키워드 | 입력한 시드 키워드 |
| 황금 키워드 | 추출된 연관 황금 키워드 |
| 월간 검색량 | PC + 모바일 월간 검색량 합계 |
| 2일 블로그 발행 수 | 최근 2일 내 발행된 블로그 글 수 |
| 2일 경쟁률 | 2일 발행 수 / 월간 검색량 |
| 금융 카테고리 | 키워드 분류 (주식/증권 등) |
| 트렌드 점수 | 검색 트렌드 상승 지수 |

---

## 사용 API

| API | 용도 |
|---|---|
| 네이버 검색광고 API | 연관 검색어 + 월간 검색량 |
| 네이버 블로그 검색 API | 최근 N일 발행 수 |
| 네이버 데이터랩 API | 트렌드 점수 |
| ClinicalTrials.gov | 바이오 임상 데이터 (agent.py) |

---

## 주의사항

- `config.py`는 절대 공유하지 마세요 (API 키 포함)
- 웹 대시보드는 `python server.py` 실행 후 `http://localhost:8765`로 접속 (`file://` 불가)
- API Rate Limit 준수를 위해 호출 간 0.5초 sleep 적용
