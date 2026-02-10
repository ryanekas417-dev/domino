import os
import json
import random
import psycopg2
from telegram import (
    InlineQueryResultCachedSticker, InlineKeyboardButton, 
    InlineKeyboardMarkup, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    InlineQueryHandler, ContextTypes
)

# --- KONFIGURASI (AMBIL DARI OS ENV) ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL")

# Load 28 kartu dari kartu.json
try:
    with open('kartu.json', 'r') as f:
        ALL_CARDS = json.load(f)
except FileNotFoundError:
    ALL_CARDS = []

# Penampung Game Aktif
games = {} 

# --- DATABASE INIT ---
def init_db():
    if not DATABASE_URL: return
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute('''CREATE TABLE IF NOT EXISTS users 
                   (id BIGINT PRIMARY KEY, name TEXT, koin INT DEFAULT 1000)''')
    conn.commit()
    cur.close()
    conn.close()

# --- LOGIKA GAME ---
async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Inisialisasi Data Game
    games[chat_id] = {
        "creator": user_id,
        "players": [], 
        "status": "LOBBY",
        "table": [],
        "ends": [None, None], # [Ujung Kiri, Ujung Kanan]
        "turn_index": 0
    }
    
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    await update.message.reply_text(
        f"🀄 **GAPLE LOBBY OPEN**\nHost: {update.effective_user.first_name}\nMinimal 2 orang untuk mulai.",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    chat_id = update.effective_chat.id
    
    if chat_id not in games: return
    game = games[chat_id]

    if any(p['id'] == user.id for p in game["players"]):
        return await query.answer("Kamu sudah join!")
    
    if len(game["players"]) >= 4:
        return await query.answer("Lobby penuh (Max 4)!")

    game["players"].append({"id": user.id, "name": user.first_name, "hand": []})
    await query.answer(f"Halo {user.first_name}, kamu masuk lobby!")
    
    # Update tampilan lobby
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("Mulai Game 🚀", callback_data="start_now")])
        
    await query.message.edit_text(
        f"🀄 **LOBBY GAPLE**\nTotal: {len(game['players'])} Pemain\n\n"
        f"Host: {game['players'][0]['name']}\n"
        f"Status: Menunggu Host memulai...",
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    game = games[chat_id]

    # Hanya creator yang boleh mulai
    if query.from_user.id != game["creator"]:
        return await query.answer("Hanya pembuat lobby yang bisa memulai!", show_alert=True)

    if len(game["players"]) < 2:
        return await query.answer("Minimal butuh 2 pemain!")

    game["status"] = "PLAYING"
    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    
    # Bagi kartu 7 per orang
    for p in game["players"]:
        p["hand"] = [deck.pop() for _ in range(7)]
    
    nama_giliran = game["players"][game["turn_index"]]["name"]
    await query.message.edit_text(
        f"🏁 **GAME DIMULAI!**\n\nGiliran: **{nama_giliran}**\n\n"
        f"Ketik `@{(await context.bot.get_me()).username}` untuk pilih kartu!",
        parse_mode="Markdown"
    )

# --- INLINE QUERY: LOGIKA FILTER KARTU ---
async def handle_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user_id = query.from_user.id
    
    # Cari game aktif di mana user ini bergabung
    current_game = None
    my_data = None
    for gid, gdata in games.items():
        for p in gdata["players"]:
            if p["id"] == user_id:
                current_game = gdata
                my_data = p
                break
    
    if not current_game or current_game["status"] != "PLAYING": return

    results = []
    ends = current_game["ends"]
    
    # Cek apakah ini giliran si user?
    is_my_turn = current_game["players"][current_game["turn_index"]]["id"] == user_id

    for card in my_data["hand"]:
        can_play = False
        # Logika: Jika giliran saya...
        if is_my_turn:
            # Jika meja kosong (awal game), semua kartu boleh
            if ends[0] is None: 
                can_play = True
            # Jika meja ada isinya, salah satu sisi kartu harus match ujung meja
            elif card["sisi_a"] in ends or card["sisi_b"] in ends:
                can_play = True

        # Hanya kartu yang bisa dimainkan yang muncul di menu inline
        if can_play:
            results.append(
                InlineQueryResultCachedSticker(
                    id=f"{card['nama']}_{user_id}", 
                    sticker_file_id=card["sticker_id"]
                )
            )

    await query.answer(results, cache_time=0, is_personal=True)

# --- ADMIN: BACKUP DATABASE ---
async def send_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    # Kirim file kartu.json sebagai backup
    if os.path.exists("kartu.json"):
        await update.message.reply_document(
            open("kartu.json", "rb"), 
            caption="Ini backup kartu.json terbaru kamu."
        )
    else:
        await update.message.reply_text("File kartu.json tidak ditemukan.")

if __name__ == '__main__':
    # init_db() # Jalankan jika sudah setup PostgreSQL di Railway
    
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("new", new_game))
    app.add_handler(CommandHandler("senddb", send_db))
    app.add_handler(CallbackQueryHandler(join_game, pattern="join"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(InlineQueryHandler(handle_inline))
    
    print("Bot Gaple Online Siap!")
    app.run_polling()
