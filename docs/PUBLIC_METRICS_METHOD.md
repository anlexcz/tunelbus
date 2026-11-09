# Metodika veřejných statistik – návrh 2026-11-09

Tato dokumentace platí pro testovací větev `design/tunelbus-light-preview`.
Úpravy se netýkají původních záznamů ani produkčního webu.

## Zásady

1. **Raw data jsou neměnná.** Archivují se všechny přijaté záznamy, včetně extrémů,
   čekání na výchozí zastávce, změn GTFS trip ID a konfliktů.
2. **Měření a odvozená statistika nejsou totéž.** Hodnota, která nereprezentuje
   doložený odjezd, nemá být prezentována jako skutečné předjetí.
3. **Důvěryhodnost se posuzuje podle návaznosti a zdrojových údajů, ne pouhým
   stropem na velikost zpoždění.** Souvislé skutečné velké zpoždění se zahrnuje.
4. **Jednotkou denních průměrů je spoj, nikoliv počet HTTP pozorování.**
   Pro jeden spoj se vytvoří zastávkové reprezentativní hodnoty a jejich medián.
   Denní medián a průměr se pak počítají se stejnou váhou pro každý použitelný spoj.
5. **Včasnost:** reprezentativní zpoždění od −60 s (včetně) do +180 s
   (bez +180 s) se klasifikuje jako včas; pod −60 s jako předjetí.
   +180 s je už zpoždění.
6. **Pokrytí = použitelné spoje / všechny plánované spoje.** Není to procento
   prokazatelně odjetých spojů ani podíl měřených zastávek. Nezachycený spoj
   se nesmí automaticky označit za vynechaný.
7. **Neúplné období nesmí působit jako uzavřený den.** GitHub Pages náhled
   obsahuje pevný archivní snímek 7. 11. 2026, nikoli živý provoz.

## Výběr reprezentativních pozorování

- Párujeme pouze přes přesnou kombinaci `trip_id`, `last_stop_sequence`
  a `last_stop_id` proti GTFS snapshotu příslušného provozního dne.
- Pro každou zastávku je uložen jeden reprezentativní bod; všechny raw záznamy
  zůstávají uložené bez filtru.
- Pokud `delay_actual` a údaj o poslední zastávce nesouhlasí o více než
  600 sekund, výsledek se označí `delay_vs_last_stop_conflict` a pro veřejné
  souhrny se nezapočítá. Není tím prokázáno, která ze dvou hodnot je chybná.
- Pokud jeden bod ukazuje více než 600 sekund absolutní odchylky, přičemž
  bezprostředně sousední pořadí zastávek vykazují zpoždění v intervalu
  `[-60, +180)`, je tento izolovaný numerický skok dočasně vyňat ze
  souhrnů jako `isolated_spike_excluded`. Jde o konzervativní heuristiku,
  nikoli důkaz, že nedošlo k dopravní události.
- Skutečné souvislé velké zpoždění zůstává v souhrnu; nejsou zavedena
  automatická tvrdá maxima celkového zpoždění.
- Spoj je použitelný pro statistiky, pokud po validaci zůstaly alespoň
  **dvě reprezentativní zastávky**. To platí pro všechny výstupy.
- Validace jednotlivých zastávek se počítá na **celém spoji**,
  až potom se vybírá požadovaná hodina či časové okno.
- Pro detail spoje jsou původní nevalidovaná měření nadále dostupná,
  veřejný průběhový graf však sporná měření označuje nebo vynechá.
- Záznamy bez dostatečné opory se nezaměňují za nulové zpoždění.

## Nezaměňovat za prokázaný stav

- Nástupní zastávka: vozidlo může být spojem identifikováno i 20 minut před
  skutečným odjezdem. Samotné `delay_last_stop_departure` ve fázi čekání
  neprokazuje předjetí.
- Stáří realtime: `observed_at` je čas přijetí, zatímco
  `source_timestamp` je zdrojový čas. Je třeba dále otestovat jejich
  případný rozchod před změnou párovací logiky.
- Medián zastávkových odchylek ani podíl včasných **spojů** nejsou
  totéž jako procento včasných odjezdů ze všech zastávek.
- Sledování jednoho vozu není stejné jako identita jednoho spoje;
  změna vozu není sama o sobě chyba.

## Čím ověřit před produkčním nasazením

1. Vzorek 7. 11. 2026, spoj `145_1320_261003`: čekání na Dejvické
   od 07:31, extrém −19:57 nevstupuje do odjezdové statistiky.
2. Jiné odjezdy na konečné a minimálně několik pracovních dnů, sobot a nedělí.
3. Skutečné trvající velké zpoždění; nesmí být vyfiltrováno jako extrém.
4. Spoj s pouze dvěma měřeními, z nichž jedno je neplatné: nesmí
   předstírat kvalitně vyhodnocený spoj.
5. Tytéž spoje v celodenním i hodinovém souhrnu.
6. Přechod přes hranici provozního dne 03:00, časové změny DST,
   neúplné dny a výpadky realtime.
7. Porovnání počtu vyřazených zastávkových hodnot, pokrytí, mediánu,
   průměru a P90 před a po validaci.

**Omezení:** bez zpětného vyhodnocení celé archivní SQLite databáze a
spuštění automatických testů nelze tvrdit, že všechny historické statistiky
jsou nyní plně odladěné. Tyto testy jsou podmínkou produkčního nasazení.


## Kontrola na skutečných datech 7. 11. 2026

Podklady: 2 233 řádků GTFS stop_times, 4 657 realtime pozorování za
provozní den od 03:00 do 03:00 dalšího dne; celkem 142 plánovaných spojů.

| Metrika | Před validací | Po validaci |
| --- | ---: | ---: |
| Použitelné spoje | 142 | 142 |
| Průměrné zpoždění | 73 s | 73 s |
| Medián | 50 s | 50 s |
| P90 | 162 s | 162 s |
| Včasnost | 91 % | 91 % |
| Nejdokonalejší extrém na úseku Dejvická → Vítězné náměstí | +1 233 s | +162 s |
| Medián změny zpoždění na tomtéž úseku | +74 s | +71 s |
| Počet měření daného úseku v souhrnu | 68 | 67 |

Ve všech datech bylo vyřazeno z veřejné agregace **jedno konfliktující
zastávkové reprezentativní měření**; počet vyřazených izolovaných skoků je
v tento den nula. Původní záznam se zachovává v raw archivu.

Spoj `145_1320_261003` (7:50 Dejvická) měl před validací medián
+41 sekund, po validaci +46 sekund. Jeho čekání na výchozí zastávce
nemění platnost zbylých 15 zastávkových reprezentantů.

Náhledové `preview-data.json` obsahuje přepočtené údaje a také oddělené
`source_api_analytics` a `source_api_segments` s původními výsledky
pro kontrolu rozdílu. Výsledky se nevztahují automaticky na ostatní dny.
