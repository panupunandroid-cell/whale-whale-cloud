
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime, date

# ---------- CONFIG ----------
INCOME_SHEET_NAME = "รายรับ"
EXPENSE_SHEET_NAME = "รายการรายจ่าย/วันที่"

st.set_page_config(
    page_title="วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud)",
    page_icon=":whale:",
    layout="wide",
)

# ---------- GOOGLE SHEETS HELPERS ----------
@st.cache_resource(show_spinner=False)
def get_gspread_client():
    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(creds_info, scopes=scopes)
    return gspread.authorize(credentials)

@st.cache_resource(show_spinner=False)
def get_worksheet(sheet_name: str):
    client = get_gspread_client()
    sheet_id = st.secrets["sheet_id"]
    sh = client.open_by_key(sheet_id)
    return sh.worksheet(sheet_name)

def load_income_df():
    ws = get_worksheet(INCOME_SHEET_NAME)
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data[1:], columns=data[0])
    # แปลงตัวเลข ถ้าทำได้
    for col in df.columns[1:]:
        df[col] = pd.to_numeric(df[col].replace("", 0), errors="coerce").fillna(0)
    return df

def save_income_for_day(target_date: date, cash, scan, halfhalf, grab, shopee, lineman):
    ws = get_worksheet(INCOME_SHEET_NAME)
    day = target_date.day
    row = day + 1  # +1 เพราะแถวแรกเป็นหัวตาราง
    values = [cash, scan, halfhalf, grab, shopee, lineman]
    cols = [2, 3, 4, 5, 6, 7]  # B-G
    for v, c in zip(values, cols):
        ws.update_cell(row, c, float(v) if v else 0)

def load_expense_items():
    ws = get_worksheet(EXPENSE_SHEET_NAME)
    data = ws.get_all_values()
    # คอลัมน์ A ตั้งแต่แถว 2 ลงไปคือชื่อรายการรายจ่าย
    items = [row[0] for row in data[1:] if row and row[0]]
    return items

def save_expenses_for_day(target_date: date, selected_rows_df: pd.DataFrame):
    if selected_rows_df.empty:
        return
    ws = get_worksheet(EXPENSE_SHEET_NAME)
    data = ws.get_all_values()
    day = target_date.day
    col = day + 1  # B คือวันที่ 1
    # map ชื่อ -> row index
    name_to_row = {}
    for idx, row in enumerate(data[1:], start=2):
        if row and row[0]:
            name_to_row[row[0]] = idx
    for _, r in selected_rows_df.iterrows():
        name = r["รายการรายจ่าย"]
        amount = r["จำนวนเงิน (บาท)"]
        if name in name_to_row:
            ws.update_cell(name_to_row[name], col, float(amount) if amount else 0)

def load_month_summary():
    income_df = load_income_df()
    try:
        expense_ws = get_worksheet(EXPENSE_SHEET_NAME)
        data = expense_ws.get_all_values()
        if not data:
            exp_df = pd.DataFrame()
        else:
            header = data[0]
            exp_df = pd.DataFrame(data[1:], columns=header)
            for c in exp_df.columns[1:]:
                exp_df[c] = pd.to_numeric(exp_df[c].replace("", 0), errors="coerce").fillna(0)
    except Exception:
        exp_df = pd.DataFrame()

    if income_df.empty:
        income_df_numeric = pd.DataFrame()
    else:
        income_df_numeric = income_df.copy()
        for c in income_df_numeric.columns[1:]:
            income_df_numeric[c] = pd.to_numeric(
                income_df_numeric[c].replace("", 0), errors="coerce"
            ).fillna(0)

    # รวมรายรับต่อวันจาก income sheet (ถ้ามีคอลัมน์ รวมต่อวัน แล้วก็ใช้เลย)
    if not income_df_numeric.empty:
        if "รวมต่อวัน" in income_df_numeric.columns:
            daily_income = pd.to_numeric(
                income_df_numeric["รวมต่อวัน"].replace("", 0), errors="coerce"
            ).fillna(0)
        else:
            daily_income = income_df_numeric.iloc[:, 1:].sum(axis=1)
        total_income = float(daily_income.sum())
    else:
        total_income = 0.0

    # รวมรายจ่ายต่อวันจาก expense sheet
    if not exp_df.empty:
        daily_expense = exp_df.iloc[:, 1:].sum(axis=0)  # รวมตามคอลัมน์ (วัน)
        total_expense = float(daily_expense.sum())
    else:
        total_expense = 0.0

    profit = total_income - total_expense
    return total_income, total_expense, profit

# ---------- UI ----------

st.sidebar.image("logo_whale.png", use_column_width=True)
st.sidebar.markdown("### วาฬวาฬ (Cloud)")
selected_date = st.sidebar.date_input("เลือกอ้างอิง (ใช้สำหรับค้นหาข้อมูลรายวัน)", value=date.today())

menu = st.radio(
    "", ["รายรับ", "รายจ่าย", "ผลรวม & กราฟ"],
    horizontal=True,
    index=0,
)

