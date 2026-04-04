"""Tests for directions.py — requires GOOGLE_MAPS_API_KEY env var."""
import os
import json
import subprocess
import sys


def run_directions(input_data):
    """Run directions.py with JSON input via stdin."""
    result = subprocess.run(
        [sys.executable, "scripts/directions.py"],
        input=json.dumps(input_data),
        capture_output=True, text=True,
        env={**os.environ}
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    return json.loads(result.stdout)


def test_resolve_single_place():
    """Places API should return place_id and coordinates."""
    data = {
        "places": [
            {"maps_query": "Tan Son Nhat International Airport, Ho Chi Minh City, Vietnam"}
        ]
    }
    result = run_directions(data)
    place = result["places"][0]
    assert place["place_id"].startswith("ChIJ"), f"Bad place_id: {place['place_id']}"
    assert 10.0 < place["lat"] < 11.0, f"Lat out of range: {place['lat']}"
    assert 106.0 < place["lng"] < 107.0, f"Lng out of range: {place['lng']}"


def test_directions_between_two_places():
    """Directions API should return duration and distance for available modes."""
    data = {
        "places": [
            {"maps_query": "Tan Son Nhat International Airport, Ho Chi Minh City, Vietnam"},
            {"maps_query": "Avanti Hotel District 1, Ho Chi Minh City, Vietnam"}
        ],
        "routes": [{"from": 0, "to": 1}]
    }
    result = run_directions(data)
    route = result["routes"][0]
    assert "driving" in route["modes"], "Missing driving mode"
    assert route["modes"]["driving"]["duration_min"] > 0
    assert route["modes"]["driving"]["distance_km"] > 0


def test_no_api_key_fallback():
    """Without API key, should return empty results with source=unavailable."""
    data = {
        "places": [
            {"maps_query": "Some Place, Somewhere"}
        ]
    }
    env = {k: v for k, v in os.environ.items() if k != "GOOGLE_MAPS_API_KEY"}
    result = subprocess.run(
        [sys.executable, "scripts/directions.py"],
        input=json.dumps(data),
        capture_output=True, text=True,
        env=env
    )
    assert result.returncode == 0
    output = json.loads(result.stdout)
    place = output["places"][0]
    assert place.get("place_id") is None
    assert place.get("source") == "unavailable"


if __name__ == "__main__":
    test_resolve_single_place()
    print("PASS: test_resolve_single_place")
    test_directions_between_two_places()
    print("PASS: test_directions_between_two_places")
    test_no_api_key_fallback()
    print("PASS: test_no_api_key_fallback")
    print("\nAll tests passed.")
