# Обновление переменных на Railway для Datagrab API

Бот мигрирован с SafeCheck на Datagrab API. Railway автоматически задеплоит новый код.

## Шаги для обновления переменных окружения:

1. Открой проект на Railway: https://railway.app
2. Выбери свой проект `receip_bot`
3. Перейди в раздел **Variables**
4. **УДАЛИ** старые переменные SafeCheck:
   - `SAFECHECK_API_KEY`
   - `SAFECHECK_USER_ID`
   - `SAFECHECK_ENDPOINT`

5. **ДОБАВЬ** новые переменные Datagrab:
   - `DATAGRAB_API_KEY` = `dfnh4fsk33ysf`
   - `DATAGRAB_ENDPOINT` = `https://api.datagrab.ru`

6. Убедись что есть:
   - `BOT_TOKEN` = `8590047017:AAFWr0Z5vty5L84Gt1BbFJxhrEhvNy_u9NQ`
   - `OWNER_ID` = `6781252224`

7. После сохранения переменных Railway автоматически перезапустит бот

## Готовые переменные для копирования:

```
BOT_TOKEN=8590047017:AAFWr0Z5vty5L84Gt1BbFJxhrEhvNy_u9NQ
DATAGRAB_API_KEY=dfnh4fsk33ysf
DATAGRAB_ENDPOINT=https://api.datagrab.ru
OWNER_ID=6781252224
```

## Проверка работы:

После деплоя отправь боту PDF чек. Бот должен:
- Принять файл
- Загрузить на Datagrab API
- Вернуть результат проверки

## Отличия от SafeCheck:

✅ **Datagrab преимущества:**
- Один запрос (без polling)
- Быстрее получение результата
- Нет проблем с балансом (если API ключ активный)
- Простая интеграция

❌ **SafeCheck удалён:**
- Требовался polling (10 запросов)
- Проблемы с балансом
- Сложнее интеграция
