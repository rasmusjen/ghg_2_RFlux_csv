# -*- coding: utf-8 -*-
"""
Created on Thu Sep 28 14:27:32 2023

@author: au710242
"""
# import pdb
import os
import hashlib
import html
import json
import re
import subprocess
import platform
import sys
from bisect import bisect_right
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

# Create output directory if it doesn't exist
os.makedirs(output_directory, exist_ok=True)

disturbance_file = os.path.join(input_directory, 'disturbance.txt')
script_file = os.path.abspath(__file__)
script_directory = os.path.dirname(script_file)
config_file = os.path.abspath('config.ini')
expected_files_per_day = 48

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


def load_disturbance_windows(file_path):
    if not os.path.isfile(file_path):
        return []

    try:
        disturbance_df = pd.read_csv(file_path)
    except Exception as e:
        print(f"Unable to read disturbance file {file_path}: {e}")
        return []

    required_cols = {'date_start', 'date_end'}
    if not required_cols.issubset(disturbance_df.columns):
        print(f"Disturbance file {file_path} is missing required columns: date_start,date_end")
        return []

    disturbance_df['date_start'] = pd.to_datetime(
        disturbance_df['date_start'].astype(str).str.strip(),
        format='%Y%m%d%H%M',
        errors='coerce'
    )
    disturbance_df['date_end'] = pd.to_datetime(
        disturbance_df['date_end'].astype(str).str.strip(),
        format='%Y%m%d%H%M',
        errors='coerce'
    )

    disturbance_df = disturbance_df.dropna(subset=['date_start', 'date_end'])
    disturbance_df = disturbance_df[disturbance_df['date_end'] >= disturbance_df['date_start']]

    windows = list(zip(disturbance_df['date_start'], disturbance_df['date_end']))
    if windows:
        print(f"Loaded {len(windows)} disturbance window(s) from {file_path}")
    else:
        print(f"No valid disturbance windows found in {file_path}")
    return windows


def build_disturbance_index(windows):
    if not windows:
        return [], []

    sorted_windows = sorted(windows, key=lambda item: item[0])
    merged_windows = []
    for start_dt, end_dt in sorted_windows:
        if not merged_windows:
            merged_windows.append([start_dt, end_dt])
            continue

        last_start, last_end = merged_windows[-1]
        if start_dt <= last_end:
            if end_dt > last_end:
                merged_windows[-1][1] = end_dt
        else:
            merged_windows.append([start_dt, end_dt])

    merged = [(start_dt, end_dt) for start_dt, end_dt in merged_windows]
    starts = [start_dt for start_dt, _ in merged]
    return merged, starts


def is_in_disturbance(timestamp_str, windows, window_starts):
    if not windows:
        return False

    try:
        file_dt = datetime.strptime(timestamp_str, '%Y%m%d%H%M')
    except Exception:
        return False

    idx = bisect_right(window_starts, file_dt) - 1
    if idx < 0:
        return False

    return file_dt <= windows[idx][1]


def extract_timestamp_from_file_path(file_path):
    file_name = os.path.basename(file_path)

    for pattern in [r'(?<!\d)(\d{12})(?!\d)', r'(?<!\d)(\d{14})(?!\d)']:
        candidates = re.findall(pattern, file_name)
        if not candidates:
            candidates = re.findall(pattern, file_path)

        for candidate in candidates:
            timestamp_text = candidate[:12]
            try:
                datetime.strptime(timestamp_text, '%Y%m%d%H%M')
                return timestamp_text
            except Exception:
                continue

    return None


def compute_file_hash(file_path):
    if not os.path.isfile(file_path):
        return 'N/A'

    hash_sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def normalize_remote_url(remote_url):
    if not remote_url:
        return 'N/A'

    url = remote_url.strip()
    if url.startswith('git@') and ':' in url:
        host_path = url[4:]
        host, path = host_path.split(':', 1)
        url = f"https://{host}/{path}"

    if url.endswith('.git'):
        url = url[:-4]

    return url


