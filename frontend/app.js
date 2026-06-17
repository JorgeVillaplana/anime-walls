// URL base de la API. Vacía = localhost (frontend y backend en mismo servidor)
const API = "";

// ── DEBOUNCE ───────────────────────────────────────────────────────────────
// Retrasa la ejecución de una función hasta que dejan de llamarla por N milisegundos.
// Útil para búsqueda: evita hacer request por cada letra que tipea el usuario.
// Ej: si delay=300ms y el usuario tipea "anime", solo ejecuta después de escribir la 'e'
function debounce(func, delay) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout); // Cancela ejecución anterior si existe
    timeout = setTimeout(() => func(...args), delay); // Espera N ms antes de ejecutar
  };
}

// ── ESTADO GLOBAL ──────────────────────────────────────────────────────────
// Almacena toda la información de la aplicación en tiempo real.
// Se actualiza según interactúa el usuario y se reciben datos del servidor.
const state = {
  series: [], // Lista completa de series del usuario
  filtered: [], // Series tras aplicar filtros de búsqueda
  currentSeries: null, // Serie seleccionada actualmente
  currentWallpapers: [], // Wallpapers encontrados para la serie actual
  currentWallpaper: null, // Wallpaper ya guardado para la serie actual
  selectedWp: null, // Wallpaper seleccionado para descargar/clasificar
  pendingStatus: null, // Estado pendiente a asignar (aptos/no_aptos/valorar)
  resolution: { w: 1920, h: 1080 }, // Resolución mínima para filtrar wallpapers
  titlePref: "romaji", // Preferencia de idioma para títulos
  scrollY: 0, // Posición de scroll guardada antes de cambiar vista
  loginTimeout: null, // Referencia al intervalo de polling de login
};

// ── UTILIDADES ─────────────────────────────────────────────────────────────
// Atajos y funciones auxiliares usadas en todo el código
function $(id) {
  return document.getElementById(id);
}

// Muestra un mensaje temporal (notificación) en la esquina inferior
function toast(msg, type = "info") {
  const el = $("toast");
  el.textContent = msg;
  el.className = `show ${type}`;
  clearTimeout(el._t);
  el._t = setTimeout(() => {
    el.className = ""; // Oculta el toast
  }, 3000);
}

// Obtiene el título de una serie según la preferencia del usuario
// Si prefiere inglés, intenta: english → romaji → japonés
// Así se garantiza siempre mostrar algo, aunque falte un título
function getTitleByPref(s) {
  const pref = state.titlePref || "romaji";
  if (pref === "english")
    return s.title_english || s.title_romaji || s.title_japanese;
  if (pref === "japanese") return s.title_japanese || s.title_romaji;
  return s.title_romaji || s.title_english || s.title_japanese;
}

// Realiza peticiones HTTP a la API con manejo de errores robusto
// Si la API devuelve error JSON, lo extrae. Si no, usa el mensaje del servidor.
// Siempre lanza un Error que quien llama puede capturar con try/catch
async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(API + path, options);
    if (!res.ok) {
      let errorDetail = res.statusText;
      try {
        const errData = await res.json();
        errorDetail = errData.detail || errorDetail;
      } catch {
        // Si no es JSON válido, usa statusText
      }
      throw new Error(errorDetail);
    }
    return await res.json();
  } catch (e) {
    // Re-lanzar el error para que quien llama lo maneje
    throw e instanceof Error ? e : new Error(String(e));
  }
}

// Cambia la vista visible ocultando todas las demás
// Solo una vista (div.view) puede estar activa a la vez
// Vistas: view-auth, view-list, view-detail
function showView(id) {
  document
    .querySelectorAll(".view")
    .forEach((v) => v.classList.remove("active"));
  $(id).classList.add("active");
}

// Convierte un código de estado en texto legible para mostrar al usuario
function statusLabel(s) {
  return (
    { aptos: "Apto", no_aptos: "No apto", valorar: "Valorar" }[s] ||
    "Sin wallpaper"
  );
}

