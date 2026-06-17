import json
import os
from pathlib import Path

# Ruta al config.json, que está en la raíz del proyecto
CONFIG_PATH = Path(__file__).parent.parent / "config.json"

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"No se encontró config.json en {CONFIG_PATH}")
    
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    
    _ensure_directories(config)
    return config

def _ensure_directories(config: dict):
    """Crea las carpetas de destino si no existen."""
    paths = config.get("paths", {})
    for key in ["aptos", "no_aptos", "valorar"]:
        path = paths.get(key)
        if path:
            Path(path).mkdir(parents=True, exist_ok=True)
        else:
            raise ValueError(f"Falta la ruta '{key}' en config.json")
    
    # Asegurarse de que la carpeta de la BD existe también
    db_path = paths.get("database")
    if db_path:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    else:
        raise ValueError("Falta la ruta 'database' en config.json")

# Instancia global, el resto de módulos importan esto directamente
config = load_config()