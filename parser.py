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
                    # bu tabloda veri satırı da olabilir, atlamadan devam et

                # Mülkiyet (hissedarlık) tablosu ya da diğer tablolar -> atla
                elif "Sistem" in header_joined and "El Birliği" in header_joined:
                    current_section = None
                    continue
                elif "İpoteğin Konulduğu" in header_joined or (
                    "Hisse Pay" in header_joined and "Borçlu Malik" in header_joined
                ):
                    current_section = None
                    continue

                # --- Veri satırlarını işle ---
                if current_section == "sb":
                    for row in table:
                        if not row or len(row) < 2:
                            continue
                        tip = _clean_cell(row[0])
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
                            r"(?:\(SN:\d+\)\s*)?(.+?)\s+(?:Hayır|Evet)\b", main_line
                        )
                        borc_m = re.search(r"([\d\.,]+)\s*(TL|EUR|USD|GBP)\b", main_line)
                        derece_m = re.search(r"\b(\d+)/(\d+)\b", main_line)
                        tarih_m = re.search(r"(\d{1,2}-\d{1,2}-\d{4})", main_line)

                        if not (alacakli_m and borc_m and tarih_m):
                            continue

                        alacakli = alacakli_m.group(1).strip()

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
                        if name_extra:
                            alacakli = f"{alacakli} {name_extra}".strip()
                        else:
                            stop_words = ("İpoteğin", "Taşınmaz", "Payda", "Tarih Yev", "Hisse")
                            for l in raw_lines[main_idx + 1:main_idx + 2]:
                                if re.fullmatch(r"\d+", l.strip()):
                                    break
                                if not any(l.startswith(sw) for sw in stop_words):
                                    alacakli = f"{alacakli} {l}".strip()
                                break

                        alacakli = re.sub(r"\s*VKN:\d+\s*", " ", alacakli)
                        alacakli = re.sub(r"\s+", " ", alacakli).strip()
                        borc = f"{borc_m.group(1)} {borc_m.group(2)}"
                        derece = derece_m.group(1) if derece_m else ""
                        tarih = tarih_m.group(1)

                        key = (alacakli, borc, derece, tarih, yevmiye)
                        if key in seen_ipotek:
                            continue
                        seen_ipotek.add(key)
                        data["ipotekler"].append({
                            "alacakli": alacakli, "borc": borc,
                            "derece": derece, "tarih": tarih, "yevmiye": yevmiye,
                        })

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


def format_report(data):
    lines = []
    if data["tarih_saat"]:
        lines.append(
            f"Taşınmazın takyidat mülkiyet bilgileri Web Tapu Müdürlüğünden "
            f"{data['tarih_saat']} de digital takbis belgesi alınarak "
            f"bakılmış olup takbis belgesi ekte yer almaktadır."
        )

    def kayit_to_line(k):
        if k["tarih"]:
            return f"{k['tip']} {k['aciklama']} ({k['tarih']} tarih-{k['yevmiye']} yevmiye)"
        return f"{k['tip']} {k['aciklama']}"

    normal, haciz_order, haciz_groups = _split_haciz(data["kayitlar"])

    for k in normal:
        lines.append(kayit_to_line(k))

    lines.extend(_haciz_lines(haciz_order, haciz_groups, kayit_to_line))

    if data["ipotekler"]:
        lines.append("İpotek kaydı:")
        for ip in data["ipotekler"]:
            tarih_dot = ip["tarih"].replace("-", ".")
            derece_txt = f"{ip['derece']}." if ip['derece'] else ""
            lines.append(
                f"{ip['alacakli']} lehine {ip['borc']} bedelle {derece_txt}dereceden "
                f"ipotek kaydı bulunmaktadır. {tarih_dot} Yev: {ip['yevmiye']}"
            )

    if not data["kayitlar"] and not data["ipotekler"]:
        lines.append("Taşınmaz üzerinde herhangi bir takyidat kaydına rastlanmamıştır.")

    return "\n".join(lines)


def _bbno_label(bbnos):
    nums = sorted(bbnos, key=lambda x: (len(x), x))
    return "-".join(nums)


def merge_multi(pdf_paths_with_names):
    """Birden fazla TAKBİS PDF'ini birleştirir. Aynı (tip, tarih, yevmiye)
    ile gelen kayıtları tek satırda toplayıp hangi bağımsız bölümler için
    ortak (müşterek) olduğunu belirtir."""
    all_data = []
    for path, display_name in pdf_paths_with_names:
        d = extract_takbis_data(path)
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

    if ipotek_map:
        lines.append("İpotek kaydı:")
        for (alacakli, borc, derece, tarih, yevmiye), info in sorted(
            ipotek_map.items(), key=lambda x: x[1]["order"]
        ):
            tarih_dot = tarih.replace("-", ".")
            derece_txt = f"{derece}." if derece else ""
            line = (
                f"{alacakli} lehine {borc} bedelle {derece_txt}dereceden "
                f"ipotek kaydı bulunmaktadır. {tarih_dot} Yev: {yevmiye}"
            )
            if len(info["bbnos"]) > 1:
                line += f" — {_bbno_label(info['bbnos'])} nolu bağımsız bölümler için müşterektir."
            lines.append(line)

    if not kayit_map and not ipotek_map:
        lines.append("Taşınmaz(lar) üzerinde herhangi bir takyidat kaydına rastlanmamıştır.")

    return "\n".join(lines)


if __name__ == "__main__":
    d = extract_takbis_data("/mnt/user-data/uploads/takbis.pdf")
    import json
    print(json.dumps(d, ensure_ascii=False, indent=2))
    print("----- RAPOR -----")
    print(format_report(d))
