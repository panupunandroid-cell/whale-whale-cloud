import streamlit as st
import pandas as pd
import altair as alt
import datetime as dt
# --- รีเซ็ต session อัตโนมัติเมื่อเปลี่ยนวัน ---
if "last_open_date" not in st.session_state:
    st.session_state.last_open_date = dt.date.today()
elif st.session_state.last_open_date != dt.date.today():
    st.session_state.clear()
    st.session_state.last_open_date = dt.date.today()
# -------------------------------------------------
import streamlit.components.v1 as components
import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, SpreadsheetNotFound, WorksheetNotFound

from pathlib import Path

# ------------------------------
# CONFIG
# ------------------------------
st.set_page_config(
    page_title="วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud)",
    page_icon="🐳",
    layout="wide",
)

INCOME_SHEET_NAME = "รายรับ"
EXPENSE_SHEET_NAME = "รายจ่าย"

# ------------------------------
# GOOGLE SHEETS
# ------------------------------
@st.cache_resource
def get_gsheet_client():
    sa_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    client = gspread.authorize(creds)
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
        st.error("ไม่พบค่า sheet_id ใน Secrets")
        st.stop()

    try:
        sh = client.open_by_key(sheet_id)
    except SpreadsheetNotFound:
        st.error("หาไฟล์ Google Sheets ไม่เจอจาก sheet_id นี้")
        st.stop()
    except APIError:
        st.error(
            "Google Sheets API ไม่อนุญาตให้เข้าไฟล์นี้ ตรวจสอบว่าแชร์ไฟล์ให้ Service Account แล้วและเปิด Google Sheets API / Drive API แล้ว"
        )
        st.stop()
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดขณะเชื่อมต่อ Google Sheets: {e}")
        st.stop()
    return sh


def ws_to_df(ws):
    data = ws.get_all_values()
    if not data:
        return pd.DataFrame()
    header = [str(h).strip() for h in data[0]]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=header).replace("", pd.NA)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def _get_monthly_sheet_title(base_name: str, ref_date: dt.date) -> str:
    """สร้างชื่อชีตตามเดือน เช่น รายรับ_2025_11"""
    return f"{base_name}_{ref_date.year}_{ref_date.month:02d}"


def get_worksheet_for_month(base_name: str, ref_date: dt.date, kind: str, create_if_missing: bool):
    """
    คืนค่า worksheet ของเดือนที่ต้องการ

    - ถ้า create_if_missing=False:
        ถ้าไม่พบชีตตามเดือน จะ fallback ไปใช้ชีตพื้นฐาน (base_name)
    - ถ้า create_if_missing=True:
        ถ้าไม่พบ จะสร้างชีตใหม่โดยใช้ชีตพื้นฐานเป็น template ถ้ามี

    kind: "income" หรือ "expense" เพื่อกำหนด header เริ่มต้นเมื่อไม่มี template
    """
    sh = get_workbook()
    monthly_title = _get_monthly_sheet_title(base_name, ref_date)

    # ลองหาชีตตามเดือนก่อน
    try:
        return sh.worksheet(monthly_title)
    except WorksheetNotFound:
        pass

    # ถ้าไม่ต้องสร้างใหม่ ให้ fallback ไปใช้ชีตพื้นฐาน (ถ้ามี)
    if not create_if_missing:
        try:
            return sh.worksheet(base_name)
        except WorksheetNotFound:
            st.error(f"ไม่พบชีต '{monthly_title}' หรือชีตพื้นฐาน '{base_name}' ในไฟล์ Google Sheets")
            st.stop()

    # ต้องการสร้างใหม่: พยายามใช้ชีตพื้นฐานเป็น template
    template_data = []
    try:
        template_ws = sh.worksheet(base_name)
        template_data = template_ws.get_all_values()
    except WorksheetNotFound:
        template_ws = None  # noqa: F841

    if template_data:
        header_row = template_data[0]
        num_cols = len(header_row)
        new_data = [header_row]

        # คัดลอกเฉพาะชื่อแถว/วันที่ในคอลัมน์แรก ค่าอื่นให้เคลียร์ว่าง
        for row in template_data[1:]:
            first_col = row[0] if row else ""
            new_row = [first_col] + [""] * (num_cols - 1)
            new_data.append(new_row)

        rows = len(new_data) + 5
        cols = num_cols + 5
        ws = sh.add_worksheet(title=monthly_title, rows=rows, cols=cols)
        ws.update("A1", new_data)
        return ws

    # กรณีไม่มี template เลย สร้างโครงพื้นฐานใหม่
    if kind == "income":
        header = ["วันที่", "เงินสด", "สแกน", "คนละครึ่ง", "Grab", "Shopee", "LINE Man"]
        rows = 32
        cols = len(header)
        ws = sh.add_worksheet(title=monthly_title, rows=rows, cols=cols)
        ws.update("A1", [header])
        # ใส่วันที่ 1-31 ในคอลัมน์แรก
        date_values = [[str(i)] for i in range(1, 32)]
        ws.update("A2", date_values)
        return ws
    else:
        header = ["รายการรายจ่าย/วันที่"] + [str(i) for i in range(1, 32)]
        rows = 50
        cols = len(header)
        ws = sh.add_worksheet(title=monthly_title, rows=rows, cols=cols)
        ws.update("A1", [header])
        return ws