// Botón de reset: pide doble confirmación y borra todo
// Esto es crítico: elimina todos los wallpapers y limpia la BD
$("btn-reset").addEventListener("click", async () => {
  const confirmed = confirm(
    "¿Seguro? Esto borrará TODOS los wallpapers descargados y limpiará la base de datos. Esta operación no se puede deshacer.",
  );
  if (!confirmed) return;
  const reconfirmed = confirm("Última confirmación: ¿borrar todo?");
  if (!reconfirmed) return;

  try {
    // Envía petición POST al servidor para ejecutar reset
    await apiFetch("/maintenance/reset", { method: "POST" });
    toast("Reset completado", "success");
    loadSeries(); // Recarga la lista tras limpiar todo
  } catch (e) {
    toast(e.message, "error");
  }
});

// Restaura el scroll a la posición guardada en state.scrollY
// Se usa al volver a la lista desde la vista de detalle
// requestAnimationFrame garantiza que el elemento está visible antes de hacer scroll
function restoreScrollToSeries() {
  requestAnimationFrame(() => {
    window.scrollTo({ top: state.scrollY, behavior: "instant" });
  });
}

// ── AUTH ───────────────────────────────────────────────────────────────────
// Verifica si el usuario está autenticado con MyAnimeList
// Si está autenticado: carga la lista de series y muestra la interfaz principal
// Si no: muestra la pantalla de login
async function checkAuth() {
  try {
    const data = await apiFetch("/auth/status");
    const badge = $("auth-badge");
    if (data.authenticated) {
      // Usuario autenticado: cambiar badge a verde y cargar serie
      badge.classList.add("ok");
      badge.querySelector(".auth-label").textContent = "MAL conectado";
      loadSeries(); // Carga la lista de anime del usuario
    } else {
      // Usuario no autenticado: mostrar pantalla de login
      badge.querySelector(".auth-label").textContent = "Sin conectar";
      showView("view-auth");
    }
  } catch {
    toast("Error al comprobar autenticación", "error");
  }
}

// Flujo de login: abre navegador, espera token, comprueba cada 2s si se completó
// Tiene timeout máximo de 5 minutos para evitar espera indefinida
$("btn-login").addEventListener("click", async () => {
  $("btn-login").disabled = true;
  $("btn-login").textContent = "Abriendo navegador…";
  try {
    // Inicia flujo OAuth con MyAnimeList
    await apiFetch("/auth/login");
    toast("Autoriza la app en el navegador y vuelve aquí", "info");

    // Polling: comprueba cada 2 segundos si el token llegó
    // Máximo 150 intentos = 300 segundos = 5 minutos
    const maxAttempts = 150;
    let attempts = 0;

    const interval = setInterval(async () => {
      attempts++;
      try {
        const data = await apiFetch("/auth/status");
        if (data.authenticated) {
          // Token recibido: limpia intervalo y carga la interfaz
          clearInterval(interval);
          checkAuth();
        } else if (attempts >= maxAttempts) {
          // Timeout: mostrar error y permitir reintentar
          clearInterval(interval);
          toast("Tiempo de espera agotado. Intenta de nuevo.", "error");
          $("btn-login").disabled = false;
          $("btn-login").textContent = "Conectar con MAL";
        }
      } catch (e) {
        // Error durante polling: si se agota tiempo, mostrar error
        if (attempts >= maxAttempts) {
          clearInterval(interval);
          toast("Error durante la autenticación", "error");
          $("btn-login").disabled = false;
          $("btn-login").textContent = "Conectar con MAL";
        }
      }
    }, 2000);

    // Guardar referencia para poder cancelar si es necesario
    state.loginTimeout = interval;
  } catch (e) {
    toast(e.message, "error");
    $("btn-login").disabled = false;
    $("btn-login").textContent = "Conectar con MAL";
  }
});

// ── RESOLUCIÓN ─────────────────────────────────────────────────────────────
// Carga la resolución mínima guardada del servidor
// Si falla, usa los valores por defecto (1920x1080)
async function loadResolution() {
  try {
    const cfg = await apiFetch("/config/resolution");
    $("res-w").value = cfg.min_width;
    $("res-h").value = cfg.min_height;
    state.resolution = { w: cfg.min_width, h: cfg.min_height };
  } catch {
    // Si la API falla, usa los valores por defecto del state
  }
}

