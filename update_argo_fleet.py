#!/usr/bin/env python3
"""Download the WHOI Argo feeds and build one merged KML snapshot."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


KML = "http://www.opengis.net/kml/2.2"
NS = f"{{{KML}}}"
ET.register_namespace("", KML)

SOURCES = [
    ("Core Argo fleet", "whoi_argo_op.kml", "https://argo.whoi.edu/argo/kml/whoi_argo_op.kml", "core_"),
    ("NAVIS active", "NAVIS_active.kml", "https://argo.whoi.edu/argo/kml/NAVIS_active.kml", "navis_active_"),
    ("NAVIS deactivated", "NAVIS_deactivated.kml", "https://argo.whoi.edu/argo/kml/NAVIS_deactivated.kml", "navis_deactivated_"),
    ("S2BGC all", "S2BGC_all.kml", "https://argo.whoi.edu/argo/kml/S2BGC_all.kml", "s2bgc_"),
]


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "argo-fleet-kml-updater/1.0"},
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def rewrite_style_urls(element: ET.Element, prefix: str) -> None:
    for style_url in element.iter(f"{NS}styleUrl"):
        if style_url.text and style_url.text.startswith("#"):
            style_url.text = f"#{prefix}{style_url.text[1:]}"


def merge(output_path: Path) -> int:
    with tempfile.TemporaryDirectory(prefix="argo_update_") as temporary_dir:
        temp_dir = Path(temporary_dir)
        root = ET.Element(f"{NS}kml")
        document = ET.SubElement(root, f"{NS}Document")
        ET.SubElement(document, f"{NS}name").text = "WHOI Argo Fleet (merged static snapshot)"
        ET.SubElement(document, f"{NS}description").text = (
            "Updated "
            + dt.datetime.now().astimezone().isoformat(timespec="seconds")
            + " from WHOI NetworkLink feeds."
        )

        placemark_count = 0
        for folder_name, filename, url, prefix in SOURCES:
            source_path = temp_dir / filename
            print(f"Downloading {filename}...")
            download(url, source_path)
            source_root = ET.parse(source_path).getroot()

            for style in source_root.iter():
                if style.tag not in (f"{NS}Style", f"{NS}StyleMap"):
                    continue
                clone = copy.deepcopy(style)
                if "id" in clone.attrib:
                    clone.attrib["id"] = prefix + clone.attrib["id"]
                rewrite_style_urls(clone, prefix)
                document.append(clone)

            folder = ET.SubElement(document, f"{NS}Folder")
            ET.SubElement(folder, f"{NS}name").text = folder_name
            ET.SubElement(folder, f"{NS}open").text = "1"
            for placemark in source_root.iter(f"{NS}Placemark"):
                clone = copy.deepcopy(placemark)
                if "id" in clone.attrib:
                    clone.attrib["id"] = prefix + clone.attrib["id"]
                rewrite_style_urls(clone, prefix)
                folder.append(clone)
                placemark_count += 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_output = output_path.with_suffix(output_path.suffix + ".tmp")
        ET.indent(root, space="  ")
        ET.ElementTree(root).write(
            temporary_output,
            encoding="utf-8",
            xml_declaration=True,
        )
        temporary_output.replace(output_path)
        return placemark_count


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(__file__).with_name("argo_fleet_merged.kml"),
        help="Output KML path (default: argo_fleet_merged.kml)",
    )
    args = parser.parse_args()
    count = merge(args.output)
    print(f"Updated {args.output} with {count} placemarks.")
    print("Google Earth Web still requires re-importing the refreshed KML.")


if __name__ == "__main__":
    main()
