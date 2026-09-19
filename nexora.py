import discord
from discord.ext import commands
from discord import app_commands
import json
import os
import io
from datetime import timedelta, datetime
from PIL import Image, ImageDraw, ImageFont
import urllib.request
import asyncio

# ==========================================
# CONFIGURAÇÃO E PERSISTÊNCIA DE DADOS
# ==========================================

CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({}, f, indent=4)
        return {}
    
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def save_config(config_data):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=4)

config = load_config()

def get_guild_config(guild_id: int):
    gid = str(guild_id)
    if gid not in config:
        config[gid] = {
            "welcome_channel_id": None,
            "leave_channel_id": None,
            "log_channel_id": None,
            "ticket_category_id": None,
            "welcome_enabled": True,
            "leave_enabled": True,
            "antispam_enabled": True,
            "welcome_message": "# 🚀 SEJA BEM-VINDO(A) AO NOSSO SERVIDOR!\n\nOlá {user}, é um prazer enorme ter-te connosco!\n\n📌 **REGRAS E DICAS:**\n• Lê as regras para evitar punições.\n• Explora os nossos canais de texto e voz.\n• Atualmente somos **{count} membros** na comunidade!\n\nAproveita a tua estadia! ✨",
            "leave_message": "# 👋 UM MEMBRO SAIU DO SERVIDOR\n\nO utilizador **{user}** decidiu deixar a comunidade.\n\nAtualmente somos **{count} membros**.",
            "welcome_card_text": "BEM-VINDO(A)!",
            "leave_card_text": "ATÉ LOGO!"
        }
        save_config(config)
    return config[gid]

# ==========================================
# INICIALIZAÇÃO DO BOT
# ==========================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(TicketPanelView())
        self.add_view(TicketCloseView())
        await self.tree.sync()

bot = Bot()

COLOR_BLACK = 0x0F0F0F
COLOR_GRAY = 0x2A2A2A
COLOR_WHITE = 0xFFFFFF

# Controle do Anti-Spam (Memória temporária)
user_message_logs = {}

# ==========================================
# GERAÇÃO DE CARDS COM PILLOW
# ==========================================