// Guarda la resolución mínima editada por el usuario
// Valida que sea al menos 800x600 antes de guardar
$("btn-save-res").addEventListener("click", async () => {
  const w = parseInt($("res-w").value);
  const h = parseInt($("res-h").value);

  // Validación: valores válidos y mínimo 800x600
  if (!w || !h || w < 800 || h < 600) {
    toast("Resolución inválida", "error");
    return;
  }

  try {
    // Envía la nueva resolución al servidor para que la guarde en config.json
    await apiFetch("/config/resolution", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ min_width: w, min_height: h }),
    });
    state.resolution = { w, h };
    toast("Resolución guardada", "success");
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── SERIES ─────────────────────────────────────────────────────────────────
// Carga la lista completa de series completadas del usuario desde MyAnimeList
// Entra a la vista de lista y muestra un spinner mientras carga
async function loadSeries() {
  showView("view-list");
  $("series-grid").innerHTML =
    '<div class="state-msg"><div class="spinner"></div>Cargando tu lista de MAL…</div>';

  try {
    // Obtiene todas las series completadas del usuario desde el servidor
    state.series = await apiFetch("/series");
    applyFilters(); // Renderiza la lista (aplica filtros actuales)
  } catch (e) {
    $("series-grid").innerHTML =
      `<div class="state-msg">Error: ${e.message}</div>`;
  }
}

// Filtra la lista de series según:
// 1. Búsqueda por texto (en el título)
// 2. Filtro: todas, solo con wallpaper, solo sin wallpaper
// 3. Preferencia de idioma del título (romaji/inglés/japonés)
function applyFilters() {
  const q = $("search-input").value.toLowerCase(); // Texto de búsqueda
  const filter = $("filter-select").value; // Filtro seleccionado

  // Filtra state.series usando los criterios anteriores
  state.filtered = state.series.filter((s) => {
    const title = getTitleByPref(s).toLowerCase();

    // Si hay búsqueda: solo incluir si el título contiene el término
    if (q && !title.includes(q)) return false;

    // Filtro "con wallpaper": solo series que ya tienen wallpaper guardado
    if (filter === "with" && !s.has_wallpaper) return false;

    // Filtro "sin wallpaper": solo series que no tienen wallpaper
    if (filter === "without" && s.has_wallpaper) return false;

    return true;
  });

  // Actualiza el contador de resultados
  $("count-label").textContent = `${state.filtered.length} series`;
  renderGrid(); // Renderiza la grid con los resultados filtrados
}

// Event listeners para los controles de filtrado
// Debounce en búsqueda (espera 300ms sin escribir antes de filtrar)
$("search-input").addEventListener("input", debounce(applyFilters, 300));
$("filter-select").addEventListener("change", applyFilters);
$("pref-title").addEventListener("change", () => {
  state.titlePref = $("pref-title").value;
  applyFilters(); // Re-renderizar con nuevo idioma
});

// Renderiza las series filtradas como tarjetas en el grid
// Cada tarjeta muestra: portada, título, tipo (serie/película)
function renderGrid() {
  const grid = $("series-grid");

  if (!state.filtered.length) {
    grid.innerHTML = '<div class="state-msg">No hay resultados.</div>';
    return;
  }

  // Construye HTML para cada serie filtrada
  grid.innerHTML = state.filtered
    .map((s) => {
      const title = getTitleByPref(s);
      const type = s.media_type === "movie" ? "película" : "serie";
      return `
      <div class="series-card ${s.has_wallpaper ? "has-wallpaper" : ""}"
           data-malid="${s.mal_id}" onclick="openSeries(${s.mal_id})">
          ${
            s.cover_url
              ? `<img class="series-card-cover" src="${s.cover_url}" alt="${title}" loading="lazy">`
              : `<div class="series-card-cover-placeholder">🎬</div>`
          }
        <div class="series-card-info">
          <div class="series-card-title">${title}</div>
          <div class="series-card-type">${type}</div>
        </div>
      </div>`;
    })
    .join("");
}

