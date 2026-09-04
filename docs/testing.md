# Testning och verifieringsgrindar

## Status 2026-09-03

Den stabila slutkörningen 2026-09-03 gav 223 godkända tester, 99,80 procent total branch coverage och minst 99,13 procent för varje produktionsmodul. Ruff, format och strict mypy var utan fel. Testerna omfattar API-säkerhet, MetObs, PTHBV, beräkningar, cache, diagnostics, config flow, coordinator, lifecycle, entities och Repairs.

Officiell hassfest-container rapporterade en integration och noll ogiltiga integrationer. Ovanstående är den daterade lokala verifieringen. Aktuella CI-resultat finns i repositoryts Actions-flik; en verklig HACS-installation kräver dessutom en publicerad releaseasset.

## Testlager

### Rena enhetstester

- URL-, redirect-, timeout-, retry- och storleksbeteende.
- MetObs stationsmetadata, kvalitetsfilter och CSV-parser.
- PTHBV URL-kontrakt, schema och kalenderdatum.
- DST, skottdag, täckning, flerårsmedel, midrank och cirkulär riktning.
- Cacheversion, checksumma, symlinkskydd, atomisk skrivning och entry-isolering.
- Diagnostics positive allowlist och redigering.

### Home Assistant-komponenttester

- Setup/migration, config flow, coordinator, entities och Repairs täcks av komponenttester.
- Success, errors, dubblett, confirm, options, reconfigure, first refresh, unload, reload, removal, partial failure, stale och cache fallback täcks.
- Entity unique IDs, units, device classes, disabled-by-default, provenance-attribut och availability har explicita assertions.
- Repairs create/clear och översättningsplaceholders verifieras; svenska och engelska translationer passerar hassfest och laddas av Home Assistant 2026.9.

### Livekontrakt

Ordinarie pytest ska vara helt offline. Begränsade SMHI-prober körs separat för att upptäcka upstream-schemaförändringar. De får inte skriva om fixtures automatiskt.

### Home Assistant runtime

Slutgrinden kördes i den verifierade utvecklingsinstansen och omfattade installation, config flow, två platser, avvisad koordinat utanför täckning, entities, states, options-reload, unload/reload, entry-borttagning med cacheisolering, full restart, cacheåteranvändning och loggar.

## Reproducerbar lokal miljö

Workflows, Ruff och mypy är harmoniserade för Python 3.14, samma huvudversion som Home Assistant Core 2026.9.0 i målmiljön.

Exempel på isolerad miljö:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install \
  pytest-homeassistant-custom-component==0.13.307 \
  pytest-cov==7.0.0 \
  ruff==0.15.4 \
  mypy==1.19.1
```

Versionspinnarna speglar de lokala workflowfilerna 2026-09-03 och ska omverifieras när arbetet återupptas.

## Lokala kommandon

Kör från repositoryroten.

### JSON

```bash
python -m json.tool hacs.json >/dev/null
python -m json.tool package.json >/dev/null
python -m json.tool custom_components/smhi_weather_context/manifest.json >/dev/null
python -m json.tool custom_components/smhi_weather_context/translations/en.json >/dev/null
python -m json.tool custom_components/smhi_weather_context/translations/sv.json >/dev/null
```

### Ruff

```bash
python -m ruff check custom_components scripts tests
python -m ruff format --check custom_components scripts tests
```

Workflowen kontrollerar `custom_components`, `scripts` och `tests`, samma scope som kommandot ovan.

### Strict typing

```bash
python -m mypy custom_components/smhi_weather_context
```

### Pytest och coverage

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest tests \
  -p no:cacheprovider \
  --cov=custom_components.smhi_weather_context \
  --cov-branch \
  --cov-report=term-missing \
  --cov-report=json:coverage.json \
  --cov-fail-under=95
```

`--cov-fail-under=95` säkerställer global nivå. Planen kräver dessutom över 95 procent för **varje** produktionsmodul. Kör därför också:

```bash
python scripts/check_coverage.py coverage.json
```

Scriptet kräver strikt mer än 95,00 procent per Python-modul under integrationen. Slutkörningen passerade för samtliga 15 moduler; lägsta resultat var 99,13 procent.

### Releasekonfiguration och deterministiskt artifact

```bash
npm ci --ignore-scripts --no-audit --no-fund
npm run verify:release:config
npm run verify:release:self-test
npm run verify:release
```

`verify:release` bygger två rena artifacts i temporära kataloger, jämför byteinnehåll, validerar flat HACS-struktur, manifestversion, förbjudna filer, SHA-256 och SPDX-SBOM samt kontrollerar att källmanifestet inte ändras.

