# Reel'in ilk 3 saniyesi: kanca listesi

Reels/Shorts/TikTok'ta izleyici ilk 3 saniyede kalıp kalmayacağına karar veriyor. Klibin başına
ekranda **tek satır yazı** (büyük, ekranın üst üçte birinde) ya da **ilk cümle** olarak bunlardan birini koy.
`make-clips.py` klibin seri adını dosya adına yazıyor; hangi kancanın hangi seriye gittiği aşağıda.

| # | Kanca (ekrandaki yazı) | Ne zaman | Seri |
|---|---|---|---|
| 1 | "Sohbet bir Kraken'i 40 saniyede indirdi 🐙" | Kraken yenildiğinde, sayıyı gerçek süreyle değiştir | Kraken Düştü |
| 2 | "Bu balık 1000'de 5 çıkıyor…" | Kraken dişi / altın sandık çıktığında | Efsane Av |
| 3 | "Twitch mi Kick mi? Halat karar verdi 🪢" | Halat çekmenin son saniyeleri | Halat Çekme |
| 4 | "Korsanlar yanlış gemiye saldırdı 🏴‍☠️" | Korsan gemisi battığında | Korsan Battı |
| 5 | "3 maç, 3 galibiyet. 4.'sü?" | Seri ateşinde, sonucu göstermeden kes | Seri Ateşi |
| 6 | "Bunu yapmamam gerekiyordu." | Kendi hatan / komik ölüm, elle 🎬 işaretle | Güverteden |
| 7 | "Sohbet 'yapamaz' dedi. 👀" | Tahmin M'ye yığılmışken kazandığın maç | Seri Ateşi / Güverteden |
| 8 | "Yayına gelen biri daha 20 kişiyle geldi 🏴‍☠️" | Baskın geldiğinde (kişi sayısını yaz) | Baskın Geldi |
| 9 | "Kimse bu hamleyi beklemiyordu" | Oyundaki büyük an, elle 🎬 işaretle | Güverteden |
| 10 | "Dün gece güvertede neler oldu? ⚓" | Sabah Reel'i (`--reel`), 3 anı birden | Seyir Defteri |

## Kurallar
- **Sonucu ilk saniyede verme.** Kanca bir soru ya da vaat; cevap klibin sonunda.
- **Sesle aç.** İlk kelimeni ya da sohbetin tepkisini klibin 0. saniyesine denk getir; sessiz başlangıç kaydırılır.
- **Yazı 7 kelimeyi geçmesin.** Telefonda tek bakışta okunmalı.
- **Aynı kancayı üst üste kullanma.** Seri adları tanınmak için, kanca cümleleri her seferinde değişsin.
- **Klip 20–40 sn.** Reel algoritması izlenme oranına bakar; kısa ve tam izlenen klip, uzun ve yarım izlenenden iyidir.
