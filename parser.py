import re
import pdfplumber


def _clean_cell(cell):
    """Tabloya PDF watermarkinden (BİLGİ AMAÇLIDIR) sızan tek karakterlik
    gürültü satırlarını temizler ve satırları tek satıra birleştirir."""
    if not cell:
        return ""
    lines = [l.strip() for l in cell.split("\n")]
    lines = [l for l in lines if len(l) > 1]
    return " ".join(lines).strip()


def _extract_tarih_yevmiye(cell_text):
    """'Pendik - 25-02-2020 14:30 - 8779' gibi bir hücreden tarih ve
    yevmiye no'yu ayıklar."""
    date_m = re.search(r"(\d{1,2}-\d{1,2}-\d{4})", cell_text)
    # yevmiye no: metindeki son bağımsız sayı grubu
    numbers = re.findall(r"\b(\d{1,7})\b", cell_text)
    tarih = date_m.group(1) if date_m else ""
    yevmiye = numbers[-1] if numbers else ""
    return tarih, yevmiye


def _format_tarih_saat(raw):
    """'13-5-2026-10:04' -> '13.05.2026 tarih saat 10.04'"""
    m = re.match(r"(\d{1,2})-(\d{1,2})-(\d{4})-(\d{1,2}):(\d{2})", raw)
    if not m:
        return raw
    gun, ay, yil, saat, dakika = m.groups()
    return f"{int(gun):02d}.{int(ay):02d}.{yil} tarih saat {int(saat):02d}.{dakika}"


def _extract_rehin_serh(full_text):
    """İpotek kaydının hemen altındaki 'Rehine Ait Şerh Beyan Bilgisi' tablosundaki
    kayıtları (ör. İİK 150/c ile satışa gidilmesi şerhi) sayfa düz metninden çıkarır.
    Bu tablo bazı belgelerde (filigran/çizgi çakışması yüzünden) pdfplumber'ın
    tablo tespitini tamamen bozduğu için tablo yerine düz metin üzerinden,
    daha toleranslı bir şekilde okunuyor. Bu belgelerde sütunlar öyle karışabiliyor
    ki tarih/saat parçaları cümlenin ortasına düşebiliyor (ör. '...İSTANBUL 03-08-20
    ANADOLU...ESAS 26 11:26 sayılı Resmi Yazı - 15452'), bu yüzden tarih parçaları
    metnin herhangi bir yerinde aranıp açıklamadan çıkarılıyor."""
    kayitlar = []
    seen = set()
    for block_m in re.finditer(
        r"Rehine Ait Şerh Beyan Bilgisi(.*?)(?=Rehine Ait Şerh Beyan Bilgisi|\bIpotek\b|BİLGİ AMAÇLIDIR|\Z)",
        full_text, re.DOTALL,
    ):
        # Watermark sızıntısından gelen tek karakterlik satırları temizle
        # (_clean_cell tablo hücreleri için kullanılan mantığın aynısı).
        cleaned = _clean_cell(block_m.group(1))
        # Sütun sırası belgeye göre değişebiliyor (ör. 'Terkin' bazen
        # 'Yevmiye'den önce geliyor) ve filigran harfi kayıt etiketine
        # bitişebiliyor (ör. 'BSerh'), bu yüzden \b sınırı aramadan
        # ilk gerçek kayıt etiketini (Beyan/Serh/İrtifak) arıyoruz.
        m = re.search(r"(Beyan|Serh|İrtifak)\s+(.*)", cleaned)
        if not m:
            continue
        tip, rest = m.group(1), m.group(2)

        # Yevmiye no'su "- NNNNN" şeklinde metinde bir yerde geçer; ondan
        # sonrası (sayfa numarası, alt bilgi metni vb.) atılır.
        yev_m = re.search(r"-\s*(\d{3,7})\b", rest)
        if not yev_m:
            continue
        yevmiye = yev_m.group(1)
        content = rest[:yev_m.start()]

        # Tarih iki parçaya bölünmüş olabilir (ör. '03-08-20' + '26 11:26'),
        # ya da tek parça halinde ('31-07-2026') gelebilir; her ikisini de dene.
        date1_m = re.search(r"\b(\d{1,2}-\d{1,2}-20)\b", content)
        date2_m = re.search(r"\b(\d{2})\s+\d{1,2}:\d{2}\b", content)
        if date1_m and date2_m:
            tarih = date1_m.group(1) + date2_m.group(1)
        else:
            single_date_m = re.search(r"\b(\d{1,2}-\d{1,2}-\d{4})\b", content)
            tarih = single_date_m.group(1) if single_date_m else ""

        aciklama = content
        if date1_m:
            aciklama = aciklama.replace(date1_m.group(0), " ", 1)
        if date2_m:
            aciklama = aciklama.replace(date2_m.group(0), " ", 1)
        aciklama = re.sub(r"\s+", " ", aciklama).strip()
        if not aciklama:
            continue

        key = (tip, aciklama, tarih, yevmiye)
        if key in seen:
            continue
        seen.add(key)
        kayitlar.append({"tip": tip, "aciklama": aciklama, "tarih": tarih, "yevmiye": yevmiye})
    return kayitlar



