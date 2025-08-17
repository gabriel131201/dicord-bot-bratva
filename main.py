import os
import sys
import asyncio
import re
import discord
from discord.ext import tasks, commands
from discord import app_commands, Interaction
import datetime
import pytz
from flask import Flask
import threading
from collections import defaultdict

# === ROLURI PERMISE ===
LEADER_ROLE_ID = 1107100643291828224
COLEADER_ROLE_ID = 1107099637644529684
ALLOWED_ROLE_IDS = {LEADER_ROLE_ID, COLEADER_ROLE_ID}

# Verificare token
TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    print("❌ EROARE: DISCORD_TOKEN nu este setat! Verifică variabila de mediu în Railway.")
    sys.exit()
else:
    print("✅ Tokenul a fost găsit. Botul pornește.")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

DATA_FILE = "backup.txt"
TICKET_DATA = {}
BUCHAREST_TZ = pytz.timezone("Europe/Bucharest")

app = Flask('')

@app.route('/')
def home():
    return "✅ Donul veghează. Botul este online."

def run_flask():
    port = int(os.getenv("PORT", "8080"))
    app.run(host='0.0.0.0', port=port)

def save_backup():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        for channel_id, tickets in TICKET_DATA.items():
            f.write(f"Canal: {channel_id}\n")
            for t in tickets:
                status = "activ" if not t['expired'] else "inactiv"
                taxa = "plătită" if t['paid'] else "neplătită"
                deleted = "DA" if t.get('deleted') else "NU"
                deleted_by = t.get('deleted_by_name') or "-"
                # scriem pe scurt emoji-urile
                def fmt_meta(m):
                    if m.get("id"):
                        return f"{'a' if m.get('animated') else ''}:{m.get('name')}:{m.get('id')}"
                    return m.get("name") or "?"
                metas = t.get('emojis_meta') or []
                emojis_txt = ",".join(fmt_meta(m) for m in metas) if metas else "-"
                f.write(
                    f"Ticket {t['id']}: făcut la {t['start']}, terminat la {t['end']}, creat de {t['author']}, "
                    f"ID: {t['player_id']}, status: {status}, taxă: {taxa}, emojis:[{emojis_txt}], "
                    f"sters:{deleted}, sters_de:{deleted_by}\n"
                )
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

def is_leader_or_coleader(member: discord.Member) -> bool:
    return any(r.id in ALLOWED_ROLE_IDS for r in getattr(member, "roles", []))

# === CHECK PERMISIUNI SLASH ===
def role_check(interaction: Interaction) -> bool:
    if isinstance(interaction.user, discord.Member) and is_leader_or_coleader(interaction.user):
        return True
    raise app_commands.CheckFailure("Nu ai permisiunea pentru această comandă.")

# === HANDLER ERORI (permisiuni) ===
@bot.tree.error
async def on_app_command_error(interaction: Interaction, error):
    if isinstance(error, app_commands.CheckFailure):
        try:
            await interaction.response.send_message("❌ Nu ai permisiunea pentru această comandă.", ephemeral=True)
        except discord.InteractionResponded:
            await interaction.followup.send_message("❌ Nu ai permisiunea pentru această comandă.", ephemeral=True)

@bot.event
async def on_ready():
    try:
        # sincronizare pe fiecare guild ca să apară instant
        for g in bot.guilds:
            bot.tree.copy_global_to(guild=discord.Object(id=g.id))
            synced = await bot.tree.sync(guild=discord.Object(id=g.id))
            print(f"✅ Comenzi sincronizate pe {g.name}: {[c.name for c in synced]}")
        # (opțional) și global, ca fallback
        try:
            synced_global = await bot.tree.sync()
            print(f"🌐 Comenzi globale sincronizate: {[c.name for c in synced_global]}")
        except Exception as e2:
            print(f"Warn la sync global: {e2}")
    except Exception as e:
        print(f"Eroare la sync: {e}")
    update_ticket_status.start()  # rulează la 10 minute
    print("🤵 Botul mafiot este online!")

# --- UTIL: creăm meta din payload (id, name, animated) + cheie unică pentru set ---
def meta_from_partial(pe: discord.PartialEmoji):
    return {
        "id": pe.id,                # int sau None (unicode)
        "name": pe.name,            # nume sau caracter
        "animated": pe.animated     # True/False (doar custom)
    }

def key_from_meta(m):
    # grupăm pe ID dacă există, altfel pe unicode char
    return m["id"] if m.get("id") else ("U", m.get("name"))

# --- BIFE (oricine, orice emoji) — on_raw_reaction_add prinde și emoji externe/Nitro ---
@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    if payload.user_id == bot.user.id:
        return
    msg_id = payload.message_id
    for channel_id, tickets in TICKET_DATA.items():
        for ticket in tickets:
            if ticket.get("message_id") == msg_id:
                if ticket.get('deleted'):
                    return  # șters => ignorăm
                if not ticket.get("paid"):
                    ticket["paid"] = True
                # adăugăm meta în set unic per ticket
                metas = ticket.get("emojis_meta") or []
                keys = {key_from_meta(m) for m in metas}
                m = meta_from_partial(payload.emoji)
                k = key_from_meta(m)
                if k not in keys:
                    metas.append(m)
                ticket["emojis_meta"] = metas
                # compat vechi: ținem și vechiul câmp 'emojis' ca afișabil
                if m["id"]:
                    disp = f"<{'a' if m.get('animated') else ''}:{m.get('name')}:{m.get('id')}>"
                else:
                    disp = m.get("name")
                old = set(ticket.get("emojis", []))
                old.add(disp)
                ticket["emojis"] = list(old)
                save_backup()
                return

