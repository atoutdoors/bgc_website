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
OVERWRITE_EXISTING_PAPER = False
# Keep this empty: logfile provenance, rather than a manual parameter list,
# determines which mission changes are included in the report.
IGNORED_MISSION_PARAMETERS = set()
# When enabled, a mission change must also be confirmed by a raw logfile
# mission-configuration block containing the parameter and new value.
REQUIRE_MISSION_LOG_EVIDENCE = True
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

parser = argparse.ArgumentParser(description='Build the Navis mission changes paper.')
parser.add_argument('data_root', nargs='?', help='Folder containing float .msg files.')
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
    """Create the CSVs and figures consumed by this report from .msg snapshots."""
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
            'Set MISSION_DATA_ROOT to the folder containing the float .msg files.'
        )

    print(f'[analysis] Searching for .msg files under {data_root}...', flush=True)
    snapshots = defaultdict(dict)
    prf_id_re = re.compile(r'\bPrfId\s*[:=]?\s*(\d+)\b', re.I)
    profile_re = re.compile(r'\bProfile\s*[:.]?\s*(\d+)\b', re.I)
    parameter_names = '|'.join(re.escape(name) for name in MISSION_PARAMETER_ALIASES)
    value_re = re.compile(
        rf'\b({parameter_names})\s*(?:\(\s*([^)]*)\)|(?::|=)\s*([^\s,;]+)|\s+(-?\d+(?:\.\d+)?))',
        re.I,
    )
    print('[analysis] Counting input files (this may take a moment)...', flush=True)
    message_files = list(data_root.rglob('*.msg'))
    total_files = len(message_files)
    print(f'[analysis] Found {total_files:,} .msg files. Starting scan...', flush=True)
    scanned = 0
    parsed = 0
    next_report = 0
    def parse_message_file(message_file):
        try:
            text = message_file.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            return None
        float_match = re.search(r'(?<!\d)(\d{3,5})(?!\d)', str(message_file.parent))
        if not float_match:
            return None
        float_id = float_match.group(1)
        # Some exports put the profile number in the filename; prefer that
        # when available because message headers can repeat the float number.
        # PrfId and Profile headers are fallbacks.
        prf_match = prf_id_re.search(text)
        profile_match = profile_re.search(text)
        filename_numbers = [int(value) for value in re.findall(r'(?<!\d)(\d{1,5})(?!\d)', message_file.stem)]
        filename_profiles = [value for value in filename_numbers if str(value) != float_id]
        if filename_profiles:
            profile = filename_profiles[-1]
        elif prf_match:
            profile = int(prf_match.group(1))
        elif profile_match:
            profile = int(profile_match.group(1))
        else:
            return None
        values = {}
        for key, call_value, separated_value, numeric_value in value_re.findall(text):
            value = call_value or separated_value or numeric_value or 'present'
            values[MISSION_PARAMETER_ALIASES[key.lower()]] = value.strip()
        return (message_file, float_id, profile, values) if values else None

    worker_count = min(32, max(4, (os.cpu_count() or 4) * 4))
    print(f'[analysis] Reading files with {worker_count} workers...', flush=True)
    parsed_results = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [executor.submit(parse_message_file, message_file) for message_file in message_files]
        for future in as_completed(futures):
            scanned += 1
            result = future.result()
            if result is not None:
                parsed_results.append(result)
                parsed += 1
            progress = scanned * 100 // max(total_files, 1)
            if progress >= next_report or scanned == total_files:
                print(f'[analysis] Scanned {scanned:,}/{total_files:,} files ({progress}%); parsed {parsed:,} snapshots...', flush=True)
                next_report = progress + 5

    # Sort before assigning so duplicate profile files resolve consistently.
    for message_file, float_id, profile, values in sorted(parsed_results, key=lambda item: str(item[0])):
        snapshots[float_id][profile] = values
    print(f'[analysis] Finished scan: {scanned:,} files, {parsed:,} snapshots, {len(snapshots):,} floats.', flush=True)
    if not snapshots:
        raise RuntimeError(f'No parseable .msg mission snapshots found below {data_root}.')

    mission_log_evidence = set()
    explicit_command_evidence = set()
    if REQUIRE_MISSION_LOG_EVIDENCE:
        log_roots = {message_file.parent for message_file, _, _, _ in parsed_results}
        print(f'[analysis] Searching .log files in {len(log_roots):,} snapshot folders for outbound mission commands...', flush=True)
        mission_log_evidence, explicit_command_evidence = _collect_mission_log_evidence(log_roots)
        print(f'[analysis] Found {len(mission_log_evidence):,} parameter/value pairs in mission-change logs.', flush=True)

    events = []
    summaries = []
    changed_counts = defaultdict(int)
    print('[analysis] Comparing profile snapshots...', flush=True)
    sorted_snapshots = sorted(snapshots.items(), key=lambda item: int(item[0]))
    total_floats = len(sorted_snapshots)
    for float_index, (float_id, profiles) in enumerate(sorted_snapshots, 1):
        profile_ids = sorted(profiles)
        changed_profiles = set()
        previous = None
        for profile in profile_ids:
            current = profiles[profile]
            if previous is not None:
                for parameter in sorted(set(previous) | set(current)):
                    old, new = previous.get(parameter), current.get(parameter)
                    if old == new or old is None or new is None:
                        continue
                    evidence_key = (float_id, parameter, _normalized_log_value(new))
                    if REQUIRE_MISSION_LOG_EVIDENCE and evidence_key not in mission_log_evidence:
                        continue
                    events.append({'FloatId': float_id, 'ProfileId': str(profile), 'Parameter': parameter, 'OldValue': old, 'NewValue': new})
                    changed_counts[float_id] += 1
                    changed_profiles.add(profile)
            previous = current
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
<p class="subtitle">Profile-by-profile analysis of Argus BGC mission message files</p>
<p class="footer">Last updated: {html.escape(generated_at)}</p>

<h2>Methods and interpretation</h2>
<p>Each parseable message file was treated as a profile snapshot. Within each float, snapshots were ordered by profile number and compared with the preceding snapshot. A reported change means that a parameter value differed from the previous profile and was supported by mission-configuration logfile evidence.</p>
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
