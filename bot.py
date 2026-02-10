import os
import json
import random
import sqlite3
from telegram import (
    InlineQueryResultCachedSticker, InlineKeyboardButton, 
    InlineKeyboardMarkup, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    InlineQueryHandler, ChosenInlineResultHandler, ContextTypes, MessageHandler, filters
)

# --- KONFIGURASI ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DB_FILE = "gaple_data.db"

with open('kartu.json', 'r') as f:
    ALL_CARDS = json.load(f)

games = {}
LOG_GROUP_ID = None 

# --- DATABASE LOKAL (SQLite) ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id INTEGER PRIMARY KEY, name TEXT, koin INTEGER DEFAULT 1000, win INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

# --- FUNGSI LOG GRUP ---
async def kirim_log(context, text):
    if LOG_GROUP_ID:
        try:
            await context.bot.send_message(chat_id=LOG_GROUP_ID, text=text, parse_mode="Markdown", disable_web_page_preview=True)
        except: pass

# --- LOGIKA GAME ---
async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games.get(chat_id)
    if not game or query.from_user.id != game["creator"]: return

    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    for p in game["players"]:
        p["hand"] = [deck.pop() for _ in range(7)]
    
    game["stockpile"] = deck
    game["status"] = "PLAYING"
    
    # Log Grup (Klikable)
    chat = query.message.chat
    link = f"https://t.me/{chat.username}" if chat.username else f"ID: `{chat_id}`"
    log_text = (f"🚀 **GAME DIMULAI**\n📍 Grup: `{chat.title}`\n🔗 Link: {link}\n👥 Pemain: {len(game['players'])}")
    await kirim_log(context, log_text)

    await query.message.delete()
    await move_to_next_turn(chat_id, context)

async def move_to_next_turn(chat_id, context):
    game = games[chat_id]
    p = game["players"][game["turn_index"]]
    kb = [
        [InlineKeyboardButton("🃏 Pilih Kartu", switch_inline_query_current_chat="")],
        [InlineKeyboardButton(f"Cangkul ({len(game['stockpile'])}) / Pass", callback_data="draw_pass")]
    ]
    meja = f"[{game['ends'][0]}] --- [{game['ends'][1]}]" if game['ends'][0] is not None else "Meja Kosong"
    await context.bot.send_message(chat_id, f"📍 Meja: `{meja}`\n🕒 Giliran: **{p['name']}**", 
                                 reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# --- PANEL ADMIN (PRIVATE) ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    kb = [
        [InlineKeyboardButton("📦 Backup DB (Send)", callback_data="adm_senddb")],
        [InlineKeyboardButton("📢 Set Grup Log Di Sini", callback_data="adm_setlog")]
    ]
    await update.message.reply_text("🛠 **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(kb))

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    global LOG_GROUP_ID
    if query.data == "adm_setlog":
        LOG_GROUP_ID = query.message.chat_id
        await query.answer("✅ Grup Log Terpasang!")
    elif query.data == "adm_senddb":
        if os.path.exists(DB_FILE):
            await context.bot.send_document(chat_id=ADMIN_ID, document=open(DB_FILE, 'rb'), caption="📦 Backup Database")
            await query.answer("DB dikirim!")

# --- BACKUP/RESTORE CMD (HANYA ADMIN) ---
async def send_db_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Command ini tidak didaftarkan di BotFather agar user tidak tahu
    if update.effective_user.id != ADMIN_ID: return
    if os.path.exists(DB_FILE):
        await update.message.reply_document(document=open(DB_FILE, 'rb'))

async def restore_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        return await update.message.reply_text("Reply file .db dengan /restoredb")
    file = await context.bot.get_file(update.message.reply_to_message.document.file_id)
    await file.download_to_drive(DB_FILE)
    await update.message.reply_text("✅ DB Restored!")

if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    
    # User Commands
    app.add_handler(CommandHandler("new", lambda u, c: ...)) # Fungsi lobby tetap ada
    
    # Admin Commands (Hanya kamu yang tahu)
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("senddb", send_db_manual)) # Tidak muncul di menu "/"
    app.add_handler(CommandHandler("restoredb", restore_db))
    
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="adm_"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(CallbackQueryHandler(lambda u, c: ..., pattern="draw_pass")) # Logika cangkul tetap ada
    
    app.add_handler(InlineQueryHandler(lambda u, c: ...)) # Logika inline tetap ada
    app.add_handler(ChosenInlineResultHandler(lambda u, c: ...)) # Logika buang kartu tetap ada
    
    print("Bot Gaple Privat Aktif!")
    app.run_polling()
