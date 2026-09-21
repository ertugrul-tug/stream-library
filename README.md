# stream-library

Kaptan Qedy'nin (Twitch/YouTube/Kick) geri dönüş planı ve yayın kütüphanesi. Ev ve iş bilgisayarı arasında senkron kalması için burada tutuluyor.

**Canlı sayfa:** https://ertugrul-tug.github.io/stream-library/

## Yapı

```
docs/       GitHub Pages kaynağı — seyir defteri sayfası (index.html)
planning/   Comeback planı ve haftalık metrik takip dosyaları
data/       Steam kütüphanesi (JSON) ve marka logoları
```

- [`docs/index.html`](docs/index.html) — planın görsel/paylaşılabilir hali, moderatörlerle bu link paylaşılabilir
- [`planning/comeback-plan.md`](planning/comeback-plan.md) — tam plan (vizyon, içerik stratejisi, yayın takvimi, risk vb.)
- [`planning/metrics-log.md`](planning/metrics-log.md) — haftalık takipçi/abone takibi
- [`data/steam-library.json`](data/steam-library.json) — 624 oyunluk Steam kütüphanesi
- [`data/logos/`](data/logos/) — marka logoları (kaynak çözünürlük)

## Senkron

```bash
git clone https://github.com/ertugrul-tug/stream-library.git
```

Sonra normal `git pull` / `git add` + `git commit` + `git push`.
