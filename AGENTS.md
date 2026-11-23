# IBMA WireWalker Processor #
This repository contains a python3 script that reads NetCDF files from the IBMA WireWalker and processes them. The 
output must be compatible with EMSO Metadata Specifications and follow Climate and Forecast (CF) Discrete Sampling
Geometries (DSG).

Input: 
* IBMA-style NetCDF file. Example in `15day1clean-nc`

Output:
* EMSO-compliant raw dataset (DSG: trajectory)
* EMSO-compliant processed dataset, aggregated per bin depth (DSG: timeSeriesProfile)

The metadata and the data should be extracted from the source NetCDF file. The nc datasets must be created with
`emso_metadata_harmonizer` python3 package, specifically `generate_dataset()` funciont. 

## Coding style ##
Instead of producing spaghetti code, encapsulate each logic block into a function or class method: 

```python3
data, metadata = read_ibma_dataset(file)
raw_profiles = detect_profiles(data)
avg_profiles = average_profiles(raw_profiles)
```

Keep it functional and simple. Do not overcomplicate things.

## Averaging Strategy ##
Averaging is a bit more complex that simply calling .mean() for every bin. We need to take a look at the quality control
column (_QC) and average only the best-possible data quality:

```
time    TEMP    TEMP_QC using_it?
00:00   13.45   1   yes
00:01   13.78   1   yes 
00:02   14.79   3   no
00:03   13.34   1   yes
```

However, in some cases we may only have suspicious or bad data:

```
time    TEMP    TEMP_QC using_it?
00:00   13.45   3   yes
00:01   13.78   3   yes 
00:02   14.79   4   no
00:03   13.34   3   yes
```

If we have at least 1 point with good data, average only the good data. Basically, take the lowest QC value in the segment and
average only that qc value. The only exception is that 0 should not be processed.

Some derived variables (e.g. `SVEL`, `DENS_AN`, `CNDC_SPEC`) have no `_QC` column of their own.
For these, just average every value in the bin unconditionally. Never invent or deduce a QC flag
for them from the QC of the variables they were derived from.


## Execution ##
The code should be a simple python3 script. No CLI interface, nothing too complext

```bash
python3 wirewalker_processor.py <input_file.nc> <raw_dataset.nc> <processed_dataset.nc>
```

Additional options: `--depth-bin` the size of the depth bin. Defaults to 1 meter.