async def create_member_card(member: discord.Member, title: str, subtitle: str) -> discord.File:
    width, height = 700, 250
    card = Image.new("RGB", (width, height), color="#0F0F0F")
    draw = ImageDraw.Draw(card)
    
    draw.rectangle([5, 5, width - 6, height - 6], outline="#FFFFFF", width=2)

    avatar_url = member.display_avatar.with_format("png").url
    req = urllib.request.Request(avatar_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        avatar_data = response.read()
    
    avatar_img = Image.open(io.BytesIO(avatar_data)).convert("RGBA")
    avatar_img = avatar_img.resize((140, 140))

    mask = Image.new("L", (140, 140), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.ellipse((0, 0, 140, 140), fill=255)
    
    card.paste(avatar_img, (50, 55), mask)

    font_large = ImageFont.load_default()
    font_medium = ImageFont.load_default()
    font_small = ImageFont.load_default()

    draw.text((220, 60), title.upper(), fill="#FFFFFF", font=font_large)
    draw.text((220, 100), member.display_name, fill="#E0E0E0", font=font_medium)
    draw.text((220, 140), f"Servidor: {member.guild.name}", fill="#888888", font=font_small)
    draw.text((220, 165), subtitle, fill="#AAAAAA", font=font_small)

    buffer = io.BytesIO()
    card.save(buffer, format="PNG")
    buffer.seek(0)
    return discord.File(buffer, filename="card.png")

# ==========================================
# UTILS & LOGS
# ==========================================

async def send_log(guild: discord.Guild, embed: discord.Embed):
    guild_cfg = get_guild_config(guild.id)
    log_channel_id = guild_cfg.get("log_channel_id")
    if log_channel_id:
        channel = guild.get_channel(log_channel_id)
        if channel:
            await channel.send(embed=embed)

# ==========================================
# EVENTOS (ENTRADA, SAÍDA E ANTI-SPAM)
# ==========================================

@bot.event
async def on_ready():
    print(f"BOT inicializado com sucesso como {bot.user}")

@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    guild_cfg = get_guild_config(message.guild.id)
    
    # Lógica Anti-Spam
    if guild_cfg.get("antispam_enabled", True) and not message.author.guild_permissions.administrator:
        user_id = message.author.id
        now = datetime.now()
        
        if user_id not in user_message_logs:
            user_message_logs[user_id] = []
        
        user_message_logs[user_id].append(now)
        user_message_logs[user_id] = [t for t in user_message_logs[user_id] if now - t < timedelta(seconds=3)]
        
        if len(user_message_logs[user_id]) > 4:
            user_message_logs[user_id] = []
            try:
                await message.author.timeout(timedelta(minutes=5), reason="Anti-Spam Automático")
                await message.channel.send(f"⚠️ {message.author.mention} foi silenciado por 5 minutos por enviar mensagens muito rápido.", delete_after=10)
                
                log_embed = discord.Embed(
                    title="Anti-Spam — Timeout Aplicado",
                    description=f"**Membro:** {message.author.mention}\n**Ação:** Silenciado por 5 minutos devido a spam.",
                    color=COLOR_WHITE,
                    timestamp=datetime.now()
                )
                await send_log(message.guild, log_embed)
            except Exception:
                pass

    await bot.process_commands(message)

@bot.event
async def on_member_join(member: discord.Member):
    guild_cfg = get_guild_config(member.guild.id)
    
    if not guild_cfg["welcome_enabled"]:
        return
    
    channel_id = guild_cfg.get("welcome_channel_id")
    if not channel_id:
        return
        
    channel = member.guild.get_channel(channel_id)
    if not channel:
        return

    text = guild_cfg["welcome_message"].format(
        user=member.mention,
        count=member.guild.member_count
    )
    
    file = await create_member_card(
        member, 
        guild_cfg["welcome_card_text"], 
        f"Somos {member.guild.member_count} membros!"
    )

    embed = discord.Embed(
        description=text,
        color=COLOR_WHITE
    )
    # Define o avatar do membro em tamanho médio abaixo da mensagem
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url="attachment://card.png")

    await channel.send(content=member.mention, embed=embed, file=file)

    log_embed = discord.Embed(
        title="Entrada de Membro",
        description=f"**Membro:** {member.mention} ({member.id})",
        color=COLOR_WHITE,
        timestamp=datetime.now()
    )
    log_embed.set_thumbnail(url=member.display_avatar.url)
    await send_log(member.guild, log_embed)

@bot.event
async def on_member_remove(member: discord.Member):
    guild_cfg = get_guild_config(member.guild.id)
    
    if not guild_cfg["leave_enabled"]:
        return
    
    channel_id = guild_cfg.get("leave_channel_id")
    if not channel_id:
        return
        
    channel = member.guild.get_channel(channel_id)
    if not channel:
        return

    text = guild_cfg["leave_message"].format(
        user=member.display_name,
        count=member.guild.member_count
    )

    file = await create_member_card(
        member, 
        guild_cfg["leave_card_text"], 
        f"Agora somos {member.guild.member_count} membros."
    )

    embed = discord.Embed(
        description=text,
        color=COLOR_WHITE
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_image(url="attachment://card.png")

    await channel.send(embed=embed, file=file)

    log_embed = discord.Embed(
        title="Saída de Membro",
        description=f"**Membro:** {member.name} ({member.id})",
        color=COLOR_GRAY,
        timestamp=datetime.now()
    )
    log_embed.set_thumbnail(url=member.display_avatar.url)
    await send_log(member.guild, log_embed)

# ==========================================
# SISTEMA DE TICKETS DE SUPORTE
# ==========================================

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Fechar Ticket", style=discord.ButtonStyle.danger, custom_id="close_ticket_btn")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("O ticket será fechado em 5 segundos...", ephemeral=False)
        
        log_embed = discord.Embed(
            title="Ticket Fechado",
            description=f"**Canal:** {interaction.channel.name}\n**Fechado por:** {interaction.user.mention}",
            color=COLOR_WHITE,
            timestamp=datetime.now()
        )
        await send_log(interaction.guild, log_embed)
        
        await asyncio.sleep(5)
        await interaction.channel.delete()

class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir Ticket", style=discord.ButtonStyle.primary, emoji="📩", custom_id="open_ticket_btn")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_cfg = get_guild_config(interaction.guild.id)
        category_id = guild_cfg.get("ticket_category_id")
        category = interaction.guild.get_channel(category_id) if category_id else None

        channel_name = f"ticket-{interaction.user.name}".lower().replace(" ", "-")
        
        # Verifica se já existe um ticket aberto com este nome
        existing_channel = discord.utils.get(interaction.guild.channels, name=channel_name)
        if existing_channel:
            return await interaction.response.send_message(f"Já tens um ticket aberto em {existing_channel.mention}!", ephemeral=True)

        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
            interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            interaction.guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)
        }

        ticket_channel = await interaction.guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            reason=f"Ticket criado por {interaction.user.name}"
        )

        embed = discord.Embed(
            title="🎫 Atendimento e Suporte",
            description=f"Olá {interaction.user.mention}, bem-vindo(a) ao teu ticket!\nDescreve o teu problema ou dúvida em pormenor. Um moderador irá atender-te em breve.",
            color=COLOR_WHITE
        )
        await ticket_channel.send(content=f"{interaction.user.mention}", embed=embed, view=TicketCloseView())
        await interaction.response.send_message(f"Ticket criado com sucesso em {ticket_channel.mention}!", ephemeral=True)