def extract_takbis_data(pdf_path):
    """Bir Web Tapu / TAKBİS PDF'inden takyidat verilerini çıkarır."""
    data = {
        "tarih_saat": "",
        "il_ilce": "",
        "ada_parsel": "",
        "bbno": "",
        "kimlik_no": "",
        "kayitlar": [],   # taşınmaza + mülkiyete ait beyan/şerh/irtifak kayıtları
        "ipotekler": [],
    }

    seen_kayit = set()
    seen_ipotek = set()

    current_section = None  # 'sb' (şerh/beyan) | 'ipotek' | None
    last_kayit = None  # sayfa sınırında bölünen kaydın devamını eşlemek için

    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join((p.extract_text() or "") for p in pdf.pages)

        m = re.search(r"Tarih:\s*([\d\-:]+)", full_text)
        if m:
            data["tarih_saat"] = _format_tarih_saat(m.group(1))

        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table:
                    continue

                header_joined = " ".join(_clean_cell(c) for c in table[0] if c)

                # --- Genel taşınmaz bilgi tablosu (key:value çiftleri) ---
                info_markers = ("Ada/Parsel", "İl/İlçe", "Taşınmaz Kimlik No", "Blok/Kat/Giriş/BBNo")
                if any(marker in _clean_cell(row[0]) for row in table if row for marker in info_markers):
                    for row in table:
                        for i in range(0, len(row) - 1, 2):
                            key = _clean_cell(row[i])
                            val = _clean_cell(row[i + 1]) if i + 1 < len(row) else ""
                            if key.startswith("Ada/Parsel"):
                                data["ada_parsel"] = val
                            elif key.startswith("İl/İlçe"):
                                data["il_ilce"] = val
                            elif key.startswith("Taşınmaz Kimlik No"):
                                data["kimlik_no"] = val
                            elif key.startswith("Blok/Kat/Giriş/BBNo"):
                                bb = val.split("/")[-1].strip()
                                data["bbno"] = bb
                    continue

                table_text = " ".join(_clean_cell(c) for row in table for c in row if c)

                # --- Şerh/Beyan/İrtifak başlık tablosu tespiti ---
                # Not: Bu tablonun "Açıklama" hücrelerinde haciz metinleri
                # geçtiğinde içinde de "Alacaklı"/"Borç" kelimeleri geçebilir
                # (ör. "İcrai Haciz ... Alacaklı : X Borç : Y TL"), bu yüzden
                # bu tespit her zaman ipotek tespitinden ÖNCE ve öncelikli
                # olarak yapılmalı (elif zinciri ile).
                if "Ş/B/İ" in header_joined and "Açıklama" in header_joined:
                    current_section = "sb"
                    # başlık ve veri aynı tabloda birlikte gelebilir, atlamadan devam et

                # --- Rehin/İpotek başlık tablosu tespiti (bazen aynı tablo içinde
                # hem başlık satırı hem de - sıkışmış - veri satırı birlikte gelir).
                # "Faiz" ve "Derece"/"Müşterek" kelimeleri sadece gerçek ipotek
                # tablosunun başlığında geçer; sadece "Alacaklı"/"Borç" kontrolü
                # haciz açıklama metinleriyle yanlış eşleşiyordu.
                elif "Faiz" in table_text and ("Derece" in table_text or "Müşterek" in table_text):
                    current_section = "ipotek"
                    last_kayit = None
                    # bu tabloda veri satırı da olabilir, atlamadan devam et

                # Mülkiyet (hissedarlık) tablosu ya da diğer tablolar -> atla
                elif "Sistem" in header_joined and "El Birliği" in header_joined:
                    current_section = None
                    last_kayit = None
                    continue
                elif "İpoteğin Konulduğu" in header_joined or (
                    "Hisse Pay" in header_joined and "Borçlu Malik" in header_joined
                ):
                    current_section = None
                    last_kayit = None
                    continue

                # --- Veri satırlarını işle ---
                if current_section == "sb":
                    for row in table:
                        if not row or len(row) < 2:
                            continue
                        tip = _clean_cell(row[0])

                        # Tip boşsa: bu satır muhtemelen bir önceki kaydın
                        # sayfa sınırında bölünmüş devamıdır (açıklama ve/veya
                        # yevmiye no bir sonraki sayfaya taşmış olabilir).
                        if tip == "":
                            if last_kayit is None:
                                continue
                            cont_aciklama = _clean_cell(row[1]) if len(row) > 1 else ""
                            tarih_yev_cell = ""
                            for c in row[2:]:
                                cc = _clean_cell(c)
                                if cc:
                                    tarih_yev_cell = cc
                                    break
                            if cont_aciklama:
                                last_kayit["aciklama"] = f"{last_kayit['aciklama']} {cont_aciklama}".strip()
                            if tarih_yev_cell:
                                if re.fullmatch(r"\d{1,7}", tarih_yev_cell):
                                    # sadece yevmiye no'su devam ediyor
                                    last_kayit["yevmiye"] = tarih_yev_cell
                                else:
                                    tarih2, yev2 = _extract_tarih_yevmiye(tarih_yev_cell)
                                    if not last_kayit["tarih"] and tarih2:
                                        last_kayit["tarih"] = tarih2
                                    if yev2:
                                        last_kayit["yevmiye"] = yev2
                            continue

                        if tip not in ("Beyan", "Şerh", "Serh", "İrtifak", "Irtifak"):
                            continue
                        aciklama = _clean_cell(row[1])
                        # tarih/yevmiye hücresi genelde sondan bir önceki hücrede
                        tarih_yev_cell = ""
                        for c in row[2:]:
                            cc = _clean_cell(c)
                            if re.search(r"\d{1,2}-\d{1,2}-\d{4}", cc):
                                tarih_yev_cell = cc
                                break
                        tarih, yevmiye = _extract_tarih_yevmiye(tarih_yev_cell)
                        if not aciklama:
                            continue
                        key = (tip, aciklama, tarih, yevmiye)
                        if key in seen_kayit:
                            continue
                        seen_kayit.add(key)
                        data["kayitlar"].append({
                            "tip": tip, "aciklama": aciklama,
                            "tarih": tarih, "yevmiye": yevmiye,
                        })
                        last_kayit = data["kayitlar"][-1]

                elif current_section == "ipotek":
                    for row in table:
                        if not row:
                            continue
                        # Bazı PDF'lerde bu satırın tüm hücreleri tek hücrede
                        # sıkışmış olarak gelir; satır bazlı (newline korunmuş)
                        # temiz metni kullanıyoruz ki isim devam satırlarını
                        # veri satırından ayırt edebilelim.
                        raw_lines = []
                        for c in row:
                            if not c:
                                continue
                            raw_lines.extend(
                                l.strip() for l in c.split("\n") if len(l.strip()) > 1
                            )
                        if not raw_lines:
                            continue
                        joined = " ".join(raw_lines)
                        if "Alacaklı" in joined and "Borç" in joined and "Tesis" in joined:
                            continue  # saf başlık satırı

                        main_line = None
                        for l in raw_lines:
                            if re.search(r"\b(Hayır|Evet)\b", l):
                                main_line = l
                                main_idx = raw_lines.index(l)
                                break
                        if not main_line:
                            continue

                        alacakli_m = re.search(
                            r"(?:\(SN:\d+\)\s*)?(.*?)\s*(?:Hayır|Evet)\b", main_line
                        )
                        # Borç tutarı ile para birimi (TL/EUR/...) bazı belgelerde
                        # PDF satır kaydırması yüzünden aynı satırda gelmeyip
                        # tutar main_line'da, birim ise bir sonraki satırda kalabiliyor
                        # (ör. "...Hayır 70000000000.00 Yıllık..." / "VKN:... TL %17,70").
                        # Bu yüzden tutarı Hayır/Evet'ten hemen sonraki sayı olarak,
                        # birimi ise main_line + bir sonraki satırda ayrı arıyoruz.
                        amt_m = re.search(r"(?:Hayır|Evet)\s+([\d\.,-]+)", main_line)
                        window = " ".join(raw_lines[main_idx:main_idx + 2])
                        currency_m = re.search(r"\b(TL|EUR|USD|GBP)\b", window)
                        if amt_m and currency_m:
                            borc_m = amt_m
                            borc_unit = currency_m.group(1)
                        else:
                            borc_m = re.search(r"([\d\.,-]+)\s*(TL|EUR|USD|GBP)\b", main_line)
                            borc_unit = borc_m.group(2) if borc_m else ""
                        derece_m = re.search(r"\b(\d+)/(\d+)\b", main_line)
                        tarih_m = re.search(r"(\d{1,2}-\d{1,2}-\d{4})", main_line)

                        # Alacaklı adı boş olabilir (ör. 'BosRehin' tablosundaki
                        # sahipsiz ipotek kayıtları) — bu durumda kayıt yine de
                        # işlenir, sadece isim boş bırakılır (rapor katmanında
                        # 'Lehtarı belli olmayan' olarak yazılır).
                        if not (borc_m and tarih_m):
                            continue

                        alacakli = alacakli_m.group(1).strip() if alacakli_m else ""

                        # Yevmiye no genelde satır sonunda "- 29430" şeklinde durur.
                        # Bazı belgelerde hücre sardığı için sadece "-" ile biter ve
                        # asıl sayı bir alt satıra taşar (o satırda VKN devamı da
                        # olabilir, ör. "VKN:3880023334 29430").
                        name_extra = ""
                        end_num_m = re.search(r"-\s*(\d{3,7})\s*$", main_line)
                        if end_num_m:
                            yevmiye = end_num_m.group(1)
                        else:
                            yevmiye = ""
                            if main_idx + 1 < len(raw_lines):
                                next_line = raw_lines[main_idx + 1]
                                next_num_m = re.search(r"(\d{3,7})\s*$", next_line)
                                if next_num_m:
                                    yevmiye = next_num_m.group(1)
                                    name_extra = next_line[:next_num_m.start()].strip()

                        # İsim, tablo satırı sarıldığı için bir sonraki satıra
                        # taşmış olabilir (ör. "BANKASI A.Ş. VKN:..."). Bu satır
                        # yeni bir tablo/bölüm başlığı ya da salt rakam değilse isme ekle.
                        # VKN numarasından SONRA gelen herhangi bir kelime (ör. kaymış
                        # faiz açıklaması 'değişken') isme dahil edilmez.
                        if name_extra:
                            vkn_m = re.search(r"VKN:\d+", name_extra)
                            if vkn_m:
                                name_extra = name_extra[:vkn_m.end()]
                            alacakli = f"{alacakli} {name_extra}".strip()
                        else:
                            stop_words = ("İpoteğin", "Taşınmaz", "Payda", "Tarih Yev", "Hisse")
                            for l in raw_lines[main_idx + 1:main_idx + 2]:
                                if re.fullmatch(r"\d+", l.strip()):
                                    break
                                # Faiz oranı (%) ya da para birimi geçen satırlar isim
                                # devamı değil, kaymış borç/faiz verisidir — isme eklenmez.
                                if "%" in l or re.search(r"\b(TL|EUR|USD|GBP)\b", l):
                                    break
                                vkn_m = re.search(r"VKN:\d+", l)
                                if vkn_m:
                                    l = l[:vkn_m.end()]
                                if not any(l.startswith(sw) for sw in stop_words):
                                    alacakli = f"{alacakli} {l}".strip()
                                break

                        alacakli = re.sub(r"\s*VKN:\d+\s*", " ", alacakli)
                        alacakli = re.sub(r"\s+", " ", alacakli).strip()
                        borc = f"{borc_m.group(1)} {borc_unit}"
                        # Derece/Sıra "X/0" ise sadece "X" gösterilir (sıra
                        # belirtilmemiş demektir); "X/0" dışındaki durumlarda
                        # (ör. "1/1", "1/2") tam kesir korunur.
                        if derece_m:
                            derece_ana, derece_sira = derece_m.group(1), derece_m.group(2)
                            derece = derece_ana if derece_sira == "0" else f"{derece_ana}/{derece_sira}"
                        else:
                            derece = ""
                        tarih = tarih_m.group(1)

                        key = (alacakli, borc, derece, tarih, yevmiye)
                        if key in seen_ipotek:
                            continue
                        seen_ipotek.add(key)
                        data["ipotekler"].append({
                            "alacakli": alacakli, "borc": borc,
                            "derece": derece, "tarih": tarih, "yevmiye": yevmiye,
                        })

    # İpotek altındaki "Rehine Ait Şerh Beyan Bilgisi" kayıtları (ör. İİK 150/c
    # ile satışa gidilmesi şerhi) — bazı belgelerde tablo tespiti filigran/çizgi
    # çakışmasıyla bozulduğu için bunlar ayrıca düz metinden okunuyor ve
    # ana tablo taramasında zaten yakalanmışsa tekrar eklenmiyor (dedup).
    for k in _extract_rehin_serh(full_text):
        key = (k["tip"], k["aciklama"], k["tarih"], k["yevmiye"])
        if key in seen_kayit:
            continue
        seen_kayit.add(key)
        data["kayitlar"].append(k)

    return data


