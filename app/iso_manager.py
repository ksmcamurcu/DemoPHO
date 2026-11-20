import hashlib
import os
import re
import shutil
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

MAX_ISO_BYTES = 16 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class IsoSpec:
    id: str
    name: str
    version: str
    architecture: str
    filename: str
    url: str
    checksum_algorithm: str
    checksum: str
    metadata_mode: str | None = None


ISO_SPECS = (
    IsoSpec(
        id="ubuntu-lts-amd64",
        name="Ubuntu LTS",
        version="24.04.5.1",
        architecture="x86_64",
        filename="ubuntu-24.04.5.1-desktop-amd64.iso",
        url="https://releases.ubuntu.com/24.04/ubuntu-24.04.5.1-desktop-amd64.iso",
        checksum_algorithm="sha256",
        checksum="4da4a0c9035da8e68a59a838674f403f0a54472c78a83b4fb7f78d03588f85a7",
        metadata_mode="ubuntu_lts",
    ),
    IsoSpec(
        id="parrot-security-amd64",
        name="Parrot Security",
        version="7.4",
        architecture="x86_64",
        filename="Parrot-security-7.4_amd64.iso",
        url="https://deb.parrot.sh/parrot/iso/7.4/Parrot-security-7.4_amd64.iso",
        checksum_algorithm="sha512",
        checksum="cc85c85061aa5539afc865895c9a2354a709ca53e246264a71dc93eeb2eedaac17b9d548f25235655fefbc7c7e080398af061c041f8ba91d4ae43ddd163e931b",
        metadata_mode="parrot_latest",
    ),
)


def default_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
        return root / "Wox"
    root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "wox"


def _status_copy(state: dict[str, object]) -> dict[str, object]:
    return dict(state)


