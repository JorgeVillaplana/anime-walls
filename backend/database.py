import sqlite3
from pathlib import Path
from config import config

DB_PATH = config["paths"]["database"]

def get_connection() -> sqlite3.Connection:
    """Abre una conexión a la BD con Row Factory para acceder por nombre de columna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Permite acceder a columnas por nombre: row["title"]
    conn.execute("PRAGMA foreign_keys = ON")  # Activa integridad referencial
    return conn

def init_db():
    """Crea las tablas si no existen. Seguro de ejecutar múltiples veces."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS series (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            mal_id          INTEGER UNIQUE NOT NULL,
            title_romaji    TEXT NOT NULL,
            title_english   TEXT,
            title_japanese  TEXT,
            media_type      TEXT NOT NULL,
            has_wallpaper   INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS wallpapers (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            series_id       INTEGER NOT NULL REFERENCES series(id),
            filename        TEXT NOT NULL,
            source          TEXT NOT NULL,
            source_url      TEXT,
            resolution_w    INTEGER,
            resolution_h    INTEGER,
            imgbb_url       TEXT,
            imgbb_delete_url TEXT,
            status          TEXT NOT NULL CHECK(status IN ('aptos', 'no_aptos', 'valorar')),
            downloaded_at   TEXT NOT NULL DEFAULT (datetime('now')),
            file_hash       TEXT UNIQUE
        );

        CREATE INDEX IF NOT EXISTS idx_series_mal_id ON series(mal_id);
        CREATE INDEX IF NOT EXISTS idx_wallpapers_file_hash ON wallpapers(file_hash);
        CREATE INDEX IF NOT EXISTS idx_wallpapers_series_id ON wallpapers(series_id);
        CREATE INDEX IF NOT EXISTS idx_wallpapers_status ON wallpapers(status);
    """)

    conn.commit()
    conn.close()