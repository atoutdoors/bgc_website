# %%
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from plotly.colors import sample_colorscale
from datetime import date, datetime
import webbrowser
from pathlib import Path
import json
import base64
import requests
import html
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# ---------------------------------------------------------------------------
# Database/API helpers
# Kept in this file so the report can be run as a single script.
# ---------------------------------------------------------------------------
BASE_URL = "https://db.whoifloatgroup.org"
PLATFORMTYPE = "&PLATFORM_TYPE=NAVIS_EBR"
REQUEST_HEADERS = {"Content-Type": "application/json"}
# Keep database/API concurrency deliberately low.  This endpoint can return a
# large profile payload, so a high worker count creates avoidable load on the
# database server during the hourly build.  Operators may lower the value with
# BGC_MAX_API_WORKERS, but the production build is sequential. Keeping this at
# one prevents a burst of API/database requests from the hourly workflow.
MAX_API_WORKERS = 1
# Cache responses that change only when new profiles or floats are added.  The
# cache lives beside the published engineering output and can be disabled for
# troubleshooting with BGC_DISABLE_API_CACHE=1.
METADATA_CACHE_TTL_HOURS = 24
# The production hourly workflow publishes HTML and must not require
# Kaleido/Chrome. Keep PNG export disabled here; HTML Plotly charts remain
# enabled. Static mission-paper figures use their own dependency-free renderer.
WRITE_PNG = False
INTERACTIVE_PLOT_MENU = False  # Click a plot name to view only that figure.
SAVE_PLOTS = True             # Set to True to save HTML files as well.
# Set to True to skip plot output and run the health-report section only.
HEALTH_REPORTS_ONLY = False
GENERATE_FLOAT_TRACK_MAPS = True
GENERATE_BATHYMETRY_MAPPING = True
GENERATE_PER_FLOAT_PLOTS = True
GENERATE_ALL_FLOAT_PLOTS = True
PLOT_REGISTRY = []
PNG_REGISTRY = []
PNG_WIDTH = 1200
PNG_HEIGHT = 700
PNG_SCALE = 1
FILTER_PLOT_OUTLIERS = False
OUTLIER_IQR_FACTOR = 9.0  # Larger values keep more extreme observations.
RH_REFERENCE_TEMPERATURE_C = 20.0

PLOT_COLORS = [
    '#0072B2', '#D55E00', '#009E73', '#CC79A7',
    '#E69F00', '#56B4E9', '#F0E442', '#D62728',
    '#1B9E77', '#7570B3', '#E7298A', '#66A61E',
    '#E6AB02', '#A6761D', '#666666', '#1F77B4',
    '#FF7F0E', '#2CA02C', '#9467BD', '#17BECF',
    '#8C564B', '#BCBD22', '#393B79', '#637939',
] + [
    f'hsl({(color_index * 137.508) % 360:.1f}, '
    f'{88 if color_index % 2 else 78}%, '
    f'{38 if color_index % 3 else 48}%)'
    for color_index in range(96)
]
LEGEND_COLOR_MAP = {}
FLOAT_COLOR_MAP = {}
GEBCO_WMS_URL = 'https://wms.gebco.net/mapserv?'
PLOT_CREATED_AT = datetime.now().astimezone().strftime('%B %d, %Y %I:%M %p').replace(' 0', ' ')

if HEALTH_REPORTS_ONLY:
    # Disable all plot outputs and the interactive plot server for this run.
    INTERACTIVE_PLOT_MENU = False
    SAVE_PLOTS = False
    WRITE_PNG = False
    GENERATE_FLOAT_TRACK_MAPS = False
    GENERATE_BATHYMETRY_MAPPING = False
    GENERATE_PER_FLOAT_PLOTS = False
    GENERATE_ALL_FLOAT_PLOTS = False


def legend_color(label):
    """Return one consistent color for each unique legend label."""
    key = str(label)
    if key not in LEGEND_COLOR_MAP:
        color_index = len(LEGEND_COLOR_MAP)
        if color_index < len(PLOT_COLORS):
            LEGEND_COLOR_MAP[key] = PLOT_COLORS[color_index]
        else:
            hue = (color_index * 137.508) % 360
            LEGEND_COLOR_MAP[key] = f'hsl({hue:.1f}, 85%, 40%)'
    return LEGEND_COLOR_MAP[key]


def _get_dataframe(endpoint, params=None):
    # Keep API requests in one helper so every endpoint uses the same base URL,
    # headers, parameters, timeout, and JSON-to-DataFrame conversion.
    """Call an API endpoint and return its JSON response as a DataFrame."""
    response = requests.get(
        f"{BASE_URL}/api/{endpoint}",
        headers=REQUEST_HEADERS,
        params=params or {},
        timeout=120,
    )
    response.raise_for_status()
    return pd.DataFrame(response.json())


def _api_cache_path(filename):
    """Return a cache path once the engineering output directory is known."""
    if os.environ.get('BGC_DISABLE_API_CACHE') == '1' or 'filedir' not in globals():
        return None
    cache_directory = Path(filedir) / 'api_cache'
    cache_directory.mkdir(parents=True, exist_ok=True)
    return cache_directory / filename


def _read_cached_dataframe(cache_path):
    """Read a JSON DataFrame cache, treating malformed caches as misses."""
    if cache_path is None or not cache_path.exists():
        return pd.DataFrame()
    try:
        return pd.read_json(
            cache_path,
            orient='records',
            dtype={'PROFILE_ID': str},
        )
    except (OSError, ValueError, TypeError):
        progress(f'Ignoring unreadable API cache: {cache_path}')
        return pd.DataFrame()


def _write_cached_dataframe(dataframe, cache_path):
    """Write a JSON DataFrame cache atomically so interrupted builds are safe."""
    if cache_path is None:
        return
    temporary_path = cache_path.with_suffix('.tmp')
    dataframe.to_json(temporary_path, orient='records', date_format='iso')
    temporary_path.replace(cache_path)


def get_gebco_bathymetry_image(dataframe, cache_directory):
    """Download one cached GEBCO WMS image covering all float tracks."""
    coordinates = dataframe[['GpsLong', 'GpsLat']].apply(pd.to_numeric, errors='coerce').dropna()
    if coordinates.empty:
        return None

    lon_min, lon_max = coordinates['GpsLong'].min(), coordinates['GpsLong'].max()
    lat_min, lat_max = coordinates['GpsLat'].min(), coordinates['GpsLat'].max()
    lon_padding = max((lon_max - lon_min) * 0.08, 2.0)
    lat_padding = max((lat_max - lat_min) * 0.08, 2.0)
    bounds = (
        max(-180, lon_min - lon_padding),
        max(-90, lat_min - lat_padding),
        min(180, lon_max + lon_padding),
        min(90, lat_max + lat_padding),
    )
    cache_path = Path(cache_directory) / 'gebco_bathymetry.png'
    if not cache_path.exists():
        response = requests.get(
            GEBCO_WMS_URL,
            params={
                'service': 'WMS',
                'version': '1.1.1',
                'request': 'GetMap',
                'layers': 'GEBCO_Latest',
                'styles': '',
                'format': 'image/png',
                'transparent': 'false',
                'srs': 'EPSG:4326',
                'bbox': ','.join(f'{value:.6f}' for value in bounds),
                'width': 1600,
                'height': 900,
            },
            timeout=120,
        )
        response.raise_for_status()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(response.content)
    return bounds, base64.b64encode(cache_path.read_bytes()).decode('ascii')


def make_gebco_bathymetry_figure(dataframe, serial_numbers, cache_directory):
    """Create one all-float track plot with a cached GEBCO background."""
    bathymetry = get_gebco_bathymetry_image(dataframe, cache_directory)
    if bathymetry is None:
        return None
    bounds, image_data = bathymetry
    lon_min, lat_min, lon_max, lat_max = bounds
    figure = go.Figure()
    figure.add_layout_image(
        source=f'data:image/png;base64,{image_data}',
        xref='x', yref='y',
        x=lon_min, y=lat_max,
        sizex=lon_max - lon_min, sizey=lat_max - lat_min,
        sizing='stretch', layer='below', opacity=0.9,
    )
    for serial_number in serial_numbers:
        track = dataframe.loc[dataframe['FloatId'].astype(str).eq(str(serial_number))].copy()
        track['GpsLong'] = pd.to_numeric(track['GpsLong'], errors='coerce')
        track['GpsLat'] = pd.to_numeric(track['GpsLat'], errors='coerce')
        track = track.dropna(subset=['GpsLong', 'GpsLat']).sort_values('ProfileId')
        if track.empty:
            continue
        figure.add_trace(go.Scatter(
            x=track['GpsLong'], y=track['GpsLat'],
            mode='lines', name=str(serial_number),
        ))
    figure.update_layout(
        title='Float Tracks with GEBCO Bathymetry',
        xaxis_title='Longitude', yaxis_title='Latitude',
        xaxis=dict(range=[lon_min, lon_max]),
        yaxis=dict(range=[lat_min, lat_max], scaleanchor='x', scaleratio=1),
    )
    return figure


def get_cal(platform_number):
    return _get_dataframe("cal", {"PLATFORM_NUMBER": platform_number})


def last_cycle(platform_number):
    response = requests.get(
        f"{BASE_URL}/api/latest_cycle",
        headers=REQUEST_HEADERS,
        params={"PLATFORM_NUMBER": platform_number},
        timeout=120,
    )
    response.raise_for_status()
    return response.json()["last_cycle"]


def get_discrete_profile_stats(platform_number):
    return _get_dataframe("discrete_profile_stats", {"PLATFORM_NUMBER": platform_number})


