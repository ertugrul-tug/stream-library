# Handoff — Kaptan Qedy Comeback Sitesi

_Son güncelleme: 25 Eylül 2026 öğleden sonra, ofis bilgisayarından. Diğer bilgisayara geçince buradan devam._

> **Sıradaki büyük adım: Pazartesi 28 Eylül 20:30 ilk gerçek yayın = canlı test.** Aşağıdaki "Pazartesi kontrol listesi"ni takip et. O güne kadar yeni yayın özelliği eklemiyoruz; önce gerçek sohbetle neyin kırıldığını görelim.

## Canlı linkler

- **Ana sayfa (izleyici vitrini):** https://ertugrul-tug.github.io/stream-library/
- **Captain on the Bridge (plan/checklist):** https://ertugrul-tug.github.io/stream-library/captain-on-the-bridge/
- **Kütüphane (627 oyun: 624 Steam + LoL, TFT, Minecraft; aranabilir):** https://ertugrul-tug.github.io/stream-library/kutuphane/
- **Repo:** https://github.com/ertugrul-tug/stream-library

## Eve geçince ilk yapılacak

```bash
git clone https://github.com/ertugrul-tug/stream-library.git
# veya zaten klonluysa:
git pull
```

GitHub Pages her push'ta otomatik build alıyor (~30-60 sn), build'i beklemeden devam edebiliriz — canlı sayfa birkaç dakika içinde güncellenir.

## Bugün ne yapıldı (özet)

1. **Araştırma & plan** — Twitch/YouTube/Kick hesapları bulundu, geri dönüş planı yazıldı (`planning/comeback-plan.md`), yayın takvimi netleşti: Pazartesi–Cuma her akşam 20:30 (günlük temalı: serbest/hikayeli-BG3/competitive/survival/toplu ekip), Cumartesi dinlenme, Pazar sadece YouTube.
2. **Repo kuruldu** — GitHub'da `stream-library`, GitHub Pages ile `/docs` yayınlanıyor.
3. **Üç sayfa:**
   - `docs/index.html` — halka açık, animasyonlu iniş sayfası
   - `docs/captain-on-the-bridge/` — detaylı plan/checklist (eski "Seyir Defteri")
   - `docs/kutuphane/` — 624 oyunluk Steam kütüphanesi, canlı arama, Steam kapak görselleri
