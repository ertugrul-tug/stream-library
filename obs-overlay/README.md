# Kaptan Qedy OBS yayın katmanı

overlay.html, mevcut sitenin görsel dilini kullanan tek OBS Browser Source katmanıdır. Oyun ve kamera görüntüsü şeffaf alanların arkasında OBS kaynakları olarak kalır. Twitch ile Kick mesajları aynı sohbet kutusunda, platform etiketleriyle görünür. Twitch bildirimleri solda, Kick bildirimleri sağda animasyon ve kısa bir sesle çıkar. Aynı anda gelen iki platformun bildirimleri birlikte görünebilir.

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

## Sahne geçişi

Bu dosya sahne üzerindeki görsel katmandır. OBS'nin iki sahne arasında tüm ekranı kaplayan gerçek geçişi için ayrıca bir Stinger video dosyası gerekir.
## Önizleme görselleri

Bu iki görsel yalnızca örnek oyun/kamera yerleşimi içindir; normal OBS katmanında gösterilmez. Temsili kameradaki kişi yayıncıyı temsil etmez.

- preview-assets/game-scene.png: ImageGen ile “üçüncü şahıs kamera açılı, kalıntılar ve sisli vadi içeren, yazısız ve arayüzsüz özgün fantastik oyun sahnesi; 16:9; kenarlarda da ayrıntı” istemiyle üretildi.
- preview-assets/webcam-standin.png: ImageGen ile “kulaklıklı, koyu kapüşonlu, tanınabilir bir gerçek kişiyi temsil etmeyen yetişkin yayıncı kesiti; şeffaf arka plan; webcam estetiği” istemiyle üretildi.