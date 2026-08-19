"""HTML QA manifest and sidecar CSV.

Transplanted from GHG2RFLUX.py:237-581. The original read module-level globals;
here every value arrives through ``report_context`` so a run is self-contained.

The rendered HTML is intentionally unchanged for a single-frequency run with no
directory markers -- that identity is what ``tests/test_golden.py`` asserts. The
folder-settings table and the frequency-mismatch banner appear only when a run
actually has markers or a mismatch, so ordinary reports look exactly as before.
"""

from __future__ import annotations

import html
import json
import os
from datetime import datetime
from typing import Any

import pandas as pd

from .columns import VARS_RENAME, VARS_SUBSET1, VARS_SUBSET2


def render_table(rows: list[tuple[Any, ...]], headers: list[str]) -> str:
    if not rows:
        return '<p class="muted">None</p>'

    thead = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    tbody_rows = []
    for row in rows:
        tbody_rows.append(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        )
    tbody = "".join(tbody_rows)
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{tbody}</tbody></table>"


def render_key_value_table(items: list[tuple[Any, ...]]) -> str:
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
            "<tr>"
            f'<th class="kv-key">{html.escape(str(key))}</th>'
            f'<td class="mono kv-value">{value_html}</td>'
            "</tr>"
        )
    return f'<table class="kv-table"><tbody>{"".join(rows)}</tbody></table>'


def generate_coverage_plotly(
    day_list: list[datetime],
    converted_by_day: dict[datetime, int],
    seen_by_day: dict[datetime, int],
    expected_files_per_day: int = 48,
) -> str:
    if not day_list:
        return '<p class="muted">No timestamps available to render coverage chart.</p>'

    x_values = [day.strftime("%Y-%m-%d") for day in day_list]
    y_values = [int(converted_by_day.get(day, 0)) for day in day_list]
    seen_values = [int(seen_by_day.get(day, 0)) for day in day_list]

    half = expected_files_per_day // 2
    colors = []
    for value in y_values:
        if value == expected_files_per_day:
            colors.append("#16a34a")
        elif half < value < expected_files_per_day:
            colors.append("#eab308")
        else:
            colors.append("#dc2626")

    na_indices = [idx for idx, seen in enumerate(seen_values) if seen == 0]
    annotations = []
    for offset, idx in enumerate(na_indices):
        annotations.append(
            {
                "x": x_values[idx],
                "y": 1.2 + (offset % 2) * 1.0,
                "text": "NA",
                "showarrow": False,
                "font": {"size": 10, "color": "#111827"},
                "yanchor": "bottom",
            }
        )

    trace = {
        "type": "bar",
        "x": x_values,
        "y": y_values,
        "marker": {"color": colors},
        "hovertemplate": (
            "Date: %{x}<br>"
            "Converted files: %{y}<br>"
            f"Expected files: {expected_files_per_day}<extra></extra>"
        ),
    }

    layout = {
        "title": {
            "text": f"Daily coverage (expected = {expected_files_per_day} files/day)",
            "x": 0.01,
        },
        "xaxis": {"title": "Date", "tickangle": -45, "type": "category"},
        "yaxis": {
            "title": "Converted files per day",
            "range": [0, expected_files_per_day + 2],
            "dtick": 6,
            "gridcolor": "#e5e7eb",
        },
        "plot_bgcolor": "#ffffff",
        "paper_bgcolor": "#ffffff",
        "margin": {"l": 60, "r": 20, "t": 60, "b": 130},
        "annotations": annotations,
        "height": 460,
    }

    trace_json = json.dumps(trace)
    layout_json = json.dumps(layout)

    return f"""
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
"""


def write_sidecar_csv(report_context: dict[str, Any], report_filename: str) -> str:
    process_datetime = report_context["process_datetime"].strftime("%Y-%m-%d %H:%M:%S")
    sidecar_filename = report_filename.replace(".html", "_qa_summary.csv")
    sidecar_path = os.path.join(report_context["output_directory"], sidecar_filename)

    extended = report_context.get("extended_sidecar", False)
    records = []
    for record in report_context["run_records"]:
        timestamp_value = record.get("timestamp_dt")
        if isinstance(timestamp_value, datetime):
            timestamp_text = timestamp_value.strftime("%Y-%m-%d %H:%M")
        else:
            timestamp_text = record.get("timestamp", "NA")

        row = {
            "site": report_context["station_ID"],
            "year": report_context["year"],
            "file_id": record.get("file_id", report_context["file_ID"]),
            "processing_datetime": process_datetime,
            "status": record.get("status", ""),
            "file_name": record.get("file_name", ""),
            "file_path": record.get("file_path", ""),
            "timestamp": timestamp_text,
            "reason": record.get("reason", ""),
            "row_count": record.get("row_count", ""),
            "padded_rows": record.get("padded_rows", 0),
            "output_file": record.get("output_file", ""),
        }
        if extended:
            row.update(
                {
                    "hz": record.get("hz", ""),
                    "averaging_minutes": record.get("averaging_minutes", ""),
                    "layout": record.get("layout", ""),
                    "expected_rows": record.get("expected_rows", ""),
                    "measured_hz": record.get("measured_hz", ""),
                    "source_marker": record.get("source_marker", ""),
                }
            )
        records.append(row)

    summary_df = pd.DataFrame(records)
    summary_df.to_csv(sidecar_path, index=False)
    return sidecar_path


