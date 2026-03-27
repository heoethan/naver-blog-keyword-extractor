import time
import hmac
import hashlib
import base64
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import config

# ============================================================
# 설정값
# ============================================================
MIN_SEARCH_COUNT       = 500    # 월간 검색량 최소 기준
MAX_SEARCH_COUNT       = 500000 # 월간 검색량 최대 기준
MAX_RECENT_COMPETITION = 0.05  # 3일 경쟁률 필터 (3일 문서 수 / 월간 검색량)
MAX_RECENT_BLOG_COUNT  = 99    # 최근 N일 블로그 발행 수 최대 기준 (100 이상 제외)
MIN_TREND_SCORE        = 1.0   # 트렌드 점수 최소 기준 (1.0 = 평균 이상)
BLOG_API_WORKERS       = 2     # 병렬 처리 수 (429 방지)
RECENT_DAYS            = 2     # 최근 N일 이내 문서 수 기준
DATALAB_BATCH_SIZE     = 5     # 데이터랩 API 배치 크기 (최대 5)

# ============================================================
# 금융 관심사 카테고리 정의
# ============================================================
FINANCE_CATEGORIES = {
    "주식/증권":     ["관련주", "테마주", "주도주"],
}

ALL_FINANCE_TERMS = [term for terms in FINANCE_CATEGORIES.values() for term in terms]


def is_finance_keyword(keyword: str) -> str | None:
    """금융 관련 키워드면 카테고리명 반환, 아니면 None"""
    kw_lower = keyword.lower()
    for category, terms in FINANCE_CATEGORIES.items():
        if any(term in kw_lower for term in terms):
            return category
    return None


# ============================================================
# 네이버 검색광고 API - 서명 생성
# ============================================================
def generate_signature(timestamp: str, method: str, path: str) -> str:
    message = f"{timestamp}.{method}.{path}"
    secret = config.SECRET_KEY.encode("utf-8")
    sig = hmac.new(secret, message.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(sig).decode("utf-8")


def get_ad_api_headers(method: str, path: str) -> dict:
    timestamp = str(int(time.time() * 1000))
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": timestamp,
        "X-API-KEY": config.ACCESS_LICENSE,
        "X-Customer": str(config.CUSTOMER_ID),
        "X-Signature": generate_signature(timestamp, method, path),
    }


# ============================================================
# 연관 검색어 + 검색량 수집 (검색광고 API)
# ============================================================
def get_related_keywords(seed_keyword: str) -> list[dict]:
    path = "/keywordstool"
    url = config.AD_API_BASE_URL + path
    headers = get_ad_api_headers("GET", path)
    params = {"hintKeywords": seed_keyword, "showDetail": "1"}

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"[오류] 검색광고 API 호출 실패 ({seed_keyword}): {e}")
        return []

    results = []
    for item in data.get("keywordList", []):
        keyword = item.get("relKeyword", "")
        pc = item.get("monthlyPcQcCnt", 0)
        mobile = item.get("monthlyMobileQcCnt", 0)
        try:
            pc = int(pc)
        except (ValueError, TypeError):
            pc = 5
        try:
            mobile = int(mobile)
        except (ValueError, TypeError):
            mobile = 5
        results.append({"keyword": keyword, "total_search": pc + mobile})
    return results


