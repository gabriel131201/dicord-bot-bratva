import os
import sys
import discord
from discord.ext import tasks, commands
from discord import app_commands, Interaction
import datetime
import pytz
from flask import Flask
import threading
from collections import defaultdict

# Verificare token
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ EROARE: DISCORD_TOKEN nu este setat! Verifică variabila de mediu în Railway.")
    sys.exit()
else:
    print("✅ Tokenul a fost găsit. Botul pornește.")


intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.reactions = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "backup.txt"
TICKET_DATA = {}
BUCHAREST_TZ = pytz.timezone("Europe/Bucharest")

app = Flask('')

@app.route('/')
def home():
    return "✅ Donul veghează. Botul este online."

def run_flask():
    app.run(host='0.0.0.0', port=8080)

def save_backup():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        for channel_id, tickets in TICKET_DATA.items():
            f.write(f"Canal: {channel_id}\n")
            for t in tickets:
                status = "activ" if not t['expired'] else "inactiv"
                taxa = "plătită" if t['paid'] else "neplătită"
                f.write(f"Contract {t['id']}: început la {t['start']}, terminat la {t['end']}, inițiat de {t['author']}, ID jucător: {t['player_id']}, status: {status}, taxă: {taxa}\n")
            f.write("\n")

def get_now(): return datetime.datetime.now(BUCHAREST_TZ)
def format_time(dt): return dt.strftime("%Y-%m-%d %H:%M:%S")
def parse_time(s): return BUCHAREST_TZ.localize(datetime.datetime.strptime(s, "%Y-%m-%d %H:%M:%S"))
def format_hour_only(s): return parse_time(s).strftime("%H:%M")
def time_remaining(end_str):
    remaining = parse_time(end_str) - get_now()
    if remaining.total_seconds() <= 0: return "expirat"
    h, m = divmod(int(remaining.total_seconds() // 60), 60)
    return f"{h}h {m}m"

@bot.event
async def on_ready():
    await bot.tree.sync()
    update_ticket_status.start()
    print("🤵 Botul mafiot este online!")

@bot.tree.command(name="ticket")
@app_commands.describe(player_id="ID-ul jucătorului")
async def ticket_command(interaction: Interaction, player_id: int):
    now = get_now()
    end = now + datetime.timedelta(hours=3)
    cid = str(interaction.channel_id)
    ticket_id = int(now.timestamp())
    if cid not in TICKET_DATA:
        TICKET_DATA[cid] = []
    ticket = {
        "id": ticket_id,
        "player_id": player_id,
        "start": format_time(now),
        "end": format_time(end),
        "author": interaction.user.name,
        "paid": False,
        "expired": False
    }
    TICKET_DATA[cid].append(ticket)
    save_backup()

    embed = discord.Embed(title=f"📄 Contract #{ticket_id}", color=discord.Color.dark_grey())
    embed.add_field(name="🧾 ID jucător", value=str(player_id), inline=True)
    embed.add_field(name="🕒 Start", value=format_hour_only(ticket['start']), inline=True)
    embed.add_field(name="⏳ Sfârșit", value=format_hour_only(ticket['end']), inline=True)
    embed.add_field(name="👤 Creat de", value=f"**{interaction.user.name}**", inline=False)
    embed.set_footer(text="💸 Taxă: neplătită.")

    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    ticket["message_id"] = msg.id
    save_backup()

@tasks.loop(minutes=60)
async def update_ticket_status():
    for channel_id, tickets in TICKET_DATA.items():
        for ticket in tickets:
            if not ticket['expired'] and get_now() >= parse_time(ticket['end']):
                ticket['expired'] = True
    save_backup()

# Pornește Flask + botul Discord
threading.Thread(target=run_flask).start()
bot.run(TOKEN)