# ------------------------------
# LOAD DATA (ตามเดือน)
# ------------------------------
@st.cache_data(ttl=60)
def load_income_df(ref_date: dt.date):
    ws = get_worksheet_for_month(INCOME_SHEET_NAME, ref_date, kind="income", create_if_missing=False)
    df = ws_to_df(ws)
    if df.empty:
        return df

    if "วันที่" not in df.columns:
        df = df.rename(columns={df.columns[0]: "วันที่"})

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
def load_expense_df(ref_date: dt.date):
    ws = get_worksheet_for_month(EXPENSE_SHEET_NAME, ref_date, kind="expense", create_if_missing=False)
    df = ws_to_df(ws)
    if df.empty:
        return df

    if "รายการรายจ่าย/วันที่" not in df.columns:
        df = df.rename(columns={df.columns[0]: "รายการรายจ่าย/วันที่"})

    if "รายการรายจ่าย/วันที่" in df.columns:
        df = df[df["รายการรายจ่าย/วันที่"] != "รวมทั้งเดือน"].copy()

    for col in df.columns:
        if str(col).strip().isdigit():
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    return df


# ------------------------------
# UPDATE FUNCTIONS
# ------------------------------
def update_income_row(date_obj: dt.date, cash, scan, half, grab, shopee, lineman):
    """อัปเดตรายรับของวันที่ในเดือนที่ระบุ ถ้าไม่มีชีตของเดือนนั้นจะสร้างใหม่ให้"""
    ws = get_worksheet_for_month(INCOME_SHEET_NAME, date_obj, kind="income", create_if_missing=True)
    data = ws.get_all_values()
    if not data:
        st.error("ชีต 'รายรับ' ยังไม่มีโครงสร้างตาราง")
        return

    header = [str(h).strip() for h in data[0]]
    try:
        col_day = header.index("วันที่") + 1
    except ValueError:
        col_day = 1

    def col_idx(name):
        return header.index(name) + 1 if name in header else None

    day = date_obj.day
    target_row = None
    for i in range(1, len(data)):
        v = data[i][col_day - 1]
        try:
            d = int(float(v))
            if d == day:
                target_row = i + 1
                break
        except Exception:
            continue

    if target_row is None:
        st.error("ไม่พบแถวของวันที่นี้ในชีต 'รายรับ'")
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
        c = col_idx(name)
        if c:
            ws.update_cell(target_row, c, float(val) if val is not None else 0)

    st.cache_data.clear()