# --- MARCARE DELETE când se șterge mesajul ticketului direct din Discord ---
@bot.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    msg_id = payload.message_id
    for channel_id, tickets in TICKET_DATA.items():
        for ticket in tickets:
            if ticket.get("message_id") == msg_id and not ticket.get("deleted"):
                ticket["deleted"] = True
                ticket["deleted_at"] = format_time(get_now())
                ticket["deleted_by_id"] = None
                ticket["deleted_by_name"] = "necunoscut"
                try:
                    if payload.guild_id:
                        guild = bot.get_guild(payload.guild_id)
                        me = getattr(guild, "me", None) or guild.get_member(bot.user.id) if guild else None
                        if guild and me and me.guild_permissions.view_audit_log:
                            async for entry in guild.audit_logs(action=discord.AuditLogAction.message_delete, limit=5):
                                ch_ok = getattr(entry.extra, "channel", None)
                                if ch_ok and ch_ok.id == payload.channel_id:
                                    delta = datetime.datetime.now(datetime.timezone.utc) - entry.created_at
                                    if delta.total_seconds() <= 10:
                                        ticket["deleted_by_id"] = entry.user.id
                                        ticket["deleted_by_name"] = entry.user.display_name
                                        break
                except Exception:
                    pass
                save_backup()
                return

# ================= Comenzi =================

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
        "expired": False,
        "deleted": False,
        "deleted_by_id": None,
        "deleted_by_name": None,
        "deleted_at": None,
        "emojis_meta": [],   # listă de dicturi {id,name,animated}
        "emojis": []         # compat vechi (stringuri randabile)
    }
    TICKET_DATA[cid].append(ticket)
    save_backup()

    embed = discord.Embed(title=f"🎫 Ticket #{ticket_id}", color=0x00ff00)
    embed.add_field(name="👤 Jucător ID", value=str(player_id), inline=True)
    embed.add_field(name="⏱️ Start", value=format_hour_only(ticket['start']), inline=True)
    embed.add_field(name="🕒 Sfârșit", value=format_hour_only(ticket['end']), inline=True)
    embed.add_field(name="🤵‍♂️ Creat de", value=f"**{interaction.user.name}**", inline=False)
    embed.set_footer(text="Status taxă: neplătită • Poți bifa cu orice emoji (și Nitro)")
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
    active = [t for t in TICKET_DATA.get(cid, []) if not t['expired'] and not t.get('deleted')]
    if not active:
        await interaction.response.send_message("Nu există tickete active.", delete_after=120)
        return
    msg = "**🎟️ Tickete active:**\n"
    for t in active:
        taxa = "✅ plătită" if t['paid'] else "❌ neplătită"
        msg += f"🟢 ID: `{t['player_id']}` | **{t['author']}** | ⏱️ {format_hour_only(t['start'])}-{format_hour_only(t['end'])} | ⌛ {time_remaining(t['end'])} | Taxă: {taxa}\n"
    await interaction.response.send_message(msg, delete_after=120)

@bot.tree.command(name="status")
@app_commands.check(role_check)
async def status(interaction: Interaction):
    cid = str(interaction.channel_id)
    data = [t for t in TICKET_DATA.get(cid, []) if not t.get('deleted')]
    a, i = sum(not t['expired'] for t in data), sum(t['expired'] for t in data)
    await interaction.response.send_message(f"✅ Tickete active: {a}\n❌ Tickete inactive: {i}")

@bot.tree.command(name="today")
async def today(interaction: Interaction):
    cid = str(interaction.channel_id)
    azi = get_now().date()
    today = [t for t in TICKET_DATA.get(cid, []) if (parse_time(t['start']).date() == azi and not t.get('deleted'))]
    if not today:
        await interaction.response.send_message("Niciun ticket creat azi.", delete_after=120)
        return
    msg = "🗓️ **Tickete de azi:**\n"
    for t in today:
        taxa = "✅ plătită" if t['paid'] else "❌ neplătită"
        msg += f"🟢 ID: `{t['player_id']}` | **{t['author']}** | ⏱️ {format_hour_only(t['start'])} - {format_hour_only(t['end'])} | Taxă: {taxa}\n"
    await interaction.response.send_message(msg, delete_after=120)

@bot.tree.command(name="cauta")
@app_commands.describe(player_id="ID-ul jucătorului")
async def cauta(interaction: Interaction, player_id: int):
    cid = str(interaction.channel_id)
    tickets = [t for t in TICKET_DATA.get(cid, []) if t['player_id'] == player_id and not t.get('deleted')]
    if not tickets:
        await interaction.response.send_message(f"Nu am găsit tickete pentru `{player_id}`.", delete_after=120)
        return
    msg = f"🔍 Tickete pentru
