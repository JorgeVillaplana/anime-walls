# anime-wallpapers

Herramienta local para automatizar la búsqueda, previsualización, descarga y organización de fondos de pantalla de series de anime basada en tu lista de MyAnimeList.

## ⚠️ Aviso Legal Importante

**Este proyecto es una herramienta personal de código abierto sin ánimo de lucro.** Debes ser consciente de lo siguiente:

- **Las imágenes descargadas no son propiedad del autor del proyecto.** Todas proceden de terceros (Wallhaven, Konachan, Yande.re, Safebooru). El usuario es responsable de asegurar que cumple con la normativa de derechos de autor y copyright de su jurisdicción.
- **Contenido potencialmente NSFW:** Algunas fuentes contienen imágenes clasificadas como NSFW (Not Safe For Work), incluidas aquellas de naturaleza suggestive. Aunque la herramienta implementa filtros (purity levels, categoría SFW), no se garantiza una clasificación 100% precisa.
- **Responsabilidad del acceso:** Este proyecto está diseñado para **usuarios adultos en entornos privados.** Si menores de edad tienen acceso a la máquina donde se ejecuta o a los wallpapers descargados, **eres responsable de implementar controles parentales adecuados.** El repositorio puede contener imágenes NSFW en ejemplos o documentación.
- **Sin garantías:** El proyecto se proporciona "tal cual", sin garantías de ningún tipo, explícitas o implícitas.
- **Sin monetización:** Este proyecto no genera ingresos ni se comercializa. Es herramienta educativa y personal únicamente.

**Al usar este software aceptas estas condiciones y asumes toda responsabilidad por el contenido descargado y su distribución.**

---

## 📋 Características

- **Integración MAL:** Conecta con tu cuenta de MyAnimeList via OAuth2 + PKCE para obtener tu lista de animes completados.
- **Agrupación inteligente:** Filtra automáticamente series raíz eliminando temporadas duplicadas.
- **Búsqueda multi-fuente:** Busca wallpapers simultáneamente en:
    - **Wallhaven**
    - **Konachan**
    - **Yande.re**
    - **Safebooru**
- **Previsualización:** Ve (a priori) 20 wallpapers diferentes antes de descargar, con badges de fuente y resolución.
- **Clasificación flexible:** Organiza en tres carpetas (`aptos`, `no_aptos`, `valorar`) basadas en contenido.
- **Conversión automática:** Pillow convierte automáticamente cualquier formato a JPG sin intervención manual.
- **Detección de duplicados:** SHA256 hash evita guardar la misma imagen dos veces.
- **Backup externo:** Sincroniza imágenes a ImgBB con URL de borrado para recuperación.
- **Interfaz web local:** HTML/CSS/JS vanilla, sin dependencias frontend.
- **Cross-platform:** Windows y Linux con rutas configurables.
- **Una imagen por serie:** Máximo un wallpaper por serie, sustitución automática al descargar otro.
- **Resolución configurable:** Ajusta la resolución mínima desde la interfaz.
- **Búsqueda manual:** Busca términos alternativos si los nombres automáticos no funcionan.
- **Subida manual:** Arrastra o sube imágenes propias directamente desde la interfaz.
- **Cambio de estado:** Reclasifica wallpapers sin necesidad de descargar de nuevo.
- **Mantenimiento automático:** Verifica consistencia entre BD y sistema de archivos en startup.
- **Reset completo:** Borra todos los wallpapers locales y de ImgBB con doble confirmación.

---

## 🔧 Requisitos Previos

- **Python 3.10+**
- **Cuenta MyAnimeList** con lista de completados
- **Cuenta Wallhaven** (gratuita, necesita API key)
- **Cuenta ImgBB** (gratuita, para backups)
- **Disco duro externo** (recomendado pero opcional)
- **Windows 11 o Linux** con permisos de escritura en la ruta configurada

### Obtener Credenciales

#### MyAnimeList OAuth2

