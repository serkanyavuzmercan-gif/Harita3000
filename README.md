# Harita3000

Saha operasyon, sevkiyat ve müşteri ziyaretlerini tek haritada toplayan iç platform.

## Çalıştırma

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m backend.seed
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Uygulama: http://127.0.0.1:8000  
API belgeleri: http://127.0.0.1:8000/docs

Varsayılan veritabanı proje kökündeki SQLite dosyasıdır. PostGIS için `docker compose up -d` ardından `.env` içinde:

```text
DATABASE_URL=postgresql+asyncpg://harita:harita@localhost:5432/harita3000
```

## Harita sağlayıcısı

Anahtar gerekmez. Varsayılan olarak harita OpenStreetMap (Leaflet) ile açılır; adres-koordinat çevirisi Nominatim, sürüş rotası OSRM üzerinden yapılır. Hiçbir harita dosyası diske indirilmez.

`.env` içine `GOOGLE_MAPS_API_KEY` yazılırsa aynı ekran otomatik olarak Google Maps'e geçer. `MAP_PROVIDER=osm` anahtar olsa bile OpenStreetMap'te tutar.

OpenStreetMap'in ücretsiz genel sunucuları düşük trafik içindir (Nominatim saniyede 1 istek). Saha ekibi büyüdüğünde `TILE_URL`, `OSRM_URL` ve `NOMINATIM_URL` kendi sunucunuza veya ücretli bir sağlayıcıya çevrilir; kod değişmez.

Örnek veri Denizli ilçeleri (Merkezefendi, Pamukkale, Honaz, Sarayköy, Çivril, Tavas, Acıpayam) üzerinedir. Harita merkezi `.env` içinden değiştirilebilir.

## Veritabanı göçleri

Şema Alembic ile yönetilir ve uygulama açılırken otomatik olarak en son sürüme yükseltilir. Eski sürümle oluşturulmuş bir veritabanı veri kaybı olmadan yükseltilir. Model değiştirdikten sonra yeni göç üretmek için:

```powershell
alembic revision --autogenerate -m "aciklama"
```

## Firma ve haritada işaretleme

Firma sekmesinde unvan, iletişim bilgileri ve logo (raporlarda kullanılır) tanımlanır. Merkez, şube, depo ve fabrika gibi birden fazla lokasyon eklenebilir; bunlar haritada mor yıldızla görünür. "Rota başlangıcı" seçilen lokasyon, rota optimizasyonu ve rota çiziminde çıkış noktası olur.

Yönetici "Haritada işaretle" ile haritaya tıklayarak bir noktayı cari (müşteri, tedarikçi, rakip, diğer) ya da firma lokasyonu olarak kaydedebilir; adres otomatik bulunur. Mevcut pinler sürüklenerek taşınır, onaydan sonra kaydedilir. Haritanın altındaki anahtarlarla katmanlar ayrı ayrı gizlenip gösterilebilir.

## Haritada arama

Haritanın sol üstündeki kutu üç kaynağa birden bakar:

- **Kayıtlarım:** Yazarken kendi carileriniz ve firma lokasyonlarınız anında listelenir; internete çıkmaz. Seçince harita o pine gider.
- **Google önerileri:** `GOOGLE_MAPS_API_KEY` tanımlıysa yazarken Google öneri listesi gelir. Bunun için Google Cloud'da anahtar üzerinde **Places API (New)** açık olmalıdır. Kapalıysa öneriler sessizce devre dışı kalır ve Enter ile arama çalışmaya devam eder.
- **Enter / Ara:** Adres veya yer adı sunucu üzerinden aranır. Anahtar varsa Google Places Text Search (başarısız olursa Google Geocoding), yoksa OpenStreetMap Nominatim kullanılır. Sonuçlar haritanın o anki merkezine yakın yerleri öne alır ve 24 saat önbellekte tutulur.

OpenStreetMap'in ücretsiz servisi yazarken öneri kullanımına izin vermez; bu yüzden anahtarsız modda dış arama yalnızca Enter ile yapılır.

Bir sonuç seçildiğinde harita oraya yaklaşır; yönetici noktayı "Cari olarak kaydet" veya "Firma lokasyonu yap" ile kaydedebilir. Yerin adı ve adresi forma kendiliğinden dolar.

## Filo takibi (Arvento, Mobiliz)

Araç konumları canlı değil, belirli aralıklarla çekilir. Sunucudaki zamanlayıcı her entegrasyonu kendi aralığında (varsayılan 5 dk) sorgular, konumları saklar ve aynı kaydı iki kez yazmaz. Tarayıcı araçları `VEHICLE_REFRESH_SECONDS` aralığıyla yeniler; uzun süre veri gelmeyen araç "veri gecikmiş" olarak gri görünür.

