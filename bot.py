import os
import json
import random
import psycopg2
from telegram import (
    InlineQueryResultCachedSticker, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    Update
)
from telegram.ext import (
    ApplicationBuilder, 
    CommandHandler, 
    CallbackQueryHandler, 
    InlineQueryHandler, 
    ChosenInlineResultHandler, 
    ContextTypes
)

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

with open('kartu.json', 'r') as f:
    ALL_CARDS = json.load(f)

games = {} 

# --- HELPER: PINDAH GILIRAN ---
async def move_to_next_turn(chat_id, context):
    game = games[chat_id]
    # Geser index ke pemain selanjutnya
    game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    
    p_skrg = game["players"][game["turn_index"]]
    
    # Kirim pesan giliran baru dengan tombol
    kb = [
        [InlineKeyboardButton("🃏 Pilih & Keluarkan Kartu", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("Pass / Lewat ⏩", callback_data="pass_turn")]
    ]
    
    # Tampilkan info meja saat ini
    meja_info = f"Ujung Meja: [{game['ends'][0]}] --- [{game['ends'][1]}]" if game['ends'][0] is not None else "Meja Kosong"
    
    await context.bot.send_message(
        chat_id, 
        f"Meja: `{meja_info}`\n\n"
        f"🕒 Giliran: **{p_skrg['name']}**\n"
        f"Sisa Kartu: {len(p_skrg['hand'])}",
        reply_markup=InlineKeyboardMarkup(kb),
        parse_mode="Markdown"
    )

# --- COMMANDS ---
async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    games[chat_id] = {
        "creator": update.effective_user.id,
        "players": [],
        "status": "LOBBY",
        "ends": [None, None],
        "turn_index": 0
    }
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    await update.message.reply_text("🀄 **GAPLE LOBBY**\nMaksimal 4 pemain.", reply_markup=InlineKeyboardMarkup(kb))

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games.get(chat_id)
    if not game or game["status"] != "LOBBY": return

    if any(p['id'] == query.from_user.id for p in game["players"]):
        return await query.answer("Sudah join!")
    
    game["players"].append({"id": query.from_user.id, "name": query.from_user.first_name, "hand": []})
    await query.answer("Berhasil join!")
    
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("Mulai Game 🚀", callback_data="start_now")])
    
    await query.message.edit_text(f"Pemain: {len(game['players'])}/4\n" + "\n".join([f"- {p['name']}" for p in game['players']]), reply_markup=InlineKeyboardMarkup(kb))

async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games[chat_id]
    
    if query.from_user.id != game["creator"]:
        return await query.answer("Hanya Host yang bisa mulai!", show_alert=True)

    game["status"] = "PLAYING"
    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    
    for p in game["players"]:
        p["hand"] = [deck.pop() for _ in range(7)]
    
    await query.message.delete()
    await move_to_next_turn(chat_id, context)

# --- INLINE QUERY (PILIH KARTU) ---
async def handle_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user_id = query.from_user.id
    
    game_id, game = next(((gid, g) for gid, g in games.items() if any(p['id'] == user_id for p in g['players'])), (None, None))
    if not game or game["status"] != "PLAYING": return

    player = next(p for p in game["players"] if p["id"] == user_id)
    is_turn = game["players"][game["turn_index"]]["id"] == user_id
    
    results = []
    if is_turn:
        for card in player["hand"]:
            # Hanya tampilkan kartu yang bisa nyambung
            if game["ends"][0] is None or card["sisi_a"] in game["ends"] or card["sisi_b"] in game["ends"]:
                results.append(
                    InlineQueryResultCachedSticker(
                        id=f"{game_id}:{card['nama']}", # Simpan chat_id di ID kartu
                        sticker_file_id=card["sticker_id"]
                    )
                )
    
    await query.answer(results, cache_time=0, is_personal=True)

