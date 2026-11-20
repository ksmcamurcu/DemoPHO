# DemoPHO API

DemoPHO; yapay zekâ sohbeti, kullanıcı belleği, öğrenme geri bildirimi, yetenek önerileri, ürün siparişleri ve randevu planlaması için modüler bir FastAPI demosudur. API varsayılan olarak yalnızca yerel bilgisayarda `127.0.0.1:8000` adresinde çalışır.

## Gereksinimler ve sanal ortam

Python 3.11 veya üzeri gerekir. Depoyu indirdikten sonra proje klasöründe sanal ortamı oluşturun:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e ".[test]"
```

Linux/macOS:

```bash
source .venv/bin/activate
python -m pip install -e ".[test]"
```

API'yi geliştirme ortamında başlatın:

```bash
python -m app.main
```

Varsayılan adres `http://127.0.0.1:8000`'dir. `DEMO_PHO_HOST` ve `DEMO_PHO_PORT` ortam değişkenleriyle değiştirilebilir. API belgeleri `/docs`, OpenAPI 3.1 şeması `/openapi.json` adresindedir.

Testleri çalıştırmak için:

```bash
python -m pytest
```

## Windows ve Linux paketleri

Tek kaynak kodu iki platforma göre GitHub Actions ile paketlenir: Windows için `DemoPHO-API.exe`, Linux için `DemoPHO-x86_64.AppImage`. Paketleri GitHub Actions'tan `v*` etiketi yayımlandığında veya Actions sekmesindeki `Paketleri oluştur` iş akışı elle çalıştırıldığında üretebilirsiniz. Çalıştırıldığında API sunucusu başlar ve günlükleri terminalde gösterir; durdurmak için `Ctrl+C` kullanın.

Yerel paketleme bağımlılıkları:

```bash
python -m pip install -e ".[build]"
```

`.AppImage` derlemesi Linux ortamı ve `appimagetool` gerektirir; `.exe` derlemesi Windows ortamı gerektirir. İş akışı bu nedenle iki ayrı GitHub Actions koşucusu kullanır.

## API kullanımı

Kullanıcıya ait tüm uç noktalar `X-User-ID` başlığı ister. Bu başlık yalnızca demoda veri kapsamını ayırır; kimlik doğrulama veya erişim kontrolü sağlamaz.

```bash
curl -H "X-User-ID: demo-user" http://127.0.0.1:8000/api/v1/memories
```

Temel uç noktalar:

| İşlev | Uç noktalar |
|---|---|
| Sohbet | `POST /api/v1/chat/completions` |
| Kullanıcı belleği | `GET, POST /api/v1/memories`, `GET, PATCH, DELETE /api/v1/memories/{id}` |
| Öğrenme geri bildirimi | `GET, POST /api/v1/learning/feedback` |
| Yetenek önerileri | `GET, POST /api/v1/capability-proposals`, `POST /api/v1/capability-proposals/{id}/decision` |
| Ürün kataloğu ve sipariş | `GET /api/v1/products`, `GET, POST /api/v1/orders` |
| Randevular | `GET, POST /api/v1/appointments` |
| Kod deneyi kuyruğu | `GET, POST /api/v1/code-experiments` |
| Sağlık kontrolü | `GET /health` |

Bellek, geri bildirim, sipariş, randevu ve öneriler uygulama belleğinde tutulur; sunucu yeniden başlayınca silinir. Sohbet uç noktası harici servise bağlanmayan örnek bir sağlayıcı kullanır. Kod deneyleri yalnızca açıklama metaverisi olarak sıraya eklenir; kullanıcı kodu çalıştırılmaz. Yetenek önerileri ayrıca açıkça onaylanabilir ancak onay üretim sisteminde değişiklik yapmaz.

Bu proje bir demo iskeletidir: gerçek ödeme, hastane/sağlık verisi, harici yapay zekâ sağlayıcısı, kalıcı veritabanı ve kimlik doğrulama içermez. Üretimde kullanıma hazır değildir.
