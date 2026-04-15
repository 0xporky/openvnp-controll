import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from vpn.commands import vpn_cleanup, vpn_down, vpn_status, vpn_up
from vpn.config import TELEGRAM_BOT_TOKEN, TELEGRAM_USER_ID

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def authorized(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != TELEGRAM_USER_ID:
            return
        return await func(update, context)
    return wrapper


@authorized
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "OpenVPN Controller\n\n"
        "/up — Start VPN\n"
        "/down — Stop VPN\n"
        "/status — Check status\n"
        "/cleanup — Delete everything"
    )


@authorized
async def cmd_up(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Starting VPN...")

    async def on_progress(text: str):
        try:
            await msg.edit_text(text)
        except Exception:
            pass

    try:
        result = await vpn_up(on_progress=on_progress)
    except Exception as e:
        await msg.edit_text(f"Error: {e}")
        return

    if result.status == "ready":
        await msg.edit_text(
            f"VPN is ready!\n\n"
            f"IP: `{result.ip}`\n"
            f"DNS: `{result.dns}`\n\n"
            f"DNS will auto-update shortly. You can connect now.",
            parse_mode="Markdown",
        )
    elif result.status == "already_running":
        await msg.edit_text(
            f"VPN is already running.\n\n"
            f"IP: `{result.ip}`\n"
            f"DNS: `{result.dns}`",
            parse_mode="Markdown",
        )
    else:
        await msg.edit_text(f"Error: {result.message}")


@authorized
async def cmd_down(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        result = await vpn_status()
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return

    if not result.running:
        await update.message.reply_text("No running VPN droplet found.")
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes, destroy", callback_data="down_yes"),
            InlineKeyboardButton("Cancel", callback_data="down_no"),
        ]
    ])
    await update.message.reply_text(
        f"Destroy VPN droplet?\n\nIP: `{result.ip}`\nRegion: {result.region}",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def callback_down(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != TELEGRAM_USER_ID:
        return
    await query.answer()

    if query.data == "down_yes":
        await query.edit_message_text("Destroying droplet...")
        try:
            result = await vpn_down()
            await query.edit_message_text(result.message)
        except Exception as e:
            await query.edit_message_text(f"Error: {e}")
    else:
        await query.edit_message_text("Cancelled.")


@authorized
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("Checking status...")

    try:
        result = await vpn_status()
    except Exception as e:
        await msg.edit_text(f"Error: {e}")
        return

    lines = []
    if result.running:
        lines.append("Status: RUNNING")
        lines.append(f"IP: `{result.ip}`")
        lines.append(f"DNS: `{result.dns}`")
        lines.append(f"Region: {result.region}")

        if result.dns_status == "ok":
            lines.append(f"DNS: OK ({result.dns_resolved_ip})")
        elif result.dns_status == "stale":
            lines.append(f"DNS: STALE (resolves to {result.dns_resolved_ip}, droplet is {result.ip})")
        else:
            lines.append("DNS: NOT RESOLVING")
    else:
        lines.append("Status: STOPPED (no droplet running)")

    if result.snapshots:
        lines.append("\nSnapshots:")
        for s in result.snapshots:
            lines.append(f"  {s.name} ({s.size_gb}GB, {s.created_at[:10]})")
    else:
        lines.append("\nNo snapshots found.")

    await msg.edit_text("\n".join(lines), parse_mode="Markdown")


@authorized
async def cmd_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Yes, delete everything", callback_data="cleanup_yes"),
            InlineKeyboardButton("Cancel", callback_data="cleanup_no"),
        ]
    ])
    await update.message.reply_text(
        "Delete ALL droplets and snapshots? This stops all costs but requires running setup again.",
        reply_markup=keyboard,
    )


async def callback_cleanup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != TELEGRAM_USER_ID:
        return
    await query.answer()

    if query.data == "cleanup_yes":
        await query.edit_message_text("Cleaning up...")
        try:
            result = await vpn_cleanup()
            await query.edit_message_text(result.message)
        except Exception as e:
            await query.edit_message_text(f"Error: {e}")
    else:
        await query.edit_message_text("Cancelled.")


def run_bot():
    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is not set in .env")
        return
    if not TELEGRAM_USER_ID:
        print("ERROR: TELEGRAM_USER_ID is not set in .env")
        return

    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("up", cmd_up))
    app.add_handler(CommandHandler("down", cmd_down))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cleanup", cmd_cleanup))
    app.add_handler(CallbackQueryHandler(callback_down, pattern="^down_"))
    app.add_handler(CallbackQueryHandler(callback_cleanup, pattern="^cleanup_"))

    logger.info("Bot started. Press Ctrl+C to stop.")
    app.run_polling()
