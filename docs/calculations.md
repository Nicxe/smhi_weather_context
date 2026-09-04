# Beräkningar

## Metodstatus

Beräkningsfunktionerna är implementerade som rena Python-funktioner och det finns riktade tester för centrala tids- och statistikfall. En full godkänd test-/coveragekörning finns ännu inte. Definitionerna nedan beskriver aktuell kod och markerar kända integrationsgap.

## Tidsmodell

Alla observationstider lagras och jämförs som timezone-aware UTC. Lokal kalenderlogik använder uttryckligen `Europe/Stockholm`.

Den “senast avslutade lokala timmen” tas fram genom att:

1. konvertera aktuell tid till UTC;
2. avrunda nedåt till hel UTC-timme;
3. gå tillbaka en fysisk timme;
4. konvertera resultatet till `Europe/Stockholm`.

Det undviker att skapa lokala tider som inte finns och bevarar ordningen mellan höstens två upprepade timmar.

## Samma timme tidigare år

För målåret krävs samma:

- månad;
- kalenderdag;
- lokal klocktimme;
- `fold`-förekomst vid höstens upprepade timme.

En historisk timme omfattar det exakta UTC-intervallet från timstart inklusive till nästa timstart exklusive. Finns flera godkända observationer inom timmen används deras aritmetiska medel. Saknas motsvarande timme returneras inget värde; en närliggande timme används aldrig.

Exempel:

```text
Mål: 2026-10-25 02:00, fold=1, Europe/Stockholm
Historiskt krav: samma kalenderdatum, 02:00 och fold=1
Första 02:00-timmen, fold=0, får inte återanvändas.
```

Om målkalenderdagen inte finns i jämförelseåret, till exempel 29 februari 2025, blir jämförelsen unavailable.

## Dagens medel hittills

Ett lokalt dygn representeras som en lista av fysiska timstarter från lokal midnatt till nästa lokala midnatt. Varje fysisk timme väger lika, oavsett hur många råobservationer som finns i timmen.

För varje timslot:

1. välj godkända observationer inom dess exakta UTC-intervall;
2. beräkna timmedel om minst en observation finns;
3. låt varje giltigt timmedel väga lika i dagsmedlet.

Intervallet slutar vid den senast avslutade timmen. Historiska dagsjämförelser använder exakt motsvarande lokala intervall.

### Täckningsgrind

Minst 75 procent av de förväntade fysiska timmarna måste ha ett timmedel:

```text
coverage = giltiga_timslotar / förväntade_timslotar
värde finns om coverage >= 0,75
```

Det motsvarar att antalet giltiga slotar minst är taket av `0,75 × förväntade`.

Exempel:

| Förväntade timmar | Minst giltiga timmar |
|---:|---:|
| 4 | 3 |
| 20 | 15 |
| 23 | 18 |
| 24 | 18 |
| 25 | 19 |

Om grinden inte nås blir värdet unavailable. `sample_count` redovisar antalet giltiga timslotar för de huvudvärden där attributet är kopplat.

## DST

### Vårövergång

När klockan går från 02:00 till 03:00 har det lokala dygnet 23 fysiska timmar. Den saknade timmen skapas inte artificiellt och ingår inte i nämnaren för täckning.

### Höstövergång

När klockan ställs tillbaka har dygnet 25 fysiska timmar. De två lokala 02:00-timmarna representeras med olika `fold` och räknas separat. Observationer från den första timmen får inte blandas med den andra.

### Historiskt jämförelsefall

Om en viss `fold`-förekomst inte finns på det historiska datumet returneras unavailable. Metoden prioriterar exakt tidsmässig jämförbarhet framför att fylla varje entity.

## Skottdag

29 februari ersätts aldrig med 28 februari eller 1 mars.

- Ett icke-skottår ger ingen motsvarande timme eller dag.
- Tio föregående år innehåller normalt bara två eller tre verkliga 29 februari och når därför inte sjuprovskravet.
- Perioden 1991–2020 innehåller åtta verkliga 29 februari. Klimatnormalens krav på 24 giltiga år kan därför inte nås den dagen.

Resultatet `unavailable` den 29 februari är ett avsiktligt metodresultat, inte ett nätverksfel.

## Tioårsmedel

Tioårsmedlet använder dagsmedel för de tio föregående kompletta åren, över samma del av det lokala dygnet som i dag. Varje giltigt årsmedel väger lika.

```text
ten_year_mean = medel(giltiga årsmedel för offset 1..10)
```

Minst sju giltiga årsmedel krävs. Med sex eller färre blir värdet unavailable. Avvikelsen beräknas som:

```text
deviation = dagens medel hittills - tioårsmedel
```

Aktuell implementation avrundar flera presenterade medel och avvikelser till två decimaler.

## Klimatnormal 1991–2020

PTHBV-datum lagras som rena kalenderdatum och konverteras inte till lokala midnattstidpunkter. För aktuell månad och dag väljs PTHBV:s dygnsvärde för varje år 1991–2020.

