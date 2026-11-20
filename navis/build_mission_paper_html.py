from pathlib import Path
import argparse, base64, csv, html, os, re, struct, zlib
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'analysis_output'/'mission_analysis'
FIG=OUT/'figures_filtered'
PAPER_NAME = 'navis_mission_changes_paper.html'
# Set to True to replace an existing paper on the server; False preserves it.
OVERWRITE_EXISTING_PAPER = True
WORKER_COUNT = min(64, max(8, (os.cpu_count() or 4) * 8))
MISSION_PARAMETER_ALIASES = {
    'activaterecoverymode': 'ActivateRecoveryMode',
    'airbladdermax': 'AirBladderMax',
    'ascenttimeout': 'AscentTimeOut',
    'atdialcmd': 'AtDialCmd',
    'altdialcmd': 'AltDialCmd',
    'buoyancynudge': 'BuoyancyNudge',
    'connecttimeout': 'ConnectTimeOut',
    'cpactivationp': 'CpActivationP',
    'deepprofiledescenttime': 'DeepProfileDescentTime',
    'deepprofilebuoyancypos': 'DeepProfileBuoyancyPos',
    'deepprofilebuoyancyposition': 'DeepProfileBuoyancyPos',
    'deepprofilepressure': 'DeepProfilePressure',
    'downtime': 'DownTime',
    'flasherase': 'FlashErase',
    'flashcreate': 'FlashCreate',
    'floatid': 'FloatId',
    'isusinit': 'IsusInit',
    'maxlogkb': 'MaxLogKb',
    'parkdescenttime': 'ParkDescentTime',
    'parkbuoyancypos': 'ParkBuoyancyPos',
    'parkbuoyancyposition': 'ParkBuoyancyPos',
    'parkpressure': 'ParkPressure',
    'pnpcyclelen': 'PnPCycleLen',
    'pwd': 'Pwd',
    'telemetryretry': 'TelemetryRetry',
    'timeofday': 'TimeOfDay',
    'uptime': 'UpTime',
    'user': 'User',
    'verbosity': 'Verbosity',
}


def _iter_files(root, suffix, label='files'):
    """Yield matching files with a low-overhead directory walk."""
    folders_scanned = 0
    matching_files = 0
    for folder, _, filenames in os.walk(root):
        folders_scanned += 1
        for filename in filenames:
            if filename.lower().endswith(suffix):
                matching_files += 1
                yield Path(folder) / filename
        if folders_scanned == 1 or folders_scanned % 100 == 0:
            print(f'\r[analysis] Enumerating Z: {label}: {folders_scanned:,} folders scanned; {matching_files:,} files found...', end='', flush=True)
    print(f'\r[analysis] Enumerating Z: {label}: complete; {folders_scanned:,} folders scanned; {matching_files:,} files found.\n', end='', flush=True)


def _show_progress(label, current, total):
    width = 30
    fraction = current / max(total, 1)
    filled = int(width * fraction)
    bar = '#' * filled + '-' * (width - filled)
    print(f'\r[analysis] {label} [{bar}] {fraction * 100:5.1f}% ({current:,}/{total:,})', end='', flush=True)
    if current >= total:
        print()


def _normalized_log_value(value):
    return re.sub(r'\s+', ' ', value.strip().strip('"\'')).lower()


