"""
로컬 대시보드 서버
실행: python server.py
접속: http://localhost:8765
"""
import os
import json
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, send_from_directory

import pandas as pd

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "golden_keywords_output.xlsx")
HISTORY_DIR = os.path.join(BASE_DIR, "history")
HISTORY_MAX = 7  # 보관할 최대 기록 수

os.makedirs(HISTORY_DIR, exist_ok=True)

app = Flask(__name__)
_run_status = {"running": False, "message": "", "last_run": None}


def _save_history(rows: list, run_at: str):
    """실행 결과를 history/ 에 날짜별 JSON으로 저장. 7개 초과 시 오래된 것 삭제."""
    date_key = datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d")
    path = os.path.join(HISTORY_DIR, f"{date_key}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"run_at": run_at, "rows": rows}, f, ensure_ascii=False, indent=2)

    # 7개 초과 시 오래된 파일 삭제
    files = sorted(
        [p for p in os.listdir(HISTORY_DIR) if p.endswith(".json")],
        reverse=True
    )
    for old in files[HISTORY_MAX:]:
        os.remove(os.path.join(HISTORY_DIR, old))


# ── 정적 파일 (result.html) ────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "result.html")


# ── 최신 데이터 (엑셀) ─────────────────────────────────────────
@app.route("/api/data")
def api_data():
    if not os.path.exists(OUTPUT_FILE):
        return jsonify({"error": "output file not found"}), 404
    df = pd.read_excel(OUTPUT_FILE)
    mtime = os.path.getmtime(OUTPUT_FILE)
    kst = timezone(timedelta(hours=9))
    updated_at = datetime.fromtimestamp(mtime, kst).strftime("%Y년 %m월 %d일 %H:%M KST")
    return jsonify({
        "updated_at": updated_at,
        "last_run": _run_status.get("last_run"),
        "rows": df.to_dict(orient="records")
    })


# ── 히스토리 목록 ──────────────────────────────────────────────
@app.route("/api/history")
def api_history():
    files = sorted(
        [p for p in os.listdir(HISTORY_DIR) if p.endswith(".json")],
        reverse=True
    )[:HISTORY_MAX]
    entries = []
    for fname in files:
        path = os.path.join(HISTORY_DIR, fname)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        entries.append({
            "date": fname.replace(".json", ""),
            "run_at": data.get("run_at", ""),
            "count": len(data.get("rows", [])),
        })
    return jsonify(entries)


# ── 히스토리 상세 (날짜별) ─────────────────────────────────────
@app.route("/api/history/<date>")
def api_history_detail(date):
    path = os.path.join(HISTORY_DIR, f"{date}.json")
    if not os.path.exists(path):
        return jsonify({"error": "not found"}), 404
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return jsonify(data)


# ── 파이프라인 실행 ────────────────────────────────────────────
@app.route("/api/run", methods=["POST"])
def api_run():
    if _run_status["running"]:
        return jsonify({"status": "already_running", "message": "이미 실행 중입니다."}), 409

    def _run():
        _run_status["running"] = True
        _run_status["message"] = "실행 중..."
        try:
            import main as m
            df = m.run_pipeline()
            kst = timezone(timedelta(hours=9))
            now_str = datetime.now(kst).strftime("%Y년 %m월 %d일 %H:%M KST")

            if df is not None and not df.empty:
                df.to_excel(OUTPUT_FILE, index=False)
                rows = df.to_dict(orient="records")
                _run_status["message"] = f"완료 — {len(df)}개 키워드 추출"
            else:
                pd.DataFrame(columns=["기준 시드 키워드", "황금 키워드", "월간 검색량",
                                       f"{m.RECENT_DAYS}일 블로그 발행 수",
                                       f"{m.RECENT_DAYS}일 경쟁률", "금융 카테고리", "트렌드 점수"]
                             ).to_excel(OUTPUT_FILE, index=False)
                rows = []
                _run_status["message"] = "조건을 만족하는 키워드가 없습니다."

            _run_status["last_run"] = now_str
            _save_history(rows, now_str)

        except Exception as e:
            _run_status["message"] = f"오류: {e}"
        finally:
            _run_status["running"] = False

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"status": "started", "message": "파이프라인 시작됨"})


# ── 실행 상태 확인 ─────────────────────────────────────────────
@app.route("/api/status")
def api_status():
    return jsonify(_run_status)


if __name__ == "__main__":
    print("=" * 45)
    print("  대시보드 서버 시작")
    print("  http://localhost:8765  에서 확인하세요")
    print("=" * 45)
    app.run(host="127.0.0.1", port=8765, debug=False)