def update_expense_cell(date_obj: dt.date, day, item_name, amount):
    """อัปเดตรายจ่ายของวันที่ในเดือนที่ระบุ ถ้าไม่มีชีตของเดือนนั้นจะสร้างใหม่ให้"""
    ws = get_worksheet_for_month(EXPENSE_SHEET_NAME, date_obj, kind="expense", create_if_missing=True)
    data = ws.get_all_values()
    if not data:
        st.error("ชีต 'รายจ่าย' ยังไม่มีโครงสร้างตาราง")
        return

    header = [str(h).strip() for h in data[0]]
    try:
        col_day = header.index(str(day)) + 1
    except ValueError:
        st.error(f"ไม่พบคอลัมน์วันที่ {day} ในชีต 'รายจ่าย'")
        return

    target_row = None
    for i in range(1, len(data)):
        if data[i][0] == item_name:
            target_row = i + 1
            break

    if target_row is None:
        st.error("ไม่พบชื่อรายการรายจ่ายในชีต 'รายจ่าย'")
        return

    ws.update_cell(target_row, col_day, float(amount) if amount is not None else 0)
    st.cache_data.clear()


# ------------------------------
# SUMMARY & CHART
# ------------------------------
def build_daily_summary(base_date: dt.date):
    inc = load_income_df(base_date)
    exp = load_expense_df(base_date)

    if inc.empty:
        inc_daily = pd.DataFrame(columns=["วันที่", "รวมรับ"])
    else:
        inc_daily = inc[["วันที่", "รวมต่อวัน"]].rename(columns={"รวมต่อวัน": "รวมรับ"})

    if exp.empty:
        exp_daily = pd.DataFrame(columns=["วันที่", "รวมจ่าย"])
    else:
        day_cols = [c for c in exp.columns if str(c).strip().isdigit()]
        tmp = exp[day_cols].sum(axis=0)
        exp_daily = tmp.reset_index().rename(columns={"index": "วันที่", 0: "รวมจ่าย"})
        exp_daily["วันที่"] = exp_daily["วันที่"].astype(int)

    df = pd.merge(inc_daily, exp_daily, on="วันที่", how="outer").fillna(0.0)
    df["รวมรับ"] = df["รวมรับ"].astype(float)
    df["รวมจ่าย"] = df["รวมจ่าย"].astype(float)
    df["กำไรสุทธิ"] = df["รวมรับ"] - df["รวมจ่าย"]

    y, mth = base_date.year, base_date.month
    df["วันที่จริง"] = df["วันที่"].apply(lambda d: dt.date(y, mth, int(d)))
    df = df.sort_values("วันที่จริง")
    return df


def build_expense_pie(start_date: dt.date, end_date: dt.date, base_date: dt.date):
    exp = load_expense_df(base_date)
    if exp.empty:
        return pd.DataFrame(columns=["รายการ", "ยอดรวม"])

    y, mth = base_date.year, base_date.month
    cur = start_date
    days = []
    while cur <= end_date:
        if cur.year == y and cur.month == mth:
            days.append(str(cur.day))
        cur += dt.timedelta(days=1)

    day_cols = [d for d in days if d in exp.columns]
    if not day_cols:
        return pd.DataFrame(columns=["รายการ", "ยอดรวม"])

    exp["ยอดรวม"] = exp[day_cols].sum(axis=1)
    df = exp[["รายการรายจ่าย/วันที่", "ยอดรวม"]].copy()
    df = df[df["ยอดรวม"] > 0]
    df = df.rename(columns={"รายการรายจ่าย/วันที่": "รายการ"})
    return df


def build_income_pie(start_date: dt.date, end_date: dt.date, base_date: dt.date):
    """สร้างข้อมูลสำหรับกราฟวงกลม รายรับตามประเภท ในช่วงวันที่ที่เลือก"""
    inc = load_income_df(base_date)
    if inc.empty:
        return pd.DataFrame(columns=["ประเภท", "ยอดรวม"])

    y, mth = base_date.year, base_date.month
    cur = start_date
    days = []
    while cur <= end_date:
        if cur.year == y and cur.month == mth:
            days.append(cur.day)
        cur += dt.timedelta(days=1)

    if not days:
        return pd.DataFrame(columns=["ประเภท", "ยอดรวม"])

    inc_sel = inc[inc["วันที่"].isin(days)].copy()
    if inc_sel.empty:
        return pd.DataFrame(columns=["ประเภท", "ยอดรวม"])

    income_cols = ["เงินสด", "สแกน", "คนละครึ่ง", "Grab", "Shopee", "LINE Man"]
    rows = []
    for col in income_cols:
        if col in inc_sel.columns:
            total = float(pd.to_numeric(inc_sel[col], errors="coerce").sum())
        else:
            total = 0.0
        if total > 0:
            rows.append({"ประเภท": col, "ยอดรวม": total})

    if not rows:
        return pd.DataFrame(columns=["ประเภท", "ยอดรวม"])
    return pd.DataFrame(rows)


