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
                f.write(f"Ticket {t['id']}: făcut la {t['start']}, terminat la {t['end']}, creat de {t['author']}, ID: {t['player_id']}, status: {status}, taxă: {taxa}\n")
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

@bot.event
async def on_reaction_add(reaction, user):
    if user.bot:
        return

    try:
        channel = reaction.message.channel
        msg_id = reaction.message.id
        print(f"[DEBUG] Reacție detectată de {user.name} pe mesaj ID {msg_id}")

        for channel_id, tickets in TICKET_DATA.items():
            for ticket in tickets:
                print(f"[DEBUG] Compar cu ticket {ticket['id']} -> msg_id salvat: {ticket.get('message_id')}")
                if ticket.get("message_id") == msg_id:
                    ticket["paid"] = True
                    print(f"[DEBUG] ✅ Taxă marcată ca plătită pentru ticket {ticket['id']}")
                    save_backup()
                    return
    except Exception as e:
        print(f"[EROARE on_reaction_add] {e}")

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

    embed = discord.Embed(title=f"🎫 Ticket #{ticket_id}", color=0x00ff00)
    embed.add_field(name="👤 Jucător ID", value=str(player_id), inline=True)
    embed.add_field(name="⏱️ Start", value=format_hour_only(ticket['start']), inline=True)
    embed.add_field(name="🕒 Sfârșit", value=format_hour_only(ticket['end']), inline=True)
    embed.add_field(name="🤵‍♂️ Creat de", value=f"**{interaction.user.name}**", inline=False)
    embed.set_footer(text="Status taxă: neplătită")
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    ticket["message_id"] = msg.id
    save_backup()

@bot.tree.command(name="tickets_reset", description="(comandă ascunsă)", extras={"hidden": True})
@app_commands.checks.has_permissions(administrator=True)
async def tickets_reset(interaction: Interaction):
    TICKET_DATA[str(interaction.channel_id)] = []
    save_backup()
    try:
        await interaction.response.send_message("✅", ephemeral=True)
    except:
        pass

@bot.tree.command(name="control")
async def control(interaction: Interaction):
    cid = str(interaction.channel_id)
    active = [t for t in TICKET_DATA.get(cid, []) if not t['expired']]
    if not active:
        await interaction.response.send_message("Nu există tickete active.")
        return
    msg = "**🎟️ Tickete active:**\n"
    for t in active:
        taxa = "✅ plătită" if t['paid'] else "❌ neplătită"
        msg += f"🟢 ID: `{t['player_id']}` | **{t['author']}** | ⏱️ {format_hour_only(t['start'])}-{format_hour_only(t['end'])} | ⌛ {time_remaining(t['end'])} | Taxă: {taxa}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="status")
async def status(interaction: Interaction):
    cid = str(interaction.channel_id)
    data = TICKET_DATA.get(cid, [])
    a, i = sum(not t['expired'] for t in data), sum(t['expired'] for t in data)
    await interaction.response.send_message(f"✅ Tickete active: {a}\n❌ Tickete inactive: {i}")

@bot.tree.command(name="today")
async def today(interaction: Interaction):
    cid = str(interaction.channel_id)
    azi = get_now().date()
    today = [t for t in TICKET_DATA.get(cid, []) if parse_time(t['start']).date() == azi]
    if not today:
        await interaction.response.send_message("Niciun ticket creat azi.")
        return
    msg = "📅 **Tickete de azi:**\n"
    for t in today:
        taxa = "✅ plătită" if t['paid'] else "❌ neplătită"
        msg += f"🟢 ID: `{t['player_id']}` | **{t['author']}** | ⏱️ {format_hour_only(t['start'])} - {format_hour_only(t['end'])} | Taxă: {taxa}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="cauta")
@app_commands.describe(player_id="ID-ul jucătorului")
async def cauta(interaction: Interaction, player_id: int):
    cid = str(interaction.channel_id)
    tickets = [t for t in TICKET_DATA.get(cid, []) if t['player_id'] == player_id]
    if not tickets:
        await interaction.response.send_message(f"Nu am găsit tickete pentru `{player_id}`.")
        return
    msg = f"🔍 Tickete pentru `{player_id}`:\n"
    for t in tickets:
        s = "✅ plătită" if t['paid'] else "❌ neplătită"
        c = "🟢 activ" if not t['expired'] else "🔴 inactiv"
        msg += f"{c} | ⏱️ {format_hour_only(t['start'])}-{format_hour_only(t['end'])} | 👤 **{t['author']}** | Taxă: {s}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="raport")
async def raport(interaction: Interaction):
    cid = str(interaction.channel_id)
    stats = defaultdict(lambda: {"platite": 0, "neplatite": 0, "total": 0})
    for t in TICKET_DATA.get(cid, []):
        a = stats[t['author']]
        a["total"] += 1
        a["platite" if t['paid'] else "neplatite"] += 1
    msg = "📋 **Raport lideri:**\n"
    for user, s in stats.items():
        msg += f"\n👤 **{user}**\n✅ Plătite: {s['platite']}\n❌ Neplatite: {s['neplatite']}\n📦 Total: {s['total']}\n"
    await interaction.response.send_message(msg)

@bot.tree.command(name="help", description="Afișează toate comenzile disponibile")
async def help_command(interaction: Interaction):
    msg = (
        "📘 **Comenzi disponibile:**\n"
        "\n`/ticket <ID>` - Creează un ticket de muncă pentru 3 ore"
        "\n`/control` - Afișează ticketele active din canal"
        "\n`/status` - Afișează câte tickete sunt active/inactive"
        "\n`/today` - Tickete create în ziua curentă"
        "\n`/cauta <ID>` - Caută tickete după ID"
        "\n`/raport` - Raport complet pentru lideri"
    )
    await interaction.response.send_message(msg)

@tasks.loop(minutes=60)
async def update_ticket_status():
    for channel_id, tickets in TICKET_DATA.items():
        for ticket in tickets:
            if not ticket['expired'] and get_now() >= parse_time(ticket['end']):
                ticket['expired'] = True
    save_backup()

# Pornire Flask + Bot
threading.Thread(target=run_flask).start()
bot.run(TOKEN)
