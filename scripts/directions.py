"""
Resolve place IDs and compute routes between places using Google Maps APIs.

Input (stdin JSON):
{
  "places": [{"maps_query": "Place Name, City, Country"}, ...],
  "routes": [{"from": 0, "to": 1}, ...]  // optional, indices into places
}

Output (stdout JSON):
{
  "places": [{"maps_query": ..., "place_id": ..., "lat": ..., "lng": ..., "source": "api"}, ...],
  "routes": [{"from": 0, "to": 1, "modes": {"driving": {"duration_min": N, "distance_km": N}, ...}, "source": "api"}, ...]
}

API Quota (project: maps-directions-202604, queried 2026-04-04):
  - Places API (searchText):   600 QPM = 10 QPS  | 75,000/day
  - Directions API (legacy):  3000 QPM = 50 QPS  | unlimited/day
  Quotas are per-project. Check current values:
    gcloud auth print-access-token | xargs -I{} curl -s \
      "https://serviceusage.googleapis.com/v1beta1/projects/maps-directions-202604/services/places.googleapis.com/consumerQuotaMetrics" \
      -H "Authorization: Bearer {}"

Parallelism strategy:
  - Places:     batch 8 concurrent, 1.0s gap between batches (target ~8 QPS, under 10 QPS limit)
  - Directions:  batch 15 concurrent, 1.0s gap between batches (target ~15 QPS, under 50 QPS limit)
  Each individual request within a batch fires simultaneously; the batch gap ensures
  we stay under the per-minute quota. Do NOT raise batch sizes without verifying quota.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

API_KEY = os.environ.get("GOOGLE_MAPS_API_KEY", "")
PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"
TRANSPORT_MODES = ["driving", "walking", "transit", "bicycling"]

# --- Quota-derived constants (see docstring for source) ---
PLACES_BATCH_SIZE = 8       # 10 QPS limit, leave 20% headroom
PLACES_BATCH_DELAY = 1.0    # seconds between batches
DIRECTIONS_BATCH_SIZE = 15  # 50 QPS limit, leave 70% headroom
DIRECTIONS_BATCH_DELAY = 1.0


DEFAULT_FIELD_MASK = "places.id,places.displayName,places.location"

FULL_FIELD_MASK = (
    "places.id,places.displayName,places.location,places.types,places.primaryType,"
    "places.primaryTypeDisplayName,places.nationalPhoneNumber,places.internationalPhoneNumber,"
    "places.formattedAddress,places.shortFormattedAddress,places.googleMapsUri,places.googleMapsLinks,"
    "places.websiteUri,places.rating,places.userRatingCount,places.priceLevel,places.priceRange,"
    "places.regularOpeningHours,places.currentOpeningHours,places.businessStatus,"
    "places.timeZone,places.utcOffsetMinutes,places.editorialSummary,places.generativeSummary,"
    "places.reviews,places.photos,places.paymentOptions,places.parkingOptions,"
    "places.accessibilityOptions,places.servesBreakfast,places.servesLunch,places.servesDinner,"
    "places.servesBeer,places.servesWine,places.servesBrunch,places.servesVegetarianFood,"
    "places.servesCocktails,places.servesCoffee,places.servesDessert,places.takeout,"
    "places.delivery,places.dineIn,places.reservable,places.outdoorSeating,places.liveMusic,"
    "places.menuForChildren,places.goodForChildren,places.goodForGroups,places.allowsDogs,"
    "places.restroom"
)


def resolve_place(query, max_retries=3, field_mask=None):
    """Resolve a text query to place_id + coordinates via Places API (New).

    When field_mask is provided, returns raw API place data alongside maps_query.
    Default (field_mask=None) returns the simplified dict for backward compat.
    """
    if not API_KEY:
        return {"maps_query": query, "place_id": None, "lat": None, "lng": None, "source": "unavailable"}

    mask = field_mask or DEFAULT_FIELD_MASK

    for attempt in range(max_retries):
        resp = requests.post(
            PLACES_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": API_KEY,
                "X-Goog-FieldMask": mask,
            },
            json={"textQuery": query},
        )
        if resp.status_code in (429, 403) and attempt < max_retries - 1:
            wait = 2 ** (attempt + 1)
            print(f"Rate limited on '{query}', retrying in {wait}s...", file=sys.stderr)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        break

    data = resp.json()
    candidates = data.get("places", [])
    if not candidates:
        print(f"WARNING: No results for '{query}'", file=sys.stderr)
        return {"maps_query": query, "place_id": None, "lat": None, "lng": None, "source": "not_found"}

    place = candidates[0]

    if field_mask:
        return {"maps_query": query, "raw": place}

    loc = place.get("location", {})
    return {
        "maps_query": query,
        "place_id": place.get("id"),
        "display_name": place.get("displayName", {}).get("text"),
        "lat": loc.get("latitude"),
        "lng": loc.get("longitude"),
        "source": "api",
    }


def get_single_direction(origin_lat, origin_lng, dest_lat, dest_lng, mode, max_retries=3):
    """Get directions for a single transport mode between two coordinates."""
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                DIRECTIONS_URL,
                params={
                    "origin": f"{origin_lat},{origin_lng}",
                    "destination": f"{dest_lat},{dest_lng}",
                    "mode": mode,
                    "key": API_KEY,
                },
            )
            if resp.status_code in (429, 403) and attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"Rate limited on directions {mode}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("status") == "OK" and data.get("routes"):
                leg = data["routes"][0]["legs"][0]
                return mode, {
                    "duration_min": round(leg["duration"]["value"] / 60, 1),
                    "distance_km": round(leg["distance"]["value"] / 1000, 1),
                }
            return mode, None
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue
            print(f"WARNING: Directions API error for mode={mode}: {e}", file=sys.stderr)
            return mode, None
    return mode, None


def get_directions(origin_lat, origin_lng, dest_lat, dest_lng):
    """Get directions for all transport modes between two coordinates (parallel)."""
    if not API_KEY:
        return {"modes": {}, "source": "unavailable"}

    modes = {}
    with ThreadPoolExecutor(max_workers=len(TRANSPORT_MODES)) as pool:
        futures = {
            pool.submit(get_single_direction, origin_lat, origin_lng, dest_lat, dest_lng, mode): mode
            for mode in TRANSPORT_MODES
        }
        for f in as_completed(futures):
            mode, result = f.result()
            if result:
                modes[mode] = result

    return {"modes": modes, "source": "api"}


def batched(items, batch_size):
    """Yield successive batches from items list."""
    for i in range(0, len(items), batch_size):
        yield items[i:i + batch_size]


def resolve_places_batched(queries, field_mask=None):
    """Resolve all place queries using batched parallelism."""
    results = [None] * len(queries)

    for batch_idx, batch in enumerate(batched(list(enumerate(queries)), PLACES_BATCH_SIZE)):
        if batch_idx > 0:
            time.sleep(PLACES_BATCH_DELAY)

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {
                pool.submit(resolve_place, query, 3, field_mask): idx
                for idx, query in batch
            }
            for f in as_completed(futures):
                idx = futures[f]
                results[idx] = f.result()

    return results


def compute_routes_batched(route_specs):
    """Compute all routes using batched parallelism.

    route_specs: list of (from_idx, to_idx, origin_lat, origin_lng, dest_lat, dest_lng)
    """
    results = [None] * len(route_specs)

    # Each route queries 3 modes in parallel internally, so effective requests
    # per route = 3. Batch size accounts for this: 15 batch × 3 modes = 45 QPS peak,
    # within the 50 QPS Directions API limit.
    for batch_idx, batch in enumerate(batched(list(enumerate(route_specs)), DIRECTIONS_BATCH_SIZE)):
        if batch_idx > 0:
            time.sleep(DIRECTIONS_BATCH_DELAY)

        with ThreadPoolExecutor(max_workers=len(batch)) as pool:
            futures = {}
            for list_idx, (fr, to, olat, olng, dlat, dlng) in batch:
                fut = pool.submit(get_directions, olat, olng, dlat, dlng)
                futures[fut] = (list_idx, fr, to)

            for f in as_completed(futures):
                list_idx, fr, to = futures[f]
                directions = f.result()
                results[list_idx] = {"from": fr, "to": to, **directions}

    return results


def main():
    t0 = time.time()
    input_data = json.load(sys.stdin)

    # Resolve places (batched parallel).
    # Places with "lat" and "lng" already set are pre-resolved — skip API call.
    raw_places = input_data.get("places", [])
    needs_resolution = []  # (index, query) pairs
    places = [None] * len(raw_places)

    for i, p in enumerate(raw_places):
        if p.get("lat") and p.get("lng"):
            # Pre-resolved: pass through as-is
            places[i] = {"maps_query": p.get("maps_query", ""), "lat": p["lat"], "lng": p["lng"],
                         "place_id": p.get("place_id"), "display_name": p.get("display_name")}
        else:
            needs_resolution.append((i, p["maps_query"]))

    t1 = time.time()
    if needs_resolution:
        queries = [q for _, q in needs_resolution]
        resolved = resolve_places_batched(queries)
        for (idx, _), result in zip(needs_resolution, resolved):
            places[idx] = result
    t2 = time.time()
    n_pre = len(raw_places) - len(needs_resolution)
    print(f"Places: {n_pre} pre-resolved, {len(needs_resolution)} API-resolved in {t2-t1:.1f}s", file=sys.stderr)

    # Compute routes (batched parallel)
    route_specs = []
    for r in input_data.get("routes", []):
        fr, to = r["from"], r["to"]
        origin, dest = places[fr], places[to]
        if origin.get("lat") and dest.get("lat"):
            route_specs.append((fr, to, origin["lat"], origin["lng"], dest["lat"], dest["lng"]))
        else:
            route_specs.append(None)

    valid_specs = [(i, s) for i, s in enumerate(route_specs) if s is not None]
    t3 = time.time()
    if valid_specs:
        route_results = compute_routes_batched([s for _, s in valid_specs])
        routes = [None] * len(route_specs)
        for result, (orig_idx, _) in zip(route_results, valid_specs):
            routes[orig_idx] = result
        # Fill unavailable routes
        for i, spec in enumerate(route_specs):
            if spec is None:
                fr, to = input_data["routes"][i]["from"], input_data["routes"][i]["to"]
                routes[i] = {"from": fr, "to": to, "modes": {}, "source": "unavailable"}
    else:
        routes = []
    t4 = time.time()
    print(f"Routes: {len(routes)} computed in {t4-t3:.1f}s", file=sys.stderr)
    print(f"Total: {t4-t0:.1f}s", file=sys.stderr)

    output = {"places": places, "routes": routes}
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()
