#!/usr/bin/env python3
"""
Telegram bot for checking bank receipts via SafeCheck API.

Features:
- /start - help
- Send PDF file - check receipt via SafeCheck API (allowed users only)
- /allow <user_id> - OWNER only, add allowed user
- /revoke <user_id> - OWNER only, remove allowed user
- /list_allowed - OWNER only, list allowed user IDs

Security: BOT token and SafeCheck API credentials must be provided via environment variables.
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


async def safecheck_upload_pdf(pdf_bytes: bytes, filename: str) -> dict:
    """
    Upload PDF file to SafeCheck API for bank receipt verification.
    
    POST https://ru.safecheck.online/api/check
    Returns file_id for polling.
    """
    api_key = os.environ.get("SAFECHECK_API_KEY")
    user_id = os.environ.get("SAFECHECK_USER_ID")
    
    if not api_key:
        raise RuntimeError("SAFECHECK_API_KEY not set in environment")
    if not user_id:
        raise RuntimeError("SAFECHECK_USER_ID not set in environment")
    
    endpoint = os.environ.get("SAFECHECK_ENDPOINT", "https://ru.safecheck.online/api")
    url = f"{endpoint}/check"
    
    headers = {
        'SC-API-KEY': api_key,
        'SC-USER-ID': user_id
    }
    
    # Prepare multipart form data
    form = aiohttp.FormData()
    form.add_field('file', pdf_bytes, filename=filename, content_type='application/pdf')
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, headers=headers, data=form, timeout=30) as resp:
                result = await resp.json()
                logger.info(f"SafeCheck upload response: {result}")
                return result
        except Exception as e:
            logger.exception("Failed to upload to SafeCheck API")
            return {"error": 1, "msg": f"Ошибка загрузки: {str(e)}"}


async def safecheck_get_result(file_id: str, max_retries: int = 10, delay: int = 3) -> dict:
    """
    Poll SafeCheck API for check results.
    
    GET https://ru.safecheck.online/api/getCheck?file_id=...
    """
    api_key = os.environ.get("SAFECHECK_API_KEY")
    user_id = os.environ.get("SAFECHECK_USER_ID")
    
    endpoint = os.environ.get("SAFECHECK_ENDPOINT", "https://ru.safecheck.online/api")
    url = f"{endpoint}/getCheck?file_id={file_id}"
    
    headers = {
        'SC-API-KEY': api_key,
        'SC-USER-ID': user_id
    }
    
    async with aiohttp.ClientSession() as session:
        for attempt in range(max_retries):
            try:
                await asyncio.sleep(delay if attempt > 0 else 0)
                
                async with session.get(url, headers=headers, timeout=30) as resp:
                    result = await resp.json()
                    
                    logger.info(f"SafeCheck poll attempt {attempt + 1}: status={result.get('result', {}).get('status')}")
                    
                    # Check for errors
                    if result.get('error', 1) == 1:
                        return result
                    
                    # Check if completed
                    if result.get('result', {}).get('status') == 'completed':
                        return result
                    
            except Exception as e:
                logger.exception(f"Failed to poll SafeCheck API (attempt {attempt + 1})")
                if attempt == max_retries - 1:
                    return {"error": 1, "msg": f"Ошибка получения результата: {str(e)}"}
        
        return {"error": 1, "msg": "Превышено время ожидания результата"}


def format_check_result(result: dict) -> str:
    """Format SafeCheck API response into user-friendly message."""
    
    # Handle errors
    if result.get("error", 1) == 1:
        msg = result.get("msg", "Неизвестная ошибка")
        return f"❌ Ошибка: {msg}"
    
    check_result = result.get("result", {})
    
    # Get main fields
    color = check_result.get("color", "")
    is_original = check_result.get("is_original", False)
    recommendation = check_result.get("recommendation", "")
    verifier = check_result.get("verifier", "")
    struct_passed = check_result.get("struct_passed", False)
    struct_result = check_result.get("struct_result", "")
    device_error = check_result.get("device_error", False)
    check_data = check_result.get("check_data", {})
    
    lines = []
    
    # Status header based on color
    if color == "white":
        lines.append("✅ ЧЕК ПОДЛИННЫЙ")
        lines.append(f"\n🔍 Статус: {color.upper()} (чистый)")
    elif color == "yellow":
        lines.append("⚠️ ЧЕК ПОДОЗРИТЕЛЬНЫЙ")
        lines.append(f"\n🔍 Статус: {color.upper()} (требует внимания)")
    elif color in ["red", "black"]:
        lines.append("🚫 ЧЕК ПОДДЕЛЬНЫЙ!")
        lines.append(f"\n🔍 Статус: {color.upper()} (фальшивый)")
    elif color == "not_supported":
        lines.append("❓ БАНК НЕ ПОДДЕРЖИВАЕТСЯ")
        lines.append(f"\n🔍 Статус: {color}")
    else:
        lines.append(f"ℹ️ Статус: {color}")
    
    # Verification details
    lines.append(f"\n📋 Результаты проверки:\n")
    lines.append(f"{'✅' if is_original else '❌'} Оригинальность: {'Подтверждена' if is_original else 'Не подтверждена'}")
    lines.append(f"{'✅' if struct_passed else '❌'} Структура PDF: {'Корректна' if struct_passed else 'Нарушена'} ({struct_result})")
    
    if device_error:
        lines.append(f"⚠️ Ошибка устройства: Файл сохранен некорректно")
    
    # Detailed violations if check failed
    if color in ["yellow", "red", "black"] and check_result:
        violations = []
        
        if not is_original:
            violations.append("❌ Чек не является оригиналом")
        
        if not struct_passed:
            violations.append(f"❌ Структура PDF нарушена: {struct_result}")
        
        if device_error:
            violations.append("❌ Обнаружена ошибка сохранения файла")
        
        # Check for specific fields that might indicate issues
        if "last_checks" in check_result:
            try:
                last_checks = int(check_result.get("last_checks", 0))
                if last_checks > 0:
                    violations.append(f"⚠️ Чек уже проверялся {last_checks} раз")
            except:
                pass
        
        if violations:
            lines.append(f"\n⚠️ Обнаруженные нарушения:")
            for violation in violations:
                lines.append(f"  • {violation}")
    
    lines.append(f"\n💡 Рекомендация: {recommendation}")
    lines.append(f"🏦 Верификатор: {verifier}")
    
    # Check data if present
    if check_data:
        lines.append(f"\n💳 Данные чека:")
        
        if "sender_fio" in check_data:
            lines.append(f"  Отправитель: {check_data['sender_fio']}")
        if "sender_bank" in check_data:
            lines.append(f"  Банк отправителя: {check_data['sender_bank']}")
        if "sender_req" in check_data:
            lines.append(f"  Счет отправителя: {check_data['sender_req']}")
        
        if "recipient_fio" in check_data:
            lines.append(f"  Получатель: {check_data['recipient_fio']}")
        if "recipient_bank" in check_data:
            lines.append(f"  Банк получателя: {check_data['recipient_bank']}")
        if "recipient_req" in check_data:
            lines.append(f"  Счет получателя: {check_data['recipient_req']}")
        
        if "sum" in check_data:
            lines.append(f"  Сумма: {check_data['sum']}")
        if "status" in check_data:
            lines.append(f"  Статус: {check_data['status']}")
        if "date" in check_data:
            try:
                dt = datetime.fromtimestamp(int(check_data['date']))
                lines.append(f"  Дата: {dt.strftime('%d.%m.%Y %H:%M:%S')}")
            except:
                lines.append(f"  Дата: {check_data['date']}")
    
    # Final recommendation based on color
    if color in ["red", "black"]:
        lines.append("\n⚠️ РЕКОМЕНДАЦИЯ: НЕ ПРИНИМАЙТЕ ЭТОТ ЧЕК!")
        lines.append("┗━ Обнаружены признаки подделки")
    elif color == "yellow":
        lines.append("\n⚠️ ВНИМАНИЕ: Проведите дополнительную проверку")
    elif color == "white":
        lines.append("\n✅ Чек прошел все проверки")
    
    return "\n".join(lines)


def is_owner(user_id: int) -> bool:
    owner = os.environ.get("OWNER_ID")
    try:
        return int(owner) == int(user_id)
    except Exception:
        return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Бот для проверки банковских чеков через SafeCheck API\n\n"
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
        
        # Step 1: Upload to SafeCheck API
        upload_result = await safecheck_upload_pdf(bytes(pdf_bytes), document.file_name or "check.pdf")
        
        if upload_result.get('error', 1) == 1:
            error_msg = upload_result.get('msg', 'Неизвестная ошибка')
            await msg.edit_text(f"❌ Ошибка загрузки: {error_msg}")
            return
        
        file_id = upload_result.get('result', {}).get('file_id')
        if not file_id:
            await msg.edit_text("❌ Не получен file_id от API")
            return
        
        await msg.edit_text(f"⏳ Чек загружен (ID: {file_id[:8]}...). Ожидание результата...")
        
        # Step 2: Poll for results
        check_result = await safecheck_get_result(file_id)
        
        # Format and send response
        formatted_result = format_check_result(check_result)
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
