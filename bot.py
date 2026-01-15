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
    
    POST {endpoint}/check
    Returns immediate response which should contain file_id for polling.
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
    
    # Retry loop for transient errors
    max_retries = 3
    for attempt in range(max_retries):
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, headers=headers, data=form, timeout=30) as resp:
                    result = await resp.json()
                    logger.info(f"SafeCheck upload response (attempt {attempt+1}): {result}")
                    return result
            except Exception as e:
                logger.exception(f"Failed to upload to SafeCheck API (attempt {attempt+1})")
                if attempt == max_retries - 1:
                    return {"error": 1, "msg": f"Ошибка загрузки: {str(e)}"}
                await asyncio.sleep(2)
    
    return {"error": 1, "msg": "Не удалось загрузить файл после нескольких попыток"}


async def safecheck_get_result(file_id: str, max_retries: int = 10, delay: int = 3) -> dict:
    """
    Poll SafeCheck API for check results.
    
    GET {endpoint}/getCheck?file_id=...
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
    """Format Datagrab API response into user-friendly message."""
    
    # Handle errors
    if result.get("result") == "forbidden":
        return "❌ Ошибка: неверный API ключ"
    elif result.get("result") == "unpaid":
        return "❌ Истек оплаченный период API"
    elif result.get("result") == "error":
        return f"❌ Ошибка при проверке: {result.get('message', 'Неизвестная ошибка')}"
    
    # Get main fields
    result_type = result.get("result", "")
    profile = result.get("profile", "")
    is_fake = result.get("is_fake", False)
    is_mod = result.get("is_mod", False)
    is_unrec = result.get("is_unrec", False)
    compliance_status = result.get("compliance_status", True)
    message = result.get("message", "")
    message2 = result.get("message2", "")
    last_checks = result.get("last_checks", 0)
    check_data = result.get("check_data", {})
    
    # Handle special result types
    if result_type == "unrec":
        lines = ["❓ ЧЕК НЕ РАСПОЗНАН"]
        lines.append("\n🔍 Причины:")
        
        violations = []
        if is_unrec:
            violations.append("❌ Система не смогла распознать чек")
        if not compliance_status:
            violations.append("❌ Некорректная структура PDF")
        
        if violations:
            lines.extend(violations)
        
        if message:
            lines.append(f"\n💬 {message}")
        if message2:
            lines.append(f"ℹ️ {message2}")
        
        lines.append("\n⚠️ Возможные причины:")
        lines.append("• Неподдерживаемый формат чека")
        lines.append("• Чек от неизвестного банка")
        lines.append("• Повреждение файла")
        
        return "\n".join(lines)
    
    elif result_type == "fake":
        lines = ["🚫 ЧЕК ПОДДЕЛЬНЫЙ!"]
        lines.append("\n🔴 Обнаружены следующие нарушения:\n")
        
        violations = []
        
        # Detailed authenticity check
        if is_fake:
            violations.append("❌ Чек не прошел проверку подлинности")
            violations.append("   └─ Подпись и метаданные не соответствуют оригиналу банка")
        
        # Detailed PDF structure analysis
        if not compliance_status:
            violations.append("❌ Нарушена структура PDF файла")
            violations.append("   └─ Файл не соответствует оригинальному формату банка")
            violations.append("   📊 Параметры нарушения:")
            violations.append("      • Некорректные метаданные документа")
            violations.append("      • Отсутствие цифровой подписи банка")
            violations.append("      • Изменена структура объектов PDF")
            violations.append("      • Несоответствие шрифтов и кодировки")
        
        # Modification detection
        if is_mod:
            violations.append("❌ Обнаружены следы модификации документа")
            violations.append("   └─ Файл был пересохранен или отредактирован")
            violations.append("   🔍 Признаки изменений:")
            violations.append("      • Использован виртуальный принтер")
            violations.append("      • PDF редактор оставил следы")
            violations.append("      • История изменений не соответствует оригиналу")
        
        if violations:
            lines.extend(violations)
        
        # Server messages with details
        if message:
            lines.append(f"\n💬 Сообщение от сервера:")
            lines.append(f"   {message}")
        
        if message2:
            lines.append(f"\nℹ️ Дополнительная информация:")
            lines.append(f"   {message2}")
        
        # Additional technical details if available
        if check_data:
            lines.append(f"\n🔬 Технические детали:")
            if "pdf_version" in check_data:
                lines.append(f"   • Версия PDF: {check_data['pdf_version']}")
            if "creator" in check_data:
                lines.append(f"   • Создатель: {check_data['creator']}")
            if "producer" in check_data:
                lines.append(f"   • Обработчик: {check_data['producer']}")
        
        lines.append("\n⚠️ РЕКОМЕНДАЦИЯ: НЕ ПРИНИМАЙТЕ ЭТОТ ЧЕК!")
        lines.append("┗━ Чек был изменен или создан искусственно")
        lines.append("┗━ Высокий риск мошенничества")
        
        return "\n".join(lines)
    
    elif result_type == "mod":
        lines = ["⚠️ ЧЕК МОДИФИЦИРОВАН"]
        lines.append("\n🔍 Обнаружено:")
        
        violations = []
        if is_mod:
            violations.append("❌ Чек был пересохранен")
            violations.append("   └─ Использован виртуальный принтер или редактор PDF")
            violations.append("   📝 Детали модификации:")
            violations.append("      • Файл создан не банковским приложением")
            violations.append("      • PDF структура была пересоздана")
            violations.append("      • Отсутствуют оригинальные метаданные")
        
        if not compliance_status:
            violations.append("❌ Структура PDF изменена")
            violations.append("   └─ Нарушены стандарты банковского формата")
        
        if violations:
            lines.extend(violations)
        
        lines.append("\n⚠️ Это означает:")
        lines.append("• Файл не является оригиналом из банка")
        lines.append("• Проверка подлинности невозможна")
        lines.append("• Чек мог быть отредактирован")
        lines.append("• Документ создан через стороннее ПО")
        
        if message:
            lines.append(f"\n💬 {message}")
        
        if message2:
            lines.append(f"ℹ️ {message2}")
        
        lines.append("\n⚠️ РЕКОМЕНДАЦИЯ: Требуется оригинальный чек из банковского приложения")
        
        return "\n".join(lines)
    
    elif result_type == "size":
        return "❌ Размер PDF файла не соответствует оригинальному"
    
    # Format successful check
    lines = []
    
    # Determine if check is genuine
    is_genuine = not is_fake and not is_mod and compliance_status
    
    if is_genuine:
        lines.append("✅ ЧЕК ПОДЛИННЫЙ")
        lines.append("\n🎯 Все проверки пройдены успешно")
    else:
        lines.append("⚠️ ЧЕК ТРЕБУЕТ ВНИМАНИЯ")
    
    if message:
        lines.append(f"\n💬 {message}")
    
    lines.append(f"\n📋 Результат проверки:")
    lines.append(f"🏦 Банк: {result_type.upper()}")
    if profile:
        profile_names = {
            "1": "Основной профиль",
            "2": "Альтернативный формат",
            "sbp": "СБП перевод",
            "vypis": "Выписка",
            "obr": "В обработке"
        }
        profile_name = profile_names.get(profile, profile)
        lines.append(f"📄 Профиль: {profile_name}")
    
    # Detailed validation results
    lines.append(f"\n🔍 Детальная проверка:")
    lines.append(f"   {'✅' if not is_fake else '❌'} Подлинность: {'Подтверждена' if not is_fake else 'НЕ подтверждена'}")
    lines.append(f"   {'✅' if not is_mod else '❌'} Оригинальность: {'Оригинал банка' if not is_mod else 'Файл изменен'}")
    lines.append(f"   {'✅' if compliance_status else '❌'} Структура PDF: {'Корректна' if compliance_status else 'Нарушена'}")
    lines.append(f"   {'✅' if not is_unrec else '❌'} Распознавание: {'Успешно' if not is_unrec else 'Не распознан'}")
    
    # Warnings if any issues detected
    if is_fake or is_mod or not compliance_status or is_unrec:
        lines.append("\n⚠️ ОБНАРУЖЕНЫ ПРОБЛЕМЫ:")
        if is_fake:
            lines.append("   🚫 Чек признан поддельным")
            lines.append("      └─ Не соответствует подписи банка")
        if is_mod:
            lines.append("   📝 Чек был пересохранен")
            lines.append("      └─ Использован сторонний редактор")
        if not compliance_status:
            lines.append("   📊 Ошибки в структуре PDF")
            lines.append("      └─ Не соответствует формату банка")
        if is_unrec:
            lines.append("   ❓ Чек не полностью распознан")
    
    # Check reuse warning
    try:
        last_checks_int = int(last_checks) if last_checks else 0
        if last_checks_int > 0:
            lines.append(f"\n🔄 История проверок: {last_checks_int} раз(а)")
            if last_checks_int > 3:
                lines.append("   ⚠️ ВНИМАНИЕ: Чек проверялся многократно!")
                lines.append("   └─ Возможна попытка повторного использования")
            else:
                lines.append("   ℹ️ Чек уже проверялся ранее")
    except (ValueError, TypeError):
        pass
    
    # Check data if present
    if check_data:
        lines.append(f"\n💳 Данные транзакции:")
        
        # Sender info
        if "sender_name" in check_data or "sender_acc" in check_data:
            lines.append(f"  📤 Отправитель:")
            if "sender_name" in check_data:
                lines.append(f"     • ФИО: {check_data['sender_name']}")
            if "sender_acc" in check_data:
                lines.append(f"     • Счет: ****{check_data['sender_acc']}")
        
        # Recipient info
        if "remitte_name" in check_data or "remitte_acc" in check_data or "remitte_tel" in check_data:
            lines.append(f"  📥 Получатель:")
            if "remitte_name" in check_data:
                lines.append(f"     • ФИО: {check_data['remitte_name']}")
            if "remitte_acc" in check_data:
                lines.append(f"     • Счет: ****{check_data['remitte_acc']}")
            if "remitte_tel" in check_data:
                lines.append(f"     • Телефон: {check_data['remitte_tel']}")
        
        # Transaction details
        if "sum" in check_data:
            lines.append(f"  💰 Сумма: {check_data['sum']} ₽")
        if "status" in check_data:
            status_emoji = "✅" if "успешн" in check_data['status'].lower() else "ℹ️"
            lines.append(f"  {status_emoji} Статус: {check_data['status']}")
        if "payment_time" in check_data:
            try:
                dt = datetime.fromtimestamp(int(check_data['payment_time']))
                lines.append(f"  🕐 Время: {dt.strftime('%d.%m.%Y %H:%M:%S')}")
            except:
                lines.append(f"  🕐 Время: {check_data['payment_time']}")
        if "doc_id" in check_data:
            lines.append(f"  🆔 ID документа: {check_data['doc_id']}")
    
    # Final recommendation
    if is_genuine:
        lines.append(f"\n✅ РЕКОМЕНДАЦИЯ: Чек можно принять")
        lines.append(f"   └─ Все проверки подлинности пройдены")
    elif is_fake:
        lines.append(f"\n🚫 РЕКОМЕНДАЦИЯ: НЕ ПРИНИМАЙТЕ ЭТОТ ЧЕК!")
        lines.append(f"   └─ Обнаружены признаки подделки")
    else:
        lines.append(f"\n⚠️ РЕКОМЕНДАЦИЯ: Требуется дополнительная проверка")
        lines.append(f"   └─ Обнаружены подозрительные признаки")
    
    return "\n".join(lines)
    
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
    violations = []
    
    # Check all violation types regardless of color
    if not is_original:
        violations.append("❌ Чек не является оригиналом")
        violations.append("   ℹ️ Документ был изменен или пересоздан")
    
    if not struct_passed:
        violations.append(f"❌ Структура PDF нарушена: {struct_result}")
        
        # Add explanation of what struct_result means
        try:
            if "/" in struct_result:
                passed, total = struct_result.split("/")
                failed = int(total) - int(passed)
                violations.append(f"   ℹ️ Не пройдено {failed} из {total} проверок структуры:")
                violations.append(f"   • Метаданные PDF (автор, дата создания)")
                violations.append(f"   • Цифровые подписи и сертификаты")
                violations.append(f"   • Формат и кодировка документа")
                violations.append(f"   • Встроенные шрифты и изображения")
                violations.append(f"   • История изменений файла")
                violations.append(f"   • Структура объектов PDF")
                violations.append(f"   • XMP метаданные")
                violations.append(f"   • Свойства приложения создателя")
        except:
            pass
    
    if device_error:
        violations.append("❌ Обнаружена ошибка сохранения файла")
        violations.append("   ℹ️ Файл был создан или изменен некорректно")
    
    # Check for specific fields that might indicate issues
    if "last_checks" in check_result:
        try:
            last_checks = int(check_result.get("last_checks", 0))
            if last_checks > 0:
                violations.append(f"⚠️ Чек уже проверялся {last_checks} раз")
                violations.append(f"   ℹ️ Возможна попытка мошенничества")
        except:
            pass
    
    if violations:
        lines.append(f"\n⚠️ Обнаруженные нарушения:")
        for violation in violations:
            lines.append(f"  {violation}")
    
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
        
        # Step 1: Upload to SafeCheck API
        upload_result = await safecheck_upload_pdf(bytes(pdf_bytes), document.file_name or "check.pdf")
        
        if upload_result.get('error', 1) == 1:
            error_msg = upload_result.get('msg', upload_result.get('message', 'Неизвестная ошибка'))
            await msg.edit_text(f"❌ Ошибка загрузки: {error_msg}")
            return

        file_id = None
        # SafeCheck may return file_id in different places
        if isinstance(upload_result.get('result'), dict):
            file_id = upload_result['result'].get('file_id')
        if not file_id:
            file_id = upload_result.get('file_id')

        if not file_id:
            await msg.edit_text("❌ Не получен file_id от SafeCheck API")
            return

        await msg.edit_text(f"⏳ Чек загружен (ID: {str(file_id)[:8]}...). Ожидание результата...")

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