def filter_by_mode(df_daily, mode: str, base_date: dt.date):
    if df_daily.empty:
        return df_daily, base_date, base_date

    if mode == "รายวัน":
        target = st.date_input("เลือกวัน", value=base_date, key="sum_daily")
        mask = df_daily["วันที่จริง"] == target
        return df_daily[mask], target, target

    elif mode == "รายสัปดาห์":
        # ใช้สัปดาห์รูปแบบ พฤหัสบดี -> อังคาร
        ref = st.date_input("เลือกวันในสัปดาห์", value=base_date, key="sum_week_ref")
        # weekday(): Monday=0 ... Sunday=6, ดังนั้น Thursday=3
        offset = (ref.weekday() - 3) % 7
        start = ref - dt.timedelta(days=offset)
        end = start + dt.timedelta(days=5)  # พฤหัสบดีถึงอังคาร รวม 6 วัน
        mask = (df_daily["วันที่จริง"] >= start) & (df_daily["วันที่จริง"] <= end)
        return df_daily[mask], start, end

    elif mode == "รายเดือน":
        y, mth = base_date.year, base_date.month
        start = dt.date(y, mth, 1)
        if mth == 12:
            end = dt.date(y, 12, 31)
        else:
            end = dt.date(y, mth + 1, 1) - dt.timedelta(days=1)
        mask = (df_daily["วันที่จริง"] >= start) & (df_daily["วันที่จริง"] <= end)
        return df_daily[mask], start, end

    else:
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input("วันที่เริ่มต้น", value=base_date, key="sum_range_start")
        with c2:
            end = st.date_input("วันที่สิ้นสุด", value=base_date, key="sum_range_end")
        if end < start:
            st.warning("วันที่สิ้นสุดต้องไม่น้อยกว่าวันที่เริ่มต้น")
            return df_daily.iloc[0:0], start, end
        mask = (df_daily["วันที่จริง"] >= start) & (df_daily["วันที่จริง"] <= end)
        return df_daily[mask], start, end


# ------------------------------
# UI
# ------------------------------
with st.sidebar:
    logo_path = Path(__file__).with_name("logo_whale.png")
    if logo_path.exists():
        st.image(str(logo_path), use_container_width=True)
    st.markdown("### 🐳 วาฬวาฬ (Cloud)")
    st.caption("แอปบันทึกบัญชีรายรับรายจ่ายบน Google Sheets")
    base_date = st.date_input("เดือนอ้างอิง (ใช้สำหรับคำนวณรายงาน)", value=dt.date.today())

st.title("🐳 วาฬวาฬ - บัญชีรายรับรายจ่าย (Cloud)")
st.caption("เวอร์ชัน V.1.1")

tab_income, tab_expense, tab_summary = st.tabs(["📥 รายรับ", "📤 รายจ่าย", "📊 ผลประกอบการ & กราฟ"])

