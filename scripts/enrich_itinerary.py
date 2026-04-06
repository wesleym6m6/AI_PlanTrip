"""
One-time script: enrich itinerary.json with place_id, coordinates, and travel data.
Reads itinerary.json, calls directions.py (Routes API), writes back enriched data.
Also auto-selects recommended_mode for each travel segment based on distance.

Usage:
  direnv exec $REPO python3 scripts/enrich_itinerary.py <itinerary.json> [modes] [timezone]

  modes:    comma-separated available modes (e.g. walking,transit,driving)
  timezone: UTC offset for departure_time (e.g. +09:00 for Japan, +08:00 for Taiwan)
            When provided, transit queries use actual scheduled departure times
            from the itinerary (day.date + place.time + timezone).
            Without timezone, transit queries use no departure_time (less accurate).

Examples:
  # Japan (no transit available, so no timezone needed):
  direnv exec $REPO python3 scripts/enrich_itinerary.py trips/japan-2026-05/data/itinerary.json walking,driving

  # Taiwan (transit available, pass timezone for accurate schedules):
  direnv exec $REPO python3 scripts/enrich_itinerary.py trips/tainan-2026-04/data/itinerary.json walking,transit,driving +08:00

  # Vietnam (transit + two_wheeler):
  direnv exec $REPO python3 scripts/enrich_itinerary.py trips/vietnam-2026-05/data/itinerary.json walking,transit,two_wheeler +07:00
"""
import json
import sys
import pathlib
import re

# Direct import instead of subprocess — avoids JSON serialization overhead
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from directions import resolve_places_batched, compute_routes_batched


# Distance-based mode selection thresholds (km)
WALK_MAX_KM = 1.0       # <= 1 km: recommend walking
SCOOTER_MAX_KM = 5.0    # 1-5 km: recommend bicycling (scooter proxy)
                         # > 5 km: recommend driving (Grab/taxi)

# Routes API supports TWO_WHEELER mode for real scooter routing (Enterprise tier).
# For backward compatibility, "bicycling" is still available as a cheaper proxy:
# - bicycling speed (~12 km/h) is ~2x slower than scooter (~25 km/h)
# - SCOOTER_SPEED_FACTOR corrects bicycling durations when used as scooter proxy
# To use real scooter routing, add "two_wheeler" to available_modes instead.
SCOOTER_SPEED_FACTOR = 0.5  # bicycling_time * 0.5 ≈ scooter_time


def select_recommended_mode(modes, available_modes=None):
    """Select the best transport mode based on distance and availability.

    available_modes: set/list of modes the user can actually use, e.g.
      {"walking", "driving"}           — no scooter, no transit
      {"walking", "bicycling"}         — scooter + walking only
      {"walking", "driving", "transit"} — public transport city
      None                             — all modes available (default)

    Returns one of: 'walking', 'bicycling', 'driving', 'transit', or None.
    """
    if not modes:
        return None

    # Filter to available modes
    if available_modes is not None:
        avail = set(available_modes)
    else:
        avail = {"walking", "bicycling", "driving", "transit"}

    # Only consider modes that are both available AND have API data
    usable = {m for m in avail if m in modes}
    if not usable:
        return None

    # Get driving distance as the reference (most reliable for distance)
    distance_km = None
    for m in ["driving", "walking", "bicycling"]:
        if m in modes and modes[m].get("distance_km"):
            distance_km = modes[m]["distance_km"]
            break

    if distance_km is None:
        # No distance data, pick first available
        for m in ["driving", "bicycling", "transit", "walking"]:
            if m in usable:
                return m
        return None

    if distance_km <= WALK_MAX_KM and "walking" in usable:
        return "walking"
    if distance_km <= SCOOTER_MAX_KM and "bicycling" in usable:
        return "bicycling"
    if "driving" in usable:
        return "driving"
    if "transit" in usable:
        return "transit"
    if "bicycling" in usable:
        return "bicycling"
    if "walking" in usable:
        return "walking"
    return None