1. Ve a [myanimelist.net/apiconfig](https://myanimelist.net/apiconfig)
2. Haz clic en **"Create ID"**
3. Rellena:
    - Nombre: `anime-wallpapers` (o el que quieras)
    - Tipo: `other`
    - Redirect URL: `http://localhost:8000/auth/callback`
4. Guarda el **Client ID** (no necesitas Client Secret con PKCE)

#### Wallhaven API Key

1. Ve a [wallhaven.cc](https://wallhaven.cc/) y crea cuenta
2. Perfil → **Settings** → **Account** → **API Key**
3. Genera y copia la key

#### ImgBB API Key

1. Ve a [api.imgbb.com](https://api.imgbb.com/)
2. Inicia sesión
3. Copia tu **API Key**
4. Crea un álbum en ImgBB
5. Copia el ID del álbum desde la URL: `https://imgbb.com/album/ID_AQUI`

---

## 📦 Instalación

### 1. Clonar el Repositorio

```bash
git clone https://github.com/tuusuario/anime-wallpapers.git
cd anime-wallpapers
```

### 2. Crear Entorno Virtual

**Windows:**

```bash
python -m venv venv
venv\Scripts\activate
```

**Linux:**

```bash
python -m venv venv
source venv/bin/activate
```

### 3. Instalar Dependencias

```bash
pip install -r requirements.txt
```

### 4. Configurar `config.json`

Copia la plantilla y rellena tus credenciales:

```json
{
    "mal": {
        "client_id": "TU_CLIENT_ID",
        "client_secret": ""
    },
    "wallhaven": {
        "api_key": "TU_WALLHAVEN_API_KEY"
    },
    "imgbb": {
        "api_key": "TU_IMGBB_API_KEY",
        "album_id": "TU_ALBUM_ID"
    },
    "display": {
        "min_width": 1920,
        "min_height": 1080
    },
    "search": {
        "wallhaven_limit": 5,
        "konachan_limit": 5,
        "yandere_limit": 5,
        "safebooru_limit": 5
    },
    "paths": {
        "database": "tu_ruta/anime_wallpapers.db",
        "aptos": "tu_ruta/aptos",
        "no_aptos": "tu_ruta/no_aptos",
        "valorar": "tu_ruta/valorar"
    }
}
```

**Importante:** Las rutas pueden ser relativas (`./data/anime_wallpapers.db`) o absolutas. En Linux usa `/media/...` en lugar de `D:/...`.

### 5. Crear Carpetas (Opcional)

Las carpetas se crean automáticamente, pero puedes crearlas manualmente si lo prefieres:

```bash
mkdir -p /tu_ruta/{aptos,no_aptos,valorar}
```

---

## 🚀 Uso

### Arrancar el Servidor

**Windows:**

```bash
run.bat
```

**Linux:**

```bash
bash run.sh
```

El servidor se inicia en `http://localhost:8000`. Abre esa URL en tu navegador.

### Flujo Principal

1. **Autenticación:** Haz clic en "Conectar con MAL". Se abrirá tu navegador para autorizar la app.
2. **Lista de Series:** Verás tu lista de completados. Las series con wallpaper aparecen con borde verde.
3. **Buscar Wallpapers:** Haz clic en una serie para ver 20 opciones de wallpapers.
4. **Previsualizar:** Haz clic en una imagen para verla y clasificarla.
5. **Clasificar:** Elige `Apto`, `No apto` o `Valorar` antes de guardar.
6. **Cambiar:** Puedes cambiar el estado o descargar otro wallpaper para la misma serie.

### Búsqueda Manual

Si los nombres automáticos no encuentran resultados, usa el campo de búsqueda manual bajo los resultados.

### Subida Manual

Arrastra imágenes directamente a la zona de subida para importar tus propias imágenes.

### Configuración

- **Resolución mínima:** Ajústala desde la vista de detalle de serie.
- **Límites de búsqueda:** Cambia cuántas imágenes traer de cada fuente.
- **Reset completo:** Botón en el header para borrar todo (requiere doble confirmación).

---

## 📁 Estructura del Proyecto

```
anime-wallpapers/
├── backend/
│   ├── main.py                  # Endpoints FastAPI
│   ├── database.py              # Esquema y operaciones BD
│   ├── mal_client.py            # Autenticación y API MAL
│   ├── wallpaper_sources.py     # Búsqueda en fuentes externas
│   ├── image_utils.py           # Descarga, conversión, hash
│   └── config.py                # Carga de configuración
├── frontend/
│   ├── index.html               # Estructura
│   ├── style.css                # Estilos (tema oscuro)
│   └── app.js                   # Lógica de interfaz
├── data/                        # BD SQLite (local)
├── wallpapers/                  # Plantilla de carpetas
│   ├── aptos/
│   ├── no_aptos/
│   └── valorar/
├── config.json                  # Credenciales y rutas
├── requirements.txt             # Dependencias Python
├── run.bat                      # Script arranque Windows
├── run.sh                       # Script arranque Linux
└── README.md                    # Este archivo
```

---

## 🗄️ Base de Datos

Se usa SQLite para mantener registro de series y wallpapers descargados. Tablas principales:

- **`series`:** Entradas de anime (mal_id, títulos, tipo media, has_wallpaper)
- **`wallpapers`:** Wallpapers descargados (filename, source, resolution, status, hashes, URLs)

La BD se inicializa automáticamente en primer arranque.

---

## 🌐 APIs Utilizadas

### MyAnimeList

- Endpoint: `https://api.myanimelist.net/v2/`
- Autenticación: OAuth2 + PKCE
- Límite: 90 requests/minuto
- Documentación: [MAL API Docs](https://myanimelist.net/forum.php?topicid=1911056)

### Wallhaven

- Endpoint: `https://wallhaven.cc/api/v1/search`
- Autenticación: API Key
- Categorías: General, Anime, People
- Filtros: Purity, ratios, orden

### Konachan / Yande.re

- Protocolo: Moebooru
- Sin autenticación requerida
- Tags personalizables

### Safebooru

- Protocolo: Gelbooru
- SFW estricto
- Sin autenticación

### ImgBB

- Backup de imágenes
- API: `https://api.imgbb.com/1/upload`
- Delete URLs para borrado

---

## 🐛 Troubleshooting

### Error 401 en autenticación MAL

- Verifica que el `client_id` es correcto
- El navegador debe permitir redirecciones a `localhost:8000`

### Wallpapers no encontrados

- Algunos animes tienen nombres muy específicos o sin tags en las fuentes
- Usa la búsqueda manual con términos alternativos
- Comprueba que Wallhaven y las demás fuentes responden (status en Headers de red)

### ImgBB no sube

- Verifica que el `api_key` y `album_id` son correctos
- Comprueba permisos de escritura en la carpeta local
- El backup es opcional, no bloquea descarga local

### Rutas en Windows

- Usa `/` en lugar de `\\` en `config.json` para compatibilidad con Linux
- Ejemplo: `D:/mis documentos/anime_wallpapers.db`

---

## 📝 Licencia

Este proyecto se distribuye bajo licencia MIT. Eres libre de modificarlo y distribuirlo, pero asumes responsabilidad total sobre el contenido descargado.

**Debes incluir este aviso legal en cualquier distribución del código.**

---

## 🛠️ Stack Técnico

- **Backend:** Python 3.10+, FastAPI, SQLite, Pillow, httpx
- **Frontend:** HTML5, CSS3, JavaScript
- **APIs:** MAL, Wallhaven, Konachan, Yande.re, Safebooru, ImgBB
- **Almacenamiento:** SQLite local + ImgBB para backups

---

## 📞 Contacto & Contribuciones

Este es un proyecto personal. Para bugs o sugerencias, abre un issue en GitHub.

**No aceptamos PRs que cambien el aviso legal o que intenten monetizar el proyecto.**

---

## 🙏 Agradecimientos

- MyAnimeList por su API pública
- Wallhaven, Konachan, Yande.re y Safebooru por las fuentes de wallpapers
- ImgBB por el servicio de almacenamiento
- FastAPI y Pillow por facilitar el desarrollo

---

**Última actualización:** Junio 2026

⚠️ **Recuerda:** Eres responsable del contenido que descargas y su cumplimiento legal. Usa responsablemente.