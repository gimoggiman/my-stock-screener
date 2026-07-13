"""
Streamlit 웹앱 - 미국 급등 징조 스크리너 (1시간마다 자동 갱신 버전)
================================================================
- 결과는 GitHub Actions가 1시간마다 백그라운드에서 만들어둔
  latest_results.json 파일을 읽어서 보여줌 (사람이 안 봐도 서버가 자동 갱신)
- 원할 때 "지금 바로 다시 스캔" 버튼도 있음 (그 자리에서 즉시 실행)
- 비밀번호 게이트 포함 (Streamlit Cloud secrets에 설정)

로컬 실행: streamlit run app.py
배포: README_DEPLOY.md 참고
"""

import json
import os
from datetime import datetime, timezone

import streamlit as st
import pandas as pd
import screener_core as core

st.set_page_config(page_title="급등주 스크리너", page_icon="📈", layout="wide")

# ------------------ 비밀번호 게이트 ------------------
# Streamlit Cloud 배포 시 App settings -> Secrets 에 아래처럼 추가하세요:
#   password = "여기에_원하는_비밀번호"
# 로컬 테스트 시엔 .streamlit/secrets.toml 파일에 같은 내용을 넣으면 됩니다.


def check_password():
    def password_entered():
        correct = st.secrets.get("password")
        if correct is None:
            # secrets 설정 안 했으면 게이트 없이 통과 (로컬 테스트 편의용)
            st.session_state["password_correct"] = True
            return
        if st.session_state.get("password_input") == correct:
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct"):
        return True

    st.title("🔒 접속 확인")
    st.text_input("비밀번호", type="password", on_change=password_entered, key="password_input")
    if st.session_state.get("password_correct") is False:
        st.error("비밀번호가 틀렸습니다.")
    return False


if not check_password():
    st.stop()

# ------------------ 메인 화면 ------------------
st.title("📈 미국 소형주 급등 징조 스크리너")
st.caption("무료 데이터 소스 기반 · 1시간마다 자동 갱신 · 투자자문 아님, 참고용")

with st.expander("⚠️ 꼭 읽어주세요 (클릭해서 펼치기)", expanded=False):
    st.markdown("""
- 이 도구는 **예측기가 아니라 패턴 감지기**입니다. 신호가 잡혀도 급등을 보장하지 않고,
  반대로 이미 펌프가 끝나가는 시점일 수도 있습니다.
- 무료 데이터라 실시간이 아니거나(15~20분 지연) 일부 누락될 수 있습니다.
- 투자 손실은 전적으로 본인 책임이며, 이 앱은 투자 자문이 아닙니다.
- 특히 **희석 리스크 '높음'** 종목은 SEC 공시 원문을 직접 확인하세요.
""")

RESULTS_FILE = "latest_results.json"

# 표 헤더를 한글로 보여주기 위한 매핑 (내부 데이터 컬럼명은 그대로 유지)
COLUMN_LABELS = {
    "ticker": "티커",
    "score": "종합점수",
    "last_close": "종가($)",
    "rel_volume": "거래량배수",
    "price_change_pct": "가격변동(%)",
    "gap_pct": "갭(%)",
    "st_msg_count": "소셜언급수",
    "short_volume_ratio_pct": "공매도비율(%)",
    "market_cap": "시가총액($)",
    "float_shares": "유통주식수",
    "cash_debt_ratio": "현금부채비율",
    "insider_pct": "내부자지분(%)",
    "dilution_risk": "희석위험",
    "recent_dilution_filings_90d": "최근90일희석공시수",
    "recent_news": "최근뉴스",
    "status": "상태",
}


