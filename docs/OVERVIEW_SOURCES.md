# Přehled Tunelbusu – zdroje a pravidla

Tato specifikace platí pro testovací větev. Produkční server zůstává nezměněný.

## Co má ukazovat přehled

1. **Aktuální stav:** `/api/live/summary` a `/api/live/vehicles`, aktualizace každých 30 sekund. Údaj označený jako živý pouze tehdy, pokud je čerstvý a backend odpovídá.
2. **Mapa:** `/api/live/route` (GTFS shapes) + aktuální GPS. Tunel mezi Hradčanskou a Kuchyňkou přináší nejistotu polohy; v něm se nepředstírá ověřený pohyb.
3. **Dnes:** `/api/day/{service_date}/analytics` pro zpoždění, včasnost, počet použitelných spojů a pokrytí (nikoli tvrzení o všech skutečně odjetých spojích).
4. **Srovnání:** historický vývoj odpovídajícího typu dne a hodiny, nikoli slepě „dnes vs včera“. Dokud není relevantních vzorků dost, zobrazit jen orientační výsledky.
5. **Predikce:** až po validaci a backtestu. Výhled nesmí být vydáván za fakt.
6. **Co se děje:** oficiální události PID a zvlášť automatická diagnostika změn jízdní doby.

## Oficiální zdroje PID

- **Výluky:** https://pid.cz/feed/rss-vyluky/
- **Mimořádnosti:** https://pid.cz/feed/rss-mimoradnosti/

RSS se čte **na serveru** (ne přímo z browseru). Parser bere jen přesnou shodu linky 145 v polích dotčených linek, ne řetězec `145` v názvu nebo popisu. Převzaté HTML popisy se nesmějí posílat do stránky jako nečištěné HTML. Ukládáme nadpis, odkaz, čas počátku/končení, datum vydání, zdroj a ID. Odkaz směřuje na původní PID.cz. Záznam je aktuální pouze tehdy, pokud platnost pokrývá aktuální čas a PID jej stále publikuje. Pokud RSS není dosažitelný, nehlásíme „bez mimořádností“, nýbrž „informace PID dočasně nedostupné“.

Pro produkci: endpoint `/api/pid/events?line=145` s serverovou cache a HTTP timeoutem; frontend nesmí stahovat feed přímo (CORS, XML, spolehlivost).

## Testovací GitHub Pages

Github Pages nemá backend, takže se má pokusit načíst veřejné živé API přes CORS. Pokud produkční server CORS nepovoluje, zobrazí pouze datovaný reálný snímek se zřetelným označením **ARCHIVNÍ SNÍMEK**. Nikdy se nesmí zobrazit zastaralé vozidlo s popisem „právě jede“.

Původní `week-preview.json` z 2.–8. listopadu poskytuje porovnání a analytický replay; 8. 11. je neúplný. Stávající agregace zatím nepředstavují nezávisle potvrzené odjezdy.

## Bezpečnost a věrohodnost

- Žádné vymyšlené živé polohy, mimořádnosti ani předpovědi.
- Včasnost zastávkových odjezdů a medián reprezentativního zpoždění spojů jsou odlišné metriky.
- GPS v tunelu = nejistá poloha, ne prokázané zdržení.
- Předčasný příjezd při čekání do odjezdu != předjetí.
- Zobrazení čerstvosti pozorování a data archivního snímku je povinné.
