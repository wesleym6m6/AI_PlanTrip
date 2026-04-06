"""
Scan trips/ directory and generate root index.html.

Usage: python3 scripts/build_index.py
Output: index.html (root)
"""
import json
import pathlib
from jinja2 import Environment, FileSystemLoader

ROOT = pathlib.Path(__file__).parent.parent
TEMPLATE_DIR = ROOT / "template"
TRIPS_DIR = ROOT / "trips"


def main():
    trips = []
    for trip_json in sorted(TRIPS_DIR.glob("*/data/trip.json")):
        data = json.loads(trip_json.read_text(encoding="utf-8"))
        if data.get("archived"):
            continue
        trips.append(data)

    # Sort by date_range (lexicographic works for YYYY-MM-DD format)
    trips.sort(key=lambda t: t.get("date_range", ""), reverse=True)

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("index.html")
    html = template.render(trips=trips)

    output = ROOT / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"Built index with {len(trips)} trip(s): {output}")


if __name__ == "__main__":
    main()
