import difflib
import html
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

# ---------------------------------------------------------------------------
# Player database. Approximate career totals; edit or add players freely.
# Use None where you don't have a number (that stat is skipped in comparisons).
# ---------------------------------------------------------------------------
PLAYERS = {
    "messi": {"name": "Lionel Messi", "country": "Argentina", "pos": "Forward",
              "goals": 890, "assists": 390, "ballon": 8, "ucl": 4, "wc": 1},
    "ronaldo": {"name": "Cristiano Ronaldo", "country": "Portugal", "pos": "Forward",
                "goals": 950, "assists": 250, "ballon": 5, "ucl": 5, "wc": 0},
    "neymar": {"name": "Neymar Jr", "country": "Brazil", "pos": "Forward",
               "goals": 440, "assists": 260, "ballon": 0, "ucl": 1, "wc": 0},
    "mbappe": {"name": "Kylian Mbappé", "country": "France", "pos": "Forward",
               "goals": 400, "assists": 120, "ballon": 0, "ucl": 0, "wc": 1},
    "haaland": {"name": "Erling Haaland", "country": "Norway", "pos": "Striker",
                "goals": 270, "assists": 60, "ballon": 0, "ucl": 1, "wc": 0},
    "salah": {"name": "Mohamed Salah", "country": "Egypt", "pos": "Forward",
              "goals": 340, "assists": 150, "ballon": 0, "ucl": 1, "wc": 0},
    "modric": {"name": "Luka Modrić", "country": "Croatia", "pos": "Midfielder",
               "goals": 50, "assists": 110, "ballon": 1, "ucl": 6, "wc": 0},
    "benzema": {"name": "Karim Benzema", "country": "France", "pos": "Striker",
                "goals": 450, "assists": None, "ballon": 1, "ucl": 5, "wc": 0},
    "pele": {"name": "Pelé", "country": "Brazil", "pos": "Forward",
             "goals": 757, "assists": None, "ballon": 0, "ucl": 0, "wc": 3},
    "maradona": {"name": "Diego Maradona", "country": "Argentina", "pos": "Attacking Mid",
                 "goals": 345, "assists": None, "ballon": 0, "ucl": 0, "wc": 1},
    "zidane": {"name": "Zinedine Zidane", "country": "France", "pos": "Attacking Mid",
               "goals": 125, "assists": None, "ballon": 1, "ucl": 1, "wc": 1},
    "ronaldinho": {"name": "Ronaldinho", "country": "Brazil", "pos": "Attacking Mid",
                   "goals": 200, "assists": None, "ballon": 1, "ucl": 1, "wc": 1},
}

# Nicknames and alternate spellings -> player key
ALIASES = {
    "leo": "messi", "lionel": "messi", "lionel messi": "messi",
    "cr7": "ronaldo", "cristiano": "ronaldo", "cris": "ronaldo",
    "neymar jr": "neymar", "ney": "neymar",
    "kylian": "mbappe", "mbappé": "mbappe", "kylian mbappe": "mbappe",
    "erling": "haaland", "mo": "salah", "mo salah": "salah",
    "luka": "modric", "modrić": "modric",
    "karim": "benzema", "pelé": "pele",
    "diego": "maradona", "zizou": "zidane", "ronaldinho gaucho": "ronaldinho",
}

STATS = [
    ("goals", "Goals"),
    ("assists", "Assists"),
    ("ballon", "Ballon d'Or"),
    ("ucl", "Champions Lg"),
    ("wc", "World Cups"),
]

FOOTNOTE = "* = higher.  Stats are approximate career totals."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def find_player(query):
    q = query.lower().strip()
    if q in PLAYERS:
        return q
    if q in ALIASES:
        return ALIASES[q]
    pool = list(PLAYERS) + list(ALIASES)
    match = difflib.get_close_matches(q, pool, n=1, cutoff=0.7)
    if match:
        m = match[0]
        return m if m in PLAYERS else ALIASES[m]
    return None


def parse_names(text):
    """Return (name1, name2) from 'messi vs ronaldo' or 'messi ronaldo'."""
    t = text.lower().strip()
    for sep in (" vs ", " v ", " versus "):
        if sep in t:
            a, b = t.split(sep, 1)
            return a.strip(), b.strip()
    parts = t.split()
    if len(parts) == 2:
        return parts[0], parts[1]
    return None


def fmt(v):
    return "n/a" if v is None else str(v)


def short(key):
    return PLAYERS[key]["name"].split()[-1]


