
import datetime as dt
from typing import Dict, Any, List

import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
import streamlit as st

# --------------------------------------------------
# Helper: read config safely from st.secrets
# --------------------------------------------------
def get_google_config() -> Dict[str, Any]:
    secrets = st.secrets

    # Try common names for the service-account section
    svc_keys_candidates = [
        "gcp_service_account",
        "gcp_service_account_keys",
        "service_account",
    ]

    svc_info = None
    for key in svc_keys_candidates:
        if key in secrets:
            svc_info = secrets[key]
            break

    if svc_info is None:
        raise RuntimeError(
            "ไม่พบค่าบัญชี service account ใน st.secrets "
            "(ลองตรวจ key: gcp_service_account หรือ gcp_service_account_keys)"
        )

    # Try to locate sheet_id in several possible places
    sheet_id = None
    if "sheet_id" in secrets:
        sheet_id = secrets["sheet_id"]
    else:
        for key in svc_keys_candidates:
            if key in secrets and "sheet_id" in secrets[key]:
                sheet_id = secrets[key]["sheet_id"]
                break

    if not sheet_id:
        raise RuntimeError(
            "ไม่พบค่า sheet_id ใน st.secrets โปรดตรวจใน Secrets ของโปรเจกต์บน Streamlit Cloud "
            "ให้มี key = 'sheet_id' หรืออยู่ในกลุ่ม gcp_service_account / gcp_service_account_keys"
        )

    return {"service_account_info": dict(svc_info), "sheet_id": sheet_id}


