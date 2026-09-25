# Kaptan Qedy OBS yayın katmanı

overlay.html, mevcut sitenin görsel dilini kullanan tek OBS Browser Source katmanıdır. Oyun ve kamera görüntüsü şeffaf alanların arkasında OBS kaynakları olarak kalır. Twitch ile Kick mesajları aynı sohbet kutusunda, platform etiketleriyle görünür. Twitch bildirimleri solda, Kick bildirimleri sağda animasyon ve kısa bir sesle çıkar. Aynı anda gelen iki platformun bildirimleri birlikte görünebilir.

## Ayrı yayın sahneleri

Aşağıdaki dört dosya OBS Browser Source olarak ayrı sahnelere eklenebilir. Her biri 2560 × 1440 tuvale göre ölçeklenir; mevcut OBS sahneleri otomatik değiştirilmez.

| Dosya | Kullanım |
| --- | --- |
| yayin-basliyor.html | Tam ekran “Yayın Başlıyor” bekleme sahnesi |
| mola.html | Tam ekran “Kısa Bir Mola” sahnesi |
| yayin-bitti.html | Tam ekran yayın sonu sahnesi |
| sohbet.html | Sol tarafı kamera için şeffaf bırakan, sağda ortak Twitch + Kick sohbeti gösteren sahne |

Başlangıç ve mola sahnelerinde isteğe bağlı geri sayım için yerel dosya adresine ?minutes=10 veya ?minutes=5 eklenebilir. Süre dolunca sayaç 00:00'da kalır; OBS sahnesi kendiliğinden değişmez.

sohbet.html normal kullanımda şeffaftır. Yerleşimi oyun benzeri arka planda örnek mesajlarla görmek için tarayıcıda sohbet.html?sample=1 açılabilir. Yayına normal sohbet.html dosyasını ekle. Canlı mesajlar için Streamer.bot WebSocket sunucusu 127.0.0.1:8080 adresinde açık olmalıdır. scene.css, scene.js, motion.css ve motion.js dosyaları aynı klasörde kalmalıdır. Hareketli ışıklar ve atmosfer parçacıkları yayın başı, mola ve bitiş ekranlarında çalışır; oyun katmanının orta alanı şeffaf kalır. Animasyonlar sistemin azaltılmış hareket ayarına uyar.

## OBS'ye ekleme

1. OBS'de QedyStudios profilini ve kullanacağın sahneyi aç. Bu profilin tuvali 2560 × 1440, 60 FPS; HTML bu tuvale göre tasarlandı.
2. Oyun yakalamayı ekle. Kamerayı ayrı bir Video Capture Device kaynağı olarak ekle; green screen için kameraya Chroma Key filtresi uygula.
3. Kaynaklar listesindeki + → Browser Source ile Kaptan Qedy Overlay adında bir kaynak oluştur. Local file seçeneğini açıp bu klasördeki overlay.html dosyasını seç.
4. Browser Source boyutunu 2560 × 1440 yap. Kaynağı oyun ve kamera kaynaklarının üstüne taşı.
5. Green screen kamerayı sol altta, alt isim barının hemen üstüne yerleştir. Kamera etrafında çerçeve yoktur. Ortak chat sağ alttadır. Aynı katmanı farklı sahnelerde kullanmak için onu içeren bir OBS sahnesini diğer sahnelere kaynak olarak ekleyebilirsin.

Yayın katmanı yerel dosyadan açılır; sitenin GitHub Pages sayfasına eklenmez. Logo görselini üst dizindeki docs/assets/logo_cat.png dosyasından okur, bu yüzden repo klasörünün yapısını koru.

## Canlı Twitch + Kick chat ve bildirimleri

Katman, bilgisayarındaki Streamer.bot WebSocket sunucusuna varsayılan yerel adresinden bağlanmayı dener. Tek OBS Browser Source yeterlidir, ancak canlı olayları almak için Streamer.bot'un çalışması ve iki yayın hesabına bağlanması gerekir.

