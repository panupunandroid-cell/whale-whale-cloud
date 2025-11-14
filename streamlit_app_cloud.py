
import streamlit as st
import pandas as pd
import altair as alt
import datetime as dt
import gspread
from google.oauth2.service_account import Credentials

# ------------------------------
# CONFIG
# ------------------------------
st.set_page_config(
    page_title="วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud)",
    page_icon="🐳",
    layout="wide",
)

INCOME_SHEET_NAME = "รายรับร้าน"
EXPENSE_SHEET_NAME = "รายจ่ายร้าน"

# ------------------------------
# GOOGLE SHEETS CLIENT
# ------------------------------
@st.cache_resource
def get_gsheet_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=scopes,
    )
    client = gspread.authorize(creds)
    return client

@st.cache_resource
def get_workbook():
    client = get_gsheet_client()
    # ใช้ sheet_id จาก secrets
    sh = client.open_by_key(st.secrets["sheet_id"])
    return sh

def ws_to_df(ws):
    """แปลง worksheet เป็น DataFrame โดยใช้แถวแรกเป็นหัวตาราง"""
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    header = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=header)
    # แปลงค่าว่างเป็น NaN
    df = df.replace('', pd.NA)
    return df

def df_to_ws(ws, df):
    """(ไม่ใช้ในเวอร์ชันนี้เพื่อเลี่ยงทับข้อมูลทั้งหมด)"""
    raise NotImplementedError

# ------------------------------
# DATA LOADERS
# ------------------------------
@st.cache_data(ttl=60)
def load_income_df():
    sh = get_workbook()
    ws = sh.worksheet(INCOME_SHEET_NAME)
    df = ws_to_df(ws)
    if df.empty:
        return df

    # คอลัมน์ "วันที่" ควรเป็น 1-31
    df["วันที่"] = pd.to_numeric(df["วันที่"], errors="coerce")
    df = df[df["วันที่"].notna()]
    df["วันที่"] = df["วันที่"].astype(int)

    income_cols = ["เงินสด", "สแกน", "คนละครึ่ง", "Grab", "Shopee", "LINE Man"]
    for c in income_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
        else:
            df[c] = 0.0
    df["รวมต่อวัน"] = df[income_cols].sum(axis=1)
    return df

@st.cache_data(ttl=60)
def load_expense_df():
    sh = get_workbook()
    ws = sh.worksheet(EXPENSE_SHEET_NAME)
    df = ws_to_df(ws)
    if df.empty:
        return df

    # ตัดแถวรวมทั้งเดือนถ้ามี
    if "รายการรายจ่าย/วันที่" in df.columns:
        df = df[df["รายการรายจ่าย/วันที่"] != "รวมทั้งเดือน"].copy()

    # แปลงคอลัมน์วันที่ (ที่เป็นตัวเลข 1-31) ให้เป็นตัวเลข
    for col in df.columns:
        if col.isdigit():
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    return df

# ------------------------------
# UPDATE FUNCTIONS
# ------------------------------
def update_income_row(day, cash, scan, half, grab, shopee, lineman):
    sh = get_workbook()
    ws = sh.worksheet(INCOME_SHEET_NAME)
    data = ws.get_all_values()
    if not data:
        st.error("ชีตรายรับร้านยังไม่มีโครงสร้างตาราง")
        return

    header = data[0]
    # หา index ของคอลัมน์
    def col_idx(col_name):
        return header.index(col_name) + 1  # 1-based

    try:
        col_day = header.index("วันที่") + 1
    except ValueError:
        st.error("ไม่พบคอลัมน์ 'วันที่' ในชีตรายรับร้าน")
        return

    target_row = None
    for i in range(1, len(data)):  # เริ่มจากแถวที่ 2 (index=1)
        cell_val = data[i][col_day - 1]
        try:
            d = int(float(cell_val))
            if d == day:
                target_row = i + 1  # 1-based
                break
        except Exception:
            continue

    if target_row is None:
        st.error("ไม่พบแถวของวันที่นี้ในชีตรายรับร้าน")
        return

    updates = {
        "เงินสด": cash,
        "สแกน": scan,
        "คนละครึ่ง": half,
        "Grab": grab,
        "Shopee": shopee,
        "LINE Man": lineman,
    }
    for name, val in updates.items():
        if name in header:
            c = col_idx(name)
            ws.update_cell(target_row, c, float(val) if val is not None else 0)

    st.cache_data.clear()

