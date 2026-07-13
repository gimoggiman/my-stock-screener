"""
Streamlit 웹앱 - 미국 급등 징조 스크리너
=========================================
로컬 실행: streamlit run app.py
배포: Streamlit Community Cloud (무료) - README_DEPLOY.md 참고
"""

import streamlit as st
import pandas as pd
import screener_core as core

st.set_page_config(page_title="급등주 스크리너", page_icon="📈", layout="wide")

st.title("📈 미국 소형주 급등 징조 스크리너")
st.caption("무료 데이터 소스 기반 · 투자자문 아님 · 참고용")

with st.expander("⚠️ 꼭 읽어주세요 (클릭해서 펼치기)", expanded=False):
    st.markdown("""
- 이 도구는 **예측기가 아니라 패턴 감지기**입니다. 신호가 잡혀도 급등을 보장하지 않습니다.
- 무료 데이터라 실시간이 아니거나(15~20분 지연) 일부 누락될 수 있습니다.
- 투자 손실은 전적으로 본인 책임이며, 이 앱은 투자 자문이 아닙니다.
- 특히 **희석 리스크 '높음'** 종목은 SEC 공시 원문을 직접 확인하세요.
""")

# ------------------ 사이드바: 설정 ------------------
st.sidebar.header("⚙️ 설정")

mode = st.sidebar.radio(
    "종목 소스",
    ["오늘의 자동 발굴 (Yahoo 실시간 스크리너)", "직접 티커 입력"],
)

if mode == "직접 티커 입력":
    manual_input = st.sidebar.text_area(
        "티커 입력 (쉼표로 구분)", "GNS, MULN, SNTG, BBIG, ATER, PROG"
    )
    tickers = [t.strip().upper() for t in manual_input.split(",") if t.strip()]
else:
    max_price = st.sidebar.slider("최대 가격 ($)", 1.0, 50.0, float(core.MAX_PRICE), 1.0)
    discover_limit = st.sidebar.slider("스크리너당 최대 발굴 수", 5, 50, 25, 5)
    tickers = None  # 버튼 누르면 그때 발굴

deep = st.sidebar.checkbox("심층분석 포함 (재무/희석/뉴스)", value=True)
score_threshold = st.sidebar.slider("심층분석 스코어 기준", 0, 100, 30, 5)
core.RELATIVE_VOLUME_THRESHOLD = st.sidebar.slider("거래량 급증 기준(배)", 1.0, 10.0, 3.0, 0.5)
core.PRICE_CHANGE_THRESHOLD_PCT = st.sidebar.slider("가격변동 기준(%)", 1.0, 30.0, 8.0, 1.0)

run_btn = st.sidebar.button("🔍 지금 스캔하기", type="primary", use_container_width=True)

# ------------------ 메인: 실행 ------------------
if run_btn:
    if mode != "직접 티커 입력":
        with st.spinner("Yahoo 실시간 스크리너에서 오늘의 후보 발굴 중..."):
            tickers = core.discover_daily_candidates(max_price=max_price, limit=discover_limit)
        if not tickers:
            st.warning("자동 발굴된 종목이 없습니다. 직접 티커 입력 모드를 사용해보세요.")
            st.stop()
        st.info(f"오늘 발굴된 후보 {len(tickers)}개: {', '.join(tickers)}")

    progress = st.progress(0, text="스크리닝 시작...")
    results = []
    for i, ticker in enumerate(tickers):
        progress.progress((i + 1) / len(tickers), text=f"조회 중: {ticker}")
        pv = core.get_price_volume_signal(ticker)
        stw = core.get_stocktwits_signal(ticker)
        sh = core.get_finra_short_volume(ticker)

        if "error" in pv:
            results.append({"ticker": ticker, "status": f"skip ({pv['error']})"})
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

        if deep and score >= score_threshold:
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

    progress.empty()
    df = pd.DataFrame(results)
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False)

    st.subheader("📊 결과")
    st.dataframe(df, use_container_width=True, hide_index=True)

    if "dilution_risk" in df.columns:
        risky = df[df["dilution_risk"] == "높음"]
        if not risky.empty:
            st.error(
                "⚠️ 최근 90일 내 희석성 공시(유상증자 등)가 잦은 종목 - 주의: "
                + ", ".join(risky["ticker"].tolist())
            )

    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 CSV 다운로드", csv, "screener_results.csv", "text/csv")
else:
    st.info("왼쪽에서 설정을 확인하고 **'지금 스캔하기'** 버튼을 눌러주세요.")
