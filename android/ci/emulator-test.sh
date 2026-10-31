#!/usr/bin/env bash
# Runs inside the Android emulator job: install CAMS Guard, connect it to the CAMS server running
# on the build machine (10.0.2.2 from inside the emulator), raise alarms, take screenshots.
set -x
OUT=${OUT:-shots}
mkdir -p "$OUT"
PKG=com.transittech.camsguard
shot() { sleep "${2:-1}"; adb exec-out screencap -p > "$OUT/$1.png"; }
fail=0

adb install -r android/app/build/outputs/apk/debug/app-debug.apk || exit 1
adb shell pm grant $PKG android.permission.POST_NOTIFICATIONS || true
adb shell cmd appops set $PKG USE_FULL_SCREEN_INTENT allow || true
adb shell dumpsys deviceidle whitelist +$PKG || true
adb shell settings put system screen_off_timeout 600000

# 1. welcome screen
adb shell am start -W -n $PKG/.MainActivity
shot 1-welcome 4
adb shell am force-stop $PKG

# diagnostics, saved next to the screenshots
{
  echo "QR=$QR"
  ss -ltnp 2>/dev/null | grep 8765
  curl -s -m 5 http://127.0.0.1:8765/api/status; echo
  adb shell "echo -e 'GET /api/status HTTP/1.0\r\n\r\n' | nc -w 5 10.0.2.2 8765" | tail -3
  adb shell ping -c 2 10.0.2.2
} > "$OUT/diag.txt" 2>&1

# 2. connect with the code (debug hook instead of the camera)
adb shell am start -W -n $PKG/.MainActivity --es qr "'$QR'"
shot 2-connected 12
adb shell dumpsys activity services $PKG | grep -q WatchService || { echo "::error::background service not running"; fail=1; }

# 3. alarm while the phone is in use
curl -s -b /tmp/ck -X POST http://127.0.0.1:8765/api/alerts/test-emergency
shot 3-alarm 10
adb shell dumpsys activity activities | grep -q "AlarmActivity" || { echo "::error::alarm screen did not open"; fail=1; }
adb shell dumpsys notification --noredact | grep -q "ALARM TEST" || echo "::warning::alarm notification text not found"
# press "Stop the test" through the API, as the guard would on another phone
for id in $(curl -s -b /tmp/ck http://127.0.0.1:8765/api/alerts/emergencies | python3 -c "import sys,json;print(' '.join(str(a['id']) for a in json.load(sys.stdin)))"); do
  curl -s -b /tmp/ck -X POST http://127.0.0.1:8765/api/alerts/$id/ack; done
shot 4-after-ack 10
adb shell dumpsys activity activities | grep "mResumedActivity\|topResumedActivity" | grep -q AlarmActivity && { echo "::error::alarm screen stayed open after it was handled"; fail=1; }

# 4. alarm while the phone is locked in a pocket
adb shell input keyevent KEYCODE_POWER
sleep 3
python3 - <<'PY'
import sqlite3, time, os
c = sqlite3.connect(os.environ["CAMS_DATA_DIR"] + "/cams.db")
c.execute("INSERT INTO alerts(created_at, kind, message) VALUES (?, 'fire', 'Possible FIRE at Store room camera (Main block). Check the camera now and call for help.')", (time.time(),))
c.commit()
PY
shot 5-locked-alarm 12
adb shell dumpsys power | grep -i "mWakefulness=" || true
adb shell dumpsys activity activities | grep -q "AlarmActivity" || { echo "::error::alarm did not open on the locked phone"; fail=1; }

# 5. other alerts become notifications
python3 - <<'PY'
import sqlite3, time, os
c = sqlite3.connect(os.environ["CAMS_DATA_DIR"] + "/cams.db")
c.execute("UPDATE alerts SET acknowledged = 1")
c.execute("INSERT INTO alerts(created_at, kind, message) VALUES (?, 'visitor_overstay', 'Visitor Juma Ally (visiting Mr Mushi) should have left at 14:00 and has not checked out.')", (time.time(),))
c.commit()
PY
sleep 25
adb shell cmd statusbar expand-notifications || true
shot 6-notification 3
adb shell cmd statusbar collapse || true
adb shell dumpsys notification --noredact | grep -q "Visitor stayed too long" || { echo "::error::normal alert notification missing"; fail=1; }

# 6. the guard screens inside the app
adb shell am start -W -n $PKG/.MainActivity
shot 7-main 6
adb logcat -d -s AndroidRuntime:E | tail -40
adb logcat -d | grep -i -E "CAMSGuard|camsguard|cleartext|AndroidRuntime" | tail -80 > "$OUT/logcat.txt"
exit $fail