// ── DETALLE DE SERIE ───────────────────────────────────────────────────────
// Abre la vista de detalle de una serie seleccionada
// Muestra portada, título, y carga los wallpapers encontrados para esa serie
async function openSeries(malId) {
  // Busca la serie en la lista de state
  const series = state.series.find((s) => s.mal_id === malId);
  if (!series) return;

  state.currentSeries = series;
  state.scrollY = window.scrollY; // Guarda posición para volver luego

  // Cambia a vista de detalle
  showView("view-detail");
  $("detail-title").textContent = getTitleByPref(series);
  $("detail-subtitle").textContent =
    series.title_romaji !== series.title_english ? series.title_romaji : "";

  // Carga y muestra la portada
  const detailCover = $("detail-cover");
  const detailCoverPh = $("detail-cover-ph");

  if (series.cover_url) {
    detailCover.src = series.cover_url;
    // Cuando cargue la imagen, oculta el placeholder y muestra la imagen
    detailCover.onload = () => {
      detailCover.style.display = "block";
      detailCoverPh.style.display = "none";
    };
  }

  try {
    // Sincroniza la serie en la BD local del servidor (upsert)
    await apiFetch(`/series/${malId}/sync`, { method: "POST" });
  } catch {}

  // Scroll al inicio de la vista de detalle
  window.scrollTo({ top: 0, behavior: "smooth" });

  // Carga los wallpapers encontrados para esta serie
  loadWallpapers(malId);
}

// Busca wallpapers en múltiples fuentes (Wallhaven, Konachan, Yandere, Safebooru)
// Muestra el wallpaper actual guardado (si existe) y permite clasificar nuevos
async function loadWallpapers(malId) {
  // Muestra spinner mientras busca
  $("wallpaper-grid").innerHTML =
    '<div class="state-msg"><div class="spinner"></div>Buscando wallpapers…</div>';
  $("detail-status-badge").className = "status-badge none";
  $("detail-status-badge").textContent = "Sin wallpaper";
  $("btn-change-status").style.display = "none";

  try {
    // Obtiene wallpapers encontrados + wallpaper actual (si existe)
    const data = await apiFetch(`/wallpapers/search/${malId}`);
    state.currentWallpapers = data.results;
    state.currentWallpaper = data.current_wallpaper;

    // Si hay wallpaper guardado: muestra su estado (Apto/No apto/Valorar)
    if (state.currentWallpaper) {
      const s = state.currentWallpaper.status;
      $("detail-status-badge").className = `status-badge ${s}`;
      $("detail-status-badge").textContent = statusLabel(s);
      $("btn-change-status").style.display = "inline-flex";
    }

    renderWallpaperGrid();
  } catch (e) {
    $("wallpaper-grid").innerHTML =
      `<div class="state-msg">Error: ${e.message}</div>`;
  }
}

// Renderiza los wallpapers encontrados como tarjetas en grid
// La tarjeta actual (la guardada) tiene clase "current" para destacarla
function renderWallpaperGrid() {
  const grid = $("wallpaper-grid");
  if (!state.currentWallpapers.length) {
    grid.innerHTML =
      '<div class="state-msg">No se encontraron wallpapers. Prueba con otro término de búsqueda.</div>';
    return;
  }

  grid.innerHTML = state.currentWallpapers
    .map((wp, i) => {
      // Marca el wallpaper actualmente guardado
      const isCurrent =
        state.currentWallpaper &&
        state.currentWallpaper.source_url === wp.full_url;

      // Optimización: imagen actual carga eager (rápido), otras lazy (más eficiente)
      const loading = isCurrent ? 'loading="eager"' : 'loading="lazy"';

      return `
      <div class="wp-card ${isCurrent ? "current" : ""}"
           onclick="selectWallpaper(${i})">
        <img src="${wp.preview_url}" alt="wallpaper ${i + 1}" ${loading}>
        <div class="wp-card-footer">
          <span class="wp-source-badge ${wp.source}">${wp.source}</span>
          <span>${wp.resolution || ""}</span>
        </div>
      </div>`;
    })
    .join("");
}

