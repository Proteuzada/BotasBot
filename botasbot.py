import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import urllib.parse, urllib.request, re

class MusicView(discord.ui.View):
    def __init__(self, ctx, play_next_func):
        super().__init__()
        self.ctx = ctx
        self.play_next = play_next_func

    @discord.ui.button(emoji="⏸️", style=discord.ButtonStyle.secondary, label="")
    async def pause_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message("Música pausada!", ephemeral=True)
        else:
            await interaction.response.send_message("Nenhuma música está tocando!", ephemeral=True)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, label="")
    async def resume_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("Música continuada!", ephemeral=True)
        else:
            await interaction.response.send_message("Nenhuma música está pausada!", ephemeral=True)

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, label="")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_connected():
            voice_client.stop()
            await voice_client.disconnect()
            await interaction.response.send_message("Música parada e bot desconectado!", ephemeral=True)
        else:
            await interaction.response.send_message("O bot não está conectado a nenhum canal de voz!", ephemeral=True)

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, label="")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()  # Para a música atual
            await self.ctx.send("Pulado para a próxima música!")
            await self.play_next(self.ctx)  # Pula para a próxima música
            await interaction.response.send_message("Música pulada!", ephemeral=True)
        else:
            await interaction.response.send_message("Não há nenhuma música tocando para pular!", ephemeral=True)

def run_bot():
    load_dotenv()
    TOKEN = os.getenv('DISCORD_TOKEN')
    
    if not TOKEN:
        raise ValueError("O token do bot não foi definido corretamente. Verifique o .env ou a variável de ambiente.")

    intents = discord.Intents.default()
    intents.message_content = True
    client = commands.Bot(command_prefix=".", intents=intents)

    queues = {}
    voice_clients = {}
    youtube_base_url = 'https://www.youtube.com/'
    youtube_results_url = youtube_base_url + 'results?'
    youtube_watch_url = youtube_base_url + 'watch?v='
    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn -filter:a "volume=0.25"'}

    @client.event
    async def on_ready():
        print(f'{client.user} Está Rodando')

    async def play_next(ctx):
        if queues.get(ctx.guild.id):
            link = queues[ctx.guild.id].pop(0)
            await play(ctx, link=link)
        else:
            await ctx.send("A fila está vazia!")

    @client.command(name="play")
    async def play(ctx, *, link):
        try:
            # Conecta ao canal de voz se o bot ainda não estiver conectado
            if ctx.guild.id not in voice_clients or not ctx.voice_client:
                voice_client = await ctx.author.voice.channel.connect()
                voice_clients[voice_client.guild.id] = voice_client
            else:
                voice_client = voice_clients[ctx.guild.id]

            # Verifica se uma música já está tocando
            if voice_client.is_playing():
                # Se estiver tocando, adiciona à fila
                if ctx.guild.id not in queues:
                    queues[ctx.guild.id] = []
                queues[ctx.guild.id].append(link)
                await ctx.send("Adicionado à fila!")
            else:
                # Se não estiver tocando, começa a tocar a música
                if youtube_base_url not in link:
                    query_string = urllib.parse.urlencode({
                        'search_query': link
                    })

                    content = urllib.request.urlopen(
                        youtube_results_url + query_string
                    )

                    search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())

                    link = youtube_watch_url + search_results[0]

                loop = asyncio.get_event_loop()
                data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))

                song = data['url']
                player = discord.FFmpegOpusAudio(song, **ffmpeg_options)

                voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))

                # Enviar botões de controle após iniciar a música
                view = MusicView(ctx, play_next)
                await ctx.send(f'Tocando agora: {data["title"]}', view=view)

        except Exception as e:
            print(e)

    @client.command(name="queue")
    async def queue(ctx, *, url):
        if ctx.guild.id not in queues:
            queues[ctx.guild.id] = []
        queues[ctx.guild.id].append(url)
        await ctx.send("Adicionado à fila!")

    @client.command(name="skip")
    async def skip(ctx):
        voice_client = ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()  # Para a música atual
            await play_next(ctx)  # Pula para a próxima música
            await ctx.send("Pulado para a próxima música!")
        else:
            await ctx.send("Não há nenhuma música tocando para pular.")

    client.run(TOKEN)
