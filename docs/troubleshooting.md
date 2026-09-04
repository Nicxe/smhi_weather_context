# Felsökning

## Integrationen syns inte under Lägg till integration

Kontrollera att katalogen är exakt:

```text
<HA config>/custom_components/smhi_weather_context/
```

och att den innehåller minst `manifest.json` och `__init__.py`. Starta om Home Assistant efter filkopiering. Sök i loggen efter `smhi_weather_context`.

I det lokala pre-release-läget kan integrationen inte installeras från HACS eftersom repositoryt och release-zippen ännu inte är publicerade.

## Config flow kan inte ansluta

Kontrollera att Home Assistant kan nå följande över HTTPS/443:

```text
opendata-download-metobs.smhi.se
opendata-download-metanalys.smhi.se
```

Integrationen följer inte HTTP-downgrade eller cross-host redirects. Proxy, DNS-filter eller TLS-inspektion kan därför orsaka anslutningsfel även om en webbsida går att öppna i en annan klient.

För PTHBV krävs gzip. Klienten skickar `Accept-Encoding: gzip`; en mellanproxy som tar bort eller ändrar headern kan ge HTTP 406.

## Platsen ligger utanför täckningen

PTHBV config flow gör ett begränsat täckningsprov. Kontrollera koordinatordning och tecken:

- latitud anges som latitud i UI;
- longitud anges som longitud i UI;
- PTHBV-klienten skickar internt `longitud,latitud`;
- svenska koordinater ska normalt ligga inom PTHBV:s täckning.

Ändra inte URL eller endpoint manuellt. Om bara MetObs önskas kan klimatperspektivet avaktiveras.

## Ingen kompatibel station hittas

En temperaturstation måste vara aktiv, tillhöra core-urvalet, ha metadatahistorik som når valt äldsta år och stödja både `latest-day` och `corrected-archive`. En vindstation måste dessutom vara gemensam för parametrarna 3, 4 och 21.

Prova att:

1. minska det längsta valda jämförelseintervallet;
2. kontrollera att koordinaten verkligen är i Sverige;
3. försöka igen senare vid SMHI-fel;
4. dokumentera felet med redigerad diagnostics om problemet kvarstår.

Närmaste station är inte alltid bäst. Integrationen ska prioritera historisk användbarhet, men den avancerade täckningsrankningen är fortfarande en öppen pre-release-grind.

## Historiska entities är unavailable efter installation

Den första corrected archive- och PTHBV-hämtningen är betydligt större än aktuella observationer. Vänta på coordinatorns nästa lyckade uppdatering och kontrollera den diagnostiska entityn **Senaste uppdatering av historiska data**.

Vanliga metodorsaker:

- färre än 75 procent giltiga timslotar;
- färre än sju giltiga årsmedel;
- färre än 24 PTHBV-år för klimatnormal;
- exakt motsvarande lokal timme saknas;
- vald jämförelsedag är 29 februari;
- corrected archive har en lucka eller stationen har flyttats.

Integrationen ersätter inte saknad data med noll eller närliggande tid.

## Klimatnormalen är unavailable den 29 februari

Det är förväntat. Normalperioden 1991–2020 har bara åtta verkliga 29 februari, medan miniminivån är 24. Ingen ersättningsdag används.

## Värdet verkar en timme fel vid sommar-/vintertid

Metoden jämför fysiska UTC-timmar med lokal kalenderrepresentation i `Europe/Stockholm`.

- Vårdygnet har 23 fysiska timmar och saknar en lokal timme.
- Höstdygnet har 25 timmar och två separata 02:00 med olika `fold`.

Kontrollera observationens timestamp och om det gäller första eller andra upprepade timmen. Rapportera inte ett fel utifrån lokal texttid ensam.

## SMHI-data är aktuella är av

`binary_sensor.smhi_data_fresh` är av om någon aktiverad aktuell MetObs-källa saknas eller senaste giltiga observation är äldre än två timmar. Det kan bero på:

- fördröjd SMHI-publicering;
- nätverksfel;
- en av vindparametrarna saknas;
- vald station har slutat rapportera;
- kvalitetsfiltret avvisar senaste värdet.

En stale observation kan fortfarande visas med sin observationstid. Kontrollera diagnostics och logg innan stationen ändras.

## Repair för otillgänglig station

Integrationen byter inte station automatiskt.

1. Öppna **Inställningar → System → Reparationer** och läs vilket stationsslag som berörs.
2. Gå till **Inställningar → Enheter och tjänster → SMHI Väderperspektiv**.
3. Välj **Konfigurera om**.
4. Granska och bekräfta en kompatibel temperatur- eller vindstation.

Repairen tas bort när stationen åter valideras.

## Options kräver reconfigure

Om temperatur eller vind aktiveras i efterhand men entryn saknar en station för produkten visar options flow att omkonfiguration krävs. Välj **Konfigurera om**, aktivera produkten, välj station och bekräfta.

Nederbörd kräver klimatperspektiv eftersom båda kommer från PTHBV.

## Cacheproblem

Checksummefel, okänd cacheversion eller trasig JSON gör att posten ignoreras och hämtas om. Radera inte `.storage` som första åtgärd.

Säkra steg:

1. Ladda om config entryn.
2. Kontrollera nätverksåtkomst och logg.
3. Starta om Home Assistant om en reload inte räcker.
4. Ta bort och lägg till entryn via UI endast om omkonfiguration inte löser problemet och du accepterar att entryns privata cache tas bort.

Rå radering i `.storage` kan skada andra Home Assistant-data och stöds inte.

## Delvis källfel

MetObs och PTHBV ska kunna fallera oberoende. Ett PTHBV-fel ska inte slå ut fungerande aktuell MetObs. På motsvarande sätt kan en vindparameter saknas medan temperatur fortfarande fungerar.

Detta beteende är verifierat både offline och live. När PTHBV-nederbörd returnerade HTTP 503 förblev config entryn `loaded` och fungerande MetObs-entities fortsatte uppdateras; endast den berörda historikkällan markerades otillgänglig.

## Samla säkert felsökningsunderlag

1. Hämta integrationens diagnostics från Home Assistant.
2. Kontrollera att title och location är `**REDACTED**`.
3. Granska ändå stations-ID och tider innan filen delas.
4. Kopiera endast relevanta loggrader för `smhi_weather_context`.
5. Dela inte full PTHBV-URL, koordinater, cachefiler, backup eller credentials.

Bra felrapport innehåller Home Assistant-version, integrationsversion, aktiverade produkter, ungefärlig region, feltyp, tidpunkt och minsta reproduktion.

## Efter uppdatering

Efter manuell filuppdatering:

1. säkerställ att inga gamla runtimefiler ligger kvar;
2. kontrollera konfigurationen;
3. starta om Home Assistant;
4. verifiera att entryn är loaded;
5. läs loggar;
6. kontrollera minst en aktuell och en historisk entity;
7. jämför runtimekomponenten med repositoryt exklusive `__pycache__` och runtimecache.

Ett grönt importtest räcker inte som runtimeverifiering.
