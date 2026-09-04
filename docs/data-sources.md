# Datakällor

## Principer

Version 1.0 använder endast officiella, dokumenterade SMHI-tjänster. Ingen scraping, browser automation, prognoskälla eller tredjepartsprovider används. API-kontrollen och de begränsade liveproberna genomfördes 2026-09-03.

MetObs och PTHBV har olika syften:

- **MetObs** är observationskälla för aktuell och historisk temperatur och vind.
- **PTHBV** är griddad dygnsdata för långsiktigt klimatperspektiv och valfri nederbörd.

PTHBV används inte som källa för aktuell temperatur.

## API-matris

| Funktion | Dokumenterat mönster | Format och verifierat kontrakt |
|---|---|---|
| MetObs katalog | `GET https://opendata-download-metobs.smhi.se/api.json` | JSON; versionerna `latest` och `1.0` annonserades |
| MetObs parametrar | `GET https://opendata-download-metobs.smhi.se/api/version/1.0.json` | JSON med parameterresurser |
| Stationer per parameter | `GET .../api/version/1.0/parameter/{parameter}.json?measuringStations=core` | JSON med station, koordinat, aktiv-status och periodmetadata |
| Stationens perioder | `GET .../parameter/{parameter}/station/{station}.json` | JSON; används för att kräva `latest-day` och `corrected-archive` |
| Aktuellt dygn | `GET .../parameter/{parameter}/station/{station}/period/latest-day/data.json` | JSON med `value[]`; datum i Unix-millisekunder och värde som sträng |
| Korrigerat arkiv | `GET .../period/corrected-archive/data.csv` | UTF-8 med BOM, semikolonseparerad CSV och variabel metadataprolog |
| PTHBV punktdata | `GET https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/version/1/geotype/multipoint/from/{from}/to/{to}/period/daily/data.json?...` | Gzip-komprimerad JSON med parallella `dates[]` och `point_values[]` |
| PTHBV täckningsprov | Samma endpoint med litet årsintervall | Koordinat utanför täckning ger HTTP 400 med textfel |

`...` i tabellen avser samma verifierade MetObs-bas under `https://opendata-download-metobs.smhi.se/api/version/1.0`. Koden använder den numeriskt pinnade versionen `1.0`, inte beständiga `latest`-URL:er.

## MetObs

### Parametrar

| ID | Innehåll | Enhet och publicerad frekvens |
|---:|---|---|
| 1 | Lufttemperatur | °C, momentanvärde en gång per timme |
| 3 | Vindriktning | grader, 10-minutersmedel en gång per timme |
| 4 | Vindhastighet | m/s, 10-minutersmedel en gång per timme |
| 21 | Vindby | m/s, maximum en gång per timme |

En verifieringsprob mot Göteborg A, station 71420, visade stöd för `latest-day` och `corrected-archive` för samtliga fyra parametrar. Proben var ett API-kontraktstest, inte bevis för att config flow eller entity states i Home Assistant fungerar.

### Aktuellt dygn

`latest-day` gav 25 observationsposter i proben. Klienten får därför inte anta exakt 24 poster. Den senaste giltiga observationen väljs efter UTC-timestamp.

Exempel på värderad:

```json
{
  "date": 1788451200000,
  "value": "15.9",
  "quality": "G"
}
```

Värdet är en JSON-sträng och datumet är Unix-millisekunder. Negativa timestamps före 1970 kan förekomma i metadata och måste tolkas korrekt.

### Corrected archive

Arkivet innehåller en variabel metadataprolog. Parsern söker därför efter den faktiska rubrikraden:

```text
Datum;Tid (UTC);...;Kvalitet
```

Den får inte förutsätta ett fast radnummer. Tiden är uttryckligen UTC. Arkivet i proben sträckte sig från 1961-01-01 till 2026-06-01 och saknade de senaste ungefär tre månaderna, vilket är normalt för corrected archive och skilt från `latest-day`.

Aktuell implementation läser endast de kalenderdatum och år som behövs för dagens jämförelser. Hela serien exponeras aldrig som Home Assistant-attribut.

### Kvalitetskoder

- `G` accepteras som kontrollerat och godkänt.
- `Y` accepteras som användbart men degraderat.
- Andra eller okända koder filtreras bort.
- Icke-ändliga tal filtreras bort.

SMHI:s historiska material kan innehålla många `Y` eftersom äldre kontrollsystem var mindre omfattande. Koden behåller därför `Y`, men en framtida kvalitetsredovisning behöver skilja det från `G`.

### Stationer

Config flow hämtar endast `measuringStations=core`. En temperaturstation måste ha parameter 1 och tillräckligt tidigt metadata-startår. En vindstation måste förekomma för parametrarna 3, 4 och 21.

Rankningen är deterministisk. Kandidater måste vara aktiva core-stationer vars metadata når valt äldsta år; vald kandidat verifieras därefter mot faktiska `latest-day`- och `corrected-archive`-perioder innan den kan sparas. Bland kompatibla kandidater används avstånd och stations-ID som stabil tie-break. Fulla arkiv laddas avsiktligt inte i config flow, eftersom planen kräver en lätt preflight och flyttar tung historik till bakgrundsinitieringen.

Samma stations-ID kan ha flyttats eller bytt höjd. Detta är en dokumenterad källbegränsning: SMHI:s stationsmetadata ger inte ett fullständigt maskinläsbart kontinuitets- eller kvalitetsbetyg för varje kandidat utan att hela arkiv hämtas.

## PTHBV

### Beslut: GO för klimatperspektiv

API-specialistens slutsats 2026-09-03 var **GO** för PTHBV som dokumenterad och versionerad källa till klimatperspektivet, särskilt normalperioden 1991–2020.

