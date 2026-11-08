# Tunelbus

Fáze 1 archivuje neměnné denní GTFS snapshoty PID a raw realtime pozorování Golemio pro linku 145 do SQLite. Aplikace poslouchá standardně jen na `127.0.0.1:8010`.


## Dokumentace a priorita specifikací

Při vývoji platí tato hierarchie:

1. `frontend.md` — autoritativní veřejný design, UX a responzivní chování,
2. `web.md` — funkční a analytická specifikace veřejného webu,
3. `zadani.md` — technické zadání backendu, collectoru, databáze a provozu,
4. `README.md` — provozní orientace a spuštění projektu.

Pokud je ve starší části dokumentace rozpor s blokem označeným **Aktuální rozhodnutí 29. 8. 2026**, platí novější blok.

Pro vývoj historie se nesmí dělat plošný redesign. Zachovat současný vizuální styl, existující komponenty, navigaci a responzivní chování; změny mají být evoluční.

## Lokální spuštění ve Windows

```powershell
cd C:\Users\trsek\Desktop\tunelbus
Copy-Item .env.example .env
# Doplňte GOLEMIO_API_KEY do .env (soubor se negituje)
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
python -m app
```

Debug: v `.env` nastavte `DEBUG=true` a `LOG_LEVEL=DEBUG`. Kontrola stavu: `http://127.0.0.1:8010/health`; detail bez secretů: `/debug/status`. Log je současně na stdout a v `logs/tunelbus.log`; soubor se rotuje každý den o půlnoci a ponechává se 30 archivů.

Po spuštění je veřejný web lokálně na `http://127.0.0.1:8010/`. Volitelný den se předává například jako `http://127.0.0.1:8010/?date=2026-08-16`.

Testy:

```powershell
pytest
```

## Produkce Ubuntu

V `/srv/anlex/tunelbus/.env` nastavte alespoň `GOLEMIO_API_KEY`, `DATA_DIR`, `BACKUP_DIR` a `LOG_DIR` podle `.env.example`. Systemd spouští aplikaci příkazem `/srv/anlex/tunelbus/.venv/bin/python -m app`.

```bash
sudo systemctl restart tunelbus
sudo systemctl status tunelbus
journalctl -u tunelbus -f
curl http://127.0.0.1:8010/health
```

Databáze je `data/tunelbus.sqlite3` (WAL). Dlouhodobý provoz má používat konzistentní SQLite Backup API, kontrolu `PRAGMA integrity_check` a retention pouze záložních kopií. Primární realtime/raw data se nemažou. Podrobnosti jsou v `zadani.md`.

GTFS snapshot vytváří samostatný idempotentní worker `python -m app.gtfs_worker`; realtime collector proto není blokován stahováním GTFS. Produkční jednotky jsou verzované v `deploy/systemd/tunelbus-gtfs.service` a `deploy/systemd/tunelbus-gtfs.timer` (00:02, 00:32, 01:02 a 02:02). Velké soubory `stop_times.txt`, `stops.txt` a `shapes.txt` se při importu GTFS streamují. `/health` navíc sleduje úložiště, velikosti DB/logů/záloh a stáří daily/intraday záloh; stav je `ok` pouze se zdravou databází, collectorem i provozními kontrolami.

## Web, API a exporty

- `/` — živý přehled linky 145 s mapou, aktuálními statistikami a automatickou obnovou po 20 sekundách.
- `/about` — informační stránka projektu.
- `/history` — historická/analytická část. Její nová podoba se rozvíjí postupně podle `frontend.md` a `web.md`; vývoj musí zachovat současný design a responzivitu.
- `/api/live/summary` — aktuální počet aktivních spojů, zpoždění a podíl spojů včas.
- `/api/live/vehicles` — aktuální polohy vozidel včetně freshness, bez raw payloadu.
- `/api/live/route` — GTFS shapes pro aktuální provozní den; staré snapshoty bez shape dat vrací prázdný seznam.
- `/api/day/2026-08-16/hours` — hodiny provozního dne odvozené z historického GTFS.
- `/api/day/2026-08-16/analytics?from_offset=2&to_offset=5` — základní denní metriky pro celý den nebo zvolený interval offset hodin.
- `/api/day/2026-08-16/summary` — denní agregované statistiky.
- `/api/day/2026-08-16/trips` — přehled plánovaných spojů a jejich realtime statistik.
- `/download/2026-08-16/schedule.csv` — jízdní řád z GTFS snapshotu.
- `/download/2026-08-16/realtime.csv` — normalizovaná realtime pozorování.
- `/download/2026-08-16/realtime.json` — realtime pozorování včetně raw payloadu.

Všechny webové route a exporty jsou read-only; collector i databázový zápis fungují nezávisle na jejich zpracování.

`SERVICE_DAY_BOUNDARY=03:00` určuje hranici provozního dne v časové zóně `Europe/Prague`. GTFS snapshoty nově archivují i body z `shapes.txt`; existující snapshoty se nemění a mohou proto trasu postrádat.

Denní souhrn pod živou mapou používá nezávislou URL volbu `/?date=YYYY-MM-DD`. Horní mapa vždy zobrazuje aktuální provozní den; dolní navigace lze bezpečně přepnout na historický den. Hodiny API používají offset od hranice provozního dne, takže GTFS časy `24:xx` a `25:xx` zůstávají ve správném provozním dni a v UI se zobrazí jako `0` a `1`.

### Jednorázový backfill historických shapes

Pro snapshot vytvořený před zavedením `shape_points` lze explicitně a idempotentně doplnit pouze GTFS shape data:

```powershell
python -m app backfill-shapes --date 2026-08-16 --gtfs "C:\cesta\k\gtfs_20260816.zip"
```

Příkaz nejdřív ověří snapshot, validitu ZIPu, `routes.txt`, `trips.txt`, `shapes.txt`, linku 145, minimálně 75% shodu tripů a nekonfliktní `shape_id`. Do jediné SQLite transakce pak zapisuje výhradně chybějící `shape_points` a dosud prázdné `trips.shape_id`; nemění stop_times, realtime data ani samotný snapshot.

## Nasazení z PowerShellu

```powershell
.\deploy.ps1 -ServerHost 194.182.64.200
```

Skript nahraje pouze `app/`, `requirements.txt` a README; nikdy nepřepisuje `.env`, `data/`, `backups/` ani `logs/`. Následně aktualizuje závislosti, restartuje systemd a ověří health endpoint. Vyžádá-li si `sudo` heslo, zadává se pouze vzdáleně do SSH relace.

## Běžné problémy

- **401/403 Golemio:** ověřte `GOLEMIO_API_KEY`; token se nikdy neloguje.
- **GTFS nebo API výpadek:** collector chybu uloží do `collector_errors`, zaloguje ji a pokračuje příští iterací.
- **Port obsazený:** upravte `PORT`, ovšem v produkci ponechte `HOST=127.0.0.1`.
