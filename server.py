"""
로컬 대시보드 서버
실행: python server.py
접속: http://localhost:5000
"""
import os
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, jsonify, send_from_directory

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "golden_keywords_output.xlsx")

app = Flask(__name__)
_run_lock = threading.Lock()
_run_status = {"running": False, "message": ""}


# ── 정적 파일 (result.html) ────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "result.html")


# ── 엑셀 읽기 → JSON ──────────────────────────────────────────
@app.route("/api/data")
def api_data():
    if not os.path.exists(OUTPUT_FILE):
        return jsonify({"error": "output file not found"}), 404
    df = pd.read_excel(OUTPUT_FILE)
    mtime = os.path.getmtime(OUTPUT_FILE)
    kst = timezone(timedelta(hours=9))
    updated_at = datetime.fromtimestamp(mtime, kst).strftime("%Y년 %m월 %d일 %H:%M KST")
    return jsonify({"updated_at": updated_at, "rows": df.to_dict(orient="records")})


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
            if df is not None and not df.empty:
                df.to_excel(OUTPUT_FILE, index=False)
                _run_status["message"] = f"완료 — {len(df)}개 키워드 추출"
            else:
                _run_status["message"] = "조건을 만족하는 키워드가 없습니다."
        except Exception as e:
            _run_status["message"] = f"오류: {e}"
        finally:
            _run_status["running"] = False

    t = threading.Thread(target=_run, daemon=True)
    t.start()
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