@st.cache_resource(show_spinner=False)
def get_client() -> gspread.Client:
    cfg = get_google_config()
    creds = Credentials.from_service_account_info(
        cfg["service_account_info"],
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def get_workbook():
    cfg = get_google_config()
    client = get_client()
    return client.open_by_key(cfg["sheet_id"])


INCOME_SHEET_NAME = "รายการรายรับ/วันที่"
EXPENSE_SHEET_NAME = "รายการรายจ่าย/วันที่"

@st.cache_data(show_spinner="กำลังโหลดข้อมูลรายรับจาก Google Sheets ...", ttl=60)
def load_income_df(month: int, year: int) -> pd.DataFrame:
    sh = get_workbook().worksheet(INCOME_SHEET_NAME)
    df = pd.DataFrame(sh.get_all_records())
    if "วันที่" not in df.columns:
        return df.iloc[0:0]
    df["วันที่"] = pd.to_datetime(df["วันที่"]).dt.date
    return df[(df["วันที่"].apply(lambda d: d.month) == month) & (df["วันที่"].apply(lambda d: d.year) == year)]

@st.cache_data(show_spinner="กำลังโหลดข้อมูลรายจ่ายจาก Google Sheets ...", ttl=60)
def load_expense_df(month: int, year: int) -> pd.DataFrame:
    sh = get_workbook().worksheet(EXPENSE_SHEET_NAME)
    df = pd.DataFrame(sh.get_all_records())
    if "วันที่" not in df.columns:
        return df.iloc[0:0]
    df["วันที่"] = pd.to_datetime(df["วันที่"]).dt.date
    return df[(df["วันที่"].apply(lambda d: d.month) == month) & (df["วันที่"].apply(lambda d: d.year) == year)]

def append_income_row(target_date: dt.date, values: Dict[str, float]) -> None:
    sh = get_workbook().worksheet(INCOME_SHEET_NAME)
    df = pd.DataFrame(sh.get_all_records())

    day_col = "วันที่"
    if day_col not in df.columns:
        df[day_col] = []

    day_numbers = df[day_col].astype(str).str[-2:].astype(int)
    target_day = target_date.day
    if (day_numbers == target_day).any():
        row_idx = day_numbers[day_numbers == target_day].index[0] + 2  # header +1
        row_number = row_idx
    else:
        # append at the bottom
        row_number = len(df) + 2

    row_values: List[Any] = [None] * max(len(df.columns), 8)
    # วันที่
    row_values[0] = target_date.strftime("%Y-%m-%d")
    # เงินสด, สแกน, คนละครึ่ง, Grab, Shopee, LINE Man, รวมต่อวัน
    row_values[1] = float(values.get("เงินสด", 0) or 0)
    row_values[2] = float(values.get("สแกน", 0) or 0)
    row_values[3] = float(values.get("คนละครึ่ง", 0) or 0)
    row_values[4] = float(values.get("Grab", 0) or 0)
    row_values[5] = float(values.get("Shopee", 0) or 0)
    row_values[6] = float(values.get("LINE Man", 0) or 0)
    row_values[7] = (
        row_values[1]
        + row_values[2]
        + row_values[3]
        + row_values[4]
        + row_values[5]
        + row_values[6]
    )

    # Update a single row
    sh.update(f"A{row_number}:H{row_number}", [row_values])


def main():
    st.set_page_config(
        page_title="วาฬวาฬฟ์ - บัญชีรายรับรายจ่าย (Cloud)",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.sidebar.image("logo_whale.png", use_column_width=True)
    st.sidebar.title("วาฬวาฬฟ์ (Cloud)")
    st.sidebar.caption("แอปบันทึกบัญชีรายรับรายจ่ายบน Google Sheets")
    date_str = st.sidebar.date_input("เลือกช่วงอ้างอิง (ใช้สำหรับเดือนในตาราง)", dt.date.today())
    st.sidebar.write(str(date_str))

    st.title("วาฬวาฬฟ์ - บัญชีรายรับรายจ่าย (Cloud)")

    page = st.sidebar.radio("เมนู", ["รายรับ", "รายจ่าย", "ผลรวม & กราฟ"], index=0)

    today = dt.date.today()
    month = date_str.month
    year = date_str.year

    if page == "รายรับ":
        page_income(today, month, year)
    elif page == "รายจ่าย":
        page_expense(today, month, year)
    else:
        page_summary(month, year)


def page_income(today: dt.date, month: int, year: int):
    st.subheader("บันทึกรายรับประจำวัน")

    target_date = st.date_input("วันที่ (รายรับ)", today)
    st.caption(
        f"จะบันทึกลงแถว 'วันที่' = {target_date.day} ในชีต 'รายรับ' "
    )

    col_cash, col_scan, col_pp, col_grab, col_shop, col_line = st.columns(6)

    with col_cash:
        cash = st.number_input("เงินสด 💵", min_value=0.0, step=1.0, format="%.2f")
    with col_scan:
        scan = st.number_input("สแกน 📲", min_value=0.0, step=1.0, format="%.2f")
    with col_pp:
        pp = st.number_input("คนละครึ่ง 🤝", min_value=0.0, step=1.0, format="%.2f")
    with col_grab:
        grab = st.number_input("Grab 🚗", min_value=0.0, step=1.0, format="%.2f")
    with col_shop:
        shopee = st.number_input("Shopee 🛒", min_value=0.0, step=1.0, format="%.2f")
    with col_line:
        lineman = st.number_input("LINE Man 🛵", min_value=0.0, step=1.0, format="%.2f")

    if st.button("บันทึกรายรับวันนี้", type="primary"):
        values = {
            "เงินสด": cash,
            "สแกน": scan,
            "คนละครึ่ง": pp,
            "Grab": grab,
            "Shopee": shopee,
            "LINE Man": lineman,
        }
        append_income_row(target_date, values)
        st.success("บันทึกรายรับเรียบร้อยแล้ว ✅")
        # clear cache and trigger rerun to show latest table
        load_income_df.clear()
        st.experimental_rerun()

    st.markdown("### ตารางรายรับทั้งเดือน (จากชีต)")
    try:
        df_month = load_income_df(month, year)
        st.dataframe(df_month, use_container_width=True, height=420)
    except Exception as e:
        st.error(f"โหลดข้อมูลรายรับไม่สำเร็จ: {e}")


def page_expense(today: dt.date, month: int, year: int):
    st.subheader("บันทึกรายจ่ายประจำวัน")
    st.write("หน้ารายจ่ายใหม่ (แบบตารางกระชับ) อยู่ในไฟล์เวอร์ชันถัดไป 😄")


def page_summary(month: int, year: int):
    st.subheader("สรุปรายรับรายจ่าย และกราฟ (อยู่ระหว่างปรับปรุงในเวอร์ชันนี้)")
    st.info("หน้านี้ยังใช้โครงแบบเดิมจากเวอร์ชันก่อนหน้า")


if __name__ == "__main__":
    main()