1. Streamer.bot içinde Twitch ve Kick yayıncı hesaplarını bağla.
2. Servers / Clients → WebSocket Server bölümünde 127.0.0.1, port 8080, endpoint / ayarlarını kullan; Auto Start ve sunucuyu etkinleştir.
3. Katman Twitch ve Kick chat mesajlarına, takip ve abonelik olaylarına otomatik abone olur. Twitch bit desteğini ve Kick Kicks desteğini de gösterir. Aynı platformda art arda gelen uyarılar sıraya alınır. Bağlantı kurulmadığında chat boş kalır; test mesajları yayında görünmez.
4. Bu yerel bağlantı için WebSocket sunucusunun Enforce Authentication seçeneği kapalı olmalıdır. Sunucuyu yalnızca 127.0.0.1 adresinde tut; dış ağlara açma.
5. OBS'de sesin yönlendirilmesini kontrol et. Takip sesini yayına vermek için Browser Source sesinin OBS mikserinde duyulduğunu kısa bir kayıtla doğrula.

Streamer.bot kurulu değilse ya da hesaplar bağlanmamışsa, katmanın görsel öğeleri çalışır; canlı chat ve uyarılar veri gelene kadar boş kalır.

## Önizleme

Normal tarayıcıda overlay.html?demo=1 adresini aç. Sol üstte test düğmeleri görünür; Twitch ve Kick mesajları ile takip ve abonelik uyarıları, ayrıca Twitch bit uyarısı oluşturur. overlay.html?sample=1 iki platformun uyarılarını ve ortak sohbeti, oyun benzeri arka plan ve temsili webcam kesitiyle gösterir. OBS'ye normal overlay.html dosyasını ekle; önizleme görselleri ve test içerikleri yayında görünmez.

## Olay biçimi

Katman yerel olarak window.qedyOverlay.push(event) ile de test edilebilir:

- Chat: {type:'chat', platform:'twitch', name:'İzleyici', text:'Selam!'}
- Takip: {type:'follow', platform:'kick', name:'Yeniİzleyici'}
- Abonelik: {type:'subscription', platform:'twitch', name:'Abone'}
- Bit: {type:'bits', platform:'twitch', name:'Destekçi', amount:250}
- Kicks: {type:'kicks', platform:'kick', name:'Destekçi', amount:100}

Kullanıcı adları ve mesajlar HTML olarak yorumlanmaz; güvenli düz metin olarak gösterilir. Chat kutusu son yedi mesajı tutar.

## İnteraktif yayın paketi (köprü + kumanda)

`show-bridge.py` ("köprü") Streamer.bot'tan Twitch ve Kick olaylarını alır, OBS'le ve Discord'la konuşur ve tüm sahnelere ortak bir yayın durumu dağıtır. `kumanda.html` bu köprünün kontrol paneli; OBS kaynağı değildir, kendi tarayıcında (bilgisayar ya da aynı wifi'deki telefon) açık tutulur.

### Başlatma