# ============================================================
# 최근 N일 블로그 문서 수 수집 (개발자센터 검색 API)
# ============================================================
def get_recent_blog_count(keyword: str) -> int:
    url = "https://openapi.naver.com/v1/search/blog.json"
    headers = {
        "X-Naver-Client-Id": config.SEARCH_CLIENT_ID,
        "X-Naver-Client-Secret": config.SEARCH_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": 100, "sort": "date"}

    kst = timezone(timedelta(hours=9))
    cutoff = datetime.now(kst) - timedelta(days=RECENT_DAYS)

    try:
        res = requests.get(url, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"[오류] 블로그 검색 API 호출 실패 ({keyword}): {e}")
        return -1

    recent_count = 0
    for item in data.get("items", []):
        post_date_str = item.get("postdate", "")
        try:
            post_date = datetime.strptime(post_date_str, "%Y%m%d").replace(tzinfo=kst)
            if post_date >= cutoff:
                recent_count += 1
            else:
                break
        except Exception:
            continue

    return recent_count


# ============================================================
# 데이터랩 트렌드 점수 수집 (최근 3일 / 30일 평균 비율)
# ============================================================
def get_trend_scores(keywords: list[str]) -> dict[str, float]:
    """키워드 목록의 트렌드 점수 반환. 5개씩 배치 처리."""
    url = "https://openapi.naver.com/v1/datalab/search"
    headers = {
        "X-Naver-Client-Id": config.SEARCH_CLIENT_ID,
        "X-Naver-Client-Secret": config.SEARCH_CLIENT_SECRET,
        "Content-Type": "application/json",
    }

    kst = timezone(timedelta(hours=9))
    today = datetime.now(kst).date()
    end_date = today - timedelta(days=2)          # 데이터랩 2일 딜레이 반영
    start_date = end_date - timedelta(days=29)    # 최근 30일

    trend_scores = {}

    for i in range(0, len(keywords), DATALAB_BATCH_SIZE):
        batch = keywords[i:i + DATALAB_BATCH_SIZE]
        keyword_groups = [{"groupName": kw, "keywords": [kw]} for kw in batch]

        body = {
            "startDate": start_date.strftime("%Y-%m-%d"),
            "endDate": end_date.strftime("%Y-%m-%d"),
            "timeUnit": "date",
            "keywordGroups": keyword_groups,
        }

        try:
            res = requests.post(url, headers=headers, json=body, timeout=10)
            res.raise_for_status()
            data = res.json()

            for result in data.get("results", []):
                kw_name = result["title"]
                data_points = result.get("data", [])

                if not data_points:
                    trend_scores[kw_name] = 1.0
                    continue

                all_ratios = [d["ratio"] for d in data_points]
                recent_3 = [d["ratio"] for d in data_points[-3:]]

                avg_30 = sum(all_ratios) / len(all_ratios) if all_ratios else 0
                avg_3 = sum(recent_3) / len(recent_3) if recent_3 else 0

                if avg_30 == 0:
                    trend_scores[kw_name] = 1.0
                else:
                    trend_scores[kw_name] = round(avg_3 / avg_30, 2)

        except Exception as e:
            print(f"[오류] 데이터랩 API 호출 실패 (배치 {i//DATALAB_BATCH_SIZE + 1}): {e}")
            for kw in batch:
                trend_scores[kw] = 1.0

        time.sleep(0.5)

    return trend_scores


# ============================================================
# 메인 실행
# ============================================================
def main():
    # 1. 시드 키워드 읽기
    try:
        df_input = pd.read_excel("input_keywords.xlsx")
        seed_keywords = df_input.iloc[:, 0].dropna().astype(str).tolist()[:100]
    except Exception as e:
        print(f"[오류] input_keywords.xlsx 읽기 실패: {e}")
        return

    print(f"시드 키워드 {len(seed_keywords)}개 로드 완료")

    all_rows = []

    for seed in seed_keywords:
        print(f"\n[처리 중] 시드 키워드: {seed}")

        # 2. 연관 검색어 + 검색량 수집
        related = get_related_keywords(seed)
        time.sleep(0.5)

        # 3. 검색량 선필터
        candidates = [item for item in related if MIN_SEARCH_COUNT <= item["total_search"] <= MAX_SEARCH_COUNT]
        print(f"  → 연관 검색어 {len(related)}개 / 검색량 {MIN_SEARCH_COUNT:,}~{MAX_SEARCH_COUNT:,}: {len(candidates)}개")

        # 4. 최근 3일 블로그 문서 수 병렬 수집
        def fetch_doc(item):
            count = get_recent_blog_count(item["keyword"])
            time.sleep(0.3)
            return item, count

        with ThreadPoolExecutor(max_workers=BLOG_API_WORKERS) as executor:
            futures = {executor.submit(fetch_doc, item): item for item in candidates}
            for future in as_completed(futures):
                item, recent_count = future.result()
                if recent_count < 0:
                    continue

                keyword = item["keyword"]
                total_search = item["total_search"]
                competition = round(recent_count / total_search, 4) if total_search > 0 else 9999.0

                # 5. 금융 카테고리 필터
                category = is_finance_keyword(keyword)
                if category is None:
                    continue

                all_rows.append({
                    "기준 시드 키워드": seed,
                    "황금 키워드": keyword,
                    "월간 검색량": total_search,
                    f"{RECENT_DAYS}일 블로그 발행 수": recent_count,
                    f"{RECENT_DAYS}일 경쟁률": competition,
                    "금융 카테고리": category,
                })

    if not all_rows:
        print("\n조건을 만족하는 금융 황금 키워드가 없습니다.")
        return

    df = pd.DataFrame(all_rows)
    df_filtered = df[
        (df[f"{RECENT_DAYS}일 경쟁률"] <= MAX_RECENT_COMPETITION) &
        (df[f"{RECENT_DAYS}일 블로그 발행 수"] <= MAX_RECENT_BLOG_COUNT)
    ].copy()
    print(f"\n경쟁률·발행 수 필터 통과: {len(df_filtered)}개 → 데이터랩 트렌드 조회 중...")

    # 6. 데이터랩 트렌드 점수 수집
    keywords_to_check = df_filtered["황금 키워드"].tolist()
    trend_scores = get_trend_scores(keywords_to_check)
    df_filtered["트렌드 점수"] = df_filtered["황금 키워드"].map(
        lambda kw: trend_scores.get(kw, 1.0)
    )

    # 7. 최종 정렬 + 중복 제거 + 트렌드 필터
    df_filtered.sort_values(
        ["트렌드 점수", f"{RECENT_DAYS}일 경쟁률"],
        ascending=[False, True],
        inplace=True
    )
    df_filtered.drop_duplicates(subset="황금 키워드", keep="first", inplace=True)
    df_filtered = df_filtered[df_filtered["트렌드 점수"] >= MIN_TREND_SCORE].copy()
    print(f"트렌드 점수 {MIN_TREND_SCORE} 이상 필터 통과: {len(df_filtered)}개")
    df_filtered.reset_index(drop=True, inplace=True)

    # 8. 엑셀 저장
    output_path = "golden_keywords_output.xlsx"
    df_filtered.to_excel(output_path, index=False)
    print(f"저장 완료: {output_path}")

    # 9. 카테고리별 요약
    if not df_filtered.empty:
        print("\n[카테고리별 황금 키워드 분포]")
        for cat, group in df_filtered.groupby("금융 카테고리"):
            top = group.head(3)["황금 키워드"].tolist()
            print(f"  {cat}: {len(group)}개  (상위: {', '.join(top)})")

        print(f"\n[트렌드 상위 5개 키워드]")
        top5 = df_filtered.head(5)[["황금 키워드", "월간 검색량", "트렌드 점수", "금융 카테고리"]]
        print(top5.to_string(index=False))


def run_pipeline() -> pd.DataFrame | None:
    """파이프라인 실행 후 필터링된 DataFrame 반환. agent.py에서 호출용."""
    try:
        df_input = pd.read_excel("input_keywords.xlsx")
        seed_keywords = df_input.iloc[:, 0].dropna().astype(str).tolist()[:100]
    except Exception as e:
        print(f"[오류] input_keywords.xlsx 읽기 실패: {e}")
        return None

    print(f"시드 키워드 {len(seed_keywords)}개 로드 완료")
    all_rows = []

    for seed in seed_keywords:
        print(f"\n[처리 중] 시드 키워드: {seed}")
        related = get_related_keywords(seed)
        time.sleep(0.5)

        candidates = [item for item in related if MIN_SEARCH_COUNT <= item["total_search"] <= MAX_SEARCH_COUNT]
        print(f"  → 연관 검색어 {len(related)}개 / 검색량 {MIN_SEARCH_COUNT:,}~{MAX_SEARCH_COUNT:,}: {len(candidates)}개")

        def fetch_doc(item):
            count = get_recent_blog_count(item["keyword"])
            time.sleep(0.3)
            return item, count

        with ThreadPoolExecutor(max_workers=BLOG_API_WORKERS) as executor:
            futures = {executor.submit(fetch_doc, item): item for item in candidates}
            for future in as_completed(futures):
                item, recent_count = future.result()
                if recent_count < 0:
                    continue
                keyword = item["keyword"]
                total_search = item["total_search"]
                competition = round(recent_count / total_search, 4) if total_search > 0 else 9999.0
                category = is_finance_keyword(keyword)
                if category is None:
                    continue
                all_rows.append({
                    "기준 시드 키워드": seed,
                    "황금 키워드": keyword,
                    "월간 검색량": total_search,
                    f"{RECENT_DAYS}일 블로그 발행 수": recent_count,
                    f"{RECENT_DAYS}일 경쟁률": competition,
                    "금융 카테고리": category,
                })

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df_filtered = df[
        (df[f"{RECENT_DAYS}일 경쟁률"] <= MAX_RECENT_COMPETITION) &
        (df[f"{RECENT_DAYS}일 블로그 발행 수"] <= MAX_RECENT_BLOG_COUNT)
    ].copy()
    print(f"\n경쟁률·발행 수 필터 통과: {len(df_filtered)}개 → 데이터랩 트렌드 조회 중...")

    keywords_to_check = df_filtered["황금 키워드"].tolist()
    trend_scores = get_trend_scores(keywords_to_check)
    df_filtered["트렌드 점수"] = df_filtered["황금 키워드"].map(lambda kw: trend_scores.get(kw, 1.0))
    df_filtered.sort_values(["트렌드 점수", f"{RECENT_DAYS}일 경쟁률"], ascending=[False, True], inplace=True)

    # 중복 황금 키워드 제거 (트렌드 점수 높은 것 유지)
    df_filtered.drop_duplicates(subset="황금 키워드", keep="first", inplace=True)

    # 트렌드 점수 필터
    df_filtered = df_filtered[df_filtered["트렌드 점수"] >= MIN_TREND_SCORE].copy()
    print(f"트렌드 점수 {MIN_TREND_SCORE} 이상 필터 통과: {len(df_filtered)}개")

    df_filtered.reset_index(drop=True, inplace=True)

    return df_filtered


if __name__ == "__main__":
    main()
