#!/usr/bin/env python3
"""Leave out requirements whose environment markers don't apply to the runtime.

flatpak-pip-generator doesn't evaluate markers on the listed requirements, so
a line like `tomli; python_version < "3.11"` would become a module without
sources. Markers are evaluated for the runtime's Python on Linux, once for
every architecture CI builds. A requirement needed on only some of them can't
be expressed in the generated module and stops the script. The markers of
the requirements that stay are removed: pip would evaluate them again for
the machine it runs on, which may not be one of the target architectures.

Usage: filter-requirements.py PYTHON_VERSION SOURCE TARGET [FLATHUB_JSON]
"""

import json
import re
import sys
from pathlib import Path

from packaging.requirements import Requirement

ARCHES = ["x86_64", "aarch64"]


def target_arches(flathub_json):
    path = Path(flathub_json) if flathub_json else None
    config = json.loads(path.read_text()) if path and path.exists() else {}
    only = config.get("only-arches")
    skip = config.get("skip-arches", [])
    arches = [a for a in ARCHES if (only is None or a in only) and a not in skip]
    if not arches:
        sys.exit(f"{flathub_json} leaves no architecture to build")
    return arches


def environment(python_version, arch):
    return {
        "implementation_name": "cpython",
        "implementation_version": python_version,
        "os_name": "posix",
        "platform_machine": arch,
        "platform_python_implementation": "CPython",
        "platform_release": "",
        "platform_system": "Linux",
        "platform_version": "",
        "python_full_version": python_version,
        "python_version": ".".join(python_version.split(".")[:2]),
        "sys_platform": "linux",
        "extra": "",
    }


def main():
    if len(sys.argv) not in (4, 5):
        sys.exit(__doc__.strip().splitlines()[-1])
    python_version, source, target = sys.argv[1:4]
    arches = target_arches(sys.argv[4] if len(sys.argv) == 5 else None)
    kept = []
    for line in open(source):
        text = line.split("#", 1)[0].strip()
        if text and not text.startswith("-"):
            requirement = Requirement(text)
            marker = requirement.marker
            if marker:
                if re.search(r"\bplatform_(release|version)\b", str(marker)):
                    sys.exit(f"{text}: platform_release and platform_version depend "
                             "on the user's kernel and can't be decided at build time")
                applies = {arch: marker.evaluate(environment(python_version, arch))
                           for arch in arches}
                if not any(applies.values()):
                    print(f"Leaving out {text}: not needed on Python {python_version} "
                          f"for {', '.join(arches)}")
                    continue
                if not all(applies.values()):
                    needed = [arch for arch, value in applies.items() if value]
                    sys.exit(f"{text} is only needed on {', '.join(needed)}. Leave it out "
                             "of requirements.txt and add it as a module with only-arches.")
                requirement.marker = None
                line = f"{requirement}\n"
        kept.append(line)
    open(target, "w").writelines(kept)


if __name__ == "__main__":
    main()
