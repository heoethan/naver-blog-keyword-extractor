"""
네이버 블로그 금융 황금 키워드 파이프라인 에이전트
시드 키워드 → 황금 키워드 추출 → Claude AI 관심사 분석 → 결과 저장
"""
import html
import requests
import pandas as pd
from datetime import datetime, date, timezone, timedelta

import config
from main import run_pipeline, RECENT_DAYS


CATEGORY_COLORS = {
    "주식/증권":    "#4f86c6",
}


def _trend_bar(score: float) -> str:
    """트렌드 점수를 시각적 바로 표현"""
    pct = min(score / 3.0, 1.0) * 100
    if score >= 1.5:
        color = "#2ecc71"
    elif score >= 1.0:
        color = "#f39c12"
    else:
        color = "#e74c3c"
    return (
        f'<div style="display:flex;align-items:center;gap:6px">'
        f'<div style="background:#eee;border-radius:4px;width:80px;height:10px;overflow:hidden">'
        f'<div style="background:{color};width:{pct:.0f}%;height:100%"></div></div>'
        f'<span style="font-size:0.85em;color:{color};font-weight:600">{score:.2f}</span>'
        f'</div>'
    )


def _competition_badge(ratio: float, blog_count: int = 0) -> str:
    if blog_count >= 100:
        color, label = "#8e44ad", "매우 높음"
    elif ratio <= 0.01:
        color, label = "#2ecc71", "매우 낮음"
    elif ratio <= 0.03:
        color, label = "#f39c12", "낮음"
    else:
        color, label = "#e74c3c", "보통"
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:12px;font-size:0.78em;font-weight:600">{label}</span>'
    )


# ============================================================
# 바이오 호재 데이터 수집
# ============================================================
def get_bio_catalysts() -> list[dict]:
    """ClinicalTrials.gov에서 한국 기업 Phase 3 임상 (향후 3개월 내 완료 예정) 조회"""
    url = "https://clinicaltrials.gov/api/v2/studies"
    params = [
        (
            "filter.advanced",
            "AREA[LocationCountry]Korea AND "
            "(AREA[OverallStatus]ACTIVE_NOT_RECRUITING OR AREA[OverallStatus]RECRUITING)",
        ),
        ("pageSize", "100"),
    ]
    try:
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()
        data = res.json()
    except Exception as e:
        print(f"[오류] ClinicalTrials.gov API 호출 실패: {e}")
        return []

    today = date.today()
    cutoff = today + timedelta(days=90)

    results = []
    for study in data.get("studies", []):
        ps = study.get("protocolSection", {})

        # Phase 3만 통과
        phases = ps.get("designModule", {}).get("phases", [])
        if "PHASE3" not in phases:
            continue

        nct_id   = ps.get("identificationModule", {}).get("nctId", "")
        title    = ps.get("identificationModule", {}).get("briefTitle", "")
        sponsor  = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")
        conditions = ps.get("conditionsModule", {}).get("conditions", [])
        status   = ps.get("statusModule", {}).get("overallStatus", "")
        comp_str = ps.get("statusModule", {}).get("primaryCompletionDateStruct", {}).get("date", "")

        if not comp_str:
            continue
        try:
            fmt = "%Y-%m" if len(comp_str) == 7 else "%Y-%m-%d"
            comp_date = datetime.strptime(comp_str, fmt).date()
        except Exception:
            continue

        if not (today <= comp_date <= cutoff):
            continue

        status_kr = {
            "ACTIVE_NOT_RECRUITING": "모집 완료·진행 중",
            "RECRUITING": "모집 중",
        }.get(status, status)

        results.append({
            "nct_id": nct_id,
            "title": title,
            "sponsor": sponsor,
            "conditions": ", ".join(conditions[:2]),
            "status": status_kr,
            "completion_date": comp_str,
        })

    results.sort(key=lambda x: x["completion_date"])
    return results


