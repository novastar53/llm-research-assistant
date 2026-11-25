"""Milestone 3 tests: the read-only HTTP API (spec section 5.1)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import add_experiment, run_git
from fastapi.testclient import TestClient

from scientist.api import create_app
from scientist.errors import GitTimeoutError


@pytest.fixture
def client(diamond_repo: Path) -> TestClient:
    return TestClient(create_app(diamond_repo))


def test_graph_endpoint(client: TestClient) -> None:
    response = client.get("/api/graph")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    graph = response.json()
    assert {n["manifest"]["id"] for n in graph["nodes"]} == {
        "baseline",
        "double-q",
        "gaussian",
        "joint-study",
    }
    assert len(graph["edges"]) == 4


def test_experiment_endpoint(client: TestClient, diamond_repo: Path) -> None:
    response = client.get("/api/experiments/double-q")
    assert response.status_code == 200
    experiment = response.json()
    assert experiment["branch"] == "experiments/double-q"
    assert (
        experiment["commit"] == run_git(diamond_repo, "rev-parse", "experiments/double-q").strip()
    )
    assert experiment["manifest"]["title"] == "An experiment"


def test_experiment_not_found_and_malformed_id(client: TestClient) -> None:
    response = client.get("/api/experiments/ghost")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "not_found"

    response = client.get("/api/experiments/Bad%20ID")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_argument"


def test_files_endpoint(client: TestClient, diamond_repo: Path) -> None:
    response = client.get("/api/experiments/double-q/files")
    assert response.status_code == 200
    listing = response.json()
    tip = run_git(diamond_repo, "rev-parse", "experiments/double-q").strip()
    assert listing["commit"] == tip
    paths = {f["path"]: f["kind"] for f in listing["files"]}
    assert paths == {"README.md": "file", "experiment.json": "file"}


def test_files_endpoint_with_historical_commit(client: TestClient, diamond_repo: Path) -> None:
    tip = run_git(diamond_repo, "rev-parse", "experiments/baseline").strip()
    response = client.get(f"/api/experiments/baseline/files?commit={tip}")
    assert response.status_code == 200
    assert response.json()["commit"] == tip


def test_files_endpoint_rejects_invalid_commit(client: TestClient, diamond_repo: Path) -> None:
    other = run_git(diamond_repo, "rev-parse", "experiments/gaussian").strip()
    response = client.get(f"/api/experiments/double-q/files?commit={other}")
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_argument"

    response = client.get("/api/experiments/double-q/files?commit=nothex")
    assert response.status_code == 400


def test_file_endpoint_exact_content(client: TestClient, diamond_repo: Path) -> None:
    response = client.get("/api/experiments/double-q/file", params={"path": "experiment.json"})
    assert response.status_code == 200
    text = response.json()
    assert text["path"] == "experiment.json"
    manifest = json.loads(text["content"])  # exact, whitespace-preserving JSON
    assert manifest["id"] == "double-q"


def test_file_endpoint_traversal_and_missing(client: TestClient) -> None:
    for bad in ("../experiment.json", "..", "/etc/passwd", "a/./b"):
        response = client.get("/api/experiments/double-q/file", params={"path": bad})
        assert response.status_code == 400, bad
        assert response.json()["error"]["code"] == "invalid_argument"

    response = client.get("/api/experiments/double-q/file", params={"path": "nope.txt"})
    assert response.status_code == 404


def test_file_endpoint_unsupported_and_too_large(repo: Path) -> None:
    add_experiment(repo, "baseline")
    run_git(repo, "checkout", "--quiet", "experiments/baseline")
    (repo / "bin.dat").write_bytes(b"\x00\x01\x02")
    (repo / "big.txt").write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    (repo / "link.md").symlink_to("experiment.json")
    run_git(repo, "add", "bin.dat", "big.txt", "link.md")
    run_git(repo, "commit", "--quiet", "--no-verify", "-m", "special files")
    run_git(repo, "checkout", "--quiet", "main")
    client = TestClient(create_app(repo))

    response = client.get("/api/experiments/baseline/file", params={"path": "bin.dat"})
    assert response.status_code == 415
    assert response.json()["error"]["code"] == "unsupported_content"

    response = client.get("/api/experiments/baseline/file", params={"path": "big.txt"})
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "file_too_large"

    response = client.get("/api/experiments/baseline/file", params={"path": "link.md"})
    assert response.status_code == 415


def test_invalid_graph_returns_409(repo: Path) -> None:
    main_commit = run_git(repo, "rev-parse", "main").strip()
    add_experiment(
        repo,
        "broken",
        parents=[{"id": "ghost", "commit": main_commit, "relationship": "extends"}],
    )
    client = TestClient(create_app(repo))
    response = client.get("/api/graph")
    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "invalid_graph"
    assert "experiments/ghost" in body["error"]["message"]


def test_framework_validation_uses_envelope(client: TestClient) -> None:
    response = client.get("/api/experiments/double-q/file")  # missing ?path=
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_timeout_maps_to_503(diamond_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scientist.repository import ResearchRepository

    original = ResearchRepository.get_graph

    def slow_graph(self: ResearchRepository):
        raise GitTimeoutError("simulated timeout")

    monkeypatch.setattr(ResearchRepository, "get_graph", slow_graph)
    client = TestClient(create_app(diamond_repo))
    response = client.get("/api/graph")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "git_timeout"
    monkeypatch.setattr(ResearchRepository, "get_graph", original)


def test_unexpected_error_maps_to_500(diamond_repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scientist.repository import ResearchRepository

    def boom(self: ResearchRepository):
        raise RuntimeError("something broke badly")

    monkeypatch.setattr(ResearchRepository, "get_graph", boom)
    # raise_server_exceptions=False lets the app's Exception handler answer
    # instead of the test client re-raising the RuntimeError.
    client = TestClient(create_app(diamond_repo), raise_server_exceptions=False)
    response = client.get("/api/graph")
    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal_error"
    assert "something broke" not in body["error"]["message"]  # no internals leaked


def test_no_mutation_endpoints_exist(client: TestClient) -> None:
    for method in ("post", "put", "patch", "delete"):
        response = getattr(client, method)("/api/graph")
        assert response.status_code in (404, 405), method


def test_api_reads_leave_repository_untouched(client: TestClient, diamond_repo: Path) -> None:
    before = run_git(diamond_repo, "status", "--porcelain")
    refs_before = run_git(diamond_repo, "for-each-ref")
    client.get("/api/graph")
    client.get("/api/experiments/double-q/files")
    client.get("/api/experiments/double-q/file", params={"path": "experiment.json"})
    assert run_git(diamond_repo, "status", "--porcelain") == before
    assert run_git(diamond_repo, "for-each-ref") == refs_before


def test_startup_rejects_invalid_repository(tmp_path: Path) -> None:
    from scientist import RepositoryError

    with pytest.raises(RepositoryError):
        create_app(tmp_path / "not-a-repo")


def test_unknown_route_uses_envelope(client: TestClient) -> None:
    response = client.get("/api/definitely-not-here")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_frontend_served_from_same_origin_without_shadowing_api(
    diamond_repo: Path, tmp_path: Path
) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html><body>explorer</body></html>", encoding="utf-8")
    client = TestClient(create_app(diamond_repo, static_dir=dist))
    response = client.get("/")
    assert response.status_code == 200
    assert "explorer" in response.text
    # API routes must still win over the static catch-all mount:
    assert client.get("/api/graph").status_code == 200
    assert len(client.get("/api/graph").json()["nodes"]) == 4


def test_external_branch_changes_visible_without_restart(
    client: TestClient, diamond_repo: Path
) -> None:
    add_experiment(diamond_repo, "newcomer")
    response = client.get("/api/graph")
    assert response.status_code == 200
    assert "newcomer" in {n["manifest"]["id"] for n in response.json()["nodes"]}
