# Large Image Viewer

A simple, high-performance viewer for very large images using OpenSeadragon's Deep Zoom technology. Initially conceived to inspect full wafer images in semiconductor fabrication processes but should fit many other applications.

## Features

- **Gigapixel Support**: Smoothly view images up to 2GB
- **Simple to Use**: Double-click to start, drag & drop images
- **Fast Processing**: Uses libvips for efficient tile generation
- **Persistent Cache**: Processed images are cached for instant reload
- **Modern UI**: Clean, dark interface with image management

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Start the viewer
docker-compose up

# Open browser to http://localhost:5000
```

### Option 2: Windows

Double-click `start-viewer.bat`

### Option 3: Command Line

```bash
python run.py
```

The browser opens automatically. Drag & drop images to view them.

## Usage

1. **Drop an image** into the upload area (or click to browse)
2. **Wait for processing** - large images may take a minute
3. **Navigate** - scroll to zoom, drag to pan, use controls to rotate
4. **Switch images** - click any image in the sidebar
5. **Delete** - hover over an image and click the trash icon

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `+` / `-` | Zoom in / out |
| `R` | Rotate 90° |
| `F` | Toggle fullscreen |
| `0` | Reset view |
| `Arrow keys` | Pan |
| `?` | Show help |

## Supported Formats

- JPEG (.jpg, .jpeg)
- PNG (.png)  
- TIFF (.tiff, .tif)
- BMP (.bmp)
- WebP (.webp)

**Maximum file size**: 2GB

## How It Works

1. When you upload an image, it's converted to **Deep Zoom Image (DZI)** format
2. DZI creates a pyramid of tiles at multiple zoom levels
3. OpenSeadragon loads only the tiles visible on screen
4. Result: smooth panning and zooming even for gigapixel images

Processed tiles are stored in the `./tiles/` directory and reused on subsequent loads.

## Requirements

### For Docker
- Docker and Docker Compose

### For Native Python
- Python 3.9+
- libvips library ([installation guide](https://www.libvips.org/install.html))

## Command Line Options

```bash
python run.py --help

Options:
  --port PORT      Port to run on (default: 5000)
  --no-browser     Don't auto-open browser
```

## Project Structure

```
LargeImageViewer/
├── src/
│   ├── __init__.py
│   ├── __main__.py
│   ├── app.py             # Main application
│   └── static/
│       └── vendor/
│           └── openseadragon/
├── run.py                 # Entry point
├── start-viewer.bat       # Windows launcher
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── requirements.txt
├── README.md
├── LICENSE
└── tiles/                 # Generated (gitignored)
```

## Troubleshooting

**"libvips not found"** - Install libvips or use Docker instead

**Slow processing** - Normal for very large images. A 1GB TIFF may take 1-2 minutes.

**Out of memory** - Increase Docker memory limit or system RAM

## License

MIT License - see [LICENSE](LICENSE) for details.

## Credits

- [OpenSeadragon](https://openseadragon.github.io/) - Deep zoom viewer
- [libvips](https://www.libvips.org/) - Fast image processing
- [Flask](https://flask.palletsprojects.com/) - Web framework
