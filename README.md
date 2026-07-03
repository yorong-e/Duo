# DuO — Digital Twin Interior Web Simulator

PropTech interior layout simulator combining **Python Flask**, **Three.js (WebGL)**, and a **C++ core calculation engine**.

## Architecture

```
Browser (Three.js)  ←→  Flask API  ←→  C++ libduo_engine (collision stub)
                              ↓
                     static/floorplan.json
```

| Layer | Role |
|-------|------|
| `templates/index.html` | Two-column UI: furniture catalog sidebar + WebGL canvas |
| `static/js/main.js` | Immediate Three.js bootstrap; async floor plan & catalog loading |
| `app.py` | REST API, optional ctypes engine binding |
| `core/engine.cpp` | Native spatial calculation module (shared library) |
| `schema.sql` | MySQL reference DDL for apartments, vectors, SKUs, materials |

## Quick Start

### 1. Python environment

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2. Floor plan data

Place your apartment JSON at:

```
static/floorplan.json
```

The API expects:

- Blueprint image (Base64 PNG data URI): `image["@attributes"]["xlink:href"]`
- Pixel dimensions: root `["@attributes"]["width"]` and `["@attributes"]["height"]`

### 3. C++ engine (optional)

```bash
cd core
make
cd ..
```

| Platform | Output |
|----------|--------|
| Linux / WSL | `core/libduo_engine.so` |
| macOS | `core/libduo_engine.dylib` |
| Windows (MinGW) | `core/libduo_engine.dll` |

If the library is missing, Flask starts in **fallback mode** with a console warning.

### 4. Run

```bash
python app.py
```

Open [http://localhost:5000](http://localhost:5000).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Main simulator UI |
| `GET` | `/api/floorplan` | `{ href, width, height }` extracted from `floorplan.json` |
| `GET` | `/api/furniture` | Mock catalog (sofa, bed, table, wardrobe) in mm |

### Example `/api/floorplan` response

```json
{
  "href": "data:image/png;base64,iVBORw0KGgo...",
  "width": 1200,
  "height": 900
}
```

## Frontend Behaviour

1. **Immediate render** — Scene, camera, lights, grid, and OrbitControls initialise on `window.onload` (no black screen).
2. **Async floor plan** — Fetches `/api/floorplan`, maps the blueprint onto a horizontal plane (XZ) with correct aspect ratio.
3. **Async catalog** — Fetches `/api/furniture`; on failure, shows a fallback notice and uses local mock data.
4. **Placement** — Click a catalog item to spawn a coloured box mesh scaled from mm dimensions.

## Database Schema

Apply the reference DDL:

```bash
mysql -u root -p < schema.sql
```

Tables: `apartments`, `space_vectors`, `furniture_sku`, `finishing_materials`.

## Project Structure

```
DuO/
├── app.py
├── requirements.txt
├── schema.sql
├── README.md
├── core/
│   ├── engine.cpp
│   └── Makefile
├── static/
│   ├── css/style.css
│   ├── js/main.js
│   ├── floorplan.json   ← place your data here
│   ├── models/
│   └── textures/
└── templates/
    └── index.html
```

## Development Notes

- `main.js` is loaded with a cache-busting query string (`?v=48291`) in `index.html`.
- Furniture dimensions in the API are in **millimetres**; the scene converts to metres (`× 0.001`).
- The C++ `check_collision()` stub always returns `false` — replace with real geometry logic as the engine matures.

## License

Internal PropTech reference boilerplate — adapt as needed.
