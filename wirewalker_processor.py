#!/usr/bin/env python3
"""
Converts an IBMA-style wire-walker NetCDF file into two EMSO-compliant, CF Discrete Sampling
Geometry datasets:
  * a raw dataset (featureType: trajectory) - the source data, reshaped only.
  * a processed dataset (featureType: timeSeriesProfile) - detected casts, averaged into
    fixed-size depth bins using the QC-aware strategy described in AGENTS.md.

Usage:
    python3 wirewalker_processor.py <input_file.nc> <raw_dataset.nc> <processed_dataset.nc> [--depth-bin 1.0]
"""
import argparse
import logging

import numpy as np
import pandas as pd
import xarray as xr
from emso_metadata_harmonizer.dataset_generator import generate_dataset

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("wirewalker_processor")

# All data in the source file comes from one merged stream (depth/time are shared, not split
# per physical sensor), so there is no per-row way to attribute a record to one specific
# instrument. EMSO/CF still require a sensor_id whenever more than one sensor is declared, so
# every record is attributed to the primary CTD, which hosts the pressure sensor the whole
# depth axis is derived from.
PRIMARY_SENSOR_ID = "RBRmaestro3_SN204388"

# Zig-zag turning-point threshold (metres): a direction only flips once depth has moved back by
# more than this, so normal sample-to-sample jitter is never mistaken for the start of a cast.
# The source file's own summary states ~140 m casts at 4 per hour, so 20 m comfortably separates
# jitter from a real turn.
MIN_EXCURSION_M = 20.0

# NetCDF bookkeeping attrs that are not part of the EMSO metadata schema.
_SKIP_ATTRS = {"_FillValue", "coordinates"}


def read_ibma_dataset(file: str) -> (pd.DataFrame, dict):
    """Reads an IBMA wire-walker NetCDF file into (dataframe, EMSO metadata dict)."""
    ds = xr.open_dataset(file)
    df = _build_dataframe(ds)
    metadata = _build_metadata(ds)
    return df, metadata


def _attrs_to_dict(attrs: dict) -> dict:
    return {k: v for k, v in attrs.items() if k not in _SKIP_ATTRS and v not in (None, "")}


def _data_variables(ds: xr.Dataset) -> list:
    """Variables carrying actual time-series data (excludes the 0-d sensor/platform anchors)."""
    return [v for v in ds.data_vars if ds[v].dims == ("time",)]


def _qc_rename_map(ds: xr.Dataset) -> dict:
    """
    The harmonizer only resolves a QC column by the '<var>_QC' naming convention, not via the
    source file's own 'ancillary_variables' attribute. 'measurementValue' is QC'd by 'FLU2_QC'
    (the original, pre-Darwin-Core channel name), which breaks that convention. Maps any such
    QC column to the name the convention expects, so it stays correctly linked to its variable.
    """
    rename = {}
    for var in _data_variables(ds):
        if var.endswith("_QC"):
            continue
        qc_col = ds[var].attrs.get("ancillary_variables")
        if qc_col and qc_col != f"{var}_QC":
            rename[qc_col] = f"{var}_QC"
    return rename


def _build_dataframe(ds: xr.Dataset) -> pd.DataFrame:
    df = ds[_data_variables(ds)].to_dataframe().reset_index()
    df = df.rename(columns=_qc_rename_map(ds))
    df["latitude"] = float(ds["latitude"].values[0])
    df["longitude"] = float(ds["longitude"].values[0])
    df["platform_id"] = str(ds["platform_id"].values)
    df["sensor_id"] = PRIMARY_SENSOR_ID
    return df


def _platform_type_uri(ds: xr.Dataset) -> str | None:
    """
    The platform_type_uri (mandatory) is not stored on any variable directly, but the file's
    global `keywords_uri` list does carry an L06 (SeaVoX Platform Categories) term for it -
    the one vocabulary this field must resolve against.
    """
    uris = ds.attrs.get("keywords_uri", "")
    for uri in uris.split():
        if "/L06/" in uri:
            return uri
    return None


