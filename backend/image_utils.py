import hashlib
import base64
import httpx
from pathlib import Path
from PIL import Image
from config import config
import re

# ── DESCARGA ──────────────────────────────────────────────────────────────────

async def download_image(url: str) -> bytes:
    """Descarga una imagen desde una URL y devuelve los bytes en crudo."""
    async with httpx.AsyncClient() as client:
        response = await client.get(url, timeout=30, follow_redirects=True)
        response.raise_for_status()
        return response.content

# ── HASH ──────────────────────────────────────────────────────────────────────
# El hash SHA256 es una huella digital del archivo.
# Dos archivos idénticos siempre producen el mismo hash.
# Dos archivos distintos (aunque sean muy parecidos) producen hashes distintos.
# Lo usamos para detectar duplicados antes de guardar.

def calculate_hash(image_bytes: bytes) -> str:
    """Calcula el SHA256 de los bytes de una imagen y lo devuelve como string hex."""
    return hashlib.sha256(image_bytes).hexdigest()

# ── CONVERSIÓN ────────────────────────────────────────────────────────────────

def convert_to_jpg(image_bytes: bytes) -> bytes:
    """
    Convierte los bytes de cualquier formato de imagen a JPG.
    Maneja el caso de imágenes RGBA (con transparencia) convirtiéndolas
    a RGB antes de guardar como JPG, ya que JPG no soporta transparencia.
    Devuelve los bytes del JPG resultante.
    """
    from io import BytesIO

    input_buffer  = BytesIO(image_bytes)
    output_buffer = BytesIO()

    img = Image.open(input_buffer)

    if img.mode in ("RGBA", "LA", "P"):
        # Crear fondo blanco y pegar la imagen encima para eliminar transparencia
        background = Image.new("RGB", img.size, (255, 255, 255))
        if img.mode == "P":
            img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1] if img.mode == "RGBA" else None)
        img = background
    elif img.mode != "RGB":
        img = img.convert("RGB")

    img.save(output_buffer, format="JPEG", quality=95, optimize=True)
    return output_buffer.getvalue()

def get_resolution(image_bytes: bytes) -> tuple[int, int]:
    """Devuelve (ancho, alto) de una imagen a partir de sus bytes."""
    from io import BytesIO
    img = Image.open(BytesIO(image_bytes))
    return img.size  # (width, height)

# ── GUARDADO LOCAL ────────────────────────────────────────────────────────────

def save_image(image_bytes: bytes, filename: str, status: str) -> Path:
    """
    Guarda los bytes de una imagen en la carpeta correspondiente al status.
    Devuelve la ruta completa donde se guardó.
    """
    folder = Path(config["paths"][status])
    dest   = folder / filename
    dest.write_bytes(image_bytes)
    return dest

# ── BACKUP EN IMGBB ───────────────────────────────────────────────────────────
# ImgBB espera la imagen codificada en base64 dentro de un POST.
# Devuelve una URL pública permanente donde está alojada la imagen.

async def upload_to_imgbb(image_bytes: bytes, filename: str) -> tuple[str, str] | None:
    """
    Sube una imagen a ImgBB y devuelve la URL pública y la URL de eliminación.
    Devuelve None si falla, para no bloquear el flujo principal.
    """
    api_key = config["imgbb"]["api_key"]
    image_b64 = base64.b64encode(image_bytes).decode("utf-8")
    album = config["imgbb"]["album_id"]
 
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.imgbb.com/1/upload",
                data={
                    "key":  api_key,
                    "image": image_b64,
                    "album": album,
                    "name": filename
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            return data["data"]["url"], data["data"]["delete_url"]
    except Exception as e:
        print(f"[ImgBB ERROR] {type(e).__name__}: {e}")
        return None


# ── FLUJO COMPLETO ────────────────────────────────────────────────────────────

async def process_and_save(
    url:       str,
    series_id: int,
    series_title: str,
    source:    str,
    status:    str,
) -> dict:
    """
    Orquesta el flujo completo para una imagen seleccionada:
      1. Descarga
      2. Calcula hash y comprueba duplicado (lanza ValueError si lo es)
      3. Convierte a JPG
      4. Obtiene resolución real
      5. Guarda en carpeta local
      6. Sube a ImgBB (backup, no bloquea si falla)
      7. Devuelve el dict con todos los datos para insertar en la BD
    """
    from database import get_connection

    # 1. Descarga
    raw_bytes = await download_image(url)

    # 2. Hash y duplicados
    file_hash = calculate_hash(raw_bytes)
    conn = get_connection()
    existing = conn.execute(
        "SELECT id FROM wallpapers WHERE file_hash = ?", (file_hash,)
    ).fetchone()
    conn.close()
    if existing:
        raise ValueError(f"Duplicado detectado: este archivo ya existe en la BD.")

    # 3. Conversión a JPG
    jpg_bytes = convert_to_jpg(raw_bytes)

    # 4. Resolución
    width, height = get_resolution(jpg_bytes)

    # 5. Nombre de archivo y guardado local
    safe_title = re.sub(r'[^\w\s-]', '', series_title).strip().replace(' ', '_')
    filename = f"{safe_title}.jpg"
    save_image(jpg_bytes, filename, status)

    # 6. Backup ImgBB
    imgbb_result = await upload_to_imgbb(jpg_bytes, filename)
    imgbb_url, imgbb_delete_url = imgbb_result if imgbb_result else (None, None)

    # 7. Devolver datos para la BD
    return {
        "filename":   filename,
        "source":     source,
        "source_url": url,
        "width":      width,
        "height":     height,
        "imgbb_url":  imgbb_url,
        "imgbb_delete_url": imgbb_delete_url,
        "status":     status,
        "file_hash":  file_hash,
    }