# Integritet och säkerhet

## Sammanfattning

Integrationen behandlar en användarvald geografisk position. Den har ingen telemetri, analytics, användarinloggning eller dataöverföring till Nicxe/GitHub. Exakta koordinater skickas endast till SMHI när PTHBV används och lagras lokalt av Home Assistant för config entry och cacheidentitet.

## Vilka uppgifter behandlas?

| Uppgift | Varför | Lagring/överföring |
|---|---|---|
| Platsnamn | Device- och UI-namn | Home Assistant config entry |
| Latitud/longitud | Stationsavstånd och PTHBV-gridpunkt | Config entry; skickas till PTHBV över HTTPS |
| Stations-ID och namn | Stabilt användarval och provenance | Config entry och små entity-attribut |
| Jämförelseår och featureval | Beräknings- och entitykonfiguration | Config entry options |
| MetObs-arkiv och PTHBV-svar | Historiska beräkningar och offlineåteranvändning | Privat entry-isolerad cache |
| Source status och feltyp | Diagnostics och felsökning | I minnet; sanitiserad diagnostics |

MetObs stationslista hämtas utan att platskoordinaten skickas som queryparameter; avståndet beräknas lokalt. PTHBV kräver däremot koordinaten i URL-queryn i ordningen longitud, latitud och avrundar den till fyra decimaler.

## Nätverksmål

Klienten tillåter endast HTTPS till exakt dessa hostnames:

```text
opendata-download-metobs.smhi.se
opendata-download-metanalys.smhi.se
```

Följande blockeras före anrop:

- HTTP och andra scheman;
- värdar utanför allowlist;
- lookalike-/suffixvärdar;
- IP-adresser och alternativa portar;
- URL-userinfo och fragment;
- cross-host redirect;
- fler än tre redirects;
- HTTPS-downgrade.

Automatiska redirects är avstängda så att varje steg kan valideras. TLS-verifieringen lämnas till Home Assistants/aiohttp standard och ingen HTTP-fallback finns.

## Begränsning av svar och parserrisk

- JSON-svar begränsas till 12 MiB.
- Text-/arkivsvar begränsas till 32 MiB.
- Både `Content-Length` och faktisk läst stream räknas.
- Innehållstyp kontrolleras men parsern validerar också schema/format.
- PTHBV-gzip dekomprimeras av aiohttp och den dekomprimerade streamen omfattas av läsgränsen.
- Integrationen extraherar inga zip-arkiv från SMHI.

Retries görs endast för idempotenta GET-anrop och begränsade tillfälliga nätverks-/HTTP-fel. Feltext från upstream ska inte loggas eller visas oredigerad.

## Lokal cache

Cache ligger under:

```text
<HA config>/.storage/smhi_weather_context/<entry_id>/
```

Skydd:

- separat katalog per config entry;
- hashade filnamn i stället för koordinatbaserade namn;
- versionsfält;
- SHA-256-kontroll över payload och metadata;
- atomisk temporär skrivning;
- katalogrättighet 0700 och temporär fil 0600;
- blockering av symlinkade mål;
- fil-I/O utanför event loop.

Home Assistant-backuper kan inkludera cachen och config entryn. Skydda därför backupfiler som annan Home Assistant-konfiguration.

När en entry tas bort genom Home Assistants UI/API raderar integrationen bara den entryns cache. Ta bort entryn innan komponentfilerna raderas. Redigera eller radera inte `.storage` manuellt under normal drift.

## Diagnostics

Diagnostics bygger på en positiv allowlist. Aktuell implementation:

- ersätter entry title och location med `**REDACTED**`;
- lämnar inte ut latitud eller longitud, inte ens avrundad;
- lämnar inte ut käll-URL:er eller råa svar;
- visar featureval, jämförelseår och stations-ID;
- visar endast godkända source-statusnycklar;
- reducerar fel till en kort klasslik feltyp;
- begränsar listan över beräknade entity-nycklar.

Stations-ID är inte en hemlighet men kan ge grov geografisk information. Granska därför alltid diagnostics innan de delas offentligt.

## Loggning

Normal loggning ska inte innehålla:

- exakta koordinater;
- fullständig PTHBV-URL;
- platsnamn i feltext;
- rå CSV/JSON;
- tokens eller andra hemligheter;
- oredigerad upstream-response body.

Historikvarningen loggar endast källkategori och exceptionklass, en gång vid bortfall och en gång vid återhämtning. Slutlig livegranskning visade inga koordinater, fulla URL:er eller råa provider-svar.

## Secrets och beroenden

SMHI-endpoints kräver ingen API-nyckel. Repositoryt ska därför inte innehålla credentials. Releasebyggaren söker efter vanliga token-, private-key- och secretmönster innan artifact skapas.

Runtime har inga externa Python-krav utöver Home Assistants miljö. Node/npm används bara för releaseverktyg. Lokal dependency audit rapporterade noll sårbarheter och releaseverifieraren passerade sin secret scan; framtida CI-körning återstår tills repositoryt får publiceras.

## Hotmodell i korthet

| Hot | Kontroll | Kvarvarande grind |
|---|---|---|
| SSRF via URL/redirect | Exakt HTTPS-allowlist och manuell redirectvalidering | Full negativ testsvit och code review |
| Överstor/dekomprimerad payload | Preflight- och streamgräns | Livekontrakt för oväntade upstreamformat |
| Cachemanipulation | Hashade namn, checksumma, version, atomicitet, symlinkskydd | Samtidighet och migrering behöver bredare test |
| Platsläcka i diagnostics | Positiv allowlist och full redigering | Liveexport och manuell granskning |
| Platsläcka i logg | Sanerade feltyper och inga URL:er | Post-restart logggranskning |
| Supply-chain-hemlighet i zip | Filallowlist och secretscan | Deterministiskt dubbelbygge samt CI |

## Rapportera säkerhetsproblem

Repositoryt är ännu inte publicerat. Rapportera säkerhetsproblem privat till maintainer. Inkludera inte koordinater, Home Assistant-URL, oredigerad diagnostics, cachefiler eller credentials i en publik kanal.
