# %%
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import date, datetime
import webbrowser
from pathlib import Path
import json
import requests
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from concurrent.futures import ThreadPoolExecutor

# ---------------------------------------------------------------------------
# Database/API helpers
# Kept in this file so the report can be run as a single script.
# ---------------------------------------------------------------------------
BASE_URL = "https://db.whoifloatgroup.org"
PLATFORMTYPE = "&PLATFORM_TYPE=NAVIS_EBR"
REQUEST_HEADERS = {"Content-Type": "application/json"}
MAX_API_WORKERS = 8
WRITE_PNG = False  # Set to True when PNG copies are needed.
INTERACTIVE_PLOT_MENU = True  # Click a plot name to view only that figure.
SAVE_PLOTS = False             # Set to True to save HTML files as well.
PLOT_REGISTRY = []
FILTER_PLOT_OUTLIERS = True
OUTLIER_IQR_FACTOR = 3.0  # Larger values keep more extreme observations.

PLOT_COLORS = [
    '#1768AC', '#0E9F9A', '#E07A5F', '#7A5195',
    '#F2A541', '#3A7D44', '#D1495B', '#4C78A8',
]


def _get_dataframe(endpoint, params=None):
    """Call an API endpoint and return its JSON response as a DataFrame."""
    response = requests.get(
        f"{BASE_URL}/api/{endpoint}",
        headers=REQUEST_HEADERS,
        params=params or {},
        timeout=120,
    )
    response.raise_for_status()
    return pd.DataFrame(response.json())


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
    """Fetch profile statistics concurrently while preserving profile order."""
    with ThreadPoolExecutor(max_workers=MAX_API_WORKERS) as executor:
        frames = list(executor.map(get_discrete_profile_stats, profile_ids))
    return pd.concat(frames, ignore_index=True)


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


def style_figure(figure):
    """Apply consistent publication-style formatting to every Plotly figure."""
    figure.update_layout(
        template='plotly_white',
        colorway=PLOT_COLORS,
        paper_bgcolor='white',
        plot_bgcolor='#F8FAFC',
        font=dict(family='Arial, sans-serif', size=12, color='#263746'),
        margin=dict(l=64, r=28, t=64, b=58),
        legend=dict(
            bgcolor='rgba(255,255,255,0.86)',
            bordercolor='#D7DEE4',
            borderwidth=1,
        ),
        hoverlabel=dict(bgcolor='white', font_size=12),
    )
    figure.update_xaxes(
        showgrid=True, gridcolor='#E5E7EB', gridwidth=1,
        zeroline=False, title_standoff=12,
    )
    figure.update_yaxes(
        showgrid=True, gridcolor='#E5E7EB', gridwidth=1,
        zeroline=False, title_standoff=12,
    )
    if figure.layout.title.text:
        figure.update_layout(
            title=dict(
                text=figure.layout.title.text,
                x=0.02,
                xanchor='left',
                font=dict(size=18, color='#174A70'),
            )
        )
    for trace in figure.data:
        if hasattr(trace, 'line') and trace.line is not None:
            trace.line.width = 2
        if getattr(trace, 'mode', None) and 'markers' in trace.mode:
            trace.marker.size = 7
    return figure


def save_figure(figure, html_path, png_path=None):
    """Style a figure and register it for interactive viewing or saving."""
    if FILTER_PLOT_OUTLIERS:
        filter_plot_outliers(figure)
    style_figure(figure)
    if INTERACTIVE_PLOT_MENU:
        label = Path(html_path).stem.replace('_', ' ')
        PLOT_REGISTRY.append((label, figure))
    if SAVE_PLOTS:
        # Loading Plotly from a CDN keeps saved HTML files small.
        figure.write_html(html_path, include_plotlyjs='cdn')
        if WRITE_PNG and png_path is not None:
            figure.write_image(png_path)


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
    return _get_dataframe(
        "deployment_metadata",
        {"deployment_fields": output_fields, "PLATFORM_TYPE": "NAVIS_EBR"},
    )


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



name = 'Aidan' # WHAT IS YOUR NAME

if name == 'Aidan':
    filedir = Path('Z://www/bgc/engineering/')
elif name == 'Kat':
    filedir = Path('/Volumes/data1/www/bgc/engineering/')
else:
    raise ValueError('Set name to Aidan or Kat, or configure filedir explicitly.')
# Normalize once because the plotting code builds several legacy paths by
# concatenating strings (for example: filedir + str(serial_number)).
filedir = str(filedir).rstrip('/\\') + '/'

progress('Starting engineering report')


filename = f'{date.today()}_engineering'

