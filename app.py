"""
E2E Dispatch Dashboard

Streamlit dashboard that summarises dispatch lag (creation_date -> dispatch_date)
by Location and Brand (Seller). Lag is bucketed into D0, D1, D2, D3+ and shown
as a percentage share of each (Location, Brand) group.

Filters:
    - Seller (Brand Name): when a single seller is chosen, the table collapses
      to a per-location view for that seller only.
    - Creation Date range: calendar based date range filter.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

import pandas as pd
import streamlit as st


DATA_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "New Microsoft Excel Worksheet.csv",
)

BUCKET_ORDER = ["D0", "D1", "D2", "D3+"]


# ---------------------------------------------------------------------------
# Data loading & preparation
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Loading data...")
def load_data(path: str) -> pd.DataFrame:
    """Load the raw CSV and compute the dispatch lag bucket per order.

    The CSV is expected to have columns:
        Location, Brand Name, Order id, Creation Date, dispatch_date

    Dates are in DD-MM-YYYY HH:MM format. Rows with no dispatch_date are kept
    so they can be optionally excluded from the bucket calculation.
    """
    df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])

    df.columns = [c.strip() for c in df.columns]

    df["Creation Date"] = pd.to_datetime(
        df["Creation Date"], format="%d-%m-%Y %H:%M", errors="coerce"
    )
    df["dispatch_date"] = pd.to_datetime(
        df["dispatch_date"], format="%d-%m-%Y %H:%M", errors="coerce"
    )

    creation_day = df["Creation Date"].dt.normalize()
    dispatch_day = df["dispatch_date"].dt.normalize()
    lag_days = (dispatch_day - creation_day).dt.days

    def _bucket(d: float) -> Optional[str]:
        if pd.isna(d):
            return None
        d = int(d)
        if d <= 0:
            return "D0"
        if d == 1:
            return "D1"
        if d == 2:
            return "D2"
        return "D3+"

    df["lag_days"] = lag_days
    df["bucket"] = lag_days.map(_bucket)

    df["Location"] = df["Location"].fillna("(blank)").replace("", "(blank)")
    df["Brand Name"] = df["Brand Name"].fillna("(blank)").replace("", "(blank)")

    return df


def build_summary(df: pd.DataFrame, group_cols: list[str]) -> pd.DataFrame:
    """Return a percentage-share table of buckets for the given grouping."""
    if df.empty:
        return pd.DataFrame(columns=group_cols + BUCKET_ORDER + ["Orders"])

    counts = (
        df.dropna(subset=["bucket"])
        .groupby(group_cols + ["bucket"], dropna=False)
        .size()
        .unstack("bucket", fill_value=0)
    )

    for b in BUCKET_ORDER:
        if b not in counts.columns:
            counts[b] = 0
    counts = counts[BUCKET_ORDER]

    totals = counts.sum(axis=1)
    pct = counts.div(totals.replace(0, pd.NA), axis=0) * 100.0

    pct["Orders"] = totals
    pct = pct.reset_index()
    return pct


def style_summary(pct: pd.DataFrame, group_cols: list[str]) -> "pd.io.formats.style.Styler":
    """Apply a percentage / integer formatting to the summary table."""
    fmt: dict[str, str] = {b: "{:.0f}%" for b in BUCKET_ORDER}
    fmt["Orders"] = "{:,.0f}"
    styler = pct.style.format(fmt, na_rep="-")
    return styler


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="E2E Dispatch Dashboard",
    page_icon=None,
    layout="wide",
)

st.title("E2E Dispatch Dashboard")
st.caption(
    "Dispatch lag distribution (D0 = same day, D1 = next day, D2 = +2 days, "
    "D3+ = 3 or more days) by Location and Seller."
)

if not os.path.exists(DATA_FILE):
    st.error(f"Data file not found: {DATA_FILE}")
    st.stop()

df = load_data(DATA_FILE)

# ---- Filters (main page) ---------------------------------------------------
valid_dates = df["Creation Date"].dropna()
if valid_dates.empty:
    st.warning("No valid Creation Dates found in data.")
    st.stop()

min_date: date = valid_dates.min().date()
max_date: date = valid_dates.max().date()
sellers = sorted(df["Brand Name"].dropna().unique().tolist())

with st.container(border=True):
    st.markdown("**Filters**")
    f1, f2, f3 = st.columns([1.2, 1.5, 1])

    with f1:
        date_range = st.date_input(
            "Creation date range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
            format="DD-MM-YYYY",
            help="Filters orders by their creation date.",
        )

    with f2:
        seller_selection = st.multiselect(
            "Seller (Brand Name)",
            options=sellers,
            default=[],
            help="Leave empty to see all sellers. Pick exactly one to see a "
            "location-wise view for that seller.",
        )

    with f3:
        exclude_undispatched = st.checkbox(
            "Exclude orders without a dispatch date",
            value=True,
            help="Uncheck to count undispatched orders (their bucket is "
            "unknown so they are still excluded from the percentage "
            "calculation).",
        )

if isinstance(date_range, tuple) and len(date_range) == 2:
    start_date, end_date = date_range
else:
    start_date = end_date = date_range  # type: ignore[assignment]

# ---- Apply filters ---------------------------------------------------------
filtered = df.copy()

mask_dates = (
    (filtered["Creation Date"].dt.date >= start_date)
    & (filtered["Creation Date"].dt.date <= end_date)
)
filtered = filtered[mask_dates]

if seller_selection:
    filtered = filtered[filtered["Brand Name"].isin(seller_selection)]

if exclude_undispatched:
    filtered = filtered[filtered["dispatch_date"].notna()]

# ---- KPIs ------------------------------------------------------------------
total_orders = len(filtered)
dispatched = filtered["dispatch_date"].notna().sum()
locations = filtered["Location"].nunique()
brands = filtered["Brand Name"].nunique()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Orders", f"{total_orders:,}")
c2.metric("Dispatched", f"{int(dispatched):,}")
c3.metric("Locations", f"{locations:,}")
c4.metric("Sellers", f"{brands:,}")

st.divider()

# ---- Main table ------------------------------------------------------------
single_seller = len(seller_selection) == 1

if single_seller:
    seller_name = seller_selection[0]
    st.subheader(f"Location-wise dispatch lag — {seller_name}")
    summary = build_summary(filtered, ["Location"])
    summary = summary.sort_values("Orders", ascending=False)
else:
    st.subheader("Location & Seller dispatch lag")
    summary = build_summary(filtered, ["Location", "Brand Name"])
    summary = summary.sort_values(
        ["Location", "Orders"], ascending=[True, False]
    )

if summary.empty:
    st.info("No data available for the selected filters.")
else:
    st.dataframe(
        style_summary(summary, list(summary.columns)),
        use_container_width=True,
        hide_index=True,
    )

    csv_bytes = summary.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download table as CSV",
        data=csv_bytes,
        file_name="dispatch_lag_summary.csv",
        mime="text/csv",
    )