def get_bio_news() -> list[dict]:
    """네이버 뉴스 API로 바이오 호재 뉴스 수집"""
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": config.SEARCH_CLIENT_ID,
        "X-Naver-Client-Secret": config.SEARCH_CLIENT_SECRET,
    }
    queries = ["기술이전 계약 바이오", "FDA 승인 한국", "임상 3상 성공", "신약 허가"]
    seen, results = set(), []

    for query in queries:
        try:
            res = requests.get(
                url,
                headers=headers,
                params={"query": query, "display": 5, "sort": "date"},
                timeout=10,
            )
            res.raise_for_status()
            for item in res.json().get("items", []):
                link = item.get("link", "")
                if link in seen:
                    continue
                seen.add(link)
                raw_title = item.get("title", "")
                clean_title = raw_title.replace("<b>", "").replace("</b>", "")
                pub = item.get("pubDate", "")[:16]
                results.append({"title": clean_title, "link": link, "pub": pub, "query": query})
        except Exception as e:
            print(f"[오류] 바이오 뉴스 검색 실패 ({query}): {e}")

    return results


def _build_bio_section(catalysts: list[dict], news: list[dict]) -> str:
    """바이오 호재 HTML 섹션 생성"""
    # ── 임상 테이블 ─────────────────────────────────────────
    if catalysts:
        rows = ""
        for c in catalysts:
            rows += f"""
            <tr>
              <td><a href="https://clinicaltrials.gov/study/{c['nct_id']}"
                     target="_blank" style="color:#3498db;font-size:0.8em">{c['nct_id']}</a></td>
              <td style="font-size:0.82em">{html.escape(c['title'][:60])}{"…" if len(c['title'])>60 else ""}</td>
              <td style="font-size:0.82em">{html.escape(c['sponsor'])}</td>
              <td style="font-size:0.82em">{html.escape(c['conditions'])}</td>
              <td><span style="background:#3498db;color:#fff;padding:2px 7px;
                  border-radius:10px;font-size:0.75em">{c['status']}</span></td>
              <td style="font-weight:700;color:#e74c3c;font-size:0.85em">{c['completion_date']}</td>
            </tr>"""
        clinical_html = f"""
        <div style="background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);
                    overflow:hidden;margin-bottom:20px;">
          <table style="width:100%;border-collapse:collapse;font-size:0.88em;">
            <thead>
              <tr style="background:#1a1a2e;color:#fff;">
                <th style="padding:10px 12px;text-align:left;white-space:nowrap">NCT ID</th>
                <th style="padding:10px 12px;text-align:left">임상 제목</th>
                <th style="padding:10px 12px;text-align:left">스폰서</th>
                <th style="padding:10px 12px;text-align:left">적응증</th>
                <th style="padding:10px 12px;text-align:left">상태</th>
                <th style="padding:10px 12px;text-align:left;white-space:nowrap">완료 예정일</th>
              </tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""
    else:
        clinical_html = '<p style="color:#aaa;font-size:0.88em;padding:12px">향후 3개월 내 완료 예정 Phase 3 임상 없음</p>'

    # ── 뉴스 카드 ────────────────────────────────────────────
    news_cards = ""
    for n in news[:8]:
        news_cards += f"""
        <div style="border:1px solid #f0f0f0;border-radius:8px;padding:10px 14px;margin-bottom:8px;">
          <div style="font-size:0.72em;color:#aaa;margin-bottom:4px">{n['pub']} &nbsp;·&nbsp;
            <span style="background:#eef6ff;color:#3498db;padding:1px 6px;border-radius:8px;
                         font-size:0.9em">{html.escape(n['query'])}</span>
          </div>
          <a href="{n['link']}" target="_blank"
             style="font-size:0.88em;color:#2c3e50;text-decoration:none;font-weight:600;
                    line-height:1.5">{html.escape(n['title'])}</a>
        </div>"""

    if not news_cards:
        news_cards = '<p style="color:#aaa;font-size:0.88em;padding:12px">관련 뉴스 없음</p>'

    return f"""
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:8px;">
      <div>
        <div style="font-size:0.9em;font-weight:700;color:#34495e;margin-bottom:10px;">
          🔬 Phase 3 임상 완료 예정 (향후 3개월)
        </div>
        {clinical_html}
      </div>
      <div>
        <div style="font-size:0.9em;font-weight:700;color:#34495e;margin-bottom:10px;">
          📰 최신 바이오 호재 뉴스
        </div>
        <div style="background:#fff;border-radius:10px;box-shadow:0 2px 8px rgba(0,0,0,.07);
                    padding:14px;max-height:360px;overflow-y:auto;">
          {news_cards}
        </div>
      </div>
    </div>
    """


def _keyword_to_theme(kw: str) -> str:
    """관련주/테마주 키워드에서 테마명 추출 (예: '텅스텐관련주' → '텅스텐')"""
    for suffix in ["관련주", "테마주", "주도주"]:
        if kw.endswith(suffix):
            return kw[: -len(suffix)].strip()
    return kw


def _build_topic_recommendations(df: pd.DataFrame) -> str:
    """트렌드 점수 높고 경쟁률 매우 낮은 상위 3개 키워드 기반 블로그 주제 추천"""
    blog_col = f"{RECENT_DAYS}일 블로그 발행 수"
    comp_col = f"{RECENT_DAYS}일 경쟁률"

    # 1순위: 발행수 < 100 이고 경쟁률 매우 낮음(≤ 0.01), 트렌드 점수 내림차순
    top3 = (
        df[(df[blog_col] < 100) & (df[comp_col] <= 0.01)]
        .sort_values("트렌드 점수", ascending=False)
        .head(3)
    )
    # 조건 완화 fallback
    if len(top3) < 3:
        top3 = df[df[blog_col] < 100].sort_values("트렌드 점수", ascending=False).head(3)
    if top3.empty:
        top3 = df.sort_values("트렌드 점수", ascending=False).head(3)

    cards_html = ""
    for rank, (_, row) in enumerate(top3.iterrows(), 1):
        kw = row["황금 키워드"]
        theme = _keyword_to_theme(kw)
        trend = row["트렌드 점수"]
        search = row["월간 검색량"]
        comp = row[comp_col]
        blog_cnt = int(row[blog_col])
        cat = row["금융 카테고리"]

        color = CATEGORY_COLORS.get(cat, "#888")
        badge_color = "#2ecc71" if trend >= 1.5 else ("#f39c12" if trend >= 1.0 else "#95a5a6")

        # 최근 이슈/호재 중심 제목 3개
        titles = [
            f"{kw} 최근 이슈 총정리 — 지금 주목받는 이유",
            f"{theme} 관련 최신 호재 분석 — {kw} 왜 지금 뜨는가?",
            f"{kw} 투자 포인트 — 최신 동향과 주목 종목 한눈에 보기",
        ]
        titles_html = "".join(
            f'<div class="post-title">✏️ {html.escape(t)}</div>'
            for t in titles
        )
        comp_badge = _competition_badge(comp, blog_cnt)

        cards_html += f"""
        <div class="topic-card">
          <div class="topic-header">
            <span class="topic-rank" style="background:{color}">{rank}</span>
            <span class="topic-label">{html.escape(kw)}</span>
            <span class="topic-trend" style="color:{badge_color}">▲ {trend:.2f}</span>
            <span class="topic-search">
              월 {search:,}회 검색 &nbsp;·&nbsp; 경쟁 {comp_badge}
            </span>
          </div>
          <div class="topic-titles">{titles_html}</div>
        </div>"""

    return f"""
    <div style="background:#fff;border-radius:10px;
         box-shadow:0 2px 8px rgba(0,0,0,.07);padding:18px;margin-bottom:28px;">
      {cards_html}
    </div>
    """


def generate_html_report(df: pd.DataFrame, bio_catalysts: list = None, bio_news: list = None) -> str:
    # 컬럼명 정규화 (이전 버전 호환 + RECENT_DAYS 동기화)
    blog_col = f"{RECENT_DAYS}일 블로그 발행 수"
    comp_col = f"{RECENT_DAYS}일 경쟁률"
    # 구버전 고정 컬럼명이 남아있을 경우 현재 설정에 맞게 변환
    rename_map = {}
    for old in ["3일 블로그 발행 수", "2일 블로그 발행 수", "월간 블로그 발행 수"]:
        if old in df.columns and old != blog_col:
            rename_map[old] = blog_col
    for old in ["3일 경쟁률", "2일 경쟁률", "월간 경쟁률"]:
        if old in df.columns and old != comp_col:
            rename_map[old] = comp_col
    if rename_map:
        df = df.rename(columns=rename_map)
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst).strftime("%Y년 %m월 %d일 %H:%M KST")
    total_kw = len(df)

    # ── 카테고리 요약 카드 ──────────────────────────────────────
    cat_cards = ""
    for cat, group in df.groupby("금융 카테고리"):
        color = CATEGORY_COLORS.get(cat, "#888")
        top3 = group.sort_values("트렌드 점수", ascending=False)["황금 키워드"].head(3).tolist()
        avg_trend = group["트렌드 점수"].mean()
        cat_cards += f"""
        <div class="cat-card" style="border-top:4px solid {color}">
          <div class="cat-name" style="color:{color}">{html.escape(cat)}</div>
          <div class="cat-count">{len(group)}개 키워드</div>
          <div class="cat-trend">평균 트렌드 <b>{avg_trend:.2f}</b></div>
          <div class="cat-kws">{' · '.join(html.escape(k) for k in top3)}</div>
        </div>"""

    # ── 키워드 테이블 행 ────────────────────────────────────────
    rows = ""
    for i, row in df.iterrows():
        cat = row["금융 카테고리"]
        color = CATEGORY_COLORS.get(cat, "#888")
        badge = f'<span class="cat-badge" style="background:{color}">{html.escape(cat)}</span>'
        rows += f"""
        <tr>
          <td>{i + 1}</td>
          <td><b>{html.escape(row['황금 키워드'])}</b></td>
          <td data-val="{row['월간 검색량']}">{row['월간 검색량']:,}</td>
          <td data-val="{int(row[blog_col])}">{int(row[blog_col])}</td>
          <td data-val="{row[comp_col]}">{_competition_badge(row[comp_col], int(row[blog_col]))}</td>
          <td data-val="{row['트렌드 점수']}">{_trend_bar(row['트렌드 점수'])}</td>
          <td>{badge}</td>
        </tr>"""

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>금융 황금 키워드 리포트 — {now}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Apple SD Gothic Neo", "Malgun Gothic", sans-serif;
         background: #f4f6f9; color: #2c3e50; }}
  .container {{ max-width: 1100px; margin: 0 auto; padding: 24px 16px; }}

  /* 헤더 */
  .header {{ background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%);
             color: #fff; padding: 32px 36px; border-radius: 12px; margin-bottom: 24px; }}
  .header h1 {{ font-size: 1.7em; font-weight: 700; }}
  .header .sub {{ opacity: .7; margin-top: 6px; font-size: 0.9em; }}
  .header .stat {{ display:inline-block; background:rgba(255,255,255,.12);
                   padding: 6px 16px; border-radius: 20px; margin-top:14px;
                   font-size:0.88em; font-weight:600; }}

  /* 카테고리 카드 */
  .section-title {{ font-size:1.1em; font-weight:700; color:#34495e;
                    margin: 24px 0 12px; padding-left:6px;
                    border-left: 4px solid #3498db; }}
  .cat-grid {{ display:grid; grid-template-columns: repeat(7, 1fr);
               gap: 8px; margin-bottom: 28px; }}
  .cat-card {{ background:#fff; border-radius:8px; padding:10px 10px 8px;
               box-shadow: 0 2px 6px rgba(0,0,0,.07); }}
  .cat-name {{ font-weight:700; font-size:0.78em; margin-bottom:3px; white-space:nowrap;
               overflow:hidden; text-overflow:ellipsis; }}
  .cat-count {{ font-size:1.1em; font-weight:800; color:#2c3e50; }}
  .cat-trend {{ font-size:0.72em; color:#7f8c8d; margin-top:1px; }}
  .cat-kws {{ font-size:0.68em; color:#95a5a6; margin-top:4px; line-height:1.5; }}

  /* 키워드 테이블 */
  .table-wrap {{ background:#fff; border-radius:10px; overflow:hidden;
                 box-shadow: 0 2px 8px rgba(0,0,0,.07); margin-bottom:32px; }}
  table {{ width:100%; border-collapse:collapse; font-size:0.88em; }}
  th {{ background:#2c3e50; color:#fff; padding:11px 14px;
        text-align:left; font-weight:600; white-space:nowrap; }}
  th.sortable {{ cursor:pointer; user-select:none; }}
  th.sortable:hover {{ background:#3d5166; }}
  th.sortable::after {{ content:" ↕"; opacity:.4; font-size:0.8em; }}
  th.sort-asc::after {{ content:" ↑"; opacity:1; }}
  th.sort-desc::after {{ content:" ↓"; opacity:1; }}
  td {{ padding:9px 14px; border-bottom:1px solid #f0f0f0; vertical-align:middle; }}
  tr:hover td {{ background:#fafbfc; }}
  tr:last-child td {{ border-bottom:none; }}
  td:first-child {{ color:#aaa; font-size:0.82em; }}

  .cat-badge {{ color:#fff; padding:2px 9px; border-radius:12px;
                font-size:0.78em; font-weight:600; white-space:nowrap; }}

  .footer {{ text-align:center; color:#aaa; font-size:0.8em; padding:16px 0 32px; }}

  /* 블로그 주제 추천 */
  .topic-card {{ border:1px solid #f0f0f0; border-radius:10px; padding:14px 16px;
                 margin-bottom:12px; transition:.15s; }}
  .topic-card:hover {{ box-shadow:0 2px 10px rgba(0,0,0,.09); }}
  .topic-header {{ display:flex; align-items:center; gap:8px; flex-wrap:wrap;
                   margin-bottom:10px; }}
  .topic-rank {{ color:#fff; width:22px; height:22px; border-radius:50%;
                 display:inline-flex; align-items:center; justify-content:center;
                 font-size:0.75em; font-weight:800; flex-shrink:0; }}
  .topic-label {{ font-weight:700; font-size:0.95em; }}
  .topic-trend {{ font-size:0.82em; font-weight:700; }}
  .topic-search {{ font-size:0.78em; color:#95a5a6; margin-left:auto; }}
  .kw-tag {{ display:inline-flex; align-items:center; gap:4px;
             background:#f4f6f9; border-radius:6px; padding:3px 8px;
             font-size:0.8em; margin:2px; }}
  .kw-score {{ background:#e8ecf0; border-radius:4px; padding:1px 5px;
               font-size:0.85em; color:#666; font-weight:600; }}
  .topic-titles {{ margin-top:10px; }}
  .post-title {{ font-size:0.88em; color:#2c3e50; padding:5px 0 5px 4px;
                 border-left:3px solid #dce3ea; margin:4px 0;
                 padding-left:10px; line-height:1.5; }}
</style>
<script>
function sortTable(th) {{
  const table = th.closest('table');
  const tbody = table.querySelector('tbody');
  const col = th.cellIndex;
  const isAsc = th.classList.contains('sort-asc');

  // 방향 토글
  table.querySelectorAll('th').forEach(t => t.classList.remove('sort-asc','sort-desc'));
  th.classList.add(isAsc ? 'sort-desc' : 'sort-asc');
  const asc = !isAsc;

  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {{
    const av = a.cells[col].dataset.val ?? a.cells[col].innerText.replace(/,/g,'').trim();
    const bv = b.cells[col].dataset.val ?? b.cells[col].innerText.replace(/,/g,'').trim();
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv, 'ko') : bv.localeCompare(av, 'ko');
  }});

  // 순번(#) 재번호
  rows.forEach((r, i) => {{
    r.cells[0].innerText = i + 1;
    tbody.appendChild(r);
  }});
}}
</script>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>📊 금융 황금 키워드 리포트</h1>
    <div class="sub">Naver 검색 데이터 기반</div>
    <div class="stat">🗓 {now} &nbsp;·&nbsp; 총 {total_kw}개 키워드 추출</div>
  </div>

  <div class="section-title">카테고리별 현황</div>
  <details style="margin-bottom:12px;">
    <summary style="cursor:pointer;background:#eef6ff;border-radius:8px;padding:8px 16px;
                    font-size:0.82em;color:#2c3e50;font-weight:700;list-style:none;
                    border-left:4px solid #3498db;display:flex;align-items:center;gap:6px;">
      📐 트렌드 점수 계산 방법 <span style="font-size:0.85em;color:#888;font-weight:400">(클릭해서 보기)</span>
    </summary>
    <div style="background:#eef6ff;border-radius:0 0 8px 8px;padding:10px 16px 12px;
                font-size:0.82em;color:#2c3e50;line-height:1.8;
                border-left:4px solid #3498db;border-top:1px solid #d6e8fa;">
      네이버 데이터랩 API의 일별 검색지수를 활용합니다.<br>
      <b>트렌드 점수 = 최근 3일 평균 검색지수 ÷ 최근 30일 평균 검색지수</b><br>
      &nbsp;· 1.5 이상 <span style="color:#2ecc71;font-weight:700">●</span> 급상승 &nbsp;
      &nbsp;· 1.0 이상 <span style="color:#f39c12;font-weight:700">●</span> 상승 중 &nbsp;
      &nbsp;· 1.0 미만 <span style="color:#e74c3c;font-weight:700">●</span> 하락 중
    </div>
  </details>
  <div class="cat-grid">{cat_cards}</div>

  <div class="section-title">✍️ 블로그 주제 추천 (카테고리별)</div>
  {_build_topic_recommendations(df)}

  <div class="section-title">황금 키워드 전체 목록</div>
  <div class="table-wrap">
    <table id="kw-table">
      <thead>
        <tr>
          <th>#</th>
          <th class="sortable" onclick="sortTable(this)">황금 키워드</th>
          <th class="sortable" onclick="sortTable(this)">월간 검색량</th>
          <th class="sortable" onclick="sortTable(this)">{RECENT_DAYS}일 발행 수</th>
          <th class="sortable" onclick="sortTable(this)">경쟁률</th>
          <th class="sortable sort-desc" onclick="sortTable(this)">트렌드 점수</th>
          <th class="sortable" onclick="sortTable(this)">카테고리</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>
  </div>

  <div class="footer">Generated by 네이버 블로그 황금 키워드 에이전트 · {now}</div>
</div>
</body>
</html>"""

    return html_content


def main():
    print("=" * 50)
    print("  금융 황금 키워드 파이프라인 에이전트")
    print("=" * 50)

    # 1. 파이프라인 실행
    df = run_pipeline()

    if df is None or df.empty:
        print("조건을 만족하는 금융 황금 키워드가 없습니다.")
        return

    print(f"\n최종 황금 키워드: {len(df)}개")

    # 2. 엑셀 저장
    output_path = "golden_keywords_output.xlsx"
    df.to_excel(output_path, index=False)
    print(f"저장 완료: {output_path}")

    # 3. 바이오 호재 데이터 수집
    print("\n바이오 호재 데이터 수집 중...")
    bio_catalysts = get_bio_catalysts()
    bio_news = get_bio_news()
    print(f"  → 임상 {len(bio_catalysts)}건 / 뉴스 {len(bio_news)}건")

    # 4. HTML 리포트 저장
    html_path = "golden_keywords_report.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(generate_html_report(df, bio_catalysts, bio_news))
    print(f"저장 완료: {html_path}  ← 브라우저에서 열어보세요")


if __name__ == "__main__":
    main()
