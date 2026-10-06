"""
1단계: DART에서 연결재무제표(CFS)를 받아 CSV로 저장

사용법 (PowerShell):
    pip install requests pandas
    python dart_fetch.py
    -> 처음 한 번만 API 키를 물어보고 .env 파일에 저장함. 다음부터는 자동.

설정은 아래 CONFIG 부분만 바꾸면 됨.
"""

import io
import os
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pandas as pd
import requests

ENV_FILE = Path(".env")


def get_api_key() -> str:
    """키 찾는 순서: 환경변수 -> .env 파일 -> 직접 입력(입력하면 .env에 저장)."""
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key

    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("DART_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
                if key:
                    return key

    key = input("DART API 키를 붙여넣고 엔터 (처음 한 번만 물어봄): ").strip()
    ENV_FILE.write_text(f'DART_API_KEY="{key}"\n', encoding="utf-8")
    print(f"키를 {ENV_FILE.resolve()} 에 저장했음. 다음부터는 안 물어봄.\n")
    return key


# ===================== CONFIG =====================
API_KEY = get_api_key()                        # .env에 저장된 키 사용. 코드에 직접 박지 말 것
STOCK_CODES = ["005930", "000660"]             # 삼성전자, SK하이닉스 (회사 추가는 여기에 종목코드만 넣으면 됨)
OVERWRITE = False                              # False: 이미 받은 회사는 건너뜀 / True: 다시 받음
YEARS = range(2020, 2026)                      # 2020 ~ 2025 사업연도
REPORT_CODE = "11011"                          # 11011 사업보고서 / 11012 반기 / 11013 1분기 / 11014 3분기
FS_DIV = "CFS"                                 # CFS 연결 / OFS 별도
OUT_DIR = Path("data")
# ==================================================

BASE = "https://opendart.fss.or.kr/api"


def load_corp_code(stock_code: str) -> str:
    """종목코드 -> DART 고유번호(corp_code). corpCode.xml은 한 번만 받아서 캐시."""
    OUT_DIR.mkdir(exist_ok=True)
    cache = OUT_DIR / "CORPCODE.xml"

    if not cache.exists():
        res = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": API_KEY}, timeout=30)
        res.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
            cache.write_bytes(zf.read("CORPCODE.xml"))

    root = ET.parse(cache).getroot()
    for item in root.iter("list"):
        if (item.findtext("stock_code") or "").strip() == stock_code:
            return item.findtext("corp_code")
    raise ValueError(f"종목코드 {stock_code} 를 corpCode.xml에서 못 찾음")


def fetch_statement(corp_code: str, year: int) -> pd.DataFrame:
    """단일회사 전체 재무제표 1개 연도분 호출."""
    params = {
        "crtfc_key": API_KEY,
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": REPORT_CODE,
        "fs_div": FS_DIV,
    }
    res = requests.get(f"{BASE}/fnlttSinglAcntAll.json", params=params, timeout=30)
    res.raise_for_status()
    data = res.json()

    # status 000 = 정상, 013 = 조회된 데이터 없음
    if data.get("status") != "000":
        print(f"  [{year}] 실패: {data.get('status')} {data.get('message')}")
        return pd.DataFrame()

    df = pd.DataFrame(data["list"])
    df["bsns_year"] = year
    return df


def to_number(series: pd.Series) -> pd.Series:
    """'1,234,567' 같은 문자열 -> 숫자. 빈 값은 NaN."""
    return pd.to_numeric(series.astype(str).str.replace(",", "", regex=False), errors="coerce")


def fetch_company(stock_code: str):
    """회사 1개: 연도별로 받아서 CSV 1개로 저장."""
    out_path = OUT_DIR / f"{stock_code}_{FS_DIV}_{REPORT_CODE}.csv"
    if out_path.exists() and not OVERWRITE:
        print(f"[{stock_code}] 이미 있음 -> 건너뜀 ({out_path.name})")
        return

    corp_code = load_corp_code(stock_code)
    print(f"[{stock_code}] corp_code {corp_code}")

    frames = []
    for year in YEARS:
        print(f"  {year} 호출 중...")
        df = fetch_statement(corp_code, year)
        if not df.empty:
            frames.append(df)
        time.sleep(0.3)  # 호출 너무 몰아치지 않게

    if not frames:
        print(f"[{stock_code}] 받아온 데이터가 없음. 종목코드/연도 확인")
        return

    all_df = pd.concat(frames, ignore_index=True)

    # 금액 컬럼 숫자로 변환 (thstrm: 당기, frmtrm: 전기, bfefrmtrm: 전전기)
    for col in ["thstrm_amount", "frmtrm_amount", "bfefrmtrm_amount"]:
        if col in all_df.columns:
            all_df[col] = to_number(all_df[col])

    all_df.to_csv(out_path, index=False, encoding="utf-8-sig")  # utf-8-sig: 엑셀에서 한글 안 깨짐
    print(f"[{stock_code}] 저장 완료: {out_path} ({len(all_df)}행)\n")


def main():
    if not API_KEY:
        raise SystemExit("API 키가 비어있음. .env 파일 지우고 다시 실행해서 키 입력해줘")

    OUT_DIR.mkdir(exist_ok=True)
    for code in STOCK_CODES:
        try:
            fetch_company(code)
        except Exception as e:       # 한 회사가 실패해도 다음 회사는 계속 진행
            print(f"[{code}] 에러: {e}\n")


if __name__ == "__main__":
    main()
