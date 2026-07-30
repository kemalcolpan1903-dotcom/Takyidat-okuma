import os
import tempfile
from functools import wraps
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for

from parser import extract_takbis_data, format_report, merge_multi

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 25 * 1024 * 1024  # 25 MB toplam yükleme sınırı

# Render'da "Environment" sekmesinden SECRET_KEY ve SITE_PASSWORD adında
# iki değişken ekleyeceksin (rehberde anlatılıyor). Buradaki değerler
# sadece o değişkenler tanımlanmamışsa (yerel test) kullanılan yedek.
app.secret_key = os.environ.get("SECRET_KEY", "yerel-test-icin-degistir")
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "degistir123")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


LOGIN_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Giriş — TAKBİS Okuyucu</title>
    <style>
        body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #0f172a; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; }
        .box { max-width: 360px; width: 100%; background: white; padding: 32px; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.05); }
        h1 { font-size: 18px; margin-bottom: 16px; }
        input[type="password"] { width: 100%; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; box-sizing: border-box; font-size: 14px; margin-bottom: 12px; }
        .btn { background: #2563eb; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; width: 100%; font-size: 14px; }
        .error { color: #dc2626; font-size: 13px; margin-bottom: 12px; }
    </style>
</head>
<body>
    <div class="box">
        <h1>🔒 TAKBİS Okuyucu — Giriş</h1>
        {% if error %}<div class="error">{{ error }}</div>{% endif %}
        <form method="POST">
            <input type="password" name="password" placeholder="Şifre" autofocus required>
            <button class="btn" type="submit">Giriş Yap</button>
        </form>
    </div>
</body>
</html>
"""


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if request.form.get('password') == SITE_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = "Şifre yanlış, tekrar dene."
    return render_template_string(LOGIN_TEMPLATE, error=error)


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>TAKBİS Takyidat Okuyucu</title>
    <style>
        body { font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f8fafc; color: #0f172a; padding: 40px; margin: 0; }
        .container { max-width: 800px; margin: 0 auto; background: white; padding: 32px; border-radius: 16px; border: 1px solid #e2e8f0; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.05); }
        h1 { font-size: 22px; margin-bottom: 6px; font-weight: 700; color: #0f172a; }
        p.sub { color: #64748b; font-size: 14px; margin-top: 0; margin-bottom: 20px; }
        .tabs { display: flex; gap: 8px; margin-bottom: 20px; }
        .tab { flex: 1; text-align: center; padding: 10px; border-radius: 8px; background: #f1f5f9; cursor: pointer; font-weight: 600; font-size: 14px; color: #475569; border: 1px solid #e2e8f0; }
        .tab.active { background: #2563eb; color: white; border-color: #2563eb; }
        .drop-zone { border: 2px dashed #94a3b8; border-radius: 12px; padding: 40px; text-align: center; background: #f1f5f9; cursor: pointer; transition: all 0.2s ease; }
        .drop-zone:hover { background: #e2e8f0; border-color: #2563eb; }
        input[type="file"] { display: none; }
        #fileList { margin-top: 12px; font-size: 13px; color: #475569; }
        #fileList div { padding: 4px 0; }
        textarea { width: 100%; height: 320px; margin-top: 20px; padding: 14px; border: 1px solid #cbd5e1; border-radius: 8px; box-sizing: border-box; font-size: 14px; line-height: 1.6; font-family: inherit; resize: vertical; }
        .btn { background: #2563eb; color: white; border: none; padding: 12px 20px; border-radius: 8px; cursor: pointer; font-weight: 600; margin-top: 12px; width: 100%; font-size: 14px; transition: background 0.2s; }
        .btn:hover { background: #1d4ed8; }
        .btn:disabled { background: #94a3b8; cursor: not-allowed; }
        .loading { display: none; color: #2563eb; font-weight: 600; font-size: 14px; margin-top: 15px; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>TAKBİS Takyidat Okuyucu</h1>
        <p class="sub">Web Tapu'dan indirdiğiniz TAKBİS PDF'ini yükleyin, takyidat/rehin bilgilerini otomatik ayrıştırıp rapor metnini hazırlasın. &nbsp;<a href="/logout" style="font-size:12px;color:#94a3b8;">(çıkış yap)</a></p>

        <div class="tabs">
            <div class="tab active" id="tabSingle" onclick="switchTab('single')">Tek PDF</div>
            <div class="tab" id="tabMulti" onclick="switchTab('multi')">Çoklu PDF</div>
        </div>

        <div class="drop-zone" onclick="document.getElementById('pdfFile').click()">
            <strong style="color: #2563eb; font-size: 15px;" id="dropLabel">PDF Dosyasını Buraya Tıklayarak Seçin</strong>
            <div style="font-size: 12px; color: #64748b; margin-top: 4px;">veya dosyayı buraya sürükleyin</div>
            <input type="file" id="pdfFile" accept=".pdf" onchange="onFilesChosen()">
        </div>
        <div id="fileList"></div>

        <button class="btn" id="analyzeBtn" onclick="uploadPDFs()" disabled>Analiz Et</button>

        <div id="loadingText" class="loading">TAKBİS belgesi(leri) inceleniyor, lütfen bekleyin...</div>

        <textarea id="resultText" readonly placeholder="Oluşturulan rapor metni burada görünecektir..."></textarea>
        <button class="btn" onclick="copyText()">Metni Kopyala</button>
    </div>

    <script>
        let mode = 'single';

        function switchTab(m) {
            mode = m;
            document.getElementById('tabSingle').classList.toggle('active', m === 'single');
            document.getElementById('tabMulti').classList.toggle('active', m === 'multi');
            document.getElementById('pdfFile').multiple = (m === 'multi');
            document.getElementById('dropLabel').textContent = m === 'multi'
                ? 'PDF Dosyalarını Buraya Tıklayarak Seçin (Birden Fazla)'
                : 'PDF Dosyasını Buraya Tıklayarak Seçin';
            document.getElementById('pdfFile').value = '';
            document.getElementById('fileList').innerHTML = '';
            document.getElementById('analyzeBtn').disabled = true;
        }

        function onFilesChosen() {
            const fileInput = document.getElementById('pdfFile');
            const list = document.getElementById('fileList');
            list.innerHTML = '';
            for (const f of fileInput.files) {
                const div = document.createElement('div');
                div.textContent = '📄 ' + f.name;
                list.appendChild(div);
            }
            document.getElementById('analyzeBtn').disabled = fileInput.files.length === 0;
        }

        async function uploadPDFs() {
            const fileInput = document.getElementById('pdfFile');
            if (fileInput.files.length === 0) return;

            const formData = new FormData();
            for (const f of fileInput.files) {
                formData.append('files', f);
            }

            document.getElementById('loadingText').style.display = 'block';
            document.getElementById('analyzeBtn').disabled = true;
            document.getElementById('resultText').value = "";

            try {
                const response = await fetch('/upload', { method: 'POST', body: formData });
                const data = await response.json();

                document.getElementById('loadingText').style.display = 'none';
                document.getElementById('analyzeBtn').disabled = false;

                if (data.success) {
                    document.getElementById('resultText').value = data.text;
                } else {
                    document.getElementById('resultText').value = "Hata oluştu: " + data.error;
                }
            } catch (err) {
                document.getElementById('loadingText').style.display = 'none';
                document.getElementById('analyzeBtn').disabled = false;
                document.getElementById('resultText').value = "Sunucuya bağlanırken bir hata oluştu.";
            }
        }

        function copyText() {
            const copyText = document.getElementById("resultText");
            if (!copyText.value) return;
            copyText.select();
            document.execCommand("copy");
            alert("Rapor metni panoya kopyalandı!");
        }
    </script>
</body>
</html>
"""


@app.route('/')
@login_required
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/upload', methods=['POST'])
@login_required
def upload():
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'success': False, 'error': 'Dosya seçilmedi'})

    tmp_paths = []
    try:
        for f in files:
            if f.filename == '':
                continue
            fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
            os.close(fd)
            f.save(tmp_path)
            tmp_paths.append((tmp_path, f.filename))

        if len(tmp_paths) == 1:
            data = extract_takbis_data(tmp_paths[0][0])
            report_text = format_report(data)
        else:
            report_text = merge_multi(tmp_paths)

        return jsonify({'success': True, 'text': report_text})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        for path, _ in tmp_paths:
            if os.path.exists(path):
                os.remove(path)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