# TAB รายรับ
with tab_income:
    st.subheader("บันทึกรายรับประจำวัน")
    d_in = st.date_input("วันที่ (รายรับ)", value=dt.date.today(), key="income_date")
    day = d_in.day
    st.caption(f"จะบันทึกลงแถว 'วันที่' = {day} ในชีตของเดือนนั้น")


    inc_df = load_income_df(d_in)
    if not inc_df.empty:
        row = inc_df.loc[inc_df["วันที่"] == day]
    else:
        row = pd.DataFrame()

    def get_inc_val(col):
        if row.empty or col not in row.columns:
            return 0.0
        v = row.iloc[0][col]
        return float(v) if pd.notna(v) else 0.0

    c1, c2, c3 = st.columns(3)
    with c1:
        cash = st.number_input("เงินสด 💵", min_value=0.0, step=10.0, value=get_inc_val("เงินสด"))
        grab = st.number_input("Grab 🛵", min_value=0.0, step=10.0, value=get_inc_val("Grab"))
    with c2:
        scan = st.number_input("สแกน 📲", min_value=0.0, step=10.0, value=get_inc_val("สแกน"))
        shopee = st.number_input("Shopee 🛒", min_value=0.0, step=10.0, value=get_inc_val("Shopee"))
    with c3:
        half = st.number_input("คนละครึ่ง 🤝", min_value=0.0, step=10.0, value=get_inc_val("คนละครึ่ง"))
        lineman = st.number_input("LINE Man 🛵", min_value=0.0, step=10.0, value=get_inc_val("LINE Man"))

    if st.button("บันทึกรายรับวันนี้", type="primary"):
        # อัปเดตรายรับลง Google Sheets (แยกชีตตามเดือน)
        update_income_row(d_in, cash, scan, half, grab, shopee, lineman)
        st.success("บันทึกรายรับเรียบร้อยแล้ว ✅")
        # โหลดข้อมูลรายรับใหม่หลังอัปเดต เพื่อให้ตารางด้านล่างเป็นค่าล่าสุดทันที
        inc_df = load_income_df(d_in)

    if not inc_df.empty:
        st.markdown("#### ตารางรายรับทั้งเดือน (จากชีตของเดือนนั้น)")
        st.dataframe(inc_df, use_container_width=True)

# TAB รายจ่าย
with tab_expense:
    st.subheader("บันทึกรายจ่ายประจำวัน")
    d_ex = st.date_input("วันที่ (รายจ่าย)", value=dt.date.today(), key="expense_date")
    day_e = d_ex.day
    st.caption(f"จะบันทึกลงวันที่ {day_e} ในชีตของเดือนนั้น")


    exp_df = load_expense_df(d_ex)
    if "รายการรายจ่าย/วันที่" in exp_df.columns:
        items = exp_df["รายการรายจ่าย/วันที่"].dropna().tolist()
    else:
        items = []

    if not items:
        st.warning("ชีต 'รายจ่าย' ยังไม่มีรายการรายจ่าย กรุณาเตรียมโครงสร้างใน Google Sheets ก่อน")
    else:
        st.markdown("เลือกติ๊ก ✔ รายการที่มีค่าใช้จ่ายวันนี้ แล้วใส่จำนวนเงินในตาราง จากนั้นกดปุ่ม **บันทึกรายจ่ายวันนี้**")


        col_day = str(day_e)
        default_amounts = []
        for item_name in items:
            amt = 0.0
            if col_day in exp_df.columns:
                row_match = exp_df[exp_df["รายการรายจ่าย/วันที่"] == item_name]
                if not row_match.empty:
                    v = pd.to_numeric(row_match.iloc[0][col_day], errors="coerce")
                    if pd.notna(v):
                        amt = float(v)
            default_amounts.append(amt)

        df_items = pd.DataFrame({
            "เลือก": [False] * len(items),
            "รายการรายจ่าย": items,
            "จำนวนเงิน (บาท)": default_amounts,
        })

        # ป้องกันไม่ให้มีค่า None ในคอลัมน์จำนวนเงิน (แก้ปัญหาแก้ไขไม่ได้บน iPad/Safari)
        df_items["จำนวนเงิน (บาท)"] = pd.to_numeric(df_items["จำนวนเงิน (บาท)"], errors="coerce").fillna(0.0)

        edited_items = st.data_editor(
            df_items,
            key="expense_editor",
            use_container_width=True,
            hide_index=True,
            column_config={
                "เลือก": st.column_config.CheckboxColumn("เลือก"),
                "รายการรายจ่าย": st.column_config.TextColumn("รายการรายจ่าย", disabled=True),
                "จำนวนเงิน (บาท)": st.column_config.NumberColumn(
                    "จำนวนเงิน (บาท)", min_value=0.0, step=1.0, format="%.2f"
                ),
            },
        )

        if st.button("บันทึกรายจ่ายวันนี้", type="primary"):
            saved_any = False
            for _, row_state in edited_items.iterrows():
                if bool(row_state["เลือก"]) and float(row_state["จำนวนเงิน (บาท)"]) > 0:
                    update_expense_cell(d_ex, day_e, row_state["รายการรายจ่าย"], float(row_state["จำนวนเงิน (บาท)"]))
                    saved_any = True

            if saved_any:
                st.success("บันทึกรายจ่ายสำหรับรายการที่เลือกเรียบร้อยแล้ว ✅")
                # โหลดข้อมูลรายจ่ายใหม่ เพื่อให้ตารางด้านล่างแสดงค่าล่าสุดทันที
                exp_df = load_expense_df(d_ex)
            else:
                st.warning("กรุณาติ๊กเลือกอย่างน้อย 1 รายการ และใส่จำนวนเงินมากกว่า 0 บาท")


        col_day = str(day_e)
        st.markdown("#### รายการรายจ่ายของวันนั้น")
        if col_day in exp_df.columns:
            tmp = exp_df[["รายการรายจ่าย/วันที่", col_day]].copy()
            tmp = tmp.rename(columns={col_day: "ยอด"})
            tmp["ยอด"] = pd.to_numeric(tmp["ยอด"], errors="coerce").fillna(0.0)
            tmp = tmp[tmp["ยอด"] > 0]
            st.dataframe(tmp.reset_index(drop=True), use_container_width=True)
        else:
            st.info("ยังไม่พบคอลัมน์วันนี้ในชีต 'รายจ่าย'")

