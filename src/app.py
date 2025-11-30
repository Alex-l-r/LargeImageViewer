#!/usr/bin/env python3
"""
Large Image Viewer
==================
A simple, high-performance viewer for very large images using OpenSeadragon.

Usage:
    python -m src.app [--port 5000] [--no-browser]

Or run directly:
    python src/app.py
"""

import argparse
import datetime
import logging
import json
import webbrowser
import threading
from pathlib import Path

from flask import Flask, request, send_from_directory, jsonify
import pyvips
from werkzeug.utils import secure_filename

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "tiff", "tif", "bmp", "webp"}
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

# Directories
SRC_DIR = Path(__file__).parent
BASE_DIR = SRC_DIR.parent
TILES_DIR = BASE_DIR / "tiles"
STATIC_DIR = SRC_DIR / "static"

# Create tiles directory
TILES_DIR.mkdir(exist_ok=True)

# =============================================================================
# Flask App
# =============================================================================

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# =============================================================================
# Routes
# =============================================================================

@app.route("/")
def index():
    return INDEX_HTML


@app.route("/static/<path:filename>")
def serve_static(filename):
    """Serve static files (OpenSeadragon, etc.)."""
    return send_from_directory(STATIC_DIR, filename)


@app.route("/tiles/<path:filename>")
def serve_tiles(filename):
    """Serve DZI tiles with aggressive caching."""
    response = send_from_directory(TILES_DIR, filename)
    # Tiles are immutable - cache for 7 days
    response.headers['Cache-Control'] = 'public, max-age=604800, immutable'
    return response


@app.route("/upload", methods=["POST"])
def upload():
    """Upload and convert image to DZI format."""
    try:
        if "file" not in request.files:
            return jsonify(success=False, error="No file provided"), 400
        
        file = request.files["file"]
        if file.filename == "":
            return jsonify(success=False, error="No file selected"), 400
        
        if not allowed_file(file.filename):
            return jsonify(success=False, error=f"Unsupported format. Use: {', '.join(ALLOWED_EXTENSIONS)}"), 400

        original_filename = file.filename
        # Create safe basename from original name
        name_without_ext = Path(original_filename).stem
        safe_name = secure_filename(name_without_ext) or f"image_{int(datetime.datetime.now().timestamp())}"
        
        # Check if already processed
        dzi_path = TILES_DIR / f"{safe_name}.dzi"
        if dzi_path.exists():
            # Already have this image, just return the URL
            logger.info(f"Image '{safe_name}' already processed, reusing tiles")
            meta = load_metadata(safe_name)
            return jsonify(
                success=True,
                dzi_url=f"/tiles/{safe_name}.dzi",
                meta=meta,
                cached=True
            )
        
        # Save uploaded file temporarily
        temp_path = TILES_DIR / f"_temp_{safe_name}{Path(original_filename).suffix}"
        
        logger.info(f"Processing: {original_filename}")
        file.save(str(temp_path))
        
        try:
            # Convert to DZI using pyvips
            logger.info("Converting to Deep Zoom format...")
            image = pyvips.Image.new_from_file(str(temp_path), access="sequential")
            
            # DZI output path (pyvips adds .dzi automatically)
            output_base = TILES_DIR / safe_name
            
            image.dzsave(
                str(output_base),
                tile_size=512,      # Larger tiles = fewer HTTP requests
                overlap=1,
                suffix=".jpg[Q=85]", # JPEG quality 85 - good balance
                container="fs",
                strip=True,          # Remove metadata from tiles
            )
            
            # Get metadata
            file_size = temp_path.stat().st_size
            width, height = image.width, image.height
            
            meta = {
                "original_name": original_filename,
                "width": width,
                "height": height,
                "size": file_size,
                "file_type": Path(original_filename).suffix[1:].lower(),
                "processed_at": datetime.datetime.now().isoformat(timespec="seconds"),
                "megapixels": round(width * height / 1_000_000, 1),
            }
            
            # Save metadata
            save_metadata(safe_name, meta)
            
            logger.info(f"Done! {width}x{height} ({meta['megapixels']} MP)")
            
            return jsonify(
                success=True,
                dzi_url=f"/tiles/{safe_name}.dzi",
                meta=meta,
                cached=False
            )
            
        finally:
            # Clean up temp file
            if temp_path.exists():
                temp_path.unlink()
                
    except pyvips.Error as e:
        logger.error(f"Image processing error: {e}")
        return jsonify(success=False, error=f"Failed to process image: {str(e)}"), 500
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify(success=False, error="Internal server error"), 500