// Abre el modal de clasificación para descargar un wallpaper seleccionado
function selectWallpaper(index) {
  state.selectedWp = state.currentWallpapers[index];
  openClassifyModal(
    state.selectedWp.preview_url,
    state.selectedWp.full_url,
    state.selectedWp.source,
  );
}

// Carga los límites de búsqueda configurados (cuántas imágenes traer de cada fuente)
async function loadSearchConfig() {
  try {
    const cfg = await apiFetch("/config/search");
    $("wh-limit").value = cfg.wallhaven_limit;
    $("kn-limit").value = cfg.konachan_limit;
    $("yd-limit").value = cfg.yandere_limit;
    $("sb-limit").value = cfg.safebooru_limit;
  } catch {}
}

// Guarda los límites de búsqueda editados por el usuario
// Envía todos los 4 límites al servidor
$("btn-save-search").addEventListener("click", async () => {
  const wh = parseInt($("wh-limit").value);
  const kn = parseInt($("kn-limit").value);
  const yd = parseInt($("yd-limit").value);
  const sb = parseInt($("sb-limit").value);

  try {
    // Envía los nuevos límites para que se guarden en la configuración
    await apiFetch("/config/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        wallhaven_limit: wh,
        konachan_limit: kn,
        yandere_limit: yd,
        safebooru_limit: sb,
      }),
    });
    toast("Configuración guardada", "success");
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── BÚSQUEDA MANUAL ────────────────────────────────────────────────────────
// Permite buscar wallpapers con un término personalizado en lugar de usar el título
// Útil cuando los títulos automáticos no dan buenos resultados
$("btn-manual-search").addEventListener("click", async () => {
  const term = $("manual-search-input").value.trim();
  if (!term) {
    toast("Escribe un término de búsqueda", "error");
    return;
  }

  $("wallpaper-grid").innerHTML =
    '<div class="state-msg"><div class="spinner"></div>Buscando…</div>';

  try {
    // Busca con el término personalizado en lugar del título de la serie
    const data = await apiFetch(
      `/wallpapers/search-term?q=${encodeURIComponent(term)}`,
    );
    state.currentWallpapers = data.results;
    renderWallpaperGrid();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ── CLASIFICAR MODAL ───────────────────────────────────────────────────────
// Abre el modal para que el usuario clasifique un wallpaper seleccionado
// Muestra preview, fuente, y botones para elegir: Apto / No apto / Valorar
function openClassifyModal(previewUrl, fullUrl, source) {
  $("modal-preview-img").src = previewUrl;
  $("modal-source").textContent = source;
  state.pendingStatus = null; // Reinicia selección

  // Reinicia todos los botones de clasificación (sin seleccionar)
  document
    .querySelectorAll(".classify-opt")
    .forEach((b) => (b.className = "classify-opt"));

  $("btn-confirm-download").disabled = true; // Desactiva descargar hasta seleccionar estado
  $("modal-classify").classList.add("open");
}

// Event listeners para los botones de clasificación dentro del modal
// Al hacer clic: marca el botón y habilita el botón de guardar
document.querySelectorAll(".classify-opt").forEach((btn) => {
  btn.addEventListener("click", () => {
    const s = btn.dataset.status; // Obtiene el estado: aptos/no_aptos/valorar
    state.pendingStatus = s;

    // Reinicia estilos de todos los botones
    document
      .querySelectorAll(".classify-opt")
      .forEach((b) => (b.className = "classify-opt"));

    // Destaca el botón seleccionado
    btn.classList.add(`selected-${s}`);
    $("btn-confirm-download").disabled = false; // Habilita descarga
  });
});

// Cierra el modal de clasificación sin guardar nada
$("btn-cancel-modal").addEventListener("click", () => {
  $("modal-classify").classList.remove("open");
});

// Cierra el modal si se hace clic en el fondo (fuera del contenido)
$("modal-classify").addEventListener("click", (e) => {
  if (e.target === $("modal-classify"))
    $("modal-classify").classList.remove("open");
});

// Descarga el wallpaper seleccionado con la clasificación elegida
// Si falla: muestra error. Si éxito: actualiza la UI y recarga wallpapers
$("btn-confirm-download").addEventListener("click", async () => {
  if (!state.pendingStatus || !state.selectedWp) return;

  $("btn-confirm-download").disabled = true;
  $("btn-confirm-download").textContent = "Guardando…";

  try {
    // Envía petición para descargar y guardar el wallpaper
    await apiFetch("/wallpapers/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mal_id: state.currentSeries.mal_id,
        source_url: state.selectedWp.full_url,
        source: state.selectedWp.source,
        status: state.pendingStatus,
      }),
    });

    toast("Wallpaper guardado correctamente", "success");
    $("modal-classify").classList.remove("open");

    // Actualiza el estado en la lista (marca como "tiene wallpaper")
    const s = state.series.find((x) => x.mal_id === state.currentSeries.mal_id);
    if (s) s.has_wallpaper = true;
    state.currentSeries.has_wallpaper = true;

    // Recarga wallpapers de la serie para mostrar el nuevo estado
    loadWallpapers(state.currentSeries.mal_id);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    $("btn-confirm-download").disabled = false;
    $("btn-confirm-download").textContent = "Guardar";
  }
});

