import os
import asyncio
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
import yt_dlp

app = FastAPI()

# Dicionário global para armazenar o status do download
download_status = {"status": "idle", "percentage": 0, "title": "", "phase": ""}

def ytdlp_hook(d):
    """Gancho de progresso para o yt-dlp com detecção de fluxo."""
    global download_status
    
    info = d.get('info_dict', {})
    vcodec = info.get('vcodec', 'none')
    acodec = info.get('acodec', 'none')
    has_video = vcodec and vcodec != 'none'
    has_audio = acodec and acodec != 'none'
    
    if has_video and not has_audio:
        download_status["phase"] = "video stream"
    elif has_audio and not has_video:
        download_status["phase"] = "audio stream"
    
    if d['status'] == 'downloading':
        download_status["status"] = "downloading"
        
        if '_percent_str' in d:
            pct_str = d['_percent_str'].replace('%', '').strip()
            try:
                download_status["percentage"] = float(pct_str)
                return
            except ValueError:
                pass
                
        total_bytes = d.get('total_bytes') or d.get('total_bytes_estimate')
        downloaded_bytes = d.get('downloaded_bytes', 0)
        
        if total_bytes and total_bytes > 0:
            percentage = (downloaded_bytes / total_bytes) * 100
            download_status["percentage"] = round(percentage, 1)

    elif d['status'] == 'finished':
        download_status["status"] = "processing"
        download_status["percentage"] = 100

# HTML Atualizado com Tema Escuro Moderno e elegante
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LEO MDZ YT CONVERTER</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0f0f0f; color: #f1f1f1; display: flex; justify-content: center; align-items: center; min-height: 100vh; padding: 20px; }
        .card { background: #1f1f1f; width: 100%; max-width: 500px; padding: 35px; border-radius: 16px; box-shadow: 0 8px 32px rgba(0, 0, 0, 0.5); border: 1px solid #2f2f2f; }
        h2 { color: #fff; text-align: center; margin-bottom: 25px; font-size: 24px; letter-spacing: 0.5px; }
        label { display: block; margin-bottom: 8px; color: #aaa; font-size: 14px; font-weight: 500; }
        input[type="text"], select { width: 100%; padding: 14px; margin-bottom: 20px; border: 1px solid #333; border-radius: 8px; background-color: #2d2d2d; color: #fff; font-size: 15px; transition: border-color 0.3s; }
        input[type="text"]:focus, select:focus { outline: none; border-color: #ff0000; }
        button { width: 100%; padding: 14px; background-color: #ff0000; color: white; border: none; border-radius: 8px; cursor: pointer; font-size: 16px; font-weight: bold; transition: background 0.3s, transform 0.1s; }
        button:hover { background-color: #cc0000; }
        button:active { transform: scale(0.98); }
        button:disabled { background-color: #555; cursor: not-allowed; }
        
        /* Custom Progress Bar */
        #progress-container { display: none; margin-top: 30px; }
        .progress-box { width: 100%; background-color: #333; border-radius: 10px; overflow: hidden; height: 12px; }
        .progress-bar { width: 0%; height: 100%; background-color: #ff0000; transition: width 0.3s ease, background-color 0.3s; }
        #status-text { text-align: center; font-weight: 500; margin-top: 12px; color: #ddd; font-size: 14px; }
    </style>
</head>
<body>
    <div class="card">
        <h2>🚀 LEO MDZ YT CONVERTER</h2>
        <form id="downloadForm">
            <label>URL do YouTube:</label>
            <input type="text" id="url" name="url" placeholder="https://www.youtube.com/watch?v=..." required>
            
            <label>Opções de Download:</label>
            <select id="quality" name="quality">
                <option value="bestvideo+bestaudio/best">Vídeo na Máxima Qualidade</option>
                <option value="bestaudio/best">Apenas Áudio (Melhor Qualidade MP3)</option>
                <option value="worst">Vídeo em Baixa Qualidade (Economizar Espaço)</option>
            </select>
            
            <button type="submit" id="submitBtn">Iniciar Download</button>
        </form>

        <div id="progress-container">
            <div class="progress-box">
                <div id="progressBar" class="progress-bar"></div>
            </div>
            <div id="status-text">Iniciando... 0%</div>
        </div>
    </div>

    <script>
        document.getElementById('downloadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = new FormData(e.target);
            document.getElementById('submitBtn').disabled = true;
            document.getElementById('progress-container').style.display = 'block';
            
            const progressBar = document.getElementById('progressBar');
            const statusText = document.getElementById('status-text');
            
            progressBar.style.width = '0%';
            progressBar.style.backgroundColor = '#ff0000';
            statusText.innerText = 'Conectando ao servidor...';

            fetch('/download', { method: 'POST', body: formData });

            const eventSource = new EventSource('/progress-stream');
            
            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);

                if (data.status === 'downloading') {
                    progressBar.style.width = data.percentage + '%';
                    let label = 'Baixando';
                    if (data.phase === 'video stream') label = 'Baixando arquivo de vídeo';
                    else if (data.phase === 'audio stream') label = 'Baixando arquivo de áudio';
                    statusText.innerText = label + ': ' + data.percentage + '%';
                } else if (data.status === 'processing') {
                    progressBar.style.width = '100%';
                    progressBar.style.backgroundColor = '#2196f3';
                    statusText.innerText = 'Mesclando áudio e vídeo... Por favor, aguarde.';
                } else if (data.status === 'finished') {
                    progressBar.style.backgroundColor = '#4caf50';
                    statusText.innerText = 'Pronto! Download concluído com sucesso.';
                    eventSource.close();
                    document.getElementById('submitBtn').disabled = false;
                } else if (data.status === 'error') {
                    progressBar.style.backgroundColor = '#f44336';
                    statusText.innerText = 'Erro: Falha ao realizar o download.';
                    eventSource.close();
                    document.getElementById('submitBtn').disabled = false;
                }
            };
        });
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    return HTML_TEMPLATE

@app.post("/download")
async def start_download(url: str = Form(...), quality: str = Form(...)):
    global download_status
    download_status = {"status": "starting", "percentage": 0, "title": "", "phase": "starting"}
    
    # Cria a pasta de downloads no servidor do Railway se ela não existir
    download_folder = os.path.join(os.getcwd(), "downloads")
    os.makedirs(download_folder, exist_ok=True)

    if quality == "bestaudio/best":
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
            'progress_hooks': [ytdlp_hook],
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
        }
    else:
        if quality == "worst":
            ydl_opts = {
                'format': 'worst',
                'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
                'progress_hooks': [ytdlp_hook],
            }
        else:
            ydl_opts = {
                'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                'merge_output_format': 'mp4',
                'outtmpl': os.path.join(download_folder, '%(title)s.%(ext)s'),
                'progress_hooks': [ytdlp_hook],
            }

    def run():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            download_status["status"] = "finished"
        except Exception as e:
            print(f"Erro interno no yt-dlp: {str(e)}")
            download_status["status"] = "error"
            download_status["error"] = str(e)

    async def worker():
        await asyncio.to_thread(run)

    asyncio.create_task(worker())
    return {"message": "Download iniciado"}

@app.get("/progress-stream")
async def progress_stream():
    async def event_generator():
        while True:
            # Uso seguro de .get() para mitigar erros do tipo KeyError
            status_val = download_status.get("status", "idle")
            percentage_val = download_status.get("percentage", 0)
            phase_val = download_status.get("phase", "")
            
            yield {"data": f'{{"status": "{status_val}", "percentage": {percentage_val}, "phase": "{phase_val}"}}'}
            
            if status_val in ["finished", "error"]:
                break
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())
