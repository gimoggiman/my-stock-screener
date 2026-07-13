"""
미국 소형주(펜니스톡) 급등 징조 스크리너
=========================================
무료 데이터 소스만 사용 (API 키 불필요):
  1) yfinance          - 가격 / 거래량 (Yahoo Finance 비공식 라이브러리)
  2) StockTwits 공개API - 소셜 미디어 언급량/게시글 수
  3) FINRA 숏볼륨 파일   - 공매도 관련 데이터 (일별, 무료 공개)

⚠️ 중요 안내
------------
- 이 스크립트는 "예측"이 아니라 "패턴 감지" 도구입니다. 신호가 떴다고 반드시
  급등한다는 보장은 전혀 없고, 반대로 급락하는 경우도 매우 흔합니다(펌프앤덤프 후반부일 수도 있음).
- 유료 서비스(Trade Ideas, Benzinga Pro, Ortex 등) 대비 데이터가 지연되거나
  누락될 수 있습니다. 무료 소스 특성상 100% 실시간은 아닙니다.
- 개인 투자 판단과 리스크는 본인 책임입니다. 이 코드는 정보 참고용입니다.

사용법
------
1) tickers.txt 파일에 스크리닝하고 싶은 종목 티커를 한 줄에 하나씩 적어두세요.
   (없으면 기본 예시 리스트로 실행됩니다)
2) python momentum_screener.py
"""

import time
import json
import requests
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------
# 설정값 (필요에 맞게 조정하세요)
# ---------------------------------------------------------
RELATIVE_VOLUME_THRESHOLD = 3.0     # 평소 대비 거래량 배수 (3배 이상이면 주목)
PRICE_CHANGE_THRESHOLD_PCT = 8.0    # 최근 가격 변동률 %
MAX_PRICE = 20.0                    # 펜니스톡/저가주 상한선 (원하는 대로 조정)
STOCKTWITS_MSG_SPIKE_THRESHOLD = 50 # 최근 시간당 StockTwits 메시지 수 기준


def discover_daily_candidates(max_price=MAX_PRICE, limit=25):
    """
    tickers.txt에만 의존하지 않고, Yahoo Finance가 매일 자체 갱신하는
    실시간 스크리너(day_gainers, most_actives, small_cap_gainers,
    aggressive_small_caps)에서 그날그날 새로운 후보를 자동으로 뽑아온다.
    -> 이게 있어야 "고정 리스트"가 아니라 "매일 달라지는 시장"을 실제로 커버함.
    """
    queries = ["day_gainers", "most_actives", "small_cap_gainers", "aggressive_small_caps"]
    candidates = set()

    for q in queries:
        try:
            result = yf.screen(q, count=limit)
            quotes = result.get("quotes", [])
            for item in quotes:
                symbol = item.get("symbol")
                price = item.get("regularMarketPrice")
                if symbol and (price is None or price <= max_price):
                    candidates.add(symbol)
        except Exception as e:
            print(f"  [스크리너 '{q}' 조회 실패: {e}]")

    return sorted(candidates)


def load_tickers(path="tickers.txt", use_daily_discovery=True):
    """
    1순위: tickers.txt에 수동으로 적어둔 관심종목이 있으면 그걸 우선 사용.
    2순위: use_daily_discovery=True면 Yahoo 실시간 스크리너에서 그날 후보를 자동 발굴.
    3순위: 둘 다 안되면 예시 리스트로 폴백.
    """
    try:
        with open(path) as f:
            tickers = [line.strip().upper() for line in f if line.strip()]
        if tickers:
            print(f"'{path}'에서 수동 지정 티커 {len(tickers)}개 로드")
            return tickers
    except FileNotFoundError:
        pass

    if use_daily_discovery:
        print("tickers.txt 없음 -> Yahoo 실시간 스크리너로 오늘의 후보 자동 발굴 중...")
        discovered = discover_daily_candidates()
        if discovered:
            print(f"오늘 자동 발굴된 후보 {len(discovered)}개: {discovered}")
            return discovered

    # 예시 (원하는 저가주/스몰캡 리스트로 직접 교체하세요)
    print("자동 발굴 실패 -> 예시 리스트로 폴백")
    return ["GNS", "MULN", "SNTG", "BBIG", "ATER", "PROG"]