st.markdown("## วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud)")

# ---------- PAGE: INCOME ----------
if menu == "รายรับ":
    st.markdown("### บันทึกรายรับประจำวัน")
    st.caption(f"วันที่ (รายรับ) {selected_date.isoformat()}  จะบันทึกลงแถวที่วันที = {selected_date.day}")

    income_df = load_income_df()

    col_cash, col_scan, col_half, col_grab, col_shopee, col_line = st.columns(6)

    with col_cash:
        cash = st.number_input("เงินสด :moneybag:", min_value=0.0, step=1.0, format="%.2f")
    with col_scan:
        scan = st.number_input("สแกน :credit_card:", min_value=0.0, step=1.0, format="%.2f")
    with col_half:
        half = st.number_input("คนละครึ่ง :handshake:", min_value=0.0, step=1.0, format="%.2f")
    with col_grab:
        grab = st.number_input("Grab :motor_scooter:", min_value=0.0, step=1.0, format="%.2f")
    with col_shopee:
        shopee = st.number_input("Shopee :shopping_trolley:", min_value=0.0, step=1.0, format="%.2f")
    with col_line:
        lineman = st.number_input("LINE Man :runner:", min_value=0.0, step=1.0, format="%.2f")

    save_col, _ = st.columns([1, 5])
    with save_col:
        if st.button("บันทึกรายรับวันนี้", type="primary", use_container_width=True):
            with st.spinner("กำลังบันทึกรายรับลง Google Sheets ..."):
                save_income_for_day(selected_date, cash, scan, half, grab, shopee, lineman)
            st.success("บันทึกรายรับเรียบร้อยแล้ว ✅")
            st.experimental_rerun()

    st.markdown("#### ตารางรายรับทั้งเดือน (จากชีต)")
    if income_df.empty:
        st.info("ยังไม่มีข้อมูลในชีตรายรับ")
    else:
        st.dataframe(income_df, use_container_width=True, height=420)

# ---------- PAGE: EXPENSE ----------
elif menu == "รายจ่าย":
    st.markdown("### บันทึกรายจ่ายประจำวัน")
    st.caption(
        "เลือกติ๊ก ✔ รายการที่มีค่าใช้จ่ายวันนี้ แล้วใส่จำนวนเงินในช่องด้านขวา แล้วกดปุ่ม **บันทึกรายจ่ายวันนี้**"
    )

    try:
        items = load_expense_items()
    except Exception as e:
        st.error(
            "ไม่สามารถโหลดรายการรายจ่ายจาก Google Sheets ได้ กรุณาตรวจสอบชื่อชีต และสิทธิ์การเข้าถึง"
        )
        st.exception(e)
        st.stop()

    # เตรียม data table สำหรับแก้ไข
    df_exp = pd.DataFrame(
        {
            "เลือก": [False] * len(items),
            "รายการรายจ่าย": items,
            "จำนวนเงิน (บาท)": [0.0] * len(items),
        }
    )

    edited_df = st.data_editor(
        df_exp,
        hide_index=True,
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "เลือก": st.column_config.CheckboxColumn("เลือก"),
            "รายการรายจ่าย": st.column_config.TextColumn("รายการรายจ่าย", disabled=True),
            "จำนวนเงิน (บาท)": st.column_config.NumberColumn(
                "จำนวนเงิน (บาท)", min_value=0.0, step=1.0, format="%.2f"
            ),
        },
        height=420,
    )

    btn_col, _ = st.columns([1, 5])
    with btn_col:
        if st.button("บันทึกรายจ่ายวันนี้", type="primary", use_container_width=True):
            selected_rows = edited_df[(edited_df["เลือก"]) & (edited_df["จำนวนเงิน (บาท)"] > 0)]
            if selected_rows.empty:
                st.warning("กรุณาเลือกรายการอย่างน้อย 1 รายการ และใส่จำนวนเงินมากกว่า 0 บาท")
            else:
                with st.spinner("กำลังบันทึกรายจ่ายลง Google Sheets ..."):
                    save_expenses_for_day(selected_date, selected_rows)
                st.success("บันทึกรายจ่ายเรียบร้อยแล้ว ✅")
                st.experimental_rerun()

# ---------- PAGE: SUMMARY ----------
else:
    st.markdown("### สรุปรายรับรายจ่าย และกราฟ")

    total_income, total_expense, profit = load_month_summary()

    col1, col2, col3 = st.columns(3)
    col1.metric("รวมรายรับ", f"{total_income:,.2f} บาท")
    col2.metric("รวมรายจ่าย", f"{total_expense:,.2f} บาท")
    col3.metric("กำไรสุทธิ", f"{profit:,.2f} บาท")

    st.markdown("---")
    st.markdown("#### หมายเหตุ")
    st.write(
        "- ยอดรวมรายรับและรายจ่ายคำนวณจากชีต Google Sheets โดยตรง\n"
        "- หากมีการแก้ไขตัวเลขในชีตโดยตรง สามารถกดปุ่ม Rerun ของ Streamlit เพื่ออัปเดตได้"
    )