def compare_text(a_key, b_key):
    a, b = PLAYERS[a_key], PLAYERS[b_key]
    an, bn = short(a_key), short(b_key)
    lines = [f"{'':<13}{an:>11}{bn:>11}"]
    a_wins = b_wins = 0

    for field, label in STATS:
        va, vb = a[field], b[field]
        ma = mb = ""
        if va is not None and vb is not None:
            if va > vb:
                ma, a_wins = "*", a_wins + 1
            elif vb > va:
                mb, b_wins = "*", b_wins + 1
        lines.append(f"{label:<13}{fmt(va) + ma:>11}{fmt(vb) + mb:>11}")

    if a_wins > b_wins:
        verdict = f"🏆 {a['name']} leads {a_wins}-{b_wins}"
    elif b_wins > a_wins:
        verdict = f"🏆 {b['name']} leads {b_wins}-{a_wins}"
    else:
        verdict = f"🤝 All square, {a_wins}-{b_wins}"

    table = html.escape("\n".join(lines), quote=False)
    return (
        f"⚔️ <b>{html.escape(a['name'])}</b> vs <b>{html.escape(b['name'])}</b>\n\n"
        f"<pre>{table}</pre>\n"
        f"{html.escape(verdict)}\n"
        f"<i>{html.escape(FOOTNOTE)}</i>"
    )


def profile_text(key):
    p = PLAYERS[key]
    rows = "\n".join(f"{label}: {fmt(p[field])}" for field, label in STATS)
    return (
        f"👤 <b>{html.escape(p['name'])}</b>\n"
        f"{html.escape(p['country'])} · {html.escape(p['pos'])}\n\n"
        f"<pre>{html.escape(rows)}</pre>"
    )


def picker_keyboard(exclude=None):
    buttons = [
        InlineKeyboardButton(short(k), callback_data=f"pick:{k}")
        for k in PLAYERS
        if k != exclude
    ]
    rows = [buttons[i:i + 3] for i in range(0, len(buttons), 3)]
    return InlineKeyboardMarkup(rows)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------
HELP = (
    "⚽ <b>Player Compare Bot</b>\n\n"
    "Compare football players side by side.\n\n"
    "/compare - pick two players with buttons\n"
    "/compare messi ronaldo - instant comparison\n"
    "/player haaland - single player card\n"
    "/players - list all players\n\n"
    "You can also just type: <code>messi vs ronaldo</code>"
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP, parse_mode=ParseMode.HTML)


async def players_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    names = "\n".join(f"• {p['name']}" for p in PLAYERS.values())
    await update.message.reply_text(f"Available players:\n\n{names}")


async def player_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /player messi")
        return
    key = find_player(" ".join(context.args))
    if not key:
        await update.message.reply_text("Player not found. Try /players to see the list.")
        return
    await update.message.reply_text(profile_text(key), parse_mode=ParseMode.HTML)


async def run_comparison(update: Update, text: str):
    names = parse_names(text)
    if not names:
        await update.message.reply_text(
            "Send two players like: messi vs ronaldo\nOr use /compare for buttons."
        )
        return
    a_key, b_key = find_player(names[0]), find_player(names[1])
    if not a_key or not b_key:
        missing = names[0] if not a_key else names[1]
        await update.message.reply_text(
            f"I don't know \"{missing}\". Try /players to see who's available."
        )
        return
    if a_key == b_key:
        await update.message.reply_text("Pick two different players!")
        return
    await update.message.reply_text(compare_text(a_key, b_key), parse_mode=ParseMode.HTML)


async def compare_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        await run_comparison(update, " ".join(context.args))
        return
    context.user_data.pop("first", None)
    await update.message.reply_text(
        "Pick the first player:", reply_markup=picker_keyboard()
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await run_comparison(update, update.message.text)


async def on_pick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    key = query.data.split(":", 1)[1]
    first = context.user_data.get("first")

    if first is None or first == key:
        context.user_data["first"] = key
        await query.edit_message_text(
            f"First: {PLAYERS[key]['name']}\nNow pick the second player:",
            reply_markup=picker_keyboard(exclude=key),
        )
    else:
        context.user_data.pop("first", None)
        await query.edit_message_text(
            compare_text(first, key), parse_mode=ParseMode.HTML
        )


def main():
    token = os.environ["BOT_TOKEN"]
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(CommandHandler("players", players_cmd))
    app.add_handler(CommandHandler("player", player_cmd))
    app.add_handler(CommandHandler("compare", compare_cmd))
    app.add_handler(CallbackQueryHandler(on_pick, pattern=r"^pick:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    logging.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