def update_expense_cell(day, item_name, amount):
    sh = get_workbook()
    ws = sh.worksheet(EXPENSE_SHEET_NAME)
    data = ws.get_all_values()
    if not data:
        st.error("ชีตรายจ่ายร้านยังไม่มีโครงสร้างตาราง")
        return

    header = data[0]
    try:
        col_day = header.index(str(day)) + 1
    except ValueError:
        st.error(f"ไม่พบคอลัมน์วันที่ {day} ในชีตรายจ่ายร้าน")
        return

    # หาแถวของชื่อรายการ
    target_row = None
    for i in range(1, len(data)):
        if data[i][0] == item_name:
            target_row = i + 1
            break

    if target_row is None:
        st.error("ไม่พบชื่อรายการรายจ่ายในชีตรายจ่ายร้าน")
        return

    ws.update_cell(target_row, col_day, float(amount) if amount is not None else 0)
    st.cache_data.clear()

# ------------------------------
# SUMMARY HELPERS
# ------------------------------
def build_daily_summary(base_date: dt.date):
    inc = load_income_df()
    exp = load_expense_df()

    # income
    if inc.empty:
        inc_daily = pd.DataFrame(columns=["วันที่", "รวมรับ"])
    else:
        inc_daily = inc[["วันที่", "รวมต่อวัน"]].copy()
        inc_daily = inc_daily.rename(columns={"รวมต่อวัน": "รวมรับ"})

    # expense
    if exp.empty:
        exp_daily = pd.DataFrame(columns=["วันที่", "รวมจ่าย"])
    else:
        day_cols = [c for c in exp.columns if c.isdigit()]
        tmp = exp[day_cols].sum(axis=0)  # index = '1','2',...
        exp_daily = (
            tmp.reset_index()
            .rename(columns={"index": "วันที่", 0: "รวมจ่าย"})
        )
        exp_daily["วันที่"] = exp_daily["วันที่"].astype(int)

    df = pd.merge(inc_daily, exp_daily, on="วันที่", how="outer").fillna(0.0)
    df["รวมรับ"] = df["รวมรับ"].astype(float)
    df["รวมจ่าย"] = df["รวมจ่าย"].astype(float)
    df["กำไรสุทธิ"] = df["รวมรับ"] - df["รวมจ่าย"]

    year = base_date.year
    month = base_date.month
    df["วันที่จริง"] = df["วันที่"].apply(lambda d: dt.date(year, month, int(d)))
    df = df.sort_values("วันที่จริง")
    return df

def build_expense_pie(start_date: dt.date, end_date: dt.date, base_date: dt.date):
    exp = load_expense_df()
    if exp.empty:
        return pd.DataFrame(columns=["รายการ", "ยอดรวม"])

    year = base_date.year
    month = base_date.month
    current = start_date
    days = []
    while current <= end_date:
        if current.year == year and current.month == month:
            days.append(str(current.day))
        current += dt.timedelta(days=1)

    day_cols = [d for d in days if d in exp.columns]
    if not day_cols:
        return pd.DataFrame(columns=["รายการ", "ยอดรวม"])

    exp["ยอดรวม"] = exp[day_cols].sum(axis=1)
    df = exp[["รายการรายจ่าย/วันที่", "ยอดรวม"]].copy()
    df = df[df["ยอดรวม"] > 0]
    df = df.rename(columns={"รายการรายจ่าย/วันที่": "รายการ"})
    return df

