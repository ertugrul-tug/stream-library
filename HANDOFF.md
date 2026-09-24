# Handoff — Kaptan Qedy Comeback Sitesi

_Son güncelleme: 25 Eylül 2026, ev bilgisayarından. Diğer bilgisayara geçince buradan devam._

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

- **Başlatma:** Masaüstündeki "Kaptan Qedy Yayın" kısayolu → Streamer.bot + köprü + kumanda açılır, OBS'i elle aç. Kumandada **🚀 Yeni yayın** → oyun seç → Başlat (yayını sıfırlar, Twitch/Kick başlık+kategori, Discord duyurusu).
- **Kumanda:** Bu bilgisayarda PIN sormaz; telefonda PIN (köprü penceresinde yazar, `show-config.local.json > pin`).
- **LoL:** Maçlar Riot'un yerel API'sinden otomatik takip ediliyor (tahmin aç/kilitle, G/M gir). TFT sayılmaz.
- **Sohbet botu:** Tahmin, maç sonucu, rütbe duyuruları; `!rütbe`, `!komutlar`.
- **Streamer.bot'ta 8 action kurulu:** QedyStreamInfo, QedyClip, QedySayTwitch/Kick, ModTimeoutTwitch/Kick, ModBanTwitch/Kick.
- **OBS (24 Eylül):** Twitch+Kick 6000 kbps (8000'den indi), NVENC p5, dinamik bitrate açık. Donma sonrası ilk yayında 0 kare kaybı. Yükleme ~50 Mbps, kablolu.
- **Diğer bilgisayarda gerekenler (git'e girmez):** `obs-overlay/show-config.local.json` (Discord webhook + PIN), masaüstü kısayolu, Streamer.bot action'ları, OBS profil ayarları.

## Açık maddeler

- [ ] **Canlı test bekleyenler (bir sonraki yayın):** Yeni yayın → Twitch/Kick başlık/kategori değişiyor mu (Twitch "Set Game" adımı `%game%` ismini kategoriye çeviriyor mu, emin değiliz) · 🎬 Anı işaretle → sohbete klip linki düşüyor mu · LoL maç sonucu kendiliğinden giriliyor mu · bot mesajları ve `!rütbe`
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
