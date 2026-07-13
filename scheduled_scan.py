"""
자동 스캔 스크립트 - GitHub Actions가 1시간마다 이 파일을 실행함.
사람이 접속 안 해도 서버 쪽에서 알아서 돌아가고, 결과를 latest_results.json에 저장.
app.py는 이 파일을 읽어서 화면에 보여주기만 함 (가벼움, 매 방문마다 새로 스캔 안 함).
"""

import json
from datetime import datetime, timezone
import screener_core as core

MAX_PRICE = 20.0
DISCOVER_LIMIT = 25
SCORE_THRESHOLD_FOR_DEEP = 30


def main():
    print("자동 스캔 시작...")
    tickers = core.discover_daily_candidates(max_price=MAX_PRICE, limit=DISCOVER_LIMIT)

    if not tickers:
        print("발굴된 후보 없음 - 예시 리스트로 폴백")
        tickers = ["GNS", "MULN", "SNTG", "BBIG", "ATER", "PROG"]

    results = []
    for ticker in tickers:
        pv = core.get_price_volume_signal(ticker)
        stw = core.get_stocktwits_signal(ticker)
        sh = core.get_finra_short_volume(ticker)

        if "error" in pv:
            continue

        score = core.composite_score(pv, stw, sh)
        row = {
            "ticker": ticker,
            "score": score,
            "last_close": pv.get("last_close"),
            "rel_volume": pv.get("rel_volume"),
            "price_change_pct": pv.get("price_change_pct"),
            "gap_pct": pv.get("gap_pct"),
            "st_msg_count": stw.get("st_msg_count"),
            "short_volume_ratio_pct": sh.get("short_volume_ratio_pct"),
        }

        if score >= SCORE_THRESHOLD_FOR_DEEP:
            fund = core.get_fundamentals(ticker)
            dilution = core.check_dilution_risk(ticker)
            news = core.get_recent_news(ticker, max_items=3)
            row.update({
                "market_cap": fund.get("market_cap"),
                "float_shares": fund.get("float_shares"),
                "cash_debt_ratio": fund.get("cash_debt_ratio"),
                "insider_pct": fund.get("insider_pct"),
                "dilution_risk": dilution.get("dilution_risk"),
                "recent_dilution_filings_90d": dilution.get("recent_dilution_filings_90d"),
                "recent_news": " | ".join(news) if news else None,
            })

        results.append(row)

    results.sort(key=lambda r: r.get("score", 0), reverse=True)

    output = {
        "last_updated_utc": datetime.now(timezone.utc).isoformat(),
        "tickers_scanned": len(tickers),
        "results": results,
    }

    with open("latest_results.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"완료: {len(results)}개 종목 결과 저장 (latest_results.json)")


if __name__ == "__main__":
    main()