_HACIZ_LABELS = ("İcrai Haciz", "İhtiyati Haciz", "Kamu Haczi")


def _tr_lower(s):
    """Türkçe karakterler için doğru küçük harfe çevirme (İ->i, I->ı)."""
    return s.replace("İ", "i").replace("I", "ı").lower()


def _haciz_label(aciklama):
    """Bir açıklama metninin haciz kaydı olup olmadığını ve türünü döndürür.
    Haciz kaydı değilse None döner. PDF'teki filigran sızıntısından satır
    başına tek bir karakter/kelime karışabildiği için (ör. 'B İcrai Haciz : ...'),
    etiketi metnin tamamında değil sadece başındaki birkaç kelimede arıyoruz."""
    text = aciklama.strip()
    head = " ".join(text.split()[:6])
    for label in _HACIZ_LABELS:
        if label in head:
            return label
    if "haciz" in _tr_lower(head):
        return "Diğer Haciz"
    return None


def _split_haciz(kayitlar):
    """Kayıtları haciz olanlar (tip etiketine göre gruplu) ve olmayanlar
    olarak ikiye ayırır. Haciz grupları eklenme sırasına göre döner."""
    normal = []
    haciz_groups = {}   # label -> list of kayit dict
    haciz_order = []
    for k in kayitlar:
        label = _haciz_label(k["aciklama"])
        if label is None:
            normal.append(k)
        else:
            if label not in haciz_groups:
                haciz_groups[label] = []
                haciz_order.append(label)
            haciz_groups[label].append(k)
    return normal, haciz_order, haciz_groups