def _build_metadata(ds: xr.Dataset) -> dict:
    global_meta = _attrs_to_dict(ds.attrs)

    platform_id = str(ds["platform_id"].values)
    platforms = {
        platform_id: {
            "long_name": global_meta.get("source", platform_id),
            "latitude": float(ds["latitude"].values[0]),
            "longitude": float(ds["longitude"].values[0]),
        }
    }
    platform_type_uri = _platform_type_uri(ds)
    if platform_type_uri:
        platforms[platform_id]["platform_type_uri"] = platform_type_uri
    else:
        log.warning("platform_type_uri could not be resolved from the source file - leaving unset")
    if global_meta.get("emso_site_uri"):
        platforms[platform_id]["platform_reference"] = global_meta["emso_site_uri"]

    sensors = {str(sid): _attrs_to_dict(ds[str(sid)].attrs) for sid in ds["sensor_id"].values}

    variables = {v: _attrs_to_dict(ds[v].attrs) for v in _data_variables(ds) if not v.endswith("_QC")}
    qc_rename = _qc_rename_map(ds)
    for meta in variables.values():
        if meta.get("ancillary_variables") in qc_rename:
            meta["ancillary_variables"] = qc_rename[meta["ancillary_variables"]]

    if not global_meta.get("title"):
        log.warning("global 'title' is empty in the source file and is mandatory for EMSO - "
                    "leaving unset rather than inventing one")
        global_meta["title"] = "TITLE IS MISSING"


    return {"global": global_meta, "platforms": platforms, "sensors": sensors, "variables": variables}


def detect_profiles(df: pd.DataFrame) -> list:
    """
    Detects individual wire-walker casts (one monotonic up or down leg each) using a zig-zag
    turning-point detector on the depth time series, and returns one DataFrame per cast with
    'profile_id' and 'profile_time' (the cast's midpoint timestamp) columns added.
    """
    depth_ts = df.drop_duplicates(subset="time").sort_values("time").reset_index(drop=True)
    depths = depth_ts["depth"].to_numpy()
    times = depth_ts["time"]

    turning_idx = [0]
    direction = None
    extreme_idx, extreme_val = 0, depths[0]

    for i in range(1, len(depths)):
        val = depths[i]
        if direction is None:
            if val - extreme_val > MIN_EXCURSION_M:
                direction = "down"
            elif extreme_val - val > MIN_EXCURSION_M:
                direction = "up"
            else:
                continue
        if direction == "down":
            if val >= extreme_val:
                extreme_val, extreme_idx = val, i
            elif extreme_val - val > MIN_EXCURSION_M:
                turning_idx.append(extreme_idx)
                direction = "up"
                extreme_val, extreme_idx = val, i
        else:  # direction == "up"
            if val <= extreme_val:
                extreme_val, extreme_idx = val, i
            elif val - extreme_val > MIN_EXCURSION_M:
                turning_idx.append(extreme_idx)
                direction = "down"
                extreme_val, extreme_idx = val, i
    turning_idx.append(extreme_idx)

    raw_profiles = []
    for profile_id, (a, b) in enumerate(zip(turning_idx[:-1], turning_idx[1:])):
        start_time, end_time = times.iloc[a], times.iloc[b]
        cast = df[(df["time"] >= start_time) & (df["time"] <= end_time)].copy()
        cast["profile_id"] = profile_id
        cast["profile_time"] = start_time + (end_time - start_time) / 2
        raw_profiles.append(cast)

    log.info(f"detected {len(raw_profiles)} profiles")
    return raw_profiles


def _qc_column_map(metadata: dict) -> dict:
    """Maps each variable to its QC column via the source file's own ancillary_variables attr."""
    return {
        var: meta["ancillary_variables"]
        for var, meta in metadata["variables"].items()
        if "ancillary_variables" in meta
    }


