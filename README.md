# trains2pdf

Tekee rautateiden kaukoliikenteen aikataulukirjat (PDF, suomi ja ruotsi) Digitrafficin GTFS-syötteestä.

## Käyttö

```bash
pip install -r requirements.txt
python main.py                                   # molemmat kielet, oletuskausi
python main.py --start 2026-12-13 --end 2027-06-27 --lang fi --outdir out
python -m pytest -q tests                        # testit
```

Ilman `--start`/`--end`-valitsimia kirja alkaa tästä päivästä (tai syötteen alusta, jos se on
myöhemmin) ja päättyy seuraavaa aikataulumuutosta edeltävään päivään, nyt 12.12.2026 (uusi
aikataulukausi 2027 alkaa 13.12.), joten myöhempiä päiviä ei tulosteta. Menneet päivät jätetään pois,
jotta ne eivät näy poikkeuksina.

## Kirjan rakenne

Kirja koostuu eri sivuista seuraavasti:

- kansi,
- sisällys,
- merkkien selitykset,
- reittikartta,
- asemien luettelo,
- aikataulukot, ja
- muistiinpanoja (valinnainen).

Sivunumerot lasketaan ennen piirtämistä, joten sisällys on kirjan alussa ja osoittaa oikeille sivuille.

## Ulkoasu

Ulkoasu on mitoitettu klassisen noin vuosina 1992-2014 käytössä olleen VR:n aikataulukirjan mallin mukaan. Kaikki fontit, mitat ja värit ovat tiedostossa `style_config.py`.

## Taulukon säännöt

- **Suunta:** junan pysähdykset sovitetaan taulukon asemajärjestykseen (pisin kasvava osajono `stop_sequence`-järjestyksessä). Vastakkaiseen suuntaan kulkeva juna ei siksi koskaan osu kahdelle asemalle.
- **Mukaan otettavat junat:** junan on pysähdyttävä taulukon suunnassa vähintään kahdella eri `filter_stations`-asemalla. Jos lista on tyhjä, kaikki taulukon asemat lasketaan.
- **Ajat:** tallennetaan minuutteina vuoron liikennepäivän keskiyöstä, myös yli 24:00.
- **Kulkupäivät:** lasketaan todellisista päivämääristä (`calendar` + `calendar_dates`). Samat ajat ajavat junaversiot yhdistetään samaan sarakkeeseen.
  - Viikonpäivä tulee mukaan, kun juna kulkee vähintään puolena kyseisistä viikonpäivistä.
  - Poikkeavaksi katsotaan juna, jonka kulusta vähintään 3 ja yli 10 % päivistä poikkeaa, sekä juna, joka kulkee enintään kahtena päivänä. Ne saavat alaviitteen: voimassaolojaksot (viikon tai pidempi tauko katkaisee jakson), lihavoidut viikonpäivät sekä "ei"- ja "myös"-päivät, esim. "21.10.-12.12. **M-S**, ei 3.11., 4.11.".
- **Tulo- ja lähtörivit:** kun asemalla on sekä tulo- että lähtörivi, lähtöasemalta lähtevällä junalla on vain lähtöaika ja määräasemalle saapuvalla vain tuloaika.
- **`|` (ohittaa pysähtymättä):** merkitään vain, jos asema on enintään 20 km päässä junan reitistä (asemien koordinaattien perusteella). Muuten juna on kulkenut toista rataa (merkitään `:`).
- **Liityntärivit** (`is_connection`): rivillä näkyy myöhäisin juna, joka saapuu seuraavan pääaseman riville vähintään `min_transfer_minutes` ja enintään `max_transfer_wait_minutes` ennen pääjunan lähtöä _jokaisena_ sen kulkupäivänä. Jos pääjuna itse tulee liityntäasemalta, rivillä näkyy sen oma aika.
- **Järjestys:** sarakkeet järjestetään arvioidun taulukon alkuaseman lähtöajan mukaan (vuorokausi alkaa klo 03). Kesken taulukon aamulla lähtevät junat tulevat siksi alkuun.

## Junatyyppien tunnukset

- **IC:** InterCity-symboli tiedostosta `logos/IC.svg` (Wikimedia Commons `File:InterCity.svg`). Se piirretään vektorina ja mustana (`LOGO_RECOLOR`) junanumeron
  korkeudella peruslinjalle, myös merkkien selityksiin. Jos tiedosto puuttuu tai `svglib` ei ole asennettu, tilalla on sisäänrakennettu musta "IC"-merkki.
- **S ja SP:** paksulla kursiivilla.
- **Muut tyypit** (PYO, HDM, H, R, M …): junanumeron fontilla ja samassa koossa. Jos tunnus ei mahdu kokonaan sarakkeeseen, sitä kavennetaan vaakasuunnassa, mutta korkeus pysyy samana.

Omia symboleja voi lisätä kansioon `logos/` nimillä `<TYYPPI>.svg`, `.png` tai `.jpg` (esim. `S.svg`, `PYO.png`). Bittikarttakuvissa valkoinen tausta muutetaan läpinäkyväksi ja kuva rajataan. Kaikissa muodoissa värit piirretään mustina.

## Palvelut

Kirjaan merkitään vain palvelut, jotka GTFS-syöte kertoo:

- polkupyörän kuljetus (`bikes_allowed`)
- pyörätuolipaikka, jos syötteessä on `wheelchair_accessible = 1` (Digitrafficissa ei tällä hetkellä ole).

Lisäksi jokaiselle yöjunalle (PYO) merkitään makuuvaunu, koska kaikissa VR:n yöjunissa on makuuvaunut. Ravintolavaunuja ei merkitä, koska syötteessä ei ole niistä tietoa. Vaunuluokka on "2" yöjunilla (PYO), kiskobusseilla (HDM) sekä taajama- ja lähijunilla, mutta muilla "1 2".

## Aikataulutaulukot

Taulukot ja niiden asemarivit on luettu tiedostoon `routes.json`, ja se sisältää esimääritetyt etäisyydet, tulo- ja lähtörivit sekä yhteysjunien rivit.

Erillisellä työkalulla `routes.json` voidaan tehdä uudelleen alkuperäisestä PDF:stä:

```bash
python tools/booklet_to_routes.py 2007-1_aikataulukirja_fin.pdf <gtfs-kansio>
```

**Mitä junia taulukkoon otetaan:** jokaisella taulukolla on oma rataosuutensa (`filter_groups`). Juna otetaan mukaan, kun se pysähtyy taulukon suunnassa vähintään kahdella saman osuuden asemalla.

**Taajamajunat:** taajama- ja lähijunien poimintaa mukaan taulukkoon säädellään `include_commuter`-asetuksella.

**Yhteysjunien rivit** (punaiset):

- ilman .o-merkkiä = liityntä: lähtöaika asemalta, jolta tuleva juna ehtii vaihtoasemalle ennen pääjunan lähtöä
- .o-merkillä = jatkoyhteys: saapumisaika asemalle, jolle jatketaan vaihtoasemalta pääjunan tulon jälkeen.

**Erot esikuvaan:**

- Lakkautetut asemat (esim. Lievestuore, Laihia, Vika) ja linja-autopysäkit on jätetty pois.
- Ulkomaan taulukot A, B, D ja E (Pietari, Moskova, Tukholma) eivät tällä hetkellä ole mukana. Venäjän junaliikenne on keskeytetty, eikä laivayhteyksiä ole GTFS-syötteessä.