def main():
    itinerary_path = pathlib.Path(sys.argv[1])
    itinerary = json.loads(itinerary_path.read_text(encoding="utf-8"))

    # Parse CLI args: modes, timezone, --days filter
    # Usage: python3 enrich_itinerary.py itinerary.json [walking,driving] [+09:00] [--days 1,3]
    available_modes = None
    utc_offset = None
    days_filter = None  # None = all days, set() = specific days

    i = 2
    while i < len(sys.argv):
        arg = sys.argv[i]
        if arg == "--days" and i + 1 < len(sys.argv):
            days_filter = set(int(d) for d in sys.argv[i + 1].split(","))
            i += 2
            continue
        elif re.match(r'^[+-]\d{2}:\d{2}$', arg):
            utc_offset = arg
        elif ',' in arg or arg in ("walking", "driving", "transit", "bicycling", "two_wheeler"):
            available_modes = set(arg.split(","))
        i += 1

    if available_modes is None and "available_modes" in itinerary:
        available_modes = set(itinerary["available_modes"])

    if available_modes:
        print(f"Available modes: {available_modes}", file=sys.stderr)
    if utc_offset:
        print(f"Timezone offset: {utc_offset} (transit will use scheduled departure times)", file=sys.stderr)
    elif available_modes and "transit" in available_modes:
        print("WARNING: transit mode without timezone — queries will not use scheduled departure times", file=sys.stderr)
    if days_filter:
        print(f"Incremental mode: only enriching days {sorted(days_filter)}", file=sys.stderr)

    # Collect all places and routes.
    # Places that already have lat/lng are "pre-resolved" — they skip API
    # resolution and their place_id/lat/lng/display_name are preserved.
    # This prevents manual cache entries (Google Maps 未收錄) from being
    # overwritten by a wrong API result, and avoids 400 errors from entries
    # with no maps_query (e.g. transport waypoints).
    all_places = []
    all_routes = []
    pre_resolved = set()  # global indices of pre-resolved places
    place_index_map = {}  # (day_idx, place_idx) -> global index

    skipped_days = set()  # day indices to skip (preserve existing travel data)
    for day_idx, day in enumerate(itinerary["days"]):
        if days_filter and day["day"] not in days_filter:
            skipped_days.add(day_idx)
            continue
        for place_idx, place in enumerate(day["places"]):
            global_idx = len(all_places)
            place_index_map[(day_idx, place_idx)] = global_idx

            has_coords = place.get("lat") and place.get("lng")
            if has_coords:
                # Pre-resolved: pass lat/lng directly so directions.py
                # skips API resolution and uses these for route computation.
                pre_resolved.add(global_idx)
                all_places.append({
                    "maps_query": place.get("maps_query", ""),
                    "lat": place["lat"],
                    "lng": place["lng"],
                    "place_id": place.get("place_id"),
                    "display_name": place.get("display_name"),
                })
            else:
                all_places.append({"maps_query": place.get("maps_query", "")})

        # Routes between consecutive places within a day
        day_date = day.get("date")  # e.g. "2026-05-18"
        for i in range(len(day["places"]) - 1):
            route_entry = {
                "from": place_index_map[(day_idx, i)],
                "to": place_index_map[(day_idx, i + 1)],
            }
            # Build departure_time from the "from" place's scheduled time.
            # This tells the Routes API: "I'm leaving place A at this time,
            # what transit should I take to reach place B?"
            if utc_offset and day_date:
                from_time = day["places"][i].get("time")  # e.g. "09:30"
                if from_time:
                    route_entry["departure_time"] = f"{day_date}T{from_time}:00{utc_offset}"
            all_routes.append(route_entry)

    n_pre = len(pre_resolved)
    n_new = len(all_places) - n_pre
    print(f"Places: {n_pre} pre-resolved (have lat/lng), {n_new} need API resolution", file=sys.stderr)

    # Resolve places that need API lookup (pre-resolved ones are kept as-is)
    needs_resolution = [(i, p["maps_query"]) for i, p in enumerate(all_places) if i not in pre_resolved]
    if needs_resolution:
        queries = [q for _, q in needs_resolution]
        resolved_places = resolve_places_batched(queries)
        for (idx, _), result in zip(needs_resolution, resolved_places):
            all_places[idx] = result

    # Build route specs and compute routes via Routes API
    route_specs = []
    for r in all_routes:
        fr, to = r["from"], r["to"]
        origin, dest = all_places[fr], all_places[to]
        dep_time = r.get("departure_time")
        if origin.get("lat") and dest.get("lat"):
            spec = (fr, to, origin["lat"], origin["lng"], dest["lat"], dest["lng"])
            if dep_time:
                spec = spec + (dep_time,)
            route_specs.append(spec)
        else:
            route_specs.append(None)

    avail_modes = sorted(available_modes) if available_modes else None
    valid_specs = [(i, s) for i, s in enumerate(route_specs) if s is not None]
    if valid_specs:
        route_results = compute_routes_batched([s for _, s in valid_specs], available_modes=avail_modes)
        computed_routes = [None] * len(route_specs)
        for result, (orig_idx, _) in zip(route_results, valid_specs):
            computed_routes[orig_idx] = result
        for i, spec in enumerate(route_specs):
            if spec is None:
                fr, to = all_routes[i]["from"], all_routes[i]["to"]
                computed_routes[i] = {"from": fr, "to": to, "modes": {}, "source": "unavailable"}
    else:
        computed_routes = []

    resolved = {"places": all_places, "routes": computed_routes}

    # Write back to itinerary — skip pre-resolved entries and skipped days
    global_idx = 0
    for day_idx, day in enumerate(itinerary["days"]):
        if day_idx in skipped_days:
            continue
        for place in day["places"]:
            if global_idx not in pre_resolved:
                r = resolved["places"][global_idx]
                place["place_id"] = r.get("place_id")
                place["lat"] = r.get("lat")
                place["lng"] = r.get("lng")
                if r.get("display_name"):
                    place["display_name"] = r["display_name"]
            global_idx += 1

    # Map routes back to days — skip days not in filter
    route_idx = 0
    for day_idx, day in enumerate(itinerary["days"]):
        if day_idx in skipped_days:
            continue
        if "travel" not in day:
            day["travel"] = []

        for i in range(len(day["places"]) - 1):
            route = resolved["routes"][route_idx]
            # Find or create travel entry for this pair
            modes = route.get("modes", {})
            recommended = select_recommended_mode(modes, available_modes)

            # Build travel entry with core fields
            travel_data = {
                "from": i,
                "to": i + 1,
                "modes": {m: {"duration_min": v["duration_min"], "distance_km": v["distance_km"]}
                          for m, v in modes.items()},
                "source": route.get("source", "api"),
                "recommended_mode": recommended,
            }

            # Store full transit leg details (stops, lines, schedules) when available.
            # These are stored per-mode alongside duration/distance.
            for m, v in modes.items():
                if "legs" in v:
                    # Extract transit steps only (WALK steps are noise for storage)
                    transit_steps = []
                    for leg in v["legs"]:
                        for step in leg.get("steps", []):
                            if step.get("travelMode") == "TRANSIT" and "transitDetails" in step:
                                transit_steps.append(step["transitDetails"])
                    if transit_steps:
                        travel_data["modes"][m]["transit_steps"] = transit_steps

            existing = next((t for t in day["travel"] if t["from"] == i and t["to"] == i + 1), None)
            if existing:
                existing.update(travel_data)
            else:
                day["travel"].append(travel_data)
            route_idx += 1

    # Apply scooter speed correction to bicycling durations
    for day in itinerary["days"]:
        for t in day.get("travel", []):
            if "bicycling" in t.get("modes", {}):
                raw = t["modes"]["bicycling"].get("duration_min", 0)
                t["modes"]["bicycling"]["duration_min"] = round(raw * SCOOTER_SPEED_FACTOR, 1)

    # Safe write: backup → temp → atomic rename
    backup_path = itinerary_path.with_suffix(".json.bak")
    import shutil
    shutil.copy2(itinerary_path, backup_path)

    tmp_path = itinerary_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(itinerary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(itinerary_path)
    print(f"Backup: {backup_path}", file=sys.stderr)

    # Print summary
    for day in itinerary["days"]:
        for t in day.get("travel", []):
            rm = t.get("recommended_mode")
            m = t.get("modes", {}).get(rm, {}) if rm else {}
            dur = m.get("duration_min", "?")
            dist = m.get("distance_km", "?")
            print(f"  Day {day['day']} [{t['from']}→{t['to']}] {rm}: {dur} min, {dist} km")
    print(f"Enriched {global_idx} places and {route_idx} routes.")


if __name__ == "__main__":
    main()
