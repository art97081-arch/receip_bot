#!/usr/bin/env python3
"""
Telegram bot for checking bank receipts via Datagrab API.

Features:
- /start - help
- Send PDF file - check receipt via Datagrab API (allowed users only)
- /allow <user_id> - OWNER only, add allowed user
- /revoke <user_id> - OWNER only, remove allowed user
- /list_allowed - OWNER only, list allowed user IDs

Security: BOT token and Datagrab API key must be provided via environment variables.
Do NOT commit secrets to the repo.
"""
import asyncio
import json
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import List

import aiohttp
import httpx
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
ALLOWED_FILE = BASE_DIR / "allowed.json"


def load_allowed() -> List[int]:
    if not ALLOWED_FILE.exists():
        return []
    try:
        with open(ALLOWED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [int(x) for x in data]
    except Exception:
        return []


def save_allowed(ids: List[int]):
    with open(ALLOWED_FILE, "w", encoding="utf-8") as f:
        json.dump([int(x) for x in ids], f, ensure_ascii=False, indent=2)


async def datagrab_check_pdf(pdf_bytes: bytes, filename: str) -> dict:
    """
    Upload and check PDF file via Datagrab/pdfchecker API.

    POST {endpoint}/upload.php?key={api_key}
    Returns immediate result (JSON) or HTML on error.
    """
    api_key = os.environ.get("DATAGRAB_API_KEY")
    if not api_key:
        raise RuntimeError("DATAGRAB_API_KEY not set in environment")

    endpoint = os.environ.get("DATAGRAB_ENDPOINT", "https://api.datagrab.ru")
    url = f"{endpoint}/upload.php?key={api_key}"

    # Quick robust alternative: use httpx.AsyncClient for multipart upload
    max_retries = 3
    verify_tls = os.environ.get("DATAGRAB_VERIFY_TLS", "1") != "0"

    for attempt in range(1, max_retries + 1):
        try:
            async with httpx.AsyncClient(verify=verify_tls, timeout=60.0) as client:
                files = {"file": (filename, pdf_bytes, "application/pdf")}
                resp = await client.post(url, files=files)
                status = resp.status_code
                text = resp.text
                logger.info(f"Datagrab response status: {status}, content-type: {resp.headers.get('content-type')}")
                logger.debug(f"Datagrab response text (preview 2000 chars): {text[:2000]}")

                if status == 200:
                    try:
                        return resp.json()
                    except Exception:
                        try:
                            return json.loads(text)
                        except Exception:
                            return {"error": 1, "msg": "Invalid JSON from Datagrab", "text": text}

                logger.warning(f"Datagrab returned status={status} (attempt {attempt}/{max_retries})")
                logger.debug("Datagrab full response body:")
                logger.debug(text)

                if status in (502, 503, 504, 429) and attempt < max_retries:
                    backoff = 2 ** attempt
                    logger.info(f"Retrying Datagrab request after {backoff}s (status {status})")
                    await asyncio.sleep(backoff)
                    continue

                return {"error": 1, "status": status, "msg": "Datagrab returned error", "text": text}

        except httpx.HTTPError as e:
            logger.exception(f"HTTPError when calling Datagrab (attempt {attempt})")
            if attempt < max_retries:
                backoff = 2 ** attempt
                logger.info(f"Retrying Datagrab request after exception in {backoff}s")
                await asyncio.sleep(backoff)
                continue
            return {"error": 1, "msg": f"Ошибка запроса: {str(e)}"}
        except Exception as e:
            logger.exception(f"Unexpected error when calling Datagrab (attempt {attempt})")
            if attempt < max_retries:
                backoff = 2 ** attempt
                logger.info(f"Retrying Datagrab request after exception in {backoff}s")
                await asyncio.sleep(backoff)
                continue
            return {"error": 1, "msg": f"Ошибка: {str(e)}"}



def format_check_result(result: dict) -> str:
    """Format datagrab/safecheck API response into a user-friendly Russian message.

    This is a cleaned and consolidated version taken from the backup implementation.
    """
    # Common simple error cases
    if result.get("result") == "forbidden":
        return "❌ Ошибка: неверный API ключ"
    if result.get("result") == "unpaid":
        return "❌ Истек оплаченный период API"
    if result.get("result") == "error":
        return f"❌ Ошибка при проверке: {result.get('message', 'Неизвестная ошибка')}"

    result_type = result.get("result", "")
    message = result.get("message", "")
    message2 = result.get("message2", "")
    is_fake = result.get("is_fake", False)
    is_mod = result.get("is_mod", False)
    compliance_status = result.get("compliance_status", True)
    is_unrec = result.get("is_unrec", False)

    # Unrecognized check
    if result_type == "unrec":
        lines = ["❓ ЧЕК НЕ РАСПОЗНАН", "", "🔍 Причины:"]
        violations = []
        if is_unrec:
            violations.append("❌ is_unrec = true — Система не смогла распознать чек")
        if not compliance_status:
            violations.append("❌ compliance_status = false — Некорректная структура PDF")
        if violations:
            lines.extend(violations)
        if message:
            lines.append("")
            lines.append(f"💬 {message}")
        if message2:
            lines.append(f"ℹ️ {message2}")
        lines.append("")
        lines.append("⚠️ Возможные причины:")
        lines.append("• Неподдерживаемый формат чека")
        lines.append("• Чек от неизвестного банка")
        lines.append("• Повреждение файла")
        return "\n".join(lines)

    # Fake check
    if result_type == "fake":
        lines = ["🚫 ЧЕК ПОДДЕЛЬНЫЙ!", "", "🔴 Обнаружены следующие нарушения:"]
        violations = []
        if is_fake:
            violations.append("❌ is_fake = true — Чек не прошел проверку подлинности")
        if not compliance_status:
            violations.append("❌ compliance_status = false — Нарушена структура PDF файла")
            violations.append("   └─ Файл не соответствует оригинальному формату банка")
        if is_mod:
            violations.append("❌ is_mod = true — Обнаружены следы модификации документа")
        if violations:
            lines.extend(violations)
        if message:
            lines.append("")
            lines.append("💬 Сообщение от сервера:")
            lines.append(f"   {message}")
        if message2:
            lines.append("")
            lines.append("ℹ️ Дополнительно:")
            lines.append(f"   {message2}")
        lines.append("")
        lines.append("⚠️ РЕКОМЕНДАЦИЯ: НЕ ПРИНИМАЙТЕ ЭТОТ ЧЕК!")
        lines.append("┗━ Чек был изменен или создан искусственно")
        return "\n".join(lines)

    # Modified check
    if result_type == "mod":
        lines = ["⚠️ ЧЕК МОДИФИЦИРОВАН", "", "🔍 Обнаружено:"]
        violations = []
        if is_mod:
            violations.append("❌ is_mod = true — Чек был пересохранен")
            violations.append("   └─ Использован виртуальный принтер или редактор PDF")
        if not compliance_status:
            violations.append("❌ compliance_status = false — Структура PDF изменена")
        if violations:
            lines.extend(violations)
        lines.append("")
        lines.append("⚠️ Это означает:")
        lines.append("• Файл не является оригиналом из банка")
        lines.append("• Проверка подлинности невозможна")
        lines.append("• Чек мог быть отредактирован")
        if message:
            lines.append("")
            lines.append(f"💬 {message}")
        return "\n".join(lines)

    if result_type == "size":
        return "❌ Размер PDF файла не соответствует оригинальному"

    # Default / success-like formatting
    profile = result.get("profile", "")
    last_checks = result.get("last_checks", 0)

    lines = []
    if message:
        lines.append(message)
    lines.append("")
    lines.append("📋 Результат проверки:")
    lines.append(f"Банк: {result_type}")
    if profile:
        lines.append(f"Профиль: {profile}")

    if is_fake:
        lines.append("⚠️ Чек признан поддельным")
    if is_mod:
        lines.append("⚠️ Чек был пересохранен")
    if is_unrec:
        lines.append("⚠️ Чек не распознан")
    if not compliance_status:
        lines.append("⚠️ Ошибки в структуре PDF")

    try:
        last_checks_int = int(last_checks) if last_checks else 0
        if last_checks_int > 0:
            lines.append(f"🔄 Ранее проверялся: {last_checks_int} раз(а)")
    except Exception:
        pass

    check_data = result.get("check_data", {})
    if check_data:
        lines.append("")
        lines.append("💳 Данные чека:")
        if "sender_name" in check_data:
            lines.append(f"Отправитель: {check_data['sender_name']}")
        if "sender_acc" in check_data:
            lines.append(f"Счет отправителя: ****{check_data['sender_acc']}")
        if "remitte_name" in check_data:
            lines.append(f"Получатель: {check_data['remitte_name']}")
        if "remitte_acc" in check_data:
            lines.append(f"Счет получателя: ****{check_data['remitte_acc']}")
        if "remitte_tel" in check_data:
            lines.append(f"Телефон получателя: {check_data['remitte_tel']}")
        if "sum" in check_data:
            lines.append(f"Сумма: {check_data['sum']} ₽")
        if "status" in check_data:
            lines.append(f"Статус: {check_data['status']}")
        if "payment_time" in check_data:
            try:
                dt = datetime.fromtimestamp(int(check_data['payment_time']))
                lines.append(f"Время: {dt.strftime('%d.%m.%Y %H:%M:%S')}")
            except Exception:
                lines.append(f"Время: {check_data['payment_time']}")
        if "doc_id" in check_data:
            lines.append(f"ID документа: {check_data['doc_id']}")

    return "\n".join(lines)


def is_owner(user_id: int) -> bool:
    owner_env = os.environ.get("OWNER_ID", "")
    if not owner_env:
        return False

    # Support multiple IDs separated by comma, semicolon or whitespace
    for token in re.split(r"[;,\s]+", owner_env.strip()):
        try:
            if int(token) == int(user_id):
                return True
        except Exception:
            continue
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Бот для проверки банковских чеков через Datagrab API\n\n"
        "📎 Отправьте PDF файл чека для проверки\n\n"
        "Команды владельца:\n"
        "/allow <user_id> - добавить пользователя\n"
        "/revoke <user_id> - удалить пользователя\n"
        "/list_allowed - список разрешенных пользователей\n"
    )
    await update.message.reply_text(text)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle PDF file uploads for check verification."""
    user_id = update.effective_user.id
    allowed = load_allowed()
    
    if user_id not in allowed and not is_owner(user_id):
        await update.message.reply_text(
            "❌ У вас нет доступа к проверке чеков.\n"
            "Попросите владельца бота добавить вас командой /allow"
        )
        return
    
    document = update.message.document
    
    # Check if it's a PDF
    if not document.mime_type or document.mime_type != "application/pdf":
        await update.message.reply_text("❌ Пожалуйста, отправьте PDF файл чека")
        return
    
    # Check file size (optional, prevent huge files)
    if document.file_size > 10 * 1024 * 1024:  # 10 MB limit
        await update.message.reply_text("❌ Файл слишком большой (макс. 10 МБ)")
        return
    
    msg = await update.message.reply_text("⏳ Загружаю и проверяю чек, подождите...")
    
    try:
        # Download the file
        file = await context.bot.get_file(document.file_id)
        pdf_bytes = await file.download_as_bytearray()
        
        # Send to Datagrab/pdfchecker API (synchronous response)
        result = await datagrab_check_pdf(bytes(pdf_bytes), document.file_name or "check.pdf")

        # Format and send response
        formatted_result = format_check_result(result)
        await msg.edit_text(formatted_result)
        
    except Exception as e:
        logger.exception("Failed to process PDF check")
        await msg.edit_text(f"❌ Ошибка при обработке: {str(e)}")


async def allow_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Только владелец может добавлять пользователей")
        return
    if not context.args:
        await update.message.reply_text(
            "Использование: /allow <user_id>\n\n"
            "Чтобы узнать user_id, пользователь может написать боту @userinfobot"
        )
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом")
        return
    allowed = load_allowed()
    if uid in allowed:
        await update.message.reply_text(f"ℹ️ Пользователь {uid} уже имеет доступ")
        return
    allowed.append(uid)
    save_allowed(allowed)
    await update.message.reply_text(f"✅ Пользователь {uid} добавлен в список разрешенных")


async def revoke_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Только владелец может удалять пользователей")
        return
    if not context.args:
        await update.message.reply_text("Использование: /revoke <user_id>")
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ user_id должен быть числом")
        return
    allowed = load_allowed()
    if uid not in allowed:
        await update.message.reply_text(f"ℹ️ Пользователь {uid} не в списке разрешенных")
        return
    allowed = [x for x in allowed if x != uid]
    save_allowed(allowed)
    await update.message.reply_text(f"✅ Пользователь {uid} удален из списка разрешенных")


async def list_allowed_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Только владелец может просматривать список")
        return
    allowed = load_allowed()
    if not allowed:
        await update.message.reply_text("ℹ️ Список разрешенных пользователей пуст")
        return
    users_list = "\n".join(f"• {uid}" for uid in allowed)
    await update.message.reply_text(f"📋 Разрешенные пользователи:\n\n{users_list}")


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN not set in environment. Do NOT commit the token to source control.")

    app = ApplicationBuilder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("allow", allow_command))
    app.add_handler(CommandHandler("revoke", revoke_command))
    app.add_handler(CommandHandler("list_allowed", list_allowed_command))
    
    # Handle PDF documents
    app.add_handler(MessageHandler(filters.Document.PDF, handle_document))

    logger.info("Starting bot...")
    app.run_polling()


if __name__ == "__main__":
    main()