// ── CAMBIO DE STATUS ──────────────────────────────────────────────────────
// Abre el modal para cambiar el estado del wallpaper actualmente guardado
// El archivo se mueve a la carpeta correspondiente (aptos/no_aptos/valorar)
$("btn-change-status").addEventListener("click", () => {
  $("modal-change-status").classList.add("open");
});

// Cierra el modal de cambio de status sin hacer cambios
$("btn-cancel-status").addEventListener("click", () => {
  $("modal-change-status").classList.remove("open");
});

// Event listeners para cambiar el estado del wallpaper guardado
// Actualiza el estado, mueve el archivo, y recarga la vista
document.querySelectorAll(".change-status-opt").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const newStatus = btn.dataset.status;
    try {
      // Envía petición PATCH para cambiar el estado
      await apiFetch("/wallpapers/status", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mal_id: state.currentSeries.mal_id,
          status: newStatus,
        }),
      });
      toast(`Estado cambiado a "${statusLabel(newStatus)}"`, "success");
      $("modal-change-status").classList.remove("open");
      loadWallpapers(state.currentSeries.mal_id); // Recarga para mostrar nuevo estado
    } catch (e) {
      toast(e.message, "error");
    }
  });
});

// ── SUBIDA MANUAL ──────────────────────────────────────────────────────────
// Permite que el usuario suba un archivo de imagen localmente
// Se procesa a JPG, se redimensiona, y se clasifica igual que un wallpaper descargado

const uploadZone = $("upload-zone"); // Zona donde se puede soltar archivo o hacer clic
const uploadInput = $("upload-input"); // Input oculto de tipo file

// Clicking en la zona de upload abre el diálogo de archivo
uploadZone.addEventListener("click", () => uploadInput.click());

// Al pasar el ratón sobre la zona: cambia estilo visual (feedback)
uploadZone.addEventListener("dragover", (e) => {
  e.preventDefault();
  uploadZone.classList.add("drag-over");
});

// Al salir de la zona: restaura estilo
uploadZone.addEventListener("dragleave", () =>
  uploadZone.classList.remove("drag-over"),
);

// Al soltar un archivo: lo procesa
uploadZone.addEventListener("drop", (e) => {
  e.preventDefault();
  uploadZone.classList.remove("drag-over");
  const file = e.dataTransfer.files[0];
  if (file) handleUpload(file);
});

// Si el usuario selecciona archivo desde el input: lo procesa
uploadInput.addEventListener("change", () => {
  if (uploadInput.files[0]) handleUpload(uploadInput.files[0]);
});

// Maneja la subida de un archivo: abre modal de clasificación
function handleUpload(file) {
  openUploadClassifyModal(file);
}

// Variables para gestionar archivos subidos
let pendingUploadFile = null;
let pendingUploadUrl = null; // URL del blob del archivo para limpiar después