# ------------------------------
# FILTER MODE
# ------------------------------
def filter_by_mode(df_daily, mode: str, base_date: dt.date):
    if df_daily.empty:
        return df_daily, base_date, base_date

    if mode == "รายวัน":
        target = st.date_input("เลือกวัน", value=base_date, key="daily_date")
        mask = df_daily["วันที่จริง"] == target
        return df_daily[mask], target, target

    elif mode == "รายสัปดาห์":
        start = st.date_input("วันเริ่มต้นสัปดาห์", value=base_date, key="week_start")
        end = start + dt.timedelta(days=6)
        mask = (df_daily["วันที่จริง"] >= start) & (df_daily["วันที่จริง"] <= end)
        return df_daily[mask], start, end

    elif mode == "รายเดือน":
        year = base_date.year
        month = base_date.month
        start = dt.date(year, month, 1)
        end = dt.date(year, month, 28) + dt.timedelta(days=4)
        end = dt.date(year, month, min(31, end.day))
        mask = (df_daily["วันที่จริง"] >= start) & (df_daily["วันที่จริง"] <= end)
        return df_daily[mask], start, end

    else:
        col1, col2 = st.columns(2)
        with col1:
            start = st.date_input("วันที่เริ่มต้น", value=base_date, key="range_start")
        with col2:
            end = st.date_input("วันที่สิ้นสุด", value=base_date, key="range_end")
        if end < start:
            st.warning("วันที่สิ้นสุดต้องไม่น้อยกว่าวันที่เริ่มต้น")
            return df_daily.iloc[0:0], start, end
        mask = (df_daily["วันที่จริง"] >= start) & (df_daily["วันที่จริง"] <= end)
        return df_daily[mask], start, end

# ------------------------------
# UI
# ------------------------------
with st.sidebar:
    try:
        st.image("logo_whale.png", width=120)
    except Exception:
        st.write("🐳")
    st.markdown("## วาฬวาฬ (Cloud)")
    st.caption("แอปบันทึกบัญชีรายรับรายจ่ายบน Google Sheets")

    base_date = st.date_input("เดือนอ้างอิง", value=dt.date.today())

st.title("🐳 วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud)")

tab_input, tab_dash = st.tabs(["✏️ บันทึกข้อมูล", "📊 สรุป & กราฟ"])

# ------------------------------
# TAB: บันทึกข้อมูล
# ------------------------------
with tab_input:
    st.subheader("บันทึกรายรับ / รายจ่าย ประจำวัน")

    col_left, col_right = st.columns(2)

    # ===== รายรับ =====
    with col_left:
        st.markdown("### รายรับ")
        income_date = st.date_input("วันที่ (รายรับ)", value=dt.date.today(), key="income_date")
        day = income_date.day
        st.caption(f"จะบันทึกลง 'วันที่' = {day} ในชีต '{INCOME_SHEET_NAME}'")

        inc_df = load_income_df()
        row = inc_df.loc[inc_df["วันที่"] == day] if not inc_df.empty else pd.DataFrame()

        def get_val(col):
            if row.empty or col not in row.columns:
                return 0.0
            v = row.iloc[0][col]
            return float(v) if pd.notna(v) else 0.0

        c1, c2, c3 = st.columns(3)
        with c1:
            cash = st.number_input("เงินสด", min_value=0.0, step=10.0, value=get_val("เงินสด"))
            grab = st.number_input("Grab", min_value=0.0, step=10.0, value=get_val("Grab"))
        with c2:
            scan = st.number_input("สแกน", min_value=0.0, step=10.0, value=get_val("สแกน"))
            shopee = st.number_input("Shopee", min_value=0.0, step=10.0, value=get_val("Shopee"))
        with c3:
            half = st.number_input("คนละครึ่ง", min_value=0.0, step=10.0, value=get_val("คนละครึ่ง"))
            lineman = st.number_input("LINE Man", min_value=0.0, step=10.0, value=get_val("LINE Man"))

        if st.button("บันทึกรายรับวันนี้", type="primary"):
            update_income_row(day, cash, scan, half, grab, shopee, lineman)
            st.success("บันทึกรายรับเรียบร้อยแล้ว ✅")

    # ===== รายจ่าย =====
    with col_right:
        st.markdown("### รายจ่าย")
        expense_date = st.date_input("วันที่ (รายจ่าย)", value=dt.date.today(), key="expense_date")
        day_e = expense_date.day
        st.caption(f"จะบันทึกลงวันที่ {day_e} ในชีต '{EXPENSE_SHEET_NAME}'")

        exp_df = load_expense_df()
        if "รายการรายจ่าย/วันที่" in exp_df.columns:
            items = exp_df["รายการรายจ่าย/วันที่"].dropna().tolist()
        else:
            items = []

        if not items:
            st.warning("ชีตรายจ่ายร้านยังไม่มีรายการรายจ่าย กรุณาเตรียมโครงสร้างใน Google Sheets ก่อน")
        else:
            item = st.selectbox("เลือกประเภทค่าใช้จ่าย", items)
            amount = st.number_input("จำนวนเงิน", min_value=0.0, step=10.0, value=0.0)

            if st.button("บันทึกรายจ่ายรายการนี้", type="primary"):
                update_expense_cell(day_e, item, amount)
                st.success("บันทึกรายจ่ายเรียบร้อยแล้ว ✅")

            st.markdown("#### รายการรายจ่ายของวันนั้น")
            day_col = str(day_e)
            if day_col in exp_df.columns:
                tmp = exp_df[["รายการรายจ่าย/วันที่", day_col]].copy()
                tmp = tmp.rename(columns={day_col: "ยอด"})
                tmp["ยอด"] = pd.to_numeric(tmp["ยอด"], errors="coerce").fillna(0.0)
                tmp = tmp[tmp["ยอด"] > 0]
                st.dataframe(tmp.reset_index(drop=True), use_container_width=True)
            else:
                st.info("ยังไม่พบคอลัมน์วันนี้ในชีตรายจ่ายร้าน")

