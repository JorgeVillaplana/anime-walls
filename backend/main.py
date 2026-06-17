import asyncio
import httpx
from pathlib import Path
from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel

from config import config, CONFIG_PATH
from database import init_db, get_connection
from mal_client import authenticate, handle_auth_callback, get_completed_list, filter_root_series, _load_token
from wallpaper_sources import search_all
from image_utils import process_and_save

app = FastAPI()

# ── ARRANQUE ──────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Se ejecuta al arrancar el servidor. Inicializa la BD."""
    init_db()
    await check_files()  # Limpia registros huérfanos al arrancar

# ── AUTENTICACIÓN MAL ─────────────────────────────────────────────────────────

@app.get("/auth/login")
async def auth_login():
    """
    Lanza el flujo de autenticación con MAL.
    Abre el navegador en la página de autorización de MAL.
    """
    await authenticate()
    return {"status": "Abre tu navegador y autoriza la aplicación en MAL."}

@app.get("/auth/callback")
async def auth_callback(code: str = Query(...)):
    """
    MAL redirige aquí tras la autorización con un código temporal.
    Lo intercambiamos por el token definitivo.
    """
    await handle_auth_callback(code)
    # Redirigir al frontend tras autenticación exitosa
    return RedirectResponse(url="/")

@app.get("/auth/status")
async def auth_status():
    """Comprueba si ya hay un token guardado."""
    token_path = Path(__file__).parent.parent / "data" / "mal_token.json"
    return {"authenticated": token_path.exists()}

# ── SERIES ────────────────────────────────────────────────────────────────────

@app.get("/series")
async def get_series():
    """
    Devuelve la lista de series raíz del usuario en MAL,
    enriquecida con el estado en la BD local (has_wallpaper, status).
    """
    from mal_client import _load_token
    token_data = _load_token()
    if not token_data:
        raise HTTPException(status_code=401, detail="No autenticado con MAL.")

    # Refrescar token y obtener lista
    from mal_client import _refresh_token
    try:
        token_data = await _refresh_token(token_data["refresh_token"])
    except Exception:
        raise HTTPException(status_code=401, detail="Token expirado, vuelve a autenticarte.")

    entries    = await get_completed_list(token_data["access_token"])
    root_series = filter_root_series(entries)

    # Enriquecer con datos locales de la BD
    conn = get_connection()
    result = []
    for series in root_series:
        mal_id = series["id"]
        row = conn.execute(
            "SELECT has_wallpaper, id FROM series WHERE mal_id = ?", (mal_id,)
        ).fetchone()

        titles = series.get("alternative_titles", {})
        picture = series.get("main_picture", {})
        result.append({
            "mal_id":          mal_id,
            "title_romaji":    series.get("title", ""),
            "title_english":   titles.get("en", ""),
            "title_japanese":  titles.get("ja", ""),
            "media_type":      series.get("media_type", ""),
            "has_wallpaper":   bool(row["has_wallpaper"]) if row else False,
            "local_id":        row["id"] if row else None,
            "cover_url":       picture.get("large") or picture.get("medium") or "",
        })
    conn.close()

    return result

@app.post("/series/{mal_id}/sync")
async def sync_series(mal_id: int):
    """
    Inserta una serie en la BD local si no existe todavía.
    Se llama automáticamente al entrar en la vista de una serie.
    Optimizado: evita consultas duplicadas.
    """
    from mal_client import _load_token, _refresh_token
    token_data = _load_token()
    if not token_data:
        raise HTTPException(status_code=401, detail="No autenticado.")

    token_data = await _refresh_token(token_data["refresh_token"])

    # Obtener datos frescos de esta serie concreta desde MAL
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.myanimelist.net/v2/anime/{mal_id}",
            headers=headers,
            params={"fields": "id,title,alternative_titles,media_type"}
        )
        response.raise_for_status()
        data = response.json()

    titles = data.get("alternative_titles", {})
    conn   = get_connection()
    try:
        # Intentar insertar si no existe (INSERT OR IGNORE)
        conn.execute(
            """INSERT OR IGNORE INTO series (mal_id, title_romaji, title_english, title_japanese, media_type)
               VALUES (?, ?, ?, ?, ?)""",
            (
                mal_id,
                data.get("title", ""),
                titles.get("en", ""),
                titles.get("ja", ""),
                data.get("media_type", ""),
            )
        )
        conn.commit()

        # Obtener el ID local de una sola vez
        row = conn.execute(
            "SELECT id FROM series WHERE mal_id = ?", (mal_id,)
        ).fetchone()
        local_id = row["id"]
    finally:
        conn.close()

    return {"local_id": local_id}

# ── BÚSQUEDA DE WALLPAPERS ────────────────────────────────────────────────────

