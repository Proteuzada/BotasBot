import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import subprocess
import urllib.parse, urllib.request, re
from asyncio import Lock

class MusicView(discord.ui.View):
    def __init__(self, ctx, play_next_func, thumbnail_url=None, title="", song_path=None):
        super().__init__()
        self.ctx = ctx
        self.play_next = play_next_func
        self.thumbnail_url = thumbnail_url
        self.title = title
        self.song_path = song_path

    async def delete_song_file(self):
        if self.song_path and os.path.exists(self.song_path):
            try:
                os.remove(self.song_path)
                print(f"{self.title} foi removida.")
            except Exception as e:
                print(f"Erro ao tentar remover {self.title}: {e}")

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
            await self.delete_song_file()

    @discord.ui.button(emoji="⏭️", style=discord.ButtonStyle.secondary, label="")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        voice_client = self.ctx.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.stop()  # Para a música atual
            await self.ctx.send("Pulado para a próxima música!")
            await self.play_next(self.ctx)  # Pula para a próxima música
            try:
                await interaction.response.send_message("Música pulada!", ephemeral=True)
            except discord.errors.NotFound:
                print("A interação não foi encontrada ou já expirou.")
            await self.delete_song_file()

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
    download_lock = Lock()  # Criação do Lock para controlar os downloads
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

    @client.command(name="play")
    @commands.cooldown(1, 25, commands.BucketType.user)
    async def play(ctx, *, link):
        async with download_lock:  # Garante que apenas um download ocorra por vez
            try:
                voice_client = ctx.voice_client
                if ctx.guild.id not in voice_clients or not voice_client:
                    voice_client = await ctx.author.voice.channel.connect()
                    voice_clients[ctx.guild.id] = voice_client
                else:
                    voice_client = voice_clients[ctx.guild.id]

                if voice_client.is_playing() or voice_client.is_paused():
                    # Adiciona à fila se uma música já está tocando ou pausada
                    if ctx.guild.id not in queues:
                        queues[ctx.guild.id] = []
                    queues[ctx.guild.id].append(link)
                    await ctx.send(f"Adicionado à fila: {link}")
                else:
                    # Reproduz a música imediatamente se nada estiver tocando
                    await start_playback(ctx, link, voice_client)

            except commands.CommandOnCooldown as e:
                await ctx.send(f"Por favor, aguarde {e.retry_after:.1f} segundos antes de usar o comando `.play` novamente.")
            except Exception as e:
                await ctx.send(f"Erro ao tentar tocar a música: {e}")

    async def start_playback(ctx, link, voice_client):
        thumbnail_url = None
        title = ""
        song_path = None

        if "spotify.com" in link:
            output_dir = os.path.join(os.getcwd(), "downloads")
            os.makedirs(output_dir, exist_ok=True)
            spotdl_command = f"spotdl {link} --output {output_dir}"
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: subprocess.run(spotdl_command, shell=True))

            downloaded_files = os.listdir(output_dir)
            if not downloaded_files:
                await ctx.send("Erro ao baixar a música.")
                return

            song_path = os.path.join(output_dir, downloaded_files[0])
            title = os.path.splitext(downloaded_files[0])[0]
            player = discord.FFmpegPCMAudio(song_path)
            voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))

        elif "youtube.com" in link or "youtu.be" in link:
            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))

            song = data['url']
            title = data['title']
            thumbnail_url = data.get('thumbnail')
            player = discord.FFmpegOpusAudio(song, **ffmpeg_options)
            voice_client.play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))
        
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

        view = MusicView(ctx, play_next, thumbnail_url, title, song_path)
        embed = discord.Embed(title="Tocando agora", description=title, color=discord.Color.blue())
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        await ctx.send(embed=embed, view=view)

    @client.command(name="queue")
    async def queue(ctx, *, url):
        if ctx.guild.id not in queues:
            queues[ctx.guild.id] = []
        queues[ctx.guild.id].append(url)
        await ctx.send(f"Adicionado à fila: {url}")

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

    @play.error
    async def play_error(ctx, error):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"Por favor, aguarde {error.retry_after:.1f} segundos antes de usar o comando `.play` novamente.")
        else:
            await ctx.send(f"Ocorreu um erro: {error}")

    client.run(TOKEN)