def get_profile_stats_parallel(profile_ids):
    """Fetch only uncached profile statistics while preserving all results."""
    platform_numbers = [str(profile_id) for profile_id in profile_ids]
    if not platform_numbers:
        return pd.DataFrame()

    cache_path = _api_cache_path('discrete_profile_stats.json')
    cached = _read_cached_dataframe(cache_path)
    # The request key is a platform/WMO number, while returned rows contain
    # profile-level PROFILE_ID values. Keep those keys separate so the latest
    # profile rows are not discarded when reading from the cache.
    if not cached.empty and '_REQUEST_PLATFORM_NUMBER' in cached.columns:
        cached['_REQUEST_PLATFORM_NUMBER'] = cached['_REQUEST_PLATFORM_NUMBER'].astype(str)
        cached = cached.drop_duplicates(
            ['_REQUEST_PLATFORM_NUMBER', 'PROFILE_ID'], keep='last'
        )
    else:
        cached = pd.DataFrame()
    cached_ids = set(cached.get('_REQUEST_PLATFORM_NUMBER', pd.Series(dtype=str)))
    missing_ids = [platform_number for platform_number in platform_numbers if platform_number not in cached_ids]

    if not missing_ids:
        progress(f'Using cached pressure statistics for {len(platform_numbers):,} platforms')
        return cached[cached['_REQUEST_PLATFORM_NUMBER'].isin(platform_numbers)].drop(
            columns=['_REQUEST_PLATFORM_NUMBER']
        ).copy()

    frames = []
    with ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
        futures = {
            executor.submit(get_discrete_profile_stats, platform_number): platform_number
            for platform_number in missing_ids
        }
        for completed_index, future in enumerate(as_completed(futures), start=1):
            frame = future.result()
            if not frame.empty:
                frame['_REQUEST_PLATFORM_NUMBER'] = futures[future]
                frames.append(frame)
            progress_stage(
                f'Fetching pressure statistics ({len(missing_ids):,} uncached)',
                completed_index, len(missing_ids),
                overall_start=25, overall_end=40,
            )
    fetched = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not fetched.empty and '_REQUEST_PLATFORM_NUMBER' in fetched.columns:
        updated_cache = pd.concat([cached, fetched], ignore_index=True)
        updated_cache = updated_cache.drop_duplicates(
            ['_REQUEST_PLATFORM_NUMBER', 'PROFILE_ID'], keep='last'
        )
        _write_cached_dataframe(updated_cache, cache_path)
    combined = pd.concat([cached, fetched], ignore_index=True)
    if '_REQUEST_PLATFORM_NUMBER' in combined.columns:
        combined = combined[combined['_REQUEST_PLATFORM_NUMBER'].isin(platform_numbers)]
        combined = combined.drop(columns=['_REQUEST_PLATFORM_NUMBER'])
    return combined


def filter_plot_outliers(figure):
    """Hide extreme numeric y-values from plots without changing source data."""
    for trace in figure.data:
        if getattr(trace, 'y', None) is None:
            continue
        values = list(trace.y)
        if len(values) < 10:
            continue
        numeric = pd.to_numeric(pd.Series(values), errors='coerce')
        valid = numeric.dropna()
        if len(valid) < 10 or valid.nunique() < 3:
            continue
        q1, q3 = valid.quantile([0.25, 0.75])
        iqr = q3 - q1
        if not iqr or pd.isna(iqr):
            continue
        lower = q1 - OUTLIER_IQR_FACTOR * iqr
        upper = q3 + OUTLIER_IQR_FACTOR * iqr
        trace.y = [value if pd.notna(number) and lower <= number <= upper else None
                   for value, number in zip(values, numeric)]
    return figure


def multi_trace_gradient_color(index, total):
    """Return a high-variance sequential Turbo color for a trace."""
    position = index / max(total - 1, 1)
    return sample_colorscale('Turbo', [position])[0]


def temperature_corrected_relative_humidity(humidity, temperature_c,
                                            reference_temperature_c=RH_REFERENCE_TEMPERATURE_C):
    """Convert RH to a common reference temperature using saturation vapor pressure.

    The correction assumes the measured water-vapor partial pressure is unchanged
    while temperature varies. Invalid or non-positive readings remain NaN.
    """
    rh = pd.to_numeric(humidity, errors='coerce')
    temperature = pd.to_numeric(temperature_c, errors='coerce')

    def saturation_vapor_pressure(temp_c):
        return 6.112 * (2.718281828459045 ** ((17.67 * temp_c) / (temp_c + 243.5)))

    corrected = rh * saturation_vapor_pressure(reference_temperature_c) / saturation_vapor_pressure(temperature)
    return corrected.where(rh.notna() & temperature.notna() & (rh >= 0) & (temperature > -243.5))


def style_figure(figure):
    """Apply consistent publication-style formatting to every Plotly figure."""
    figure.update_layout(
        template='plotly_white',
        colorway=PLOT_COLORS,
        paper_bgcolor='white',
        plot_bgcolor='#F8FAFC',
        font=dict(family='Arial, sans-serif', size=12, color='#263746'),
        margin=dict(l=64, r=28, t=84, b=58),
        legend=dict(
            bgcolor='rgba(255,255,255,0.86)',
            bordercolor='#D7DEE4',
            borderwidth=1,
        ),
        hovermode='closest',
        hoverlabel=dict(
            bgcolor='#FFFFFF',
            bordercolor='#174A70',
            font=dict(family='Arial, sans-serif', size=13, color='#17202A'),
            align='left',
        ),
    )
    figure.update_xaxes(
        showgrid=True, gridcolor='#E5E7EB', gridwidth=1,
        zeroline=False, title_standoff=12,
    )
    figure.update_yaxes(
        showgrid=True, gridcolor='#E5E7EB', gridwidth=1,
        zeroline=False, title_standoff=12,
    )
    if figure.layout.title.text and 'Created:' not in str(figure.layout.title.text):
        figure.update_layout(
            title=dict(
                text=f'{figure.layout.title.text}<br><sup>Created: {PLOT_CREATED_AT}</sup>',
                x=0.02,
                xanchor='left',
                font=dict(size=18, color='#174A70'),
            )
        )
    used_colors = set()
    named_trace_count = sum(1 for trace in figure.data if getattr(trace, 'name', None))
    named_trace_index = 0
    for trace_index, trace in enumerate(figure.data):
        if getattr(trace, 'name', None):
            # Multi-trace figures use the same ordered sequential Turbo
            # colormap as bgcwebsite_test.py.
            if named_trace_count > 1:
                color = multi_trace_gradient_color(named_trace_index, named_trace_count)
                named_trace_index += 1
            else:
                color = FLOAT_COLOR_MAP.get(str(trace.name), legend_color(trace.name))
            if color in used_colors:
                unused_palette = [candidate for candidate in PLOT_COLORS if candidate not in used_colors]
                if unused_palette:
                    color = unused_palette[0]
                else:
                    alternate_index = len(LEGEND_COLOR_MAP) + trace_index
                    while True:
                        hue = (alternate_index * 137.508) % 360
                        alternate_color = f'hsl({hue:.1f}, 85%, 40%)'
                        if alternate_color not in used_colors:
                            color = alternate_color
                            break
                        alternate_index += 1
            used_colors.add(color)
            if getattr(trace, 'line', None) is not None:
                trace.line.color = color
            if getattr(trace, 'marker', None) is not None:
                trace.marker.color = color
            if hasattr(trace, 'fillcolor'):
                trace.fillcolor = color
            if str(trace.name) in FLOAT_COLOR_MAP:
                trace.hovertemplate = (
                    f'Float Serial Number: {trace.name}<br>'
                    '%{x}: %{y}<extra></extra>'
                )
        if hasattr(trace, 'line') and trace.line is not None:
            trace.line.width = 1.2
            trace.opacity = 0.82
        if getattr(trace, 'mode', None) and 'markers' in trace.mode:
            trace.marker.size = 4
            trace.marker.opacity = 0.72
    return figure


def plot_category_enabled(html_path):
    """Return whether the output category is enabled in the run settings."""
    normalized_path = str(html_path).replace('\\', '/').lower()
    if 'bathymetry' in normalized_path:
        return GENERATE_BATHYMETRY_MAPPING
    if normalized_path.endswith('/map.html'):
        return GENERATE_FLOAT_TRACK_MAPS
    if '/by_parameter/' in normalized_path:
        return GENERATE_ALL_FLOAT_PLOTS
    return GENERATE_PER_FLOAT_PLOTS


def save_figure(figure, html_path, png_path=None):
    # Every plot passes through this function. It applies common styling and
    # decides whether the plot is registered, saved as HTML, or queued as PNG.
    """Style a figure and register it for interactive viewing or saving."""
    if HEALTH_REPORTS_ONLY:
        return
    if not plot_category_enabled(html_path):
        return
    if FILTER_PLOT_OUTLIERS:
        filter_plot_outliers(figure)
    style_figure(figure)
    # Pressure is a depth-like quantity in these plots: larger values belong
    # lower on the chart. Apply this centrally so newly added pressure plots
    # keep the same orientation as the explicit pressure plots below.
    yaxis_title = getattr(getattr(figure.layout, 'yaxis', None), 'title', None)
    yaxis_title_text = getattr(yaxis_title, 'text', '') or ''
    figure_title = getattr(getattr(figure.layout, 'title', None), 'text', '') or ''
    pressure_markers = ('pressure', 'pres_max', 'surfacepressure', 'parkpressure')
    pressure_text = ' '.join((str(yaxis_title_text), str(figure_title), str(html_path))).lower()
    if any(marker in pressure_text for marker in pressure_markers):
        figure.update_yaxes(autorange='reversed')
    if INTERACTIVE_PLOT_MENU:
        label = Path(html_path).stem.replace('_', ' ')
        PLOT_REGISTRY.append((label, figure))
    if SAVE_PLOTS:
        # Loading Plotly from a CDN keeps saved HTML files small.
        figure.write_html(html_path, include_plotlyjs='cdn')
        if WRITE_PNG and png_path is not None:
            PNG_REGISTRY.append((figure, png_path))


def _trace_serial(trace_name, serial_numbers):
    """Find the float serial represented by an across-float trace name."""
    label = str(trace_name)
    for serial_number in sorted((str(value) for value in serial_numbers), key=len, reverse=True):
        if label == serial_number or label.startswith(serial_number):
            return serial_number
    return None


def save_across_float_figure(figure, plot_name, standard_html, standard_png=None):
    """Save an across-float plot and a filtered copy for each deployment cohort."""
    save_figure(figure, standard_html, standard_png)
    if HEALTH_REPORTS_ONLY or not GENERATE_ALL_FLOAT_PLOTS or not DEPLOYMENT_COHORTS:
        return

    for deployment_year, serial_numbers in DEPLOYMENT_COHORTS.items():
        cohort_figure = go.Figure(figure)
        cohort_figure.data = tuple(
            trace for trace in cohort_figure.data
            if _trace_serial(getattr(trace, 'name', ''), serial_numbers) in serial_numbers
        )
        if not cohort_figure.data:
            continue
        cohort_directory = Path(filedir) / 'cohort_plots' / str(deployment_year)
        cohort_directory.mkdir(parents=True, exist_ok=True)
        save_figure(
            cohort_figure,
            cohort_directory / f'{plot_name}.html',
            cohort_directory / f'{plot_name}.png',
        )


