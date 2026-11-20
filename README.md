# Wox

Wox, kendi sanal makine motorunu geliştiren bir masaüstü prototipidir. Windows `.exe` ve Linux `.AppImage` olarak paketlenir. Arayüz Tkinter ile uygulamanın içindedir; kullanıcıdan ayrıca C++ çalışma zamanı indirmesi istenmez.

## Şu anki durum

Wox Core 0.1.0-prototype, kendi tanımlı `Wox Bytecode v1` komut kümesini ve sınırlandırılmış bir x86 16-bit gerçek kip CPU adımını içerir. x86 önyükleme sektörü 1 MiB sanal bellekte en fazla 100.000 komut çalıştırabilir; BIOS 10h metin çıktısı desteklenir. Bytecode denemesi dört kayıtçı ve 64 KiB sanal bellek sunar. Motor konak dosyalarına, ağa veya işletim sistemine erişemez.

**Henüz Ubuntu, Parrot, Pardus ARM veya Windows ISO’larını başlatamaz.** Mevcut x86 denemesi disk BIOS kesmelerini (`INT 13h`), 32/64-bit kipleri, ARM64'ü, sanal aygıtları veya disk denetleyicilerini desteklemez. Bu sistemler için bu bileşenler geliştirilmelidir. Kendi motoruyla güvenilir işletim sistemi sanallaştırması uzun soluklu bir mühendislik çalışmasıdır; Wox şu anda ana bilgisayar için güvenlik garantisi vermez. Güvenilmeyen ISO’ları çalıştırmak için kullanmayın.

## Geliştirme

Python 3.11 veya üzeri gerekir. Sanal ortam oluşturup test bağımlılıklarını yükleyin:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Linux:

```bash
source .venv/bin/activate
python -m pip install -e ".[test]"
```

Wox penceresini başlatın:

```bash
python -m app.main
```

Testleri çalıştırın:

```bash
python -m pytest
```

## Yerel API

Wox açıldığında API yalnızca bu bilgisayarda `127.0.0.1:8000` adresinde başlar. Belgeler `/docs`, OpenAPI 3.1 şeması `/openapi.json` adresindedir.

- `GET /health`
- `GET /api/v1/engine` — motor yetenekleri ve sınırları
- `POST /api/v1/engine/run` — sınırlı Wox Bytecode programı çalıştırma
- `POST /api/v1/engine/boot-sector` — imzası doğrulanan 512 baytlık x86 16-bit boot sektörünü sınırlı komut kümesinde çalıştırma

Motorun adım sayısı, program uzunluğu, kayıtçı sayısı ve belleği sabit sınırlarla korunur. Programlar Python kodu veya konak komutları çalıştıramaz. Masaüstü arayüzündeki **x86 önyükleme denemesi** sekmesi örnek boot sektörünü çalıştırır; bu, gerçek işletim sistemi boot desteği değildir.

## Paketleme

Windows ve Linux paketleri GitHub Actions’taki **Wox paketlerini oluştur** iş akışıyla derlenir. `v*` etiketi yayımlandığında iş akışı testleri ve platform paketlemelerini tamamlar, ardından `Wox.exe`, `Wox-x86_64.AppImage` ve FUSE gerektirmeyen `Wox-Linux-x86_64.tar.gz` dosyalarını GitHub Release varlıkları olarak ekler. Tar arşivini dosya yöneticisiyle çıkarıp içindeki `Wox` uygulamasını çalıştırabilirsiniz. AppImage dosyasını doğrudan kullanmak için Linux sisteminde FUSE 2 desteği ve çalıştırma izni gerekir. Depoda **Actions → Wox paketlerini oluştur → Run workflow** ile elle çalıştırma yalnızca Actions artifacts üretir; Release oluşturmaz. Paketler özel Wox motor prototipini ve arayüzü içerir; QEMU/VirtualBox içermez.

ISO indirmeleri uygulamanın **ISO arşivi** sekmesinden kullanıcı isteğiyle başlatılır. Ubuntu LTS ve Parrot indirmeleri resmî metadata üzerinden sürümü ve SHA özetini denetler; yeni dosya doğrulandıktan sonra eski sürüm silinir. Pardus ARM64 için resmî sanal makine ISO’su bulunmadığından kullanıcı kendi ARM64 imajını seçebilir. Lisanslı Windows ISO’su kullanıcı tarafından seçilir; Windows ISO’su uygulamayla dağıtılmaz. İndirilen ISO’lar kullanıcı veri klasöründe saklanır.

ISO’lar şu an yalnızca indirilebilir ve saklanabilir; Wox Core bu prototipte henüz işletim sistemi ISO’su başlatamaz.
