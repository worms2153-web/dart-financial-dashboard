"""
2단계: dart_fetch.py가 만든 CSV -> 핵심 계정 추출 -> 재무지표 계산

입력 : data/*_CFS_11011.csv  (data 폴더의 모든 회사)
출력 : data/{종목코드}_metrics.csv  (엑셀로 열어도 보기 편한 요약표)
"""

from pathlib import Path

import pandas as pd

# ===================== CONFIG =====================
DATA_DIR = Path("data")
# ==================================================

# 뽑을 계정 목록: 이름 -> (어느 재무제표에서, account_id, 못 찾으면 쓸 계정명)
# account_id가 '-표준계정코드 미사용-'인 계정(단기차입금 등)은 이름으로만 찾을 수 있음
ACCOUNTS = {
    "매출액":        (["IS", "CIS"], "ifrs-full_Revenue", "매출액"),
    "매출총이익":    (["IS", "CIS"], "ifrs-full_GrossProfit", "매출총이익"),
    "매출원가":      (["IS", "CIS"], "ifrs-full_CostOfSales", "매출원가"),
    "영업이익":      (["IS", "CIS"], "dart_OperatingIncomeLoss", "영업이익"),
    "당기순이익":    (["IS", "CIS"], "ifrs-full_ProfitLoss", "당기순이익"),
    "자산총계":      (["BS"], "ifrs-full_Assets", "자산총계"),
    "유동자산":      (["BS"], "ifrs-full_CurrentAssets", "유동자산"),
    "부채총계":      (["BS"], "ifrs-full_Liabilities", "부채총계"),
    "유동부채":      (["BS"], "ifrs-full_CurrentLiabilities", "유동부채"),
    "자본총계":      (["BS"], "ifrs-full_Equity", "자본총계"),
    "매출채권":      (["BS"], "ifrs-full_CurrentTradeReceivables", "매출채권"),
    "재고자산":      (["BS"], "ifrs-full_Inventories", "재고자산"),
    "현금및현금성자산": (["BS"], "ifrs-full_CashAndCashEquivalents", "현금및현금성자산"),
    "단기금융상품":  (["BS"], "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents", "단기금융상품"),
    "단기차입금":    (["BS"], None, "단기차입금"),
    "유동성장기부채": (["BS"], "ifrs-full_CurrentPortionOfLongtermBorrowings", "유동성장기부채"),
    "장기차입금":    (["BS"], "ifrs-full_NoncurrentPortionOfNoncurrentLoansReceived", "장기차입금"),
    "사채":          (["BS"], "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued", "사채"),
    "영업활동현금흐름": (["CF"], "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름"),
    "유형자산취득":  (["CF"], "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "유형자산의 취득"),
}


def pick(year_df: pd.DataFrame, sj_divs, account_id, account_nm):
    """한 연도 데이터에서 계정 하나의 (당기값, 전기값)을 찾음. 못 찾으면 (None, None)."""
    x = year_df[year_df["sj_div"].isin(sj_divs)]
    hit = pd.DataFrame()
    if account_id:                                   # 1순위: 표준 계정ID로 찾기
        hit = x[x["account_id"] == account_id]
    if hit.empty:                                    # 2순위: 계정명으로 찾기
        hit = x[x["account_nm"] == account_nm]
    if hit.empty:
        return None, None
    row = hit.iloc[0]
    return row["thstrm_amount"], row["frmtrm_amount"]


def extract(df: pd.DataFrame) -> pd.DataFrame:
    """연도별 핵심 계정 표 만들기. 행=연도, 열=계정. 전기 값도 같이 뽑음."""
    rows = {}
    for year, g in df.groupby("bsns_year"):
        r = {}
        for name, (sj, aid, anm) in ACCOUNTS.items():
            cur, prev = pick(g, sj, aid, anm)
            r[name] = cur
            r[f"전기_{name}"] = prev                # 전년 대비 비교용 (같은 보고서 안의 전기 컬럼)
        rows[year] = r
    return pd.DataFrame(rows).T.astype(float)


def calc_metrics(a: pd.DataFrame) -> pd.DataFrame:
    """계정 표 -> 지표 표."""
    m = pd.DataFrame(index=a.index)

    # --- 수익성 ---
    m["매출액증가율(%)"] = a["매출액"].pct_change() * 100
    m["영업이익률(%)"] = a["영업이익"] / a["매출액"] * 100
    m["순이익률(%)"] = a["당기순이익"] / a["매출액"] * 100
    avg_eq = (a["자본총계"] + a["전기_자본총계"]) / 2
    avg_as = (a["자산총계"] + a["전기_자산총계"]) / 2
    m["ROE(%)"] = a["당기순이익"] / avg_eq * 100
    m["ROA(%)"] = a["당기순이익"] / avg_as * 100

    # --- 안정성 ---
    m["부채비율(%)"] = a["부채총계"] / a["자본총계"] * 100
    m["유동비율(%)"] = a["유동자산"] / a["유동부채"] * 100
    debt = a[["단기차입금", "유동성장기부채", "장기차입금", "사채"]].sum(axis=1)
    m["차입금(조원)"] = debt / 1e12
    m["순현금(조원)"] = (a["현금및현금성자산"] + a["단기금융상품"] - debt) / 1e12

    # --- 현금흐름 ---
    m["영업CF(조원)"] = a["영업활동현금흐름"] / 1e12
    m["CAPEX(조원)"] = a["유형자산취득"] / 1e12
    m["FCF(조원)"] = (a["영업활동현금흐름"] - a["유형자산취득"]) / 1e12

    return m.T.round(1)   # 행=지표, 열=연도 로 뒤집어서 보기 편하게


def main():
    files = sorted(DATA_DIR.glob("*_CFS_11011.csv"))
    if not files:
        raise SystemExit("data 폴더에 CSV 없음. 먼저 1단계(run.bat) 실행해줘")

    pd.set_option("display.width", 200)
    for in_file in files:
        code = in_file.name.split("_")[0]
        df = pd.read_csv(in_file, dtype={"corp_code": str})
        accounts = extract(df)

        print(f"\n==================== {code} ====================")
        missing = accounts.isna().sum()
        missing = missing[(missing > 0) & ~missing.index.str.startswith("전기_")]
        if not missing.empty:
            print("[주의] 못 찾은 계정이 있음 (연도 수):\n", missing, "\n")

        metrics = calc_metrics(accounts)
        print(metrics.to_string())
        out_file = DATA_DIR / f"{code}_metrics.csv"
        metrics.to_csv(out_file, encoding="utf-8-sig")
        print(f"저장 완료: {out_file}")


if __name__ == "__main__":
    main()
