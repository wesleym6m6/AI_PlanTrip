"""Tests for render_trip.py."""
import json
import subprocess
import sys
import pathlib


def test_render_produces_valid_html():
    """render_trip.py should produce a complete HTML file."""
    result = subprocess.run(
        [sys.executable, "scripts/render_trip.py", "trips/vietnam-2026-05"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"Render failed: {result.stderr}"

    # Check output file exists
    output = pathlib.Path("trips/vietnam-2026-05/index.html")
    assert output.exists(), "index.html not created"

    html = output.read_text()
    assert "<!DOCTYPE html>" in html
    assert "</html>" in html
    # Check data was injected
    assert "place_id:" in html or "maps/search" in html, "No Google Maps links found"
    assert "Day 1" in html, "Day 1 not found"
    assert "localStorage" in html, "No localStorage code found"


def test_render_includes_all_days():
    """Output should contain all 10 days."""
    output = pathlib.Path("trips/vietnam-2026-05/index.html")
    html = output.read_text()
    for i in range(1, 11):
        assert f"Day {i}" in html, f"Day {i} missing from output"


if __name__ == "__main__":
    test_render_produces_valid_html()
    print("PASS: test_render_produces_valid_html")
    test_render_includes_all_days()
    print("PASS: test_render_includes_all_days")
    print("\nAll tests passed.")