@app.get("/wallpapers/search/{mal_id}")
async def search_wallpapers(mal_id: int):
    """
    Busca wallpapers para una serie en Wallhaven y Konachan.
    También devuelve el wallpaper actual si la serie ya tiene uno.
    """
    conn = get_connection()
    series = conn.execute(
        "SELECT * FROM series WHERE mal_id = ?", (mal_id,)
    ).fetchone()

    current_wallpaper = None
    if series:
        wp = conn.execute(
            "SELECT * FROM wallpapers WHERE series_id = ?", (series["id"],)
        ).fetchone()
        if wp:
            current_wallpaper = dict(wp)

    conn.close()

    if not series:
        raise HTTPException(status_code=404, detail="Serie no encontrada en BD local. Llama a /sync primero.")

    results = await search_all(
        title_english   = series["title_english"] or None,
        title_romaji    = series["title_romaji"]  or None,
        title_japanese  = series["title_japanese"] or None,
        wallhaven_limit = config["search"]["wallhaven_limit"],
        konachan_limit  = config["search"]["konachan_limit"],
        yandere_limit   = config["search"]["yandere_limit"],
        safebooru_limit = config["search"]["safebooru_limit"],
    )

    return {
        "results":          results,
        "current_wallpaper": current_wallpaper,
    }

@app.get("/config/search")
async def get_search_config():
    return {
        "wallhaven_limit": config["search"]["wallhaven_limit"],
        "konachan_limit":  config["search"]["konachan_limit"],
        "yandere_limit":   config["search"]["yandere_limit"],
        "safebooru_limit": config["search"]["safebooru_limit"]
    }

@app.post("/config/search")
async def save_search_config(data: dict):
    wh = data.get("wallhaven_limit")
    kn = data.get("konachan_limit")
    yd = data.get("yandere_limit")
    sb = data.get("safebooru_limit")
    
    if not all([wh, kn, yd, sb]) or not all(1 <= v <= 20 for v in [wh, kn, yd, sb]):
        raise HTTPException(status_code=400, detail="Todos los límites deben estar entre 1 y 20.")
    
    config["search"]["wallhaven_limit"] = wh
    config["search"]["konachan_limit"]  = kn
    config["search"]["yandere_limit"]   = yd
    config["search"]["safebooru_limit"] = sb
    
    import json
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)
    return {"status": "ok"}

# ── DESCARGA Y CLASIFICACIÓN ──────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    mal_id:     int
    source_url: str
    source:     str      # 'wallhaven' | 'konachan' | 'yandere' | 'safebooru'
    status:     str      # 'aptos' | 'no_aptos' | 'valorar'

@app.post("/wallpapers/download")
async def download_wallpaper(req: DownloadRequest):
    """
    Descarga un wallpaper seleccionado, lo procesa y lo guarda.
    Si la serie ya tenía wallpaper, borra el anterior SOLO si el nuevo se procesa exitosamente.
    Transaccional: si algo falla, no se pierde el wallpaper anterior.
    """
    if req.status not in ("aptos", "no_aptos", "valorar"):
        raise HTTPException(status_code=400, detail="Status inválido.")

    conn = get_connection()
    try:
        # Obtener serie y wallpaper existente en una sola consulta
        series = conn.execute(
            "SELECT * FROM series WHERE mal_id = ?", (req.mal_id,)
        ).fetchone()
        if not series:
            raise HTTPException(status_code=404, detail="Serie no encontrada.")

        series_id = series["id"]
        existing_wp = conn.execute(
            "SELECT * FROM wallpapers WHERE series_id = ?", (series_id,)
        ).fetchone()
    finally:
        conn.close()

    # Procesar y guardar la NUEVA imagen PRIMERO (antes de tocar la anterior)
    try:
        image_data = await process_and_save(
            url           = req.source_url,
            series_id     = series_id,
            series_title  = series["title_romaji"],
            source        = req.source,
            status        = req.status,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando imagen: {str(e)}")

    # Si llegamos aquí, la nueva imagen está guardada. Ahora podemos eliminar la anterior.
    if existing_wp:
        try:
            # Borrar archivo local
            old_path = Path(config["paths"][existing_wp["status"]]) / existing_wp["filename"]
            if old_path.exists():
                old_path.unlink()

            # Borrar de ImgBB (no-bloqueante, error no es crítico)
            if existing_wp.get("imgbb_delete_url"):
                async with httpx.AsyncClient() as client:
                    try:
                        await client.get(existing_wp["imgbb_delete_url"], timeout=10)
                    except Exception:
                        pass  # Si falla ImgBB, continuamos de todas formas

            # Borrar de la BD
            conn = get_connection()
            try:
                conn.execute("DELETE FROM wallpapers WHERE id = ?", (existing_wp["id"],))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            # Log pero no falla: la nueva imagen ya está guardada
            print(f"[WARN] Error limpiando wallpaper anterior: {e}")

    # Insertar el nuevo wallpaper en la BD
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO wallpapers
               (series_id, filename, source, source_url, resolution_w, resolution_h,
                imgbb_url, imgbb_delete_url, status, file_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                series_id,
                image_data["filename"],
                image_data["source"],
                image_data["source_url"],
                image_data["width"],
                image_data["height"],
                image_data["imgbb_url"],
                image_data.get("imgbb_delete_url"),
                image_data["status"],
                image_data["file_hash"],
            )
        )
        conn.execute(
            "UPDATE series SET has_wallpaper = 1 WHERE id = ?", (series_id,)
        )
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "filename": image_data["filename"]}

