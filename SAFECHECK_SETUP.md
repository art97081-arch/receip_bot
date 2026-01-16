# 🔄 Переход на SafeCheck API

Бот успешно переведен с datagrab на SafeCheck API!

## ✅ Что изменилось:

- API: datagrab → **SafeCheck** (https://ru.safecheck.online)
- Метод работы: прямой ответ → **асинхронная проверка с polling**
- Формат ответа: статусы fake/mod → **цветовые коды (white/yellow/red/black)**

## 🚀 Быстрый старт:

### 1️⃣ Получить API ключи SafeCheck:

1. Зарегистрируйтесь на https://ru.safecheck.online
2. Получите:
   - **SC-API-KEY** (API ключ)
   - **SC-USER-ID** (ваш user ID)

### 2️⃣ Обновить .env:

Откройте `.env` и замените:

```bash
SAFECHECK_API_KEY=ваш_api_ключ_здесь
SAFECHECK_USER_ID=ваш_user_id_здесь
```

### 3️⃣ Запустить бота:

```bash
export $(cat .env | xargs)
/Users/step/Desktop/bot_helper/.venv/bin/python bot.py
```

## 📊 Новые статусы проверки:

| Цвет | Значение | Описание |
|------|----------|----------|
| **white** | ✅ Подлинный | Чек прошел все проверки |
| **yellow** | ⚠️ Подозрительный | Требует дополнительной проверки |
| **red/black** | 🚫 Поддельный | Обнаружены признаки подделки |
| **not_supported** | ❓ Не поддерживается | Банк не в базе |

## 🔍 Что проверяет SafeCheck:

- ✅ **is_original** - оригинальность документа
- ✅ **struct_passed** - корректность структуры PDF
- ✅ **device_error** - ошибки при сохранении файла
- ✅ **recommendation** - рекомендация системы
- ✅ **check_data** - данные транзакции

## 💳 Данные чека:

SafeCheck извлекает:
- Отправитель (ФИО, банк, счет)
- Получатель (ФИО, банк, счет)
- Сумма
- Дата и время
- Статус платежа

## ⚙️ Как работает проверка:

1. **Upload** → POST `/check` → получаем `file_id`
2. **Polling** → GET `/getCheck?file_id=...` → ждем `status=completed`
3. **Format** → красивый вывод результатов

Обычно проверка занимает **3-15 секунд**.

## 🆚 Отличия от datagrab:

| Параметр | datagrab | SafeCheck |
|----------|----------|-----------|
| Ответ | Синхронный | Асинхронный (polling) |
| Статусы | fake/mod/unrec | white/yellow/red/black |
| Детализация | Базовая | Расширенная |
| Поля | is_fake, is_mod | color, is_original, recommendation |

## 📝 Пример ответа SafeCheck:

```json
{
  "error": 0,
  "result": {
    "color": "white",
    "is_original": true,
    "recommendation": "Ok",
    "verifier": "sberbank_default",
    "struct_passed": true,
    "struct_result": "16/16",
    "check_data": {
      "sender_fio": "Иван И.",
      "sender_bank": "Сбербанк",
      "recipient_fio": "Петр П.",
      "recipient_bank": "Т-Банк",
      "sum": "1000 ₽",
      "date": 1736069820,
      "status": "Исполнено"
    },
    "status": "completed"
  }
}
```

## 🔒 Безопасность:

- ✅ API ключи в `.env` (не в коде)
- ✅ `.env` в `.gitignore`
- ✅ Резервная копия старой версии: `bot_datagrab_backup.py`

## 🆘 Troubleshooting:

### Ошибка: "SAFECHECK_API_KEY not set"
→ Заполните `.env` файл

### Ошибка: "Превышено время ожидания"
→ Увеличьте `max_retries` или `delay` в `safecheck_get_result()`

### Чек не проверяется
→ Проверьте баланс на https://ru.safecheck.online

## 📚 Документация SafeCheck:

https://ru.safecheck.online/documentation

---

**Готово!** Теперь бот работает с SafeCheck API 🎉