def _haciz_lines(haciz_order, haciz_groups, kayit_to_line):
    """Haciz gruplarını rapor satırlarına çevirir. Toplam haciz sayısı 3'ten
    fazlaysa her tür için 'N adet <tür> kararı' şeklinde özet satır(lar)ı,
    değilse (3 veya daha az) kayıtları tek tek listeler."""
    total = sum(len(v) for v in haciz_groups.values())
    lines = []
    if total == 0:
        return lines
    if total > 3:
        summary_parts = []
        for label in haciz_order:
            count = len(haciz_groups[label])
            summary_parts.append(f"{count} adet {_tr_lower(label)} kararı")
        lines.append(", ".join(summary_parts) + " bulunmaktadır.")
    else:
        for label in haciz_order:
            for k in haciz_groups[label]:
                lines.append(kayit_to_line(k))
    return lines


def _ipotek_lines(ipotekler):
    """İpotek kayıtlarını rapor satırlarına çevirir. Alacaklısı boş olan
    (ör. 'BosRehin' tablosundaki) kayıtlar için 'Lehtarı belli olmayan' ifadesi
    kullanılır."""
    lines = []
    for ip in ipotekler:
        tarih_dot = ip["tarih"].replace("-", ".")
        derece_txt = f"{ip['derece']}." if ip["derece"] else ""
        if ip["alacakli"]:
            baslangic = f"{ip['alacakli']} lehine "
        else:
            baslangic = "Lehtarı belli olmayan "
        lines.append(
            f"{baslangic}{ip['borc']} bedelle {derece_txt}dereceden "
            f"ipotek kaydı bulunmaktadır. {tarih_dot} Yev: {ip['yevmiye']}"
        )
    return lines


