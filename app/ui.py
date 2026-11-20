import json
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import uvicorn
from pydantic import ValidationError

from app.engine.core import EngineError, run_program
from app.engine.realmode import SAMPLE_BOOT_SECTOR, run_boot_sector
from app.iso_manager import IsoManager
from app.schemas import WoxProgram

SAMPLE_PROGRAM = {
    "program": [
        {"op": "load_imm", "register": 0, "value": 7},
        {"op": "load_imm", "register": 1, "value": 35},
        {"op": "add", "register": 0, "source": 1},
        {"op": "print", "register": 0},
        {"op": "halt"},
    ]
}


def run_desktop(
    application, host: str, port: int, iso_manager: IsoManager
) -> None:
    server = uvicorn.Server(
        uvicorn.Config(application, host=host, port=port, log_level="error")
    )
    threading.Thread(target=server.run, daemon=True).start()

    root = tk.Tk()
    root.title("Wox")
    root.geometry("980x700")
    root.minsize(760, 560)
    root.configure(background="#111827")

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(
        "TFrame",
        background="#111827",
    )
    style.configure(
        "TLabel",
        background="#111827",
        foreground="#e5e7eb",
        font=("Segoe UI", 10),
    )
    style.configure(
        "Title.TLabel",
        foreground="#f9fafb",
        font=("Segoe UI", 24, "bold"),
    )
    style.configure(
        "Subtitle.TLabel",
        foreground="#9ca3af",
        font=("Segoe UI", 10),
    )
    style.configure(
        "TButton",
        padding=(12, 8),
        font=("Segoe UI", 10, "bold"),
    )
    style.configure(
        "TNotebook",
        background="#111827",
        borderwidth=0,
    )
    style.configure(
        "TNotebook.Tab",
        padding=(16, 9),
        background="#1f2937",
        foreground="#d1d5db",
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", "#2563eb")],
        foreground=[("selected", "#ffffff")],
    )

    outer = ttk.Frame(root, padding=24)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="Wox", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        outer,
        text="Kendi sanal makine motorunun geliştirme prototipi",
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(2, 18))

    tabs = ttk.Notebook(outer)
    tabs.pack(fill="both", expand=True)

    engine_tab = ttk.Frame(tabs, padding=18)
    tabs.add(engine_tab, text="Motor denemesi")
    ttk.Label(
        engine_tab,
        text=(
            "Wox Bytecode v1 — dört kayıtçı, 64 KiB bellek ve sınırlı komut kümesi. "
            "Bu prototip konak bilgisayarın dosyalarına, ağına veya işletim sistemine erişmez."
        ),
        wraplength=850,
    ).pack(anchor="w", pady=(0, 12))

    program_editor = tk.Text(
        engine_tab,
        height=15,
        wrap="none",
        font=("Consolas", 10),
        background="#0b1220",
        foreground="#d1d5db",
        insertbackground="#ffffff",
        relief="flat",
        padx=12,
        pady=12,
    )
    program_editor.pack(fill="both", expand=True)
    program_editor.insert("1.0", json.dumps(SAMPLE_PROGRAM, indent=2))

    result_box = tk.Text(
        engine_tab,
        height=5,
        state="disabled",
        wrap="word",
        font=("Consolas", 10),
        background="#0b1220",
        foreground="#86efac",
        relief="flat",
        padx=12,
        pady=10,
    )
    result_box.pack(fill="x", pady=(12, 10))

    def show_result(text: str) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", "end")
        result_box.insert("1.0", text)
        result_box.configure(state="disabled")

    def execute() -> None:
        try:
            program = WoxProgram.model_validate_json(
                program_editor.get("1.0", "end-1c")
            )
            result = run_program(program.program)
        except (ValidationError, EngineError) as exc:
            show_result(f"Program çalıştırılamadı: {exc}")
            return
        show_result(
            f"Çıktı: {' '.join(result.output) or '(boş)'}\n"
            f"Kayıtçılar: {result.registers}\n"
            f"Adım: {result.steps}"
        )

    buttons = ttk.Frame(engine_tab)
    buttons.pack(fill="x")
    ttk.Button(
        buttons,
        text="Örnek programı yükle",
        command=lambda: (
            program_editor.delete("1.0", "end"),
            program_editor.insert("1.0", json.dumps(SAMPLE_PROGRAM, indent=2)),
        ),
    ).pack(side="left")
    ttk.Button(buttons, text="Motoru çalıştır", command=execute).pack(
        side="right"
    )
    execute()

    boot_tab = ttk.Frame(tabs, padding=18)
    tabs.add(boot_tab, text="x86 önyükleme denemesi")
    ttk.Label(
        boot_tab,
        text="Wox x86 gerçek kip — 16 bit",
        style="Title.TLabel",
    ).pack(anchor="w", pady=(0, 8))
    ttk.Label(
        boot_tab,
        text=(
            "512 baytlık imzalı önyükleme sektörünü hex olarak çalıştırır. "
            "Şimdilik BIOS 10h metin çıktısı desteklenir; disk erişimi, ISO "
            "önyükleme ve tam işletim sistemi desteği yoktur."
        ),
        wraplength=850,
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(0, 12))
    boot_editor = tk.Text(
        boot_tab,
        height=8,
        wrap="word",
        font=("Consolas", 10),
        background="#0b1220",
        foreground="#d1d5db",
        insertbackground="#ffffff",
        relief="flat",
        padx=12,
        pady=12,
    )
    boot_editor.pack(fill="both", expand=True)
    boot_editor.insert("1.0", SAMPLE_BOOT_SECTOR.hex())
    boot_result = tk.StringVar(value="Örnek henüz çalıştırılmadı.")
    ttk.Label(
        boot_tab,
        textvariable=boot_result,
        style="Subtitle.TLabel",
        wraplength=850,
    ).pack(anchor="w", pady=12)

    def execute_boot_sector() -> None:
        try:
            result = run_boot_sector(
                bytes.fromhex(boot_editor.get("1.0", "end-1c").strip())
            )
        except ValueError as exc:
            boot_result.set(f"Önyükleme başarısız: {exc}")
            return
        boot_result.set(
            f"BIOS metin çıktısı: {result.output or '(boş)'} — "
            f"{result.instructions} x86 komutu"
        )

    boot_buttons = ttk.Frame(boot_tab)
    boot_buttons.pack(fill="x")
    ttk.Button(
        boot_buttons,
        text="Örnek sektör yükle",
        command=lambda: (
            boot_editor.delete("1.0", "end"),
            boot_editor.insert("1.0", SAMPLE_BOOT_SECTOR.hex()),
        ),
    ).pack(side="left")
    ttk.Button(
        boot_buttons,
        text="Önyükleme kodunu çalıştır",
        command=execute_boot_sector,
    ).pack(side="right")
    execute_boot_sector()

    systems_tab = ttk.Frame(tabs, padding=18)
    tabs.add(systems_tab, text="ISO arşivi")
    ttk.Label(
        systems_tab,
        text="Hedeflenen konuk sistemler",
        style="Title.TLabel",
    ).pack(anchor="w", pady=(0, 12))
    for system in (
        "Ubuntu x86_64",
        "Parrot x86_64",
        "Pardus ARM64",
        "Windows 11",
        "Windows 10",
        "Windows Vista",
    ):
        ttk.Label(systems_tab, text=f"• {system} — motor desteği geliştiriliyor").pack(
            anchor="w", pady=4
        )

    ttk.Label(
        systems_tab,
        text=(
            "Linux ISO'larını indir/güncelle düğmeleri resmi kaynaklardan indirir. "
            "Dosyanın SHA özeti doğrulandıktan sonra önceki sürüm silinir."
        ),
        wraplength=850,
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(14, 8))

    iso_status: dict[str, tk.StringVar] = {}
    iso_rows = ttk.Frame(systems_tab)
    iso_rows.pack(fill="x")
    for iso_id, title, size in (
        ("ubuntu-lts-amd64", "Ubuntu LTS x86_64", "yaklaşık 6 GiB"),
        ("parrot-security-amd64", "Parrot Security x86_64", "yaklaşık 9 GiB"),
    ):
        row = ttk.Frame(iso_rows)
        row.pack(fill="x", pady=4)
        ttk.Label(row, text=f"{title} — {size}").pack(side="left")
        status_text = tk.StringVar(value="Hazır değil")
        iso_status[iso_id] = status_text
        ttk.Label(row, textvariable=status_text, style="Subtitle.TLabel").pack(
            side="right", padx=(8, 12)
        )
        ttk.Button(
            row,
            text="ISO indir / güncelle",
            command=lambda selected=iso_id: start_iso_update(selected),
        ).pack(side="right")

    user_image_row = ttk.Frame(systems_tab)
    user_image_row.pack(fill="x", pady=(10, 4))
    user_image_status = tk.StringVar(
        value="Windows ISO'su ve Pardus ARM64 imajı henüz seçilmedi."
    )
    saved_images = {
        item["id"]: item["filename"]
        for item in iso_manager.list_isos()
        if item.get("downloaded") and item.get("filename")
    }
    if "windows" in saved_images or "pardus-arm64" in saved_images:
        user_image_status.set(
            "Kayıtlı imajlar: "
            + ", ".join(
                f"{image_id}: {filename}"
                for image_id, filename in saved_images.items()
                if image_id in {"windows", "pardus-arm64"}
            )
        )
    ttk.Label(
        user_image_row,
        textvariable=user_image_status,
        style="Subtitle.TLabel",
        wraplength=600,
    ).pack(side="left", fill="x", expand=True)
    ttk.Button(
        user_image_row,
        text="Windows ISO seç",
        command=lambda: import_image("windows", "Windows ISO"),
    ).pack(side="right", padx=(8, 0))
    ttk.Button(
        user_image_row,
        text="Pardus ARM imajı seç",
        command=lambda: import_image("pardus-arm64", "Pardus ARM"),
    ).pack(side="right")

    def update_iso_status() -> None:
        for iso_id, variable in iso_status.items():
            state = iso_manager.get_status(iso_id)
            status_value = state["status"]
            if status_value == "downloading":
                done = int(state.get("downloaded_bytes") or 0) / (1024 * 1024)
                total = state.get("total_bytes")
                if total:
                    variable.set(
                        f"İndiriliyor: %{done / (int(total) / (1024 * 1024)) * 100:.0f}"
                    )
                else:
                    variable.set(f"İndiriliyor: {done:.0f} MiB")
            elif status_value == "ready":
                variable.set("İndirildi ve doğrulandı")
            elif status_value == "ready_cleanup_warning":
                variable.set("Doğrulandı; eski dosya silinemedi")
            elif status_value == "failed":
                variable.set(f"Hata: {state.get('error')}")
            elif status_value == "queued":
                variable.set("İndirme kuyruğunda")
            elif status_value == "checking_metadata":
                variable.set("Resmî sürüm ve SHA bilgisi denetleniyor")
            else:
                variable.set("İndirilmedi")
        root.after(1000, update_iso_status)

    def start_iso_update(iso_id: str) -> None:
        try:
            iso_manager.start_update(iso_id)
        except ValueError as exc:
            messagebox.showerror("ISO güncelleme hatası", str(exc), parent=root)

    def import_image(image_id: str, title: str) -> None:
        source = filedialog.askopenfilename(
            parent=root,
            title=f"{title} dosyasını seçin",
            filetypes=[
                ("ISO veya disk imajı", "*.iso *.img *.qcow2"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if not source:
            return
        try:
            filename = iso_manager.import_user_image(image_id, source)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Dosya eklenemedi", str(exc), parent=root)
            return
        user_image_status.set(f"{title} imajı eklendi: {filename}")

    update_iso_status()
    ttk.Label(
        systems_tab,
        text=(
            "ISO dosyaları şu an yalnızca indirilip saklanır; bu prototip onları "
            "henüz başlatamaz. Windows için lisanslı ISO dosyanızı siz seçmelisiniz."
        ),
        wraplength=850,
        style="Subtitle.TLabel",
    ).pack(anchor="w", pady=(18, 0))

    api_tab = ttk.Frame(tabs, padding=18)
    tabs.add(api_tab, text="Yerel API")
    ttk.Label(api_tab, text="Wox API", style="Title.TLabel").pack(anchor="w")
    ttk.Label(
        api_tab,
        text=f"Yalnızca bu bilgisayarda: http://{host}:{port}/docs",
    ).pack(anchor="w", pady=(10, 4))
    ttk.Label(
        api_tab,
        text="Motor bilgisi: GET /api/v1/engine\nProgram çalıştır: POST /api/v1/engine/run",
        style="Subtitle.TLabel",
    ).pack(anchor="w")

    def close() -> None:
        server.should_exit = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", close)
    root.mainloop()
    if server.started:
        server.should_exit = True