// Abre modal de clasificación para un archivo subido por el usuario
// Crea una URL blob temporal del archivo para mostrar preview
function openUploadClassifyModal(file) {
  pendingUploadFile = file;

  // Libera URL anterior si existe (previene memory leaks)
  if (pendingUploadUrl) {
    URL.revokeObjectURL(pendingUploadUrl);
  }

  // Crea URL temporal del archivo para mostrar preview
  pendingUploadUrl = URL.createObjectURL(file);
  $("modal-upload-preview").src = pendingUploadUrl;
  $("modal-upload-filename").textContent = file.name;
  state.pendingStatus = null;
  document
    .querySelectorAll(".upload-classify-opt")
    .forEach((b) => (b.className = "classify-opt upload-classify-opt"));
  $("btn-confirm-upload").disabled = true;
  $("modal-upload").classList.add("open");
}

// Event listeners para botones de clasificación en modal de upload
document.querySelectorAll(".upload-classify-opt").forEach((btn) => {
  btn.addEventListener("click", () => {
    const s = btn.dataset.status;
    state.pendingStatus = s;
    document
      .querySelectorAll(".upload-classify-opt")
      .forEach((b) => (b.className = "classify-opt upload-classify-opt"));
    btn.classList.add(`selected-${s}`);
    $("btn-confirm-upload").disabled = false;
  });
});

// Cierra el modal de upload sin guardar
$("btn-cancel-upload").addEventListener("click", () => {
  $("modal-upload").classList.remove("open");
  // Libera URL blob para evitar memory leak
  if (pendingUploadUrl) {
    URL.revokeObjectURL(pendingUploadUrl);
    pendingUploadUrl = null;
  }
});

// Sube el archivo seleccionado con la clasificación elegida
// Similar a download, pero envía FormData en lugar de JSON
$("btn-confirm-upload").addEventListener("click", async () => {
  if (!pendingUploadFile || !state.pendingStatus) return;
  $("btn-confirm-upload").disabled = true;
  $("btn-confirm-upload").textContent = "Subiendo…";

  const formData = new FormData();
  formData.append("mal_id", state.currentSeries.mal_id);
  formData.append("status", state.pendingStatus);
  formData.append("file", pendingUploadFile);

  try {
    // Sube el archivo (sin usar apiFetch porque necesita FormData)
    await fetch("/wallpapers/upload", { method: "POST", body: formData }).then(
      (r) => {
        if (!r.ok) throw new Error("Error al subir");
        return r.json();
      },
    );

    toast("Imagen subida correctamente", "success");
    $("modal-upload").classList.remove("open");
    // Libera URL blob después de éxito
    if (pendingUploadUrl) {
      URL.revokeObjectURL(pendingUploadUrl);
      pendingUploadUrl = null;
    }
    // Actualiza estado y recarga wallpapers
    const s = state.series.find((x) => x.mal_id === state.currentSeries.mal_id);
    if (s) s.has_wallpaper = true;
    loadWallpapers(state.currentSeries.mal_id);
  } catch (e) {
    toast(e.message, "error");
  } finally {
    $("btn-confirm-upload").disabled = false;
    $("btn-confirm-upload").textContent = "Guardar";
  }
});

// ── VOLVER ─────────────────────────────────────────────────────────────────
// Botón para volver a la lista de series desde la vista de detalle
// Limpia el estado actual y restaura scroll
$("detail-back").addEventListener("click", () => {
  $("wallpaper-grid").innerHTML = "";
  state.currentWallpapers = [];
  state.currentWallpaper = null;
  showView("view-list");
  renderGrid(); // refresca badges de has_wallpaper
  restoreScrollToSeries();
});

// ── INIT ───────────────────────────────────────────────────────────────────
// Inicialización: ejecuta al cargar la página
// 1. Carga configuración de resolución desde servidor
// 2. Carga límites de búsqueda desde servidor
// 3. Verifica si el usuario está autenticado con MyAnimeList
loadResolution();
loadSearchConfig();
checkAuth();