def _aggregate_profile(cast: pd.DataFrame, qc_map: dict, depth_bin: float) -> pd.DataFrame:
    """
    Bins one cast into fixed-size depth cells centered on multiples of depth_bin (cell `d`
    covers [d - depth_bin/2, d + depth_bin/2), giving a fixed integer-valued depth axis when
    depth_bin=1) and averages each cell (QC-aware), vectorized across all of the cast's bins
    at once rather than looping bin by bin:
      - variable with a QC column: average only the records at the best (lowest, excluding
        0/unknown) QC value present in that bin.
      - variable with no QC column: average every value in the bin, unconditionally - never
        invent or deduce a QC flag for it.
    """
    depth_cell = np.round(cast["depth"].to_numpy() / depth_bin) * depth_bin

    out = {"depth": pd.Series(depth_cell, index=cast.index).groupby(depth_cell).first()}
    for var, qc_col in qc_map.items():
        qc = cast[qc_col].where(cast[qc_col] != 0)  # QC==0/unknown never counts
        best_qc = qc.groupby(depth_cell).transform("min")
        out[var] = cast[var].where(qc == best_qc).groupby(depth_cell).mean()
        out[qc_col] = qc.groupby(depth_cell).min()

    no_qc_vars = [v for v in cast.columns if v not in qc_map and v not in qc_map.values()
                  and v not in ("time", "depth", "latitude", "longitude", "platform_id",
                                "sensor_id", "profile_id", "profile_time")]
    for var in no_qc_vars:
        out[var] = cast[var].groupby(depth_cell).mean()

    binned = pd.concat(out, axis=1).reset_index(drop=True)
    # "time" is the profile discriminator (cf_role=profile_id downstream), so the internal
    # profile_id bookkeeping column itself has no place in the output dataset.
    binned["time"] = cast["profile_time"].iloc[0]
    binned["latitude"] = cast["latitude"].iloc[0]
    binned["longitude"] = cast["longitude"].iloc[0]
    binned["platform_id"] = cast["platform_id"].iloc[0]
    binned["sensor_id"] = cast["sensor_id"].iloc[0]
    return binned.sort_values("depth").reset_index(drop=True)


def average_profiles(raw_profiles: list, metadata: dict, depth_bin: float = 1.0) -> pd.DataFrame:
    """Bins every detected cast into fixed-size depth cells and averages each cell (QC-aware)."""
    qc_map = _qc_column_map(metadata)
    n = len(raw_profiles)
    log_every = max(1, n // 20)  # ~20 progress lines regardless of profile count

    binned_profiles = []
    for i, cast in enumerate(raw_profiles, start=1):
        if i == 1 or i == n or i % log_every == 0:
            log.info(f"averaging profile {i} of {n}")
        binned_profiles.append(_aggregate_profile(cast, qc_map, depth_bin))

    return pd.concat(binned_profiles, ignore_index=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="IBMA-style input NetCDF file")
    parser.add_argument("raw_dataset", help="output path for the raw (trajectory) NetCDF")
    parser.add_argument("processed_dataset", help="output path for the processed (timeSeriesProfile) NetCDF")
    parser.add_argument("--depth-bin", type=float, default=1.0, help="depth bin size in metres (default: 1.0)")
    args = parser.parse_args()

    data, metadata = read_ibma_dataset(args.input_file)

    raw_metadata = {**metadata, "global": {**metadata["global"], "featureType": "trajectory"}}
    log.info(f"generating raw dataset {args.raw_dataset}")
    generate_dataset(data, raw_metadata, args.raw_dataset)

    raw_profiles = detect_profiles(data)
    avg_profiles = average_profiles(raw_profiles, metadata, depth_bin=args.depth_bin)

    processed_metadata = {**metadata, "global": {**metadata["global"], "featureType": "timeSeriesProfile"}}
    log.info(f"generating processed dataset {args.processed_dataset}")
    generate_dataset(avg_profiles, processed_metadata, args.processed_dataset)


if __name__ == "__main__":
    main()