def _kayit_to_line(k):
    if k["tarih"]:
        return f"{k['tip']} {k['aciklama']} ({k['tarih']} tarih-{k['yevmiye']} yevmiye)"
    return f"{k['tip']} {k['aciklama']}"


def _format_body(data):
    """Bir taşınmazın kayıtlarını (haciz gruplaması dahil) ve ipotek
    kayıtlarını rapor satırları olarak döndürür — üstteki genel 'Web Tapu
    Müdürlüğünden ... alınmıştır' cümlesi hariç. Hem tekli belge raporunda
    hem de çoklu (parsel bazlı) raporda ortak kullanılır."""
    lines = []
    normal, haciz_order, haciz_groups = _split_haciz(data["kayitlar"])

    for k in normal:
        lines.append(_kayit_to_line(k))

    lines.extend(_haciz_lines(haciz_order, haciz_groups, _kayit_to_line))

    if data["ipotekler"]:
        lines.append("İpotek kaydı:")
        lines.extend(_ipotek_lines(data["ipotekler"]))

    if not data["kayitlar"] and not data["ipotekler"]:
        lines.append("Taşınmaz üzerinde herhangi bir takyidat kaydına rastlanmamıştır.")

    return lines


def format_report(data):
    lines = []
    if data["tarih_saat"]:
        lines.append(
            f"Taşınmazın takyidat mülkiyet bilgileri Web Tapu Müdürlüğünden "
            f"{data['tarih_saat']} de digital takbis belgesi alınarak "
            f"bakılmış olup takbis belgesi ekte yer almaktadır."
        )
    lines.extend(_format_body(data))
    return "\n".join(lines)


