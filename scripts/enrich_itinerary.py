"""
One-time script: enrich itinerary.json with place_id, coordinates, and travel data.
Reads itinerary.json, calls directions.py, writes back enriched data.
Also auto-selects recommended_mode for each travel segment based on distance.

Usage: direnv exec $REPO python3 scripts/enrich_itinerary.py trips/vietnam-2026-05/data/itinerary.json
"""
import json
import subprocess
import sys
import pathlib


# Distance-based mode selection thresholds (km)
WALK_MAX_KM = 1.0       # <= 1 km: recommend walking
SCOOTER_MAX_KM = 5.0    # 1-5 km: recommend bicycling (scooter proxy)
                         # > 5 km: recommend driving (Grab/taxi)

# Google Directions API has no "scooter" mode. We use "bicycling" as a proxy:
# - Similar routing to scooter (smaller roads, urban paths)
# - But bicycle speed (~12 km/h) is ~2x slower than scooter (~25 km/h)
# - We apply SCOOTER_SPEED_FACTOR to correct bicycling durations
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
    itinerary = json.loads(itinerary_path.read_text())

    # Parse available_modes from CLI arg or itinerary metadata
    # Usage: python3 enrich_itinerary.py itinerary.json [walking,driving]
    available_modes = None
    if len(sys.argv) > 2:
        available_modes = set(sys.argv[2].split(","))
    elif "available_modes" in itinerary:
        available_modes = set(itinerary["available_modes"])

    if available_modes:
        print(f"Available modes: {available_modes}", file=sys.stderr)

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

    for day_idx, day in enumerate(itinerary["days"]):
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
        for i in range(len(day["places"]) - 1):
            all_routes.append({
                "from": place_index_map[(day_idx, i)],
                "to": place_index_map[(day_idx, i + 1)],
            })

    n_pre = len(pre_resolved)
    n_new = len(all_places) - n_pre
    print(f"Places: {n_pre} pre-resolved (have lat/lng), {n_new} need API resolution", file=sys.stderr)

    # Call directions.py
    input_data = {"places": all_places, "routes": all_routes}
    result = subprocess.run(
        [sys.executable, "scripts/directions.py"],
        input=json.dumps(input_data),
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"directions.py failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    resolved = json.loads(result.stdout)

    # Write back to itinerary — skip pre-resolved entries
    global_idx = 0
    for day in itinerary["days"]:
        for place in day["places"]:
            if global_idx not in pre_resolved:
                r = resolved["places"][global_idx]
                place["place_id"] = r.get("place_id")
                place["lat"] = r.get("lat")
                place["lng"] = r.get("lng")
                if r.get("display_name"):
                    place["display_name"] = r["display_name"]
            global_idx += 1

    # Map routes back to days
    route_idx = 0
    for day in itinerary["days"]:
        if "travel" not in day:
            day["travel"] = []

        for i in range(len(day["places"]) - 1):
            route = resolved["routes"][route_idx]
            # Find or create travel entry for this pair
            modes = route.get("modes", {})
            recommended = select_recommended_mode(modes, available_modes)
            existing = next((t for t in day["travel"] if t["from"] == i and t["to"] == i + 1), None)
            if existing:
                existing["modes"] = modes
                existing["source"] = route.get("source", "api")
                existing["recommended_mode"] = recommended
            else:
                day["travel"].append({
                    "from": i,
                    "to": i + 1,
                    "modes": modes,
                    "source": route.get("source", "api"),
                    "recommended_mode": recommended,
                })
            route_idx += 1

    # Apply scooter speed correction to bicycling durations
    for day in itinerary["days"]:
        for t in day.get("travel", []):
            if "bicycling" in t.get("modes", {}):
                raw = t["modes"]["bicycling"].get("duration_min", 0)
                t["modes"]["bicycling"]["duration_min"] = round(raw * SCOOTER_SPEED_FACTOR, 1)

    itinerary_path.write_text(json.dumps(itinerary, ensure_ascii=False, indent=2) + "\n")

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