@app.post("/wallpapers/upload")
async def upload_manual(
    mal_id: int       = Form(...),
    status: str       = Form(...),
    file:   UploadFile = File(...),
):
    """
    Permite subir manualmente un wallpaper desde el disco local.
    Mismo flujo que la descarga: reemplaza el anterior si existe.
    """
    if status not in ("aptos", "no_aptos", "valorar"):
        raise HTTPException(status_code=400, detail="Status inválido.")

    conn = get_connection()
    try:
        series = conn.execute(
            "SELECT * FROM series WHERE mal_id = ?", (mal_id,)
        ).fetchone()
        if not series:
            raise HTTPException(status_code=404, detail="Serie no encontrada.")

        series_id = series["id"]
        existing_wp = conn.execute(
            "SELECT * FROM wallpapers WHERE series_id = ?", (series_id,)
        ).fetchone()
    finally:
        conn.close()

    # Leer bytes del archivo subido
    from image_utils import calculate_hash, convert_to_jpg, get_resolution, save_image, upload_to_imgbb

    raw_bytes = await file.read()
    file_hash = calculate_hash(raw_bytes)

    # Verificar duplicado ANTES de procesar
    conn = get_connection()
    try:
        existing_hash = conn.execute(
            "SELECT id FROM wallpapers WHERE file_hash = ?", (file_hash,)
        ).fetchone()
    finally:
        conn.close()

    if existing_hash:
        raise HTTPException(status_code=409, detail="Duplicado: este archivo ya existe en la BD.")

    # Procesar imagen (convertir a JPG, obtener resolución, guardar)
    try:
        jpg_bytes = convert_to_jpg(raw_bytes)
        width, height = get_resolution(jpg_bytes)
        filename = f"{series_id}_{file_hash[:8]}.jpg"
        save_image(jpg_bytes, filename, status)
        imgbb_result = await upload_to_imgbb(jpg_bytes, filename)
        imgbb_url, imgbb_delete_url = imgbb_result if imgbb_result else (None, None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando imagen: {str(e)}")

    # Eliminar wallpaper anterior si existe (DESPUÉS de procesar el nuevo)
    if existing_wp:
        try:
            old_path = Path(config["paths"][existing_wp["status"]]) / existing_wp["filename"]
            if old_path.exists():
                old_path.unlink()

            # Borrar de ImgBB (no-bloqueante)
            if existing_wp.get("imgbb_delete_url"):
                async with httpx.AsyncClient() as client:
                    try:
                        await client.get(existing_wp["imgbb_delete_url"], timeout=10)
                    except Exception:
                        pass

            # Borrar de la BD
            conn = get_connection()
            try:
                conn.execute("DELETE FROM wallpapers WHERE id = ?", (existing_wp["id"],))
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            print(f"[WARN] Error limpiando wallpaper anterior: {e}")

    # Insertar nuevo wallpaper
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO wallpapers
               (series_id, filename, source, source_url, resolution_w, resolution_h,
                imgbb_url, imgbb_delete_url, status, file_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (series_id, filename, "manual", "", width, height, imgbb_url, imgbb_delete_url, status, file_hash)
        )
        conn.execute("UPDATE series SET has_wallpaper = 1 WHERE id = ?", (series_id,))
        conn.commit()
    finally:
        conn.close()

    return {"status": "ok", "filename": filename}

# ── CAMBIO DE STATUS ──────────────────────────────────────────────────────────

class StatusUpdate(BaseModel):
    mal_id: int
    status: str

@app.patch("/wallpapers/status")
async def update_status(req: StatusUpdate):
    """
    Cambia el status de un wallpaper (aptos/no_aptos/valorar).
    Mueve el archivo físico a la carpeta correspondiente.
    """
    if req.status not in ("aptos", "no_aptos", "valorar"):
        raise HTTPException(status_code=400, detail="Status inválido.")

    conn   = get_connection()
    series = conn.execute(
        "SELECT * FROM series WHERE mal_id = ?", (req.mal_id,)
    ).fetchone()
    if not series:
        raise HTTPException(status_code=404, detail="Serie no encontrada.")

    wp = conn.execute(
        "SELECT * FROM wallpapers WHERE series_id = ?", (series["id"],)
    ).fetchone()
    if not wp:
        raise HTTPException(status_code=404, detail="Esta serie no tiene wallpaper.")

    # Mover archivo físico
    old_path = Path(config["paths"][wp["status"]]) / wp["filename"]
    new_path = Path(config["paths"][req.status])   / wp["filename"]

    if old_path.exists():
        old_path.rename(new_path)

    conn.execute(
        "UPDATE wallpapers SET status = ? WHERE id = ?", (req.status, wp["id"])
    )
    conn.commit()
    conn.close()

    return {"status": "ok"}

@app.post("/maintenance/check-files")
async def check_files():
    """
    Comprueba que cada wallpaper registrado en la BD existe físicamente.
    Si no existe, limpia la BD y actualiza has_wallpaper de la serie.
    """
    conn    = get_connection()
    orphans = []

    wallpapers = conn.execute("SELECT * FROM wallpapers").fetchall()
    for wp in wallpapers:
        path = Path(config["paths"][wp["status"]]) / wp["filename"]
        if not path.exists():
            orphans.append(wp["id"])
            conn.execute("DELETE FROM wallpapers WHERE id = ?", (wp["id"],))
            conn.execute(
                "UPDATE series SET has_wallpaper = 0 WHERE id = ?", (wp["series_id"],)
            )

    conn.commit()
    conn.close()

    return {"cleaned": len(orphans), "ids": orphans}

#DEBUG
@app.get("/debug/series/{mal_id}")
async def debug_series(mal_id: int):
    token_data = _load_token()
    if not token_data:
        raise HTTPException(status_code=401, detail="No autenticado.")
    
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.myanimelist.net/v2/anime/{mal_id}",
            headers=headers,
            params={"fields": "id,title,related_anime,media_type"}
        )
        response.raise_for_status()
        return response.json()
    