# ------------------------------
# TAB: สรุป & กราฟ
# ------------------------------
with tab_dash:
    st.subheader("สรุปภาพรวม")

    daily = build_daily_summary(base_date)

    if daily.empty:
        st.info("ยังไม่มีข้อมูลรายรับ/รายจ่ายในชีต")
    else:
        col1, col2 = st.columns([1, 3])
        with col1:
            mode = st.radio(
                "เลือกรูปแบบ",
                ["รายวัน", "รายสัปดาห์", "รายเดือน", "ช่วงวันที่กำหนดเอง"],
                index=2,
            )

        filtered, start_d, end_d = filter_by_mode(daily, mode, base_date)

        if filtered.empty:
            st.warning("ไม่มีข้อมูลในช่วงวันที่ที่เลือก")
        else:
            total_inc = filtered["รวมรับ"].sum()
            total_exp = filtered["รวมจ่าย"].sum()
            net = filtered["กำไรสุทธิ"].sum()

            c1, c2, c3 = st.columns(3)
            c1.metric("รวมรายรับ", f"{total_inc:,.0f} บาท")
            c2.metric("รวมรายจ่าย", f"{total_exp:,.0f} บาท")
            c3.metric("กำไรสุทธิ", f"{net:,.0f} บาท")

            st.markdown(f"ช่วงวันที่ {start_d.strftime('%d/%m/%Y')} - {end_d.strftime('%d/%m/%Y')}")

            st.markdown("#### ตารางสรุป")
            st.dataframe(
                filtered[["วันที่จริง", "รวมรับ", "รวมจ่าย", "กำไรสุทธิ"]]
                .rename(columns={"วันที่จริง": "วันที่"})
                .reset_index(drop=True),
                use_container_width=True,
            )

            # กราฟแท่ง
            st.markdown("#### กราฟแท่งรายรับ-รายจ่ายตามวัน")
            chart_data = filtered.melt(
                id_vars=["วันที่จริง"],
                value_vars=["รวมรับ", "รวมจ่าย"],
                var_name="ประเภท",
                value_name="ยอด",
            )
            bar = (
                alt.Chart(chart_data)
                .mark_bar()
                .encode(
                    x="วันที่จริง:T",
                    y="ยอด:Q",
                    color="ประเภท:N",
                    tooltip=["วันที่จริง:T", "ประเภท:N", "ยอด:Q"],
                )
                .properties(height=320)
            )
            st.altair_chart(bar, use_container_width=True)

            # กราฟวงกลมรายจ่าย
            st.markdown("#### กราฟวงกลมรายจ่ายตามประเภท")
            pie_df = build_expense_pie(start_d, end_d, base_date)
            if pie_df.empty:
                st.info("ไม่มีข้อมูลรายจ่ายสำหรับทำกราฟวงกลมในช่วงนี้")
            else:
                pie = (
                    alt.Chart(pie_df)
                    .mark_arc()
                    .encode(
                        theta="ยอดรวม:Q",
                        color="รายการ:N",
                        tooltip=["รายการ:N", "ยอดรวม:Q"],
                    )
                    .properties(height=350)
                )
                st.altair_chart(pie, use_container_width=True)
