"""Tests for the R2 deploy helpers (Q3/Q5).

The helper must be safe by default: no `--apply`, no environment variables, no
upload. These tests pin that behaviour and the CORS policy the PMTiles format
needs.
"""

from __future__ import annotations

import pytest

from pipeline import deploy_r2


def test_plan_reports_both_targets():
    plan = deploy_r2.plan()
    assert plan["site_bucket_env"] == deploy_r2.SITE_BUCKET_ENV
    assert plan["tile_bucket_env"] == deploy_r2.TILE_BUCKET_ENV
    assert "site" in plan and "tiles" in plan
    assert plan["site"]["files"] >= 0
    assert plan["tiles"]["files"] >= 0


def test_cors_exposes_the_range_headers_pmtiles_needs():
    """PMTiles reads byte ranges, so these headers are not optional."""
    rule = deploy_r2.CORS_POLICY["rules"][0]
    exposed = set(rule["exposeHeaders"])
    assert {"Content-Range", "Content-Length", "Accept-Ranges"} <= exposed
    assert "Range" in rule["allowed"]["headers"]
    assert "GET" in rule["allowed"]["methods"]


def test_cors_does_not_allow_wildcard_origin_by_default():
    origins = deploy_r2.CORS_POLICY["rules"][0]["allowed"]["origins"]
    assert "*" not in origins
    assert all("YOUR-SITE-DOMAIN" in origin for origin in origins)


def test_upload_refuses_without_buckets(monkeypatch):
    """No --apply means dry run; but even --apply without env vars must refuse."""
    monkeypatch.delenv(deploy_r2.SITE_BUCKET_ENV, raising=False)
    monkeypatch.delenv(deploy_r2.TILE_BUCKET_ENV, raising=False)
    assert deploy_r2.upload(dry_run=False) == 2


def test_upload_dry_run_does_not_require_buckets(monkeypatch, capsys):
    monkeypatch.delenv(deploy_r2.SITE_BUCKET_ENV, raising=False)
    monkeypatch.delenv(deploy_r2.TILE_BUCKET_ENV, raising=False)
    code = deploy_r2.upload(dry_run=True)
    # Either 0 (planned) or 2 (dist missing); never a crash.
    assert code in (0, 2)
    if code == 0:
        assert "DRY-RUN" in capsys.readouterr().out


def test_cors_and_rollback_are_dry_run_by_default(capsys):
    assert deploy_r2.cors(dry_run=True) == 0
    assert "DRY-RUN" in capsys.readouterr().out
    assert deploy_r2.rollback(dry_run=True) == 0
    assert "DRY-RUN" in capsys.readouterr().out


def test_wrangler_prefix_is_a_list():
    """Regression: passing the binary name where a command list was expected
    produced `npx r2 object put`, which is not a wrangler invocation."""
    prefix = deploy_r2._wrangler()
    if prefix is None:
        pytest.skip("wrangler/npx not installed")
    assert isinstance(prefix, list)
    assert prefix[-1] in ("wrangler",) or prefix[0].endswith("wrangler")
