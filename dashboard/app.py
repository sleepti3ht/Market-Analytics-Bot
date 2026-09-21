import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
from storage.db import DB_PATH

st.set_page_config(page_title="Arbitrage Analytics", layout="wide")

# --- Dark theme with purple accents ---
st.markdown("""
<style>
.stApp { background-color: #0f0f1a; color: #e0e0ff; }
h1, h2, h3 { color: #c084fc !important; }
div[data-testid="stMetric"] { background-color: #1a1a2e; border-left: 4px solid #7c3aed; border-radius: 10px; padding: 10px; }
[data-testid="stSidebar"] { background-color: #14142a; }
div[data-testid="stDataFrame"] { border: 1px solid #6b21a8; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("🎯 Arbitrage Analytics Dashboard")

# Manual cache reset button (in case data didn't refresh)
if st.sidebar.button("🔄 Clear data cache"):
    st.cache_data.clear()
    st.rerun()

# Cache TTL: 30 seconds. Data is re-read from the DB on cache expiration.
@st.cache_data(ttl=30)
def load_data():
    with sqlite3.connect(DB_PATH) as conn:
        signals = pd.read_sql_query("SELECT * FROM arbitrage_signals", conn)
        prices = pd.read_sql_query("SELECT * FROM market_prices", conn)
    return signals, prices

signals, prices = load_data()

# Enforce data types for accurate calculations and plotting
if len(signals) > 0:
    signals["notified_at_utc"] = pd.to_datetime(signals["notified_at_utc"])
    signals["profit_percent"] = pd.to_numeric(signals["profit_percent"])
    signals["profit_eur"] = pd.to_numeric(signals["profit_eur"])

st.write(f"Signals in DB: {len(signals)}")
st.write(f"Market prices: {len(prices)}")

if len(signals) == 0:
    st.warning("No signals yet. Wait until the bot finds a profitable deal.")
    st.stop()

# --- Filters ---
st.sidebar.header("Filters")

# Default date range: last 7 days (ensures recent historical data remains visible)
max_date = signals["notified_at_utc"].max().date()
min_date_db = signals["notified_at_utc"].min().date()
default_start = max(min_date_db, max_date - timedelta(days=7))

min_profit = st.sidebar.slider("Min profit, %", 0, 200, 0)
date_from = st.sidebar.date_input("From date", value=default_start, min_value=min_date_db, max_value=max_date)
date_to = st.sidebar.date_input("To date", value=max_date, min_value=min_date_db, max_value=max_date)

filtered = signals[
    (signals["profit_percent"] >= min_profit) &
    (signals["notified_at_utc"].dt.date >= date_from) &
    (signals["notified_at_utc"].dt.date <= date_to)
]

# --- Metrics ---
col1, col2, col3, col4 = st.columns(4)
col1.metric("Signals", len(filtered))
col2.metric("Avg profit", f"{filtered['profit_percent'].mean():.2f}%" if len(filtered) > 0 else "0%")

total_invested = filtered['lis_price'].sum()
total_profit = filtered['profit_eur'].sum()
roi = (total_profit / total_invested * 100) if total_invested > 0 else 0
col3.metric("ROI", f"{roi:.2f}%")
col4.metric("Profit (€)", f"€{total_profit:.2f}")

# --- Time-series profit chart ---
st.subheader("📈 Profit over time")
if len(filtered) > 0:
    fig = px.scatter(
        filtered,
        x="notified_at_utc",
        y="profit_percent",
        hover_data=["item_name", "lis_price", "market_price"],
        title="Profit dynamics",
        color_discrete_sequence=['#8b5cf6', '#c084fc']
    )
    fig.update_layout(
        plot_bgcolor='#0f0f1a',
        paper_bgcolor='#0f0f1a',
        font_color='#e0e0ff',
        title_font_color='#c084fc'
    )
    fig.update_xaxes(gridcolor='#2a2a44', zerolinecolor='#2a2a44')
    fig.update_yaxes(gridcolor='#2a2a44', zerolinecolor='#2a2a44')
    st.plotly_chart(fig, use_container_width=True) # Updated from deprecated 'width="stretch"'
else:
    st.info("No data for the selected period")

# --- TOP-10 profits ---
st.subheader("🏆 TOP-10 profits")
if len(filtered) > 0:
    top10 = filtered.nlargest(10, "profit_percent")
    st.table(top10[["item_name", "lis_price", "market_price", "profit_eur", "profit_percent"]].assign(
        lis_price=lambda d: d["lis_price"].map(lambda x: f"€{x:.2f}"),
        market_price=lambda d: d["market_price"].map(lambda x: f"€{x:.2f}"),
        profit_eur=lambda d: d["profit_eur"].map(lambda x: f"€{x:.2f}"),
        profit_percent=lambda d: d["profit_percent"].map(lambda x: f"{x:.1f}%"),
    ))
else:
    st.info("No data")

# --- Profit distribution ---
st.subheader("📊 Profit distribution")
if len(filtered) > 0:
    fig2 = px.histogram(
        filtered,
        x="profit_percent",
        nbins=30,
        title="Profit distribution",
        color_discrete_sequence=['#8b5cf6']
    )
    fig2.update_layout(
        plot_bgcolor='#0f0f1a',
        paper_bgcolor='#0f0f1a',
        font_color='#e0e0ff',
        title_font_color='#c084fc'
    )
    fig2.update_xaxes(gridcolor='#2a2a44', zerolinecolor='#2a2a44')
    fig2.update_yaxes(gridcolor='#2a2a44', zerolinecolor='#2a2a44')
    st.plotly_chart(fig2, use_container_width=True) # Updated from deprecated 'width="stretch"'
else:
    st.info("No data")

# --- Export ---
st.subheader("📤 Export data")
csv = signals.to_csv(index=False).encode("utf-8")
st.download_button(
    label="⬇️ Download CSV",
    data=csv,
    file_name="arbitrage_signals.csv",
    mime="text/csv",
)