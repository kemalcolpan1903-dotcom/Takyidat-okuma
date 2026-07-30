# TAKBİS Okuyucu — Adım Adım Canlıya Alma Rehberi (Yeni Başlayanlar İçin)

Bu rehberi baştan sona, hiçbir teknik bilgin olmadığını varsayarak yazdım.
Sırayla ilerle, hiçbir adımı atlama. Toplam süre ~20-25 dakika.

Sonunda elinde: `https://senin-secgin-isim.onrender.com` adresinden,
şifreyle korunan, herkese açık ama sadece şifreyi bilenlerin kullanabildiği
bir site olacak. **Tamamen ücretsiz.**

---

## BÖLÜM 1 — GitHub Hesabı Açma (kodu depolayacağın yer)

1. Tarayıcıda **github.com** adresine git.
2. Sağ üstteki **Sign up** butonuna tıkla.
3. E-posta adresini gir → şifre belirle → kullanıcı adı seç.
4. Doğrulama adımlarını tamamla (bir kaç basit güvenlik sorusu / robot testi).
5. E-postana gelen doğrulama kodunu gir.
6. Hesap oluştu — bu kadar. Ücretsiz.

## BÖLÜM 2 — Kodu GitHub'a Yükleme

1. GitHub'da sağ üstteki **+** işaretine tıkla → **New repository**.
2. **Repository name** kutusuna bir isim yaz, örn: `takbis-okuyucu`.
3. "Public" seçili kalsın (ücretsiz plan için gerekli).
4. **Create repository** butonuna bas.
5. Açılan sayfada **"uploading an existing file"** yazan mavi linke tıkla.
6. Bilgisayarındaki şu dosyaları sürükleyip bırak (hepsini aynı anda seçebilirsin):
   - `app.py`
   - `parser.py`
   - `requirements.txt`
   - `Procfile`
7. Sayfanın altındaki **Commit changes** butonuna bas.
8. Dosyalar artık GitHub'da — repo sayfasında 4 dosyayı görüyor olman lazım.

## BÖLÜM 3 — Render Hesabı Açma (siteyi burada barındıracağız)

1. Tarayıcıda **render.com** adresine git.
2. **Get Started** veya **Sign Up** butonuna tıkla.
3. **"Sign up with GitHub"** seçeneğini seç (en kolayı bu — ayrı şifre
   oluşturmana gerek kalmaz, GitHub hesabınla giriş yapmış olursun).
4. GitHub açılıp Render'a izin vermeni isteyecek → **Authorize Render** de.
5. Render hesabın oluştu.

## BÖLÜM 4 — Siteyi Yayınlama

1. Render panelinde **New +** butonuna tıkla → **Web Service** seç.
2. Az önce yüklediğin `takbis-okuyucu` reposunu listede göreceksin →
   yanındaki **Connect** butonuna tıkla.
   - Eğer repo listede görünmüyorsa, "Configure GitHub App" linkine
     tıklayıp Render'a repona erişim izni ver.
3. Karşına bir ayar formu çıkacak, şunları doldur:
   - **Name:** İstediğin bir isim (bu, adresinin bir parçası olacak,
     örn. `takbis-okuyucu` yazarsan adresin `takbis-okuyucu.onrender.com` olur)
   - **Region:** Frankfurt (Türkiye'ye en yakın seçenek)
   - **Branch:** main (otomatik gelir, değiştirme)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Instance Type:** **Free** seç (0$/ay yazan)
4. Aşağıda **"Advanced"** yazan yere tıkla, açılan bölümde
   **"Add Environment Variable"** butonuna 2 kere bas ve şunları ekle:

   | Key | Value |
   |---|---|
   | `SITE_PASSWORD` | *(kullanıcıların gireceği şifre — kendin belirle, örn: `Pendik2026!`)* |
   | `SECRET_KEY` | *(rastgele, kimsenin bilmediği uzun bir metin — örn: `x7Ka9pQz2mLtV4rWnB8s`)* |

   > `SITE_PASSWORD` = sitene girecek kişilerin kullanacağı şifre.
   > `SECRET_KEY` = sadece Flask'ın oturum (giriş) bilgisini güvenli
   > tutması için kullandığı teknik bir anahtar; kimseyle paylaşmıyorsun,
   > rastgele bir şey yazman yeterli.

5. En altta **Create Web Service** butonuna bas.
6. Render otomatik olarak kodu indirip kuracak — bu 2-5 dakika sürer.
   Ekranda akan loglarda en altta **"Live"** yazısını ve yeşil bir
   nokta görünce site hazır demektir.
7. Sayfanın üst kısmında `https://takbis-okuyucu.onrender.com` gibi bir
   adres göreceksin — bu senin sitenin linki.

## BÖLÜM 5 — Siteyi Kullanma

1. Adrese gidince karşına şifre giriş ekranı çıkacak.
2. `SITE_PASSWORD` olarak belirlediğin şifreyi gir.
3. Giriş yapınca PDF yükleme ekranı açılır — normal şekilde kullan.
4. Şifreyi kullanıcılarına (ör. meslektaşların) sen paylaşırsın; onlar da
   aynı adrese girip aynı şifreyi yazarak kullanabilir.
5. Şifreyi değiştirmek istersen: Render panelinde projenin
   **Environment** sekmesine gidip `SITE_PASSWORD` değerini güncelle,
   kaydet — site birkaç saniyede otomatik yeniden başlar.

## Bilmen Gereken Küçük Detaylar

- **Ücretsiz plan uyku modu:** Site 15 dakika kullanılmazsa "uyur";
  bir sonraki ziyaretçi siteyi açtığında ilk yüklemede 20-30 saniye
  bekleme olabilir. Bu normal, ücretsiz planın bir özelliği.
- **Dosyalar saklanmıyor:** Yüklenen PDF'ler işlendikten hemen sonra
  sunucudan siliniyor, kalıcı olarak hiçbir yerde durmuyor.
- **Kod güncellemesi:** İleride app.py veya parser.py'de değişiklik
  yaparsan, GitHub'daki dosyayı güncellemen yeterli — Render otomatik
  algılayıp siteyi yeniden yayınlar.
- **Şifreyi unutma:** Render'ın Environment sekmesinden istediğin an
  tekrar bakabilirsin, kaybolmaz.

Bir yerde takılırsan, hangi adımda olduğunu ve ekranda ne gördüğünü
söyle, oradan devam ettiririm.
