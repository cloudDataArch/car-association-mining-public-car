"""Create close-up map panels from the public CAR WFS and Esri imagery."""
from __future__ import annotations

import io
import json
import subprocess
import tempfile
from urllib.parse import urlencode
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from PIL import Image
import requests


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "article"
WFS = "https://geoserver.car.gov.br/geoserver/sicar/wfs"
TILE = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"

AREAS = {
    "São Félix do Xingu, Pará": {
        "layer": "sicar_imoveis_pa",
        "bbox": (-52.25, -6.82, -51.74, -6.43),
        "center": (-51.995, -6.645),
        "file": OUT / "map_sao_felix_perimetros_public.png",
    },
    "Presidente Prudente, São Paulo": {
        "layer": "sicar_imoveis_sp",
        "bbox": (-51.60, -22.30, -51.20, -21.90),
        "center": (-51.39, -22.12),
        "file": OUT / "map_presidente_prudente_perimetros_public.png",
    },
}


def fetch_features(layer: str, bbox: tuple[float, float, float, float]) -> list[dict]:
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": f"sicar:{layer}",
        "outputFormat": "application/json",
        "bbox": ",".join(map(str, bbox)) + ",EPSG:4326",
        "count": 3000,
    }
    query_url = WFS + "?" + urlencode(params)
    try:
        response = requests.get(query_url, timeout=120)
        response.raise_for_status()
        return response.json().get("features", [])
    except requests.RequestException:
        # Some Windows Python builds cannot negotiate the CAR server's TLS
        # handshake, while the system curl client can. Keep the fallback
        # explicit so the public-data workflow remains reproducible.
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            target = tmp.name
        try:
            subprocess.run(["curl.exe", "--tlsv1.2", "-L", "--fail", "--max-time", "180", "-o", target, query_url], check=True)
            return json.loads(Path(target).read_text(encoding="utf-8")).get("features", [])
        finally:
            Path(target).unlink(missing_ok=True)


def tile_xy(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    import math

    scale = 2**zoom
    x = (lon + 180.0) / 360.0 * scale
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * scale
    return x, y


def imagery(bbox: tuple[float, float, float, float], zoom: int = 10) -> tuple[Image.Image, tuple[float, float, float, float]]:
    west, south, east, north = bbox
    x0, y1 = tile_xy(west, south, zoom)
    x1, y0 = tile_xy(east, north, zoom)
    ix0, ix1 = int(x0), int(x1)
    iy0, iy1 = int(y0), int(y1)
    canvas = Image.new("RGB", ((ix1 - ix0 + 1) * 256, (iy1 - iy0 + 1) * 256))
    for tx in range(ix0, ix1 + 1):
        for ty in range(iy0, iy1 + 1):
            url = TILE.format(z=zoom, x=tx, y=ty)
            try:
                tile_response = requests.get(url, timeout=60)
                tile_response.raise_for_status()
                tile_bytes = tile_response.content
            except requests.RequestException:
                tile_bytes = subprocess.run(["curl.exe", "--tlsv1.2", "-L", "--fail", "--max-time", "60", url],
                                             check=True, capture_output=True).stdout
            image = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
            canvas.paste(image, ((tx - ix0) * 256, (ty - iy0) * 256))
    px0, py0 = tile_xy(west, north, zoom)
    px1, py1 = tile_xy(east, south, zoom)
    extent = (px0 - ix0, px1 - ix0, py1 - iy0, py0 - iy0)
    return canvas, extent


def polygons(features: list[dict]):
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") == "MultiPolygon":
            rings = [ring for polygon in geometry.get("coordinates", []) for ring in polygon]
        elif geometry.get("type") == "Polygon":
            rings = geometry.get("coordinates", [])
        else:
            rings = []
        for ring in rings:
            if len(ring) >= 3:
                yield [(float(x), float(y)) for x, y in ring]


def make_panel(title: str, config: dict) -> None:
    features = fetch_features(config["layer"], config["bbox"])
    image, _ = imagery(config["bbox"], zoom=10)
    fig, ax = plt.subplots(figsize=(8.2, 5.4), dpi=220)
    ax.imshow(image, extent=config["bbox"], origin="upper", alpha=0.88)
    for ring in polygons(features):
        ax.add_patch(Polygon(ring, closed=True, facecolor="#ff9f1c", edgecolor="#fff3d6", linewidth=0.18, alpha=0.22))
    cx, cy = config["center"]
    ax.scatter([cx], [cy], s=42, c="#d7191c", edgecolors="white", linewidths=1.2, zorder=10)
    ax.annotate("Municipal reference", (cx, cy), xytext=(8, 8), textcoords="offset points", color="white", fontsize=8,
                bbox={"facecolor": "black", "alpha": 0.65, "pad": 2})
    ax.set_xlim(config["bbox"][0], config["bbox"][2])
    ax.set_ylim(config["bbox"][1], config["bbox"][3])
    ax.set_title(f"{title} — public CAR property perimeters", loc="left", fontsize=11, weight="bold")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(color="white", linewidth=0.35, alpha=0.35)
    ax.text(0.01, 0.01, f"Public CAR WFS: {config['layer']} | Features drawn: {len(features)} (query cap) | Esri World Imagery",
            transform=ax.transAxes, fontsize=7, color="white", bbox={"facecolor": "black", "alpha": 0.65, "pad": 2})
    fig.tight_layout()
    fig.savefig(config["file"], bbox_inches="tight")
    plt.close(fig)
    return features


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    panels = []
    for title, config in AREAS.items():
        panels.append((title, config, make_panel(title, config)))
    fig, axes = plt.subplots(1, 2, figsize=(13.6, 5.1), dpi=220)
    for ax, (title, config, features) in zip(axes, panels):
        image, _ = imagery(config["bbox"], zoom=10)
        ax.imshow(image, extent=config["bbox"], origin="upper", alpha=0.88)
        for ring in polygons(features):
            ax.add_patch(Polygon(ring, closed=True, facecolor="#ff9f1c", edgecolor="#fff3d6", linewidth=0.16, alpha=0.22))
        cx, cy = config["center"]
        ax.scatter([cx], [cy], s=38, c="#d7191c", edgecolors="white", linewidths=1.0, zorder=10)
        ax.set_xlim(config["bbox"][0], config["bbox"][2])
        ax.set_ylim(config["bbox"][1], config["bbox"][3])
        ax.set_title(title, fontsize=10, weight="bold")
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(color="white", linewidth=0.3, alpha=0.35)
        ax.text(0.01, 0.01, f"CAR WFS features drawn: {len(features)} (query cap)", transform=ax.transAxes, fontsize=7,
                color="white", bbox={"facecolor": "black", "alpha": 0.65, "pad": 2})
    fig.suptitle("Close-up views of public CAR property perimeters", fontsize=14, weight="bold")
    fig.text(0.5, 0.01, "Perimeters are public CAR declarations shown for spatial context; they are not legal proof of ownership or compliance.",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0, 0.035, 1, 0.95))
    fig.savefig(OUT / "fig_cadastral_context_closeups.png", bbox_inches="tight")
    (OUT / "map_cadastral_context_metadata.json").write_text(json.dumps({
        title: {"layer": config["layer"], "bbox": config["bbox"], "features_returned": len(features)}
        for title, config, features in panels
    }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
