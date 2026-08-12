import os
import asyncio
import uuid
import time
from pathlib import Path
from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse
from sse_starlette.sse import EventSourceResponse
import yt_dlp

app = FastAPI()

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

# Status por download_id (evita conflito entre usuários)
downloads = {}

def cleanup_old_files(max_age_seconds=3600):
    """Remove arquivos com mais de 1 hora"""
    now = time.time()
    for f in DOWNLOAD_DIR.glob("*"):
        if f.is_file() and (now - f.stat().st_mtime) > max_age_seconds:
            try:
                f.unlink()
            except:
                pass

def ytdlp_hook(d, download_id: str):
    if download_id not in downloads:
        return

    status = downloads[download_id]
    info = d.get("info_dict", {}) or {}
    vcodec = info.get("vcodec", "none")
    acodec = info.get("acodec", "none")

    has_video = vcodec and vcodec != "none"
    has_audio = acodec and acodec != "none"

    if has_video and not has_audio:
        status["phase"] = "video"
    elif has_audio and not has_video:
        status["phase"] = "audio"

    if d["status"] == "downloading":
        status["status"] = "downloading"
        if "_percent_str" in d:
            try:
                pct = float(d["_percent_str"].replace("%", "").strip())
                status["percentage"] = round(pct, 1)
                return
            except:
                pass
        total = d.get("total_bytes") or d.get("total_bytes_estimate")
        downloaded = d.get("downloaded_bytes", 0)
        if total and total > 0:
            status["percentage"] = round((downloaded / total) * 100, 1)

    elif d["status"] == "finished":
        status["status"] = "processing"
        status["percentage"] = 100
        # Guarda o nome do arquivo final
        filename = d.get("filename") or d.get("info_dict", {}).get("_filename")
        if filename:
            status["filename"] = Path(filename).name

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LEO MDZ YT CONVERTER</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #0f0f0f;
            color: #f1f1f1;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 20px;
        }
        .card {
            background: #1f1f1f;
            width: 100%;
            max-width: 520px;
            padding: 32px;
            border-radius: 16px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            border: 1px solid #2f2f2f;
        }
        h2 {
            text-align: center;
            margin-bottom: 24px;
            font-size: 22px;
            letter-spacing: 0.3px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #aaa;
            font-size: 14px;
        }
        input[type="text"], select {
            width: 100%;
            padding: 13px 14px;
            margin-bottom: 18px;
            border: 1px solid #333;
            border-radius: 8px;
            background: #2d2d2d;
            color: #fff;
            font-size: 15px;
        }
        input:focus, select:focus {
            outline: none;
            border-color: #ff0000;
        }
        button {
            width: 100%;
            padding: 14px;
            background: #ff0000;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s;
        }
        button:hover { background: #cc0000; }
        button:disabled {
            background: #555;
            cursor: not-allowed;
        }
        #progress-container {
            display: none;
            margin-top: 28px;
        }
        .progress-box {
            width: 100%;
            background: #333;
            border-radius: 10px;
            overflow: hidden;
            height: 12px;
        }
        .progress-bar {
            width: 0%;
            height: 100%;
            background: #ff0000;
            transition: width 0.3s ease;
        }
        #status-text {
            text-align: center;
            margin-top: 12px;
            font-size: 14px;
            color: #ddd;
        }
        #download-link {
            display: none;
            margin-top: 18px;
            text-align: center;
        }
        #download-link a {
            display: inline-block;
            padding: 12px 24px;
            background: #4caf50;
            color: white;
            text-decoration: none;
            border-radius: 8px;
            font-weight: 600;
        }
        #download-link a:hover { background: #43a047; }
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
                <option value="best">Vídeo na Máxima Qualidade (MP4)</option>
                <option value="audio">Apenas Áudio (MP3)</option>
                <option value="worst">Vídeo em Baixa Qualidade</option>
            </select>

            <button type="submit" id="submitBtn">Iniciar Download</button>
        </form>

        <div id="progress-container">
            <div class="progress-box">
                <div id="progressBar" class="progress-bar"></div>
            </div>
            <div id="status-text">Iniciando...</div>
            <div id="download-link">
                <a id="fileLink" href="#" download>⬇️ Baixar arquivo</a>
            </div>
        </div>
    </div>

    <script>
        document.getElementById('downloadForm').addEventListener('submit', async (e) => {
            e.preventDefault();

            const formData = new FormData(e.target);
            const btn = document.getElementById('submitBtn');
            const progressContainer = document.getElementById('progress-container');
            const progressBar = document.getElementById('progressBar');
            const statusText = document.getElementById('status-text');
            const downloadLink = document.getElementById('download-link');
            const fileLink = document.getElementById('fileLink');

            btn.disabled = true;
            progressContainer.style.display = 'block';
            downloadLink.style.display = 'none';
            progressBar.style.width = '0%';
            progressBar.style.backgroundColor = '#ff0000';
            statusText.innerText = 'Conectando...';

            try {
                const res = await fetch('/download', {
                    method: 'POST',
                    body: formData
                });
                const data = await res.json();

                if (!res.ok) {
                    throw new Error(data.detail || 'Erro ao iniciar');
                }

                const downloadId = data.download_id;
                const eventSource = new EventSource(`/progress-stream/${downloadId}`);

                eventSource.onmessage = (event) => {
                    const d = JSON.parse(event.data);

                    if (d.status === 'downloading') {
                        progressBar.style.width = d.percentage + '%';
                        let label = 'Baixando';
                        if (d.phase === 'video') label = 'Baixando vídeo';
                        else if (d.phase === 'audio') label = 'Baixando áudio';
                        statusText.innerText = `${label}: ${d.percentage}%`;
                    }
                    else if (d.status === 'processing') {
                        progressBar.style.width = '100%';
                        progressBar.style.backgroundColor = '#2196f3';
                        statusText.innerText = 'Processando / mesclando... aguarde';
                    }
                    else if (d.status === 'finished') {
                        progressBar.style.backgroundColor = '#4caf50';
                        statusText.innerText = 'Pronto! Clique no botão abaixo para baixar.';
                        if (d.filename) {
                            fileLink.href = `/file/${encodeURIComponent(d.filename)}`;
                            fileLink.download = d.filename;
                            downloadLink.style.display = 'block';
                        }
                        eventSource.close();
                        btn.disabled = false;
                    }
                    else if (d.status === 'error') {
                        progressBar.style.backgroundColor = '#f44336';
                        statusText.innerText = 'Erro: ' + (d.error || 'Falha no download');
                        eventSource.close();
                        btn.disabled = false;
                    }
                };

                eventSource.onerror = () => {
                    statusText.innerText = 'Conexão perdida com o servidor';
                    eventSource.close();
                    btn.disabled = false;
                };

            } catch (err) {
                statusText.innerText = 'Erro: ' + err.message;
                btn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def home():
    cleanup_old_files()
    return HTML_TEMPLATE

@app.post("/download")
async def start_download(url: str = Form(...), quality: str = Form(...)):
    download_id = str(uuid.uuid4())
    downloads[download_id] = {
        "status": "starting",
        "percentage": 0,
        "phase": "",
        "filename": None,
        "error": None
    }

    # Opções base mais robustas para Railway / IPs de datacenter
    base_opts = {
        "progress_hooks": [lambda d: ytdlp_hook(d, download_id)],
        "outtmpl": str(DOWNLOAD_DIR / "%(title).80s [%(id)s].%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": True,
        "ignoreerrors": False,
        "geo_bypass": True,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web", "ios"],
            }
        },
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
        "retries": 3,
        "fragment_retries": 3,
    }

    if quality == "audio":
        ydl_opts = {
            **base_opts,
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        }
    elif quality == "worst":
        ydl_opts = {
            **base_opts,
            "format": "worst[ext=mp4]/worst",
        }
    else:  # best
        ydl_opts = {
            **base_opts,
            "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "merge_output_format": "mp4",
        }

    def run_download():
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                # Garante o nome do arquivo final
                if "requested_downloads" in info:
                    for rd in info["requested_downloads"]:
                        if "filepath" in rd:
                            downloads[download_id]["filename"] = Path(rd["filepath"]).name
                            break
                elif "_filename" in info:
                    downloads[download_id]["filename"] = Path(info["_filename"]).name

            downloads[download_id]["status"] = "finished"
            downloads[download_id]["percentage"] = 100
        except Exception as e:
            downloads[download_id]["status"] = "error"
            downloads[download_id]["error"] = str(e)[:200]
            print(f"[ERRO] {download_id}: {e}")

    asyncio.create_task(asyncio.to_thread(run_download))
    return {"message": "Download iniciado", "download_id": download_id}

@app.get("/progress-stream/{download_id}")
async def progress_stream(download_id: str):
    if download_id not in downloads:
        raise HTTPException(status_code=404, detail="Download não encontrado")

    async def event_generator():
        while True:
            status = downloads.get(download_id, {})
            data = {
                "status": status.get("status", "idle"),
                "percentage": status.get("percentage", 0),
                "phase": status.get("phase", ""),
                "filename": status.get("filename"),
                "error": status.get("error")
            }
            yield {"data": str(data).replace("'", '"')}  # simples JSON

            if status.get("status") in ("finished", "error"):
                # Mantém o status um pouco para o frontend pegar
                await asyncio.sleep(1)
                break
            await asyncio.sleep(0.4)

    return EventSourceResponse(event_generator())

@app.get("/file/{filename}")
async def get_file(filename: str):
    # Segurança básica
    safe_name = Path(filename).name
    file_path = DOWNLOAD_DIR / safe_name
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    return FileResponse(
        path=file_path,
        filename=safe_name,
        media_type="application/octet-stream"
    )