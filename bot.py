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

# Load kartu dari file lokal
with open('kartu.json', 'r') as f:
    ALL_CARDS = json.load(f)

games = {}
LOG_GROUP_ID = None # ID Grup Log disimpan di memori

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
        except Exception as e:
            print(f"Gagal kirim log: {e}")

# --- LOGIKA GAME ---
async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games.get(chat_id)
    
    if not game or query.from_user.id != game["creator"]:
        return await query.answer("Hanya Host yang bisa mulai!", show_alert=True)

    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    
    # Pembagian 7 kartu per orang (Aturan Standar)
    for p in game["players"]:
        p["hand"] = [deck.pop() for _ in range(7)]
    
    game["stockpile"] = deck # Sisa kartu jadi cangkulan
    game["status"] = "PLAYING"
    
    # Logika Log Grup (Link bisa diklik)
    chat = query.message.chat
    link = f"https://t.me/{chat.username}" if chat.username else f"ID: `{chat_id}`"
    log_text = (f"🚀 **GAME DIMULAI**\n"
                f"📍 Grup: `{chat.title}`\n"
                f"🔗 Link: {link}\n"
                f"👥 Pemain: {len(game['players'])}\n"
                f"🃏 Sisa Cangkulan: {len(game['stockpile'])}")
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
    await context.bot.send_message(
        chat_id, 
        f"📍 Meja: `{meja}`\n🕒 Giliran: **{p['name']}**\nSisa Kartu: {len(p['hand'])}",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown"
    )

async def draw_pass(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games.get(chat_id)
    if not game: return
    
    p = game["players"][game["turn_index"]]
    if query.from_user.id != p["id"]:
        return await query.answer("Bukan giliranmu!", show_alert=True)

    if game["stockpile"]:
        card = game["stockpile"].pop()
        p["hand"].append(card)
        await query.answer(f"Kamu cangkul: {card['nama']}", show_alert=True)
    else:
        # Jika cangkulan habis, pemain baru bisa PASS
        game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
        await query.answer("Cangkulan habis, kamu lewat (Pass)!")
    
    await move_to_next_turn(chat_id, context)

# --- PANEL ADMIN & DATABASE ---
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
        await query.answer("✅ Grup ini diset sebagai pusat Log!", show_alert=True)
        await query.message.edit_text(f"✅ **Grup Log Aktif**\nID: `{LOG_GROUP_ID}`")

    elif query.data == "adm_senddb":
        if os.path.exists(DB_FILE):
            await context.bot.send_document(chat_id=ADMIN_ID, document=open(DB_FILE, 'rb'), caption="📦 Backup Database User/Koin")
            await query.answer("File DB dikirim ke PC!")
        else:
            await query.answer("File DB belum ada.")

async def restore_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cara pakai: Kirim file .db lalu reply dengan /restoredb"""
    if update.effective_user.id != ADMIN_ID: return
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        return await update.message.reply_text("Balas (reply) file database-nya dengan perintah /restoredb")
    
    doc = update.message.reply_to_message.document
    if not doc.file_name.endswith('.db'):
        return await update.message.reply_text("Itu bukan file .db!")
        
    file = await context.bot.get_file(doc.file_id)
    await file.download_to_drive(DB_FILE)
    await update.message.reply_text("✅ Database berhasil ditimpa (Restored)!")

# --- INLINE HANDLER ---
async def handle_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.inline_query
    user_id = query.from_user.id
    
    game = next((g for g in games.values() if any(p['id'] == user_id for p in g['players'])), None)
    if not game or game["status"] != "PLAYING": return

    p = next(p for p in game["players"] if p["id"] == user_id)
    is_turn = game["players"][game["turn_index"]]["id"] == user_id
    
    res = []
    if is_turn:
        for c in p["hand"]:
            if game["ends"][0] is None or c["sisi_a"] in game["ends"] or c["sisi_b"] in game["ends"]:
                res.append(InlineQueryResultCachedSticker(id=f"{id(game)}:{c['nama']}", sticker_file_id=c["sticker_id"]))
    await query.answer(res, cache_time=0, is_personal=True)

async def on_chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chosen_inline_result
    game_ref, card_name = result.result_id.split(":")
    game = next((g for g in games.values() if str(id(g)) == game_ref), None)
    if not game: return

    p = next(p for p in game["players"] if p["id"] == result.from_user.id)
    card = next(c for c in ALL_CARDS if c["nama"] == card_name)
    
    p["hand"] = [c for c in p["hand"] if c["nama"] != card_name]
    
    # Update Meja
    if game["ends"][0] is None: game["ends"] = [card["sisi_a"], card["sisi_b"]]
    else:
        if card["sisi_a"] == game["ends"][0]: game["ends"][0] = card["sisi_b"]
        elif card["sisi_b"] == game["ends"][0]: game["ends"][0] = card["sisi_a"]
        elif card["sisi_a"] == game["ends"][1]: game["ends"][1] = card["sisi_b"]
        elif card["sisi_b"] == game["ends"][1]: game["ends"][1] = card["sisi_a"]

    if not p["hand"]:
        await context.bot.send_message(LOG_GROUP_ID if LOG_GROUP_ID else result.from_user.id, f"🎉 {p['name']} MENANG!")
        game["status"] = "ENDED"
    else:
        game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
        # Chat_id diperlukan di sini untuk melanjutkan pesan turn

if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("restoredb", restore_db))
    app.add_handler(CallbackQueryHandler(admin_callback, pattern="adm_"))
    app.add_handler(CallbackQueryHandler(draw_pass, pattern="draw_pass"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(InlineQueryHandler(handle_inline))
    app.add_handler(ChosenInlineResultHandler(on_chosen_inline))
    
    print("Bot Gaple Pro Aktif!")
    app.run_polling()
