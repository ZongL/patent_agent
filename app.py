"""Flask web interface for patent_agent."""

import os
import tempfile
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
load_dotenv()

from flask import Flask, request, render_template_string, send_file, jsonify

app = Flask(__name__)

# Max upload size: 50MB
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Patent Agent - USPTO Patent Analysis</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #f5f5f5;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 40px 20px;
        }
        .container {
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 12px rgba(0,0,0,0.1);
            padding: 40px;
            max-width: 600px;
            width: 100%;
        }
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 8px;
            font-size: 24px;
        }
        .subtitle {
            text-align: center;
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }
        .upload-area {
            border: 2px dashed #ccc;
            border-radius: 8px;
            padding: 40px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s;
            margin-bottom: 20px;
        }
        .upload-area:hover, .upload-area.dragover {
            border-color: #4a90d9;
            background: #f0f7ff;
        }
        .upload-area p {
            color: #666;
            margin-bottom: 10px;
        }
        .upload-area .icon {
            font-size: 48px;
            margin-bottom: 10px;
        }
        input[type="file"] {
            display: none;
        }
        .btn {
            display: block;
            width: 100%;
            padding: 14px;
            background: #4a90d9;
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            cursor: pointer;
            transition: background 0.3s;
        }
        .btn:hover { background: #357abd; }
        .btn:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        .filename {
            margin-bottom: 15px;
            padding: 10px;
            background: #f0f7ff;
            border-radius: 6px;
            display: none;
            word-break: break-all;
        }
        .progress {
            display: none;
            margin-top: 20px;
            text-align: center;
        }
        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #4a90d9;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 15px;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .error {
            color: #d32f2f;
            background: #ffeaea;
            padding: 12px;
            border-radius: 6px;
            margin-top: 15px;
            display: none;
        }
        .footer {
            margin-top: 20px;
            text-align: center;
            color: #999;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Patent Agent</h1>
        <p class="subtitle">USPTO Patent PDF Intelligent Analysis</p>

        <form id="uploadForm" enctype="multipart/form-data">
            <div class="upload-area" id="dropZone">
                <div class="icon"> </div>
                <p>Drag & drop PDF here, or click to select</p>
                <p style="font-size: 12px; color: #999;">Supports USPTO patent PDF files</p>
            </div>
            <input type="file" id="fileInput" name="pdf" accept=".pdf">
            <div class="filename" id="fileName"></div>
            <button type="submit" class="btn" id="submitBtn" disabled>Analyze Patent</button>
        </form>

        <div class="progress" id="progress">
            <div class="spinner"></div>
            <p id="progressText">Processing... This may take 2-5 minutes.</p>
        </div>

        <div class="error" id="error"></div>
    </div>

    <div class="footer">
        Powered by LLM | Patent Agent v1.0
    </div>

    <script>
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput');
        const fileName = document.getElementById('fileName');
        const submitBtn = document.getElementById('submitBtn');
        const uploadForm = document.getElementById('uploadForm');
        const progress = document.getElementById('progress');
        const error = document.getElementById('error');

        dropZone.addEventListener('click', () => fileInput.click());

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');
            if (e.dataTransfer.files.length) {
                fileInput.files = e.dataTransfer.files;
                updateFileName();
            }
        });

        fileInput.addEventListener('change', updateFileName);

        function updateFileName() {
            if (fileInput.files.length) {
                fileName.textContent = '  ' + fileInput.files[0].name;
                fileName.style.display = 'block';
                submitBtn.disabled = false;
            }
        }

        uploadForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!fileInput.files.length) return;

            submitBtn.disabled = true;
            progress.style.display = 'block';
            error.style.display = 'none';

            const formData = new FormData();
            formData.append('pdf', fileInput.files[0]);

            try {
                const response = await fetch('/analyze', {
                    method: 'POST',
                    body: formData
                });

                if (response.ok) {
                    const blob = await response.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'patent_report.html';
                    a.click();
                    window.URL.revokeObjectURL(url);
                    progress.innerHTML = '<p style="color: #4caf50;">✅ Report downloaded!</p>';
                } else {
                    const data = await response.json();
                    throw new Error(data.error || 'Analysis failed');
                }
            } catch (err) {
                error.textContent = '❌ ' + err.message;
                error.style.display = 'block';
                progress.style.display = 'none';
            } finally {
                submitBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/analyze", methods=["POST"])
def analyze():
    if "pdf" not in request.files:
        return jsonify({"error": "No PDF file uploaded"}), 400

    pdf_file = request.files["pdf"]
    if not pdf_file.filename:
        return jsonify({"error": "No file selected"}), 400

    if not pdf_file.filename.lower().endswith(".pdf"):
        return jsonify({"error": "Only PDF files are supported"}), 400

    # Create temp directory for processing
    tmp_dir = tempfile.mkdtemp(prefix="patent_")
    try:
        pdf_path = os.path.join(tmp_dir, pdf_file.filename)
        pdf_file.save(pdf_path)

        # Run the pipeline
        from patent_agent.cli import main as run_pipeline

        output_dir = os.path.join(tmp_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        # Call pipeline with CLI args
        ret = run_pipeline([
            pdf_path,
            "--output-dir", output_dir,
        ])

        if ret != 0:
            return jsonify({"error": f"Pipeline failed with code {ret}"}), 500

        # Find the report
        report_path = os.path.join(output_dir, "report.html")
        if not os.path.exists(report_path):
            return jsonify({"error": "Report not generated"}), 500

        return send_file(
            report_path,
            mimetype="text/html",
            as_attachment=True,
            download_name="patent_report.html"
        )

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)