progress('Downloading engineering data')
# Pull Engineering Data for all floats
data = get_engineering_all("PROFILE_ID,GPS_DURATION,TRANS_DURATION,SurfacePressure,Sbe63Volts,Vacuum,ParkBuoyancyPosition,GpsFixTime,FloatId,BuoyancyPumpOnTime,ActiveBallastAdjustments,\
ProfileId,GpsNsat,IsusPowerCycleCounter,GpsLong,GpsLat,PHBaseAmps,PHBatteryInVolts,PHBatteryOutVolts,AirBladderPressure,AirPumpAmps,AirPumpVolts,BuoyancyPumpAmps,BuoyancyPumpVolts,\
QuiescentAmps,QuiescentVolts,Sbe41cpAmps,Sbe41cpVolts,Sbe63Volts,McomsAmps,McomsVolts,Sbe63Amps,SurfaceBuoyancyPosition,DeepProfileBuoyancyPosition,ISUS_BYTES,MSG_BYTES,LOG_BYTES,\
UPLOAD_ATTEMPTS,UPLOADS,CONNECTIONS,CONNECTION_ATTEMPTS,TimeStartTelemetry,Sbe41cpHumidity,Sbe41cpHumidityTemp,BatteryCounts,ObsIndex,ParkDescentPCnt,ParkObs")
data = pd.DataFrame(data)
engineering_data = data.copy()

if name == 'Aidan':
    export_path = Path('G://Shared drives/WHOI Argo/BGC/Float Tracking/engineering_data') / f'{filename}.xlsx'
elif name == 'Kat':
    export_path = Path('/Users/katherineparise/Library/CloudStorage/GoogleDrive-katherine.parise@whoi.edu/Shared drives/WHOI Argo/BGC/Float Tracking/engineering_data') / f'{filename}.xlsx'
else:
    raise ValueError('Configure an engineering-data export path.')
export_path.parent.mkdir(parents=True, exist_ok=True)
data.to_excel(export_path, index=False)
progress(f'Loaded {len(data):,} engineering records for {data["FloatId"].nunique()} floats')

# Split it by each float you can call each float by indfloat[0:NumFloats]
SNs = serial_number_order(data['FloatId'].dropna())
groups = data.groupby('FloatId', sort=False)
indfloat = [groups.get_group(sn).sort_values('ProfileId').reset_index(drop=True) for sn in SNs]

# Create Folder for each float if it doesn't exist

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

#Report Days
progress('Calculating report dates, float ages, and cycle lengths')
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


# GET THE MAX PRESSURE FOR EVERY PROFILE AND ADD TO THIS DATAFRAME
progress('Downloading maximum pressure statistics')

mo = pd.unique(
    dat['PROFILE_ID'].astype(str).str.extract(r'(\d{7})', expand=False).dropna()
)
maxp = []
maxp = get_profile_stats_parallel(mo)
profile_stats = maxp.copy()

maxp['PROFILE_ID']=maxp['PROFILE_ID'].astype('object')
maxp['PRES_MAX'] = maxp['PRES_MAX'].astype('object')
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
    d3[i].reset_index(inplace = True)

deepp= []
for i, j in enumerate(d3):
    deepp.append(d3[i]['PRES_MAX'].iloc[-1])

tab = pd.DataFrame()
tab['Serial Number'] = SNs
tab['WMO ID'] = wmo
tab['Last Park Pressure (dbars)'] = parkpressure
tab['Last Deep Profile Pressure (dbars)'] = deepp
tab['First Report'] = firstreport
tab['Latest Report'] =lastreport
tab['Age in Days at Latest Report'] = age
tab['Latest Cycle Length']= cyclelength
tab['Cycle Number'] = cyclenum
tab['Days Since Last Report'] = timesince
tab = tab.sort_values(by = 'Serial Number')
tab['Serial Number'] = [make_named_link(sn, f'{sn}/index.html') for sn in tab['Serial Number']]

htmltab = generate_html(tab)

with open(Path(filedir, 'engineeringtable.html'), 'w', encoding='utf-8') as html_file:
    html_file.write(htmltab)
webbrowser.open(filedir+'engineeringtable.html')
#filename = str(date.today())+'_engineering'#update to day you run it
#data = pd.read_excel('G://Shared drives/WHOI Argo/BGC/Float Tracking/engineering_data' '/' +  filename + ".xlsx")
# Split it by each float you can call each float by indfloat[0:NumFloats]
data['BuoyancyPumpEnergy']=data['BuoyancyPumpOnTime']*data['BuoyancyPumpVolts']*data['BuoyancyPumpAmps']
groups = data.groupby('FloatId', sort=False)
indfloat = [groups.get_group(sn).sort_values('ProfileId').reset_index(drop=True) for sn in SNs]
dat = data.sort_values('ProfileId').copy()

