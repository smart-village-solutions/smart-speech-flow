from fastapi.responses import HTMLResponse
from .health import get_health_status_html
from services.api_gateway.app import SERVICE_URLS, app

@app.get("/", response_class=HTMLResponse)
def index():
    health_html = get_health_status_html(SERVICE_URLS)
    html = f"""
    <html>
    <head><title>Smart Speech Flow API Gateway</title>
    <script>
    async function uploadExample(fname, sourceLang, targetLang) {{
        const formData = new FormData();
        formData.append('source_lang', sourceLang);
        formData.append('target_lang', targetLang);
        // Lade die Datei als Blob
        const response = await fetch('/examples/' + fname);
        const blob = await response.blob();
        formData.append('file', blob, fname);
        formData.append('debug', 'true');
        // Sende das Formular per fetch
        const result = await fetch('/upload', {{
            method: 'POST',
            body: formData
        }});
        const html = await result.text();
        document.open();
        document.write(html);
        document.close();
    }}
    </script>
    </head>
    <body>
    <h1>Smart Speech Flow API Gateway</h1>
        <h2>Health-Status</h2>
        <ul>{health_html}</ul>
        <h2>WAV-Datei hochladen</h2>
        <form action='/upload' method='post' enctype='multipart/form-data'>
            <label for='file'>WAV-Datei:</label>
            <input type='file' name='file' accept='.wav' required><br><br>
            <label for='source_lang'>Ausgangssprache:</label>
            <select name='source_lang' required>
                <option value='de'>Deutsch</option>
                <option value='en'>Englisch</option>
                <option value='ar'>Arabisch</option>
                <option value='tr'>Türkisch</option>
                <option value='am'>Amharisch</option>
                <option value='fa'>Persisch</option>
                <option value='ru'>Russisch</option>
                <option value='uk'>Ukrainisch</option>
            </select><br><br>
            <label for='target_lang'>Zielsprache:</label>
            <select name='target_lang' required>
                <option value='de'>Deutsch</option>
                <option value='en'>Englisch</option>
                <option value='ar'>Arabisch</option>
                <option value='tr'>Türkisch</option>
                <option value='am'>Amharisch</option>
                <option value='fa'>Persisch</option>
                <option value='ru'>Russisch</option>
                <option value='uk'>Ukrainisch</option>
            </select><br><br>
            <input type='hidden' name='debug' value='true'>
            <button type='submit'>Verarbeiten & Download</button>
        </form>

    </body>
    </html>
    """
    return HTMLResponse(content=html)