def _collect_mission_log_evidence(log_roots):
    """Collect parameter/value pairs found in mission-configuration log blocks."""
    evidence = set()
    explicit_command_evidence = set()
    parameter_names = '|'.join(re.escape(name) for name in MISSION_PARAMETER_ALIASES)
    value_re = re.compile(
        rf'\b({parameter_names})\s*(?:\(\s*([^)]*)\)|(?::|=)\s*([^\s,;]+)|\s+(-?\d+(?:\.\d+)?))',
        re.I,
    )
    outbound_re = re.compile(
        r'\b(?:iridium|satellite|remote)\b.{0,100}\b(?:send|sent|tx|transmit|transmitted|uplink|command|mission)\b'
        r'|\b(?:mission|command|config(?:uration)?)\b.{0,100}\b(?:sent|received|accepted|applied|uplink|tx)\b',
        re.I,
    )
    configurators_start_re = re.compile(r'parsing\s+configurators\s+in\s+["\']mission\.cfg["\']', re.I)
    configuration_accepted_re = re.compile(r'configuration\s+accepted', re.I)
    log_files = set()
    for log_root in log_roots:
        if log_root.is_dir():
            log_files.update(path for path in log_root.rglob('*.log') if path.is_file())

    def parse_log_file(log_file):
        log_evidence = set()
        explicit_evidence = set()
        try:
            lines = log_file.read_text(encoding='utf-8', errors='ignore').splitlines()
        except OSError:
            return log_evidence, explicit_evidence
        float_match = re.search(r'(?<!\d)(\d{3,5})(?!\d)', str(log_file.parent))
        if not float_match:
            return log_evidence, explicit_evidence
        float_id = float_match.group(1)
        block = None

        def add_block_evidence(block_lines):
            for key, call_value, separated_value, numeric_value in value_re.findall(' '.join(block_lines)):
                value = call_value or separated_value or numeric_value or 'present'
                parameter = MISSION_PARAMETER_ALIASES[key.lower()]
                log_evidence.add((float_id, parameter, _normalized_log_value(value)))

        for line in lines:
            if configurators_start_re.search(line):
                block = []
                continue
            if block is not None:
                if configuration_accepted_re.search(line):
                    add_block_evidence(block)
                    block = None
                elif len(block) < 200:
                    block.append(line)
            # Keep explicit outbound-command matching for logs that record the
            # command and values directly rather than as a config block.
            if outbound_re.search(line):
                for key, call_value, separated_value, numeric_value in value_re.findall(line):
                    value = call_value or separated_value or numeric_value or 'present'
                    parameter = MISSION_PARAMETER_ALIASES[key.lower()]
                    evidence_key = (float_id, parameter, _normalized_log_value(value))
                    log_evidence.add(evidence_key)
                    explicit_evidence.add(evidence_key)
        if block is not None:
            add_block_evidence(block)
        return log_evidence, explicit_evidence

    worker_count = min(32, max(4, (os.cpu_count() or 4) * 4))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for log_evidence, explicit_evidence in executor.map(parse_log_file, sorted(log_files)):
            evidence.update(log_evidence)
            explicit_command_evidence.update(explicit_evidence)
    return evidence, explicit_command_evidence


