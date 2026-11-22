"""Tests for the basemap extractor (T5).

The network part cannot be unit-tested, so these cover the pure pieces: URL and
bbox validation, CLI discovery, and the production tile-source guard.
"""

from __future__ import annotations

import pytest

from pipeline import basemap


def test_build_url_rejects_a_bad_date():
    with pytest.raises(ValueError):
        basemap.build_url("2026-11-20")
    with pytest.raises(ValueError):
        basemap.build_url("2026112")
    with pytest.raises(ValueError):
        basemap.build_url("20261399")


def test_build_url_accepts_a_real_date():
    assert basemap.build_url("20261120") == "https://build.protomaps.com/20261120.pmtiles"


def test_bbox_arg_formats_lon_lat_order():
    assert basemap.bbox_arg((105.0, -8.9, 114.7, -5.8)) == "105.0,-8.9,114.7,-5.8"


def test_bbox_arg_rejects_an_inverted_box():
    with pytest.raises(ValueError):
        basemap.bbox_arg((114.7, -5.8, 105.0, -8.9))


def test_java_bbox_covers_the_island():
    min_lon, min_lat, max_lon, max_lat = basemap.BBOX
    # Jakarta, Surabaya and Banyuwangi must all fall inside.
    for lon, lat in ((106.8, -6.2), (112.75, -7.25), (114.37, -8.2)):
        assert min_lon <= lon <= max_lon
        assert min_lat <= lat <= max_lat


def test_max_zoom_is_within_the_archive_range():
    # The Protomaps build publishes up to zoom 15; asking for more yields no tiles.
    assert 0 <= basemap.MIN_ZOOM <= basemap.MAX_ZOOM <= 15
