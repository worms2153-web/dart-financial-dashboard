"""
3단계: 재무제표 이상 징후 탐지

입력 : data/*_CFS_11011.csv  (data 폴더의 모든 회사, metrics.py의 extract 재사용)
출력 : data/{종목코드}_flags.csv  (연도별 점검 결과표)

점검 항목 6개 (기준값은 아래 CONFIG에서 조절)
  1. 매출채권 증가율이 매출 증가율보다 너무 빠른가  -> 외상 매출 부풀리기 의심
  2. 재고자산 증가율이 매출원가 증가율보다 너무 빠른가 -> 안 팔리고 쌓이는 재고 의심
  3. 영업현금흐름이 순이익보다 너무 작은가          -> 장부상 이익만 있고 현금은 없음
  4. 영업이익률이 전년 대비 급락했는가              -> 본업 수익성 악화
  5. 부채비율이 전년 대비 급등했는가                -> 재무 안정성 악화
  6. FCF가 마이너스인가                             -> 벌어서 투자도 못 감당
"""

from pathlib import Path

import pandas as pd

from metrics import extract   # 2단계에서 만든 계정 추출 함수 재사용

# ===================== CONFIG =====================
DATA_DIR = Path("data")

TH_RECEIVABLE_GAP = 10    # 매출채권 증가율 - 매출 증가율 (%p) 가 이 값 초과면 경고
TH_INVENTORY_GAP = 10     # 재고자산 증가율 - 매출원가 증가율 (%p)
TH_CASH_QUALITY = 0.8     # 영업CF / 당기순이익 이 이 값 미만이면 경고
TH_MARGIN_DROP = -5       # 영업이익률 변화 (%p) 가 이 값 미만이면 경고
TH_DEBT_JUMP = 10         # 부채비율 변화 (%p) 가 이 값 초과면 경고
# ==================================================


def growth(cur: pd.Series, prev: pd.Series) -> pd.Series:
    """증가율(%) = (올해 - 작년) / 작년 * 100"""
    return (cur - prev) / prev * 100


def build_checks(a: pd.DataFrame) -> pd.DataFrame:
    """점검 지표 값 계산. 행=연도, 열=점검항목."""
    v = pd.DataFrame(index=a.index)

    v["매출채권-매출 괴리(%p)"] = (growth(a["매출채권"], a["전기_매출채권"])
                              - growth(a["매출액"], a["전기_매출액"]))
    v["재고-매출원가 괴리(%p)"] = (growth(a["재고자산"], a["전기_재고자산"])
                              - growth(a["매출원가"], a["전기_매출원가"]))
    # 순이익이 0 이하(적자)면 이 비율은 의미가 없어서 비움 (적자인데 비율이 음수로 나와 경고 뜨는 오탐 방지)
    positive_ni = a["당기순이익"].where(a["당기순이익"] > 0)
    v["영업CF/순이익(배)"] = a["영업활동현금흐름"] / positive_ni

    margin = a["영업이익"] / a["매출액"] * 100
    prev_margin = a["전기_영업이익"] / a["전기_매출액"] * 100
    v["영업이익률 변화(%p)"] = margin - prev_margin

    debt_ratio = a["부채총계"] / a["자본총계"] * 100
    prev_debt_ratio = a["전기_부채총계"] / a["전기_자본총계"] * 100
    v["부채비율 변화(%p)"] = debt_ratio - prev_debt_ratio

    v["FCF(조원)"] = (a["영업활동현금흐름"] - a["유형자산취득"]) / 1e12
    return v


def build_flags(v: pd.DataFrame) -> pd.DataFrame:
    """기준값과 비교해서 True(경고)/False 표 만들기."""
    f = pd.DataFrame(index=v.index)
    f["매출채권-매출 괴리(%p)"] = v["매출채권-매출 괴리(%p)"] > TH_RECEIVABLE_GAP
    f["재고-매출원가 괴리(%p)"] = v["재고-매출원가 괴리(%p)"] > TH_INVENTORY_GAP
    f["영업CF/순이익(배)"] = v["영업CF/순이익(배)"] < TH_CASH_QUALITY
    f["영업이익률 변화(%p)"] = v["영업이익률 변화(%p)"] < TH_MARGIN_DROP
    f["부채비율 변화(%p)"] = v["부채비율 변화(%p)"] > TH_DEBT_JUMP
    f["FCF(조원)"] = v["FCF(조원)"] < 0
    return f


# 경고가 떴을 때 보여줄 해석 문구
MEANING = {
    "매출채권-매출 괴리(%p)": "매출보다 외상값이 더 빨리 늘었음. 물건을 팔고 돈을 못 받고 있거나 매출이 부풀려졌을 수 있음",
    "재고-매출원가 괴리(%p)": "팔리는 속도보다 재고가 더 빨리 쌓였음. 재고 평가손실이나 감산 가능성 체크",
    "영업CF/순이익(배)": "장부상 이익에 비해 실제로 들어온 현금이 적음 (이익의 질 의심)",
    "영업이익률 변화(%p)": "본업 수익성이 한 해 만에 크게 꺾였음. 원가나 판관비 급증 원인 확인",
    "부채비율 변화(%p)": "빚이 자본보다 훨씬 빠르게 늘었음. 차입 증가 원인 확인",
    "FCF(조원)": "영업으로 번 돈보다 설비투자가 더 많음. 재원은 어디서 조달했는지 확인",
}


def fmt(x) -> str:
    return "-" if pd.isna(x) else f"{x:.1f}"


def main():
    files = sorted(DATA_DIR.glob("*_CFS_11011.csv"))
    if not files:
        raise SystemExit("data 폴더에 CSV 없음. 먼저 1단계(run.bat) 실행해줘")

    pd.set_option("display.width", 220)
    for in_file in files:
        code = in_file.name.split("_")[0]
        df = pd.read_csv(in_file, dtype={"corp_code": str})
        a = extract(df)
        v = build_checks(a)
        f = build_flags(v)

        # 사람이 보기 좋게: 값 옆에 경고면 [!] 붙이기
        shown = v.apply(lambda col: col.map(fmt))
        shown = shown.where(~f, shown + " [!]")

        print(f"\n==================== {code} ====================")
        print("=== 점검표 ([!] = 경고, - = 계산 불가) ===")
        print(shown.T.to_string())

        print("\n=== 경고 상세 ===")
        total = 0
        for year in f.index:
            for col in f.columns:
                if f.loc[year, col]:
                    total += 1
                    print(f"[{year}] {col} = {v.loc[year, col]:.1f}")
                    print(f"       -> {MEANING[col]}")
        if total == 0:
            print("경고 없음")

        out_file = DATA_DIR / f"{code}_flags.csv"
        shown.T.to_csv(out_file, encoding="utf-8-sig")
        print(f"\n저장 완료: {out_file}")


if __name__ == "__main__":
    main()