# --- KARTU DIKLIK (CHOSEN RESULT) ---
async def on_chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chosen_inline_result
    user_id = result.from_user.id
    # Format ID kita tadi: "chat_id:nama_kartu"
    chat_id_str, card_name = result.result_id.split(":")
    chat_id = int(chat_id_str)
    
    game = games.get(chat_id)
    if not game: return

    player = next(p for p in game["players"] if p["id"] == user_id)
    card_data = next(c for c in ALL_CARDS if c["nama"] == card_name)

    # 1. HAPUS KARTU DARI TANGAN
    player["hand"] = [c for c in player["hand"] if c["nama"] != card_name]

    # 2. UPDATE UJUNG MEJA
    a, b = card_data["sisi_a"], card_data["sisi_b"]
    if game["ends"][0] is None:
        game["ends"] = [a, b]
    else:
        # Cari mana yang nyambung dan update ujung yang baru
        if a == game["ends"][0]: game["ends"][0] = b
        elif b == game["ends"][0]: game["ends"][0] = a
        elif a == game["ends"][1]: game["ends"][1] = b
        elif b == game["ends"][1]: game["ends"][1] = a

    # 3. CEK APAKAH MENANG
    if not player["hand"]:
        await context.bot.send_message(chat_id, f"🏆 **{player['name']} MENANG!** Kartu habis.")
        game["status"] = "ENDED"
    else:
        # 4. LANJUT GILIRAN
        await move_to_next_turn(chat_id, context)

async def pass_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games.get(chat_id)
    
    if query.from_user.id != game["players"][game["turn_index"]]["id"]:
        return await query.answer("Bukan giliranmu!", show_alert=True)
    
    await query.answer("Kamu lewat.")
    await move_to_next_turn(chat_id, context)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("new", new_game))
    app.add_handler(CallbackQueryHandler(join_game, pattern="join"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(CallbackQueryHandler(pass_turn, pattern="pass_turn"))
    app.add_handler(InlineQueryHandler(handle_inline))
    # INI YANG PENTING UNTUK HAPUS KARTU & LANJUT GILIRAN
    app.add_handler(ChosenInlineResultHandler(on_chosen_inline))
    app.run_polling()
    InlineQueryResultCachedSticker, InlineKeyboardButton, 
    InlineKeyboardMarkup, Update
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, 
    InlineQueryHandler, ContextTypes, ChosenInlineResultHandler
)

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATABASE_URL = os.getenv("DATABASE_URL")

with open('kartu.json', 'r') as f:
    ALL_CARDS = json.load(f)

games = {} 

# --- LOGIKA HELPER ---
def next_turn(chat_id):
    game = games[chat_id]
    game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    return game["players"][game["turn_index"]]

# --- COMMANDS ---
async def new_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    games[chat_id] = {
        "creator": update.effective_user.id,
        "players": [],
        "status": "LOBBY",
        "table": [],
        "ends": [None, None],
        "turn_index": 0
    }
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    await update.message.reply_text("🀄 **GAPLE LOBBY**\nMinimal 2, Maksimal 4 pemain.", 
                                  reply_markup=InlineKeyboardMarkup(kb))

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if chat_id not in games: return
    game = games[chat_id]

    if any(p['id'] == query.from_user.id for p in game["players"]):
        return await query.answer("Sudah join!")
    if len(game["players"]) >= 4:
        return await query.answer("Lobby penuh!")

    game["players"].append({"id": query.from_user.id, "name": query.from_user.first_name, "hand": []})
    await query.answer("Berhasil join!")
    
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("Mulai Game 🚀", callback_data="start_now")])
    
    await query.message.edit_text(f"🀄 **LOBBY**\nPemain ({len(game['players'])}/4):\n" + 
                                 "\n".join([f"- {p['name']}" for p in game['players']]),
                                 reply_markup=InlineKeyboardMarkup(kb))