# ==========================================
# PAINEL ADMINISTRATIVO (INTERFACE)
# ==========================================

class ConfigModal(discord.ui.Modal, title="Personalização de Textos"):
    def __init__(self, guild_cfg: dict):
        super().__init__()
        self.guild_cfg = guild_cfg

        self.welcome_msg = discord.ui.TextInput(
            label="Mensagem de Boas-vindas",
            style=discord.TextStyle.paragraph,
            default=guild_cfg.get("welcome_message", ""),
            required=True
        )
        self.leave_msg = discord.ui.TextInput(
            label="Mensagem de Despedida",
            style=discord.TextStyle.paragraph,
            default=guild_cfg.get("leave_message", ""),
            required=True
        )
        self.welcome_card = discord.ui.TextInput(
            label="Texto do Card de Boas-vindas",
            style=discord.TextStyle.short,
            default=guild_cfg.get("welcome_card_text", "Bem-vindo(a)!"),
            required=True
        )
        self.leave_card = discord.ui.TextInput(
            label="Texto do Card de Despedida",
            style=discord.TextStyle.short,
            default=guild_cfg.get("leave_card_text", "Até logo!"),
            required=True
        )

        self.add_item(self.welcome_msg)
        self.add_item(self.leave_msg)
        self.add_item(self.welcome_card)
        self.add_item(self.leave_card)

    async def on_submit(self, interaction: discord.Interaction):
        guild_cfg = get_guild_config(interaction.guild.id)
        guild_cfg["welcome_message"] = self.welcome_msg.value
        guild_cfg["leave_message"] = self.leave_msg.value
        guild_cfg["welcome_card_text"] = self.welcome_card.value
        guild_cfg["leave_card_text"] = self.leave_card.value
        save_config(config)

        log_embed = discord.Embed(
            title="Configuração Alterada",
            description=f"Textos do sistema atualizados por {interaction.user.mention}",
            color=COLOR_WHITE,
            timestamp=datetime.now()
        )
        await send_log(interaction.guild, log_embed)

        await interaction.response.send_message("Configurações atualizadas com sucesso!", ephemeral=True)

class ConfigControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Alternar Entrada", style=discord.ButtonStyle.secondary, custom_id="toggle_welcome")
    async def toggle_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_cfg = get_guild_config(interaction.guild.id)
        guild_cfg["welcome_enabled"] = not guild_cfg["welcome_enabled"]
        save_config(config)
        await interaction.response.send_message(f"Sistema de entrada: **{'Ativado' if guild_cfg['welcome_enabled'] else 'Desativado'}**", ephemeral=True)

    @discord.ui.button(label="Alternar Anti-Spam", style=discord.ButtonStyle.secondary, custom_id="toggle_antispam")
    async def toggle_antispam(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_cfg = get_guild_config(interaction.guild.id)
        guild_cfg["antispam_enabled"] = not guild_cfg.get("antispam_enabled", True)
        save_config(config)
        await interaction.response.send_message(f"Sistema Anti-Spam: **{'Ativado' if guild_cfg['antispam_enabled'] else 'Desativado'}**", ephemeral=True)

    @discord.ui.button(label="Editar Textos", style=discord.ButtonStyle.primary, custom_id="edit_texts")
    async def edit_texts(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild_cfg = get_guild_config(interaction.guild.id)
        await interaction.response.send_modal(ConfigModal(guild_cfg))

    @discord.ui.button(label="Enviar Painel Ticket", style=discord.ButtonStyle.success, custom_id="send_ticket_panel")
    async def send_ticket_panel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📩 Central de Suporte e Atendimento",
            description="Precisa de ajuda ou pretende entrar em contacto com a nossa equipa?\nClique no botão abaixo para abrir um ticket privado.",
            color=COLOR_WHITE
        )
        await interaction.channel.send(embed=embed, view=TicketPanelView())
        await interaction.response.send_message("Painel de Ticket enviado no canal!", ephemeral=True)

@bot.tree.command(name="painel", description="Abre o painel de configuração do BOT")
@app_commands.checks.has_permissions(administrator=True)
async def painel(interaction: discord.Interaction):
    guild_cfg = get_guild_config(interaction.guild.id)
    
    embed = discord.Embed(
        title="Painel de Configuração",
        description="Gerencie os sistemas automatizados de entrada, saída, suporte e moderação.",
        color=COLOR_WHITE
    )
    
    welcome_ch = f"<#{guild_cfg['welcome_channel_id']}>" if guild_cfg['welcome_channel_id'] else "Não definido"
    leave_ch = f"<#{guild_cfg['leave_channel_id']}>" if guild_cfg['leave_channel_id'] else "Não definido"
    log_ch = f"<#{guild_cfg['log_channel_id']}>" if guild_cfg['log_channel_id'] else "Não definido"

    embed.add_field(name="Canais", value=f"**Boas-vindas:** {welcome_ch}\n**Despedida:** {leave_ch}\n**Logs:** {log_ch}", inline=False)
    embed.add_field(name="Status", value=f"**Entrada:** {'Ativado' if guild_cfg['welcome_enabled'] else 'Desativado'}\n**Anti-Spam:** {'Ativado' if guild_cfg.get('antispam_enabled', True) else 'Desativado'}", inline=False)

    await interaction.response.send_message(embed=embed, view=ConfigControlView(), ephemeral=True)

@bot.tree.command(name="set_canal", description="Define os canais e categorias do sistema")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(tipo=[
    app_commands.Choice(name="Boas-vindas", value="welcome"),
    app_commands.Choice(name="Despedida", value="leave"),
    app_commands.Choice(name="Logs", value="log")
])
async def set_canal(interaction: discord.Interaction, tipo: str, canal: discord.TextChannel):
    guild_cfg = get_guild_config(interaction.guild.id)
    
    if tipo == "welcome":
        guild_cfg["welcome_channel_id"] = canal.id
    elif tipo == "leave":
        guild_cfg["leave_channel_id"] = canal.id
    elif tipo == "log":
        guild_cfg["log_channel_id"] = canal.id
    
    save_config(config)
    await interaction.response.send_message(f"Canal de **{tipo}** definido para {canal.mention}.", ephemeral=True)

@bot.tree.command(name="set_categoria_ticket", description="Define a categoria onde os tickets serão criados")
@app_commands.checks.has_permissions(administrator=True)
async def set_categoria_ticket(interaction: discord.Interaction, categoria: discord.CategoryChannel):
    guild_cfg = get_guild_config(interaction.guild.id)
    guild_cfg["ticket_category_id"] = categoria.id
    save_config(config)
    await interaction.response.send_message(f"Categoria de tickets definida para **{categoria.name}**.", ephemeral=True)

# ==========================================
# EXECUÇÃO DO BOT
# ==========================================

if __name__ == "__main__":
    bot.run(os.environ.get("DISCORD_TOKEN"))
