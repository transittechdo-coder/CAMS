# CAMS - Camera AI Monitoring System

CAMS finds people on a school or company compound using the cameras that are already there.
Enrol a person's face once; whenever any camera sees them, CAMS logs where and when, so a guard
can type a name and see **where that person was last seen**, their path on a 2D or 3D map of
the campus, and a timeline of their day.

A collaboration between **TransitTech** and **Godwill Andrew Madunda**.

## What it does

| Area | Features |
| --- | --- |
| Cameras | Any IP / Ethernet / PoE camera or NVR channel (RTSP), HTTP/MJPEG cameras and phones, USB webcams, video files. Address helper for Hikvision, Dahua, Uniview, TP-Link, Reolink, Axis, EZVIZ and ONVIF. Connection test with preview. Network scan to find cameras. Auto-reconnect. |
| Recognition | Face detection and recognition on every camera, on the PC itself (OpenCV YuNet + SFace). 360° enrolment: seven face views (front, half left, left, half right, right, up, down) used for recognition, plus back and top reference pictures for guards. Guided webcam wizard, any CAMS camera, photos with a chosen side, or a turn-around video split into the best picture per angle. Duplicate-face warning. |
| Finding people | Search by name or ID, or by photo. Last seen place and time, movement trail on the map, timeline for today / 24 h / 7 / 30 days. |
| Campus builder | Draw buildings, zones, gates, fields and parking on a plan or satellite picture; move, turn and duplicate them; set heights, add and name floors; put cameras on a building and floor, drag them into place and turn them to face the right way. 2D plan and 3D view. |
| Restricted areas | Per building or zone: only certain people may enter (by type, class/department or name), or certain people may not; closed hours. Alerts when someone is seen where they are not allowed. |
| Suspicious activity | On-device person-detection AI (NanoDet-Plus) with rules per camera: loitering, crowding, running, people present during closed hours, camera covered / blurred / turned away. Alerts come with a scene picture. These flag situations for a guard to check; they do not judge intent. |
| Alerts | Rule breaks, watch-list people seen, unknown people on restricted cameras, suspicious activity, cameras offline. |
| Privacy and security | Faces of people who are not enrolled are blurred. Consent recorded per person. Automatic deletion after N days. Full erasure of a person. Admin / operator / viewer roles. Activity log of every search and change. Data never leaves the PC. |
| Windows app | One setup .exe, desktop window, first-run setup wizard, guided tour and a written how-to guide. |

**Works offline.** The AI models, 3D engine, database and interface are all inside the installer.
Internet is needed only to download the installer.

## Install (users)

1. Download `CAMS-Setup-x.y.z.exe` from the [Releases](../../releases) page
   (or from the latest run on the **Actions** tab, under *Artifacts*).
2. Run it and follow the steps. Windows 10 or 11, 64-bit. No administrator rights are needed;
   CAMS installs for the current user, like Scratch or Zoom.
3. CAMS opens at the end of setup. Later, double-click the **CAMS** icon on the desktop
   (or find CAMS in the Start menu). It opens in its own window and needs no internet.

To install for every user of the PC, an IT admin can run `CAMS-Setup-x.y.z.exe /ALLUSERS`.

Then read [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

**Suggested PC:** 4-core CPU (Intel i5 / Ryzen 5 or better), 8 GB RAM. One such PC handles about
8-12 cameras at 2 analysed frames per second each. No graphics card is needed.

## Build it yourself (developers)

On Windows, double-click **`build.bat`**. It sets up Python packages, downloads the AI models,
runs the tests, builds `CAMS.exe` and `installer\Output\CAMS-Setup-<version>.exe` (if
[Inno Setup 6](https://jrsoftware.org/isdl.php) is installed), then **installs CAMS on that PC,
puts the CAMS icon on the desktop and opens CAMS**. After that, just double-click the icon.
Copy `CAMS-Setup-<version>.exe` to install CAMS on other PCs.

GitHub also builds the installer automatically on every push to `main`
(`.github/workflows/build-windows.yml`); find it on the **Actions** tab, open the latest
run and download **CAMS-Setup** under *Artifacts*.

To publish a version for everyone: on GitHub open **Releases → Draft a new release**, type a new
tag such as `v1.0.0`, and press **Publish release**. The workflow builds the installer and
attaches it to that release within about 10 minutes.

Run from source on any OS:

```bash
pip install -r requirements-dev.txt
python scripts/download_models.py   # once, 43 MB
python -m pytest -q                 # tests
python -m cams                      # opens the app (or: python -m cams --no-window)
```

Behind its window, CAMS runs a small private web server that only this PC can reach
(127.0.0.1; no admin rights needed). The window is Edge WebView2, or Edge/Chrome in app mode
if WebView2 is missing. Options: `--lan` lets other PCs on the network open CAMS at `http://<this-pc>:8765`;
`--port 8770` changes the port. Data is stored in `%APPDATA%\CAMS` (Windows) or `~/.cams`.

## How it is built

```
cams/
  main.py         start-up: local server + desktop window (pywebview / Edge WebView2)
  api.py          HTTP API used by the interface
  system.py       camera threads -> recognition workers -> sightings, alerts, live view
  cameras.py      camera connections, address templates, network scan
  face_engine.py  face detection, face prints, pose (angle) estimation, blurring
  activity.py     person detection, tracking and suspicious-activity rules
  db.py           SQLite schema and helpers
  auth.py         accounts, roles, sessions
  static/         the interface (plain JavaScript, no build step)
    js/map2d.js   site plan and campus builder
    js/map3d.js   3D campus (three.js, bundled)
    js/enrol.js   five-angle face capture wizard
installer/        PyInstaller and Inno Setup recipes
scripts/          model download, icon
tests/            automated tests
```

Recognition pipeline: each camera thread keeps only the newest frame; a small pool of workers
analyses frames at the configured rate, matches each face print against the enrolled gallery
(cosine similarity, default threshold 0.40), and merges repeated sightings of the same person
on the same camera into one record. Each sighting is checked against the access rules of the
building or zone the camera watches. In parallel, a person detector and tracker feed the activity
rules (loitering, crowding, running, closed hours, tampering).

## Responsible use

Face recognition handles sensitive personal data. Read [docs/PRIVACY.md](docs/PRIVACY.md) before
deployment: get consent (from parents or guardians for students under 18), put up signs, give
accounts only to staff who need them, and keep records only as long as needed. Follow the
Personal Data Protection Act of Tanzania (2022) or the law of your country.

## Licence

Copyright (c) 2026 TransitTech and Godwill Andrew Madunda. All rights reserved. See [LICENSE](LICENSE).
Third-party components keep their own licences (listed in LICENSE).