Exakt kontrakt:

```text
GET https://opendata-download-metanalys.smhi.se/api/category/pthbv1g/version/1/geotype/multipoint/from/1991/to/2020/period/daily/data.json?epsg=4326&ll=11.97,57.71&var=p&var=t
Accept-Encoding: gzip
```

Koordinatordningen är **longitud, latitud**. PTHBV kräver gzip; en prob utan gzip gav HTTP 406.

Det verifierade 1991–2020-svaret innehöll:

- 10 958 datum från 1991-01-01 till 2020-12-31;
- lika långa temperatur- och nederbördsarrayer;
- temperatur i °C;
- nederbörd i mm;
- inga kvalitetsfält.

PTHBV beskrivs av SMHI som rikstäckande griddata med cirka 4 × 4 km upplösning från 1961. Integrationen validerar schema, EPSG 4326, strikt stigande unika datum, begärd period, arraylängder och ändliga tal.

### Normalperiod 1991–2020

Klimatnormalen är låst till 1991–2020. Minst 24 verkliga kalenderdagar krävs för aktuell månad/dag. Den 29 februari finns bara åtta prov och blir därför unavailable.

Aktuell kod hämtar en längre PTHBV-serie från 1961 till föregående år för att även kunna ge senare nederbördssammanhang, men klimatnormalens urval filtreras uttryckligen till 1991–2020.

### Ingen kvalitetsstämpel för färska PTHBV-dygn

PTHBV-svaret saknar kvalitets- och preliminärmarkering. Live-API:t innehöll data till gårdagen samtidigt som produktbeskrivningar nämner månadsvis uppdatering och retroaktiva korrigeringar. Därför gäller följande produktbeslut:

- använd 1991–2020 som klimatnormal;
- beskriv inte de senaste PTHBV-dygnen som slutligt kvalitetskontrollerade;
- använd inte PTHBV som aktuell temperaturkälla;
- håll griddata tydligt separerad från MetObs-stationsdata.

## HTTP- och cacheegenskaper

| Resurs | Observerad cachemetadata 2026-09-03 | Klientstrategi |
|---|---|---|
| MetObs metadata | `Cache-Control: max-age=60`, inget `ETag` | Kortlivad metadata, ingen 304-förutsättning |
| MetObs `latest-day` | `Cache-Control: max-age=600`, inget `ETag` | Coordinator var 30:e minut |
| MetObs corrected archive | Lång `max-age`, inget `ETag` | Lokal 28-dagarscache och checksumma |
| PTHBV | Inget `Cache-Control`, inget `ETag` | Långlivad 28-dagarscache och checksumma |

`Last-Modified` flyttades i proberna fram till ungefär anropstiden och `If-Modified-Since` gav ändå 200. Det används därför inte som källans sakliga uppdateringstid. MetObs periodmetadata har ett eget `updated`-fält som är ett bättre framtida ändringskontrakt; aktuell kod använder ännu inte detta för villkorad arkivhämtning.

Canonical HTTPS-anrop gav inga redirects. HTTP gav inte en säker redirect till HTTPS, så klienten kräver själv HTTPS och validerar varje redirect.

SMHI publicerar ingen numerisk rate limit i det kontrollerade materialet. Riktlinjen är att cacha, undvika onödiga upprepningar och hämta stora historiska filer sekventiellt och sparsamt.

## Värdar och nätverksmål

Endast följande hostnames tillåts:

```text
opendata-download-metobs.smhi.se
opendata-download-metanalys.smhi.se
```

Subdomänsuffix, IP-adresser, alternativa portar, HTTP, cross-host redirects och URL:er med userinfo blockeras.

## Licens och attribution

SMHI-data ska attribueras. Källkontrollen 2026-09-03 identifierade Creative Commons Erkännande 4.0 SE i [SMHI:s villkor för användning](https://www.smhi.se/data/om-smhis-data/villkor-for-anvandning). Integrationens entities använder attributionen “Weather and climate data from SMHI”. Bearbetningar, till exempel medel och percentiler, är integrationens beräkningar på SMHI-data.

## Officiella källor

- [MetObs introduktion](https://opendata.smhi.se/metobs/introduction)
- [MetObs perioder](https://opendata.smhi.se/metobs/resources/period)
- [MetObs dataformat och kvalitetskoder](https://opendata.smhi.se/metobs/resources/data)
- [PTHBV punkt-API](https://opendata.smhi.se/pthbv/get_point)
- [PTHBV parametrar](https://opendata.smhi.se/pthbv/parameters)
- [PTHBV produktbeskrivning](https://www.smhi.se/data/nederbord-och-fuktighet/nederbord/griddad-nederbord--och-temperaturdata)
- [Normalvärden](https://www.smhi.se/kunskapsbanken/klimat/normaler/hur-beraknas-normalvarden)
- [Frågor och svar om SMHI-data](https://www.smhi.se/data/om-smhis-data/fragor-och-svar)
- [Villkor för användning](https://www.smhi.se/data/om-smhis-data/villkor-for-anvandning)

## Öppna datakällgrindar

- Verifiera stationsval mot faktisk arkivtäckning och positionsperioder, inte bara metadataår.
- Använd MetObs periodens `updated` för att undvika oförändrade arkivhämtningar om kontraktet kan testas stabilt.
- Mät och dokumentera kvalitetsfördelningen `G`/`Y` i beräkningar utan att fylla entity-attribut med stora serier.
- Kontraktstesta parsern separat från ordinarie offline-CI.
- Livejämför entities mot råa SMHI-svar i mål-Home Assistant; detta är ännu inte gjort.