def write_cohort_index():
    """Write year links and one embedded all-plots page for each cohort."""
    if HEALTH_REPORTS_ONLY or not GENERATE_ALL_FLOAT_PLOTS or not DEPLOYMENT_COHORTS:
        return
    cohort_directory = Path(filedir) / 'cohort_plots'
    cohort_directory.mkdir(parents=True, exist_ok=True)
    sections = []
    for deployment_year, serial_numbers in DEPLOYMENT_COHORTS.items():
        year_directory = cohort_directory / str(deployment_year)
        year_directory.mkdir(parents=True, exist_ok=True)
        plot_paths = sorted(
            plot_path for plot_path in year_directory.glob('*.html')
            if plot_path.name != 'index.html'
        ) if year_directory.exists() else []
        year_navigation = ' '.join(
            f'<a class="nav-link d-inline-block" href="../{html.escape(str(year))}/index.html">{html.escape(str(year))}</a>'
            for year in DEPLOYMENT_COHORTS
        )
        embedded_plots = ''.join(
            f'<details class="card shadow-sm border-0 mb-3" id="plot-{index}"><summary class="card-header text-primary fw-semibold">{html.escape(plot_path.stem.replace("_", " "))}</summary>'
            f'<div class="plot-frame p-2 p-md-3"><iframe src="{html.escape(plot_path.name)}" title="{html.escape(plot_path.stem)}" '
            f'loading="lazy"></iframe></div><p class="back-top px-3 pb-2 mb-0"><a href="#top">Back to top</a></p></details>'
            for index, plot_path in enumerate(plot_paths)
        ) or '<p>No plots available for this cohort.</p>'
        year_page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<title>{html.escape(str(deployment_year))} Cohort Plots</title><style>