class IsoManager:
    def __init__(
        self,
        data_dir: Path | None = None,
        opener=urllib.request.urlopen,
        specs: tuple[IsoSpec, ...] = ISO_SPECS,
    ) -> None:
        self.iso_dir = (data_dir or default_data_dir()) / "isos"
        self._specs = {spec.id: spec for spec in specs}
        self._opener = opener
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, object]] = {}
        self._user_images: dict[str, str] = {}
        for image_id in ("windows", "pardus-arm64"):
            directory = self.iso_dir / image_id
            image = next(
                (
                    path
                    for path in sorted(directory.iterdir())
                    if path.is_file()
                    and path.suffix.lower() in {".iso", ".img", ".qcow2"}
                ),
                None,
            ) if directory.exists() else None
            if image is not None:
                self._user_images[image_id] = image.name

    def list_isos(self) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for spec in self._specs.values():
            existing = sorted(
                self.iso_dir.glob(f"{spec.id}-*.iso"),
                key=lambda path: path.stat().st_mtime,
            ) if self.iso_dir.exists() else []
            path = existing[-1] if existing else None
            filename = path.name if path is not None else self._filename(spec)
            with self._lock:
                task = _status_copy(
                    self._tasks.get(
                        spec.id,
                        {"status": "ready" if path is not None else "not_downloaded"},
                    )
                )
            filename_version = (
                path.stem.removeprefix(f"{spec.id}-") if path is not None else spec.version
            )
            items.append(
                {
                    "id": spec.id,
                    "name": spec.name,
                    "version": task.get("version", filename_version),
                    "architecture": spec.architecture,
                    "filename": filename,
                    "downloaded": path is not None,
                    "size_bytes": path.stat().st_size if path is not None else None,
                    **task,
                }
            )
        items.extend(
            [
                {
                    "id": "pardus-arm64",
                    "name": "Pardus ARM64",
                    "architecture": "ARM64",
                    "downloaded": "pardus-arm64" in self._user_images,
                    "filename": self._user_images.get("pardus-arm64"),
                    "status": (
                        "ready"
                        if "pardus-arm64" in self._user_images
                        else "manual_image_required"
                    ),
                    "message": "Resmî indirme dizininde ARM64 sanal makine ISO'su bulunamadı.",
                },
                {
                    "id": "windows",
                    "name": "Windows 11 / 10 / Vista",
                    "downloaded": "windows" in self._user_images,
                    "filename": self._user_images.get("windows"),
                    "status": (
                        "ready" if "windows" in self._user_images else "manual_iso_required"
                    ),
                    "message": "Lisanslı Windows ISO dosyanızı seçin.",
                },
            ]
        )
        return items

    def start_update(self, iso_id: str) -> dict[str, object]:
        spec = self._specs.get(iso_id)
        if spec is None:
            raise ValueError("Bu ISO için otomatik indirme desteklenmiyor.")
        self.iso_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            state = self._tasks.get(iso_id)
            if state is not None and state["status"] in {"queued", "downloading"}:
                return _status_copy(state)
            self._tasks[iso_id] = {
                "status": "queued",
                "downloaded_bytes": 0,
                "total_bytes": None,
                "verified": False,
                "error": None,
            }
        threading.Thread(
            target=self._download, args=(spec,), daemon=True, name=f"wox-iso-{iso_id}"
        ).start()
        with self._lock:
            return _status_copy(self._tasks[iso_id])

    def get_status(self, iso_id: str) -> dict[str, object]:
        spec = self._specs.get(iso_id)
        if spec is None:
            raise ValueError("ISO bulunamadı.")
        with self._lock:
            state = _status_copy(
                self._tasks.get(
                    iso_id,
                    {
                        "status": (
                            "ready"
                            if any(self.iso_dir.glob(f"{spec.id}-*.iso"))
                            else "not_downloaded"
                        ),
                        "downloaded_bytes": 0,
                        "total_bytes": None,
                        "verified": False,
                        "error": None,
                    },
                )
            )
        if "filename" not in state:
            existing = sorted(
                self.iso_dir.glob(f"{spec.id}-*.iso"),
                key=lambda path: path.stat().st_mtime,
            ) if self.iso_dir.exists() else []
            state["filename"] = (
                existing[-1].name if existing else self._filename(spec)
            )
        state.setdefault(
            "version",
            str(state["filename"])
            .removeprefix(f"{spec.id}-")
            .removesuffix(".iso"),
        )
        return state

    def import_user_image(self, image_id: str, source_path: str) -> str:
        allowed = {"windows", "pardus-arm64"}
        if image_id not in allowed:
            raise ValueError("Bu tür için kullanıcı imajı eklenemez.")
        source = Path(source_path).expanduser().resolve(strict=True)
        if not source.is_file() or source.suffix.lower() not in {
            ".iso",
            ".img",
            ".qcow2",
        }:
            raise ValueError("ISO, IMG veya QCOW2 dosyası seçin.")
        if source.stat().st_size > MAX_ISO_BYTES:
            raise ValueError("İmaj dosyası 16 GiB sınırını aşıyor.")
        self.iso_dir.mkdir(parents=True, exist_ok=True)
        destination_dir = self.iso_dir / image_id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / source.name
        temporary = destination.with_name(destination.name + ".part")
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        self._user_images[image_id] = destination.name
        return destination.name

    def _download(self, spec: IsoSpec) -> None:
        destination: Path | None = None
        temporary: Path | None = None
        downloaded = 0
        total: int | None = None
        try:
            self.iso_dir.mkdir(parents=True, exist_ok=True)
            with self._lock:
                self._tasks[spec.id].update({"status": "checking_metadata"})
            spec = self._resolve_latest(spec)
            filename = self._filename(spec)
            destination = self.iso_dir / filename
            temporary = destination.with_name(destination.name + ".part")
            digest = hashlib.new(spec.checksum_algorithm)
            with self._lock:
                self._tasks[spec.id].update(
                    {
                        "status": "downloading",
                        "filename": filename,
                        "version": spec.version,
                    }
                )
            request = urllib.request.Request(
                spec.url,
                headers={"User-Agent": "Wox-ISO-Manager/0.1"},
            )
            with self._opener(request, timeout=60) as response:
                total_header = response.headers.get("Content-Length")
                total = int(total_header) if total_header else None
                if total is not None and total > MAX_ISO_BYTES:
                    raise ValueError("ISO dosyası 16 GiB sınırını aşıyor.")
                with temporary.open("wb") as output:
                    while chunk := response.read(CHUNK_SIZE):
                        downloaded += len(chunk)
                        if downloaded > MAX_ISO_BYTES:
                            raise ValueError("ISO dosyası 16 GiB sınırını aşıyor.")
                        output.write(chunk)
                        digest.update(chunk)
                        with self._lock:
                            self._tasks[spec.id].update(
                                {
                                    "status": "downloading",
                                    "downloaded_bytes": downloaded,
                                    "total_bytes": total,
                                }
                            )
            if digest.hexdigest().lower() != spec.checksum.lower():
                raise ValueError("ISO SHA doğrulaması başarısız; eski dosya korundu.")
            if downloaded == 0:
                raise ValueError("Sunucu boş bir ISO dosyası gönderdi.")
            os.replace(temporary, destination)
            cleanup_warning = None
            prefix = f"{spec.id}-"
            for old in self.iso_dir.glob(f"{prefix}*.iso"):
                if old != destination and old.is_file():
                    try:
                        old.unlink()
                    except OSError as exc:
                        cleanup_warning = str(exc)
            with self._lock:
                self._tasks[spec.id].update(
                    {
                        "status": (
                            "ready_cleanup_warning"
                            if cleanup_warning
                            else "ready"
                        ),
                        "downloaded_bytes": downloaded,
                        "total_bytes": total,
                        "verified": True,
                        "error": cleanup_warning,
                    }
                )
        except (OSError, TimeoutError, ValueError, urllib.error.URLError) as exc:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError as cleanup_exc:
                    exc.add_note(f"Geçici dosya temizlenemedi: {cleanup_exc}")
            with self._lock:
                self._tasks[spec.id].update(
                    {
                        "status": "failed",
                        "downloaded_bytes": downloaded,
                        "verified": False,
                        "error": str(exc),
                    }
                )

    def _resolve_latest(self, spec: IsoSpec) -> IsoSpec:
        if spec.metadata_mode == "ubuntu_lts":
            releases = self._read_text("https://releases.ubuntu.com/")
            lts_versions = {
                version
                for version in re.findall(
                    r"""href=["'](\d{2,4}\.04)/["']""", releases
                )
                if int(version.split(".", 1)[0]) % 2 == 0
            }
            if not lts_versions:
                raise ValueError("Ubuntu LTS sürümü bulunamadı.")
            release_version = max(
                lts_versions,
                key=lambda value: tuple(int(part) for part in value.split(".")),
            )
            manifest = self._read_text(
                f"https://releases.ubuntu.com/{release_version}/SHA256SUMS"
            )
            escaped_version = re.escape(release_version)
            matches = re.findall(
                r"^([a-fA-F0-9]{64})\s+\*?"
                rf"(ubuntu-{escaped_version}(?:\.\d+)*-desktop-amd64\.iso)$",
                manifest,
                re.MULTILINE,
            )
            if not matches:
                raise ValueError("Ubuntu LTS ISO özeti bulunamadı.")
            checksum, filename = max(
                matches,
                key=lambda item: tuple(
                    int(part) for part in re.findall(r"\d+", item[1])
                ),
            )
            version = filename.removeprefix("ubuntu-").removesuffix(
                "-desktop-amd64.iso"
            )
            return replace(
                spec,
                version=version,
                filename=filename,
                url=f"https://releases.ubuntu.com/{release_version}/{filename}",
                checksum=checksum.lower(),
            )
        if spec.metadata_mode == "parrot_latest":
            page = self._read_text("https://www.parrotsec.org/download/")
            latest_match = re.search(r"Latest:\s*v?([\d.]+)", page)
            candidates = re.findall(
                r"https://deb\.parrot\.sh/parrot/iso/([\d.]+)/"
                r"(Parrot-security-([\d.]+)_amd64\.iso)",
                page,
            )
            if latest_match is not None:
                latest_version = latest_match.group(1).rstrip(".")
                candidates = [
                    item for item in candidates if item[2] == latest_version
                ]
            if not candidates:
                raise ValueError("Resmî Parrot ISO bağlantısı bulunamadı.")
            directory_version, filename, version = max(
                candidates,
                key=lambda item: tuple(
                    int(part) for part in item[2].split(".")
                ),
            )
            if directory_version != version:
                raise ValueError("Parrot sayfasındaki sürüm bilgisi tutarsız.")
            hash_manifest = self._read_text(
                f"https://deb.parrot.sh/parrot/iso/{version}/signed-hashes.txt"
            )
            checksum_match = re.search(
                rf"^([a-fA-F0-9]{{128}})\s+{re.escape(filename)}$",
                hash_manifest,
                re.MULTILINE,
            )
            if checksum_match is None:
                raise ValueError("Resmî Parrot SHA512 özeti bulunamadı.")
            return replace(
                spec,
                version=version,
                filename=filename,
                url=f"https://deb.parrot.sh/parrot/iso/{version}/{filename}",
                checksum=checksum_match.group(1).lower(),
            )
        return spec

    def _read_text(self, url: str) -> str:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Wox-ISO-Manager/0.1"},
        )
        with self._opener(request, timeout=30) as response:
            content = response.read(2 * 1024 * 1024 + 1)
        if len(content) > 2 * 1024 * 1024:
            raise ValueError("Resmî ISO metadata dosyası beklenenden büyük.")
        return content.decode("utf-8")

    @staticmethod
    def _filename(spec: IsoSpec) -> str:
        return f"{spec.id}-{spec.version}.iso"