def get_git_metadata(path):
    def run_git(args):
        return subprocess.check_output(['git', *args], cwd=path, text=True).strip()

    metadata = {
        'short_hash': 'N/A',
        'full_hash': 'N/A',
        'branch': 'N/A',
        'remote_url': 'N/A',
        'commit_url': 'N/A'
    }

    try:
        metadata['short_hash'] = run_git(['rev-parse', '--short', 'HEAD'])
    except Exception:
        pass

    try:
        metadata['full_hash'] = run_git(['rev-parse', 'HEAD'])
    except Exception:
        pass

    try:
        metadata['branch'] = run_git(['rev-parse', '--abbrev-ref', 'HEAD'])
    except Exception:
        pass

    try:
        remote_raw = run_git(['config', '--get', 'remote.origin.url'])
        remote_https = normalize_remote_url(remote_raw)
        metadata['remote_url'] = remote_https
        if metadata['full_hash'] != 'N/A' and remote_https != 'N/A':
            metadata['commit_url'] = f"{remote_https}/commit/{metadata['full_hash']}"
    except Exception:
        pass

    return metadata


def render_table(rows, headers):
    if not rows:
        return '<p class="muted">None</p>'

    thead = ''.join(f'<th>{html.escape(h)}</th>' for h in headers)
    tbody_rows = []
    for row in rows:
        tbody_rows.append('<tr>' + ''.join(f'<td>{html.escape(str(cell))}</td>' for cell in row) + '</tr>')
    tbody = ''.join(tbody_rows)
    return f'<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>'


def render_key_value_table(items):
    if not items:
        return '<p class="muted">None</p>'

    rows = []
    for item in items:
        if len(item) == 3:
            key, value, is_html = item
        else:
            key, value = item
            is_html = False

        value_html = str(value) if is_html else html.escape(str(value))
        rows.append(
            '<tr>'
            f'<th class="kv-key">{html.escape(str(key))}</th>'
            f'<td class="mono kv-value">{value_html}</td>'
            '</tr>'
        )
    return f'<table class="kv-table"><tbody>{"".join(rows)}</tbody></table>'


def generate_coverage_plotly(day_list, converted_by_day, seen_by_day):
    if not day_list:
        return '<p class="muted">No timestamps available to render coverage chart.</p>'

    x_values = [day.strftime('%Y-%m-%d') for day in day_list]
    y_values = [int(converted_by_day.get(day, 0)) for day in day_list]
    seen_values = [int(seen_by_day.get(day, 0)) for day in day_list]

    colors = []
    for value in y_values:
        if value == expected_files_per_day:
            colors.append('#16a34a')
        elif 24 < value < expected_files_per_day:
            colors.append('#eab308')
        else:
            colors.append('#dc2626')

    na_indices = [idx for idx, seen in enumerate(seen_values) if seen == 0]
    annotations = []
    for offset, idx in enumerate(na_indices):
        annotations.append({
            'x': x_values[idx],
            'y': 1.2 + (offset % 2) * 1.0,
            'text': 'NA',
            'showarrow': False,
            'font': {'size': 10, 'color': '#111827'},
            'yanchor': 'bottom'
        })

    trace = {
        'type': 'bar',
        'x': x_values,
        'y': y_values,
        'marker': {'color': colors},
        'hovertemplate': (
            'Date: %{x}<br>'
            'Converted files: %{y}<br>'
            'Expected files: 48<extra></extra>'
        )
    }

    layout = {
        'title': {'text': 'Daily coverage (expected = 48 files/day)', 'x': 0.01},
        'xaxis': {
            'title': 'Date',
            'tickangle': -45,
            'type': 'category'
        },
        'yaxis': {
            'title': 'Converted files per day',
            'range': [0, 50],
            'dtick': 6,
            'gridcolor': '#e5e7eb'
        },
        'plot_bgcolor': '#ffffff',
        'paper_bgcolor': '#ffffff',
        'margin': {'l': 60, 'r': 20, 't': 60, 'b': 130},
        'annotations': annotations,
        'height': 460
    }

    trace_json = json.dumps(trace)
    layout_json = json.dumps(layout)

    return f'''
<div id="coverage_plot" style="min-height:460px;"></div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
  (function() {{
        const trace = {trace_json};
        const layout = {layout_json};
        if (typeof Plotly !== 'undefined') {{
            Plotly.newPlot('coverage_plot', [trace], layout, {{responsive: true, displaylogo: false}});
        }} else {{
            document.getElementById('coverage_plot').innerHTML = '<p class="muted">Plotly could not be loaded.</p>';
        }}
  }})();
</script>
'''


