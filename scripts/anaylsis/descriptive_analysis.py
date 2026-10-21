# Q3 descriptive analysis for the NYS EV project.
# Run from the repo root: python scripts/analysis/descriptive_analysis.py
# Needs the curated parquet files and the county boundaries geojson from ingest_boundaries.py

import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

STATIONS_FILE = "data/curated/parquet/curated_stations.parquet"
REGISTRATIONS_FILE = "data/curated/parquet/curated_ev_registrations.parquet"
BOUNDARIES_FILE = "data/raw/boundaries/ny_county_boundaries.geojson"
FIPS_FILE = "metadata/schemas/ny_fips_mapping.json"

FIG_DIR = "reports/figures"
TABLE_DIR = "reports/tables"

# NYC boroughs + Nassau, Suffolk, Westchester, Rockland, Putnam
NYC_METRO = ["005", "047", "061", "081", "085", "059", "103", "119", "087", "079"]


def clean_county_name(name):
    # DMV has "ST LAWRENCE" but our mapping file has "St. Lawrence"
    return str(name).lower().replace(".", "").strip()


def get_station_counties(stations):
    # the NLR API doesn't give us a county, so we figure it out from lat/lon
    with open(BOUNDARIES_FILE) as f:
        geo = json.load(f)

    polygons = []
    fips_codes = []
    for feature in geo["features"]:
        polygons.append(shape(feature["geometry"]))
        fips_codes.append(feature["properties"]["COUNTY"])

    tree = STRtree(polygons)

    counties = []
    for lat, lon in zip(stations["latitude"], stations["longitude"]):
        point = Point(lon, lat)
        found = None
        for i in tree.query(point):
            if polygons[i].contains(point):
                found = fips_codes[i]
                break
        counties.append(found)

    return counties


def model_year_chart(reg):
    years = pd.to_numeric(reg["model_year"], errors="coerce")
    print("vehicles with model year before 2010:", (years < 2010).sum())

    counts = years[years >= 2010].value_counts().sort_index()
    counts.index = counts.index.astype(int)

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(counts.index, counts.values)
    ax.set_title("Registered EVs in NY by model year (DMV snapshot, Oct 2026)")
    ax.set_xlabel("Model year")
    ax.set_ylabel("Registered vehicles")
    ax.set_xticks(counts.index)
    ax.tick_params(axis="x", rotation=45)
    ax.annotate("2027 = partial\nmodel year", xy=(2027, counts[2027]),
                xytext=(2025.2, counts.max() * 0.9), fontsize=8,
                arrowprops=dict(arrowstyle="->"))
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/fig1_model_year.png", dpi=200)
    plt.close()

    print(counts.tail(10))
    counts.to_csv(f"{TABLE_DIR}/model_year_counts.csv", header=["vehicles"])


def port_growth_chart(stations):
    stations = stations.copy()
    stations["open_year"] = pd.to_datetime(stations["open_date"], errors="coerce").dt.year
    stations = stations.dropna(subset=["open_year"])
    stations["open_year"] = stations["open_year"].astype(int)

    per_year = stations.groupby("open_year")[["level2_ports", "dc_fast_ports"]].sum()
    cumulative = per_year.cumsum()

    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.plot(cumulative.index, cumulative["level2_ports"], marker="o", label="Level 2 ports")
    ax.plot(cumulative.index, cumulative["dc_fast_ports"], marker="o", label="DC fast ports")
    ax.set_title("Cumulative public charging ports in NY by opening year")
    ax.set_xlabel("Opening year")
    ax.set_ylabel("Cumulative ports")
    ax.set_xticks(cumulative.index)
    ax.tick_params(axis="x", rotation=45)
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/fig2_port_growth.png", dpi=200)
    plt.close()

    print(cumulative.tail(6))
    cumulative.to_csv(f"{TABLE_DIR}/cumulative_ports_by_year.csv")


