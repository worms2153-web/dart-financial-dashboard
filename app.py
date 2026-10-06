"""
4단계: Streamlit 대시보드

실행: streamlit run app.py   (또는 run_app.bat 더블클릭)
필요: data/ 폴더에 *_CFS_11011.csv (1단계 결과)가 있어야 함

앞에서 만든 코드를 그대로 재사용함
  metrics.py   -> extract, calc_metrics  (계정 추출, 지표 계산)
  anomalies.py -> build_checks, build_flags, MEANING  (이상 징후 탐지)
"""

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

import anomalies
from metrics import calc_metrics, extract

DATA_DIR = Path("data")

st.set_page_config(page_title="연결재무제표 분석기", layout="wide")


# ---------------------------------------------------------------- 데이터 로딩
@st.cache_data
def company_name(stock_code: str) -> str:
    """종목코드 -> 회사명. 1순위 company_names.csv(배포용), 2순위 CORPCODE.xml(내 PC), 없으면 종목코드."""
    names_path = DATA_DIR / "company_names.csv"
    if names_path.exists():
        names = pd.read_csv(names_path, dtype=str, encoding="utf-8-sig")
        hit = names[names["stock_code"] == stock_code]
        if not hit.empty:
            return hit.iloc[0]["corp_name"]

    xml_path = DATA_DIR / "CORPCODE.xml"
    if xml_path.exists():
        for item in ET.parse(xml_path).getroot().iter("list"):
            if (item.findtext("stock_code") or "").strip() == stock_code:
                return item.findtext("corp_name")
    return stock_code


@st.cache_data
def load_accounts(stock_code: str) -> pd.DataFrame:
    """원본 CSV -> 연도별 핵심 계정 표 (metrics.py의 extract)."""
    df = pd.read_csv(DATA_DIR / f"{stock_code}_CFS_11011.csv", dtype={"corp_code": str})
    return extract(df)


def style_chart(fig, unit=""):
    # 범례/툴팁에 보일 이름에서 "(%)", "(조원)" 같은 괄호 단위를 뗌 (단위는 축 제목과 툴팁 값 뒤에 붙음)
    fig.for_each_trace(lambda t: t.update(name=re.sub(r"\(.*?\)", "", t.name).strip()))
    # 툴팁: "variable= / index= / value=" 같은 영어 라벨 없이 "영업이익률: 13.1%" 형태로
    fig.update_traces(hovertemplate="%{fullData.name}: %{y:,.1f}" + unit + "<extra></extra>")
    fig.update_layout(
        xaxis_type="category",       # 연도를 숫자가 아니라 라벨로 취급
        xaxis_title=None,
        yaxis_title=unit,
        legend_title=None,
        hovermode="x unified",
        margin=dict(t=50, b=20),
    )
    return fig


def fmt_table(df: pd.DataFrame, decimals: int = 1):
    """표 숫자를 천 단위 쉼표 + 소수점 N자리로 표시."""
    return df.style.format("{:,.%df}" % decimals, na_rep="-")


# ---------------------------------------------------------------- 사이드바
files = sorted(DATA_DIR.glob("*_CFS_11011.csv"))
if not files:
    st.error("data 폴더에 재무제표 CSV가 없음. 먼저 run.bat (1단계)부터 실행해줘.")
    st.stop()

codes = [f.name.split("_")[0] for f in files]
labels = {c: f"{company_name(c)} ({c})" for c in codes}

st.sidebar.header("설정")
code = st.sidebar.selectbox("회사", codes, format_func=lambda c: labels[c])

st.sidebar.subheader("이상 징후 기준값")
anomalies.TH_RECEIVABLE_GAP = st.sidebar.slider("매출채권-매출 괴리 (%p) 초과", 0, 50, anomalies.TH_RECEIVABLE_GAP)
anomalies.TH_INVENTORY_GAP = st.sidebar.slider("재고-매출원가 괴리 (%p) 초과", 0, 50, anomalies.TH_INVENTORY_GAP)
anomalies.TH_CASH_QUALITY = st.sidebar.slider("영업CF/순이익 (배) 미만", 0.0, 2.0, float(anomalies.TH_CASH_QUALITY), 0.1)
anomalies.TH_MARGIN_DROP = st.sidebar.slider("영업이익률 변화 (%p) 미만", -30, 0, anomalies.TH_MARGIN_DROP)
anomalies.TH_DEBT_JUMP = st.sidebar.slider("부채비율 변화 (%p) 초과", 0, 100, anomalies.TH_DEBT_JUMP)

# ---------------------------------------------------------------- 계산
a = load_accounts(code)
m = calc_metrics(a).T            # 행=연도, 열=지표
v = anomalies.build_checks(a)    # 점검 지표 값
f = anomalies.build_flags(v)     # 경고 여부 (True/False)

for d in (a, m, v, f):
    d.index = d.index.astype(str)    # 연도를 문자열로 (차트/표 표시용)

last, prev = m.iloc[-1], m.iloc[-2]
year = m.index[-1]