@app.route("/images")
def list_images():
    """List all processed images."""
    images = []
    for dzi_file in TILES_DIR.glob("*.dzi"):
        name = dzi_file.stem
        meta = load_metadata(name)
        images.append({
            "name": name,
            "dzi_url": f"/tiles/{name}.dzi",
            "meta": meta
        })
    # Sort by processed date, newest first
    images.sort(key=lambda x: x.get("meta", {}).get("processed_at", ""), reverse=True)
    return jsonify(images=images)


@app.route("/delete/<name>", methods=["POST"])
def delete_image(name):
    """Delete a processed image and its tiles."""
    import shutil
    
    safe_name = secure_filename(name)
    dzi_path = TILES_DIR / f"{safe_name}.dzi"
    tiles_path = TILES_DIR / f"{safe_name}_files"
    meta_path = TILES_DIR / f"{safe_name}_meta.json"
    
    deleted = False
    for path in [dzi_path, meta_path]:
        if path.exists():
            path.unlink()
            deleted = True
    
    if tiles_path.exists():
        shutil.rmtree(tiles_path)
        deleted = True
    
    if deleted:
        logger.info(f"Deleted: {safe_name}")
        return jsonify(success=True)
    else:
        return jsonify(success=False, error="Image not found"), 404


# =============================================================================
# Helpers
# =============================================================================

def load_metadata(name: str) -> dict:
    """Load metadata for an image."""
    meta_path = TILES_DIR / f"{name}_meta.json"
    if meta_path.exists():
        try:
            return json.loads(meta_path.read_text())
        except Exception:
            pass
    return {}


def save_metadata(name: str, meta: dict):
    """Save metadata for an image."""
    meta_path = TILES_DIR / f"{name}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))


