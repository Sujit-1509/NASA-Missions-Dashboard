#!/usr/bin/env python3
"""
Streamlit NASA Missions Dashboard powered by SQLite.

Features:
- KPIs: Total Missions, Avg Cost, Success Rate, Most Common Launch Vehicle
- Filters: Mission Type, Target Type, Launch Vehicle, Year Range
- Charts: Missions per Target Type, Success Rate per Mission Type, Missions over Years,
          Cost vs Distance scatter, Top 5 Most Expensive
- Data Table: Filtered results, CSV download
- Theme toggle: Light / Dark (updates Plotly templates and basic CSS)
- NASA Image of the Day: Fetches and displays APOD from NASA API
- Hazardous Asteroid Tracker: Displays potentially hazardous asteroids

Run:
  streamlit run nasa_dashboard/app.py

Ensure DB exists:
  python nasa_dashboard/load_data.py
"""

import os
import sqlite3
from typing import Tuple
from datetime import datetime
import requests

import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(THIS_DIR, "nasa_missions.db")

NASA_APOD_API_URL = "https://api.nasa.gov/planetary/apod"
NASA_NEO_API_URL = "https://api.nasa.gov/neo/rest/v1/feed"
NASA_API_KEY = "xEvTGkzBk3HBkX7v83JEaLmRZXBuhJff9fAcxyJb"

st.set_page_config(
    page_title="NASA Missions Dashboard",
    page_icon="🚀",
    layout="wide",
)