Kommandot får inte lämna `smhi_weather_context.zip` i repositoryt. Semantic-release dry-run är inte meningsfullt fullt ut innan Git-historik och brancher finns; `verify:release:config` är den säkra icke-publicerande grinden tills dess.

### Dependency audit

```bash
npm audit --audit-level=high
```

Slutkörningen av `npm audit` rapporterade noll kända sårbarheter.

## HACS och hassfest

Följande workflows är förberedda:

- `home-assistant/actions/hassfest`
- `hacs/action` med kategorin `integration`

De är pinnade till fulla action-SHA i workflowfilen. Hassfest kördes lokalt med `ghcr.io/home-assistant/hassfest` och passerade. HACS-containern startades men stoppade korrekt på avsaknad av GitHub-token/repositorymetadata; full HACS-repository- och releasekontroll är därför en uttrycklig publiceringsgrind. HACS `zip_release` kräver ett framtida publicerat release-asset med exakt filnamn.

## Fixtureprinciper

- Fixtures ska vara små och kunna köras offline.
- Källa, hämtningstid och licens ska dokumenteras.
- Platsinformation minimeras när den inte behövs för kontraktet.
- Råa fullarkiv får inte checkas in.
- Upstream-svar får inte automatiskt ersätta golden fixtures utan granskning.
- Schemafel och providerfel ska kunna skiljas från lokal parserregression.

De befintliga fixturefilerna behöver en slutlig provenance-/licensgranskning innan release.

## Obligatorisk testmatris

| Område | Minsta bevis | Status 2026-09-03 |
|---|---|---|
| API-säkerhet | Tillåt/blockera URL, redirects, size, retry, felstatus | Godkänd offline-svit |
| MetObs | Stationer, current, archive, `G`/`Y`, schemafel | Godkänd offline-svit och liveprobe |
| PTHBV | lon/lat, gzipkontrakt, schema, täckning, 29 februari | Godkänd offline-svit; temperatur live, nederbörd gav verifierat upstream-503 |
| Beräkningar | DST 23/25, 75 %, 7/6, 24/23, midrank, vind | Godkänd offline-svit och livefacit |
| Cache | Version, checksumma, symlink, atomicitet, removal | Godkänd offline- och liveverifiering |
| Diagnostics | Redigering, positive allowlist, storlek | Godkänd; exakt position redigerad live |
| Config flow | Alla steg, errors, abort, duplicate, options, reconfigure | Godkänd offline och live |
| Lifecycle | Setup, first refresh, unload, reload, removal, migration | Godkänd offline och live |
| Entities | IDs, defaultläge, units, availability, attributes | Godkänd offline och live |
| Repairs | Create, clear, text | Godkänd offline-svit |
| Coverage | >95 % globalt och per modul | 99,80 % totalt; minst 99,13 % per modul |
| Ruff/format/mypy | Noll fel | Godkänd |
| hassfest/HACS | Gröna validators | hassfest godkänd; full HACS kräver publicerat repo/release |
| Artifact | Två byteidentiska builds | Godkänd; checksumma dokumenteras i projektloggen |
| Live HA | Loaded entry, states, rådatakontroll, reload/restart/logg | Godkänd med dokumenterad PTHBV-nederbördsbegränsning |

## Liveverifiering i utvecklingsinstansen

Följande checklista ska genomföras utan rå `.storage`-redigering:

1. Bekräfta aktuell Home Assistant-version, tidszon och exakt runtimeväg.
2. Säkerhetskopiera endast en eventuell befintlig målkomponent.
3. Kopiera komponenten och verifiera repo/runtime-paritet exklusive cache/bytecode.
4. Kontrollera konfiguration och starta om med Home Assistants stödda API/UI.
5. Lägg till entry genom config flow.
6. Läs tillbaka entry, device, entities, states, units, attributes, translations och disabled-by-default.
7. Jämför temperatur, vind och minst en historisk beräkning mot samma SMHI-källsvar.
8. Prova reload, cacheåteranvändning och full restart.
9. Lägg till en andra svensk plats och avvisa en punkt utanför PTHBV-täckning.
10. Genomför kontrollerat source-failure-test i testmiljö.
11. Granska loggar före och efter återhämtning.

Ett rimligt state-värde är inte tillräckligt bevis; källtimestamp, station, metod och beräkningsfacit måste matcha.

## GO/NO-GO

Den lokala implementationen är **GO** för fortsatt användning och granskning i utvecklingsinstansen. En publik källkodsleverans är inte samma sak som en verifierad release: releasegrinden omfattar gröna GitHub Actions, kontrollerad semantic-release, granskad releaseasset och en riktig HACS-installation. Ingen release får publiceras utan uttryckligt godkännande.