:root{{--navy:#243b53;--slate:#486581;--muted:#627d98;--line:#d9e2ec;--page:#f5f7fa}}
body{{background:var(--page)!important;color:#334e68}}
.year-nav{{position:sticky;top:0;z-index:10;background:var(--navy)!important;box-shadow:0 2px 8px #102a4333;border-bottom:1px solid #526b84}}
.navbar-brand{{font-weight:600;letter-spacing:.01em}} .navbar-nav{{gap:.2rem}}
.navbar-dark .navbar-nav .nav-link{{color:#d9e2ec!important;border-radius:.35rem;padding:.45rem .7rem}}
.navbar-dark .navbar-nav .nav-link:hover{{color:#fff!important;background:#ffffff18}}
details{{scroll-margin-top:70px}}
summary{{cursor:pointer;list-style:none}} summary::-webkit-details-marker{{display:none}} summary::before{{content:'+';display:inline-block;width:1.4rem;font-size:1.2rem}} details[open] summary::before{{content:'-'}}
.plot-frame{{background:#f1f5f9}} iframe{{display:block;width:100%;height:min(72vh,720px);min-height:480px;border:1px solid #dbe3e9;border-radius:.5rem;background:#fff}}
.back-top{{font-size:.875rem}} a{{color:var(--slate)}} a:hover{{color:var(--navy)}} .text-primary{{color:var(--slate)!important}} .text-bg-primary{{background-color:var(--slate)!important}} .page-kicker{{letter-spacing:.12em;font-size:.72rem;font-weight:700;color:var(--muted)}}
</style></head><body class="bg-light" id="top"><nav class="navbar navbar-expand-lg navbar-dark bg-primary year-nav"><div class="container-xxl gap-3"><a class="navbar-brand" href="../index.html">Cohort Plots</a><div class="navbar-nav flex-row flex-nowrap overflow-auto"><a class="nav-link d-inline-block" href="../../index.html">&larr; Engineering website</a>{year_navigation}</div></div></nav><main class="container-xxl py-4">
<div class="card shadow-sm border-0 mb-4"><div class="card-body p-4 p-lg-5">
<div class="d-flex flex-wrap justify-content-between align-items-start gap-3"><div><div class="page-kicker text-uppercase mb-2">WHOI BGC Engineering</div><h1 class="h2 text-primary mb-2">{html.escape(str(deployment_year))} Cohort Plots</h1><p class="text-secondary mb-0">Floats: {html.escape(", ".join(map(str, serial_numbers)))}</p></div><span class="badge text-bg-primary rounded-pill fs-6">{len(plot_paths)} plots</span></div>
</div></div>
{embedded_plots}</main><footer class="container-xxl pb-4 text-secondary small">WHOI BGC Engineering &middot; Cohort plot report</footer></body></html>'''
        (year_directory / 'index.html').write_text(year_page, encoding='utf-8')
        sections.append(
            f'<a class="list-group-item list-group-item-action d-flex justify-content-between align-items-center" '
            f'href="{html.escape(str(deployment_year))}/index.html">'
            f'<span>{html.escape(str(deployment_year))} Cohort</span>'
            f'<span class="badge text-bg-primary rounded-pill">{len(serial_numbers)} floats</span></a>'
        )
    page = f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<title>Cohort Plots</title><style>
:root{{--navy:#243b53;--slate:#486581;--muted:#627d98;--line:#d9e2ec;--page:#f5f7fa}}
body{{background:var(--page)!important;color:#334e68}} a{{color:var(--slate)}} a:hover{{color:var(--navy)}}
.text-primary{{color:var(--slate)!important}} .list-group-item{{border-color:var(--line)}}
.list-group-item-action{{color:var(--slate)}} .list-group-item-action:hover{{color:var(--navy);background:#eef2f6}} .text-bg-primary{{background-color:var(--slate)!important}} .page-kicker{{letter-spacing:.12em;font-size:.72rem;font-weight:700;color:var(--muted)}}
</style></head><body class="bg-light"><main class="container py-4">
<p><a href="../index.html" class="link-primary">&larr; Engineering website</a></p>
<div class="card shadow-sm border-0"><div class="card-body p-4 p-lg-5"><div class="page-kicker text-uppercase mb-2">WHOI BGC Engineering</div><h1 class="h2 text-primary">Cohort Plots</h1>
<p class="text-secondary">Across-float engineering plots grouped by deployment year.</p>
<div class="list-group">{"".join(sections)}</div></div></div><footer class="pt-4 text-secondary small">WHOI BGC Engineering &middot; Cohort plot index</footer></main></body></html>'''
    (cohort_directory / 'index.html').write_text(page, encoding='utf-8')


def write_registered_pngs():
    """Write all queued PNGs in one renderer batch for better performance."""
    if not WRITE_PNG or not PNG_REGISTRY:
        return
    for _, png_path in PNG_REGISTRY:
        Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    figures, paths = zip(*PNG_REGISTRY)
    try:
        pio.write_images(
            fig=list(figures),
            file=list(paths),
            format='png',
            width=PNG_WIDTH,
            height=PNG_HEIGHT,
            scale=PNG_SCALE,
        )
    except AttributeError:
        for png_index, (figure, png_path) in enumerate(PNG_REGISTRY, start=1):
            progress_stage('PNG rendering', png_index, len(PNG_REGISTRY), overall_start=92, overall_end=99)
            figure.write_image(
                png_path,
                format='png',
                width=PNG_WIDTH,
                height=PNG_HEIGHT,
                scale=PNG_SCALE,
            )


def serve_plot_menu(host='127.0.0.1', port=8765):
    """Open a local clickable menu that renders figures only when selected."""
    class PlotMenuHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            request = urlparse(self.path)
            query = parse_qs(request.query)
            if request.path == '/':
                links = ''.join(
                    f'<li><a href="/plot?id={i}">{html.escape(label)}</a></li>'
                    for i, (label, _) in enumerate(PLOT_REGISTRY)
                )
                body = f'''<!doctype html><html><head><meta charset="utf-8">
                <title>Engineering plots</title><style>
                body{{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;line-height:1.7}}
                a{{color:#174a70;text-decoration:none}}a:hover{{text-decoration:underline}}
                </style></head><body><h1>Engineering plots</h1>
                <p>Choose a plot to view it.</p><ul>{links}</ul></body></html>'''
                self._send(body)
                return
            if request.path == '/plot':
                try:
                    index = int(query.get('id', [''])[0])
                    figure = PLOT_REGISTRY[index][1]
                except (ValueError, IndexError):
                    self.send_error(404, 'Plot not found')
                    return
                self._send(figure.to_html(full_html=True, include_plotlyjs='cdn'))
                return
            self.send_error(404)

        def _send(self, body):
            payload = body.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            return

    server = HTTPServer((host, port), PlotMenuHandler)
    url = f'http://{host}:{port}/'
    progress(f'Interactive plot menu available at {url} (Ctrl+C to stop)')
    webbrowser.open(url)
    server.serve_forever()


def get_continuous_profile_stats(platform_number):
    return _get_dataframe("continuous_profile_stats", {"PLATFORM_NUMBER": platform_number})


def get_discrete_one_float(platform_number, output_fields):
    return _get_dataframe(
        "discrete_data_get",
        {"DEPLOYMENT__PLATFORM_NUMBER": platform_number, "output_fields": output_fields},
    )


def get_discrete_one_profile(profile_id, output_fields):
    return _get_dataframe(
        "discrete_data_get",
        {"PROFILE_ID": profile_id, "output_fields": output_fields},
    )


def get_continuous_one_float(platform_number, output_fields):
    return _get_dataframe(
        "continuous_data_get",
        {"DEPLOYMENT__PLATFORM_NUMBER": platform_number, "output_fields": output_fields},
    )


def get_continuous_one_profile(profile_id, output_fields):
    return _get_dataframe(
        "continuous_data_get",
        {"PROFILE_ID": profile_id, "output_fields": output_fields},
    )


def get_engineering_all(output_fields):
    return _get_dataframe("cycle_meta_get", {"output_fields": output_fields})


def get_park_all(output_fields):
    return _get_dataframe("park_data_get", {"output_fields": output_fields})


def get_surface_all(output_fields):
    return _get_dataframe("surface_observations_get", {"output_fields": output_fields})


def get_metadata_all(output_fields):
    cache_path = _api_cache_path('deployment_metadata.json')
    if cache_path is not None and cache_path.exists():
        cache_age_hours = (datetime.now().timestamp() - cache_path.stat().st_mtime) / 3600
        if cache_age_hours < METADATA_CACHE_TTL_HOURS:
            progress(f'Using cached deployment metadata ({cache_age_hours:.1f} hours old)')
            return _read_cached_dataframe(cache_path)
    metadata = _get_dataframe(
        "deployment_metadata",
        {"deployment_fields": output_fields, "PLATFORM_TYPE": "NAVIS_EBR"},
    )
    _write_cached_dataframe(metadata, cache_path)
    return metadata


def get_cal_sn(float_number):
    return _get_dataframe(
        "cal",
        {"FLOAT_SERIAL_NO": float_number, "PLATFORM_TYPE": "NAVIS_EBR"},
    )


def make_clickable(value):
    return f'<a target="_blank" href="{value}">{value}</a>'


def make_named_link(label, href):
    return (
        f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
        f'onclick="event.preventDefault(); window.open(this.href, \'_blank\', '
        f'\'noopener,noreferrer\');">{label}</a>'
    )


def generate_html(dataframe):
    table_html = dataframe.to_html(render_links=True, escape=False, index=False, table_id="table")
    return f"""
    <html>
    <head>
        <link href="https://cdn.datatables.net/1.11.5/css/jquery.dataTables.min.css" rel="stylesheet">
    </head>
    <body style="margin:0; padding:24px; text-align:center; font-family:Arial, sans-serif; background:#f6f8fa;">
    <div style="max-width:1100px; margin:0 auto;">{table_html}</div>
    <script src="https://code.jquery.com/jquery-3.6.0.slim.min.js"></script>
    <script src="https://cdn.datatables.net/1.11.5/js/jquery.dataTables.min.js"></script>
    <script>
        $(document).ready(function () {{ $('#table').DataTable(); }});
    </script>
    </body>
    </html>
    """


def serial_number_order(values):
    """Return serial numbers in numeric order, with a text fallback."""
    def sort_key(value):
        text_value = str(value)
        try:
            return (0, int(text_value))
        except ValueError:
            return (1, text_value)

    return sorted(pd.unique(values), key=sort_key)


def progress(message):
    """Print a timestamped progress message immediately."""
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def progress_stage(label, current, total, overall_start=0, overall_end=100):
    """Print an updating overall/stage percentage for long-running work."""
    stage_percent = 100 if total <= 0 else int(current / total * 100)
    fraction = min(max(current / max(total, 1), 0), 1)
    overall_percent = overall_start + int((overall_end - overall_start) * fraction)
    bar_width = 24
    filled = int(bar_width * overall_percent / 100)
    bar = '#' * filled + '-' * (bar_width - filled)
    print(
        f"[{datetime.now():%H:%M:%S}] [{bar}] {overall_percent:3d}% "
        f"{label}: {current}/{total} ({stage_percent}%)",
        flush=True,
    )



name = 'Aidan' # Legacy label retained for report metadata.

filedir = Path(
    os.environ.get(
        'BGC_ENGINEERING_ROOT',
        'Z:/www/bgc/engineering/' if os.name == 'nt' else '/data1/www/bgc/engineering/',
    )
)
# Normalize once because the plotting code builds several legacy paths by
# concatenating strings (for example: filedir + str(serial_number)).
filedir = str(filedir).rstrip('/\\') + '/'

progress_stage('Starting engineering report', 0, 1, overall_start=0, overall_end=2)


filename = f'{date.today()}_engineering'

progress_stage('Downloading engineering data', 0, 1, overall_start=2, overall_end=12)
# Pull one engineering-data table for all floats. The selected fields below
# are the source data for the plots, index table, and health reports.
data = get_engineering_all("PROFILE_ID,GPS_DURATION,TRANS_DURATION,SurfacePressure,Sbe63Volts,Vacuum,ParkBuoyancyPosition,GpsFixTime,FloatId,BuoyancyPumpOnTime,ActiveBallastAdjustments,\
ProfileId,GpsNsat,IsusPowerCycleCounter,GpsLong,GpsLat,PHBaseAmps,PHBatteryInVolts,PHBatteryOutVolts,AirBladderPressure,AirPumpAmps,AirPumpVolts,BuoyancyPumpAmps,BuoyancyPumpVolts,\
QuiescentAmps,QuiescentVolts,Sbe41cpAmps,Sbe41cpVolts,Sbe63Volts,McomsAmps,McomsVolts,Sbe63Amps,SurfaceBuoyancyPosition,DeepProfileBuoyancyPosition,ISUS_BYTES,MSG_BYTES,LOG_BYTES,\
UPLOAD_ATTEMPTS,UPLOADS,CONNECTIONS,CONNECTION_ATTEMPTS,TimeStartTelemetry,Sbe41cpHumidity,Sbe41cpHumidityTemp,BatteryCounts,ObsIndex,ParkDescentPCnt,ParkObs")
data = pd.DataFrame(data)
engineering_data = data.copy()

export_root = os.environ.get('BGC_ENGINEERING_EXPORT_DIR')
if export_root:
    export_path = Path(export_root) / f'{filename}.xlsx'
elif os.name == 'nt':
    export_path = Path('G:/Shared drives/WHOI Argo/BGC/Float Tracking/engineering_data') / f'{filename}.xlsx'
else:
    export_path = Path(
        os.environ.get('BGC_ENGINEERING_ROOT', '/data1/www/bgc/engineering')
    ) / 'engineering_data' / f'{filename}.xlsx'
export_path.parent.mkdir(parents=True, exist_ok=True)
data.to_excel(export_path, index=False)
progress_stage(f'Loaded {len(data):,} engineering records for {data["FloatId"].nunique()} floats', 1, 1, overall_start=2, overall_end=12)

# Sort serial numbers numerically and build one DataFrame per float. Keeping
# this order makes plot legends and report links consistent.
SNs = serial_number_order(data['FloatId'].dropna())
for float_index, serial_number in enumerate(SNs):
    if float_index < len(PLOT_COLORS):
        FLOAT_COLOR_MAP[str(serial_number)] = PLOT_COLORS[float_index]
    else:
        hue = (float_index * 137.508) % 360
        FLOAT_COLOR_MAP[str(serial_number)] = f'hsl({hue:.1f}, 65%, 45%)'

# Group floats by the year of their first engineering telemetry record.  This
# keeps cohort membership tied to the same source data used by the plots.
deployment_year_by_float = (
    data.assign(TimeStartTelemetry=pd.to_datetime(data['TimeStartTelemetry'], errors='coerce', utc=True))
    .dropna(subset=['FloatId', 'TimeStartTelemetry'])
    # The database uses epoch-era timestamps (1969/1970) as missing-value
    # sentinels for some records; they are not real deployment dates.
    .loc[lambda frame: frame['TimeStartTelemetry'].dt.year >= 2000]
    .groupby('FloatId')['TimeStartTelemetry']
    .min()
    .dt.year
)
DEPLOYMENT_COHORTS = {}
for serial_number in SNs:
    deployment_year = deployment_year_by_float.get(serial_number)
    deployment_year = int(deployment_year) if pd.notna(deployment_year) else 'Unknown'
    DEPLOYMENT_COHORTS.setdefault(deployment_year, []).append(str(serial_number))
DEPLOYMENT_COHORTS = dict(sorted(DEPLOYMENT_COHORTS.items(), key=lambda item: str(item[0])))
groups = data.groupby('FloatId', sort=False)
indfloat = [groups.get_group(sn).sort_values('ProfileId').reset_index(drop=True) for sn in SNs]

# Create the output folders before writing any float-specific files.

for i in SNs:
    Path(filedir, str(i)).mkdir(parents=True, exist_ok=True)
Path(filedir, 'by_parameter').mkdir(parents=True, exist_ok=True)

#filename = str(date.today())+'_engineering' #update to day you run it
#data = pd.read_excel('G://Shared drives/WHOI Argo/BGC/Float Tracking/engineering_data' '/' +  filename + ".xlsx")
# Split it by each float you can call each float by indfloat[0:NumFloats]

groups = data.groupby('FloatId', sort=False)
indfloat = [groups.get_group(sn).sort_values('ProfileId').reset_index(drop=True) for sn in SNs]
dat = pd.concat(indfloat)

dat['WMO_ID'] = dat['PROFILE_ID'].astype(str).str.extract(r'(\d+)', expand=False)
wmo = dat['WMO_ID'].unique()

lastparkpress=[]
for i,d in enumerate(SNs):
    lastparkpress.append(indfloat[i]['ParkObs'].iloc[-1])

parkpressure = [pd.to_numeric(pd.Series([value]).astype(str).str.extract(r'(\d+(?:\.\d+)?)')[0].iloc[0])
                for value in lastparkpress]

# Calculate values used by the engineering index, including report age,
# float age, and the interval between recent cycles.
progress_stage('Calculating report dates, float ages, and cycle lengths', 0, 1, overall_start=12, overall_end=25)
lastreport = []
deploydate=[]
for i,k in enumerate(SNs):
    lastreport.append(indfloat[i]['TimeStartTelemetry'].iloc[-1])
    deploydate.append(indfloat[i]['TimeStartTelemetry'].iloc[0])

 # Force every timestamp to UTC so naive and timezone-aware API values can
 # safely be compared and subtracted.
firstt = pd.to_datetime(deploydate, utc=True)
lastt = pd.to_datetime(lastreport, utc=True)
firstreport = firstt.strftime('%Y-%m-%d').tolist()
lastreport = lastt.strftime('%Y-%m-%d').tolist()

#time since last report
lastt
today = pd.Timestamp.now(tz='UTC')
tsl=[]
for i,d in enumerate(SNs):
    tsl.append(pd.Timedelta(today-lastt[i]))

timesince = [delta.days for delta in tsl]

#AGE 
age = []
for i, d in enumerate(SNs):
    age.append(pd.Timedelta(lastt[i]-firstt[i]))
age = [delta.days for delta in age]

# Time Between Most Recent Cycles
lt=[]
cyclelengthsecond=[]
cyclelengthlast=[]
for i,k in enumerate(SNs):
    cyclelengthsecond.append(indfloat[i]['TimeStartTelemetry'].iloc[-1])
    try:
        cyclelengthlast.append(indfloat[i]['TimeStartTelemetry'].iloc[-2])
    except:
        cyclelengthlast.append(indfloat[i]['TimeStartTelemetry'].iloc[-1])
lastreport2 = cyclelengthsecond
seclastreport = cyclelengthlast

lastreport2 = pd.to_datetime(lastreport2, utc=True)
seclastreport = pd.to_datetime(seclastreport, utc=True)

cyclelength = []
for i, d in enumerate(SNs):
    cyclelength.append(pd.Timedelta(lastreport2[i]-seclastreport[i]))

# 
cyclenum = []
for i, d in enumerate(SNs):
    cyclenum.append(indfloat[i]['ProfileId'].iloc[-1])

progress_stage('Calculating report dates, float ages, and cycle lengths', 1, 1, overall_start=12, overall_end=25)


# GET THE MAX PRESSURE FOR EVERY PROFILE AND ADD TO THIS DATAFRAME
progress_stage('Downloading maximum pressure statistics', 0, 1, overall_start=25, overall_end=40)

mo = pd.unique(
    dat['PROFILE_ID'].astype(str).str.extract(r'(\d{7})', expand=False).dropna()
)
maxp = []
maxp = get_profile_stats_parallel(mo)
profile_stats = maxp.copy()

maxp['PROFILE_ID']=maxp['PROFILE_ID'].astype('object')
maxp['PRES_MAX'] = maxp['PRES_MAX'].astype('object')
dat['PROFILE_ID'] = dat['PROFILE_ID'].astype(str)
maxp['PROFILE_ID'] = maxp['PROFILE_ID'].astype(str)
#print(dat['PROFILE_ID'])
#print(maxp['PROFILE_ID'])

d2 = pd.merge(dat,maxp, on = "PROFILE_ID", how = 'left')
#d2 = pd.concat(dat,maxp)

d2['FloatId'] = d2['FloatId'].astype(str)
s = d2.groupby("FloatId")

d3 = []
for i, j in enumerate(SNs):
    try:
        d3.append(s.get_group(str(SNs[i])))
    except:
        pass
for i, j in enumerate(d3):
    d3[i] = d3[i].reset_index()

deepp= []
for i, j in enumerate(d3):
    # Negative PRES_MAX values are database/surface sentinels, not valid deep
    # profile pressures. Select the latest valid positive pressure instead.
    available_pressures = pd.to_numeric(d3[i]['PRES_MAX'], errors='coerce')
    available_pressures = available_pressures[available_pressures > 0].dropna()
    deepp.append(available_pressures.iloc[-1] if not available_pressures.empty else None)

tab = pd.DataFrame()
tab['Serial Number'] = SNs
tab['WMO ID'] = [
    make_named_link(wmo_id, f'../../wmo/{wmo_id}/index.html') for wmo_id in wmo
]
tab['Last Park Pressure (dbars)'] = parkpressure
tab['Last Deep Profile Pressure (dbars)'] = deepp
tab['First Report'] = firstreport
tab['Latest Report'] =lastreport
tab['Age in Days at Latest Report'] = age
tab['Latest Cycle Length']= cyclelength
tab['Cycle Number'] = cyclenum
tab['Days Since Last Report'] = timesince
tab['mission'] = [make_named_link('Mission JSON', f'{sn}/mission.json') for sn in SNs]
tab = tab.sort_values(by = 'Serial Number')
tab['Serial Number'] = [make_named_link(sn, f'{sn}/index.html') for sn in tab['Serial Number']]

htmltab = generate_html(tab)

with open(Path(filedir, 'engineeringtable.html'), 'w', encoding='utf-8') as html_file:
    html_file.write(htmltab)
progress_stage('Writing engineering table', 1, 1, overall_start=40, overall_end=43)
#filename = str(date.today())+'_engineering'#update to day you run it
#data = pd.read_excel('G://Shared drives/WHOI Argo/BGC/Float Tracking/engineering_data' '/' +  filename + ".xlsx")
# Split it by each float you can call each float by indfloat[0:NumFloats]
data['BuoyancyPumpEnergy']=data['BuoyancyPumpOnTime']*data['BuoyancyPumpVolts']*data['BuoyancyPumpAmps']
# Normalize the RH readings to a common temperature so floats can be compared
# without conflating sensor temperature changes with moisture changes.
data['TemperatureCorrectedRH'] = temperature_corrected_relative_humidity(
    data['Sbe41cpHumidity'], data['Sbe41cpHumidityTemp']
)
groups = data.groupby('FloatId', sort=False)
indfloat = [groups.get_group(sn).sort_values('ProfileId').reset_index(drop=True) for sn in SNs]
dat = data.sort_values('ProfileId').copy()

# These variables are grouped into plot families so related engineering
# measurements can be reviewed together for each float.
group1 = ['MSG_BYTES', 'LOG_BYTES', 'ISUS_BYTES']
group2= ['UPLOAD_ATTEMPTS', 'UPLOADS']
group3= ['CONNECTION_ATTEMPTS', 'CONNECTIONS']
group4= ['DeepProfileBuoyancyPosition', 'ParkBuoyancyPosition', 'SurfaceBuoyancyPosition']
group5 = ['Vacuum', 'Sbe41cpHumidity', 'Sbe41cpHumidityTemp']

vars = ['ObsIndex','ParkDescentPCnt']
units = ['Number of Discrete Samples Made During Acent', 'Number of Pressure Measurements made During Descent']
data['Park Pressure (dbars)'] = pd.to_numeric(
    data['ParkObs'].astype(str).str.extract(r'(\d+(?:\.\d+)?)', expand=False),
    errors='coerce'
)
groups = data.groupby('FloatId', sort=False)
indfloat = [groups.get_group(sn).sort_values('ProfileId').reset_index(drop=True) for sn in SNs]
for frame in indfloat:
    frame['Park Pressure (dbars)'] = pd.to_numeric(frame['ParkObs'].astype(str).str.extract(r'(\d+(?:\.\d+)?)', expand=False), errors='coerce')
progress_stage('Generating per-float sample and pump-energy plots', 0, 1, overall_start=43, overall_end=52)
# Per-float plots show measurements for one float across its profile history.
#park descent pressure and number of pressure measurements
for j,k in enumerate(vars):
    for i,d in enumerate(SNs):
        progress(f'Plotting {vars[j]} for float {SNs[i]}')
        dats = indfloat[i]
        dats = dats.sort_values(by='ProfileId')
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x = dats['ProfileId'],
            y = dats[vars[j]]
        ))
        fig.update_layout(
            title = vars[j],
            xaxis_title = 'Profile Number',
            yaxis_title = units[j]
        )
        save_figure(fig, filedir+str(SNs[i])+'/'+vars[j]+".html", filedir+str(SNs[i])+'/'+vars[j]+".png")
        progress_stage(f'Per-float plots: {vars[j]}', i + 1, len(SNs), overall_start=43, overall_end=52)
#Energy Of Buoyancy Pump
for i,d in enumerate(SNs):
    progress(f'Plotting buoyancy-pump energy for float {SNs[i]}')
    dats = indfloat[i]
    dats=dats.sort_values(by = ['ProfileId'])
    fig= go.Figure()
    fig.add_trace(go.Scatter(
        x = dats['ProfileId'],
        y = dats['BuoyancyPumpEnergy']
    ))
    fig.update_layout(
        title = 'Buoyancy Pump Energy',
        xaxis_title = 'Profile Number',
        yaxis_title = 'Joules'
    )
    save_figure(fig, filedir+str(SNs[i])+'/BuoyancyPumpEnergy.html', filedir+str(SNs[i])+'/BuoyancyPumpEnergy.png')

#GROUP 1
progress('Generating transmission plots')
for i ,d in enumerate(SNs):
    dats = indfloat[i]
    dats = dats.sort_values(by = ['ProfileId'])
    fig = go.Figure()
    for j, d in enumerate(group1):
        fig.add_trace(go.Scatter(
            x = dats['ProfileId'],
            y = dats[group1[j]],
            name = group1[j]
        ))
    fig.update_layout(
        title = 'Transmitted Bytes',
        xaxis_title = 'Profile Number',
        yaxis_title = 'Bytes'
    )
  
    save_figure(fig, filedir+str(SNs[i])+'/TransmittionBytes.html', filedir+str(SNs[i])+'/TransmittionBytes.png')

#GROUP 2
progress('Generating upload plots')
for i ,d in enumerate(SNs):
    dats = indfloat[i]
    dats = dats.sort_values(by = ['ProfileId'])
    fig = go.Figure()
    for j, d in enumerate(group2):
        fig.add_trace(go.Scatter(
            x = dats['ProfileId'],
            y = dats[group2[j]],
            name = group2[j]
        ))
    fig.update_layout(
        title = 'Upload Info',
        xaxis_title = 'Profile Number',
        yaxis_title = 'Number of Attempts / Upload Number'
    )

    save_figure(fig, filedir+str(SNs[i])+'/UploadInfo.html', filedir+str(SNs[i])+'/UploadInfo.png')

#group 3
progress('Generating connection plots')
for i ,d in enumerate(SNs):
    dats = indfloat[i]
    dats = dats.sort_values(by = ['ProfileId'])
    fig = go.Figure()
    for j, d in enumerate(group3):
        fig.add_trace(go.Scatter(
            x = dats['ProfileId'],
            y = dats[group3[j]],
            name = group3[j]
        ))
    fig.update_layout(
        title = 'Connection Info',
        xaxis_title = 'Profile Number',
        yaxis_title = 'Connection Attemp / Connection Number'
    )

    save_figure(fig, filedir+str(SNs[i])+'/ConnectionInfo.html', filedir+str(SNs[i])+'/ConnectionInfo.png')

#group4
progress('Generating buoyancy-position plots')
for i ,d in enumerate(SNs):
    dats = indfloat[i]
    dats = dats.sort_values(by = ['ProfileId'])
    fig = go.Figure()
    for j, d in enumerate(group4):
        fig.add_trace(go.Scatter(
            x = dats['ProfileId'],
            y = dats[group4[j]],
            name = group4[j]
        ))
    fig.update_layout(
        title = 'Buoyancy Position',
        xaxis_title = 'Profile Number',
        yaxis_title = 'Position'
    )
    save_figure(fig, filedir+str(SNs[i])+'/BuoyancyPosition.html', filedir+str(SNs[i])+'/BuoyancyPosition.png')

#group5
progress('Generating vacuum and humidity plots')
for i ,d in enumerate(SNs):
    dats = indfloat[i]
    dats = dats.sort_values(by = ['ProfileId'])
    fig = go.Figure()
    for j, d in enumerate(group5):
        fig.add_trace(go.Scatter(
            x = dats['ProfileId'],
            y = dats[group5[j]],
            name = group5[j]
        ))
    fig.update_layout(
        title = 'Internal Vacuum Vs. Humidity',
        xaxis_title = 'Profile Number',
        yaxis_title = 'Vac. (counts) vs Humidity(%) vs Internal Temp (C)'
    )

    save_figure(fig, filedir+str(SNs[i])+'/VacHumid.html', filedir+str(SNs[i])+'/VacHumid.png')
    
dat['Park Pressure (dbars)'] = pd.to_numeric(
    dat['ParkObs'].astype(str).str.extract(r'(\d+(?:\.\d+)?)', expand=False),
    errors='coerce'
)



groups = dat.groupby('FloatId', sort=False)
indfloat2 = [groups.get_group(sn).copy() for sn in SNs]

for i, d in enumerate(indfloat2):
    indfloat2[i]=indfloat2[i].sort_values(by=['ProfileId'])
    indfloat2[i] = indfloat2[i].reset_index()
    indfloat2[i]['Park Pressure (dbars)'] = indfloat2[i]['Park Pressure (dbars)'].apply(pd.to_numeric)

indfloat3=[]
for i,d in enumerate(indfloat2):
    indfloat3.append(indfloat2[i].loc[indfloat2[i]['ProfileId']>0])
for i, d in enumerate(indfloat3):
    indfloat3[i] = indfloat3[i].sort_values(by=['ProfileId'])
    indfloat3[i] = indfloat3[i].reset_index()
progress_stage('Generating parameter plots across all floats', 0, 1, overall_start=62, overall_end=72)
# Across-float plots place every float on the same axes for comparison.
param = [
'GpsFixTime', 'BuoyancyPumpOnTime', 'ActiveBallastAdjustments','ParkBuoyancyPosition','Vacuum','GpsNsat','IsusPowerCycleCounter',\
'SurfacePressure','AirBladderPressure','DeepProfileBuoyancyPosition','SurfaceBuoyancyPosition','BatteryCounts','Sbe41cpHumidity','Sbe41cpHumidityTemp'
]
params = [
'GpsFixTime', 'BuoyancyPumpOnTime', 'ActiveBallastAdjustments','ParkBuoyancyPosition','IsusPowerCycleCounter',\
'SurfacePressure','AirBladderPressure','SurfaceBuoyancyPosition','DeepProfileBuoyancyPosition','BatteryCounts','BuoyancyPumpEnergy','Sbe41cpHumidity','TemperatureCorrectedRH'
]
j=0
dat=dat.sort_values(by = ['ProfileId'])

#Plot of Parameters across floats
for j, k in enumerate(params):
    progress_stage(f'All-float plot: {params[j]}', j + 1, len(params), overall_start=62, overall_end=72)
    fig=px.line(dat, x='ProfileId', y=params[j], color='FloatId', render_mode='webgl', category_orders={'FloatId': SNs}, labels={'AirBladderPressure':'Air Bladder Pressure (counts)', 'ProfileId':'Profile Number', 'BuoyancyPumpOnTime':'Buoyancy Pump Run Time (s)',\
        'ActiveBallastAdjustments':'Number of Active Ballast Adjustments','GpsFixTime':'Time for GPS Fix (s)', 'IsusPowerCycleCounter':'Number of Isus Power Cycles', 'ParkBuoyancyPosition':'Buoyancy Position of Park (counts)',\
        'SurfacePressure':'Surface Pressure (dbar)','DeepProfileBuoyancyPosition':'Deep Profile Buoyancy Position (counts)','SurfaceBuoyancyPosition':'Surface Buoyancy Position (counts)','BatteryCounts':'Battery Counts','BuoyancyPumpEnergy':'Buoyancy Pump Energy (J)', 'Sbe41cpHumidity':'Internal Humidity (%)', 'TemperatureCorrectedRH':'Temperature-corrected RH (%)'}, title = ('Temperature-corrected RH (20 °C)' if params[j] == 'TemperatureCorrectedRH' else params[j]))
    save_across_float_figure(fig, str(params[j]), filedir+'by_parameter/'+str(params[j])+'.html', filedir+'by_parameter/'+str(params[j])+'.png')

# Plot of Parameters for Each Float
i=0
j=0
float_plot_index = 0
float_plot_total = len(param) * len(SNs)
for j, k in enumerate(param):
    i=0
    while i < len(SNs):
        dats = indfloat[i]
        dats=dats.sort_values(by = ['ProfileId'])
        fig=px.line(dats,x=dats['ProfileId'],y=dats[param[j]], labels={'AirBladderPressure':'Air Bladder Pressure (inHg)', 'ProfileId':'Profile Number', 'BuoyancyPumpOnTime':'Buoyancy Pump Run Time (s)',\
        'ActiveBallastAdjustments':'Number of Active Ballast Adjustments','GpsFixTime':'Time for GPS Fix (s)', 'GpsNsat':'Number of Satellites', 'IsusPowerCycleCounter':'Number of Isus Power Cycles', 'ParkBuoyancyPosition':'Buoyancy Position of Park (counts)',\
        'SurfacePressure':'Surface Pressure (dbar)', 'Vacuum':'Vacuum (counts)','DeepProfileBuoyancyPosition':'Deep Profile Buoyancy Position (counts)','SurfaceBuoyancyPosition':'Surface Buoyancy Position (counts)','BatteryCounts':'Battery Counts',\
        'Sbe41cpHumidity':'Humidity (%)', 'Sbe41cpHumidityTemp':'Int. Temp (C)'}, title = param[j])
        save_figure(fig, filedir+str(SNs[i])+'/'+str(param[j])+'.html', filedir+str(SNs[i])+'/'+str(param[j])+'.png')
        float_plot_index += 1
        progress_stage(f'Per-float parameter plots: {param[j]}', float_plot_index, float_plot_total, overall_start=72, overall_end=82)
        i=i+1
    
# Mapping plots are retained only in the regular script and are skipped when
# HEALTH_REPORTS_ONLY is enabled.
if not HEALTH_REPORTS_ONLY:
    progress('Generating individual float track maps')
    for j,d in enumerate(indfloat):
        sn = indfloat[j]['FloatId']
        sn = sn.reset_index()
        fn = sn.reset_index()
        fn = fn['FloatId'][0]
        indfloat[j] = indfloat[j].sort_values(by=['ProfileId'])
        indfloat[j] = indfloat[j].reset_index()
        fig = px.line_geo(
            indfloat[j], indfloat[j]['GpsLat'], indfloat[j]['GpsLong'],
            hover_name=indfloat[j]['FloatId']
        )
        fig.update_layout(margin=dict(l=0, r=0, b=0, t=35))
        fig.update_geos(projection_type='orthographic')
        save_figure(fig, filedir+str(fn)+'/map.html', filedir+str(fn)+'/map.png')

    for i, d in enumerate(SNs):
        fig = go.Figure()
        fig.add_trace(go.Scattergeo(
            lon=indfloat[i]['GpsLong'],
            lat=indfloat[i]['GpsLat'],
            mode='lines',
            name=str(SNs[i])
        ))
        fig.update_geos(projection_type='orthographic')
        fig.update_layout(margin=dict(l=0, r=0, b=0, t=35))
        save_figure(fig, filedir+str(SNs[i])+'/map.html', filedir+str(SNs[i])+'/map.png')

    bathymetry_figure = make_gebco_bathymetry_figure(dat, SNs, filedir)
    if bathymetry_figure is not None:
        save_figure(
            bathymetry_figure,
            filedir+'bathymetry.html',
            filedir+'bathymetry.png',
        )

#Volts Plots
progress('Generating per-float voltage plots')
# Cycle 0 is excluded from voltage, current, and amp plots because it is not
# representative of normal float operation.
volts = ['McomsVolts','Sbe63Volts','Sbe41cpVolts','QuiescentVolts','BuoyancyPumpVolts','AirPumpVolts' ]

def without_cycle_zero(frame):
    """Return plotting data with cycle/profile 0 removed."""
    profile_numbers = pd.to_numeric(frame['ProfileId'], errors='coerce')
    return frame.loc[profile_numbers.ne(0)].copy()

for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    plot_data = without_cycle_zero(indfloat[j]).sort_values(by=['ProfileId'])
    fig = px.line(plot_data[volts], labels={'value':'Volts', 'index':'Profile Number', 'variable':'Hardware'}, title= 'Recorded Voltages')
    save_figure(fig, filedir+str(fn)+'/volts.html', filedir+str(fn)+'/volts.png')

#Volts Plots Across Floats
progress('Generating current plots across floats')
dat['FloatId']=dat['FloatId'].astype("category")
amps = ['McomsAmps','Sbe63Amps','Sbe41cpAmps','QuiescentAmps','BuoyancyPumpAmps','AirPumpAmps' ]
for i, d in enumerate(amps):
    fig = go.Figure()
    for j,k in enumerate(indfloat):
        plot_data = without_cycle_zero(indfloat[j])
        fig.add_trace(go.Scatter(
            x = plot_data['ProfileId'],
            y= plot_data[amps[i]],
            mode = 'lines+markers',
            name = str(indfloat[j]['FloatId'][0])
    ))
    fig.update_layout(
        title = amps[i],
        xaxis_title = 'Profile Number',
        yaxis_title = 'Current (amps)'
    )
    save_across_float_figure(fig, str(amps[i]), filedir+'by_parameter/'+str(amps[i])+'.html', filedir+'by_parameter/'+str(amps[i])+'.png')

#Volts Plots Across Floats
progress('Generating voltage plots across floats')
dat['FloatId']=dat['FloatId'].astype("category")
volts = ['McomsVolts','Sbe63Volts','Sbe41cpVolts','QuiescentVolts','BuoyancyPumpVolts','AirPumpVolts' ]
for i, d in enumerate(volts):
    fig = go.Figure()
    for j,k in enumerate(indfloat):
        plot_data = without_cycle_zero(indfloat[j])
        fig.add_trace(go.Scatter(
            x = plot_data['ProfileId'],
            y= plot_data[volts[i]],
            mode = 'lines+markers',
            name = str(indfloat[j]['FloatId'][0])
    ))
    fig.update_layout(
        title = volts[i],
        xaxis_title = 'Profile Number',
        yaxis_title = 'Voltage'
    )
    save_across_float_figure(fig, str(volts[i]), filedir+'by_parameter/'+str(volts[i])+'.html', filedir+'by_parameter/'+str(volts[i])+'.png')
progress('Generating combined motor-voltage plots')
#Volts Plots Across Floats
dat['FloatId']=dat['FloatId'].astype("category")
volts = ['McomsVolts','BuoyancyPumpVolts' ]
fig = go.Figure()
for i, d in enumerate(indfloat):
    plot_data = without_cycle_zero(indfloat[i])
    for j,k in enumerate(volts):
        fig.add_trace(go.Scatter(
            x = plot_data['ProfileId'],
            y= plot_data[volts[j]],
            mode = 'lines+markers',
            name = str(indfloat[i]['FloatId'][0])+str(volts[j])))
    fig.update_layout(
        #title = volts[i],
        xaxis_title = 'Profile Number',
        yaxis_title = 'Volts'
    )
    save_across_float_figure(fig, 'BPvsMCOMS', filedir+'BPvsMCOMS.html', filedir+'BPvsMCOMS.png')
#Amps Plots
progress('Generating per-float amperage plots')
amps = ['McomsAmps','Sbe63Amps','Sbe41cpAmps','QuiescentAmps','BuoyancyPumpAmps','AirPumpAmps' ]
for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    plot_data = without_cycle_zero(indfloat[j]).sort_values(by=['ProfileId'])
    fig = px.line(plot_data[amps], labels={'value':'Amps', 'index':'Profile Number', 'variable':'Hardware'}, title = 'Recorded Amperage')
    save_figure(fig, filedir+str(fn)+'/amps.html', filedir+str(fn)+'/amps.png')

#ParkPRessure Plots Across Floats
progress('Generating park-pressure plots')
fig = go.Figure()
for j,k in enumerate(indfloat):
        fig.add_trace(go.Scatter(
        x = indfloat[j]['ProfileId'],
        y= indfloat[j]['Park Pressure (dbars)'],
        mode = 'markers',
        name = str(indfloat[j]['FloatId'][0])
        
    
))
fig.update_layout(
    title = 'Park Pressure by Profile',
    xaxis_title = 'Profile Number',
    yaxis_title = 'Pressure (dbars)',
    yaxis = dict(autorange='reversed')
)
save_across_float_figure(fig, 'ParkPressure', filedir+'by_parameter/ParkPressure.html', filedir+'by_parameter/ParkPressure.png')



for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    indfloat[j] = indfloat[j].sort_values(by=['ProfileId'])
    #indfloat[j] = indfloat[j].reset_index()
    fig = px.line(indfloat[j]['Park Pressure (dbars)'], title= 'Park Pressure by Profile')
    fig.update_yaxes(autorange='reversed', title_text='Pressure (dbars)')
    save_figure(fig, filedir+str(fn)+'/ParkPressure.html', filedir+str(fn)+'/ParkPressure.png')

#Park Pressure vs Buoyancy Position

#ParkPRessure Plots Across Floats
fig = go.Figure()
for j,k in enumerate(indfloat):
        fig.add_trace(go.Scatter(
        x = indfloat[j]['ParkBuoyancyPosition'],
        y= indfloat[j]['Park Pressure (dbars)'],
        mode = 'markers',
        name = str(indfloat[j]['FloatId'][0])
))
fig.update_layout(
    title = 'Park Pressure vs. Buoyancy Position',
    xaxis_title = 'Park Buoyancy Position',
    yaxis_title = 'Pressure (dbars)',
    yaxis = dict(autorange='reversed')
)
save_across_float_figure(fig, 'ParkPressurevsBP', filedir+'by_parameter/ParkPressurevsBP.html', filedir+'by_parameter/ParkPressurevsBP.png')
progress('Generating pressure-versus-buoyancy plots')

# 
#Park Pressure vs Buoyancy Position

#ParkPRessure Plots Across Floats
fig = go.Figure()
for j,k in enumerate(indfloat):
        fig.add_trace(go.Scatter(
        x = indfloat[j]['ParkBuoyancyPosition'],
        y= indfloat[j]['Park Pressure (dbars)'],
        mode = 'markers',
        name = str(indfloat[j]['FloatId'][0])
))
for j,k in enumerate(indfloat):
        fig.add_trace(go.Scatter(
        x = indfloat[j]['SurfaceBuoyancyPosition'],
        y= indfloat[j]['SurfacePressure'],
        mode = 'markers',
        name = str(indfloat[j]['FloatId'][0])
        ))
fig.update_layout(
    title = 'Pressure vs. Buoyancy Position',
    xaxis_title = 'Buoyancy Position',
    yaxis_title = 'Pressure (dbars)',
    yaxis = dict(autorange='reversed')
)
save_across_float_figure(fig, 'PVBP', filedir+'by_parameter/PVBP.html', filedir+'by_parameter/PVBP.png')


# GET THE MAX PRESSURE FOR EVERY PROFILE AND ADD TO THIS DATAFRAME

maxp = profile_stats.copy()

maxp['PROFILE_ID']=maxp['PROFILE_ID'].astype('object')
maxp['PRES_MAX'] = maxp['PRES_MAX'].astype('object')
progress('Generating maximum-pressure plots')

d2 = pd.merge(dat,maxp, on = "PROFILE_ID", how = 'left')
#d2 = pd.concat(dat,maxp)

d2['FloatId'] = d2['FloatId'].astype(str)
s = d2.groupby("FloatId")

d3 = []
for i, j in enumerate(SNs):
    try:
        d3.append(s.get_group(str(SNs[i])))
    except:
        pass
for i, j in enumerate(d3):
    d3[i] = d3[i].reset_index()

fig = go.Figure()
for i, j in enumerate(SNs):
    fig.add_trace(go.Scatter(
    y = d3[i]['PRES_MAX'],
    x = d3[i]['ProfileId'],
    mode = 'markers',
    
    #name = str(d3[i]['FloatId']),
    #marker_color = d2['FloatId'],
    name = str(d3[i]['FloatId'][0])
    ))
fig.update_layout(
    xaxis_title = 'Profile Number',
    yaxis_title = 'Maximum Pressure (dbars)',
    yaxis = dict(autorange='reversed')
)
save_across_float_figure(fig, 'MAXP', filedir+'by_parameter/MAXP.html', filedir+'by_parameter/MAXP.png')

for i, j in enumerate(SNs):
    fig = px.scatter(d3[i],x = 'DeepProfileBuoyancyPosition', y = 'PRES_MAX', color = 'ProfileId')
    fig.update_yaxes(autorange='reversed', title_text='Maximum Pressure (dbars)')
    save_figure(fig, filedir+str(SNs[i])+'/MPBP.html', filedir+str(SNs[i])+'/MPBP.png')
fig



#Park Pressure vs Buoyancy Position
#ParkPRessure Plots Across Floats

fig = go.Figure()
for j,k in enumerate(indfloat3):
        fig.add_trace(go.Scatter(
        x = indfloat[j]['ParkBuoyancyPosition'],
        y= indfloat[j]['Park Pressure (dbars)'],
        mode = 'markers',
        name = str(indfloat[j]['FloatId'][0]),
        legendgroup = None,
        hovertext = None,
        marker = dict(color = 'blue')

        
))
for j,k in enumerate(indfloat3):
        fig.add_trace(go.Scatter(
        x = indfloat[j]['SurfaceBuoyancyPosition'],
        y= indfloat[j]['SurfacePressure'],
        mode = 'markers',
        name = str(indfloat[j]['FloatId'][0]),
        legendgroup = None,
        marker = dict(color = 'lightblue')
        ))
for j,k in enumerate(d3):
        fig.add_trace(go.Scatter(
        x = d3[j]['DeepProfileBuoyancyPosition'],
        y= d3[j]['PRES_MAX'],
        mode = 'markers',
        name = str(d3[j]['FloatId'][0]),
        legendgroup = None,
        marker = dict(color = 'DarkBlue')
        ))


fig.update_layout(
    title = 'Pressure vs. Buoyancy Position',
    xaxis_title = 'Buoyancy Position',
    yaxis_title = 'Pressure (dbars)',
    yaxis = dict(autorange='reversed'),
    showlegend = False
)
save_across_float_figure(fig, 'PVBP', filedir+'by_parameter/PVBP.html', filedir+'by_parameter/PVBP.png')

# 
for i, j in enumerate(d3):
    d3[i]['Park Pressure (dbars)']= d3[i]['Park Pressure (dbars)'].astype(float)
    d3[i] = d3[i].sort_values(by = 'Park Pressure (dbars)')
# 
# Park Buoyancy Position vs Park Pressure for each float

for i, j in enumerate(SNs):
    try:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x = indfloat[i]['ParkBuoyancyPosition'], #changed this?
            y = indfloat[i]['Park Pressure (dbars)'], #changed this? 
            mode = 'markers',
            marker = dict(
                size = 10,
                color = d3[i]['ProfileId'],
                colorscale = 'Viridis',
                showscale = True,
                colorbar = dict(title = 'Profile Number')
            )))
        fig.update_layout(
            title = 'Pressure vs. Buoyancy Position at Park',
            xaxis_title = 'Buoyancy Position',
            yaxis_title = 'Pressure (dbars)',
            yaxis = dict(autorange='reversed'),
            
            )
        save_figure(fig, filedir+str(SNs[i])+'/PBPvsPP.html', filedir+str(SNs[i])+'/PBPvsPP.png')
    except:
        pass

# Communication duration plots
progress('Downloading communication-duration data')

# Reuse the first all-float engineering download instead of requesting the
# same duration fields again from the API.
data = data[['PROFILE_ID', 'GPS_DURATION', 'TRANS_DURATION']].copy()
meta = get_metadata_all("FLOAT_SERIAL_NO,PLATFORM_NUMBER")

# split PROIFLE_ID column and remove; create SN colomn
data[["WMO","PROFILE"]] = data.PROFILE_ID.str.split(".", expand=True)
data = data.drop("PROFILE_ID", axis=1)
wmo_sn = dict(zip( meta.PLATFORM_NUMBER, meta.FLOAT_SERIAL_NO))
data["SN"] = data.WMO.replace(wmo_sn)

# convert to time delta object then to seconds
data.GPS_DURATION = pd.to_timedelta(data.GPS_DURATION).dt.total_seconds()
data.TRANS_DURATION = pd.to_timedelta(data.TRANS_DURATION).dt.total_seconds()
data = data.dropna()

# stats 
sat_mean = data.groupby("SN").TRANS_DURATION.mean()
sat_std = data.groupby("SN").TRANS_DURATION.std()
sat_mean.name = "MEAN"
sat_std.name = "STD"
sat = pd.concat([sat_mean, sat_std], axis=1).reset_index()
sat_mean_all = data.TRANS_DURATION.mean()
progress(f'Communication duration mean: {sat_mean_all / 60:.1f} minutes')
sat_mean_max = data.TRANS_DURATION.max()
progress(f'Communication duration maximum: {sat_mean_max / 3600:.1f} hours')

fig = go.Figure()
fig = px.bar(
    x = sat.SN,
    y = sat.MEAN/60,
    height = 900,
    width = 1600,
    error_y = sat.STD/60,
    )
fig.update_layout(
    title = 'Communication Duration By Float',
    xaxis_title = 'Float Serial No',
    yaxis_title = 'Minutes',
    )
fig.update_xaxes(
    ticks="outside", 
    tickwidth=2
    )
fig.update_traces(
    hovertemplate =' Float SN: %{x} <br>Minutes: %{y}',
    marker_color = 'LightSkyBlue'
    )
fig.add_hline(y=sat_mean_all/60, line_dash='dot',line_color='red')
save_figure(fig, filedir+'/by_parameter/COMDUR.html', filedir+'/by_parameter/COMDUR.png')
if not HEALTH_REPORTS_ONLY and GENERATE_ALL_FLOAT_PLOTS:
    for deployment_year, serial_numbers in DEPLOYMENT_COHORTS.items():
        cohort_sat = sat[sat['SN'].astype(str).isin(serial_numbers)]
        if cohort_sat.empty:
            continue
        cohort_fig = px.bar(
            x=cohort_sat.SN,
            y=cohort_sat.MEAN / 60,
            height=900,
            width=1600,
            error_y=cohort_sat.STD / 60,
        )
        cohort_fig.update_layout(title='Communication Duration By Float', xaxis_title='Float Serial No', yaxis_title='Minutes')
        cohort_directory = Path(filedir) / 'cohort_plots' / str(deployment_year)
        cohort_directory.mkdir(parents=True, exist_ok=True)
        save_figure(cohort_fig, cohort_directory / 'COMDUR.html', cohort_directory / 'COMDUR.png')

# Per-float health reports
# ---------------------------------------------------------------------------
# Health reports use cycle data only (cycle 0 is excluded), sorted by float and
# profile so that "latest" and "last readings" are calculated consistently.
diagnostic = dat.copy()
diagnostic['FloatId'] = diagnostic['FloatId'].astype(str)
diagnostic['ProfileId'] = pd.to_numeric(diagnostic['ProfileId'], errors='coerce')
diagnostic = diagnostic.loc[diagnostic['ProfileId'].ne(0)].copy()
diagnostic = diagnostic.sort_values(['FloatId', 'ProfileId'])

progress('Generating per-float health reports')

def health_status(value, watch_limit, concern_limit):
    # Return both a display label and a numeric score. The highest score across
    # all metrics becomes the overall status for the float.
    if value is None or pd.isna(value):
        return 'Insufficient data', 0
    if value >= concern_limit:
        return 'Concern', 2
    if value >= watch_limit:
        return 'Watch', 1
    return 'Good', 0


def health_value(value, suffix=''):
    return 'Insufficient data' if value is None or pd.isna(value) else f'{value:.2f}{suffix}'


def duration_seconds(frame, column):
    # TRANS_DURATION may arrive as either a numeric value or a time-like string.
    # Try both formats so the report works with either API representation.
    raw_values = frame.get(column, pd.Series(dtype=float))
    numeric_values = pd.to_numeric(raw_values, errors='coerce')
    timed_values = pd.to_timedelta(raw_values, errors='coerce').dt.total_seconds()
    return numeric_values.fillna(timed_values).dropna()


health_css = """
body { font-family: Arial, sans-serif; max-width: 1050px; margin: 28px auto;
padding: 0 20px; color: #273746; background: #f6f8fa; }
h1 { color: #174a70; }
.summary { padding: 14px 18px; margin: 20px 0; border-radius: 5px;
background: #e8f3f8; border-left: 5px solid #318db0; }
.summary.watch { background: #fff6df; border-color: #d28b00; }
.summary.concern { background: #fdecec; border-color: #c0392b; }
table { width: 100%; border-collapse: collapse; background: white; }
th, td { padding: 9px 10px; border-bottom: 1px solid #d7dee4; text-align: left; }
th { background: #eef3f6; color: #174a70; }
.report-plot { margin-top: 24px; padding: 10px; background: white; border: 1px solid #d7dee4; border-radius: 5px; }
.good { color: #287a3e; font-weight: bold; }
.watch { color: #996500; font-weight: bold; }
.concern { color: #b42318; font-weight: bold; }
.insufficient-data { color: #687783; font-weight: bold; }
"""

def difference_from_fleet_average(value, average):
    if value is None or pd.isna(value) or average is None or pd.isna(average) or average == 0:
        return None
    # Report runtime as a percentage of the fleet average:
    # 100% = equal to the fleet average, 115% = 15% above it.
    return value / average * 100


def last_readings_average(frame, column, count=3):
    values = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors='coerce').dropna()
    return values.tail(min(count, len(values))).mean() if not values.empty else None


def last_readings_vs_own_average(frame, column, count=3):
    values = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors='coerce').dropna()
    if values.empty or values.mean() == 0:
        return None
    recent_average = last_readings_average(frame, column, count)
    return recent_average / abs(values.mean()) * 100


fleet_runtime_values = {}
# Calculate each float's recent average pump runtime first. The fleet average
# is then calculated from those per-float values, giving every float equal
# weight regardless of how many records it contains.
for serial_number in SNs:
    float_frame = diagnostic.loc[diagnostic['FloatId'].eq(str(serial_number))]
    fleet_runtime_values[str(serial_number)] = last_readings_average(
        float_frame, 'BuoyancyPumpOnTime'
    )
fleet_runtime_average = pd.Series(fleet_runtime_values, dtype='float64').dropna().mean()


for health_index, serial_number in enumerate(SNs, start=1):
    # Build the report one float at a time so a problem in one float's data
    # does not require manually assembling reports for the other floats.
    progress_stage(
        f'Writing health report for float {serial_number}',
        health_index, len(SNs), overall_start=90, overall_end=100,
    )
    float_frame = diagnostic.loc[diagnostic['FloatId'].eq(str(serial_number))].copy()
    metrics = []
    scores = []

    timing = float_frame[['ProfileId', 'TimeStartTelemetry']].copy()
    timing['TimeStartTelemetry'] = pd.to_datetime(
        timing['TimeStartTelemetry'], errors='coerce', utc=True
    )
    timing = timing.dropna(subset=['TimeStartTelemetry']).sort_values('ProfileId')

    # Runtime is shown as a percentage of the fleet average: 100% is average,
    # 130% is the watch threshold and 155% is the concern threshold.
    runtime_percent = difference_from_fleet_average(
        fleet_runtime_values.get(str(serial_number)),
        fleet_runtime_average,
    )
    status, score = health_status(runtime_percent, 130, 155)
    metrics.append(('Buoyancy pump runtime vs fleet average', health_value(runtime_percent, '%'), status))
    scores.append(score)

    quiescent_voltage = last_readings_average(float_frame, 'QuiescentVolts', count=1)
    if quiescent_voltage is None or pd.isna(quiescent_voltage):
        status, score = 'Insufficient data', 0
    elif quiescent_voltage < 10:
        status, score = 'Concern', 2
    else:
        status, score = 'Good', 0
    metrics.append(('Quiescent voltage', health_value(quiescent_voltage, ' V'), status))
    scores.append(score)

    # Humidity values below 1% are treated as an unusable/near-zero reading,
    # so the last-vs-average comparison is intentionally skipped in that case.
    humidity_values = pd.to_numeric(
        float_frame.get('Sbe41cpHumidity', pd.Series(dtype=float)),
        errors='coerce'
    ).dropna()
    humidity_last = humidity_values.iloc[-1] if not humidity_values.empty else None
    humidity_average = humidity_values.mean() if not humidity_values.empty else None
    humidity_difference = None
    humidity_comparison_skipped = (
        humidity_last is not None and humidity_last < 1
    ) or (
        humidity_average is not None and humidity_average < 1
    )
    if not humidity_comparison_skipped and humidity_last is not None and humidity_average != 0:
        humidity_difference = (humidity_last - humidity_average) / abs(humidity_average) * 100
    if humidity_comparison_skipped:
        status, score = 'Good', 0
    else:
        status, score = health_status(
            abs(humidity_difference) if humidity_difference is not None else None,
            25,
            50,
        )
    metrics.append(('Latest humidity reading', health_value(humidity_last, '%'), status))
    humidity_comparison_value = (
        'Not compared (<1%)'
        if humidity_comparison_skipped
        else health_value(humidity_difference, '%')
    )
    metrics.append(('Humidity last reading vs float average', humidity_comparison_value, status))
    scores.append(score)

    surface_time_values = duration_seconds(float_frame, 'TRANS_DURATION')
    latest_surface_time = surface_time_values.iloc[-1] if not surface_time_values.empty else None
    metrics.append(('Latest time on surface', health_value(latest_surface_time, ' seconds'), 'Informational'))

    # Compare the average of the last two park/deep position readings with the
    # absolute mean for the same float. This is not a fleet comparison.
    for column, label in [
        ('ParkBuoyancyPosition', 'Park buoyancy position change'),
        ('DeepProfileBuoyancyPosition', 'Deep-profile buoyancy position change'),
    ]:
        position_change = last_readings_vs_own_average(float_frame, column, count=2)
        status, score = health_status(
            abs(position_change - 100) if position_change is not None else None,
            25,
            50,
        )
        metrics.append((label + ' vs float average', health_value(position_change, '%'), status))
        scores.append(score)

    attempts = pd.to_numeric(
        float_frame.get('CONNECTION_ATTEMPTS', pd.Series(dtype=float)),
        errors='coerce'
    ).sum(min_count=1)
    connections = pd.to_numeric(
        float_frame.get('CONNECTIONS', pd.Series(dtype=float)),
        errors='coerce'
    ).sum(min_count=1)
    failure_rate = None
    if pd.notna(attempts) and attempts > 0 and pd.notna(connections):
        failure_rate = max(0, (attempts - connections) / attempts * 100)
    status, score = health_status(failure_rate, 20, 50)
    metrics.append(('Connection failure estimate', health_value(failure_rate, '%'), status))
    scores.append(score)

    # Report age is timezone-safe because telemetry timestamps were converted
    # to UTC above and the current time is also requested in UTC.
    latest_report = timing['TimeStartTelemetry'].max() if not timing.empty else pd.NaT
    report_age = (
        (pd.Timestamp.now(tz='UTC') - latest_report).total_seconds() / 86400
        if pd.notna(latest_report) else None
    )
    if report_age is None or pd.isna(report_age):
        report_status, report_score = 'Insufficient data', 0
    elif report_age > 30:
        report_status, report_score = 'Concern', 2
    elif report_age > 10:
        report_status, report_score = 'Watch', 1
    else:
        report_status, report_score = 'Good', 0
    metrics.append(('Days since latest report', health_value(report_age, ' days'), report_status))
    scores.append(report_score)

    overall_status = {0: 'Good', 1: 'Watch', 2: 'Concern'}.get(max(scores, default=1), 'Insufficient data')
    overall_class = overall_status.lower().replace(' ', '-')
    rows_html = ''.join(
        f'<tr><td>{html.escape(label)}</td><td>{html.escape(value)}</td>'
        f'<td class="{status.lower().replace(" ", "-")}">{html.escape(status)}</td></tr>'
        for label, value, status in metrics
    )
    buoyancy_plot = go.Figure()
    profile_numbers = pd.to_numeric(float_frame['ProfileId'], errors='coerce')
    for column, label in [
        ('ParkBuoyancyPosition', 'Park'),
        ('DeepProfileBuoyancyPosition', 'Deep Profile'),
    ]:
        if column in float_frame.columns:
            position_values = pd.to_numeric(float_frame[column], errors='coerce')
            valid_positions = pd.DataFrame({
                'ProfileId': profile_numbers,
                'Position': position_values,
            }).dropna()
            if not valid_positions.empty:
                buoyancy_plot.add_trace(go.Scatter(
                    x=valid_positions['ProfileId'],
                    y=valid_positions['Position'],
                    mode='lines+markers',
                    name=label,
                ))
    if buoyancy_plot.data:
        buoyancy_plot.update_layout(
            title='Buoyancy Position by Profile',
            xaxis_title='Profile Number',
            yaxis_title='Buoyancy Position',
        )
        style_figure(buoyancy_plot)
        buoyancy_plot_html = f'<div class="report-plot">{buoyancy_plot.to_html(full_html=False, include_plotlyjs="cdn")}</div>'
    else:
        buoyancy_plot_html = '<p>No park or deep-profile buoyancy-position data are available for this float.</p>'
    report_html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Float {html.escape(str(serial_number))} Health Report</title>
<style>{health_css}</style></head><body>
<p><a href="../index.html">&larr; Engineering website</a></p>
<h1>Float {html.escape(str(serial_number))} Health Report</h1>
<p>Diagnostic screening based on the latest engineering data.</p>
<div class="summary {overall_class}">
<strong>Overall status: {html.escape(overall_status)}</strong><br>
Review the underlying plots and test records before making operational decisions.
</div>
<table><thead><tr><th>Metric</th><th>Value</th><th>Status</th></tr></thead>
<tbody>{rows_html}</tbody></table>
<h2>Buoyancy Position</h2>
{buoyancy_plot_html}
</body></html>"""
    report_path = Path(filedir) / str(serial_number) / 'health_report.html'
    # Write one self-contained HTML report inside that float's directory.
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_html, encoding='utf-8')

progress('Completed per-float health reports')
write_cohort_index()
write_registered_pngs()
progress(
    'Engineering report complete; health reports only'
    if HEALTH_REPORTS_ONLY
    else f'Engineering report complete; registered {len(PLOT_REGISTRY)} plots'
)
if INTERACTIVE_PLOT_MENU and not HEALTH_REPORTS_ONLY:
    serve_plot_menu()