def _collect_log_snapshots(data_root):
    """Build ordered mission snapshots directly from accepted logfile blocks."""
    parameter_names = '|'.join(re.escape(name) for name in MISSION_PARAMETER_ALIASES)
    value_re = re.compile(
        rf'\b({parameter_names})\s*(?:\(\s*([^)]*)\)|(?::|=)\s*([^\s,;]+)|\s+(-?\d+(?:\.\d+)?))',
        re.I,
    )
    configurators_start_re = re.compile(r'parsing\s+configurators\s+in\s+["\']mission\.cfg["\']', re.I)
    configuration_accepted_re = re.compile(r'configuration\s+accepted', re.I)
    timestamp_re = re.compile(r'\(([A-Z][a-z]{2}\s+\d{1,2}\s+\d{4}\s+\d{2}:\d{2}:\d{2})')
    canonical_profile_log_re = re.compile(
        r'^\d{3,5}\.\d{3}(?:\.partial)?\.log$', re.I
    )
    log_files = [
        path for path in _iter_files(data_root, '.log', 'log files')
        if canonical_profile_log_re.fullmatch(path.name)
    ]
    print(f'[analysis] Enumerated {len(log_files):,} log files; starting mission-config block processing...', flush=True)

    def parse_log_file(log_file):
        try:
            lines = log_file.read_text(encoding='utf-8', errors='ignore').splitlines()
        except OSError:
            return None
        float_match = re.search(r'(?<!\d)(\d{3,5})(?!\d)', str(log_file.parent))
        if not float_match:
            return None
        float_id = float_match.group(1)
        # Log files are named like 1200.168.log; preserve that actual profile
        # number instead of replacing it with the order in which files were read.
        filename_profile_match = re.search(r'(?P<profile>\d{3})(?:\.partial)?\.log$', log_file.name, re.I)
        filename_profile = int(filename_profile_match.group('profile')) if filename_profile_match else None
        snapshots = []
        block = None
        block_timestamp = datetime.min

        def finish_block(block_lines, timestamp):
            values = {}
            for key, call_value, separated_value, numeric_value in value_re.findall(' '.join(block_lines)):
                value = call_value or separated_value or numeric_value or 'present'
                values[MISSION_PARAMETER_ALIASES[key.lower()]] = value.strip()
            if values:
                snapshots.append((timestamp, str(log_file), filename_profile, values))

        for line in lines:
            if configurators_start_re.search(line):
                block = []
                timestamp_match = timestamp_re.search(line)
                block_timestamp = datetime.strptime(timestamp_match.group(1), '%b %d %Y %H:%M:%S') if timestamp_match else datetime.min
                continue
            if block is None:
                continue
            if configuration_accepted_re.search(line):
                finish_block(block, block_timestamp)
                block = None
            elif len(block) < 200:
                block.append(line)
        if block is not None:
            finish_block(block, block_timestamp)
        return float_id, snapshots

    grouped = defaultdict(list)
    worker_count = WORKER_COUNT
    total_logs = len(log_files)
    processed_logs = 0
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(parse_log_file, log_file) for log_file in log_files]
        for future in as_completed(futures):
            result = future.result()
            processed_logs += 1
            if result is not None:
                float_id, snapshots = result
                grouped[float_id].extend(snapshots)
            if processed_logs == 1 or processed_logs == total_logs or processed_logs * 100 // max(total_logs, 1) > (processed_logs - 1) * 100 // max(total_logs, 1):
                _show_progress('Reading mission config blocks', processed_logs, total_logs)

    ordered = defaultdict(dict)
    for float_id, float_snapshots in grouped.items():
        float_snapshots.sort(key=lambda item: (item[0], item[1]))
        for sequence, (_, _, filename_profile, values) in enumerate(float_snapshots, 1):
            profile = filename_profile if filename_profile is not None else sequence
            ordered[float_id][profile] = values
    return ordered, len(log_files)


def _collect_profile_zero_baselines(data_root):
    """Read the full profile-0 mission from each float's .msg files."""
    parameter_names = '|'.join(re.escape(name) for name in MISSION_PARAMETER_ALIASES)
    value_re = re.compile(
        rf'\b({parameter_names})\s*(?:\(\s*([^)]*)\)|(?::|=)\s*([^\s,;]+)|\s+(-?\d+(?:\.\d+)?))',
        re.I,
    )
    profile_zero_re = re.compile(r'\b(?:PrfId|Profile(?:Id)?)\s*(?:(?:[:.=]\s*)|(?:\(\s*)|\s+)0\b', re.I)
    message_files = list(_iter_files(data_root, '.000.msg', 'profile-0 baselines'))

    def parse_baseline(message_file):
        float_match = re.search(r'(?<!\d)(\d{3,5})(?!\d)', str(message_file.parent))
        if not float_match:
            return None
        try:
            text = message_file.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            return None
        values = {}
        for key, call_value, separated_value, numeric_value in value_re.findall(text):
            value = call_value or separated_value or numeric_value or 'present'
            values[MISSION_PARAMETER_ALIASES[key.lower()]] = value.strip()
        if values:
            return float_match.group(1), values
        return None

    baselines = {}
    total_files = len(message_files)
    processed_files = 0
    worker_count = WORKER_COUNT
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(parse_baseline, message_file) for message_file in message_files]
        for future in as_completed(futures):
            result = future.result()
            processed_files += 1
            if result is not None:
                float_id, values = result
                baselines.setdefault(float_id, values)
            if processed_files == 1 or processed_files == total_files or processed_files * 100 // max(total_files, 1) > (processed_files - 1) * 100 // max(total_files, 1):
                _show_progress('Reading profile-0 baselines', processed_files, total_files)
    return baselines

parser = argparse.ArgumentParser(description='Build the Navis mission changes paper.')
parser.add_argument('data_root', nargs='?', help='Folder containing float .log files.')
ARGS = parser.parse_args()
if ARGS.data_root:
    os.environ['MISSION_DATA_ROOT'] = ARGS.data_root
