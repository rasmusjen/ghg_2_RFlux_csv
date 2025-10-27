# ghg_2_RFlux_csv

Read raw .ghg files and write .csv file formatted for RFlux.

## Description

This Python script processes raw `.ghg` files (compressed archive files containing eddy covariance data) and converts them to `.csv` files formatted for RFlux analysis. The script extracts data from zipped archives, processes time series data, and exports formatted CSV files with standardized column names.

## Prerequisites

- Python 3.7 or higher
- PowerShell (Windows)

## Setup Instructions

### 1. Create Virtual Environment

Open PowerShell and navigate to the project directory:

```powershell
cd c:\Users\au710242\Code\Python\ghg_2_RFlux_csv
python -m venv venv
```

### 2. Activate Virtual Environment

You can activate the virtual environment in two ways:

**Option A: Use the activation script (Recommended)**
```powershell
.\activate_venv.ps1
```

**Option B: Activate manually**
```powershell
.\venv\Scripts\Activate.ps1
```

After activation, you should see `(venv)` at the beginning of your PowerShell prompt.

### 3. Install Required Packages

With the virtual environment activated, install the required dependencies:

```powershell
pip install -r requirements.txt
```

## Configuration

Before running the script, edit `config.ini` to set your parameters:

```ini
[settings]
station_ID = GL-ZaH
year = 2019
file_ID = F10
hz = 10
```

- `station_ID`: Station identifier
- `year`: Year of data collection
- `file_ID`: File identifier for output naming
- `hz`: Sampling frequency in Hz

## Running the Script

With the virtual environment activated, run:

```powershell
python GHG2RFLUX.py
```

The script will:
1. Read `.ghg` files from the input directory: `D:\L0_raw\{station_ID}\{year}\ec\raw`
2. Process and convert the data
3. Output `.csv` files to: `D:\L0_raw\{station_ID}\{year}\ec\rflux_csv`

## Required Python Packages

The following packages are required (automatically installed from `requirements.txt`):
- `pandas>=2.0.0` - Data manipulation and analysis
- `tqdm>=4.65.0` - Progress bar functionality

Additional standard library modules used:
- `os` - File and directory operations
- `datetime` - Date and time handling
- `zipfile` - ZIP archive handling
- `configparser` - Configuration file parsing

## Troubleshooting

### PowerShell Execution Policy Error

If you encounter an error when running the activation script:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then try running `.\activate_venv.ps1` again.

### Virtual Environment Not Found

If the activation script reports that the virtual environment is not found, make sure you've created it:

```powershell
python -m venv venv
```

## Deactivating the Virtual Environment

When you're done, deactivate the virtual environment:

```powershell
deactivate
```

## License

See LICENSE file for details.
