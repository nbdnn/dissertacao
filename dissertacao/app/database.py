import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tle_history.db")

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Table for tracking which satellites we want historical data for
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS marked_satellites (
        norad_cat_id INTEGER PRIMARY KEY,
        marked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    
    # Table for storing the actual historical TLEs
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS historical_tles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        norad_cat_id INTEGER,
        tle_line1 TEXT,
        tle_line2 TEXT,
        epoch TEXT,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(norad_cat_id, epoch)
    )
    ''')
    
    conn.commit()
    conn.close()

def mark_satellite(norad_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO marked_satellites (norad_cat_id) VALUES (?)', (norad_id,))
    conn.commit()
    conn.close()

def get_marked_satellites() -> list[int]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT norad_cat_id FROM marked_satellites')
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def store_historical_tle(norad_id: int, tle1: str, tle2: str, epoch: str):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            'INSERT OR IGNORE INTO historical_tles (norad_cat_id, tle_line1, tle_line2, epoch) VALUES (?, ?, ?, ?)',
            (norad_id, tle1, tle2, epoch)
        )
        conn.commit()
    except Exception as e:
        print(f"Error saving historical TLE for {norad_id}: {e}")
    finally:
        conn.close()

def get_historical_tles(norad_id: int) -> list[dict]:
    conn = get_connection()
    cursor = conn.cursor()
    # Fetch ordered by the time they were recorded (or epoch) to show history
    cursor.execute(
        'SELECT tle_line1, tle_line2, epoch, recorded_at FROM historical_tles WHERE norad_cat_id = ? ORDER BY epoch ASC',
        (norad_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    return [
        {
            "TLE_LINE1": r[0],
            "TLE_LINE2": r[1],
            "EPOCH": r[2],
            "RECORDED_AT": r[3]
        }
        for r in rows
    ]

# Initialize on import
init_db()