def write_sidecar_csv(report_context, report_filename):
    process_datetime = report_context['process_datetime'].strftime('%Y-%m-%d %H:%M:%S')
    sidecar_filename = report_filename.replace('.html', '_qa_summary.csv')
    sidecar_path = os.path.join(output_directory, sidecar_filename)

    records = []
    for record in report_context['run_records']:
        timestamp_value = record.get('timestamp_dt')
        if isinstance(timestamp_value, datetime):
            timestamp_text = timestamp_value.strftime('%Y-%m-%d %H:%M')
        else:
            timestamp_text = record.get('timestamp', 'NA')

        records.append({
            'site': station_ID,
            'year': year,
            'file_id': file_ID,
            'processing_datetime': process_datetime,
            'status': record.get('status', ''),
            'file_name': record.get('file_name', ''),
            'file_path': record.get('file_path', ''),
            'timestamp': timestamp_text,
            'reason': record.get('reason', ''),
            'row_count': record.get('row_count', ''),
            'padded_rows': record.get('padded_rows', 0),
            'output_file': record.get('output_file', '')
        })

    summary_df = pd.DataFrame(records)
    summary_df.to_csv(sidecar_path, index=False)
    return sidecar_path


def write_report(report_context):
    start_dt = report_context['start_datetime']
    end_dt = report_context['end_datetime']
    process_dt = report_context['process_datetime']

    start_token = start_dt.strftime('%Y%m%d%H%M') if start_dt is not None else 'NA'
    end_token = end_dt.strftime('%Y%m%d%H%M') if end_dt is not None else 'NA'
    process_token = process_dt.strftime('%Y%m%d%H%M%S')

    report_filename = f"{station_ID}_ghg2rluxcsv_report_{start_token}_{end_token}_{process_token}.html"
    report_path = os.path.join(output_directory, report_filename)

    settings_rows = [(k, v) for k, v in config['settings'].items()]
    settings_table = render_table(settings_rows, ['Setting', 'Value'])

    disturbance_rows = [
        (start.strftime('%Y-%m-%d %H:%M'), end.strftime('%Y-%m-%d %H:%M'))
        for start, end in report_context['disturbance_windows']
    ]
    disturbance_table = render_table(disturbance_rows, ['Date start', 'Date end'])

    mapping_rows = [
        (in1, in2, out)
        for in1, in2, out in zip(vars_subset1, vars_subset2, vars_rename)
    ]
    mapping_table = render_table(mapping_rows, ['Input name (layout A)', 'Input name (layout B)', 'Output name'])

    excluded_rows = [
        (
            item.get('timestamp', 'NA'),
            item.get('file_name', ''),
            item.get('file_path', ''),
            item.get('reason', '')
        )
        for item in report_context['excluded_disturbance']
    ]
    excluded_table = render_table(excluded_rows, ['Timestamp', 'File', 'Path', 'Reason'])

    rejected_rows = [
        (
            item.get('timestamp', 'NA'),
            item.get('file_name', ''),
            item.get('file_path', ''),
            item.get('reason', ''),
            item.get('row_count', 'NA')
        )
        for item in report_context['rejected_missing']
    ]
    rejected_table = render_table(rejected_rows, ['Timestamp', 'File', 'Path', 'Reason', 'Rows'])

    failed_rows = [
        (
            item.get('file_name', ''),
            item.get('file_path', ''),
            item.get('reason', '')
        )
        for item in report_context['failed_files']
    ]
    failed_table = render_table(failed_rows, ['File', 'Path', 'Reason'])

    coverage_plot = generate_coverage_plotly(
        report_context['day_list'],
        report_context['converted_by_day'],
        report_context['seen_by_day']
    )

    start_text = start_dt.strftime('%Y-%m-%d %H:%M') if start_dt is not None else 'N/A'
    end_text = end_dt.strftime('%Y-%m-%d %H:%M') if end_dt is not None else 'N/A'

    git_metadata = report_context.get('git_metadata', {})
    remote_url = git_metadata.get('remote_url', 'N/A')
    commit_url = git_metadata.get('commit_url', 'N/A')
    remote_link_html = (
        f'<a href="{html.escape(remote_url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(remote_url)}</a>'
        if remote_url != 'N/A' else 'N/A'
    )
    commit_link_html = (
        f'<a href="{html.escape(commit_url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(commit_url)}</a>'
        if commit_url != 'N/A' else 'N/A'
    )

    metadata_items = [
        ('Input directory', input_directory),
        ('Output directory', output_directory),
        ('Script path', script_file),
        ('Script directory', script_directory),
        ('Script SHA256', report_context['script_hash']),
        ('Config path', config_file),
        ('Config SHA256', report_context['config_hash']),
        ('Report hash', report_context['report_hash']),
        ('Git branch', git_metadata.get('branch', 'N/A')),
        ('Git short hash', git_metadata.get('short_hash', 'N/A')),
        ('Git full hash', git_metadata.get('full_hash', 'N/A')),
        ('Git repository', remote_link_html, True),
        ('Git commit link', commit_link_html, True),
        ('Disturbance file', disturbance_file),
        ('Disturbance windows loaded', report_context['stats']['disturbance_windows_loaded'])
    ]
    metadata_table = render_key_value_table(metadata_items)

    run_argument_items = [
        ('Python version', report_context['run_arguments']['python_version']),
        ('OS', report_context['run_arguments']['os']),
        ('Working directory', report_context['run_arguments']['working_directory']),
        ('Command used', report_context['run_arguments']['command'])
    ]
    run_arguments_table = render_key_value_table(run_argument_items)

    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>GHG2RFlux CSV Run Manifest</title>
  <style>
    body {{ font-family: Arial, Helvetica, sans-serif; color: #1f2937; margin: 0; background: #f8fafc; }}
    .container {{ max-width: 1260px; margin: 0 auto; padding: 24px; }}
    h1 {{ margin: 0 0 8px 0; font-size: 28px; }}
    h2 {{ margin: 28px 0 10px; font-size: 20px; border-bottom: 1px solid #e5e7eb; padding-bottom: 6px; }}
    h3 {{ margin: 20px 0 8px; font-size: 16px; }}
    .muted {{ color: #6b7280; }}
    .panel {{ background: #ffffff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; margin-bottom: 16px; }}
    .stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    .stat {{ border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px 12px; background: #ffffff; }}
    .label {{ font-size: 12px; color: #6b7280; text-transform: uppercase; letter-spacing: .04em; }}
    .value {{ font-size: 20px; font-weight: 700; margin-top: 4px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f3f4f6; font-weight: 600; }}
    .chart-wrap {{ overflow-x: auto; border: 1px solid #e5e7eb; border-radius: 8px; background: #ffffff; padding: 8px; }}
    .mono {{ font-family: Consolas, Menlo, monospace; font-size: 12px; }}
        .kv-table {{ width: 100%; border-collapse: collapse; table-layout: fixed; }}
        .kv-key {{ width: 240px; background: #f9fafb; }}
        .kv-value {{ white-space: normal; overflow-wrap: anywhere; word-break: break-word; line-height: 1.35; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="panel">
      <h1>GHG2RFlux CSV Run Manifest</h1>
      <p class="muted">Site: {html.escape(station_ID)} | Processing datetime: {process_dt.strftime('%Y-%m-%d %H:%M:%S')} | Script version: {html.escape(report_context['script_version'])}</p>
      <p class="muted">Data window from {start_text} to {end_text}</p>
    </div>

    <h2>Run Summary</h2>
    <div class="stats">
      <div class="stat"><div class="label">Discovered .ghg files</div><div class="value">{report_context['stats']['total_discovered']}</div></div>
      <div class="stat"><div class="label">Converted files</div><div class="value">{report_context['stats']['converted_total']}</div></div>
      <div class="stat"><div class="label">Disturbance excluded</div><div class="value">{report_context['stats']['excluded_disturbance']}</div></div>
            <div class="stat"><div class="label">Excluded by prefilter</div><div class="value">{report_context['stats']['excluded_disturbance_prefilter']}</div></div>
            <div class="stat"><div class="label">Excluded after parse</div><div class="value">{report_context['stats']['excluded_disturbance_post_parse']}</div></div>
      <div class="stat"><div class="label">Rejected (>10% missing)</div><div class="value">{report_context['stats']['rejected_missing']}</div></div>
      <div class="stat"><div class="label">Failed parse/read</div><div class="value">{report_context['stats']['failed_parse']}</div></div>
      <div class="stat"><div class="label">Expected rows per file</div><div class="value">{report_context['stats']['expected_rows_per_file']}</div></div>
    </div>

    <h2>Coverage</h2>
    <div class="panel">
      <p class="muted">Daily converted-file coverage (expected = 48 files/day). NA indicates no timestamped input files found for that day.</p>
            <div class="chart-wrap">{coverage_plot}</div>
    </div>

    <h2>Reproducibility Metadata</h2>
    <div class="panel">{metadata_table}</div>

        <h3>Run arguments</h3>
        <div class="panel">{run_arguments_table}</div>

    <h3>Config settings</h3>
    <div class="panel">{settings_table}</div>

    <h3>Input-to-output variable mapping</h3>
    <div class="panel">{mapping_table}</div>

    <h3>Disturbance windows applied</h3>
    <div class="panel">{disturbance_table}</div>

    <h2>Excluded / Rejected / Failed Files</h2>
    <h3>Excluded by disturbance windows</h3>
    <div class="panel">{excluded_table}</div>

    <h3>Rejected due to missing data (>10%)</h3>
    <div class="panel">{rejected_table}</div>

    <h3>Failed to parse/read</h3>
    <div class="panel">{failed_table}</div>
  </div>
</body>
</html>
"""

    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    sidecar_path = write_sidecar_csv(report_context, report_filename)
    return report_path, sidecar_path

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
                df['TIMESTAMP'] = df['Datetime'].dt.strftime('%Y%m%d%H%M%S.%f')
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
        return df1, timestamp, None

    except Exception as e:
        print(f"Error processing file {file_path}: {e}")
        return None, None, str(e)


ghg_files = []
for root, _, files in os.walk(input_directory):
    for file in files:
        if file.endswith('.ghg'):
            ghg_files.append(os.path.join(root, file))

total_files = len(ghg_files)
disturbance_windows = load_disturbance_windows(disturbance_file)
disturbance_windows_indexed, disturbance_window_starts = build_disturbance_index(disturbance_windows)
expected_rows = 60 * 30 * hz
run_started = datetime.now()

run_records = []
converted_timestamps = []
seen_timestamps = []
# Initialize a progress bar
pbar = tqdm(total=total_files)

# Iterate through .ghg files
for file_path in ghg_files:
    file_name = os.path.basename(file_path)

    timestamp_hint = extract_timestamp_from_file_path(file_path)
    timestamp_hint_dt = None
    if timestamp_hint is not None:
        try:
            timestamp_hint_dt = datetime.strptime(timestamp_hint, '%Y%m%d%H%M')
            seen_timestamps.append(timestamp_hint_dt)
        except Exception:
            timestamp_hint_dt = None

    if timestamp_hint and is_in_disturbance(timestamp_hint, disturbance_windows_indexed, disturbance_window_starts):
        print("File omitted due to disturbance window (prefilter):", file_path)
        run_records.append({
            'status': 'excluded_disturbance',
            'file_name': file_name,
            'file_path': file_path,
            'timestamp': timestamp_hint,
            'timestamp_dt': timestamp_hint_dt,
            'reason': 'Timestamp within disturbance window (prefilter)'
        })
        pbar.update(1)
        continue

    df1, timestamp, error_message = process_ghg_file(file_path)

    timestamp_dt = None
    if timestamp is not None:
        try:
            timestamp_dt = datetime.strptime(timestamp, '%Y%m%d%H%M')
            if timestamp_hint_dt is None or timestamp_dt != timestamp_hint_dt:
                seen_timestamps.append(timestamp_dt)
        except Exception:
            timestamp_dt = None

    if df1 is None:
        print("File could not be processed:", file_path)
        run_records.append({
            'status': 'failed_parse',
            'file_name': file_name,
            'file_path': file_path,
            'timestamp': timestamp if timestamp else 'NA',
            'timestamp_dt': timestamp_dt,
            'reason': error_message if error_message else 'File is empty or invalid archive'
        })
        pbar.update(1)
        continue

    if is_in_disturbance(timestamp, disturbance_windows_indexed, disturbance_window_starts):
        print("File omitted due to disturbance window:", file_path)
        run_records.append({
            'status': 'excluded_disturbance',
            'file_name': file_name,
            'file_path': file_path,
            'timestamp': timestamp,
            'timestamp_dt': timestamp_dt,
            'reason': 'Timestamp within disturbance window',
            'row_count': len(df1)
        })
        pbar.update(1)
        continue

    if len(df1) < expected_rows * 0.9:
        print("File is omitted. Missing more than 10% of data:", file_path)
        run_records.append({
            'status': 'rejected_missing',
            'file_name': file_name,
            'file_path': file_path,
            'timestamp': timestamp,
            'timestamp_dt': timestamp_dt,
            'reason': 'More than 10% rows missing',
            'row_count': len(df1)
        })
        pbar.update(1)
        continue

    padded_rows = 0
    status = 'converted_full'
    if len(df1) < expected_rows:
        missing_rows = expected_rows - len(df1)
        padded_rows = missing_rows
        add_missing_rows = pd.DataFrame({col: [-9999] * missing_rows for col in df1.columns})
        df1 = pd.concat([df1, add_missing_rows], ignore_index=True)
        status = 'converted_padded'

    output_file_name = f"{station_ID}_EC_{timestamp}_{file_ID}.csv"
    output_file_path = os.path.join(output_directory, output_file_name)
    df1.to_csv(output_file_path, index=False)

    run_records.append({
        'status': status,
        'file_name': file_name,
        'file_path': file_path,
        'timestamp': timestamp,
        'timestamp_dt': timestamp_dt,
        'reason': '',
        'row_count': len(df1),
        'padded_rows': padded_rows,
        'output_file': output_file_path
    })
    if timestamp_dt is not None:
        converted_timestamps.append(timestamp_dt)

    pbar.update(1)

# Close the progress bar
pbar.close()

start_datetime = None
end_datetime = None
all_timestamps = []
for record in run_records:
    record_timestamp = record.get('timestamp_dt')
    if isinstance(record_timestamp, datetime):
        all_timestamps.append(record_timestamp)
if all_timestamps:
    start_datetime = min(all_timestamps)
    end_datetime = max(all_timestamps)
    day_list = list(pd.date_range(start_datetime.date(), end_datetime.date(), freq='D').to_pydatetime())
    day_list = [day.replace(hour=0, minute=0, second=0, microsecond=0) for day in day_list]
else:
    day_list = []

converted_by_day = {}
seen_by_day = {}
for day in day_list:
    converted_by_day[day] = 0
    seen_by_day[day] = 0

for ts in seen_timestamps:
    day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if day in seen_by_day:
        seen_by_day[day] += 1

for ts in converted_timestamps:
    day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    if day in converted_by_day:
        converted_by_day[day] += 1

converted_full = sum(1 for r in run_records if r['status'] == 'converted_full')
converted_padded = sum(1 for r in run_records if r['status'] == 'converted_padded')
excluded_disturbance = [r for r in run_records if r['status'] == 'excluded_disturbance']
excluded_disturbance_prefilter = [
    r for r in excluded_disturbance
    if 'prefilter' in str(r.get('reason', '')).lower()
]
excluded_disturbance_post_parse = [
    r for r in excluded_disturbance
    if 'prefilter' not in str(r.get('reason', '')).lower()
]
rejected_missing = [r for r in run_records if r['status'] == 'rejected_missing']
failed_files = [r for r in run_records if r['status'] == 'failed_parse']

script_hash = compute_file_hash(script_file)
config_hash = compute_file_hash(config_file)
git_metadata = get_git_metadata(script_directory)
script_version = git_metadata['short_hash']
run_finished = datetime.now()
run_arguments = {
    'python_version': sys.version.replace('\n', ' '),
    'os': f"{platform.system()} {platform.release()} ({platform.version()})",
    'working_directory': os.getcwd(),
    'command': 'python ' + os.path.basename(script_file)
}

report_hash_source = (
    f"{station_ID}|{year}|{file_ID}|{hz}|{run_started.isoformat()}|{run_finished.isoformat()}|"
    f"{len(ghg_files)}|{converted_full}|{converted_padded}|{len(excluded_disturbance)}|"
    f"{len(rejected_missing)}|{len(failed_files)}|{script_hash}|{config_hash}"
)
report_hash = hashlib.sha256(report_hash_source.encode('utf-8')).hexdigest()

report_context = {
    'start_datetime': start_datetime,
    'end_datetime': end_datetime,
    'process_datetime': run_finished,
    'script_hash': script_hash,
    'config_hash': config_hash,
    'report_hash': report_hash,
    'script_version': script_version,
    'git_metadata': git_metadata,
    'disturbance_windows': disturbance_windows,
    'excluded_disturbance': excluded_disturbance,
    'rejected_missing': rejected_missing,
    'failed_files': failed_files,
    'day_list': day_list,
    'converted_by_day': converted_by_day,
    'seen_by_day': seen_by_day,
    'run_records': run_records,
    'run_arguments': run_arguments,
    'stats': {
        'total_discovered': len(ghg_files),
        'converted_total': converted_full + converted_padded,
        'converted_full': converted_full,
        'converted_padded': converted_padded,
        'excluded_disturbance': len(excluded_disturbance),
        'excluded_disturbance_prefilter': len(excluded_disturbance_prefilter),
        'excluded_disturbance_post_parse': len(excluded_disturbance_post_parse),
        'rejected_missing': len(rejected_missing),
        'failed_parse': len(failed_files),
        'expected_rows_per_file': expected_rows,
        'disturbance_windows_loaded': len(disturbance_windows)
    }
}

report_path, sidecar_path = write_report(report_context)
print(f"Run manifest written: {report_path}")
print(f"QA sidecar CSV written: {sidecar_path}")
