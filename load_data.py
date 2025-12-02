#!/usr/bin/env python3
"""
Load the provided Space Missions dataset into an SQLite database.
Also fetches NASA API data (APOD, NEO, Earth Imagery).

- Reads CSV from a local path (default: dataset in your folder)
- Normalizes columns to snake_case aligned with schema.sql
- Parses dates, coerces numeric types, adds launch_year
- Recreates missions table and inserts data
- Fetches and stores NASA API data

Usage:
  python nasa_dashboard/load_data.py                  # uses default local CSV
  python nasa_dashboard/load_data.py --csv <path>     # custom CSV file
"""

import argparse
import os
import sqlite3
from datetime import datetime, timedelta
import pandas as pd
import requests

# 👇 Change this to your actual dataset path
DEFAULT_CSV_PATH = r"C:\Users\sujit\PycharmProjects\PythonProject1\space_missions_dataset.csv"
DEFAULT_CSV_URL = "/images/space-missions-dataset.csv"

NASA_API_KEY = "xEvTGkzBk3HBkX7v83JEaLmRZXBuhJff9fAcxyJb"
NASA_APOD_URL = "https://api.nasa.gov/planetary/apod"
NASA_NEO_URL = "https://api.nasa.gov/neo/rest/v1/feed"
NASA_EARTH_URL = "https://api.nasa.gov/planetary/earth/imagery"
NASA_EXOPLANET_URL = "https://exoplanetarchive.ipac.caltech.edu/TAP/sync"

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(THIS_DIR, "nasa_missions.db")
SCHEMA_PATH = os.path.join(THIS_DIR, "schema.sql")

COLUMN_MAP = {
    "Mission ID": "mission_id",
    "Mission Name": "mission_name",
    "Launch Date": "launch_date",
    "Target Type": "target_type",
    "Target Name": "target_name",
    "Mission Type": "mission_type",
    "Distance from Earth (light-years)": "distance_ly",
    "Mission Duration (years)": "duration_years",
    "Mission Cost (billion USD)": "cost_billion_usd",
    "Scientific Yield (points)": "scientific_yield",
    "Crew Size": "crew_size",
    "Mission Success (%)": "success_pct",
    "Fuel Consumption (tons)": "fuel_consumption_tons",
    "Payload Weight (tons)": "payload_weight_tons",
    "Launch Vehicle": "launch_vehicle",
}

NUMERIC_COLS = [
    "distance_ly",
    "duration_years",
    "cost_billion_usd",
    "scientific_yield",
    "crew_size",
    "success_pct",
    "fuel_consumption_tons",
    "payload_weight_tons",
]


def read_input(args: argparse.Namespace) -> pd.DataFrame:
    # Prefer explicit --csv if provided
    if getattr(args, "csv", None):
        csv_path = args.csv
        if isinstance(csv_path, str) and csv_path.lower().startswith(("http://", "https://")):
            print(f"[load_data] Reading CSV from URL: {csv_path}")
            return pd.read_csv(csv_path)
        print(f"[load_data] Reading local CSV: {csv_path}")
        if not os.path.exists(csv_path):
            raise FileNotFoundError(f"CSV file not found at: {csv_path}")
        return pd.read_csv(csv_path)

    # Fallbacks: local default path first, then remote URL
    if DEFAULT_CSV_PATH and os.path.exists(DEFAULT_CSV_PATH):
        print(f"[load_data] Reading local CSV (default): {DEFAULT_CSV_PATH}")
        return pd.read_csv(DEFAULT_CSV_PATH)

    # Remote default if local missing
    print(f"[load_data] Local CSV not found. Downloading from default URL: {DEFAULT_CSV_URL}")
    return pd.read_csv(DEFAULT_CSV_URL)


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    missing = [c for c in COLUMN_MAP.keys() if c not in df.columns]
    if missing:
        raise ValueError(f"CSV missing expected columns: {missing}")

    df = df.rename(columns=COLUMN_MAP).copy()

    # Parse launch_date and add launch_year
    df["launch_date"] = pd.to_datetime(df["launch_date"], errors="coerce").dt.date
    df["launch_date"] = df["launch_date"].astype("string")
    df["launch_year"] = pd.to_datetime(df["launch_date"], errors="coerce").dt.year

    # Convert numeric fields
    for col in NUMERIC_COLS:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # Ensure mission_id is filled
    if "mission_id" not in df or df["mission_id"].isna().any():
        df["mission_id"] = df["mission_id"].fillna("")
        df.loc[df["mission_id"] == "", "mission_id"] = (
                "MSN-" + (df.index + 1).astype(str).str.zfill(4)
        )

    # Strip whitespace from key text fields
    for col in ["mission_name", "target_type", "target_name", "mission_type", "launch_vehicle"]:
        if col in df.columns:
            df[col] = df[col].astype("string").str.strip()

    return df


