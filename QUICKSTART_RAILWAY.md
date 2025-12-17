# ⚡ Быстрый старт: Деплой на Railway

## 📋 Чеклист готовности

✅ Git репозиторий инициализирован  
✅ Procfile создан  
✅ runtime.txt создан  
✅ requirements.txt создан  
✅ bot.py готов  
✅ .gitignore настроен  

## 🎯 Три простых шага:

### 1️⃣ Загрузите на GitHub

Если еще не создали репозиторий:

```bash
# Создайте новый репозиторий на github.com с именем telegram-receipt-bot
# Затем выполните:

cd /Users/step/Desktop/bot_helper
git remote add origin https://github.com/ВАШ_USERNAME/telegram-receipt-bot.git
git push -u origin main
```

### 2️⃣ Подключите к Railway

1. Зайдите на **https://railway.app**
2. Войдите через GitHub
3. New Project → Deploy from GitHub repo
4. Выберите `telegram-receipt-bot`

### 3️⃣ Добавьте переменные окружения

В Railway → Variables → добавьте:

```
BOT_TOKEN=8200377370:AAENmD6RKlxdQYIAMjKsZQ-UkY3LaNJQ4Uk
SAFECHECK_API_KEY=bb97014d466423ee30e48a83bbd670039c01c17e5f309503a449cb531e4e11ad
SAFECHECK_USER_ID=6781252224
SAFECHECK_ENDPOINT=https://ru.safecheck.online/api
OWNER_ID=6781252224
```

## ✨ Готово!

Бот автоматически задеплоится и начнет работать!

Проверьте логи: Railway → Deployments → View Logs

---

📖 Подробная инструкция: см. `RAILWAY_DEPLOY.md`
