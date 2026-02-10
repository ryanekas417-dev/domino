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
DATABASE_URL = os.getenv("DATABASE_URL")

try:
    with open('kartu.json', 'r') as f:
        ALL_CARDS = json.load(f)
except Exception as e:
    ALL_CARDS = []

games = {} 

# --- DATABASE ---
def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

def init_db():
    if not DATABASE_URL: return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS users (
            id BIGINT PRIMARY KEY, 
            name TEXT, 
            win INT DEFAULT 0, 
            koin INT DEFAULT 1000)''')
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB Error: {e}")

def update_win(user_id, name):
    if not DATABASE_URL: return
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''INSERT INTO users (id, name, win, koin) VALUES (%s, %s, 1, 1500)
                       ON CONFLICT (id) DO UPDATE SET win = users.win + 1, koin = users.koin + 500''', (user_id, name))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Update Error: {e}")

# --- HELPERS ---
async def move_to_next_turn(chat_id, context):
    game = games[chat_id]
    game["turn_index"] = (game["turn_index"] + 1) % len(game["players"])
    p_skrg = game["players"][game["turn_index"]]
    
    kb = [
        [InlineKeyboardButton("🃏 Pilih & Keluarkan Kartu", switch_inline_query_current_chat="")],
        [InlineKeyboardButton("Pass / Lewat ⏩", callback_data="pass_turn")]
    ]
    
    meja = f"[{game['ends'][0]}] --- [{game['ends'][1]}]" if game['ends'][0] is not None else "KOSONG"
    
    await context.bot.send_message(
        chat_id, 
        f"Meja: `{meja}`\n\n🕒 Giliran: **{p_skrg['name']}**\nSisa Kartu: {len(p_skrg['hand'])}",
        reply_markup=InlineKeyboardMarkup(kb), 
        parse_mode="Markdown"
    )

# --- COMMANDS ---
async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not DATABASE_URL: return
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, win FROM users ORDER BY win DESC LIMIT 10")
    rows = cur.fetchall()
    text = "🏆 **LEADERBOARD**\n\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. {row[0]} - {row[1]} Win\n"
    cur.close()
    conn.close()
    await update.message.reply_text(text, parse_mode="Markdown")

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
    await update.message.reply_text("🀄 **GAPLE LOBBY**", reply_markup=InlineKeyboardMarkup(kb))

async def join_game(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    game = games.get(query.message.chat_id)
    if not game or game["status"] != "LOBBY": return
    if any(p['id'] == query.from_user.id for p in game["players"]): return
    
    game["players"].append({"id": query.from_user.id, "name": query.from_user.first_name, "hand": []})
    await query.answer("Joined!")
    
    kb = [[InlineKeyboardButton("Join Game 🤝", callback_data="join")]]
    if len(game["players"]) >= 2:
        kb.append([InlineKeyboardButton("Mulai Game 🚀", callback_data="start_now")])
    await query.message.edit_text(f"Pemain: {len(game['players'])}\n" + "\n".join([f"- {p['name']}" for p in game['players']]), reply_markup=InlineKeyboardMarkup(kb))

async def start_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    game = games[chat_id]
    if query.from_user.id != game["creator"]: return
    
    game["status"] = "PLAYING"
    deck = ALL_CARDS.copy()
    random.shuffle(deck)
    for p in game["players"]: p["hand"] = [deck.pop() for _ in range(7)]
    
    await query.message.delete()
    await move_to_next_turn(chat_id, context)

# --- INLINE ---
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
            if game["ends"][0] is None or card["sisi_a"] in game["ends"] or card["sisi_b"] in game["ends"]:
                results.append(InlineQueryResultCachedSticker(id=f"{game_id}:{card['nama']}", sticker_file_id=card["sticker_id"]))
    await query.answer(results, cache_time=0, is_personal=True)

async def on_chosen_inline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chosen_inline_result
    chat_id_str, card_name = result.result_id.split(":")
    game = games.get(int(chat_id_str))
    if not game: return

    player = next(p for p in game["players"] if p["id"] == result.from_user.id)
    card_data = next(c for c in ALL_CARDS if c["nama"] == card_name)

    player["hand"] = [c for c in player["hand"] if c["nama"] != card_name]
    a, b = card_data["sisi_a"], card_data["sisi_b"]
    if game["ends"][0] is None: game["ends"] = [a, b]
    else:
        if a == game["ends"][0]: game["ends"][0] = b
        elif b == game["ends"][0]: game["ends"][0] = a
        elif a == game["ends"][1]: game["ends"][1] = b
        elif b == game["ends"][1]: game["ends"][1] = a

    if not player["hand"]:
        await context.bot.send_message(int(chat_id_str), f"🏆 **{player['name']} MENANG!**")
        update_win(player["id"], player["name"])
        game["status"] = "ENDED"
    else:
        await move_to_next_turn(int(chat_id_str), context)

async def pass_turn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    game = games.get(query.message.chat_id)
    if not game or query.from_user.id != game["players"][game["turn_index"]]["id"]: return
    await query.answer("Lewat...")
    await move_to_next_turn(query.message.chat_id, context)

if __name__ == '__main__':
    init_db()
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("new", new_game))
    app.add_handler(CommandHandler("top", leaderboard))
    app.add_handler(CallbackQueryHandler(join_game, pattern="join"))
    app.add_handler(CallbackQueryHandler(start_now, pattern="start_now"))
    app.add_handler(CallbackQueryHandler(pass_turn, pattern="pass_turn"))
    app.add_handler(InlineQueryHandler(handle_inline))
    app.add_handler(ChosenInlineResultHandler(on_chosen_inline))
    app.run_polling()