def recreate_schema(conn: sqlite3.Connection):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()


def insert_data(conn: sqlite3.Connection, df: pd.DataFrame):
    df.to_sql("missions", conn, if_exists="append", index=False)


def fetch_nasa_apod(days: int = 7) -> list:
    """
    Fetch APOD (Astronomy Picture of the Day) for the last N days.

    Args:
        days: Number of days to fetch (default: 7)

    Returns:
        List of APOD data dictionaries
    """
    apod_data = []
    try:
        for i in range(days):
            date = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            params = {
                "api_key": NASA_API_KEY,
                "date": date
            }
            response = requests.get(NASA_APOD_URL, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                apod_data.append({
                    "date": data.get("date"),
                    "title": data.get("title"),
                    "explanation": data.get("explanation", "")[:500],  # Truncate explanation
                    "url": data.get("url"),
                    "media_type": data.get("media_type"),
                    "source": "APOD"
                })
                print(f"[NASA] APOD fetched for {date}: {data.get('title')}")
    except Exception as e:
        print(f"[NASA] Error fetching APOD data: {e}")

    return apod_data


def fetch_nasa_neo(days_ahead: int = 7) -> list:
    """
    Fetch Near-Earth Objects (NEO) data for the next N days.

    Args:
        days_ahead: Number of days ahead to check (default: 7)

    Returns:
        List of NEO data dictionaries
    """
    neo_data = []
    try:
        start_date = datetime.now().strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

        params = {
            "api_key": NASA_API_KEY,
            "start_date": start_date,
            "end_date": end_date,
            "detailed": False
        }
        response = requests.get(NASA_NEO_URL, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            near_earth_objects = data.get("near_earth_objects", {})

            for date_str, objects in near_earth_objects.items():
                for obj in objects:
                    neo_data.append({
                        "date": date_str,
                        "name": obj.get("name"),
                        "diameter_km": obj.get("estimated_diameter", {}).get("kilometers", {}).get(
                            "estimated_diameter_max"),
                        "hazardous": obj.get("is_potentially_hazardous_asteroid"),
                        "velocity_kms": obj.get("close_approach_data", [{}])[0].get("relative_velocity", {}).get(
                            "kilometers_per_second"),
                        "source": "NEO"
                    })
            print(f"[NASA] NEO data fetched: {len(neo_data)} objects found")
    except Exception as e:
        print(f"[NASA] Failed to fetch NEO data: {e}")

    return neo_data


def fetch_nasa_exoplanet() -> list:
    """
    Fetch exoplanet data from Caltech's Exoplanet Archive.

    Returns:
        List of exoplanet data dictionaries
    """
    exoplanet_data = []
    try:
        # Query for recently discovered exoplanets
        query = """
        SELECT pl_name, sy_pnum, pl_rade, pl_bmasse, sy_dist, disc_year
        FROM ps
        WHERE pl_name IS NOT NULL
        ORDER BY disc_year DESC
        LIMIT 50
        """

        params = {
            "query": query,
            "format": "json"
        }
        response = requests.get(NASA_EXOPLANET_URL, params=params, timeout=10)

        if response.status_code == 200:
            data = response.json()
            for planet in data:
                exoplanet_data.append({
                    "name": planet.get("pl_name"),
                    "planet_count": planet.get("sy_pnum"),
                    "radius_earth": planet.get("pl_rade"),
                    "mass_earth": planet.get("pl_bmasse"),
                    "distance_pc": planet.get("sy_dist"),
                    "discovery_year": planet.get("disc_year"),
                    "source": "Exoplanet Archive"
                })
            print(f"[NASA] Exoplanet data fetched: {len(exoplanet_data)} planets found")
    except Exception as e:
        print(f"[NASA] Failed to fetch exoplanet data: {e}")

    return exoplanet_data


def fetch_nasa_earth_imagery() -> list:
    """
    Fetch Earth imagery metadata for key locations.

    Returns:
        List of Earth imagery data dictionaries
    """
    earth_data = []
    locations = [
        {"lon": -74.0060, "lat": 40.7128, "name": "New York City"},
        {"lon": 139.6917, "lat": 35.6895, "name": "Tokyo"},
        {"lon": -0.1278, "lat": 51.5074, "name": "London"},
        {"lon": 151.2093, "lat": -33.8688, "name": "Sydney"}
    ]

    try:
        for loc in locations:
            params = {
                "lon": loc["lon"],
                "lat": loc["lat"],
                "dim": 0.15,
                "api_key": NASA_API_KEY
            }
            response = requests.head(NASA_EARTH_URL, params=params, timeout=10)

            if response.status_code == 200:
                earth_data.append({
                    "location": loc["name"],
                    "latitude": loc["lat"],
                    "longitude": loc["lon"],
                    "url": response.url,
                    "source": "Earth Imagery"
                })
                print(f"[NASA] Earth imagery available for {loc['name']}")
    except Exception as e:
        print(f"[NASA] Failed to fetch Earth imagery data: {e}")

    return earth_data


def store_nasa_data(conn: sqlite3.Connection, apod_data: list, neo_data: list, exoplanet_data: list, earth_data: list):
    """
    Store NASA API data in SQLite database.
    """
    cursor = conn.cursor()

    # Create NASA data tables if they don't exist
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS apod (
            id INTEGER PRIMARY KEY,
            date TEXT,
            title TEXT,
            explanation TEXT,
            url TEXT,
            media_type TEXT,
            source TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS neo (
            id INTEGER PRIMARY KEY,
            date TEXT,
            name TEXT,
            diameter_km REAL,
            hazardous BOOLEAN,
            velocity_kms REAL,
            source TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS exoplanet (
            id INTEGER PRIMARY KEY,
            name TEXT,
            planet_count INTEGER,
            radius_earth REAL,
            mass_earth REAL,
            distance_pc REAL,
            discovery_year INTEGER,
            source TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS earth_imagery (
            id INTEGER PRIMARY KEY,
            location TEXT,
            latitude REAL,
            longitude REAL,
            url TEXT,
            source TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()

    # Insert APOD data
    for item in apod_data:
        cursor.execute("""
            INSERT INTO apod (date, title, explanation, url, media_type, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (item["date"], item["title"], item["explanation"], item["url"], item["media_type"], item["source"]))

    # Insert NEO data
    for item in neo_data:
        cursor.execute("""
            INSERT INTO neo (date, name, diameter_km, hazardous, velocity_kms, source)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (item["date"], item["name"], item["diameter_km"], item["hazardous"], item["velocity_kms"], item["source"]))

    # Insert exoplanet data
    for item in exoplanet_data:
        cursor.execute("""
            INSERT INTO exoplanet (name, planet_count, radius_earth, mass_earth, distance_pc, discovery_year, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (item["name"], item["planet_count"], item["radius_earth"], item["mass_earth"], item["distance_pc"],
              item["discovery_year"], item["source"]))

    # Insert Earth imagery data
    for item in earth_data:
        cursor.execute("""
            INSERT INTO earth_imagery (location, latitude, longitude, url, source)
            VALUES (?, ?, ?, ?, ?)
        """, (item["location"], item["latitude"], item["longitude"], item["url"], item["source"]))

    conn.commit()
    print(
        f"[NASA] Stored {len(apod_data)} APOD, {len(neo_data)} NEO, {len(exoplanet_data)} exoplanet, {len(earth_data)} Earth imagery records")


def ensure_database(db_path: str = DB_PATH):
    """
    Create and populate the SQLite DB if it doesn't exist or is empty.
    Uses read_input() fallbacks (local path or default URL).
    Also fetches and stores NASA API data.
    """
    # If db exists and missions has rows, skip
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='missions';")
            if cur.fetchone():
                cur.execute("SELECT COUNT(*) FROM missions;")
                count = cur.fetchone()[0]
                if count and count > 0:
                    print(f"[load_data] DB already populated at {db_path} with {count} rows. Skipping.")
                    conn.close()
                    return
        except Exception as e:
            print(f"[load_data] Warning checking DB state: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

    # Build/refresh db
    args = argparse.Namespace(csv=None, db=db_path)
    df_raw = read_input(args)
    print(f"[load_data] Loaded rows: {len(df_raw)}")
    df = normalize(df_raw)
    print(f"[load_data] Normalized rows: {len(df)} | Columns: {list(df.columns)}")

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        recreate_schema(conn)
        insert_data(conn, df)

        print("[NASA] Fetching NASA API data...")
        apod_data = fetch_nasa_apod(days=7)
        neo_data = fetch_nasa_neo(days_ahead=7)
        exoplanet_data = fetch_nasa_exoplanet()
        earth_data = fetch_nasa_earth_imagery()

        store_nasa_data(conn, apod_data, neo_data, exoplanet_data, earth_data)

        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM missions;")
        total = cur.fetchone()[0]
        print(f"[load_data] Inserted missions: {total}")
    finally:
        conn.close()

    print(f"[load_data] ✅ Done. Database created at: {db_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="Path to local CSV file", default=None)
    parser.add_argument("--db", help="Output SQLite DB path", default=DB_PATH)
    args = parser.parse_args()

    ensure_database(args.db)

    print(f"[load_data] ✅ Done. Database created at: {args.db}")


if __name__ == "__main__":
    main()
