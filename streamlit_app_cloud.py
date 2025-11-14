
import streamlit as st
import pandas as pd
import altair as alt
import datetime as dt
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound

st.set_page_config(
    page_title="วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud Debug)",
    page_icon="🐳",
    layout="wide",
)

INCOME_SHEET_NAME = "รายรับ"
EXPENSE_SHEET_NAME = "รายจ่าย"

# -------------------------
# DEBUG HELPERS
# -------------------------
def show_debug(msg):
    st.sidebar.markdown(f"🛠️ **DEBUG:** {msg}")

# -------------------------
# GOOGLE SHEETS HELPERS
# -------------------------
@st.cache_resource
def get_gsheet_client():
    try:
        sa_info = st.secrets["gcp_service_account"]
    except Exception as e:
        st.error(f"❌ อ่านค่า `gcp_service_account` จาก Secrets ไม่ได้\nชนิดข้อผิดพลาด: {type(e).__name__}\nรายละเอียด: {e}")
        st.stop()

    # แสดง debug ว่ามี key อะไรบ้าง (ไม่โชว์ค่า)
    show_debug("gcp_service_account keys: " + ", ".join(sorted(sa_info.keys())))

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    except Exception as e:
        st.error(
            "❌ สร้าง Credentials จาก Service Account ไม่ได้\n"
            f"ชนิดข้อผิดพลาด: {type(e).__name__}\nรายละเอียด: {e}"
        )
        st.stop()

    try:
        client = gspread.authorize(creds)
    except Exception as e:
        st.error(
            "❌ authorize กับ gspread ไม่สำเร็จ\n"
            f"ชนิดข้อผิดพลาด: {type(e).__name__}\nรายละเอียด: {e}"
        )
        st.stop()

    return client

def get_sheet_id_from_secrets():
    sheet_id = st.secrets.get("sheet_id", None)
    if sheet_id is None:
        sa = st.secrets.get("gcp_service_account", {})
        sheet_id = sa.get("sheet_id", None)
    return sheet_id

@st.cache_resource
def get_workbook():
    client = get_gsheet_client()
    sheet_id = get_sheet_id_from_secrets()

    if not sheet_id:
        st.error(
            "❌ ไม่พบค่า `sheet_id` ใน Secrets\n\n"
            "ให้เพิ่มบรรทัดนี้ใน Secrets:\n"
            "```toml\nsheet_id = \"1a_jzfPs1pQJGEx_QgnTs3qFAMfUFLm5JN9E_5QNSMvM\"\n```"
        )
        st.stop()

    show_debug(f"sheet_id = {sheet_id}")

    try:
        sh = client.open_by_key(sheet_id)
    except SpreadsheetNotFound as e:
        st.error(
            "❌ หา Google Sheets ไม่เจอจาก sheet_id นี้ (SpreadsheetNotFound)\n"
            "ตรวจสอบว่า sheet_id ตรงกับรหัสหลัง `/d/` ใน URL ของไฟล์\n\n"
            f"รายละเอียด: {e}"
        )
        st.stop()
    except APIError as e:
        st.error(
            "❌ Google API ตอบกลับว่าเข้าไฟล์ไม่ได้ (APIError)\n"
            "สาเหตุที่พบบ่อย: ยังไม่ได้แชร์ไฟล์ให้ Service Account หรือสิทธิ์ไม่ใช่ Editor\n\n"
            f"รายละเอียด: {e}"
        )
        st.stop()
    except Exception as e:
        st.error(
            "❌ เกิดข้อผิดพลาดไม่ทราบสาเหตุขณะเชื่อมต่อ Google Sheets (Exception)\n"
            f"ชนิดข้อผิดพลาด: {type(e).__name__}\nรายละเอียด: {e}"
        )
        st.stop()

    return sh

# ที่เหลือใช้โค้ดเดียวกับเวอร์ชันก่อน แต่ตัดบางส่วนออกให้สั้นลงสำหรับ debug
def ws_to_df(ws):
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    header = [str(h).strip() for h in data[0]]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=header).replace("", pd.NA)
    df.columns = [str(c).strip() for c in df.columns]
    return df

@st.cache_data(ttl=60)
def load_income_df():
    sh = get_workbook()
    ws = sh.worksheet(INCOME_SHEET_NAME)
    df = ws_to_df(ws)
    return df

# UI เล็ก ๆ แค่เพื่อให้เรียก get_workbook() แล้วเห็น error
st.title("🐳 วาฬวาฬ - Debug การเชื่อมต่อ Google Sheets")

if st.button("ทดสอบเชื่อมต่อ Google Sheets"):
    df = load_income_df()
    st.success(f"โหลดข้อมูลรายรับได้ {len(df)} แถว")
