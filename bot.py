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

# --- KONFIGURASI ---
TOKEN = "TOKEN_BOT_ANDA"
ADMIN_ID = 12345678 
with open('kartu.json', 'r') as f:
    ALL_CARDS = json.load(f)

games = {} # {chat_id: {data}}

# --- LOGIKA GAME ---
async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Inisialisasi Lobby
    games[chat_id] = {
        "creator": user_id,
        "players": [], # [{"id": 123, "name": "Budi", "hand": []}]
        "status": "LOBBY",
        "table": [],
        "ends": [None, None], # [ujung_kiri, ujung_kanan]
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
    await query.answer("Berhasil Join!")
    
    # Hanya creator yang bisa lihat tombol START
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("Mulai Game 🚀", callback_data="start_now")])
        
    await query.message.edit_text(
        f"🀄 **LOBBY GAPLE**\nTotal: {len(game['players'])} Pemain\nHost: <a href='tg://user?id={game['creator']}'>Klik Mulai</a>",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML"
    )

async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    game = games[chat_id]

    # VALIDASI: Hanya pembuat lobby yang bisa klik mulai
    if query.from_user.id != game["creator"]:
        return await query.answer("Hanya pembuat lobby yang bisa memulai!", show_alert=True)

    game["status"] = "PLAYING"
    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    
    # Bagi kartu (7 per orang)
    for p in game["players"]:
        p["hand"] = [deck.pop() for _ in range(7)]
    
    player_skrg = game["players"][game["turn_index"]]["name"]
    await query.message.edit_text(
        f"🏁 **GAME DIMULAI!**\n\nGiliran Pertama: **{player_skrg}**\n\nKetik `@nama_bot` untuk pilih kartu!",
        parse_mode="Markdown"
    )

# --- INLINE QUERY: FILTER KARTU ---
async def handle_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user_id = query.from_user.id
    
    # Cari game aktif user ini
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
    
    # CEK APAKAH GILIRAN DIA?
    is_my_turn = current_game["players"][current_game["turn_index"]]["id"] == user_id

    for card in my_data["hand"]:
        # LOGIKA VALIDASI:
        # 1. Harus giliran dia
        # 2. Jika meja kosong, semua kartu boleh (True)
        # 3. Jika meja isi, salah satu sisi kartu harus sama dengan salah satu ujung meja
        can_play = False
        if is_my_turn:
            if ends[0] is None: 
                can_play = True
            elif card["sisi_a"] in ends or card["sisi_b"] in ends:
                can_play = True

        if can_play:
            results.append(
                InlineQueryResultCachedSticker(
                    id=f"{card['nama']}_{current_game['creator']}", # ID unik
                    sticker_file_id=card["sticker_id"]
                )
            )
        # Kartu yang TIDAK cocok tidak dimasukkan ke results 
        # (Otomatis tidak muncul/greyed out di mata user)

    await query.answer(results, cache_time=0, is_personal=True)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("new", new_game))
    app.add_handler(CallbackQueryHandler(join_game, pattern="join"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(InlineQueryHandler(handle_inline))
    app.run_polling()