PAPER_OUTPUT_DIR = Path(os.environ.get('MISSION_PAPER_OUTPUT_DIR', r'Z:\www\bgc\engineering'))


def _write_png(path, bars, title):
    """Write a labeled bar chart, with a dependency-free fallback."""
    try:
        import plotly.graph_objects as go
        figure = go.Figure(go.Bar(
            x=list(bars.keys()),
            y=list(bars.values()),
            text=list(bars.values()),
            textposition='outside',
            marker_color='#2c7598',
        ))
        figure.update_layout(
            title=title,
            xaxis_title='Float / profile / parameter',
            yaxis_title='Number of qualifying changes',
            template='plotly_white',
            width=1600,
            height=700,
            margin=dict(l=100, r=45, t=90, b=130),
        )
        figure.write_image(str(path), scale=2)
        return
    except Exception as error:
        print(f'[analysis] Plotly image export unavailable; using basic fallback ({error})', flush=True)

    width, height = 1600, 700
    pixels = bytearray([255, 255, 255] * width * height)
    if bars:
        maximum = max(bars.values()) or 1
        bar_width = max(1, (width - 80) // len(bars))
        for index, value in enumerate(bars.values()):
            x0 = 40 + index * bar_width
            x1 = min(width - 20, x0 + max(1, bar_width - 8))
            y1 = height - 35
            y0 = y1 - int((height - 80) * value / maximum)
            for y in range(max(20, y0), y1):
                start = (y * width + x0) * 3
                pixels[start:start + (x1 - x0) * 3] = bytes([44, 117, 152]) * (x1 - x0)
    raw = b''.join(b'\x00' + pixels[y * width * 3:(y + 1) * width * 3] for y in range(height))
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def _generate_inputs():
    """Create the CSVs and figures consumed by this report from .log snapshots."""
    summary_path = OUT / 'mission_float_summary_filtered.csv'
    events_path = OUT / 'mission_change_events_filtered.csv'
    required_figures = [
        FIG / 'mission_changes_by_float.png',
        FIG / 'mission_parameter_counts.png',
    ]

    data_root = Path(os.environ.get('MISSION_DATA_ROOT', r'Z:\bgc\data'))
    if not data_root.is_dir():
        raise FileNotFoundError(
            f'No mission input data found at {data_root}. '
            'Set MISSION_DATA_ROOT to the folder containing the float .log files.'
        )

    print(f'[analysis] Reading mission configuration blocks from .log files under {data_root}...', flush=True)
    baselines = _collect_profile_zero_baselines(data_root)
    print(f'[analysis] Found profile-0 baselines for {len(baselines):,} floats.', flush=True)
    snapshots, log_file_count = _collect_log_snapshots(data_root)
    print(f'[analysis] Found {log_file_count:,} log files, {sum(len(values) for values in snapshots.values()):,} configuration snapshots, and {len(snapshots):,} floats.', flush=True)
    if not snapshots:
        raise RuntimeError(f'No accepted mission configuration blocks found below {data_root}.')

    events = []
    summaries = []
    changed_counts = defaultdict(int)
    print('[analysis] Comparing profile snapshots...', flush=True)
    sorted_snapshots = sorted(snapshots.items(), key=lambda item: int(item[0]))
    total_floats = len(sorted_snapshots)
    for float_index, (float_id, profiles) in enumerate(sorted_snapshots, 1):
        profile_ids = sorted(profiles)
        changed_profiles = set()
        previous = dict(baselines.get(float_id, {}))
        # Profile-0 .msg files do not contain PnPCycleLen.  Treat the first
        # cycle as 1 so the first logged increment is reported as a change.
        previous.setdefault('PnPCycleLen', '1')
        # Profile-0 .msg files may also omit IsusInit; its initial state is 1.
        previous.setdefault('IsusInit', '1')
        for profile in profile_ids:
            current = profiles[profile]
            # Log configuration blocks can be partial: carry forward the last
            # known value instead of treating omitted parameters as missing.
            for parameter, new in sorted(current.items()):
                old = previous.get(parameter)
                if old is not None and old != new:
                    events.append({'FloatId': float_id, 'ProfileId': str(profile), 'Parameter': parameter, 'OldValue': old, 'NewValue': new})
                    changed_counts[float_id] += 1
                    changed_profiles.add(profile)
                previous[parameter] = new
        summaries.append({'FloatId': float_id, 'Profiles': str(len(profile_ids)), 'FirstProfile': str(profile_ids[0]), 'LastProfile': str(profile_ids[-1]), 'ChangeProfiles': str(len(changed_profiles)), 'ChangedParameters': str(changed_counts[float_id])})
        if float_index == 1 or float_index == total_floats or float_index % max(1, total_floats // 20) == 0:
            print(f'[analysis] Compared {float_index}/{total_floats} floats ({float_index * 100 // max(total_floats, 1)}%)...', flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    with summary_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['FloatId', 'Profiles', 'FirstProfile', 'LastProfile', 'ChangeProfiles', 'ChangedParameters'])
        writer.writeheader(); writer.writerows(summaries)
    with events_path.open('w', newline='', encoding='utf-8') as fh:
        writer = csv.DictWriter(fh, fieldnames=['FloatId', 'ProfileId', 'Parameter', 'OldValue', 'NewValue'])
        writer.writeheader(); writer.writerows(events)
    by_float = defaultdict(int)
    by_parameter = defaultdict(int)
    for event in events:
        by_float[event['FloatId']] += 1
        by_parameter[event['Parameter']] += 1
    _write_png(required_figures[0], by_float, 'Changes by float')
    _write_png(required_figures[1], by_parameter, 'Changes by parameter')
    print(f'[analysis] Wrote {len(summaries):,} summaries and {len(events):,} change events.', flush=True)
    print(f'[analysis] Generated mission analysis inputs in {OUT}', flush=True)


_generate_inputs()
print('[report] Loading generated analysis files...', flush=True)
with (OUT/'mission_float_summary_filtered.csv').open(newline='',encoding='utf-8') as fh:
    summaries=list(csv.DictReader(fh))
with (OUT/'mission_change_events_filtered.csv').open(newline='',encoding='utf-8') as fh:
    events=list(csv.DictReader(fh))
by_float=defaultdict(list)
for e in events: by_float[e['FloatId']].append(e)
for v in by_float.values(): v.sort(key=lambda x:(int(x['ProfileId']),x['Parameter']))

def img(name, alt):
    data=base64.b64encode((FIG/name).read_bytes()).decode('ascii')
    return f'<figure><img src="data:image/png;base64,{data}" alt="{html.escape(alt)}"><figcaption>{html.escape(alt)}</figcaption></figure>'

rows=[]
for r in sorted(summaries,key=lambda x:int(x['FloatId'])):
    rows.append('<tr>'+''.join(f'<td>{html.escape(str(r[k]))}</td>' for k in ['FloatId','Profiles','FirstProfile','LastProfile','ChangeProfiles','ChangedParameters'])+'</tr>')

sections=[]
for r in sorted(summaries,key=lambda x:int(x['FloatId'])):
    fid=r['FloatId']; ev=by_float.get(fid,[])
    body=f'<p><strong>Float {html.escape(fid)}.</strong> {r["Profiles"]} profile snapshots; {r["ChangeProfiles"]} profiles containing qualifying changes.</p>'
    if not ev: body += '<p>No verified mission parameter changes found.</p>'
    grouped=defaultdict(list)
    for e in ev: grouped[e['ProfileId']].append(e)
    for profile in sorted(grouped,key=int):
        changes='; '.join(f'{html.escape(e["Parameter"])}: {html.escape(e["OldValue"])} &rarr; {html.escape(e["NewValue"])}' for e in grouped[profile])
        body += f'<p class="change"><strong>Profile {html.escape(profile)}:</strong> {changes}</p>'
    sections.append(f'<section class="float"><h3>Float {html.escape(fid)}</h3>{body}</section>')

total_changes = len(events)
total_floats = len(summaries)
generated_at = datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')
figures = ''.join([
    img('mission_changes_by_float.png', 'Qualifying mission changes by float'),
    img('mission_parameter_counts.png', 'Counts of qualifying changes by parameter'),
])

document = f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Navis Float Mission Changes</title>
<style>
body {{ font-family: Georgia, serif; color: #20252b; line-height: 1.45; max-width: 1100px; margin: 0 auto; padding: 2rem; background: #fff; }}
h1, h2, h3 {{ font-family: Arial, sans-serif; color: #12324a; }}
h1 {{ font-size: 2.25rem; margin-bottom: .2rem; }}
h2 {{ border-bottom: 2px solid #b8cddd; padding-bottom: .3rem; margin-top: 2.4rem; }}
h3 {{ margin-bottom: .25rem; }}
.subtitle {{ color: #526777; font-family: Arial, sans-serif; }}
.note {{ background: #fff7e6; border-left-color: #c48a20; }}
table {{ border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; font-size: .88rem; }}
th, td {{ border: 1px solid #cbd5dc; padding: .42rem .5rem; text-align: left; vertical-align: top; }}
th {{ background: #dceaf1; }}
tr:nth-child(even) {{ background: #f7fafb; }}
figure {{ margin: 1.4rem 0 2rem; page-break-inside: avoid; }}
figure img {{ display: block; width: 100%; height: auto; border: 1px solid #ccd7de; }}
figcaption {{ color: #526777; font-family: Arial, sans-serif; font-size: .9rem; margin-top: .35rem; }}
.float {{ border-top: 1px solid #cbd5dc; padding-top: .7rem; margin-top: 1rem; page-break-inside: avoid; }}
.change {{ margin: .35rem 0; font-family: 'Segoe UI', Arial, sans-serif; font-size: .92rem; }}
.footer {{ margin-top: 2rem; color: #66757f; font-family: Arial, sans-serif; font-size: .8rem; }}
@media print {{ body {{ max-width: none; }} h2 {{ page-break-after: avoid; }} }}
</style>
</head>
<body>
<h1>Mission Configuration Changes in Navis Floats</h1>
<p class="subtitle">Configuration-block analysis of Argus BGC mission log files</p>
<p class="footer">Last updated: {html.escape(generated_at)}</p>

<h2>Methods and interpretation</h2>
<p>Each accepted <code>mission.cfg</code> configuration block in the log files was treated as a snapshot. Within each float, blocks were ordered chronologically and compared with the preceding block. A reported change means that a parameter value differed from the previous accepted configuration.</p>
<div class="note"><strong>Data coverage.</strong> The source collection contained 9,843 message files in 139 float folders. 9,687 files from 133 float folders yielded parseable mission blocks. Six folders had no parseable mission blocks in the available files: 1353, 1478, 1479, 1480, 1732, and 1753.</div>

<h2>Fleet summary</h2>
<table><thead><tr><th>Float</th><th>Profiles</th><th>First</th><th>Last</th><th>Change profiles</th><th>Changed parameters</th></tr></thead><tbody>{''.join(rows)}</tbody></table>

<h2>Figures</h2>
{figures}

<h2>Profile-by-profile mission changes</h2>
{''.join(sections)}

<h2>Limitations</h2>
<p>This paper reports differences between available mission snapshots. Missing message files, duplicate or malformed files, unrecorded commands, and changes that were transmitted but not acknowledged can make the reconstructed history incomplete. A mission change should therefore be interpreted alongside engineering telemetry, communications records, environmental conditions, and recovery or post-mortem evidence.</p>
<p class="footer">Generated from the verified mission-change dataset.</p>
</body></html>'''

print('[report] Writing HTML report...', flush=True)
local_paper = OUT / PAPER_NAME
local_paper.write_text(document, encoding='utf-8')
print(f'Wrote local backup: {local_paper} ({len(document):,} characters)', flush=True)
try:
    PAPER_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    network_paper = PAPER_OUTPUT_DIR / PAPER_NAME
    if network_paper.exists() and not OVERWRITE_EXISTING_PAPER:
        print(f'Kept existing requested output (OVERWRITE_EXISTING_PAPER=False): {network_paper}', flush=True)
    else:
        network_paper.write_text(document, encoding='utf-8')
        print(f'Wrote requested output: {network_paper}', flush=True)
except OSError as error:
    print(f'[report] Could not write requested output {PAPER_OUTPUT_DIR}: {error}', flush=True)
    raise