async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    game = games[update.effective_chat.id]
    if query.from_user.id != game["creator"]:
        return await query.answer("Hanya Host yang bisa mulai!", show_alert=True)

    game["status"] = "PLAYING"
    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    for p in game["players"]:
        p["hand"] = [deck.pop() for _ in range(7)]
    
    await send_turn_msg(update.effective_chat.id, context)

async def send_turn_msg(chat_id, context):
    game = games[chat_id]
    p = game["players"][game["turn_index"]]
    kb = [
        [InlineKeyboardButton("🃏 Pilih & Keluarkan Kartu", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("Pass / Lewat ⏩", callback_data="pass_turn")]
    ]
    await context.bot.send_message(chat_id, f"🕒 Giliran: **{p['name']}**\nSisa kartu: {len(p['hand'])}", 
                                 reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")

# --- INLINE QUERY ---
async def handle_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user_id = query.from_user.id
    res = []
    
    # Cari game aktif
    game = next((g for g in games.values() if any(p['id'] == user_id for p in g['players'])), None)
    if not game or game["status"] != "PLAYING": return

    p_data = next(p for p in game["players"] if p["id"] == user_id)
    is_turn = game["players"][game["turn_index"]]["id"] == user_id
    
    if is_turn:
        for card in p_data["hand"]:
            # Validasi kartu cocok dengan ujung meja
            if game["ends"][0] is None or card["sisi_a"] in game["ends"] or card["sisi_b"] in game["ends"]:
                res.append(InlineQueryResultCachedSticker(id=card["nama"], sticker_file_id=card["sticker_id"]))
    
    await query.answer(res, cache_time=0, is_personal=True)

# --- LOGIKA KARTU DIKELUARKAN ---
async def on_chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chosen_inline_result
    user_id = result.from_user.id
    card_name = result.result_id
    
    # Cari game dan hapus kartu dari tangan
    for chat_id, game in games.items():
        for p in game["players"]:
            if p["id"] == user_id:
                # Hapus kartu yang dibuang
                p["hand"] = [c for c in p["hand"] if c["nama"] != card_name]
                
                # Update Ujung Meja (Logika Sederhana)
                card_data = next(c for c in ALL_CARDS if c["nama"] == card_name)
                if game["ends"][0] is None:
                    game["ends"] = [card_data["sisi_a"], card_data["sisi_b"]]
                else:
                    # Logika sambung kiri/kanan
                    if card_data["sisi_a"] == game["ends"][0]: game["ends"][0] = card_data["sisi_b"]
                    elif card_data["sisi_b"] == game["ends"][0]: game["ends"][0] = card_data["sisi_a"]
                    elif card_data["sisi_a"] == game["ends"][1]: game["ends"][1] = card_data["sisi_b"]
                    elif card_data["sisi_b"] == game["ends"][1]: game["ends"][1] = card_data["sisi_a"]

                # Cek Menang
                if not p["hand"]:
                    await context.bot.send_message(chat_id, f"🎉 **{p['name']} MENANG!** Game Berakhir.")
                    game["status"] = "ENDED"
                    return

                # Ganti Giliran
                next_turn(chat_id)
                await send_turn_msg(chat_id, context)
                break

async def pass_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = update.effective_chat.id
    game = games.get(chat_id)
    if not game: return
    
    if query.from_user.id != game["players"][game["turn_index"]]["id"]:
        return await query.answer("Bukan giliranmu!", show_alert=True)
    
    next_turn(chat_id)
    await query.answer("Kamu lewat.")
    await send_turn_msg(chat_id, context)

if __name__ == '__main__':
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("new", new_game))
    app.add_handler(CallbackQueryHandler(join_game, pattern="join"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(CallbackQueryHandler(pass_turn, pattern="pass_turn"))
    app.add_handler(InlineQueryHandler(handle_inline))
    app.add_handler(ChosenInlineResultHandler(on_chosen_inline)) # Deteksi kartu dibuang
    app.run_polling()
