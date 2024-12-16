# -*- coding: utf-8 -*-
"""
Created on Thu Sep 28 14:27:32 2023

@author: au710242
"""
# import pdb
import os
import pandas as pd
from datetime import datetime
from pandas.tseries.offsets import DateOffset
import zipfile
from tqdm import tqdm
import configparser  # Import configparser to read the INI file

# Read configuration from config.ini
config = configparser.ConfigParser()
config.read('config.ini')

station_ID = config['settings']['station_ID']
year = int(config['settings']['year'])
file_ID = config['settings']['file_ID']
hz = int(config['settings']['hz'])

# Define the input and output directories
input_directory = fr'D:\L0_raw\{station_ID}\{year}\ec\raw'
output_directory = fr'D:\L0_raw\{station_ID}\{year}\ec\rflux_csv'

vars_subset1 = [ 'U (m/s)', 'V (m/s)', 'W (m/s)', 'T (C)',
               'Anemometer Diagnostics','Diagnostic Value',
               'CO2 dry(umol/mol)', 'H2O dry(mmol/mol)',
               'Cell Temperature (C)', 'Temperature In (C)', 'Temperature Out (C)',
               'Total Pressure (kPa)',
               ]

vars_subset2 = ['Aux 1 - U (m/s)', 'Aux 2 - V (m/s)', 'Aux 3 - W (m/s)', 'Aux 4 - Ts (C)',
               'Anemometer Diagnostics','Diagnostic Value',
               'CO2 dry(umol/mol)', 'H2O dry(mmol/mol)',
               'Cell Temperature (C)', 'Temperature In (C)', 'Temperature Out (C)',
               'Total Pressure (kPa)',
               ]

vars_rename = ['U', 'V', 'W', 'T_SONIC', 
               'SA_DIAG','GA_DIAG',
               'CO2', 'H2O',
               'T_CELL', 'T_CELL_IN', 'T_CELL_OUT',
               'PRESS_CELL']

# A function to process each .ghg file
def process_ghg_file(file_path):
    try:
        # Extract the .data file from the .ghg archive
        with zipfile.ZipFile(file_path, 'r') as archive:
            data_file_name = [f for f in archive.namelist() if f.endswith('.data')][0]
            with archive.open(data_file_name) as data_file:
                df = pd.read_csv(data_file, header=[0], skiprows=7, delimiter='\t')
                df['Datetime'] = (pd.to_datetime(df['Seconds'], unit='s') + pd.to_timedelta(df['Nanoseconds'], unit = 'ns')) + DateOffset(milliseconds=100) # DateOffset must be Interger, i.e. miliseconds
                df.index = df['Datetime']
                df['TIMESTAMP'] = df.index.strftime('%Y%m%d%H%M%S.%f')
                df['TIMESTAMP'] = pd.to_numeric(df['TIMESTAMP'])
                # df['Datetime'] = df['Datetime'].apply(lambda x: datetime.strptime(x, '%Y-%m-%d %H:%M:%S:%f').timestamp())
                # df.drop(columns=['Anemometer Diagnostics'])
                df['Anemometer Diagnostics'] = -9999

        # Extract columns and rename them
        if 'U (m/s)' in df.columns and 'V (m/s)' in df.columns:
            df1 = df.loc[:, vars_subset1]
            df1 = df1.rename(columns=dict(zip(vars_subset1, vars_rename)))
        else:
            df1 = df.loc[:, vars_subset2]
            df1 = df1.rename(columns=dict(zip(vars_subset2, vars_rename)))
        timestamp = str(df['TIMESTAMP'].iloc[-1])[:12]
        # pdb.set_trace()
        return df1, timestamp

    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return None, None


total_files = sum(len(files) for _, _, files in os.walk(input_directory) if any(f.endswith('.ghg') for f in files))
# Initialize a progress bar
pbar = tqdm(total=total_files)

# Iterate through .ghg files
for root, dirs, files in os.walk(input_directory):
    for file in files:
        if file.endswith(".ghg"):
            file_path = os.path.join(root, file)
            df1, timestamp = process_ghg_file(file_path)
            
            if df1 is None:
                print("File is empty:", file_path)
                continue
            elif len(df1)<60*30*hz*0.9:
                print("File is omitted. Missig more than 10% of data:", file_path)
                continue
            elif len(df1)<60*30*hz:
                missing_rows = (60*30*hz)-len(df1)
                add_missing_rows = pd.DataFrame({col: [-9999] * missing_rows for col in df1.columns})
                df1 = pd.concat([df1, add_missing_rows], ignore_index=True)


            # Create output file path
            output_file_name = f"{station_ID}_EC_{timestamp}_{file_ID}.csv"
            output_file_path = os.path.join(output_directory, output_file_name)

            # Write to CSV
            df1.to_csv(output_file_path, index=False)
            # Update progress bar
            pbar.update(1)

# Close the progress bar
pbar.close()