@app.get("/debug/mylist")
async def debug_mylist():
    token_data = _load_token()
    if not token_data:
        raise HTTPException(status_code=401, detail="No autenticado.")
    
    headers = {"Authorization": f"Bearer {token_data['access_token']}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.myanimelist.net/v2/users/@me/animelist",
            headers=headers,
            params={
                "status": "completed",
                "fields": "id,title,media_type,related_anime",
                "limit": 3,
            }
        )
        response.raise_for_status()
        return response.json()
    
@app.post("/maintenance/reset")
async def reset_all():
    """
    Borra todos los wallpapers del disco y limpia la BD.
    Operación irreversible.
    """
    conn = get_connection()
    wallpapers = conn.execute("SELECT * FROM wallpapers").fetchall()

    async with httpx.AsyncClient() as client:
        for wp in wallpapers:
            # Borrar archivo local
            path = Path(config["paths"][wp["status"]]) / wp["filename"]
            if path.exists():
                path.unlink()
            # Borrar de ImgBB
            if wp["imgbb_delete_url"]:
                try:
                    await client.get(wp["imgbb_delete_url"], timeout=10)
                except Exception:
                    pass  # Si falla no es crítico

    conn.execute("DELETE FROM wallpapers")
    conn.execute("UPDATE series SET has_wallpaper = 0")
    conn.commit()
    conn.close()

    return {"status": "ok"}
# ── FRONTEND ──────────────────────────────────────────────────────────────────
# Sirve los archivos estáticos del frontend desde /frontend
# Debe ir al final para no interceptar las rutas del API

frontend_path = Path(__file__).parent.parent / "frontend"

@app.get("/config/resolution")
async def get_resolution():
    return {
        "min_width":  config["display"]["min_width"],
        "min_height": config["display"]["min_height"],
    }

@app.post("/config/resolution")
async def save_resolution(data: dict):
    w = data.get("min_width")
    h = data.get("min_height")
    if not w or not h:
        raise HTTPException(status_code=400, detail="Faltan parámetros.")

    config["display"]["min_width"]  = w
    config["display"]["min_height"] = h

    import json
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4)

    return {"status": "ok"}
@app.get("/wallpapers/search-term")
async def search_by_term(q: str = Query(...)):
    """Búsqueda libre por término, para cuando los títulos automáticos no dan resultado."""
    from wallpaper_sources import search_all
    results = await search_all(
        title_english  = q,
        title_romaji   = None,
        title_japanese = None,
        wallhaven_limit = config["search"]["wallhaven_limit"],
        konachan_limit  = config["search"]["konachan_limit"],
        yandere_limit   = config["search"]["yandere_limit"],
        safebooru_limit = config["search"]["safebooru_limit"],
    )
    return {"results": results}
app.mount("/", StaticFiles(directory=str(frontend_path), html=True), name="frontend")