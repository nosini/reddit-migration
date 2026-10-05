#!/usr/bin/env python3
"""Check the exported catalog consumed by software centers."""

import gzip
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def main():
    catalog_dir = Path(sys.argv[1])
    compressed = catalog_dir / "appstream.xml.gz"
    if compressed.exists():
        with gzip.open(compressed, "rb") as stream:
            catalog = ET.parse(stream)
    else:
        catalog = ET.parse(catalog_dir / "appstream.xml")

    components = {c.findtext("id"): c for c in catalog.findall("component")}
    app = components["eu.nosini.RedditMigration"]
    # GNOME Software hides console-application components from its app lists.
    assert app.get("type") == "desktop-application"
    assert app.findtext("launchable[@type='desktop-id']") == "eu.nosini.RedditMigration.desktop"
    assert app.find("icon") is not None, "App icon is missing from the catalog"
    assert app.findtext("bundle[@type='flatpak']") == "app/eu.nosini.RedditMigration/x86_64/stable"
    print("Published catalog entry for eu.nosini.RedditMigration passed.")


if __name__ == "__main__":
    main()
