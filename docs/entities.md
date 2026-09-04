# Entiteter

## Modell

Varje config entry skapar en device för den konfigurerade platsen. Entiteter använder översatta namn och stable unique IDs baserade på entryns beständiga `location_id`:

```text
<location_id>_<entity_key>
```

Home Assistant skapar entity IDs utifrån plats- och entitynamn. Det faktiska `sensor.*`-namnet kan därför skilja sig mellan installationer och kan ändras manuellt av användaren utan att unique ID ändras.

En entity vars specifika beräknade värde saknas blir `unavailable`. Saknat värde ersätts aldrig med noll.

## Temperatur från MetObs

Entiteterna skapas när **Temperatur** är aktiverat.

| Svenskt namn | Nyckel | Enhet | Standard | Innehåll |
|---|---|---:|---|---|
| Aktuell temperatur | `temperature_now` | °C | På | Senaste giltiga observation från vald temperaturstation |
| Medeltemperatur i dag | `temperature_today_mean` | °C | På | Timviktat lokalt medel till senast avslutad timme, minst 75 % täckning |
| Temperaturens tioårsmedel | `temperature_10_year_mean` | °C | På | Medel av samma dagsintervall för föregående tio år, minst sju år |
| Avvikelse från temperaturens tioårsmedel | `temperature_deviation_10_year` | °C | På | Dagens medel minus tioårsmedel |
| Historisk temperaturpercentil | `temperature_historical_percentile` | % | På | Midrank för dagens medel i historiskt stickprov, minst sju prov |
| Historisk maxtemperatur | `temperature_historical_max` | °C | Av | Högsta giltiga historiska dagsmedel i coordinatorns stickprov |
| Historisk mintemperatur | `temperature_historical_min` | °C | Av | Lägsta giltiga historiska dagsmedel i coordinatorns stickprov |
| Temperatur samma timme, jämförelse N år | `temperature_same_hour_N_year` | °C | På för N=1, annars av | Exakt motsvarande lokala timme N år tillbaka |
| Medeltemperatur i dag, jämförelse N år | `temperature_today_mean_N_year` | °C | På för N=1, annars av | Samma lokala dagsintervall N år tillbaka |

`N` skapas för varje valt jämförelseår. Config flow erbjuder 1, 2, 3, 5, 10, 20 och 30 år; standard är 1, 2, 3 och 10.

## Vind från MetObs

Entiteterna skapas när **Vind** är aktiverat. Samma valda vindstation måste vara kompatibel med MetObs-parametrarna vindriktning, vindhastighet och vindby.

| Svenskt namn | Nyckel | Enhet | Standard | Innehåll |
|---|---|---:|---|---|
| Aktuell vindhastighet | `wind_speed_now` | m/s | På | Senaste giltiga vindhastighet |
| Vindriktning | `wind_direction` | text | På | Svensk 16-sektorsriktning för senaste gradvärdet |
| Vindriktning i grader | `wind_direction_degrees` | ° | På | Senaste meteorologiska vindriktning |
| Vindby | `wind_gust` | m/s | På | Senaste giltiga vindby |
| Medelvind i dag | `wind_today_mean` | m/s | På | Timviktad vindhastighet till senast avslutad timme |
| Vindens tioårsmedel | `wind_10_year_mean` | m/s | På | Tioårsmedel av jämförbart dagsintervall, minst sju år |
| Avvikelse från vindens tioårsmedel | `wind_deviation_10_year` | m/s | På | Dagens medelvind minus tioårsmedel |
| Historisk vindpercentil | `wind_historical_percentile` | % | Av | Midrank för dagens medelvind |
| Vindhastighet samma timme, jämförelse N år | `wind_same_hour_N_year` | m/s | På för N=1, annars av | Exakt motsvarande timme N år tillbaka |
| Medelvind i dag, jämförelse N år | `wind_today_mean_N_year` | m/s | På för N=1, annars av | Samma dagsintervall N år tillbaka |

Historiska vindjämförelser använder i aktuell kod vindhastighet. Den cirkulära medelfunktionen för riktning är implementerad och referenstestad separat men ännu inte kopplad till historiska vindriktningsentities.

## Klimatperspektiv från PTHBV