# Variables to compare for each float
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
progress('Generating per-float sample and pump-energy plots')
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
progress('Generating parameter plots across all floats')
param = [
'GpsFixTime', 'BuoyancyPumpOnTime', 'ActiveBallastAdjustments','ParkBuoyancyPosition','Vacuum','GpsNsat','IsusPowerCycleCounter',\
'SurfacePressure','AirBladderPressure','DeepProfileBuoyancyPosition','SurfaceBuoyancyPosition','BatteryCounts','Sbe41cpHumidity','Sbe41cpHumidityTemp'
]
params = [
'GpsFixTime', 'BuoyancyPumpOnTime', 'ActiveBallastAdjustments','ParkBuoyancyPosition','IsusPowerCycleCounter',\
'SurfacePressure','AirBladderPressure','SurfaceBuoyancyPosition','DeepProfileBuoyancyPosition','BatteryCounts','BuoyancyPumpEnergy','Sbe41cpHumidity'
]
j=0
dat=dat.sort_values(by = ['ProfileId'])

#Plot of Parameters across floats
for j, k in enumerate(params):
    progress(f'Plotting all floats: {params[j]} ({j + 1}/{len(params)})')
    fig=px.line(dat, x='ProfileId', y=params[j], color='FloatId', render_mode='webgl', category_orders={'FloatId': SNs}, labels={'AirBladderPressure':'Air Bladder Pressure (counts)', 'ProfileId':'Profile Number', 'BuoyancyPumpOnTime':'Buoyancy Pump Run Time (s)',\
        'ActiveBallastAdjustments':'Number of Active Ballast Adjustments','GpsFixTime':'Time for GPS Fix (s)', 'IsusPowerCycleCounter':'Number of Isus Power Cycles', 'ParkBuoyancyPosition':'Buoyancy Position of Park (counts)',\
        'SurfacePressure':'Surface Pressure (dbar)','DeepProfileBuoyancyPosition':'Deep Profile Buoyancy Position (counts)','SurfaceBuoyancyPosition':'Surface Buoyancy Position (counts)','BatteryCounts':'Battery Counts','BuoyancyPumpEnergy':'Buoyancy Pump Energy (J)', 'Sbe41cpHumidity':'Internal Humidity (%)'}, title = params[j])
    save_figure(fig, filedir+'by_parameter/'+str(params[j])+'.html', filedir+'by_parameter/'+str(params[j])+'.png')

# Plot of Parameters for Each Float
i=0
j=0
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
        i=i+1
    
progress('Generating individual float track maps')
for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    indfloat[j] = indfloat[j].sort_values(by=['ProfileId'])
    indfloat[j] = indfloat[j].reset_index()
    fig = px.line_geo(indfloat[j],indfloat[j]['GpsLat'],indfloat[j]['GpsLong'],hover_name=indfloat[j]['FloatId'])
    fig.update_layout(
        margin = dict(l = 0, r = 0, b =0,t=35 ))
    fig.update_geos(projection_type = 'orthographic')
    save_figure(fig, filedir+str(fn)+'/map.html', filedir+str(fn)+'/map.png')
#Mape For each FLoat
for i, d in enumerate(SNs):
    fig = go.Figure()
    fig.add_trace(go.Scattergeo(
        lon = indfloat[i]['GpsLong'],
        lat = indfloat[i]['GpsLat'],
        mode = 'lines',
        name = str(SNs[i])
    ))
    fig.update_geos(projection_type = 'orthographic')
    fig.update_layout(
    margin = dict(l = 0, r = 0, b =0,t=35 ))

    save_figure(fig, filedir+str(SNs[i])+'/map.html', filedir+str(SNs[i])+'/map.png')

#Volts Plots
progress('Generating per-float voltage plots')
volts = ['McomsVolts','Sbe63Volts','Sbe41cpVolts','QuiescentVolts','BuoyancyPumpVolts','AirPumpVolts' ]
for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    indfloat[j] = indfloat[j].sort_values(by=['ProfileId'])
    #indfloat[j] = indfloat[j].reset_index()
    fig = px.line(indfloat[j][volts], labels={'value':'Volts', 'index':'Profile Number', 'variable':'Hardware'}, title= 'Recorded Voltages')
    save_figure(fig, filedir+str(fn)+'/volts.html', filedir+str(fn)+'/volts.png')

#Volts Plots Across Floats
progress('Generating current plots across floats')
dat['FloatId']=dat['FloatId'].astype("category")
amps = ['McomsAmps','Sbe63Amps','Sbe41cpAmps','QuiescentAmps','BuoyancyPumpAmps','AirPumpAmps' ]
for i, d in enumerate(amps):
    fig = go.Figure()
    for j,k in enumerate(indfloat):
        fig.add_trace(go.Scatter(
            x = indfloat[j]['ProfileId'],
            y= indfloat[j][amps[i]],
            mode = 'lines+markers',
            name = str(indfloat[j]['FloatId'][0])
    ))
    fig.update_layout(
        title = amps[i],
        xaxis_title = 'Profile Number',
        yaxis_title = 'Current (amps)'
    )
    save_figure(fig, filedir+'by_parameter/'+str(amps[i])+'.html', filedir+'by_parameter/'+str(amps[i])+'.png')

