# Tunelbus – denní zálohy na Google Drive a bezpečná lokální retence

## Provozní uspořádání
- Živá databáze `data/tunelbus.sqlite3` zůstává **kompletní**, nikdy ji retence nemaže ani nemění.
- Denní záloha vzniká v 02:30 do `backups/daily/tunelbus_YYYY-MM-DD.sqlite3.zst`, s datem předchozího dne. SQLite Backup API, integrity_check a Zstandard kontrola.
- Upload na `gdrive:Tunelbus/Zálohy` běží v 04:00 a porovnává SHA-256 celé komprimované zálohy se skutečně přečtenou vzdálenou kopií.
- Samostatný úplný archiv `gdrive:Tunelbus/Archiv/` se retencí nemění. Vzdálené denní zálohy se také automaticky nemažou.
- Vnitrodenní zálohy zůstávají místní; jejich komprimované soubory pro **včerejší den** lze odstranit, jen když byl tento denní backup úspěšně nahrán a ověřen.
- Místní komprimované denní zálohy zůstávají pro **poslední 3 dokončené kalendářní dny** včetně právě nahraného dne. Každá starší lokální denní záloha se musí porovnat s její vlastní vzdálenou kopií.
- Historické nekomprimované soubory `*.sqlite3` se **nikdy automaticky nemažou**. Jejich zvláštní ruční úklid je samostatná operace.

## Důležitá bezpečnostní změna
`backup.sh` už nic nemaže na základě `mtime`. Staré čtrnáctidenní `find -delete` bylo odstraněno: lokální snapshot se nesmí ztratit při výpadku Google Disku. Čištění se volá až ze skriptu `scripts/upload-daily-backup.sh` po dokončeném vzdáleném SHA-256 ověření.

`scripts/prune-verified-backups.sh` má ve výchozím stavu **dry-run**. Soubory odstraní pouze s `TUNELBUS_RETENTION_APPLY=1`. Při chybě Google Drive, checksumu nebo komprimovaného souboru skončí bez mazání. Provozní účet `anlex` musí mít právo zapisovat do adresářů `backups/daily` a `backups/intraday` (mazání souborů vyžaduje zápis do adresáře). Před nastavením `APPLY=1` zkontrolujte oprávnění obou adresářů, aplikujte potřebná nejmenší oprávnění po zvláštním schválení a ověřte výstup dry-run. Nepoužívat rekurzivní chmod nebo chown nad daty.

## Kontrola bez mazání
```bash
cd /srv/anlex/tunelbus
bash tests/smoke_compressed_backups.sh
bash tests/smoke_verified_retention.sh
sudo -u anlex /usr/bin/bash scripts/upload-daily-backup.sh
stat -c '%A %U:%G %n' backups/daily backups/intraday
```
Pozor: přímé spuštění jako `anlex` nemusí mít přístup ke komprimované denní záloze bez `SupplementaryGroups=tunelbus`. Pro reálný ruční test použijte `sudo systemctl start tunelbus-gdrive-upload.service` a prohlédněte journal. Ten upload při opakovaném běhu musí projít jako immutable a retence zůstane dry-run.

## Zapnutí mazání až po kontrole
V systemd drop-in lze přidat:
```ini
[Service]
Environment=TUNELBUS_RETENTION_APPLY=1
```
Následuje `sudo systemctl daemon-reload`, spuštění jednoho testovacího uploadu a kontrola journalu, seznamu zachovaných souborů a `df -h`. Úspěšný upload **není automaticky důkaz, že soubory zmizely**; sledujte `PRUNED` nebo `WOULD_PRUNE`.

Pravidelné selhání uploadu se nesmí tiše přehlížet: nastavit a otestovat upozornění. Pravidelně provádět i zkušební obnovu.