# Theming helpers
def apply_base_css(theme: str):
    dark_bg = "#0b0f19"
    dark_panel = "#121a2a"
    light_bg = "#f7f9fc"
    light_panel = "#ffffff"
    nasa_blue = "#0b3d91"
    text_light = "#e6edf7"
    text_dark = "#0a0a0a"

    if theme == "Dark":
        bg, panel, text = dark_bg, dark_panel, text_light
    else:
        bg, panel, text = light_bg, light_panel, text_dark

    st.markdown(
        f"""
        <style>
        .stApp {{
            background-color: {bg};
        }}
        [data-testid="stSidebar"] > div:first-child {{
            background-color: {panel};
        }}
        .block-container {{
            padding-top: 1.5rem;
            padding-bottom: 2rem;
        }}
        h1, h2, h3, h4, h5, h6, p, span, div, label {{
            color: {text};
        }}
        .kpi-card {{
            background: {panel};
            border: 1px solid rgba(11,61,145,0.25);
            border-radius: 12px;
            padding: 16px;
        }}
        .kpi-title {{
            font-size: 0.9rem;
            color: {nasa_blue};
            text-transform: uppercase;
            letter-spacing: 0.05em;
            margin-bottom: 4px;
        }}
        .kpi-value {{
            font-size: 1.6rem;
            font-weight: 700;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def plotly_template(theme: str) -> str:
    return "plotly_dark" if theme == "Dark" else "plotly_white"


# Data access
@st.cache_data(ttl=300)
def load_data(db_path: str) -> pd.DataFrame:
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM missions;", conn)
    finally:
        conn.close()

    # Coerce types just in case
    if "launch_year" in df.columns:
        df["launch_year"] = pd.to_numeric(df["launch_year"], errors="coerce").astype("Int64")
    if "success_pct" in df.columns:
        df["success_pct"] = pd.to_numeric(df["success_pct"], errors="coerce")
    if "cost_billion_usd" in df.columns:
        df["cost_billion_usd"] = pd.to_numeric(df["cost_billion_usd"], errors="coerce")
    if "distance_ly" in df.columns:
        df["distance_ly"] = pd.to_numeric(df["distance_ly"], errors="coerce")
    return df


@st.cache_data(ttl=1800)
def fetch_hazardous_asteroids():
    """Fetch potentially hazardous asteroids from today."""
    try:
        response = requests.get(NASA_NEO_API_URL, params={"api_key": NASA_API_KEY}, timeout=10)
        response.raise_for_status()
        data = response.json()

        asteroids = []
        for date, objects in data.get("near_earth_objects", {}).items():
            for obj in objects:
                close_approach = obj.get("close_approach_data", [{}])[0] if obj.get("close_approach_data") else {}
                asteroid = {
                    "name": obj.get("name", "Unknown"),
                    "diameter_max": obj.get("estimated_diameter", {}).get("meters", {}).get("estimated_diameter_max",
                                                                                            0),
                    "velocity_kph": float(close_approach.get("relative_velocity", {}).get("kilometers_per_hour",
                                                                                          0)) if close_approach else 0,
                    "miss_distance_km": float(
                        close_approach.get("miss_distance", {}).get("kilometers", 0)) if close_approach else 0,
                    "is_hazardous": obj.get("is_potentially_hazardous_asteroid", False),
                }
                asteroids.append(asteroid)

        return [a for a in asteroids if a["is_hazardous"]]
    except Exception as e:
        st.warning(f"Unable to fetch asteroids: {str(e)}")
        return []


def show_hazardous_asteroid_tracker(theme: str):
    """Display Hazardous Asteroid Tracker."""
    st.header("☄️ Hazardous Asteroid Tracker (Today)")

    asteroids = fetch_hazardous_asteroids()
    st.subheader(f"Potentially Hazardous: {len(asteroids)}")

    if asteroids:
        for asteroid in asteroids:
            with st.expander(f"☄️ {asteroid['name']}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Diameter (m)", f"{asteroid['diameter_max']:,.0f}")
                    st.metric("Velocity (km/h)", f"{asteroid['velocity_kph']:,.0f}")
                with col2:
                    st.metric("Miss Distance (km)", f"{asteroid['miss_distance_km']:,.0f}")
                    st.metric("Hazardous", "Yes" if asteroid['is_hazardous'] else "No")

                st.progress(min(asteroid['diameter_max'] / 1000, 1.0),
                            text=f"Size: {min(asteroid['diameter_max'] / 1000 * 100, 100):.0f}%")
    else:
        st.info("No potentially hazardous asteroids today.")


def auto_refresh(seconds: int = 3600):
    """Auto-refresh the page at specified interval."""
    st.markdown(f"<meta http-equiv='refresh' content='{seconds}'>", unsafe_allow_html=True)


def sidebar_filters(df: pd.DataFrame) -> Tuple[list, list, list, Tuple[int, int], str, str]:
    """
    Updated sidebar with NASA API section at the top
    Returns: mission types, target types, vehicles, year range, theme, nasa_section
    """
    with st.sidebar:
        st.markdown("## 🌌 NASA API Features")

        nasa_section = st.radio(
            "Choose Feature",
            [
                "Dashboard",
                "NASA Image of the Day",
                "Hazardous Asteroid Tracker",
                "ISS Live Earth View"
            ]
        )

        st.markdown("---")

        st.markdown("### Controls")
        theme = st.radio("Theme", options=["Dark", "Light"], index=0, horizontal=True)

        mission_types = sorted([x for x in df["mission_type"].dropna().unique()]) if "mission_type" in df else []
        target_types = sorted([x for x in df["target_type"].dropna().unique()]) if "target_type" in df else []
        vehicles = sorted([x for x in df["launch_vehicle"].dropna().unique()]) if "launch_vehicle" in df else []
        years = df["launch_year"].dropna().astype(int) if "launch_year" in df else pd.Series(dtype=int)
        min_year = int(years.min()) if not years.empty else 2000
        max_year = int(years.max()) if not years.empty else 2050

        sel_mission_types = st.multiselect("Mission Type", mission_types, default=mission_types[:0])
        sel_target_types = st.multiselect("Target Type", target_types, default=target_types[:0])
        sel_vehicles = st.multiselect("Launch Vehicle", vehicles, default=vehicles[:0])
        year_range = st.slider("Launch Year Range", min_year, max_year, (min_year, max_year), step=1)

    return sel_mission_types, sel_target_types, sel_vehicles, year_range, theme, nasa_section


def apply_filters(df: pd.DataFrame, sel_m_types, sel_t_types, sel_vehicles, year_range) -> pd.DataFrame:
    if df.empty:
        return df
    f = df.copy()
    if sel_m_types:
        f = f[f["mission_type"].isin(sel_m_types)]
    if sel_t_types:
        f = f[f["target_type"].isin(sel_t_types)]
    if sel_vehicles:
        f = f[f["launch_vehicle"].isin(sel_vehicles)]
    if "launch_year" in f.columns and year_range:
        f = f[(f["launch_year"] >= year_range[0]) & (f["launch_year"] <= year_range[1])]
    return f


def kpi_card(title: str, value: str):
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-title">{title}</div>
          <div class="kpi-value">{value}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def show_iss_live_feed(theme: str):
    """
    Display Live ISS Earth-Viewing camera feed with automatic fallback.
    """
    st.header("🛰 Live ISS Earth-Viewing Stream")
    st.caption("Live HD camera view from the International Space Station")

    st.info("If the stream appears black or offline, the ISS may be on the night side of Earth.")

    streams = [
        # NASA's official Earth Views (most stable)
        "https://www.youtube.com/watch?v=fO9e9jnhYK8",

        # ESA ISS live view (excellent fallback
    ]

    # Try each stream one by one until one loads
    for stream in streams:
        try:
            st.markdown(
                f"""
                <iframe width="100%" height="520" 
                src="{stream}?autoplay=1&mute=1" 
                frameborder="0" allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture" 
                allowfullscreen></iframe>
                """,
                unsafe_allow_html=True
            )
            break  # first working stream stops loop
        except:
            continue

@st.cache_data(ttl=3600)
def fetch_nasa_apod():
    """Fetch NASA Astronomy Picture of the Day from API."""
    try:
        params = {
            "api_key": NASA_API_KEY,
        }
        response = requests.get(NASA_APOD_API_URL, params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.warning(f"Unable to load NASA Image of the Day. Please try again later. (Error: {str(e)})")
        return None


def show_nasa_image_of_the_day(theme: str):
    """Display NASA Astronomy Picture of the Day (APOD) with theming."""
    st.header("🌌 NASA Image of the Day")

    apod_data = fetch_nasa_apod()

    if apod_data is None:
        return

    title = apod_data.get("title", "Untitled")
    explanation = apod_data.get("explanation", "No description available.")
    url = apod_data.get("url", None)
    media_type = apod_data.get("media_type", "image")
    date = apod_data.get("date", "Unknown date")

    # Display title and date
    st.subheader(title)
    st.caption(f"📅 {date}")

    # Display media based on type
    if media_type == "image" and url:
        try:
            st.image(url, use_column_width=True, caption=title)
        except Exception as e:
            st.warning(f"Could not load image: {str(e)}")

    elif media_type == "video" and url:
        try:
            st.video(url)
        except Exception as e:
            st.warning(f"Could not load video: {str(e)}")
    else:
        if url:
            st.info(f"📌 Media type '{media_type}' not directly supported. [View here]({url})")
        else:
            st.warning("No media URL available for today's image.")

    # Display explanation in expandable section
    with st.expander("📝 Description"):
        st.write(explanation)


def main():
    try:
        from load_data import ensure_database  # local module in the same folder
        ensure_database(DB_PATH)
    except Exception as e:
        st.warning(f"Attempted to build database automatically but failed: {e}")

    df = load_data(DB_PATH)

    sel_m_types, sel_t_types, sel_vehicles, year_range, theme, nasa_section = sidebar_filters(df)
    apply_base_css(theme)
    tmpl = plotly_template(theme)

    if nasa_section in [
        "NASA Image of the Day",
        "Hazardous Asteroid Tracker",
        "Mars Rover Photos",
        "EPIC Earth Images",
        "ISS Live Earth View"
    ]:
        auto_refresh(seconds=3600)

        if nasa_section == "NASA Image of the Day":
            show_nasa_image_of_the_day(theme)
        elif nasa_section == "Hazardous Asteroid Tracker":
            show_hazardous_asteroid_tracker(theme)
        elif nasa_section == "ISS Live Earth View":
            show_iss_live_feed(theme)

    else:
        st.title("🚀 NASA Missions Dashboard")

        if df.empty:
            st.warning(
                "Database not found or still empty after initialization. Please check CSV accessibility or try again.")
            return

        filtered = apply_filters(df, sel_m_types, sel_t_types, sel_vehicles, year_range)

        # KPIs
        total_missions = len(filtered)
        avg_cost = np.nanmean(filtered["cost_billion_usd"]) if "cost_billion_usd" in filtered else np.nan
        avg_success = np.nanmean(filtered["success_pct"]) if "success_pct" in filtered else np.nan
        most_common_vehicle = (
            filtered["launch_vehicle"].mode().iat[0]
            if "launch_vehicle" in filtered and not filtered["launch_vehicle"].dropna().empty and not filtered[
                "launch_vehicle"].mode().empty
            else "N/A"
        )

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            kpi_card("Total Missions", f"{total_missions:,}")
        with c2:
            kpi_card("Avg Cost (B$)", f"{avg_cost:,.2f}" if not np.isnan(avg_cost) else "—")
        with c3:
            kpi_card("Avg Success (%)", f"{avg_success:,.1f}" if not np.isnan(avg_success) else "—")
        with c4:
            kpi_card("Top Launch Vehicle", most_common_vehicle)

        st.markdown("---")

        # Charts row 1
        cc1, cc2, cc3 = st.columns(3)

        with cc1:
            if "target_type" in filtered and not filtered.empty:
                tgt_count = filtered.groupby("target_type", dropna=False)["mission_id"].count().reset_index(
                    name="missions")
                fig = px.bar(
                    tgt_count.sort_values("missions", ascending=False),
                    x="target_type",
                    y="missions",
                    title="Missions per Target Type",
                    template=tmpl,
                    color="missions",
                    color_continuous_scale="Blues",
                )
                fig.update_layout(showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for Target Type chart.")

        with cc2:
            if "mission_type" in filtered and "success_pct" in filtered and not filtered.empty:
                sr = filtered.groupby("mission_type")["success_pct"].mean().reset_index(name="avg_success_pct")
                fig = px.bar(
                    sr.sort_values("avg_success_pct", ascending=False),
                    x="mission_type",
                    y="avg_success_pct",
                    title="Success Rate per Mission Type",
                    template=tmpl,
                    color="avg_success_pct",
                    color_continuous_scale="Blues",
                )
                fig.update_layout(showlegend=False, yaxis_title="Avg Success (%)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for Success Rate chart.")

        with cc3:
            if "launch_year" in filtered and not filtered.empty:
                yearly = filtered.groupby("launch_year", dropna=False)["mission_id"].count().reset_index(
                    name="missions")
                yearly = yearly.sort_values("launch_year")
                fig = px.line(
                    yearly,
                    x="launch_year",
                    y="missions",
                    markers=True,
                    title="Mission Count Over Years",
                    template=tmpl,
                )
                fig.update_layout(xaxis_title="Year", yaxis_title="Missions")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for Missions over Years.")

        # Charts row 2
        cc4, cc5 = st.columns(2)

        with cc4:
            if all(c in filtered.columns for c in ["distance_ly", "cost_billion_usd"]) and not filtered.empty:
                fig = px.scatter(
                    filtered,
                    x="distance_ly",
                    y="cost_billion_usd",
                    color="mission_type" if "mission_type" in filtered else None,
                    hover_data=["mission_name", "target_type", "launch_year"],
                    title="Cost vs Distance",
                    template=tmpl,
                    color_discrete_sequence=px.colors.sequential.Blues,
                )
                fig.update_layout(xaxis_title="Distance from Earth (light-years)", yaxis_title="Cost (billion USD)")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for Cost vs Distance.")

        with cc5:
            if "cost_billion_usd" in filtered and not filtered.empty:
                top5 = filtered.nlargest(5, "cost_billion_usd")[["mission_name", "cost_billion_usd"]]
                fig = px.bar(
                    top5.sort_values("cost_billion_usd"),
                    x="cost_billion_usd",
                    y="mission_name",
                    orientation="h",
                    title="Top 5 Most Expensive Missions",
                    template=tmpl,
                    color="cost_billion_usd",
                    color_continuous_scale="Blues",
                )
                fig.update_layout(showlegend=False, xaxis_title="Cost (billion USD)", yaxis_title="")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No data for Top 5 chart.")

        st.markdown("---")
        st.subheader("Missions Table")

        # Display filtered table (lightweight)
        display_cols = [
            c for c in [
                "mission_id", "mission_name", "launch_date", "launch_year",
                "mission_type", "target_type", "target_name", "launch_vehicle",
                "distance_ly", "duration_years", "cost_billion_usd", "success_pct",
                "scientific_yield", "crew_size", "payload_weight_tons", "fuel_consumption_tons"
            ] if c in filtered.columns
        ]
        st.dataframe(filtered[display_cols], use_container_width=True, hide_index=True)

        csv_bytes = filtered[display_cols].to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name="missions_filtered.csv",
            mime="text/csv",
        )


if __name__ == "__main__":
    main()