# 회사마다 계정 이름/코드가 달라서 못 찾은 계정이 있을 수 있음 -> 조용히 틀리지 않게 화면에 알림
missing = [c for c in a.columns if not c.startswith("전기_") and a[c].isna().any()]
if missing:
    st.warning("일부 연도에서 못 찾은 계정: " + ", ".join(missing)
               + " (회사에 원래 없는 계정이면 무시해도 됨. 있어야 되는 계정이면 해당 지표가 부정확할 수 있음)")

# ---------------------------------------------------------------- 상단
st.title(f"{company_name(code)} 연결재무제표 분석")
st.caption(f"DART 사업보고서(연결) 기준 · {m.index[0]}~{year} · 단위: 조원 (별도 표기 제외)")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(f"{year} 매출액", f"{a.loc[year, '매출액'] / 1e12:,.1f}조",
          f"{last['매출액증가율(%)']:+.1f}%")
c2.metric("영업이익률", f"{last['영업이익률(%)']:.1f}%",
          f"{last['영업이익률(%)'] - prev['영업이익률(%)']:+.1f}%p")
c3.metric("ROE", f"{last['ROE(%)']:.1f}%",
          f"{last['ROE(%)'] - prev['ROE(%)']:+.1f}%p")
c4.metric("부채비율", f"{last['부채비율(%)']:.1f}%",
          f"{last['부채비율(%)'] - prev['부채비율(%)']:+.1f}%p", delta_color="inverse")
c5.metric("FCF", f"{last['FCF(조원)']:.1f}조",
          f"{last['FCF(조원)'] - prev['FCF(조원)']:+.1f}조")

n_flags = int(f.values.sum())
n_last = int(f.loc[year].sum())
if n_last:
    st.warning(f"{year}년 기준 이상 징후 {n_last}건 감지 (전체 기간 {n_flags}건). '이상 징후' 탭에서 확인.")
else:
    st.success(f"{year}년 기준 감지된 이상 징후 없음 (전체 기간 {n_flags}건).")

# ---------------------------------------------------------------- 탭
tab1, tab2, tab3, tab4, tab5 = st.tabs(["수익성", "안정성", "현금흐름", "이상 징후", "데이터"])

with tab1:
    left, right = st.columns(2)
    rev = pd.DataFrame({"매출액": a["매출액"] / 1e12, "영업이익": a["영업이익"] / 1e12,
                        "당기순이익": a["당기순이익"] / 1e12})
    left.plotly_chart(style_chart(px.bar(rev, barmode="group", title="매출 · 이익 추이"), "조원"))
    right.plotly_chart(style_chart(
        px.line(m[["영업이익률(%)", "순이익률(%)", "ROE(%)"]], markers=True, title="수익성 지표"), "%"))

with tab2:
    left, right = st.columns(2)
    left.plotly_chart(style_chart(
        px.line(m[["부채비율(%)"]], markers=True, title="부채비율 (부채총계 / 자본총계)"), "%"))
    cash = m[["차입금(조원)", "순현금(조원)"]]
    right.plotly_chart(style_chart(px.bar(cash, barmode="group", title="차입금 vs 순현금"), "조원"))
    st.plotly_chart(style_chart(
        px.line(m[["유동비율(%)"]], markers=True, title="유동비율 (유동자산 / 유동부채)"), "%"))

with tab3:
    cf = m[["영업CF(조원)", "CAPEX(조원)", "FCF(조원)"]]
    st.plotly_chart(style_chart(px.bar(cf, barmode="group", title="영업CF · CAPEX · FCF"), "조원"))
    st.caption("FCF = 영업활동현금흐름 − 유형자산 취득 (무형자산 취득은 제외한 단순 계산)")

with tab4:
    st.subheader("점검표")
    st.caption("빨간 칸이 경고. 경고는 분식회계 판정이 아니라 '확인해볼 신호'임. 기준값은 왼쪽 사이드바에서 조절.")

    vt = v.round(1).T
    ft = f.T

    def highlight(_):
        css = np.where(ft.values, "background-color: #ffd6d6; color: #b00020; font-weight: bold", "")
        return pd.DataFrame(css, index=ft.index, columns=ft.columns)

    st.dataframe(vt.style.apply(highlight, axis=None).format("{:.1f}", na_rep="-"))

    st.subheader("경고 상세")
    found = False
    for y in reversed(list(f.index)):               # 최근 연도부터
        for col in f.columns:
            if f.loc[y, col]:
                found = True
                st.error(f"**{y}년 · {col} = {v.loc[y, col]:.1f}**  \n{anomalies.MEANING[col]}")
    if not found:
        st.info("경고 없음")

with tab5:
    st.subheader("지표 요약")
    st.dataframe(fmt_table(m.T))
    st.download_button("지표 CSV 다운로드", m.T.to_csv().encode("utf-8-sig"),
                       file_name=f"{code}_metrics.csv", mime="text/csv")

    st.subheader("핵심 계정 (백만원)")
    st.caption("DART 공시와 같은 단위라서 원문이랑 바로 대조 가능")
    core = a[["매출액", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계"]] / 1e6
    st.dataframe(fmt_table(core.T, decimals=0))
