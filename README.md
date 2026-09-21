# stream-library

Kaptan Qedy'nin (Twitch/YouTube/Kick) geri dönüş planı ve yayın kütüphanesi. Ev ve iş bilgisayarı arasında senkron kalması için burada tutuluyor.

**Canlı sayfa (izleyici vitrini):** https://ertugrul-tug.github.io/stream-library/
**Captain on the Bridge (plan/checklist, mürettebat & moderatör için):** https://ertugrul-tug.github.io/stream-library/captain-on-the-bridge/

## Yapı

```
docs/
├── index.html                  Halka açık iniş sayfası — hero, haftalık ritim, platformlar, animasyonlu
├── assets/                     Landing page için marka görselleri + steam-library.json (servable kopya)
├── captain-on-the-bridge/      Detaylı plan/checklist sayfası (eski Seyir Defteri)
└── kutuphane/                  624 oyunluk Steam kütüphanesi, aranabilir/taranabilir
planning/   Comeback planı ve haftalık metrik takip dosyaları (.md kaynağı)
data/       Steam kütüphanesi (JSON) ve marka logoları (kaynak çözünürlük)
```

- [`docs/index.html`](docs/index.html) — izleyiciye gösterilecek vitrin sayfası
- [`docs/captain-on-the-bridge/index.html`](docs/captain-on-the-bridge/index.html) — planın görsel/paylaşılabilir hali, moderatörlerle bu link paylaşılabilir
- [`planning/comeback-plan.md`](planning/comeback-plan.md) — tam plan (vizyon, içerik stratejisi, yayın takvimi, risk vb.)
- [`planning/metrics-log.md`](planning/metrics-log.md) — haftalık takipçi/abone takibi
- [`data/steam-library.json`](data/steam-library.json) — 624 oyunluk Steam kütüphanesi
- [`data/logos/`](data/logos/) — marka logoları (kaynak çözünürlük)

## Senkron

```bash
git clone https://github.com/ertugrul-tug/stream-library.git
```

Sonra normal `git pull` / `git add` + `git commit` + `git push`.
