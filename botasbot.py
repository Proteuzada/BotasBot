import discord
from discord.ext import commands, tasks
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import subprocess
import urllib.parse, urllib.request, re

class MusicView(discord.ui.View):
    def __init__(self, ctx, play_next_func, thumbnail_url=None, title="", song_path=None):
        super().__init__()
        self.ctx = ctx
        self.play_next = play_next_func
        self.thumbnail_url = thumbnail_url
        self.title = title
        self.song_path = song_path

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

    @discord.ui.button(emoji="⏹️", style=discord.ButtonStyle.secondary, label="")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
            await voice_client.disconnect()
            await interaction.response.send_message("Música parada e bot desconectado!", ephemeral=True)
            
            if self.song_path and os.path.exists(self.song_path):
                try:
                    os.remove(self.song_path)  # Deleta a música baixada após parar
                    print(f"{self.title} foi removida após a parada.")
                except Exception as e:
                    print(f"Erro ao tentar remover {self.title}: {e}")

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, label="")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await self.ctx.send("Pulado para a próxima música!")
            await self.play_next(self.ctx)
            await interaction.response.send_message("Música pulada!", ephemeral=True)
            
            if self.song_path and os.path.exists(self.song_path):
                try:
                    os.remove(self.song_path)  # Deleta a música baixada após pular
                    print(f"{self.title} foi removida após ser pulada.")
                except Exception as e:
                    print(f"Erro ao tentar remover {self.title}: {e}")

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
        inactivity_check.start()

    @tasks.loop(minutes=1)
    async def inactivity_check():
        for vc in client.voice_clients:
            if not vc.is_playing() and not vc.is_paused():
                await vc.disconnect()

    async def play_next(ctx):
        if queues.get(ctx.guild.id):
            link = queues[ctx.guild.id].pop(0)
            await play(ctx, link=link)

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
                thumbnail_url = None
                title = ""
                song_path = None

                # Se o link for do Spotify, baixa a música usando SpotDL
                if "spotify.com" in link:
                    loop = asyncio.get_event_loop()
                    output_dir = os.path.join(os.getcwd(), "downloads")
                    os.makedirs(output_dir, exist_ok=True)
                    spotdl_command = f"spotdl {link} --output {output_dir}"
                    process = await loop.run_in_executor(None, lambda: subprocess.run(spotdl_command, shell=True))

                    # Verifique se o download foi bem-sucedido
                    downloaded_files = os.listdir(output_dir)
                    if not downloaded_files:
                        await ctx.send("Erro ao baixar a música.")
                        return

                    # Pega o arquivo baixado e toca a música
                    song_path = os.path.join(output_dir, downloaded_files[0])
                    title = os.path.splitext(downloaded_files[0])[0]  # Remove a extensão do título
                    player = discord.FFmpegPCMAudio(song_path)
                    voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))

                # Se o link for do YouTube, use o yt-dlp para tocar a música
                elif "youtube.com" in link or "youtu.be" in link:
                    loop = asyncio.get_event_loop()
                    data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))

                    song = data['url']
                    title = data['title']
                    thumbnail_url = data.get('thumbnail')
                    player = discord.FFmpegOpusAudio(song, **ffmpeg_options)
                    voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))
                
                # Se for uma pesquisa ou um link desconhecido, assume que é uma pesquisa no YouTube
                else:
                    query_string = urllib.parse.urlencode({'search_query': link})
                    content = urllib.request.urlopen(youtube_results_url + query_string)
                    search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
                    if search_results:
                        link = youtube_watch_url + search_results[0]
                        loop = asyncio.get_event_loop()
                        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))

                        song = data['url']
                        title = data['title']
                        thumbnail_url = data.get('thumbnail')
                        player = discord.FFmpegOpusAudio(song, **ffmpeg_options)
                        voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))
                    else:
                        await ctx.send("Nenhum resultado encontrado no YouTube.")
                        return

                # Enviar embed com preview da música e botões de controle após iniciar a música
                view = MusicView(ctx, play_next, thumbnail_url, title, song_path)
                embed = discord.Embed(title="Tocando agora", description=title, color=discord.Color.blue())
                if thumbnail_url:
                    embed.set_thumbnail(url=thumbnail_url)
                await ctx.send(embed=embed, view=view)

        except Exception as e:
            print(f"Erro ao tentar tocar a música: {e}")

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
            voice_client.stop()
            await play_next(ctx)
            await ctx.send("Pulado para a próxima música!")

    @client.command(name="clearqueue")
    async def clearqueue(ctx):
        if ctx.guild.id in queues:
            queues[ctx.guild.id].clear()
        await ctx.send("Fila limpa!")

    client.run(TOKEN)