def county_scatter(county):
    county = county[county["total_ports"] > 0]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(county["total_ports"], county["evs"], alpha=0.75)

    # dashed reference lines so you can read off EVs per port
    x = np.logspace(np.log10(county["total_ports"].min()), np.log10(county["total_ports"].max()), 50)
    for ratio, style in [(1, ":"), (10, "--"), (30, "-.")]:
        ax.plot(x, x * ratio, linestyle=style, color="gray", lw=0.8)
        ax.text(x[-1], x[-1] * ratio, f" {ratio} EVs/port", fontsize=7, color="gray")

    # label the counties at both ends of the ratio, plus Manhattan
    by_ratio = county.sort_values("evs_per_port")
    to_label = list(by_ratio.index[:4]) + list(by_ratio.index[-5:]) + ["061"]
    for fips in to_label:
        row = county.loc[fips]
        ax.annotate(row["name"], (row["total_ports"], row["evs"]),
                    textcoords="offset points", xytext=(4, 3), fontsize=7)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Public charging ports (Level 2 + DC fast, log scale)")
    ax.set_ylabel("Registered EVs (log scale)")
    ax.set_title("EVs vs public charging ports, by NY county")
    ax.grid(alpha=0.3, which="both")
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/fig3_county_evs_vs_ports.png", dpi=200)
    plt.close()


def region_chart(county):
    county = county.copy()
    county["region"] = "Rest of state"
    county.loc[county.index.isin(NYC_METRO), "region"] = "NYC metro"

    totals = county.groupby("region")[["evs", "total_ports", "dc_fast_ports"]].sum()
    totals["evs_per_port"] = totals["evs"] / totals["total_ports"]
    totals["evs_per_dcfc"] = totals["evs"] / totals["dc_fast_ports"]
    print(totals.round(1))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9, 4))
    colors = ["#d95f02", "#2b7bba"]

    ax1.bar(totals.index, totals["evs_per_port"], color=colors)
    ax1.set_title("EVs per public port (L2 + DC fast)", fontsize=10)

    ax2.bar(totals.index, totals["evs_per_dcfc"], color=colors)
    ax2.set_title("EVs per DC fast port", fontsize=10)

    # put the value on top of each bar
    for ax in [ax1, ax2]:
        for bar in ax.patches:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2, height, f"{height:.1f}",
                    ha="center", va="bottom", fontsize=9)
        ax.set_ylim(0, ax.get_ylim()[1] * 1.1)

    fig.suptitle("Charging demand per port: NYC metro vs rest of New York")
    plt.tight_layout()
    plt.savefig(f"{FIG_DIR}/fig4_region_ratios.png", dpi=200)
    plt.close()


def main():
    os.makedirs(FIG_DIR, exist_ok=True)
    os.makedirs(TABLE_DIR, exist_ok=True)

    stations = pd.read_parquet(STATIONS_FILE)
    reg = pd.read_parquet(REGISTRATIONS_FILE)
    with open(FIPS_FILE) as f:
        fips_to_name = json.load(f)

    # stations got unnested by connector type in the transform step,
    # so drop the duplicates or the port counts get double counted
    print("connector rows:", len(stations))
    stations = stations.drop_duplicates("station_id").copy()
    print("unique stations:", len(stations))

    stations["county_fips"] = get_station_counties(stations)
    print("stations matched to a county:", stations["county_fips"].notna().sum())

    # map registration counties to fips (OUT-OF-STATE won't match, which is what we want)
    name_to_fips = {}
    for fips, name in fips_to_name.items():
        name_to_fips[clean_county_name(name)] = fips

    reg["county_fips"] = reg["county"].apply(lambda c: name_to_fips.get(clean_county_name(c)))
    print("out of state registrations:", (reg["county"] == "OUT-OF-STATE").sum())
    print("registrations in NY counties:", reg["county_fips"].notna().sum())

    model_year_chart(reg)
    port_growth_chart(stations)

    # build one row per county with EV count and port counts
    county = pd.DataFrame({"name": pd.Series(fips_to_name)})
    county["evs"] = reg.groupby("county_fips").size()
    ports = stations.groupby("county_fips")[["level2_ports", "dc_fast_ports"]].sum()
    county = county.join(ports).fillna(0)
    county["total_ports"] = county["level2_ports"] + county["dc_fast_ports"]
    county["evs_per_port"] = county["evs"] / county["total_ports"]
    county = county.sort_values("evs", ascending=False)

    print(county[["evs", "total_ports", "evs_per_port"]].describe().round(1))

    r = np.corrcoef(np.log10(county["evs"]), np.log10(county["total_ports"]))[0, 1]
    print(f"log-log correlation between EVs and ports: r = {r:.2f}")

    top5 = county["evs"].head(5).sum() / county["evs"].sum()
    print(f"top 5 counties have {top5:.1%} of the EVs")
    print("counties with no DC fast ports:", list(county[county["dc_fast_ports"] == 0]["name"]))

    county_scatter(county)
    region_chart(county)

    county.to_csv(f"{TABLE_DIR}/county_summary.csv")


if __name__ == "__main__":
    main()