Filo sekmesinden (yönetici):

1. Yeni entegrasyon ekleyin ve sağlayıcıyı seçin. Kimlik bilgileri şifreli saklanır, ekrana bir daha gelmez.
2. "Test et" ile bağlantıyı deneyin.
3. "Araç eşleştir" ile takip sistemindeki her aracı plakaya bağlayın.

Arvento ve Mobiliz bağlayıcılarının iskeleti, ayar alanları ve şifreleme hazırdır; API erişimi ve dokümanı gelince yalnızca `services/telematics/arvento.py` ve `mobiliz.py` içindeki iki metot doldurulur. O zamana kadar **Simülatör** sağlayıcısı Denizli'de gerçek yollar üzerinde mesai saatlerinde (08:00–18:00) dolaşan dört araç üretir. Demo veride 20 HRT 01 ve 20 HRT 04 simülatöre bağlıdır ve dünün izi hazır yüklüdür.

Birden fazla uvicorn süreci çalıştırılıyorsa zamanlayıcı yalnızca birinde açık kalmalıdır (`TELEMATICS_POLLER_ENABLED`).

## Gün sonu rota raporu

Rapor sekmesinde tarih ve araç seçilerek PDF veya Excel indirilir:

- özet: toplam km, sürüş ve durak süresi, ilk ve son hareket, en yüksek hız, sürücü
- rota haritası (OpenStreetMap üzerinde iz ve numaralı duraklar)
- duraklar: varış, ayrılış, süre, eşleşen cari veya firma lokasyonu (200 m içinde), planlı teslimat olup olmadığı
- o gün o araca planlanıp uğranmayan teslimatlar
- Excel'de ayrıca tüm konum kayıtları

"Tüm filo PDF" o gün verisi olan bütün araçları tek dosyada verir. Her gece `DAILY_REPORT_HOUR:DAILY_REPORT_MINUTE` saatinde raporlar `reports/YYYY-AA-GG/` altına yazılır ve arşiv listesinden indirilebilir. `POSITION_RETENTION_DAYS` günden eski konumlar silinir.

Filo sekmesindeki "Günün izi" aynı analizi haritada gösterir.

## Testler

```powershell
python -m pytest
```

Testler geçici bir veritabanı kullanır ve ağa çıkmaz.

## Giriş

Varsayılan olarak giriş ekranı yoktur: program açılınca doğrudan yönetici yetkisiyle çalışır. Sunucu yalnızca bu bilgisayardan (`127.0.0.1`) erişilecek şekilde başlatıldığı sürece bu güvenlidir. Programı ağdaki başka kişilere açacaksanız `.env` içinde `AUTH_REQUIRED=true` yapın; kullanıcı adı, parola ve roller geri gelir.

## Veri saklama, yedek ve aktarma

Tüm kayıtlar proje kökündeki `harita3000.db` dosyasında kalıcı olarak saklanır; yüklenen logo ve teslim fotoğrafları `uploads/`, arşiv raporları `reports/` klasöründedir.

Firma sekmesinin altındaki "Veri: yedekle ve aktar" bölümünden:

- **Tam yedek indir:** Bütün veritabanı ve dosyalar tek bir ZIP olur (`harita3000_yedek_YYYY-AA-GG_SSDD.zip`). Konum geçmişi büyükse hariç tutulabilir.
- **Yedekten geri yükle:** ZIP içindeki veri mevcut verinin yerine konur. Yedek başka bir bilgisayardan geliyorsa ve orada `INTEGRATION_SECRET` farklıysa filo entegrasyonlarının kimlik bilgileri yeniden girilmelidir; ekran bunu uyarır.
- **Cari listesi:** Excel veya CSV olarak dışa aktarılır. Aynı sütunlarla (Unvan, Tip, Kategori, Adres, Enlem, Boylam, Telefon, E-posta, Vergi No, Bakiye, Durum, Bölge) düzenlenip yeniden içe aktarılabilir. İçe aktarma yeni kayıt ekler.

Yedeği başka bir bilgisayara taşımak için orada programı kurup boş açın, ardından ZIP'i geri yükleyin.

## Demo hesaplar

Yalnızca `AUTH_REQUIRED=true` iken gerekir. Parola hepsi için `admin123`.

| Kullanıcı | Rol |
| --- | --- |
| admin | Yönetici |
| lojistik | Lojistik Sorumlusu |
| pazarlamaci | Saha Pazarlamacı |
| surucu | Sürücü |

Toplu içe aktarma örneği: `database/ornek_musteriler.csv`
