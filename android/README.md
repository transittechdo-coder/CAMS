# CAMS Guard (Android)

The app for guards' phones. It connects to the CAMS computer over the site's Wi-Fi by scanning
one QR code (CAMS: Settings, Phones, Add a phone), then rings a full-screen alarm for fire, smoke
or a person down, even when the phone is locked, and shows the other alerts as notifications.
It also shows the guard screens (alerts, cameras, visitors, find a person).

GitHub builds it (`.github/workflows/android.yml`) as `CAMS-Guard.apk`. The Windows build puts it
inside CAMS, so phones install it from the CAMS computer without internet.

## Signing key

Android only updates an app when the new version is signed with the same key.

* The real key is kept in two repository secrets: `ANDROID_KEYSTORE` (the .jks file, base64) and
  `ANDROID_KEYSTORE_PASSWORD`. Keep a copy of the .jks file and its password somewhere safe:
  if they are lost, phones must uninstall the app and install it again.
* Without those secrets the build uses `test-signing.jks` (password `camsguard-test`). It is
  public, so it is only for testing.

## Build by hand

Needs Android Studio (or the Android SDK) and JDK 17:

    cd android
    gradle assembleRelease -PcamsVersion=1.7.0