def _mismatch_banner(mismatches: list[dict[str, Any]]) -> str:
    """Red banner listing folders whose measured frequency contradicts config.

    Deliberately loud: the run still completes, so this banner (plus the nonzero
    exit code) is the only durable trace once the terminal has scrolled away.
    """
    if not mismatches:
        return ""

    rows = [
        (
            item["folder"],
            item["declared_hz"],
            f"{item['measured_hz']:.2f}",
            f"{item['files']} / {item['total']}",
            item["consequence"],
        )
        for item in mismatches
    ]
    table = render_table(
        rows,
        ["Folder", "Declared Hz", "Measured Hz", "Files affected", "Consequence"],
    )
    return f"""
    <div style="background:#fef2f2;border:1px solid #dc2626;border-radius:8px;padding:16px;margin-bottom:16px;">
      <h2 style="margin:0 0 8px;color:#991b1b;border:none;padding:0;">Acquisition frequency mismatch detected</h2>
      <p>The frequency measured from the data disagrees with the configured value in
      {len(mismatches)} folder(s). The files below were still processed, using the
      <em>declared</em> frequency. Review before publishing this output.</p>
      {table}
    </div>
"""


def write_report(report_context: dict[str, Any]) -> tuple[str, str]:
    station_ID = report_context["station_ID"]
    output_directory = report_context["output_directory"]

    start_dt = report_context["start_datetime"]
    end_dt = report_context["end_datetime"]
    process_dt = report_context["process_datetime"]

    start_token = start_dt.strftime("%Y%m%d%H%M") if start_dt is not None else "NA"
    end_token = end_dt.strftime("%Y%m%d%H%M") if end_dt is not None else "NA"
    process_token = process_dt.strftime("%Y%m%d%H%M%S")

    # Note: 'ghg2rluxcsv' is a long-standing typo kept deliberately -- downstream
    # tooling may match on this filename.
    report_filename = (
        f"{station_ID}_ghg2rluxcsv_report_{start_token}_{end_token}_{process_token}.html"
    )
    report_path = os.path.join(output_directory, report_filename)

    settings_rows = list(report_context["config_settings"].items())
    settings_table = render_table(settings_rows, ["Setting", "Value"])

    disturbance_rows = [
        (start.strftime("%Y-%m-%d %H:%M"), end.strftime("%Y-%m-%d %H:%M"))
        for start, end in report_context["disturbance_windows"]
    ]
    disturbance_table = render_table(disturbance_rows, ["Date start", "Date end"])

    mapping_rows = [
        (in1, in2, out)
        for in1, in2, out in zip(VARS_SUBSET1, VARS_SUBSET2, VARS_RENAME, strict=True)
    ]
    mapping_table = render_table(
        mapping_rows, ["Input name (layout A)", "Input name (layout B)", "Output name"]
    )

    excluded_rows = [
        (
            item.get("timestamp", "NA"),
            item.get("file_name", ""),
            item.get("file_path", ""),
            item.get("reason", ""),
        )
        for item in report_context["excluded_disturbance"]
    ]
    excluded_table = render_table(excluded_rows, ["Timestamp", "File", "Path", "Reason"])

    rejected_rows = [
        (
            item.get("timestamp", "NA"),
            item.get("file_name", ""),
            item.get("file_path", ""),
            item.get("reason", ""),
            item.get("row_count", "NA"),
        )
        for item in report_context["rejected_missing"]
    ]
    rejected_table = render_table(rejected_rows, ["Timestamp", "File", "Path", "Reason", "Rows"])

    failed_rows = [
        (item.get("file_name", ""), item.get("file_path", ""), item.get("reason", ""))
        for item in report_context["failed_files"]
    ]
    failed_table = render_table(failed_rows, ["File", "Path", "Reason"])

    coverage_plot = generate_coverage_plotly(
        report_context["day_list"],
        report_context["converted_by_day"],
        report_context["seen_by_day"],
        report_context["stats"].get("expected_files_per_day", 48),
    )

    start_text = start_dt.strftime("%Y-%m-%d %H:%M") if start_dt is not None else "N/A"
    end_text = end_dt.strftime("%Y-%m-%d %H:%M") if end_dt is not None else "N/A"

    git_metadata = report_context.get("git_metadata", {})
    remote_url = git_metadata.get("remote_url", "N/A")
    commit_url = git_metadata.get("commit_url", "N/A")
    remote_link_html = (
        f'<a href="{html.escape(remote_url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(remote_url)}</a>'
        if remote_url != "N/A"
        else "N/A"
    )
    commit_link_html = (
        f'<a href="{html.escape(commit_url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(commit_url)}</a>'
        if commit_url != "N/A"
        else "N/A"
    )

    metadata_items = [
        ("Input directory", report_context["input_directory"]),
        ("Output directory", output_directory),
        ("Script path", report_context["script_file"]),
        ("Script directory", report_context["script_directory"]),
        ("Script SHA256", report_context["script_hash"]),
        ("Config path", report_context["config_file"]),
        ("Config SHA256", report_context["config_hash"]),
        ("Report hash", report_context["report_hash"]),
        ("Git branch", git_metadata.get("branch", "N/A")),
        ("Git short hash", git_metadata.get("short_hash", "N/A")),
        ("Git full hash", git_metadata.get("full_hash", "N/A")),
        ("Git repository", remote_link_html, True),
        ("Git commit link", commit_link_html, True),
        ("Disturbance file", report_context["disturbance_file"]),
        ("Disturbance windows loaded", report_context["stats"]["disturbance_windows_loaded"]),
    ]
    metadata_table = render_key_value_table(metadata_items)

    run_argument_items = [
        ("Python version", report_context["run_arguments"]["python_version"]),
        ("OS", report_context["run_arguments"]["os"]),
        ("Working directory", report_context["run_arguments"]["working_directory"]),
        ("Command used", report_context["run_arguments"]["command"]),
    ]
    run_arguments_table = render_key_value_table(run_argument_items)

    banner_html = _mismatch_banner(report_context.get("hz_mismatches", []))

    # Only rendered when a run actually uses directory markers or excludes a
    # folder, so an ordinary single-frequency report is unchanged.
    folder_section = ""
    folder_rows = report_context.get("folder_rows", [])
    excluded_folders = report_context.get("excluded_folders", [])
    if folder_rows or excluded_folders:
        folder_table = render_table(
            folder_rows,
            [
                "Folder",
                "Hz",
                "Averaging (min)",
                "Layout",
                "File ID",
                "Files",
                "Source",
                "Note",
            ],
        )
        excluded_folder_table = render_table(
            [(item.path, item.marker_path, item.note) for item in excluded_folders],
            ["Folder", "Marker", "Note"],
        )
        folder_section = f"""
    <h3>Folder settings</h3>
    <div class="panel">{folder_table}</div>

    <h3>Excluded folders</h3>
    <div class="panel">{excluded_folder_table}</div>
"""

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
      <p class="muted">Site: {html.escape(station_ID)} | Processing datetime: {process_dt.strftime("%Y-%m-%d %H:%M:%S")} | Script version: {html.escape(report_context["script_version"])}</p>
      <p class="muted">Data window from {start_text} to {end_text}</p>
    </div>
{banner_html}
    <h2>Run Summary</h2>
    <div class="stats">
      <div class="stat"><div class="label">Discovered .ghg files</div><div class="value">{report_context["stats"]["total_discovered"]}</div></div>
      <div class="stat"><div class="label">Converted files</div><div class="value">{report_context["stats"]["converted_total"]}</div></div>
      <div class="stat"><div class="label">Disturbance excluded</div><div class="value">{report_context["stats"]["excluded_disturbance"]}</div></div>
            <div class="stat"><div class="label">Excluded by prefilter</div><div class="value">{report_context["stats"]["excluded_disturbance_prefilter"]}</div></div>
            <div class="stat"><div class="label">Excluded after parse</div><div class="value">{report_context["stats"]["excluded_disturbance_post_parse"]}</div></div>
      <div class="stat"><div class="label">Rejected (>10% missing)</div><div class="value">{report_context["stats"]["rejected_missing"]}</div></div>
      <div class="stat"><div class="label">Failed parse/read</div><div class="value">{report_context["stats"]["failed_parse"]}</div></div>
      <div class="stat"><div class="label">Expected rows per file</div><div class="value">{report_context["stats"]["expected_rows_per_file"]}</div></div>
    </div>

    <h2>Coverage</h2>
    <div class="panel">
      <p class="muted">Daily converted-file coverage (expected = {report_context["stats"].get("expected_files_per_day", 48)} files/day). NA indicates no timestamped input files found for that day.</p>
            <div class="chart-wrap">{coverage_plot}</div>
    </div>

    <h2>Reproducibility Metadata</h2>
    <div class="panel">{metadata_table}</div>

        <h3>Run arguments</h3>
        <div class="panel">{run_arguments_table}</div>

    <h3>Config settings</h3>
    <div class="panel">{settings_table}</div>
{folder_section}
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

    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    sidecar_path = write_sidecar_csv(report_context, report_filename)
    return report_path, sidecar_path