1. Bir kere: `python -m pip install -r obs-overlay/requirements.txt`
2. Masaüstündeki **Kaptan Qedy Yayın** kısayoluna (ya da `start-show.cmd`'ye) çift tıkla. Streamer.bot kapalıysa açar, köprüyü "Qedy Show Bridge" penceresinde başlatır (zaten açıksa ikinci kopyayı açmaz) ve kumandayı tarayıcıda açar. OBS'i kendin aç.
3. Köprü penceresi telefon adresini (`http://<LAN-IP>:8766/kumanda.html`) ve **telefon PIN'ini** yazar. Pencereyi yayın bitene kadar kapatma.
4. Kumandada **🚀 Yeni yayın**: oyunu listeden seç (LoL, TFT, Minecraft, BG3 hazır; "➕ Başka oyun…" 627 oyunluk kütüphanede arar), rotalar ve yayın başlığı oyuna göre dolar. **Başlat** yayını sıfırlar (rütbe puanları kalır), Twitch + Kick başlık/kategoriyi günceller ve Discord'a canlı duyurusunu atar. Her yayına bununla başla; "yayındaki ilk mesaj" rütbe bonusu buna bağlı.

### Kumandada neler var

**⏱ Geri sayım:** Canlı sekmesinin başındaki 5/10/15 dk düğmeleri Yayın Başlıyor ve Kısa Mola ekranlarındaki sayacı başlatır (OBS'teki `?minutes=` adresini değiştirmeye gerek kalmaz), bot sohbete duyurur; ✕ iptal eder. Sayaç bittiğinde OBS hâlâ "Yayın Başlıyor" ya da "Kısa Mola"daysa köprü oyun sahnesine (`obsScenes` içindeki "Sahne") kendiliğinden geçer; kumandadan kapatılabilir.

**Yayın öncesi kontrol** (Canlı sekmesinin en üstü): OBS, Streamer.bot, 8 action, Discord webhook, mikrofon ve bot durumu ✅/❌ olarak listelenir. **🎬 Prova** ~25 sn'lik sessiz bir gösteri oynatır (baskın kartı, efsane olta, konfeti, Kraken): bot sohbete yazmaz, istatistik ve ganimete dokunmaz. Yayına girmeden OBS sahnelerinin güncel olduğunu ve seslerin geldiğini kontrol etmek için.

Telefonda bölümler alttaki sekmelere ayrılır: 🎬 Canlı (klip, maç serisi, sorular, öne çıkanlar) · 🎮 Oyunlar (mini oyunlar, rota) · 💬 Sohbet (ortak sohbet, rütbeler) · ⚙️ Ayarlar (seyir defteri, Discord). Bekleyen soru sayısı Canlı sekmesinde rozet olarak görünür. Bilgisayarda hepsi aynı sayfadadır.

- **Sahneye duyarlı:** Köprü OBS sahne değişikliklerini dinler. Kumandada yayındaki sahnenin düğmesi kırmızı çerçeveli görünür. Bot "Kısa Mola"ya geçince mola duyurusu, moladan dönünce "Güverteye döndük", "Yayın Başlıyor"da ısınma çağrısı, "Yayın Bitti"de teşekkür ve ganimet kralını yazar (aynı tür için 2 dk'da bir).
- **Yayıncıya hatırlatmalar (sadece kumandada):** Yayında her 45 dakikada "💧 su iç, omuzlarını gevşet"; 2. ve 4. saatte "kısa bir mola iyi gelebilir" ve tek dokunuşla "⏸️ Mola ver (5 dk)": OBS'i Kısa Mola'ya geçirir, 5 dk sayaç başlatır, sayaç bitince oyun sahnesine döner.
- **Yayın sağlığı:** Üst çubuğun altında "🔴 CANLI 1:23:45 · 5.9 Mbps · kayıp %0.1" (bitrate son ~15 sn, kare kaybı son 1 dk). Yayındayken OBS'teki mikrofon (Mic/Aux) sessizdeyse yanıp sönen kırmızı "🎙️ MİKROFON KAPALI" bandı, kare kaybı %1'i geçerse turuncu bağlantı uyarısı çıkar.
- **Üst çubuk:** OBS ve Bot (Streamer.bot) durum noktaları, şu anki segment, sahne düğmeleri: 🎮 Sahne · 💭 Sohbet Güvertesi · ▶️ Yayın Başlıyor · ⏸️ Kısa Mola · ⏹️ Yayın Bitti (`show-config.json > obsScenes`; obs-websocket v5 gerekir).
- **⏱ !süre / 🏆 !skor:** Sohbet yayının ne kadardır sürdüğünü ve bu akşamki G/M'yi (2+ maçlık seriyle) sorabilir; 30 sn'de bir cevaplanır.
- **🎯 !hedef / 💤 !lurk:** `!hedef` bu akşamki takip hedefini ilerleme çubuğuyla gösterir; `!lurk` (`!afk`) sessiz izleyiciyi ambara uğurlar (kişi başı 10 dk'da bir).
- **🔥 Sadakat serisi:** Bir önceki yayına da gelen izleyicinin serisi artar; tekrar selamında "N yayın üst üste" yazar. 3., 5. ve 10'dan sonra her 5. yayında seri×5 🪙 sadakat ödülü verilir. Seri "Yeni yayın" ile açılan yayınlar arasında sayılır. Yayın sonu özetinde 3+ serisi olan en sadık 3 kişi yazılır; sohbet kutularında isminin yanında 🔥N rozeti görünür.
- **⏸️ Mola özeti:** Moladan oyun sahnesine dönünce bot, mola boyunca sohbete yazılan mesaj ve atılan olta sayısını da söyler.
- **🎲 !öner:** Kaptanın oyun kütüphanesinden (`steam-library.json`) rastgele bir oyun ve Steam linkini önerir; 30 sn'de bir.
- **📣 Tanıtım:** Kumandada sohbet satırındaki 📣 o kişinin Twitch/Kick kanalını iki sohbete de tanıtır (kişi başı dakikada bir).
- **🎬 Klipler:** "Otomatik klip" açıksa otomatik işaretlenen büyük anlar `QedyClip` ile de kliplenir (en fazla 2 dk'da bir, varsayılan kapalı). Sohbet `!klip` ile o anı klipleyebilir (yalnızca yayındayken, tüm sohbet için 90 sn'de bir); link sohbete düşer.
- **📝 YouTube bölümleri:** Klip işareti kartındaki düğme, VOD zamanlı işaretlerden YouTube'un anladığı bölüm listesini (0:00 Açılış, artan sıra, ≥10 sn arayla) ve altına kanal linklerini panoya kopyalar; Pazar kurgusunda video açıklamasına yapıştırılır.
- **🤖 Otomatik işaretler:** Yayın açıkken baskın, Kraken zaferi, yarış sonucu, efsane olta (60+), takip hedefi ve 3+ galibiyet serisi VOD zamanıyla kendiliğinden işaretlenir; kumandada 🤖 ile görünür, Discord özetindeki "Yayından anlar" listesine girer (Pazar YouTube kurgusu için).
- **🎬 Anı işaretle:** VOD zamanını OBS'ten alıp notla kaydeder, yayın sonu özetine girer ve Streamer.bot `QedyClip`'i tetikler (Twitch klibi + linki Twitch/Kick sohbetine).
- **Maç serisi:** ✅/❌ ile skor, son 5 maç noktaları, 2+ galibiyet serisinde oyun sahnesinde alev. **Maç tahmini:** sohbet `!tahmin G` / `!tahmin M` yazar, kilitleyince oylar durur, sonuç girilince "Sohbetin %70'i bildi" 30 sn ekranda kalır.
- **LoL otomatik takip:** Riot'un yerel Live Client Data API'si (127.0.0.1:2999, anahtarsız) okunur. Maç yüklenince tahmin açılır, 3. dakikada (`lolAuto.lockAfterSec`) kilitlenir, maç bitince G/M kendiliğinden girilir. İzleyici modu, Practice Tool ve TFT sayılmaz; elle girilen sonuç tekrarlanmaz. Kumandadan kapatılabilir.
- **🎮 Birlikte oyna (`!oyna`):** Toplu ekip geceleri için Oyunlar sekmesinden sırayı aç; bot duyurur. İzleyiciler `!oyna OyunİçiAdı` ile girer (bot sırasını söyler), `!sıram` ile sorar, `!çık` ile çıkar. "▶ Sıradakini çağır" ya da satırdaki ▶ kişiyi çağırır, bot "sıra sende, lobiye gel" der. Sıra açıkken oyun sahnesinin etkinlik şeridinde küçük bir sıra kartı görünür.
- **Rota oylaması:** sohbet `!rota 1/2/3`; kaydedince bot seçenekleri sohbete yazar, "🧭 Sohbete hatırlat" tekrar yazar.
- **Sohbet botu:** tahmin açılış/kilit/sonucu, maç sonucu ve seri, rütbe atlama duyuruları; `!rütbe` ve `!komutlar` sorulan platformda cevaplanır (kişi başı bekleme süreli). Yayındaki ilk mesajında herkesi karşılar (yeniye "Güverteye hoş geldin", düzenliye rütbe ve kaçıncı seferi; dakikada en fazla 6, yayıncı hesabı ve Nightbot gibi botlar hariç). Sohbet aktifken 15 dakikada bir sırayla ipucu yazar (`show-config.json > tips.everyMinutes`). `!kehanet <soru>` korsan kâhininden evet/hayır cevabı verir. Yayındayken sohbet 12 dakikadır sessizse hafif bir oyun çağrısıyla dürter (yayın başına en fazla 3, arası en az 20 dk; `show-config.json > quietNudge.afterMinutes`). Botun kendi mesajları geri geldiğinde sayılmaz. "🤖 Bot konuşuyor · sustur" ile kapatılır.
- **❓ Sorular:** sohbet `!soru ...` yazar (en az 5 harf, kişi başı 60 sn), bot sırasını söyler. Kumandada "📺 Göster" soruyu oyun/sohbet sahnesinde "SOHBETTEN SORU" kartıyla gösterir, "✓ Cevaplandı" listeden ve ekrandan kaldırır. 23:00 "Günlük sohbet" bölümü için.
- **Link komutları:** `show-config.json > chatLinks` içindeki her komut (`!site`, `!kutuphane`, `!twitch`, `!kick`…) sohbette o metni yazar, komut başına 30 sn'de bir. `!discord`, `!youtube`, `!instagram` sitedeki adreslerle dolduruldu. Sitenin ana sayfasındaki "Güverte" bölümü (`docs/index.html#guverte`) izleyicilere oyunları ve komutları anlatır.
- **Destekçilere teşekkür:** Takip edenler birkaç saniye içinde platform başına tek mesajla karşılanır (+10 ganimet); abone/hediye abonelik +50, her 100 bit ya da 100 Kicks +10 ganimet ve sohbette teşekkür. Destek böylece mini oyun ekonomisine de girer.
- **Ortak sohbet:** mesajı "Anons yap" ile ekranda öne çıkar; 🎁 o kişiye 10 ganimet hediye eder (bot sohbette duyurur); ⏱ timeout (10 dk) ve ⛔ ban.
- **Discord:** 📣 Canlıyım (oyun satırlı duyuru), 📊 yayın sonu özeti (önizlemeli), özel mesaj.
- **Mini oyunlar** (oyun sahnesinin üst ortasındaki etkinlik şeridinde görünür):
  - **🎣 Olta:** sohbet `!olta` yazar (kişi başı 60 sn), 2,6 sn sonra ganimet çıkar: Hamsi (3) … Altın sandık (60), Kraken dişi (100). 25+ puanlık yakalamaları bot duyurur. `!ganimet` toplamı ve en iyi yakalamayı söyler. İlk kez yakalanan ganimette ekranda **YENİ!** etiketi çıkar; `!koleksiyon` 9 ganimetten hangilerinin toplandığını gösterir, tamamlayana +100 ganimet ve "Balıkçı Reisi" ilanı. Kumandadaki "🎣 Olta at" Kaptan adına atar.
  - **🐙 Kraken:** kumandadan çağrılır ya da yayın açıkken 25–50 dakikada bir kendiliğinden çıkar (kumandadan kapatılabilir). Sohbet 90 sn içinde `!saldır` ile canını bitirir; can son 10 dakikada yazan kişi sayısına göre ayarlanır. Kazanılırsa saldıran herkes ganimet alır, son vuruşa +25.
  - **⛵ Yelken yarışı:** kumandadan başlar, 45 sn `!katıl` süresi var, Kaptan'ın gemisi otomatik katılır. Yarışta yazılan her mesaj o kişinin gemisine rüzgâr verir; ilk üç 50/25/10 ganimet alır.
  - **🛒 Market:** Ganimet ekran efektlerine harcanır: 🕊️ `!martı` 15 (adını taşıyan martı ekranın üstünden geçer), 🎉 `!konfeti` 20, 💥 `!top` 40 (parlama, kartlar sarsılır, gümbürtü). `!market` fiyatları ve bakiyeyi söyler; yetmezse bot eksiği yazar. Aynı efekt 8 sn, aynı kişi 10 sn beklemeli. Ganimet sıralaması toplam kazanılana göredir, harcamak düşürmez. Kumandadan "🛒 Market kapalı" yapılabilir. Önizleme: `overlay.html?sample=fx`.
  - **💜 Twitch kanal puanları:** Twitch → Yayıncı Paneli → Kanal Puanları'nda başlıkları birebir `🎉 Konfeti`, `🕊️ Martı`, `💥 Top`, `🎣 Olta`, `🐙 Kraken çağır` olan ödüller oluştur (başlık ↔ etki eşlemesi `show-config.json > channelPoints`). Ödül kullanılınca efekt ganimet harcamadan oynar, olta bekleme süresine takılmaz; Kraken başka bir etkinlik sürerken çağrılırsa bot bunu söyler (puan otomatik iade edilemez, Kraken ödülüne Twitch'te bekleme süresi koymak iyi olur).
  - **🏅 Sezon:** Ganimet her ay sıfırdan başlayan bir sezon sıralamasında da toplanır (tüm zamanlar sıralaması ayrıca kalır). `!sezon` ilk üçü ve kişinin bu ayki ganimetini söyler; sezonun ilk üçü Yayın Başlıyor ve Kısa Mola ekranlarında da görünür; kumandada sezon listesi, Discord özetinde sezon lideri.
  - **⚔️ Düello:** `!düello @isim 20` (5–100, varsayılan 10) ganimetine meydan okur; karşı taraf 30 sn içinde `!kabul` ya da `!red` yazar. Kabulde yazı tura, kazanan ortaya konan miktarı alır; ekranda düello şeridi ve kılıç sesi. Platformlar arası çalışır, bakiye yetmezse teklif edilemez.
  - **🏴‍☠️ Baskın:** Twitch'ten baskın gelince etkinlik şeridinde altın "BASKIN" kartı çıkar, bot baskını yapanı ve tayfasını karşılar, 6 sn sonra kanalına takip çağrısı atar; 3+ kişilik baskından 20 sn sonra Kraken çıkar (`games.kraken.raidMinViewers`). Baskınlar Discord özetine girer. Önizleme: `overlay.html?sample=raid`.
  - **🚂 Hype Train ve 📺 reklam:** Twitch Hype Train başlayınca etkinlik şeridinde mor "HYPE TRAIN" kartı açılır, her seviyede konfeti ve sohbet çağrısı olur, bitince teşekkür edilir. Reklam arası başlayınca bot sohbete süreyi söyler, kumandanın üstünde kalan süre sayılır (Streamer.bot `AdRun` / `HypeTrain*` olayları).
  - Oyun sesleri (Kraken gürlemesi, vuruş, olta, yarış düdüğü) tarayıcıda sentezlenir; kumandadan kapatılır. Gece sonunda olta/Kraken/yarış sayıları ve "👑 Gecenin ganimet kralı" kapanış ekranına ve Discord özetine girer.
  - Kraken ve yarış aynı anda açılmaz. Ganimet puanları rütbeyi değiştirmez, `.crew.json`'da ayrı tutulur. Süreler `show-config.json > games`'te. Önizleme: `overlay.html?sample` (Kraken) ve `overlay.html?sample=race`.
- **🎯 Takip hedefi:** Ayarlar sekmesindeki (Seyir defteri) kutuya bu akşamki hedefi yaz (0 = kapalı). Oyun sahnesinin segment şeridinde "🎯 3/5 takipçi" ve ilerleme çubuğu görünür; hedef tutunca ekranda konfeti ve "hedef tamam" şeridi, bot teşekkür eder, Discord özetine girer.
- **📈 Son yayınlar:** Her "🚀 Yeni yayın"da biten gecenin özeti (oyun, mesaj, takip, abone, skor, baskın, mini oyunlar, ganimet kralı) yerel `.nights.jsonl`'a yazılır ve Ayarlar sekmesinde listelenir. "📋 Haftalık özeti kopyala" son 7 günün toplamını `planning/metrics-log.md` Not sütununa yapıştırılacak tek satır olarak panoya alır.
- **Mürettebat rütbeleri:** yayındaki ilk mesaj +10, sonra her mesaj +1 (30 sn arayla). Miço → Tayfa (20) → Usta Gemici (60) → Lostromo (150) → Dümenci (350) → İkinci Kaptan (800). Puanlar `.crew.json`'da yayınlar arası saklanır. Oyun sahnesi ve Sohbet Güvertesi sohbet kutularında isimlerin yanında altın rütbe etiketi görünür (Tayfa ve üstü). Kanala ilk kez yazan birinin mesajı altın çerçeve ve "✨ İLK SEFER" etiketiyle öne çıkar.

### Streamer.bot action'ları

Köprü Twitch/Kick'e doğrudan bağlanmaz; bu işleri Streamer.bot'taki aşağıdaki action'lara yaptırır. Action yoksa ya da içi boşsa kumanda bunu söyler.

| Action | Köprünün gönderdiği | İçinde olması gereken |
| --- | --- | --- |
| `QedyStreamInfo` | `%title%`, `%game%` | Twitch Set Title / Set Game, Kick Set Title / Set Category |
| `QedyClip` | `%note%` | Twitch Create Clip (başlık `%note%`) → If `createClipSuccess` = True → Twitch + Kick mesajı (`%createClipUrl%`) |
| `QedySayTwitch`, `QedySayKick` | `%message%` | O platforma Send Message |
| `ModTimeoutTwitch`, `ModTimeoutKick` | `%user%`, `%duration%` (600), `%reason%` | O platformda Timeout User |
| `ModBanTwitch`, `ModBanKick` | `%user%`, `%reason%` | O platformda Ban User |

Streamer.bot WebSocket Server: 127.0.0.1, port 8080, endpoint `/`, Auto Start açık, Enforce Authentication kapalı.

### Güvenlik ve yerel ayarlar

Köprünün WebSocket'i (8765) ve dosya sunucusu (8766) ev ağına açıktır ki telefondan kullanılabilsin. **Bu bilgisayardan açılan kumanda PIN sormaz; başka cihazlar köprü penceresinde yazan PIN'i bir kez girer** (4 hane girilince otomatik gönderilir, cihaz hatırlar). PIN'siz bağlantı durumu izleyebilir (OBS sahneleri böyle çalışır) ama hiçbir düğmeyi çalıştıramaz; 5 yanlış denemeden sonra o cihaz 1 dakika bekler. Dosya sunucusu `show-config.local.json`, `.show-state.json`, `.crew.json` ve `.py` dosyalarını hiçbir zaman vermez.

`show-config.json` Git'e girer (public repo): oyun/rota hazır listeleri (`routePresets`), başlık şablonları (`titleTemplates`, `{game}` yer tutuculu), sahneler, segment saatleri, LoL ayarları. **Gizli değerleri buraya yazma.** Onlar aynı klasörde Git'e girmeyen `show-config.local.json`'a gider; bu dosya varsa üstüne yazılır:

```json
{ "discordWebhook": "https://discord.com/api/webhooks/...", "pin": "1234" }
```

**Yedek ve taşıma:** Köprü her açılışta ve her "Yeni yayın"da mürettebat + arşiv verisinin kopyasını `backups/`'a alır (son 10, git'e girmez, ağa servis edilmez). Ayarlar sekmesindeki "💾 Yedeği indir" hepsini tek dosya olarak indirir; diğer bilgisayarda "📂 Yedeği geri yükle" ile yüklenir (önce oradaki veri yedeklenir).

`pin` yoksa köprü ilk açılışta rastgele 4 haneli bir PIN üretip buraya yazar. OBS şifresi gerekmez: köprü bu bilgisayardaki obs-websocket ayarından okur.

Yayın verisi `.show-state.json`'da, rütbe puanları `.crew.json`'da, geçmiş yayın özetleri `.nights.jsonl`'da yerel tutulur (Git'e girmez, sohbet kullanıcı adları içerir; paylaşma). Canlı mesajlar HTML olarak işlenmez; Twitch ve Kick emoteleri görsel olarak gösterilir (`emotes.js`).

### Sahnelerdeki kartlar

Açılış sahnesi sohbete yazanları rütbeleriyle radar listesinde gösterir. Oyun sahnesinde rota oylaması, maç serisi, maç tahmini, rütbe atlama bildirimi ve segment şeridi ("ŞİMDİ · Tema bloğu · SIRADAKİ · Günlük sohbet 23:00") vardır; kartlar ancak kullanıldıklarında görünür. Mola sahnesi oyun, dönüş notu, skor ve öne çıkan anları; kapanış sahnesi mesaj/takip/abonelik sayılarını, skor, rekor seri ve tahmin isabetini gösterir. `?sample=1` ile her sahne örnek içerikle önizlenir; OBS'e normal dosya adresini ekle. OBS önbelleği eski sayfayı tutarsa kaynak özelliklerinden "Mevcut sayfanın önbelleğini yenile".

### Testler

Köprüde bir şey değiştirdikten sonra (ya da yayından önce içini rahatlatmak için):

```bash
python obs-overlay/tests/run_tests.py
```

Köprüyü ayrı portlarda ve geçici bir klasörle başlatır; sahte Streamer.bot, OBS, LoL istemcisi ve Discord kullanır. Gerçek sohbete, Discord'a ya da kayıtlı yayın verine dokunmaz, çalışan köprünle de çakışmaz. Güvenlik (PIN, gizli dosyalar), Yeni yayın, sohbet botu, tahmin, olta/market/soru, Kraken/yarış/baskın, OBS sahne ve sağlık, LoL otomasyonu, moderasyon ve Discord özeti uçtan uca denenir; yaklaşık 2 dakika sürer.

## Pusulalı sahne geçişi

pusula-gecis.webm, OBS Stinger geçişinde kullanılacak 1280 × 720, 60 FPS ve şeffaf VP9 videodur. OBS sahne geçişlerine yeni bir Stinger ekle, dosyayı seç ve Transition Point değerini 600 ms yap. Tam örtme anında sahne değişir. OBS sahne/kaynak sırası bu paket tarafından değiştirilmez. Videoyu yeniden üretmek istersen önce python -m pip install Pillow, ardından python obs-overlay/make-stinger.py çalıştır. [OBS Stinger açıklaması](https://obsproject.com/kb/track-matte-stinger-transitions) geçiş noktasını açıklar.

## Önizleme görselleri

Bu iki görsel yalnızca örnek oyun/kamera yerleşimi içindir; normal OBS katmanında gösterilmez. Temsili kameradaki kişi yayıncıyı temsil etmez.

- preview-assets/game-scene.png: ImageGen ile “üçüncü şahıs kamera açılı, kalıntılar ve sisli vadi içeren, yazısız ve arayüzsüz özgün fantastik oyun sahnesi; 16:9; kenarlarda da ayrıntı” istemiyle üretildi.
- preview-assets/webcam-standin.png: ImageGen ile “kulaklıklı, koyu kapüşonlu, tanınabilir bir gerçek kişiyi temsil etmeyen yetişkin yayıncı kesiti; şeffaf arka plan; webcam estetiği” istemiyle üretildi.