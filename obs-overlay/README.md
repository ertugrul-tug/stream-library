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

## İnteraktif yayın paketi

show-bridge.py, Streamer.bot WebSocket sunucusundan Twitch ve Kick olaylarını alıp sahneler arasında ortak bir yayın durumu tutar. Köprünün WebSocket'i (8765) ve kumanda.html'i servis eden HTTP sunucusu (8766) artık bu bilgisayarın tüm ağ arayüzlerinde dinliyor — yani **aynı wifi'deki telefon veya tabletten de** kumandayı açabilirsin. Streamer.bot için kullanılan 127.0.0.1:8080 portunu değiştirme. kumanda.html OBS kaynağı değildir, sadece kendi tarayıcında (bilgisayar veya telefon) açık tutulur. Köprü yoksa mevcut ortak sohbet ve bildirimler doğrudan Streamer.bot üzerinden çalışmaya devam eder; yeni interaktif alanlar canlı veri alamaz.

**Güvenlik notu:** Bu, kumandayı ev ağındaki herkesin erişebileceği hale getirir (internete değil, sadece aynı wifi'ye açık). Şu anki aksiyonlar (oyun adı, rota, anons, öne çıkanlar) zararsız; ileride timeout/ban gibi moderasyon aksiyonları eklenirse önce bir PIN/şifre kontrolü konulmalı.

1. Bir kere: python -m pip install -r obs-overlay/requirements.txt
2. Yayından önce start-show.cmd dosyasına çift tıkla veya python obs-overlay/show-bridge.py çalıştır. Açılan "Qedy Show Bridge" penceresi telefon için kullanılacak LAN adresini yazdırır, o pencereyi açık bırak. Streamer.bot WebSocket Server da açık olmalı. Köprü bağlantı kurulana kadar yeniden dener.
3. Kumanda otomatik açılır (http://127.0.0.1:8766/kumanda.html). Telefondan/tabletten aynı wifi'deyken "Qedy Show Bridge" penceresindeki `http://<LAN-IP>:8766/kumanda.html` adresini aç. Üstteki durum Streamer.bot bağlı olduğunda yeşile döner. Oyunu, mola notunu ve rota seçeneklerini buradan yaz.
4. Sohbette !rota 1, !rota 2, !rota 3 oyları iki platformdan toplanır. Her kullanıcı her platformda bir güncel oya sahiptir; yeni oy önceki oyunu değiştirir. Kumandada mesajı “Anons yap” ile seçip ekranda öne çıkarabilirsin. “Öne çıkan anlar” alanına yayın sırasında kısa notlar ekleyebilirsin.
5. Açılış sahnesi sohbete yazanları radar listesinde gösterir. Mola sahnesi oyun, dönüş notu ve öne çıkan anları; kapanış sahnesi mesaj, takip, abonelik sayılarını ve notları gösterir. Bunlar köprü başladıktan sonra gelen olaylardır. Geçmiş platform istatistikleri veya otomatik Twitch klipleri içe aktarılmaz.

show-config.json ilk açılıştaki metinleri belirler. Değişen yayın verileri .show-state.json içinde yerel olarak saklanır ve Git'e eklenmez. Dosyada sohbet kullanıcı adları ve mesajları olabilir; paylaşma. Kumandadaki “Yeni yayın başlat” düğmesi bu oturum verilerini sıfırlar. Canlı mesajlar HTML olarak işlenmez, yalnızca düz metin olarak gösterilir. ?sample=1 ile sahnelerde örnek interaktif içerik görülebilir; OBS'ye normal dosya adresini ekle.

## Pusulalı sahne geçişi

pusula-gecis.webm, OBS Stinger geçişinde kullanılacak 1280 × 720, 60 FPS ve şeffaf VP9 videodur. OBS sahne geçişlerine yeni bir Stinger ekle, dosyayı seç ve Transition Point değerini 600 ms yap. Tam örtme anında sahne değişir. OBS sahne/kaynak sırası bu paket tarafından değiştirilmez. Videoyu yeniden üretmek istersen önce python -m pip install Pillow, ardından python obs-overlay/make-stinger.py çalıştır. [OBS Stinger açıklaması](https://obsproject.com/kb/track-matte-stinger-transitions) geçiş noktasını açıklar.

## Önizleme görselleri

Bu iki görsel yalnızca örnek oyun/kamera yerleşimi içindir; normal OBS katmanında gösterilmez. Temsili kameradaki kişi yayıncıyı temsil etmez.

- preview-assets/game-scene.png: ImageGen ile “üçüncü şahıs kamera açılı, kalıntılar ve sisli vadi içeren, yazısız ve arayüzsüz özgün fantastik oyun sahnesi; 16:9; kenarlarda da ayrıntı” istemiyle üretildi.
- preview-assets/webcam-standin.png: ImageGen ile “kulaklıklı, koyu kapüşonlu, tanınabilir bir gerçek kişiyi temsil etmeyen yetişkin yayıncı kesiti; şeffaf arka plan; webcam estetiği” istemiyle üretildi.