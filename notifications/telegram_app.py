import asyncio
import logging
import telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from config import TELEGRAM_BOT_TOKEN, ALLOWED_USER_IDS, get_dashboard_url
from storage.db import DB_PATH, get_setting, set_setting
from shared_state import get_latest_latency_ms
import sqlite3

logger = logging.getLogger(__name__)


def _build_menu() -> InlineKeyboardMarkup:
    """Builds the main menu, reading the current dashboard URL lazily."""
    rows = [
        [InlineKeyboardButton("📊 Statistics", callback_data="stats")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
        [InlineKeyboardButton("📈 Status", callback_data="status")],
    ]
    url = get_dashboard_url()
    if url:
        rows.append([InlineKeyboardButton("🧭 Open Dashboard", url=url)])
    return InlineKeyboardMarkup(rows)


def _is_allowed(user_id: int) -> bool:
    """Allowlist check. Empty allowlist = open to everyone (dev mode)."""
    return not ALLOWED_USER_IDS or user_id in ALLOWED_USER_IDS


async def _safe_edit(query, text, reply_markup=None):
    """Edits the message, but ignores 'Message is not modified' errors."""
    try:
        await query.edit_message_text(text, reply_markup=reply_markup)
    except telegram.error.BadRequest as e:
        # Text hasn't changed — not a user error, just skip it
        if "not modified" in str(e).lower():
            await query.answer("No changes")
        else:
            raise


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await update.message.reply_text("🎯 Arbitrage Analytics", reply_markup=_build_menu())


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if not _is_allowed(update.effective_user.id):
        return

    if query.data == "stats":
        await show_stats(query)
    elif query.data == "settings":
        await show_settings(query)
    elif query.data == "status":
        await show_status(query)


async def update_field_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    try:
        key = context.args[0].lower()
        value = context.args[1]
        set_setting(key, value)
        await update.message.reply_text(f"✅ Field {key} updated successfully.")
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /update_field <key> <value>")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_allowed(update.effective_user.id):
        return
    await show_status(update)


async def show_status(query):
    try:
        latency = get_latest_latency_ms()
        msg = "Your account settings:\n"
        msg += f"💰 Min price: ${get_setting('min_price')}\n"
        msg += f"💰 Max price: ${get_setting('max_price')}\n"
        msg += f"💼 Min profit: {get_setting('min_profit_percent')}%\n"
        msg += f"🤑 Min profit (EUR): {get_setting('min_abs_profit')}\n"
        msg += f"📊 Min popularity: {get_setting('min_liquidity')}\n"
        msg += f"📊 Max popularity: {get_setting('max_liquidity')}\n"
        msg += f"\n⚡ Latest latency: {latency:.0f} ms"
        await _safe_edit(query, msg, _build_menu())
    except Exception as e:
        logger.error(f"Error showing status: {e}")
        await _safe_edit(query, "❌ Error", _build_menu())


async def show_stats(query):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM arbitrage_signals")
            signals = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM market_prices")
            prices = cursor.fetchone()[0]
            # Average and total profit in EUR (for better visibility)
            cursor.execute("SELECT AVG(profit_percent), SUM(profit_eur) FROM arbitrage_signals")
            row = cursor.fetchone()
            avg_profit = row[0] or 0
            total_profit = row[1] or 0

        latency = get_latest_latency_ms()
        await _safe_edit(
            query,
            f"📊 Statistics:\n"
            f"Signals: {signals}\n"
            f"Market Prices: {prices}\n"
            f"Avg profit: {avg_profit:.2f}%\n"
            f"Total profit: €{total_profit:.2f}\n"
            f"⚡ Latency: {latency:.0f} ms",
            _build_menu()
        )
    except Exception as e:
        logger.error(f"Error showing stats: {e}")
        await _safe_edit(query,
                         "❌ Error while loading statistics.\n"
                         "Make sure the bot is running correctly.",
                         _build_menu())


async def show_settings(query):
    await _safe_edit(
        query,
        "Send: /update_field <key> <value>\n\n"
        "📋 Available fields:\n\n"
        "/update_field min_price <number>\n"
        "» Example: /update_field min_price 5\n"
        "» Output: ✅ Field min_price updated successfully.\n\n"
        "/update_field max_price <number>\n"
        "» Example: /update_field max_price 140\n"
        "» Output: ✅ Field max_price updated successfully.\n\n"
        "/update_field min_profit_percent <number>\n"
        "» Example: /update_field min_profit_percent 15\n"
        "» Output: ✅ Field min_profit_percent updated successfully.\n\n"
        "/update_field min_liquidity <number>\n"
        "» Example: /update_field min_liquidity 10\n"
        "» Output: ✅ Field min_liquidity updated successfully.\n\n"
        "/update_field max_liquidity <number>\n"
        "» Example: /update_field max_liquidity 500\n"
        "» Output: ✅ Field max_liquidity updated successfully.",
        _build_menu()
    )


def run_telegram_app():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("update_field", update_field_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.run_polling()