def get_price_volume_signal(ticker: str) -> dict:
    """yfinance로 최근 가격/거래량 데이터를 받아 급등 징조 계산."""
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="30d", interval="1d")
        if hist.empty or len(hist) < 5:
            return {"ticker": ticker, "error": "데이터 부족"}

        avg_volume = hist["Volume"][:-1].mean()
        last_volume = hist["Volume"].iloc[-1]
        rel_volume = last_volume / avg_volume if avg_volume > 0 else 0

        last_close = hist["Close"].iloc[-1]
        prev_close = hist["Close"].iloc[-2]
        price_change_pct = ((last_close - prev_close) / prev_close) * 100

        # 인트라데이 갭 (오늘 시가 vs 어제 종가) - intraday 데이터 있으면 활용
        gap_pct = None
        try:
            intraday = t.history(period="2d", interval="5m")
            if not intraday.empty:
                today_open = intraday["Open"].iloc[-1]
                gap_pct = ((today_open - prev_close) / prev_close) * 100
        except Exception:
            pass

        return {
            "ticker": ticker,
            "last_close": round(last_close, 3),
            "rel_volume": round(rel_volume, 2),
            "price_change_pct": round(price_change_pct, 2),
            "gap_pct": round(gap_pct, 2) if gap_pct is not None else None,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_stocktwits_signal(ticker: str) -> dict:
    """StockTwits 공개 API에서 최근 메시지량/센티먼트 확인 (키 불필요)."""
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return {"ticker": ticker, "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        messages = data.get("messages", [])
        msg_count = len(messages)

        bullish = sum(
            1 for m in messages
            if m.get("entities", {}).get("sentiment", {}) and
            m["entities"]["sentiment"].get("basic") == "Bullish"
        )
        bearish = sum(
            1 for m in messages
            if m.get("entities", {}).get("sentiment", {}) and
            m["entities"]["sentiment"].get("basic") == "Bearish"
        )

        return {
            "ticker": ticker,
            "st_msg_count": msg_count,
            "st_bullish": bullish,
            "st_bearish": bearish,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_finra_short_volume(ticker: str, date: str = None) -> dict:
    """
    FINRA 일별 숏볼륨 공개 파일에서 해당 티커 데이터 조회.
    파일 예시: https://cdn.finra.org/equity/regsho/daily/CNMSshvolYYYYMMDD.txt
    (전날 데이터가 보통 다음 영업일 아침에 올라옴 - 실시간 아님)
    """
    if date is None:
        date = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y%m%d")
    url = f"https://cdn.finra.org/equity/regsho/daily/CNMSshvol{date}.txt"
    try:
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return {"ticker": ticker, "error": f"FINRA 파일 없음 (HTTP {resp.status_code})"}
        lines = resp.text.strip().split("\n")
        header = lines[0].split("|")
        for line in lines[1:]:
            parts = line.split("|")
            row = dict(zip(header, parts))
            if row.get("Symbol", "").upper() == ticker.upper():
                total_vol = int(row.get("TotalVolume", 0) or 0)
                short_vol = int(row.get("ShortVolume", 0) or 0)
                short_ratio = (short_vol / total_vol * 100) if total_vol else 0
                return {
                    "ticker": ticker,
                    "short_volume_ratio_pct": round(short_ratio, 1),
                }
        return {"ticker": ticker, "error": "해당 티커 없음"}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_fundamentals(ticker: str) -> dict:
    """yfinance에서 기본 재무/유통주식 정보 조회 (무료, 부정확할 수 있음)."""
    try:
        info = yf.Ticker(ticker).info
        market_cap = info.get("marketCap")
        float_shares = info.get("floatShares")
        shares_out = info.get("sharesOutstanding")
        cash = info.get("totalCash")
        debt = info.get("totalDebt")
        insider_pct = info.get("heldPercentInsiders")

        cash_debt_ratio = None
        if cash is not None and debt:
            cash_debt_ratio = round(cash / debt, 2) if debt > 0 else None

        return {
            "ticker": ticker,
            "market_cap": market_cap,
            "float_shares": float_shares,
            "shares_outstanding": shares_out,
            "cash": cash,
            "debt": debt,
            "cash_debt_ratio": cash_debt_ratio,
            "insider_pct": round(insider_pct * 100, 1) if insider_pct else None,
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def get_recent_news(ticker: str, max_items: int = 5) -> list:
    """yfinance 뉴스 + 실패시 Google News RSS로 최근 헤드라인 조회 (제목만, 무료)."""
    headlines = []
    try:
        news = yf.Ticker(ticker).news or []
        for n in news[:max_items]:
            title = n.get("title") or n.get("content", {}).get("title")
            if title:
                headlines.append(title)
    except Exception:
        pass

    if not headlines:
        try:
            url = f"https://news.google.com/rss/search?q={ticker}+stock&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(url, timeout=8)
            if resp.status_code == 200:
                import re
                titles = re.findall(r"<title>(.*?)</title>", resp.text)
                headlines = titles[1:max_items + 1]  # 첫 항목은 피드 제목이라 제외
        except Exception:
            pass

    return headlines


def check_dilution_risk(ticker: str) -> dict:
    """
    SEC EDGAR 전문검색(Full-Text Search)으로 최근 90일 내
    S-1/S-3(유상증자)/424B(공모) 공시가 있었는지 확인 (무료, 키 불필요).
    """
    url = "https://efts.sec.gov/LATEST/search-index"
    params = {
        "q": ticker,
        "forms": "S-1,S-3,424B5,424B3",
        "dateRange": "custom",
        "startdt": (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d"),
        "enddt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    headers = {"User-Agent": "personal-research-script contact@example.com"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            return {"ticker": ticker, "error": f"HTTP {resp.status_code}"}
        data = resp.json()
        hits = data.get("hits", {}).get("total", {}).get("value", 0)
        return {
            "ticker": ticker,
            "recent_dilution_filings_90d": hits,
            "dilution_risk": "높음" if hits >= 2 else ("주의" if hits == 1 else "낮음"),
        }
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}


def composite_score(pv: dict, st: dict, sh: dict) -> float:
    """세 신호를 종합해 0~100점 스코어로 환산 (가중치는 임의 설정, 조정 가능)."""
    score = 0.0

    rel_vol = pv.get("rel_volume") or 0
    price_chg = pv.get("price_change_pct") or 0
    gap = pv.get("gap_pct") or 0

    # 거래량 급증 (최대 35점)
    score += min(rel_vol / RELATIVE_VOLUME_THRESHOLD, 1.0) * 35

    # 가격 변동 (최대 25점)
    score += min(abs(price_chg) / PRICE_CHANGE_THRESHOLD_PCT, 1.0) * 25

    # 갭 (최대 15점)
    if gap:
        score += min(abs(gap) / PRICE_CHANGE_THRESHOLD_PCT, 1.0) * 15

    # 소셜 버즈 (최대 15점)
    msg_count = st.get("st_msg_count") or 0
    score += min(msg_count / STOCKTWITS_MSG_SPIKE_THRESHOLD, 1.0) * 15

    # 숏 비율 높으면 숏스퀴즈 잠재력 가점 (최대 10점)
    short_ratio = sh.get("short_volume_ratio_pct") or 0
    score += min(short_ratio / 50, 1.0) * 10

    return round(score, 1)


def run_screener(tickers, deep_analysis=True):
    results = []
    for ticker in tickers:
        print(f"조회 중: {ticker} ...")
        pv = get_price_volume_signal(ticker)
        st = get_stocktwits_signal(ticker)
        sh = get_finra_short_volume(ticker)
        time.sleep(0.5)  # 무료 API 예의상 딜레이

        if "error" in pv:
            results.append({"ticker": ticker, "status": f"skip ({pv['error']})"})
            continue

        score = composite_score(pv, st, sh)
        row = {
            "ticker": ticker,
            "score": score,
            "last_close": pv.get("last_close"),
            "rel_volume": pv.get("rel_volume"),
            "price_change_pct": pv.get("price_change_pct"),
            "gap_pct": pv.get("gap_pct"),
            "st_msg_count": st.get("st_msg_count"),
            "short_volume_ratio_pct": sh.get("short_volume_ratio_pct"),
        }

        # 스코어가 어느정도 높은 종목만 심층분석 (API 호출 절약)
        if deep_analysis and score >= 30:
            fund = get_fundamentals(ticker)
            dilution = check_dilution_risk(ticker)
            news = get_recent_news(ticker, max_items=3)
            row.update({
                "market_cap": fund.get("market_cap"),
                "float_shares": fund.get("float_shares"),
                "cash_debt_ratio": fund.get("cash_debt_ratio"),
                "insider_pct": fund.get("insider_pct"),
                "dilution_risk": dilution.get("dilution_risk"),
                "recent_dilution_filings_90d": dilution.get("recent_dilution_filings_90d"),
                "recent_news": " | ".join(news) if news else None,
            })
            time.sleep(0.3)

        results.append(row)

    df = pd.DataFrame(results)
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False)
    return df


if __name__ == "__main__":
    tickers = load_tickers()
    print(f"스크리닝 대상 ({len(tickers)}개): {tickers}\n")
    df = run_screener(tickers)
    print("\n=== 결과 (점수 높은 순) ===")
    print(df.to_string(index=False))
    df.to_csv("screener_results.csv", index=False)
    print("\n결과를 screener_results.csv 로 저장했습니다.")

    if "dilution_risk" in df.columns:
        risky = df[df["dilution_risk"] == "높음"]
        if not risky.empty:
            print("\n⚠️  최근 90일 내 희석성 공시(유상증자 등)가 잦은 종목 - 주의:")
            print(risky[["ticker", "recent_dilution_filings_90d"]].to_string(index=False))