# =============================================================================
# HTML Template
# =============================================================================

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Large Image Viewer</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200" rel="stylesheet">
  <script src="/static/vendor/openseadragon/openseadragon.min.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    
    :root {
      --bg: #0f0f0f;
      --surface: #1a1a1a;
      --surface-hover: #252525;
      --border: #2a2a2a;
      --text: #e5e5e5;
      --text-dim: #888;
      --accent: #3b82f6;
      --accent-hover: #2563eb;
      --success: #22c55e;
      --error: #ef4444;
    }
    
    html, body {
      height: 100%;
      font-family: 'Inter', -apple-system, sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }
    
    .app {
      display: flex;
      height: 100vh;
    }
    
    /* Sidebar */
    .sidebar {
      width: 280px;
      background: var(--surface);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }
    
    .sidebar-header {
      padding: 16px;
      border-bottom: 1px solid var(--border);
    }
    
    .sidebar-header h1 {
      font-size: 14px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    
    .sidebar-header h1 .material-symbols-outlined {
      font-size: 20px;
      color: var(--accent);
    }
    
    /* Upload area */
    .upload-area {
      margin: 16px;
      padding: 24px 16px;
      border: 2px dashed var(--border);
      border-radius: 8px;
      text-align: center;
      cursor: pointer;
      transition: all 0.15s;
    }
    
    .upload-area:hover, .upload-area.dragover {
      border-color: var(--accent);
      background: rgba(59, 130, 246, 0.05);
    }
    
    .upload-area .material-symbols-outlined {
      font-size: 32px;
      color: var(--text-dim);
      margin-bottom: 8px;
    }
    
    .upload-area p {
      font-size: 13px;
      color: var(--text-dim);
    }
    
    .upload-area input { display: none; }
    
    /* Progress */
    .progress-container {
      margin: 0 16px 16px;
      display: none;
    }
    
    .progress-container.active { display: block; }
    
    .progress-bar {
      height: 4px;
      background: var(--border);
      border-radius: 2px;
      overflow: hidden;
    }
    
    .progress-fill {
      height: 100%;
      background: var(--accent);
      width: 0%;
      transition: width 0.2s;
    }
    
    .progress-text {
      font-size: 12px;
      color: var(--text-dim);
      margin-top: 6px;
    }
    
    /* Image list */
    .image-list {
      flex: 1;
      overflow-y: auto;
      padding: 0 8px;
    }
    
    .image-item {
      padding: 10px 12px;
      border-radius: 6px;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 10px;
      transition: background 0.1s;
      margin-bottom: 2px;
    }
    
    .image-item:hover { background: var(--surface-hover); }
    .image-item.active { background: var(--accent); }
    
    .image-item .material-symbols-outlined {
      font-size: 18px;
      color: var(--text-dim);
    }
    
    .image-item.active .material-symbols-outlined { color: white; }
    
    .image-info {
      flex: 1;
      min-width: 0;
    }
    
    .image-name {
      font-size: 13px;
      font-weight: 500;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    
    .image-meta {
      font-size: 11px;
      color: var(--text-dim);
      margin-top: 2px;
    }
    
    .image-item.active .image-meta { color: rgba(255,255,255,0.7); }
    
    .delete-btn {
      opacity: 0;
      background: none;
      border: none;
      color: var(--text-dim);
      cursor: pointer;
      padding: 4px;
      border-radius: 4px;
      transition: all 0.1s;
    }
    
    .image-item:hover .delete-btn { opacity: 1; }
    .delete-btn:hover { background: var(--error); color: white; }
    
    /* Viewer */
    .viewer-container {
      flex: 1;
      position: relative;
      background: #000;
    }
    
    #viewer {
      width: 100%;
      height: 100%;
    }
    
    .viewer-placeholder {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      color: var(--text-dim);
    }
    
    .viewer-placeholder .material-symbols-outlined {
      font-size: 48px;
      margin-bottom: 12px;
      opacity: 0.5;
    }
    
    /* Info bar */
    .info-bar {
      position: absolute;
      bottom: 16px;
      left: 16px;
      background: rgba(0,0,0,0.75);
      backdrop-filter: blur(8px);
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 12px;
      color: var(--text-dim);
      display: none;
    }
    
    .info-bar.active { display: block; }
    
    /* Toast notifications */
    .toast {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: var(--surface);
      border: 1px solid var(--border);
      padding: 12px 16px;
      border-radius: 8px;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 8px;
      transform: translateY(100px);
      opacity: 0;
      transition: all 0.2s;
      z-index: 1000;
    }
    
    .toast.show { transform: translateY(0); opacity: 1; }
    .toast.success { border-color: var(--success); }
    .toast.error { border-color: var(--error); }
    
    /* Scrollbar */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #444; }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="sidebar-header">
        <h1>
          <span class="material-symbols-outlined">photo_library</span>
          Large Image Viewer
        </h1>
      </div>
      
      <div class="upload-area" id="uploadArea">
        <span class="material-symbols-outlined">cloud_upload</span>
        <p>Drop image here or click to browse</p>
        <input type="file" id="fileInput" accept="image/*">
      </div>
      
      <div class="progress-container" id="progress">
        <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
        <div class="progress-text" id="progressText">Processing...</div>
      </div>
      
      <div class="image-list" id="imageList"></div>
    </aside>
    
    <main class="viewer-container">
      <div id="viewer"></div>
      <div class="viewer-placeholder" id="placeholder">
        <span class="material-symbols-outlined">image</span>
        <p>Select or upload an image to view</p>
        <p style="margin-top:16px;font-size:11px;opacity:0.5">Press ? for keyboard shortcuts</p>
      </div>
      <div class="info-bar" id="infoBar"></div>
    </main>
  </div>
  
  <div class="toast" id="toast"></div>

  <script>
    // ===========================================
    // State
    // ===========================================
    let viewer = null;
    let currentImage = null;
    
    // ===========================================
    // Elements
    // ===========================================
    const uploadArea = document.getElementById('uploadArea');
    const fileInput = document.getElementById('fileInput');
    const progress = document.getElementById('progress');
    const progressFill = document.getElementById('progressFill');
    const progressText = document.getElementById('progressText');
    const imageList = document.getElementById('imageList');
    const placeholder = document.getElementById('placeholder');
    const infoBar = document.getElementById('infoBar');
    const toast = document.getElementById('toast');
    
    // ===========================================
    // Upload handling
    // ===========================================
    uploadArea.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) uploadFile(e.target.files[0]);
    });
    
    uploadArea.addEventListener('dragover', (e) => {
      e.preventDefault();
      uploadArea.classList.add('dragover');
    });
    
    uploadArea.addEventListener('dragleave', () => {
      uploadArea.classList.remove('dragover');
    });
    
    uploadArea.addEventListener('drop', (e) => {
      e.preventDefault();
      uploadArea.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        uploadFile(e.dataTransfer.files[0]);
      }
    });
    
    async function uploadFile(file) {
      progress.classList.add('active');
      progressFill.style.width = '0%';
      progressText.textContent = 'Uploading...';
      
      const formData = new FormData();
      formData.append('file', file);
      
      const xhr = new XMLHttpRequest();
      
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round(e.loaded / e.total * 50); // Upload is 0-50%
          progressFill.style.width = pct + '%';
          progressText.textContent = `Uploading: ${pct * 2}%`;
        }
      };
      
      xhr.onload = () => {
        try {
          const data = JSON.parse(xhr.responseText);
          if (data.success) {
            progressFill.style.width = '100%';
            progressText.textContent = data.cached ? 'Already processed!' : 'Done!';
            showToast(data.cached ? 'Image loaded from cache' : 'Image processed successfully', 'success');
            loadImageList();
            loadImage(data.dzi_url, data.meta);
          } else {
            showToast(data.error || 'Upload failed', 'error');
          }
        } catch (e) {
          showToast('Upload failed', 'error');
        }
        setTimeout(() => progress.classList.remove('active'), 1000);
      };
      
      xhr.onerror = () => {
        showToast('Upload failed - network error', 'error');
        progress.classList.remove('active');
      };
      
      // Simulate processing progress after upload
      xhr.onreadystatechange = () => {
        if (xhr.readyState === 4) return;
        if (xhr.readyState === 3) {
          progressFill.style.width = '75%';
          progressText.textContent = 'Processing image...';
        }
      };
      
      xhr.open('POST', '/upload');
      xhr.send(formData);
    }
    
    // ===========================================
    // Image list
    // ===========================================
    async function loadImageList() {
      try {
        const resp = await fetch('/images');
        const data = await resp.json();
        renderImageList(data.images);
      } catch (e) {
        console.error('Failed to load images:', e);
      }
    }
    
    function renderImageList(images) {
      imageList.innerHTML = images.map(img => `
        <div class="image-item ${currentImage === img.dzi_url ? 'active' : ''}" 
             data-url="${img.dzi_url}" data-name="${img.name}">
          <span class="material-symbols-outlined">image</span>
          <div class="image-info">
            <div class="image-name">${img.meta?.original_name || img.name}</div>
            <div class="image-meta">${img.meta?.width || '?'}×${img.meta?.height || '?'} · ${formatSize(img.meta?.size)}</div>
          </div>
          <button class="delete-btn" onclick="deleteImage(event, '${img.name}')">
            <span class="material-symbols-outlined">delete</span>
          </button>
        </div>
      `).join('');
      
      // Add click handlers
      imageList.querySelectorAll('.image-item').forEach(el => {
        el.addEventListener('click', (e) => {
          if (e.target.closest('.delete-btn')) return;
          const url = el.dataset.url;
          const name = el.dataset.name;
          // Find meta from images array
          const img = images.find(i => i.name === name);
          loadImage(url, img?.meta);
        });
      });
    }
    
    async function deleteImage(event, name) {
      event.stopPropagation();
      if (!confirm(`Delete "${name}" and its tiles?`)) return;
      
      try {
        const resp = await fetch(`/delete/${name}`, { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
          showToast('Image deleted', 'success');
          if (currentImage?.includes(name)) {
            currentImage = null;
            if (viewer) viewer.destroy();
            viewer = null;
            placeholder.style.display = 'flex';
            infoBar.classList.remove('active');
          }
          loadImageList();
        } else {
          showToast(data.error || 'Delete failed', 'error');
        }
      } catch (e) {
        showToast('Delete failed', 'error');
      }
    }
    
    // ===========================================
    // Viewer
    // ===========================================
    function loadImage(dziUrl, meta) {
      currentImage = dziUrl;
      placeholder.style.display = 'none';
      
      // Update active state in list
      imageList.querySelectorAll('.image-item').forEach(el => {
        el.classList.toggle('active', el.dataset.url === dziUrl);
      });
      
      // Destroy existing viewer
      if (viewer) viewer.destroy();
      
      // Create new viewer with optimized settings
      viewer = OpenSeadragon({
        id: 'viewer',
        prefixUrl: '/static/vendor/openseadragon/images/',
        tileSources: dziUrl,
        
        // Performance optimizations
        immediateRender: true,
        imageLoaderLimit: 4,
        maxImageCacheCount: 500,
        timeout: 60000,
        useCanvas: true,
        
        // Navigation
        showNavigator: true,
        navigatorPosition: 'TOP_RIGHT',
        navigatorSizeRatio: 0.15,
        
        // Controls
        showRotationControl: true,
        showFullPageControl: true,
        
        // Zoom settings
        minZoomLevel: 0.1,
        maxZoomPixelRatio: 4,
        visibilityRatio: 0.5,
        constrainDuringPan: false,
        
        // Gestures
        gestureSettingsMouse: {
          scrollToZoom: true,
          clickToZoom: true,
          dblClickToZoom: true,
        },
        gestureSettingsTouch: {
          pinchToZoom: true,
          flickEnabled: true,
        },
        
        // Smoothness
        animationTime: 0.3,
        springStiffness: 10,
      });
      
      // Update info bar
      if (meta) {
        infoBar.innerHTML = `${meta.original_name || 'Image'} · ${meta.width}×${meta.height} · ${meta.megapixels} MP`;
        infoBar.classList.add('active');
      }
      
      // Error handling
      viewer.addHandler('open-failed', (e) => {
        showToast('Failed to load image tiles', 'error');
        console.error('OpenSeadragon error:', e);
      });
    }
    
    // ===========================================
    // Utilities
    // ===========================================
    function formatSize(bytes) {
      if (!bytes) return '?';
      if (bytes < 1024) return bytes + ' B';
      if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
      if (bytes < 1024 * 1024 * 1024) return (bytes / 1024 / 1024).toFixed(1) + ' MB';
      return (bytes / 1024 / 1024 / 1024).toFixed(2) + ' GB';
    }
    
    function showToast(message, type = '') {
      toast.textContent = message;
      toast.className = 'toast ' + type;
      setTimeout(() => toast.classList.add('show'), 10);
      setTimeout(() => toast.classList.remove('show'), 3000);
    }
    
    // ===========================================
    // Keyboard shortcuts
    // ===========================================
    document.addEventListener('keydown', (e) => {
      if (!viewer) return;
      
      switch(e.key) {
        case '+':
        case '=':
          viewer.viewport.zoomBy(1.5);
          break;
        case '-':
          viewer.viewport.zoomBy(0.67);
          break;
        case 'r':
        case 'R':
          viewer.viewport.setRotation((viewer.viewport.getRotation() + 90) % 360);
          break;
        case '0':
          viewer.viewport.goHome();
          break;
        case 'f':
        case 'F':
          viewer.setFullScreen(!viewer.isFullPage());
          break;
        case 'ArrowLeft':
          viewer.viewport.panBy(new OpenSeadragon.Point(-0.1, 0));
          break;
        case 'ArrowRight':
          viewer.viewport.panBy(new OpenSeadragon.Point(0.1, 0));
          break;
        case 'ArrowUp':
          viewer.viewport.panBy(new OpenSeadragon.Point(0, -0.1));
          break;
        case 'ArrowDown':
          viewer.viewport.panBy(new OpenSeadragon.Point(0, 0.1));
          break;
        case '?':
          showToast('Keys: +/- zoom, R rotate, F fullscreen, 0 reset, arrows pan', 'info');
          break;
      }
    });
    
    // ===========================================
    // Init
    // ===========================================
    loadImageList();
  </script>
</body>
</html>
"""


# =============================================================================
# Main
# =============================================================================

def open_browser(port: int):
    """Open browser after a short delay."""
    import time
    time.sleep(1.0)
    url = f"http://localhost:{port}"
    print(f"\n  Opening browser: {url}\n")
    webbrowser.open(url)


def main():
    parser = argparse.ArgumentParser(
        description="Large Image Viewer - View gigapixel images smoothly",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python viewer.py                  # Start on port 5000, open browser
  python viewer.py --port 8080      # Use different port
  python viewer.py --no-browser     # Don't auto-open browser
        """
    )
    parser.add_argument("--port", type=int, default=5000, help="Port to run on (default: 5000)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()
    
    print("""
╔═══════════════════════════════════════════════════════════╗
║           Large Image Viewer                              ║
║           ──────────────────                              ║
║  Drag & drop large images to view them smoothly.          ║
║  Processed tiles are cached in ./tiles/                   ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    print(f"  Tiles directory: {TILES_DIR}")
    print(f"  Server running on: http://localhost:{args.port}")
    print(f"  Press Ctrl+C to stop\n")
    
    # Open browser in background thread
    if not args.no_browser:
        threading.Thread(target=open_browser, args=(args.port,), daemon=True).start()
    
    # Run Flask (use threaded mode for better tile serving)
    app.run(
        host="127.0.0.1",  # Localhost only for security
        port=args.port,
        debug=False,
        threaded=True,
    )


if __name__ == "__main__":
    main()