| Svenskt namn | Nyckel | Enhet | Standard | Villkor och innehåll |
|---|---|---:|---|---|
| Klimatnormal temperatur | `temperature_climate_normal` | °C | På | **Klimatperspektiv** aktiverat; PTHBV-medel 1991–2020, minst 24 år |
| Temperaturens klimatanomali | `temperature_climate_anomaly` | °C | På | Klimatperspektiv och temperatur aktiverade; MetObs dagsmedel hittills minus PTHBV dygnsnormal |
| Klimatnormal nederbörd | `precipitation_climate_normal` | mm | På | **Nederbördsperspektiv** aktiverat; PTHBV 1991–2020 |
| Nederbördens tioårsmedel | `precipitation_10_year_mean` | mm | På | PTHBV för föregående tio år, minst sju värden |
| Historisk maxnederbörd | `precipitation_historical_max` | mm | Av | Högsta giltiga värde i hämtad PTHBV-serie för samma kalenderdatum |

PTHBV är griddata och ska inte tolkas som den valda MetObs-stationens mätvärde. Den 29 februari är klimatnormalen unavailable eftersom 1991–2020 bara innehåller åtta verkliga skottdagar och miniminivån är 24.

## Diagnostiska entiteter

| Svenskt namn | Domän/nyckel | Standard | Innehåll |
|---|---|---|---|
| Senaste SMHI-observation | `sensor` / `smhi_last_observation` | Av | Timestamp för den senaste giltiga observationen bland aktiverade MetObs-källor |
| Senaste uppdatering av historiska data | `sensor` / `smhi_last_historical_update` | Av | När coordinatorn senast slutförde historikladdning |
| SMHI-data är aktuella | `binary_sensor` / `smhi_data_fresh` | Av | På när samtliga aktiverade aktuella MetObs-källor är tillgängliga och högst två timmar gamla |

`smhi_last_observation` fungerar även för en vind-only-entry och väljer den senaste giltiga observationstiden utan att exponera någon full serie.

## Attribut

Huvudentiteter kan ha följande små provenance-attribut när uppgiften är relevant:

| Attribut | Betydelse |
|---|---|
| `source_product` | `MetObs`, `PTHBV` eller `MetObs and PTHBV` |
| `station_id` | Vald MetObs-station; saknas för ren PTHBV |
| `station_name` / `station_distance_km` | Vald station och avrundat avstånd vid senaste uttryckliga stationsval |
| `observation_time` | Observation eller jämförelsens tidsreferens |
| `comparison_period` | Vald historisk period när entityn är en jämförelse |
| `sample_count` | Antal timslotar eller år som användes |
| `data_quality` / `quality_flag` | Normaliserad status samt aktuell MetObs-flagga när den finns |
| `last_source_update` | Senaste observation eller historikladdning som ligger bakom värdet |
| `attribution` | “Weather observations and climate context from SMHI” |

Alla dynamiska jämförelseentities har inte egna attribut i aktuell kod. Full historik, koordinater, råa serier och källsvar exponeras inte som state attributes.

## Availability och partial failure

- Coordinatorfel gör coordinator-baserade entities unavailable enligt Home Assistants standardbeteende.
- Om en enskild beräkning ger `None` blir bara den entityn unavailable.
- Om en aktuell MetObs-delkälla fallerar men en annan fungerar kan coordinatorn fortsätta med delresultat.
- PTHBV-fel ska inte göra fungerande MetObs-värden unavailable; fullständigt partial-failure-beteende behöver fortfarande coordinator-/entitytest och liveprov.
- Ett stale observationsvärde kan fortfarande visas, medan den diagnostiska färskhetsentityn blir av. Observationstid och intern source status används för felsökning.

## Repairs

Valda stationer kontrolleras högst en gång per dygn mot stöd för `latest-day` och `corrected-archive`. Om en station inte längre är kompatibel skapas en Repair. Integrationen byter inte station automatiskt; användaren öppnar **Konfigurera om**, granskar alternativen och bekräftar en ny station.

## Exempel på användning

En enkel automation kan reagera på en stor avvikelse från tioårsmedlet. Byt entity ID till det som Home Assistant har skapat för platsen:

```yaml
alias: Ovanligt varm dag
triggers:
  - trigger: numeric_state
    entity_id: sensor.hem_avvikelse_fran_temperaturens_tioarsmedel
    above: 5
actions:
  - action: notify.notify
    data:
      message: Dagens temperatur ligger mer än 5 °C över tioårsmedlet.
```

Exemplet är dokumentation, inte ett utfört liveprov.