def load_saved_results():
    if not os.path.exists(RESULTS_FILE):
        return None
    with open(RESULTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def generate_summary(df: pd.DataFrame) -> str:
    """스코어 상위 종목들을 자연어 문장으로 요약."""
    if df.empty or "score" not in df.columns:
        return "이번 스캔에서 조건에 맞는 종목이 없었습니다."

    top = df.sort_values("score", ascending=False).head(3)
    lines = [f"이번 스캔에서 총 **{len(df)}개** 종목이 조회되었습니다. 점수 상위 종목은 다음과 같습니다:\n"]

    for _, row in top.iterrows():
        parts = [f"- **{row['ticker']}** (점수 {row['score']}점)"]
        if pd.notna(row.get("rel_volume")):
            parts.append(f"거래량 평소의 {row['rel_volume']}배")
        if pd.notna(row.get("price_change_pct")):
            direction = "상승" if row["price_change_pct"] >= 0 else "하락"
            parts.append(f"가격 {abs(row['price_change_pct'])}% {direction}")
        if pd.notna(row.get("dilution_risk")):
            parts.append(f"희석위험 '{row['dilution_risk']}'")
        lines.append(" · ".join(parts))

    if "dilution_risk" in df.columns:
        risky_count = (df["dilution_risk"] == "높음").sum()
        if risky_count:
            lines.append(f"\n⚠️ 이 중 **{risky_count}개** 종목은 최근 90일 내 희석성 공시가 잦아 특히 주의가 필요합니다.")

    return "\n".join(lines)


def render_results(df: pd.DataFrame):
    st.markdown(generate_summary(df))
    st.divider()

    display_df = df.rename(columns=COLUMN_LABELS)
    st.dataframe(display_df, use_container_width=True, hide_index=True)

    if "dilution_risk" in df.columns:
        risky = df[df["dilution_risk"] == "높음"]
        if not risky.empty:
            st.error(
                "⚠️ 최근 90일 내 희석성 공시(유상증자 등)가 잦은 종목 - 주의: "
                + ", ".join(risky["ticker"].tolist())
            )
    csv = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 CSV 다운로드", csv, "screener_results.csv", "text/csv")




# ------------------ 자동 갱신된 최신 결과 표시 ------------------
st.subheader("🕐 자동 스캔 결과 (1시간마다 갱신)")

saved = load_saved_results()
if saved:
    updated_utc = datetime.fromisoformat(saved["last_updated_utc"])
    updated_kst = updated_utc.astimezone(
        timezone.utc
    )  # KST 표시하려면 아래에서 +9시간
    from datetime import timedelta
    updated_kst = updated_utc + timedelta(hours=9)
    st.caption(f"마지막 자동 갱신: {updated_kst.strftime('%Y-%m-%d %H:%M')} (KST) · "
               f"스캔한 종목 수: {saved.get('tickers_scanned', '?')}")

    if saved["results"]:
        df_saved = pd.DataFrame(saved["results"])
        render_results(df_saved)
    else:
        st.warning("최근 자동 스캔에서 조건에 맞는 종목이 없었습니다.")
else:
    st.info(
        "아직 자동 스캔 결과가 없습니다. GitHub Actions 워크플로우가 "
        "처음 실행되면 (최대 1시간 내) 여기에 자동으로 표시됩니다. "
        "지금 바로 확인하려면 아래 수동 스캔을 사용하세요."
    )

st.divider()

# ------------------ 수동 즉시 스캔 (옵션) ------------------
st.subheader("🔍 지금 바로 다시 스캔하기 (선택)")

col1, col2 = st.columns(2)
with col1:
    mode = st.radio("종목 소스", ["오늘의 자동 발굴", "직접 티커 입력"], horizontal=True)
with col2:
    deep = st.checkbox("심층분석 포함 (재무/희석/뉴스)", value=True)

if mode == "직접 티커 입력":
    manual_input = st.text_input("티커 입력 (쉼표로 구분)", "GNS, MULN, SNTG, BBIG, ATER, PROG")
    manual_tickers = [t.strip().upper() for t in manual_input.split(",") if t.strip()]
else:
    manual_tickers = None
    max_price = st.slider("최대 가격 ($)", 1.0, 50.0, float(core.MAX_PRICE), 1.0)
    discover_limit = st.slider("스크리너당 최대 발굴 수", 5, 50, 25, 5)

if st.button("지금 스캔하기", type="primary"):
    if mode != "직접 티커 입력":
        with st.spinner("Yahoo 실시간 스크리너에서 후보 발굴 중..."):
            manual_tickers = core.discover_daily_candidates(max_price=max_price, limit=discover_limit)
        if not manual_tickers:
            st.warning("발굴된 종목이 없습니다.")
            st.stop()
        st.info(f"발굴된 후보 {len(manual_tickers)}개: {', '.join(manual_tickers)}")

    progress = st.progress(0, text="스크리닝 시작...")
    results = []
    for i, ticker in enumerate(manual_tickers):
        progress.progress((i + 1) / len(manual_tickers), text=f"조회 중: {ticker}")
        pv = core.get_price_volume_signal(ticker)
        stw = core.get_stocktwits_signal(ticker)
        sh = core.get_finra_short_volume(ticker)

        if "error" in pv:
            continue

        score = core.composite_score(pv, stw, sh)
        row = {
            "ticker": ticker, "score": score, "last_close": pv.get("last_close"),
            "rel_volume": pv.get("rel_volume"), "price_change_pct": pv.get("price_change_pct"),
            "gap_pct": pv.get("gap_pct"), "st_msg_count": stw.get("st_msg_count"),
            "short_volume_ratio_pct": sh.get("short_volume_ratio_pct"),
        }
        if deep and score >= 30:
            fund = core.get_fundamentals(ticker)
            dilution = core.check_dilution_risk(ticker)
            news = core.get_recent_news(ticker, max_items=3)
            row.update({
                "market_cap": fund.get("market_cap"), "float_shares": fund.get("float_shares"),
                "cash_debt_ratio": fund.get("cash_debt_ratio"), "insider_pct": fund.get("insider_pct"),
                "dilution_risk": dilution.get("dilution_risk"),
                "recent_dilution_filings_90d": dilution.get("recent_dilution_filings_90d"),
                "recent_news": " | ".join(news) if news else None,
            })
        results.append(row)

    progress.empty()
    df = pd.DataFrame(results)
    if "score" in df.columns:
        df = df.sort_values("score", ascending=False)
    render_results(df)