#Volts Plots Across Floats
progress('Generating voltage plots across floats')
dat['FloatId']=dat['FloatId'].astype("category")
volts = ['McomsVolts','Sbe63Volts','Sbe41cpVolts','QuiescentVolts','BuoyancyPumpVolts','AirPumpVolts' ]
for i, d in enumerate(volts):
    fig = go.Figure()
    for j,k in enumerate(indfloat):
        fig.add_trace(go.Scatter(
            x = indfloat[j]['ProfileId'],
            y= indfloat[j][volts[i]],
            mode = 'lines+markers',
            name = str(indfloat[j]['FloatId'][0])
    ))
    fig.update_layout(
        title = volts[i],
        xaxis_title = 'Profile Number',
        yaxis_title = 'Voltage'
    )
    save_figure(fig, filedir+'by_parameter/'+str(volts[i])+'.html', filedir+'by_parameter/'+str(volts[i])+'.png')
progress('Generating combined motor-voltage plots')
#Volts Plots Across Floats
dat['FloatId']=dat['FloatId'].astype("category")
volts = ['McomsVolts','BuoyancyPumpVolts' ]
fig = go.Figure()
for i, d in enumerate(indfloat):
    for j,k in enumerate(volts):
        fig.add_trace(go.Scatter(
            x = indfloat[i]['ProfileId'],
            y= indfloat[i][volts[j]],
            mode = 'lines+markers',
            name = str(indfloat[i]['FloatId'][0])+str(volts[j])))
    fig.update_layout(
        #title = volts[i],
        xaxis_title = 'Profile Number',
        yaxis_title = 'Volts'
    )
    save_figure(fig, filedir+'BPvsMCOMS.html', filedir+'BPvsMCOMS.png')
#Amps Plots
progress('Generating per-float amperage plots')
amps = ['McomsAmps','Sbe63Amps','Sbe41cpAmps','QuiescentAmps','BuoyancyPumpAmps','AirPumpAmps' ]
for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    indfloat[j] = indfloat[j].sort_values(by=['ProfileId'])
    #indfloat[j] = indfloat[j].reset_index()
    fig = px.line(indfloat[j][amps], labels={'value':'Amps', 'index':'Profile Number', 'variable':'Hardware'}, title = 'Recorded Amperage')
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
    yaxis_title = 'Pressure (dbars)'
)
save_figure(fig, filedir+'by_parameter/ParkPressure.html', filedir+'by_parameter/ParkPressure.png')



for j,d in enumerate(indfloat):
    sn = indfloat[j]['FloatId']
    sn=sn.reset_index()
    fn = sn.reset_index()
    fn=(fn['FloatId'][0])
    indfloat[j] = indfloat[j].sort_values(by=['ProfileId'])
    #indfloat[j] = indfloat[j].reset_index()
    fig = px.line(indfloat[j]['Park Pressure (dbars)'], title= 'Park Pressure by Profile')
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
    yaxis_title = 'Pressure (dbars)'
)
save_figure(fig, filedir+'by_parameter/ParkPressurevsBP.html', filedir+'by_parameter/ParkPressurevsBP.png')
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
    yaxis_title = 'Pressure (dbars)'
)
save_figure(fig, filedir+'by_parameter/PVBP.html', filedir+'by_parameter/PVBP.png')


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
    d3[i].reset_index(inplace = True)

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
    yaxis_title = 'Maximum Pressure (dbars)'
)
save_figure(fig, filedir+'by_parameter/MAXP.html', filedir+'by_parameter/MAXP.png')

for i, j in enumerate(SNs):
    fig = px.scatter(d3[i],x = 'DeepProfileBuoyancyPosition', y = 'PRES_MAX', color = 'ProfileId')
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
    showlegend = False
)
save_figure(fig, filedir+'by_parameter/PVBP.html', filedir+'by_parameter/PVBP.png')

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
            
            )
        save_figure(fig, filedir+str(SNs[i])+'/PBPvsPP.html', filedir+str(SNs[i])+'/PBPvsPP.png')
    except:
        pass

# Communication duration plots
progress('Downloading communication-duration data')

data = get_engineering_all("PROFILE_ID,GPS_DURATION,TRANS_DURATION")
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

progress(f'Engineering report complete; registered {len(PLOT_REGISTRY)} plots')
if INTERACTIVE_PLOT_MENU:
    serve_plot_menu()
