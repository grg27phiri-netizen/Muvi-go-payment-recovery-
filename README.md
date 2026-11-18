ó
<<<<<<< HEAD
# MUVI_GO_PAYMENT_RECOVERY_V1
Muvi go payment recovery v1.verfied payment recovery build 
# MUVI GO — Consolidated Streaming Prototype

Version: 1.0 Consolidated Prototype
Creator: George Phiri · GP Creations · © 2026
Brand status: Proposed MUVI GO rebrand; use of Muvi TV branding/content requires authorization.

## Consolidated from
- ZIGO TV Deployment v5.15.1 (Flask, SQLite, Studio, launchers, Docker).
- ZIGO TV Reference Match Frontend (12-channel mobile-first design).
- ZIGO TV Streaming Engine Stage (HLS.js scaffold, native HLS fallback, fullscreen and local saved channels).

## Run locally
Requirements: Python 3.11+ and internet access for the HLS.js CDN script if you need browser HLS.js playback.

Linux/macOS/Termux with Python and Flask installed:
```sh
python -m pip install -r requirements.txt
python run.py
```
Open `http://127.0.0.1:5000`.

Windows: run `start_zigo.bat` (the legacy filename is retained for compatibility).
Docker: `docker compose up --build`.

Studio: `http://127.0.0.1:5000/admin`
Health: `http://127.0.0.1:5000/api/health`
Search: `http://127.0.0.1:5000/api/search?q=Zambian`

## Current verified scope
The package combines the existing streaming UI with the existing Flask/SQLite deployment prototype. It includes the channel grid, category filters, search, saved channels in browser local storage, fullscreen control, HLS.js/native-HLS playback scaffold, local Studio catalogue and a health endpoint.

## Important limitations
- Channel names are prototype placeholders. No live feed is included or presumed authorized. `STREAMS` is intentionally empty. Add only feeds you are authorized to distribute.
- The Studio and media API are prototype-level and do not have production authentication/authorization. Do not expose this build publicly or use it for real payments or sensitive data.
- No payment provider, production CDN, DRM, production transcoding pipeline or production backend is integrated.
- PWA shell caching is best-effort; offline video is not provided.
- MUVI GO is a proposed rebrand. Obtain Muvi TV's authorization for trademarks, logos, channels and content before commercial use.

## Verification
Run: `python -m unittest discover -s tests -v`
=======
# Muvi-go-payment-recovery-
Zambian first video on demand 
>>>>>>> origin/main
ó