def _parsel_label(ada_parsel):
    """'0/1908' -> '1908 PARSEL', '6922/4' -> '6922 ADA - 4 PARSEL'."""
    if not ada_parsel or "/" not in ada_parsel:
        return ada_parsel or "TAŞINMAZ"
    ada, parsel = ada_parsel.split("/", 1)
    ada, parsel = ada.strip(), parsel.strip()
    if not ada or ada == "0":
        return f"{parsel} PARSEL"
    return f"{ada} ADA - {parsel} PARSEL"


def _bbno_label(bbnos):
    nums = sorted(bbnos, key=lambda x: (len(x), x))
    return "-".join(nums)


def merge_multi(pdf_paths_with_names):
    """Birden fazla TAKBİS PDF'ini birleştirir. Aynı (tip, tarih, yevmiye)
    ile gelen kayıtları tek satırda toplayıp hangi bağımsız bölümler için
    ortak (müşterek) olduğunu belirtir. Bir PDF okunamazsa (bozuk dosya,
    beklenmeyen format vb.) tüm toplu işlemi durdurmak yerine o dosyayı
    atlayıp diğerleriyle devam eder; atlanan dosyalar rapor sonunda listelenir."""
    all_data = []
    failed = []  # (display_name, hata mesajı)
    for path, display_name in pdf_paths_with_names:
        try:
            d = extract_takbis_data(path)
        except Exception as e:
            failed.append((display_name, str(e)))
            continue
        bbno = d["bbno"] or display_name
        all_data.append((bbno, d))

    kayit_map = {}   # (tip, tarih, yevmiye) -> {"aciklama":..., "bbnos": set(), "order": int}
    ipotek_map = {}  # (alacakli, borc, derece, tarih, yevmiye) -> {"bbnos": set(), "order": int}
    order_counter = [0]
    tarih_saat = ""
    il_ilce = ""

    for bbno, d in all_data:
        if not tarih_saat:
            tarih_saat = d["tarih_saat"]
        if not il_ilce:
            il_ilce = d["il_ilce"]
        for k in d["kayitlar"]:
            key = (k["tip"], k["tarih"], k["yevmiye"])
            if key not in kayit_map:
                order_counter[0] += 1
                kayit_map[key] = {"aciklama": k["aciklama"], "bbnos": set(), "order": order_counter[0]}
            kayit_map[key]["bbnos"].add(bbno)
        for ip in d["ipotekler"]:
            key = (ip["alacakli"], ip["borc"], ip["derece"], ip["tarih"], ip["yevmiye"])
            if key not in ipotek_map:
                order_counter[0] += 1
                ipotek_map[key] = {"bbnos": set(), "order": order_counter[0]}
            ipotek_map[key]["bbnos"].add(bbno)

    lines = []
    if tarih_saat:
        lines.append(
            f"Taşınmazın takyidat mülkiyet bilgileri Web Tapu Müdürlüğünden "
            f"{tarih_saat} de digital takbis belgesi alınarak "
            f"bakılmış olup takbis belgesi ekte yer almaktadır."
        )

    def kayit_map_to_line(tip, tarih, yevmiye, info):
        if tarih:
            line = f"{tip} {info['aciklama']} ({tarih} tarih-{yevmiye} yevmiye)"
        else:
            line = f"{tip} {info['aciklama']}"
        if len(info["bbnos"]) > 1:
            line += f" — {_bbno_label(info['bbnos'])} nolu bağımsız bölümler için müşterektir."
        return line

    sorted_kayitlar = sorted(kayit_map.items(), key=lambda x: x[1]["order"])
    normal_entries = []
    haciz_order = []
    haciz_groups = {}
    for (tip, tarih, yevmiye), info in sorted_kayitlar:
        label = _haciz_label(info["aciklama"])
        if label is None:
            normal_entries.append(((tip, tarih, yevmiye), info))
        else:
            if label not in haciz_groups:
                haciz_groups[label] = []
                haciz_order.append(label)
            haciz_groups[label].append(((tip, tarih, yevmiye), info))

    for (tip, tarih, yevmiye), info in normal_entries:
        lines.append(kayit_map_to_line(tip, tarih, yevmiye, info))

    total_haciz = sum(len(v) for v in haciz_groups.values())
    if total_haciz > 3:
        summary_parts = []
        for label in haciz_order:
            summary_parts.append(f"{len(haciz_groups[label])} adet {_tr_lower(label)} kararı")
        lines.append(", ".join(summary_parts) + " bulunmaktadır.")
    else:
        for label in haciz_order:
            for (tip, tarih, yevmiye), info in haciz_groups[label]:
                lines.append(kayit_map_to_line(tip, tarih, yevmiye, info))

