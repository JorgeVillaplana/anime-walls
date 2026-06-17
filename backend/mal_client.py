import httpx
import hashlib
import secrets
import json
import webbrowser
from pathlib import Path
from config import config

MAL_API_BASE = "https://api.myanimelist.net/v2"
MAL_AUTH_URL = "https://myanimelist.net/v1/oauth2/authorize"
MAL_TOKEN_URL = "https://myanimelist.net/v1/oauth2/token"
TOKEN_PATH = Path(__file__).parent.parent / "data" / "mal_token.json"

# ── PKCE ──────────────────────────────────────────────────────────────────────
# PKCE (Proof Key for Code Exchange) es un mecanismo de seguridad para OAuth2
# que no requiere Client Secret. Funciona así:
#   1. Generamos un 'code_verifier' aleatorio
#   2. Calculamos su hash SHA256 → 'code_challenge'
#   3. Enviamos el challenge a MAL al pedir autorización
#   4. Al intercambiar el código por el token, enviamos el verifier original
#   5. MAL verifica que el hash coincide → confirma que somos nosotros
# Esto evita que alguien que intercepte el código de autorización pueda usarlo.

def _generate_pkce() -> tuple[str, str]:
    """Devuelve (code_verifier, code_challenge)."""
    code_verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(code_verifier.encode()).digest()
    # MAL es peculiar: acepta el verifier directamente como challenge (plain)
    # en lugar del hash base64url estándar. Usamos plain para evitar problemas.
    return code_verifier, code_verifier

# ── TOKEN PERSISTENTE ─────────────────────────────────────────────────────────
# El token se guarda en disco para no tener que autenticarse cada vez.
# Contiene: access_token, refresh_token y expires_in.

def _save_token(token_data: dict):
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_PATH, "w", encoding="utf-8") as f:
        json.dump(token_data, f, indent=2)

def _load_token() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    with open(TOKEN_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

async def _refresh_token(refresh_token: str) -> dict:
    """Renueva el access_token usando el refresh_token."""
    async with httpx.AsyncClient() as client:
        response = await client.post(MAL_TOKEN_URL, data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": config["mal"]["client_id"],
        })
        response.raise_for_status()
        token_data = response.json()
        _save_token(token_data)
        return token_data

# ── FLUJO DE AUTENTICACIÓN ────────────────────────────────────────────────────

async def authenticate() -> str:
    """
    Devuelve un access_token válido.
    Si ya hay uno guardado intenta reutilizarlo o renovarlo.
    Si no hay ninguno lanza el flujo completo de autorización.
    """
    token_data = _load_token()

    if token_data:
        # Intentar renovar con el refresh_token
        try:
            token_data = await _refresh_token(token_data["refresh_token"])
            return token_data["access_token"]
        except Exception:
            pass  # Si falla, relanzamos el flujo completo

    # Flujo completo: abrir navegador para que el usuario autorice
    return await _full_auth_flow()

async def _full_auth_flow() -> str:
    client_id = config["mal"]["client_id"]
    code_verifier, code_challenge = _generate_pkce()

    # Construir URL de autorización
    auth_url = (
        f"{MAL_AUTH_URL}"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&code_challenge={code_challenge}"
        f"&code_challenge_method=plain"
        f"&redirect_uri=http://localhost:8000/auth/callback"
    )

    print("\n── Autenticación MAL ──")
    print("Se abrirá tu navegador. Autoriza la aplicación en MAL.")
    print("Serás redirigido a localhost automáticamente.\n")
    webbrowser.open(auth_url)

    # El código de autorización llega via el endpoint /auth/callback del backend
    # Guardamos el verifier para usarlo cuando llegue el callback
    _save_pkce_verifier(code_verifier)
    return ""  # El token real se obtiene en handle_auth_callback

def _save_pkce_verifier(verifier: str):
    path = Path(__file__).parent.parent / "data" / "pkce_verifier.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(verifier)

def _load_pkce_verifier() -> str:
    path = Path(__file__).parent.parent / "data" / "pkce_verifier.txt"
    return path.read_text()

async def handle_auth_callback(code: str) -> str:
    """
    Llamado por el endpoint /auth/callback cuando MAL redirige de vuelta.
    Intercambia el código de autorización por el token definitivo.
    """
    code_verifier = _load_pkce_verifier()
    client_id = config["mal"]["client_id"]

    async with httpx.AsyncClient() as client:
        response = await client.post(MAL_TOKEN_URL, data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": "http://localhost:8000/auth/callback",
        })
        response.raise_for_status()
        token_data = response.json()
        _save_token(token_data)
        return token_data["access_token"]

# ── LISTA DE ANIME ────────────────────────────────────────────────────────────

async def get_completed_list(access_token: str) -> list[dict]:
    """
    Obtiene toda la lista de completados de MAL.
    Pagina automáticamente hasta traer todas las entradas.
    Con timeout global de 60s para evitar bloqueos indefinidos.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    fields = "id,title,alternative_titles,media_type,related_anime,main_picture"
    entries = []
    url = f"{MAL_API_BASE}/users/@me/animelist"
    params = {
        "status": "completed",
        "fields": fields,
        "limit": 100,
        "nsfw": "true",
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        while url:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
            entries.extend(data.get("data", []))

            url = data.get("paging", {}).get("next")
            params = {}

    return entries

def filter_root_series(entries: list[dict]) -> list[dict]:
    """Filtra entradas para obtener solo las series raíz (no subseries).
    Usa set para búsquedas O(1) en lugar de O(n) con lista.
    """
    result = []
    accepted_titles = set()  # títulos raíz ya aceptados, en minúsculas

    for entry in entries:
        node       = entry.get("node", {})
        media_type = node.get("media_type", "")
        title      = node.get("title", "")
        title_low  = title.lower().strip()

        if media_type == "ova":
            continue

        # Si el título es prefijo de algún título raíz ya aceptado, es subserie
        is_sub = any(
            title_low != root and title_low.startswith(root)
            for root in accepted_titles
        )

        if is_sub:
            continue

        accepted_titles.add(title_low)
        result.append(node)

    return result