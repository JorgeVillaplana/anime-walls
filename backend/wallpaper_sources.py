import httpx
from config import config

WALLHAVEN_API = "https://wallhaven.cc/api/v1/search"
SAFEBOORU_API = "https://safebooru.org/index.php"

# ── WALLHAVEN ─────────────────────────────────────────────────────────────────

async def search_wallhaven(query: str, limit: int = 5) -> list[dict]:
    """
    Busca wallpapers en Wallhaven.
    Filtra por resolución mínima configurada y categoría anime.
    """
    min_w = config["display"]["min_width"]
    min_h = config["display"]["min_height"]

    params = {
        "apikey":     config["wallhaven"]["api_key"],
        "q":          query,
        "categories": "110",        # bit: general|anime|people
        "purity":     "110",        # bit: sfw|sketchy|nsfw
        "atleast":    f"{min_w}x{min_h}",
        "sorting":    "relevance",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(WALLHAVEN_API, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()

    results = []
    for item in data.get("data", [])[:limit]:
        results.append({
            "source":      "wallhaven",
            "id":          item["id"],
            "preview_url": item["thumbs"]["large"],  # Thumbnail para previsualizar
            "full_url":    item["path"],              # URL de la imagen a tamaño completo
            "resolution":  item["resolution"],        # Ej: "1920x1080"
            "width":       item["dimension_x"],
            "height":      item["dimension_y"],
        })

    return results


def _normalize_tag(query: str) -> str:
    return query.strip().lower().replace(" ", "_")


# ── SAFEBOORU ─────────────────────────────────────────────────────────────────

async def search_safebooru(query: str, limit: int = 5) -> list[dict]:
    min_w = config["display"]["min_width"]
    min_h = config["display"]["min_height"]
    tag   = _normalize_tag(query)

    params = {
        "page":  "dapi",
        "s":     "post",
        "q":     "index",
        "tags":  tag,
        "limit": limit * 3,
        "json":  1,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(SAFEBOORU_API, params=params, timeout=10)
        response.raise_for_status()
        # Safebooru devuelve body vacío cuando no hay resultados
        if not response.content or not response.text.strip():
            return []
        data = response.json()

    # Safebooru devuelve {"post": [...]} o directamente una lista según la versión
    items = data if isinstance(data, list) else data.get("post", [])

    results = []
    for item in items:
        width  = item.get("width", 0)
        height = item.get("height", 0)
        if width < min_w or height < min_h:
            continue
        image_url = f"https://safebooru.org/images/{item['directory']}/{item['image']}"
        preview_url = f"https://safebooru.org/thumbnails/{item['directory']}/thumbnail_{item['image']}"
        results.append({
            "source":      "safebooru",
            "id":          str(item["id"]),
            "preview_url": preview_url,
            "full_url":    image_url,
            "resolution":  f"{width}x{height}",
            "width":       width,
            "height":      height,
        })
        if len(results) >= limit:
            break

    return results

# ── BÚSQUEDA COMBINADA ────────────────────────────────────────────────────────

async def search_all(
    title_english:   str | None,
    title_romaji:    str | None,
    title_japanese:  str | None,
    wallhaven_limit: int = 5,
    safebooru_limit: int = 5,
) -> list[dict]:
    titles = [t for t in [title_english, title_romaji, title_japanese] if t]

    wallhaven_results = []
    safebooru_results = []

    for title in titles:
        if not wallhaven_results:
            wallhaven_results = await search_wallhaven(title, limit=wallhaven_limit)
        if not safebooru_results:
            safebooru_results = await search_safebooru(title, limit=safebooru_limit)
        if all([wallhaven_results, safebooru_results]):
            break

    return wallhaven_results + safebooru_results