4. **Ana sayfa animasyon geçmişi** (en son hali canlıda):
   - Hero: pinned scroll-scrub — logo ekranı kaplayacak kadar büyüyüp (~12x) **crossfade** ile "KAPTAN QEDY / GERİ DÖNÜYOR" yazısına dönüşüyor (sıralı değil, aynı pencerede çapraz geçiş — aradaki boşluk sorunu bu şekilde çözüldü)
   - Kayan yazı bandı: scroll hızına tepki veriyor (idle drift + velocity kick)
   - Haftalık Sefer: pinned yatay filmstrip, gün kartlarında artık 4 duraklı mini zaman çizelgesi (20:30 · 21:00 · 23:00 · 23:30)
   - İki Liman (Twitch/Kick): mobilde de hep yan yana, **fermuar efekti** — biri soldan biri sağdan gelip ortada buluşuyor, YouTube'a doğru kaydırınca aynı yoldan geri çıkıyorlar (sürekli scroll'a bağlı, tek seferlik değil)
   - YouTube paneli: Twitch/Kick'ten ayrı, "kendine has içerik" vurgusu, büyük rise+scale girişi
   - Sayılar (2.8K, 178, 491, 264) scroll'a girince sıfırdan sayarak gerçek değere geliyor
   - "Canlı İzle" artık Twitch/Kick arasında seçtiren bir `<dialog>` açıyor (üç ayrı buton yerine)
   - Mobilde Kütüphane + Canlı İzle alt sabit çubukta (parmak erişimi için)
   - Nav scroll'da küçülüyor, mürettebat portresinin halkası dönüyor, topluluk butonlarının noktaları nabız atıyor, footer fade-in alıyor
   - Sayfalar arası native View Transitions (Chrome/Edge'de crossfade, desteklemeyen tarayıcıda sorunsuz normal geçiş)
   - Her şey `prefers-reduced-motion` ve JS'siz durumda güvenli statik hale düşüyor (`.scrub` / `.js` class gating)

## Yayın sistemi (22–25 Eylül'de kuruldu)

Ayrıntılar `obs-overlay/README.md`'de. Kısaca:

- **Başlatma:** Masaüstündeki "Kaptan Qedy Yayın" kısayolu → Streamer.bot + köprü + kumanda açılır, OBS'i elle aç. Kumandada **🚀 Yeni yayın** → oyunu listeden seç → Başlat (yayını sıfırlar, Twitch/Kick başlık + kategori, Discord duyurusu).
- **Kumanda:** Bu bilgisayarda PIN sormaz; telefonda PIN 4444 (`show-config.local.json > pin`). Üstte yayın sağlığı (canlı süre, bitrate, kare kaybı), mikrofon kapalıysa kırmızı uyarı; yayındaki sahne işaretli.
- **Sohbet botu:** karşılama (yeni/düzenli), 15 dk'da bir ipucu, tahmin/maç/rütbe duyuruları, sahneye göre mola/dönüş/kapanış satırları, baskın karşılama. Komutlar: `!olta` `!ganimet` `!koleksiyon` `!market` (`!martı` `!konfeti` `!top`) `!soru` `!rota` `!tahmin` `!rütbe` `!komutlar`, etkinliklerde `!saldır` `!katıl`.
- **Mini oyunlar:** olta (koleksiyon, YENİ etiketi), Kraken (kumandadan, rastgele ya da 3+ kişilik baskın sonrası), yelken yarışı, ganimet marketi ekran efektleri. Yayın Başlıyor, oyun, sohbet ve mola sahnelerinde etkinlik şeridi; oyun sesleri.
- **Sonradan eklenenler (25 Eylül):** aylık ganimet sezonu (`!sezon`), `!düello`, Twitch kanal puanı ödülleri (başlıklar README'de), `!kehanet`, sessiz sohbet dürtmesi, ilk kez yazanlara ekranda "✨ İLK SEFER", kumandadan geri sayım + sayaç bitince oyun sahnesine otomatik geçiş, YouTube bölüm listesi kopyalama, otomatik yedek ve 💾/📂 yedek taşıma. Köprü yayın ortası hatalara karşı gözetmenli.
- **LoL:** maçlar Riot'un yerel API'sinden otomatik (tahmin aç/kilitle, G/M). TFT sayılmaz.
- **Streamer.bot'ta 8 action kurulu:** QedyStreamInfo, QedyClip, QedySayTwitch/Kick, ModTimeoutTwitch/Kick, ModBanTwitch/Kick.
- **OBS (24 Eylül):** Twitch + Kick 6000 kbps, NVENC p5, dinamik bitrate açık. Yükleme ~50 Mbps, kablolu; o geceden beri kare kaybı yok.
- **Testler:** `python obs-overlay/tests/run_tests.py` (76 kontrol, ~3 dk, gerçek sohbete/Discord'a dokunmaz). Köprüde değişiklikten sonra çalıştır. Ofis bilgisayarının Türkçe konsolunda ✓ işaretleri yüzünden çöker; orada başına `PYTHONIOENCODING=utf-8` koy (evde gerek yok).
- **Diğer bilgisayarda gerekenler (git'e girmez):** `obs-overlay/show-config.local.json` (Discord webhook + PIN), masaüstü kısayolu, Streamer.bot action'ları, OBS profil ayarları. `.crew.json` (rütbe/ganimet) ve `.nights.jsonl` (yayın arşivi) bilgisayara özel: taşımak için kumanda → Ayarlar → "💾 Yedeği indir", diğer bilgisayarda "📂 Yedeği geri yükle".

## 25 Eylül öğleden sonra — ofis bilgisayarında eklenenler

- **📱 Dikey klipler (`obs-overlay/make-clips.py`):** 🎬 işaretleri artık yayın zamanının yanında OBS'in **yerel kayıt** zamanını da tutuyor (`rec`; `!klip` ve otomatik işaretler dahil). Yayından sonra `python obs-overlay/make-clips.py` en yeni kayıttan her işaretin 30 sn öncesi + 10 sn sonrasını 1080×1920 keser (üstte kamera, altta oyun), yakın işaretleri birleştirir, `kayıt klasörü/klipler/<kayıt>/` altına yazar. `--list`, `--only 2,5`, `--before/--after`, `--preview`. Ayar: `show-config.local.json > clips` (`recordingDir`, kamera/oyun kırpma kutuları). Sentetik 2560×1440 kayıtla uçtan uca test edildi.
- **⛵ Modern yelkenliler:** Galeonlar gitti. Klasik yat, balon yelkenli, katamaran ve dinghy; renk/boy/hız/yön her teknede rastgele ve ekrandan çıkan tekne yenisiyle değişiyor. Kod tek dosyada: `docs/assets/ships.js` (site + OBS sahneleri ortak kullanıyor, sahneler `../docs/assets/ships.js` ile yüklüyor).
- **Açılış ekranı radar kartı** başlığa biniyordu (sezon/geçen sefer satırları eklenince); yukarı alındı ve sınırlandı. Tüm sahneler sample modda çakışma için tarandı: temiz.

## Pazartesi 28 Eylül — kontrol listesi

**Yayından önce (ev bilgisayarı):**
- [ ] `git pull` (ofiste eklenenler: klip scripti, yelkenliler, radar düzeltmesi)
- [ ] ffmpeg kur: `winget install Gyan.FFmpeg` (klip scripti için; şu an sadece ofiste kurulu)
- [ ] OBS kaydının yayınla birlikte açıldığını ve hangi klasöre yazdığını kontrol et; `Videos` değilse `show-config.local.json > clips.recordingDir`
- [ ] Kick bio'yu işle (`planning/comeback-plan.md` Bölüm 9'daki metin)
- [ ] Varsa Discord Mürettebat rol ID'si → `show-config.json > discordLive.roleId`
- [ ] `python obs-overlay/tests/run_tests.py` → hepsi geçmeli
- [ ] Kumandada 🚀 **Yeni yayın** ile başla (rütbelerdeki "yayındaki ilk mesaj" bonusu buna bağlı)

**Yayında dikkat edilecekler (canlı test):**
- [ ] Yeni yayın → Twitch/Kick başlık + kategori doğru mu (Twitch "Set Game" `%game%`'i kategoriye çeviriyor mu, emin değiliz)
- [ ] 🎬 Anı işaretle ve sohbetten `!klip` → Twitch klibi oluşuyor mu, link sohbete düşüyor mu
- [ ] LoL maç sonucu kendiliğinden geliyor mu (TFT sayılmaz)
- [ ] Bot mesajları (karşılama, ipuçları, sahneye göre satırlar, 📣 tanıtım) — sıklık rahatsız edici mi
- [ ] Mini oyunların gerçek sohbetle ilk turu: olta, Kraken (çok mu kolay/zor), yelken yarışı
- [ ] Olta kartı ekranda yeterince fark ediliyor mu (küçük olabilir; gerekirse nadir avda büyütülür)
- [ ] Baskın / Hype Train (`level`) / reklam (`length`) gelirse: Streamer.bot'un gerçek verisindeki alanlar doğru okunuyor mu
- [ ] Neyin kırıldığını ya da garip durduğunu not al — salı günü düzeltme listesi bu olacak

**Yayından sonra (aynı gece, "Yeni yayın"a basmadan — işaretleri o sıfırlar):**
- [ ] `python obs-overlay/make-clips.py --preview` → PNG'de kamera ve oyun doğru kırpılmış mı; değilse `clips.camera` / `clips.game` kutularını ayarla
- [ ] `python obs-overlay/make-clips.py` → klipleri Reels/Shorts/TikTok'a yükle (plandaki 1 numaralı büyüme taktiği)
- [ ] Kumandadan 📊 yayın özetini Discord'a gönder

## Açık maddeler

- [ ] **Canlı test** ve **Kick bio** — Pazartesi kontrol listesinde
- [ ] **Mürettebat rol ID'si** — gelirse `show-config.json > discordLive.roleId`, Discord duyuruları rolü etiketler
- [ ] **Instagram hesabı kararı** — @ertugrul_tug mi @kaptan_qedy mi; `social/` altındaki reel bu karara bağlı bekliyor
- [ ] **Pazar 27 Eylül:** `planning/metrics-log.md` 1. hafta satırı
- [ ] **İlk ay sonu check-in** (~20 Ekim) — metrikler + 3 aylık hedefler

## Teknik notlar (devam ederken hatırlanacak)

- **Mobil öncelikli** — az kişi masaüstünden görecek, her karar önce telefonda test edilmeli (`resize_window preset mobile` ile kontrol edilebiliyor)
- Repo yapısı: `docs/` = canlı site (GitHub Pages kökü), `planning/` = plan `.md` kaynakları, `data/` = ham Steam JSON + logo kaynakları
- Push sonrası build'i beklemeden devam etme tercih edildi — sadece istenirse kontrol ediliyor
- Marka renkleri: Twitch mor `#9146FF`, Kick yeşil `#53FC18`, site genel paleti koyu lacivert/siyah + elektrik mavisi `#22aef0` + pembe `#ff3d7f`
- Animasyon felsefesi: "her şeyin kendi hikayesi olsun" — tek seferlik fade yerine mümkün olduğunca scroll'a gerçekten bağlı (scrub), ama her zaman `prefers-reduced-motion` ve JS'siz durumda tam görünür statik hale düşecek şekilde (progressive enhancement, `.js`/`.scrub` class gating deseni tüm sayfalarda tutarlı)