def merge_multi(pdf_paths_with_names):
    """Birden fazla TAKBİS PDF'ini (çoklu taşınmaz/parsel) tek raporda birleştirir.
    Kayıtları parseller arasında birleştirip 'müşterektir' notu düşmek yerine —
    her parsel kendi başlığı altında (ör. '1908 PARSEL:') kendi kayıtlarıyla
    ayrı ayrı listelenir. Üstte tek bir genel 'Web Tapu Müdürlüğünden ...
    alınmıştır' cümlesi yer alır. Bir PDF okunamazsa (bozuk dosya, beklenmeyen
    format vb.) tüm toplu işlemi durdurmak yerine o dosya atlanıp diğerleriyle
    devam edilir; atlanan dosyalar rapor sonunda ayrıca listelenir."""
    results = []  # (label, data)
    failed = []  # (display_name, hata mesajı)
    tarih_saat = ""
    for path, display_name in pdf_paths_with_names:
        try:
            d = extract_takbis_data(path)
        except Exception as e:
            failed.append((display_name, str(e)))
            continue
        if not tarih_saat:
            tarih_saat = d["tarih_saat"]
        label = _parsel_label(d["ada_parsel"]) or display_name
        results.append((label, d))

    lines = []
    if tarih_saat:
        lines.append(
            f"Taşınmazın takyidat mülkiyet bilgileri Web Tapu Müdürlüğünden "
            f"{tarih_saat} de digital takbis belgesi alınarak "
            f"bakılmış olup takbis belgesi ekte yer almaktadır."
        )

    for i, (label, d) in enumerate(results):
        if i > 0 or tarih_saat:
            lines.append("")
        lines.append(f"{label}:")
        lines.extend(_format_body(d))

    if not results and not failed:
        lines.append("Taşınmaz(lar) üzerinde herhangi bir takyidat kaydına rastlanmamıştır.")

    if failed:
        lines.append("")
        lines.append("Not: Aşağıdaki dosya(lar) okunamadığı için rapora dahil edilemedi:")
        for name, err in failed:
            lines.append(f"- {name} ({err})")

    return "\n".join(lines)


if __name__ == "__main__":
    d = extract_takbis_data("/mnt/user-data/uploads/takbis.pdf")
    import json
    print(json.dumps(d, ensure_ascii=False, indent=2))
    print("----- RAPOR -----")
    print(format_report(d))
