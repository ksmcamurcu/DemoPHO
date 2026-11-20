import hashlib
import time
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient

from app.iso_manager import IsoManager, IsoSpec
from app.main import create_app


class FakeResponse(BytesIO):
    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args) -> None:
        self.close()


def spec_for(content: bytes, version: str = "2.0") -> IsoSpec:
    return IsoSpec(
        id="test-linux",
        name="Test Linux",
        version=version,
        architecture="x86_64",
        filename=f"test-{version}.iso",
        url="https://images.example.test/test.iso",
        checksum_algorithm="sha256",
        checksum=hashlib.sha256(content).hexdigest(),
    )


def wait_for_status(manager: IsoManager, expected: str) -> dict[str, object]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        status = manager.get_status("test-linux")
        if status["status"] in {"ready", "failed"}:
            if status["status"] == expected:
                return status
            if expected == "ready" and status["status"] == "failed":
                raise AssertionError(status["error"])
            if expected == "failed" and status["status"] == "ready":
                raise AssertionError("The invalid ISO was accepted.")
        time.sleep(0.01)
    raise TimeoutError("ISO download did not finish.")


def test_iso_update_replaces_old_file_only_after_checksum_verifies(
    tmp_path: Path,
) -> None:
    content = b"verified test ISO"
    manager = IsoManager(
        data_dir=tmp_path,
        opener=lambda _request, timeout: FakeResponse(content),
        specs=(spec_for(content),),
    )
    manager.iso_dir.mkdir(parents=True)
    old_file = manager.iso_dir / "test-linux-1.0.iso"
    old_file.write_bytes(b"old ISO")

    manager.start_update("test-linux")
    state = wait_for_status(manager, "ready")

    new_file = manager.iso_dir / "test-linux-2.0.iso"
    assert state["verified"] is True
    assert new_file.read_bytes() == content
    assert not old_file.exists()
    listed = next(
        item for item in manager.list_isos() if item["id"] == "test-linux"
    )
    assert listed["downloaded"] is True
    assert listed["version"] == "2.0"
    reloaded_manager = IsoManager(data_dir=tmp_path, specs=(spec_for(content),))
    reloaded = next(
        item for item in reloaded_manager.list_isos() if item["id"] == "test-linux"
    )
    assert reloaded["version"] == "2.0"


def test_bad_checksum_keeps_the_previous_iso(tmp_path: Path) -> None:
    manager = IsoManager(
        data_dir=tmp_path,
        opener=lambda _request, timeout: FakeResponse(b"tampered bytes"),
        specs=(spec_for(b"expected bytes"),),
    )
    manager.iso_dir.mkdir(parents=True)
    old_file = manager.iso_dir / "test-linux-1.0.iso"
    old_file.write_bytes(b"known good")

    manager.start_update("test-linux")
    state = wait_for_status(manager, "failed")

    assert "SHA" in str(state["error"])
    assert old_file.read_bytes() == b"known good"
    assert not (manager.iso_dir / "test-linux-2.0.iso").exists()


def test_linux_iso_metadata_uses_latest_official_lts(tmp_path: Path) -> None:
    text_responses = iter(
        [
            b'<a href="24.04/">24.04</a><a href="26.04/">26.04</a><a href="26.10/">26.10</a>',
            b"a" * 64 + b" *ubuntu-26.04.1-desktop-amd64.iso\n",
        ]
    )
    manager = IsoManager(
        data_dir=tmp_path,
        opener=lambda _request, timeout: FakeResponse(next(text_responses)),
    )
    current = next(spec for spec in manager._specs.values() if spec.metadata_mode == "ubuntu_lts")

    latest = manager._resolve_latest(current)

    assert latest.version == "26.04.1"
    assert latest.checksum == "a" * 64
    assert "releases.ubuntu.com/26.04/" in latest.url
    assert latest.url.endswith("ubuntu-26.04.1-desktop-amd64.iso")


def test_parrot_metadata_uses_latest_official_iso_hash(tmp_path: Path) -> None:
    checksum = "b" * 128
    text_responses = iter(
        [
            (
                b"Latest: v7.4 "
                b"https://deb.parrot.sh/parrot/iso/7.3/"
                b"Parrot-security-7.3_amd64.iso "
                b"https://deb.parrot.sh/parrot/iso/7.4/"
                b"Parrot-security-7.4_amd64.iso"
            ),
            f"{checksum} Parrot-security-7.4_amd64.iso\n".encode(),
        ]
    )
    manager = IsoManager(
        data_dir=tmp_path,
        opener=lambda _request, timeout: FakeResponse(next(text_responses)),
    )
    current = next(
        spec
        for spec in manager._specs.values()
        if spec.metadata_mode == "parrot_latest"
    )

    latest = manager._resolve_latest(current)

    assert latest.version == "7.4"
    assert latest.checksum == checksum
    assert latest.url.endswith("/7.4/Parrot-security-7.4_amd64.iso")


def test_iso_api_lists_sources_and_rejects_missing_pardus_arm_image(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(IsoManager(data_dir=tmp_path)))

    listing = client.get("/api/v1/isos")
    assert listing.status_code == 200
    ids = {item["id"] for item in listing.json()}
    assert {
        "ubuntu-lts-amd64",
        "parrot-security-amd64",
        "pardus-arm64",
        "windows",
    } <= ids
    response = client.post("/api/v1/isos/pardus-arm64/update")
    assert response.status_code == 422


def test_user_iso_import_only_accepts_known_image_types(tmp_path: Path) -> None:
    source = tmp_path / "windows.iso"
    source.write_bytes(b"Windows ISO placeholder")
    manager = IsoManager(data_dir=tmp_path / "wox-data")

    copied_name = manager.import_user_image("windows", str(source))

    assert copied_name == "windows.iso"
    assert (
        manager.iso_dir / "windows" / "windows.iso"
    ).read_bytes() == source.read_bytes()
    reloaded_manager = IsoManager(data_dir=tmp_path / "wox-data")
    saved_image = next(
        item for item in reloaded_manager.list_isos() if item["id"] == "windows"
    )
    assert saved_image["downloaded"] is True
    assert saved_image["filename"] == "windows.iso"
