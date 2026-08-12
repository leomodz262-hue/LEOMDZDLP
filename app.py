import os
import asyncio
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse
from sse_starlette.sse import EventSourceResponse
import yt_dlp

app = FastAPI()

# A global dictionary to store the download progress of the current video
download_status = {"status": "idle", "percentage": 0, "title": "", "phase": ""}

def ytdlp_hook(d):
    """Progress hook for yt-dlp with stream detection."""
    global download_status
    
    # Detect which stream is downloading (video-only or audio-only)
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

# Updated HTML with modern progress bar and simple JavaScript (EventSource)
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>yt-dlp Downloader with Progress</title>
    <style>
        body { font-family: Arial, sans-serif; max-width: 600px; margin: 50px auto; padding: 20px; background-color: #f9f9f9; }
        .card { background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }
        h2 { color: #333; text-align: center; margin-bottom: 20px; }
        input[type="text"], select { width: 100%; padding: 12px; margin: 10px 0 20px 0; border: 1px solid #ccc; border-radius: 6px; box-sizing: border-box; }
        button { width: 100%; padding: 14px; background-color: #ff0000; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 16px; font-weight: bold; }
        button:hover { background-color: #cc0000; }
        
        /* Progress Bar Styling */
        #progress-container { display: none; margin-top: 25px; }
        .progress-box { width: 100%; background-color: #e0e0e0; border-radius: 8px; overflow: hidden; }
        .progress-bar { width: 0%; height: 20px; background-color: #4caf50; transition: width 0.2s ease; }
        #status-text { text-align: center; font-weight: bold; margin-top: 8px; color: #555; }
    </style>
</head>
<body>
    <div class="card">
        <h2>🎥 Local yt-dlp Manager</h2>
        <form id="downloadForm">
            <label>YouTube URL:</label>
            <input type="text" id="url" name="url" placeholder="https://www.youtube.com/watch?v=..." required>
            
            <label>Download Options:</label>
            <select id="quality" name="quality">
                <option value="bestvideo+bestaudio/best">Highest Quality Video (Merged)</option>
                <option value="bestaudio/best">Audio Only (Best Quality MP3)</option>
                <option value="worst">Lowest Quality Video (Saves Space)</option>
            </select>
            
            <button type="submit" id="submitBtn">Start Download</button>
        </form>

        <div id="progress-container">
            <div class="progress-box">
                <div id="progressBar" class="progress-bar"></div>
            </div>
            <div id="status-text">Starting... 0%</div>
        </div>
    </div>

    <script>
        document.getElementById('downloadForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const formData = new FormData(e.target);
            document.getElementById('submitBtn').disabled = true;
            document.getElementById('progress-container').style.display = 'block';
            
            // 1. Trigger the download backend
            fetch('/download', { method: 'POST', body: formData });

            // 2. Open an SSE connection to listen for live progress updates
            const eventSource = new EventSource('/progress-stream');
            
            eventSource.onmessage = (event) => {
                const data = JSON.parse(event.data);
                const progressBar = document.getElementById('progressBar');
                const statusText = document.getElementById('status-text');

                if (data.status === 'downloading') {
                    progressBar.style.width = data.percentage + '%';
                    let label = 'Downloading';
                    if (data.phase === 'video stream') label = 'Downloading video';
                    else if (data.phase === 'audio stream') label = 'Downloading audio';
                    statusText.innerText = label + ': ' + data.percentage + '%';
                } else if (data.status === 'processing') {
                    progressBar.style.width = '100%';
                    progressBar.style.backgroundColor = '#2196f3';
                    statusText.innerText = 'Merging audio and video... Please wait.';
                } else if (data.status === 'finished') {
                    progressBar.style.backgroundColor = '#4caf50';
                    statusText.innerText = 'Done! Download finished.';
                    eventSource.close();
                    document.getElementById('submitBtn').disabled = false;
                } else if (data.status === 'error') {
                    progressBar.style.backgroundColor = '#f44336';
                    statusText.innerText = 'Error: download failed.';
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
    """Triggers the download and correctly schedules it in the event loop."""
    global download_status
    download_status = {"status": "starting", "percentage": 0, "title": ""}
    
    download_folder = os.path.join(os.getcwd(), "downloads")

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
            download_status["status"] = "error"
            download_status["error"] = str(e)

    async def worker():
        await asyncio.to_thread(run)

    asyncio.create_task(worker())
    
    return {"message": "Download initiated"}

@app.get("/progress-stream")
async def progress_stream():
    """Streams the current download percentage to the frontend in real-time."""
    async def event_generator():
        global download_status
        while True:
            yield {"data": f'{{"status": "{download_status["status"]}", "percentage": {download_status["percentage"]}, "phase": "{download_status["phase"]}"}}'}
            if download_status["status"] == "finished":
                break
            await asyncio.sleep(0.5) # Send updates every half-second

    return EventSourceResponse(event_generator())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main-app:app", host="0.0.0.0", port=8000, reload=True)