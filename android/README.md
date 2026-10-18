# HomeMusic – Android

Kotlin + Jetpack Compose + Media3 (háttérlejátszás, értesítési sáv / zárolt képernyő vezérlők).
Min. Android 12 (API 31).

## APK építése (GitHub Actions)
1. Tedd fel a `homemusic` mappát egy (privát) GitHub repóba.
2. Actions → "Android APK" → Run workflow (vagy push az `android/` mappára).
3. A lefutott munkafolyamat "HomeMusic-apk" artifactjából töltsd le az `app-release.apk`-t, telepítsd (ismeretlen forrásból).

## Helyi építés
Android Studio-val nyisd meg az `android/` mappát (JDK 17), vagy: `gradle assembleRelease`.