```text
climate_normal = medel(PTHBV-värden 1991..2020 för samma månad/dag)
```

Minst 24 giltiga år krävs. `sample_count` visar hur många år som användes.

Temperaturens klimatanomali i aktuell kod är:

```text
MetObs stationens dagsmedel hittills - PTHBV dygnsnormal 1991–2020
```

Detta är ett klimatperspektiv, inte en metodhomogen observationsavvikelse. MetObs är en station och värdet gäller dagen hittills; PTHBV är ett griddat dygnsmedel. Entitynamn, attribut och dokumentation ska bevara den skillnaden.

## Nederbörd

PTHBV kan hämta både temperatur (`t`) och nederbörd (`p`). Den fasta klimatnormalen använder 1991–2020 och minst 24 giltiga år. Aktuell kod kan också beräkna ett tioårsmedel för PTHBV-nederbörd och historiskt maximum från hämtad serie.

PTHBV-svaret saknar kvalitets- och preliminärmarkering. Färska dygn får därför inte beskrivas som slutligt kvalitetskontrollerade observationer. PTHBV används inte som källa för aktuell temperatur.

## Percentil med midrank

Historisk percentil använder midrank, så lika värden delar mittplaceringen:

```text
percentil = 100 × (antal lägre + 0,5 × antal lika) / antal prov
```

Exempel med historiken `[10, 12, 12, 20]` och dagens värde `12`:

```text
lägre = 1
lika = 2
percentil = 100 × (1 + 0,5 × 2) / 4 = 50
```

Om alla värden är lika blir percentilen 50. Minst sju giltiga historiska dagsmedel krävs i coordinatorns temperatur- och vindberäkningar. Aktuell implementation bygger percentilens provmängd från offset 1–10 plus eventuella ytterligare valda jämförelseår; exakt produktscope för extra år bör låsas i QA-grinden.

## Vind

### Aktuella parametrar

- Vindhastighet: MetObs parameter 4, m/s.
- Vindriktning: MetObs parameter 3, meteorologiska grader.
- Vindby: MetObs parameter 21, m/s.

### Kompassriktning

Grader mappas till 16 svenska sektorer:

```text
N, NNO, NO, ONO, O, OSO, SO, SSO,
S, SSV, SV, VSV, V, VNV, NV, NNV
```

Varje sektor är 22,5 grader bred och centreras på sin huvudriktning.

### Cirkulärt medel

Ett aritmetiskt medel är fel för riktningar runt norr. Den rena beräkningsfunktionen använder därför enhetsvektorer:

```text
x = medel(cos(vinkel))
y = medel(sin(vinkel))
medelriktning = atan2(y, x)
```

350° och 10° ger därmed 0°, inte 180°. Exakt motsatta riktningar ger undefined när resultantvektorn är nära noll.

Den cirkulära funktionen och gränsfallen är testade. Version 1.0 exponerar aktuell vindriktning och historiska jämförelser för vindhastighet; historisk medelriktning är uttryckligen utanför v1-entiteternas scope.

## Datakvalitet

MetObs-observationer accepteras när värdet är ändligt och kvalitetskoden är `G` eller `Y`.

- `G`: kontrollerat och godkänt.
- `Y`: användbart men kan vara misstänkt, grovt kontrollerat, aggregerat eller okontrollerat realtidsvärde beroende på period.
- Okända koder och underkända värden filtreras bort.

Att kassera alla äldre `Y` skulle kunna göra historiska serier oanvändbara. Aktuell kod accepterar därför båda, visar aktuell `quality_flag` och normaliserad `data_quality`, men publicerar inte en full kvalitetsfördelning som skulle belasta entity-attribut och Recorder.

## Saknade värden och avrundning

Saknade, otillräckliga eller metodmässigt omöjliga värden representeras internt som `None`, vilket gör entityn unavailable. Värdet `0` används endast när källan faktiskt rapporterar eller beräkningen faktiskt ger noll.

Koden avrundar timmedel, dagsmedel, flerårsmedel och avvikelser till två decimaler samt cirkulär riktning till en decimal. Home Assistant kan därutöver presentera värden med egen display precision. Ingen närliggande timme eller ersättningsdag används för att undvika unavailable.

## Referenstest som måste vara gröna

- 23-timmars vårdygn utan artificiell timme.
- 25-timmars höstdygn med två separata `fold`.
- Exakt 75-procentsgräns.
- Flera råvärden i en timme utan extra vikt för timmen.
- 29 februari utan ersättningsdatum.
- Tioårsmedel med sju respektive sex giltiga år.
- Klimatnormal med 24 respektive 23 giltiga år.
- Midrank med ties och alla värden lika.
- 350°/10° runt norr och 0°/180° som undefined.
- Svenska 16-sektorsgränser.

Testfiler för dessa fall finns, men hela testsviten och coveragegrinden behöver köras om och godkännas efter att implementationen är stabil.
