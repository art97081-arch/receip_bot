# 🚀 Быстрый старт

## 1️⃣ Установка (1 минута)

```bash
cd /Users/step/Desktop/bot_helper
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2️⃣ Настройка (2 минуты)

### Создайте файл `.env`:

```bash
cp .env.example .env
nano .env  # или любой редактор
```

### Заполните 4 параметра:

1. **BOT_TOKEN** — зайдите в Telegram → @BotFather → `/newbot` → скопируйте токен
2. **DATAGRAB_API_KEY** — ваш ключ от bankpdf.ru
3. **OWNER_ID** — ваш Telegram ID (узнайте в @userinfobot)
4. **DATAGRAB_ENDPOINT** — оставьте `https://api.datagrab.ru/upload.php`

Пример `.env`:
```bash
BOT_TOKEN=8200377370:AAENmD6RKlxdQYIAMjKsZQ-UkY3LaNJQ4Uk
DATAGRAB_API_KEY=ваш_ключ_здесь
DATAGRAB_ENDPOINT=https://api.datagrab.ru/upload.php
OWNER_ID=123456789
```

⚠️ **ВАЖНО**: Замените токен выше! Если вы его уже публиковали — отзовите в @BotFather!

## 3️⃣ Запуск (10 секунд)

```bash
export $(cat .env | xargs)
python bot.py
```

✅ Готово! Бот запущен!

## 4️⃣ Первое использование

1. Найдите вашего бота в Telegram
2. Напишите `/start`
3. Добавьте себе доступ: `/allow ваш_user_id`
4. Отправьте PDF чек боту
5. Получите результат проверки!

## 🎯 Как добавить другого пользователя

```
/allow 987654321
```

где `987654321` — ID пользователя (пусть узнает в @userinfobot)

## 📱 Команды бота

| Команда | Описание |
|---------|----------|
| `/start` | Помощь |
| `/allow <id>` | Добавить пользователя (только владелец) |
| `/revoke <id>` | Удалить пользователя (только владелец) |
| `/list_allowed` | Список пользователей (только владелец) |
| **Отправить PDF** | Проверить чек (для разрешенных) |

## 🆘 Проблемы?

### Бот не отвечает
- Проверьте, что `BOT_TOKEN` правильный
- Убедитесь, что бот запущен (смотрите терминал)

### "Ключ API указан неверно"
- Проверьте `DATAGRAB_API_KEY` в `.env`
- Убедитесь, что подписка активна

### "У вас нет доступа"
- Выполните `/allow ваш_user_id` от имени владельца
- Узнайте ваш ID в @userinfobot

## 🔒 Безопасность

✅ Файл `.env` уже в `.gitignore` — не будет закоммичен  
✅ Используйте разные токены для тестирования и продакшена  
✅ Регулярно меняйте API ключи  

---

💡 **Подсказка**: Чтобы бот работал постоянно, используйте `screen`, `tmux` или деплой на сервер (VPS).

Пример с `screen`:
```bash
screen -S telegram_bot
export $(cat .env | xargs)
python bot.py
# Нажмите Ctrl+A, затем D для отсоединения
# screen -r telegram_bot  # вернуться к боту
```