# TAB สรุป
with tab_summary:
    st.subheader("สรุปรายรับรายจ่าย และกราฟ")
    daily = build_daily_summary(base_date)
    if daily.empty:
        st.info("ยังไม่มีข้อมูลรายรับ/รายจ่ายในชีต")
    else:
        col_mode, _ = st.columns([1, 3])
        with col_mode:
            mode = st.radio(
                "เลือกรูปแบบสรุป",
                ["รายวัน", "รายสัปดาห์", "รายเดือน", "ช่วงวันที่กำหนดเอง"],
                index=2,
            )

        filtered, start_d, end_d = filter_by_mode(daily, mode, base_date)

        # สร้างรายงานสรุปรายรับ-รายจ่ายในรูปแบบ HTML สำหรับพรีวิวและสั่งพิมพ์
        if not filtered.empty:
            total_income = float(filtered.get("รวมรับ", pd.Series(dtype=float)).sum())
            total_expense = float(filtered.get("รวมจ่าย", pd.Series(dtype=float)).sum())
            profit = total_income - total_expense

            # เตรียมแถวตารางรายวัน
            table_rows = ""
            for _, r in filtered.iterrows():
                day_label = r.get("วันที่แสดง", r.get("วันที่", ""))
                try:
                    inc_val = float(r.get("รวมรับ", 0) or 0)
                except Exception:
                    inc_val = 0.0
                try:
                    exp_val = float(r.get("รวมจ่าย", 0) or 0)
                except Exception:
                    exp_val = 0.0
                prof_val = inc_val - exp_val
                table_rows += f"<tr><td>{day_label}</td><td style='text-align:right;'>{inc_val:,.2f}</td><td style='text-align:right;'>{exp_val:,.2f}</td><td style='text-align:right;'>{prof_val:,.2f}</td></tr>"

            period_text = start_d.strftime("%d/%m/%Y")
            if end_d != start_d:
                period_text = f"{start_d.strftime('%d/%m/%Y')} - {end_d.strftime('%d/%m/%Y')}"

            period_text_str = period_text
            total_income_str = f"{total_income:,.2f}"
            total_expense_str = f"{total_expense:,.2f}"
            profit_str = f"{profit:,.2f}"

            report_html = """<html><head><meta charset='utf-8'>
<style>
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; padding:16px; color:#222; }}
h2 {{ margin-top:0; }}
table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; font-size: 13px; }}
th {{ background:#f1f3ff; text-align:center; }}
.summary-box {{ margin-top:12px; padding:10px 12px; background:#f7fbff; border-radius:8px; border:1px solid #dde7ff; }}
.btn-print {{ padding:6px 12px; border-radius:6px; border:none; background:#ff4b4b; color:white; cursor:pointer; font-size:13px; }}
.btn-print:hover {{ opacity:0.9; }}
.header-row {{ display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:4px; }}
</style>
</head>
<body>
<div class='header-row'>
  <h2>รายงานสรุปรายรับ–รายจ่าย</h2>
  <button class='btn-print' onclick='window.print()'>🖨️ พิมพ์รายงาน</button>
</div>
<p>ช่วงวันที่: <strong>{period_text}</strong></p>
<div class='summary-box'>
    <div>รวมรายรับ: <strong>{total_income}</strong> บาท</div>
    <div>รวมรายจ่าย: <strong>{total_expense}</strong> บาท</div>
    <div>กำไรสุทธิ: <strong>{profit}</strong> บาท</div>
</div>
<table>
    <thead>
        <tr>
            <th>วันที่</th>
            <th>รวมรับ (บาท)</th>
            <th>รวมจ่าย (บาท)</th>
            <th>กำไรต่อวัน (บาท)</th>
        </tr>
    </thead>
    <tbody>
        {table_rows}
    </tbody>
</table>
</body></html>""".format(
                period_text=period_text_str,
                total_income=total_income_str,
                total_expense=total_expense_str,
                profit=profit_str,
                table_rows=table_rows,
            )

            components.html(report_html, height=500, scrolling=True)

        if filtered.empty:
            st.warning("ไม่มีข้อมูลในช่วงวันที่ที่เลือก")
        else:
            total_inc = filtered["รวมรับ"].sum()
            total_exp = filtered["รวมจ่าย"].sum()
            net = filtered["กำไรสุทธิ"].sum()

            m1, m2, m3 = st.columns(3)
            m1.metric("รวมรายรับ", f"{total_inc:,.0f} บาท")
            m2.metric("รวมจ่าย", f"{total_exp:,.0f} บาท")
            m3.metric("กำไรสุทธิ", f"{net:,.0f} บาท")

            st.markdown(f"ช่วงวันที่ {start_d.strftime('%d/%m/%Y')} - {end_d.strftime('%d/%m/%Y')}")

            st.markdown("#### ตารางสรุป")
            st.dataframe(
                filtered[["วันที่จริง", "รวมรับ", "รวมจ่าย", "กำไรสุทธิ"]]
                .rename(columns={"วันที่จริง": "วันที่"})
                .reset_index(drop=True),
                use_container_width=True,
            )

            st.markdown("#### กราฟแท่ง รายรับ-รายจ่ายต่อวัน")
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

            st.markdown("#### กราฟวงกลม รายรับ / รายจ่าย ตามประเภท")
            col_in, col_ex = st.columns(2)

            with col_in:
                pie_inc_df = build_income_pie(start_d, end_d, base_date)
                if pie_inc_df.empty:
                    st.info("ไม่มีข้อมูลรายรับสำหรับทำกราฟวงกลมในช่วงนี้")
                else:
                    pie_inc = (
                        alt.Chart(pie_inc_df)
                        .mark_arc()
                        .encode(
                            theta="ยอดรวม:Q",
                            color=alt.Color(
                                "ประเภท:N",
                                scale=alt.Scale(
                                    domain=["Grab", "LINE Man", "Shopee", "คนละครึ่ง", "สแกน", "เงินสด"],
                                    range=["#003300", "#CCFFCC", "#FF7F00", "#87CEFA", "#FFFACD", "#FF66CC"],
                                ),
                            ),
                            tooltip=["ประเภท:N", "ยอดรวม:Q"],
                        )
                        .properties(height=350)
                    )
                    st.altair_chart(pie_inc, use_container_width=True)

            with col_ex:
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
