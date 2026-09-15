# NDLI Club Management App — Native Android Project

Official Mobile Client for the **National Digital Library of India (NDLI) Club Management and Employee Activity Tracking System**, developed by **Dr. Anirban Mukherjee**.

---

## 📱 Architecture & Features

This project provides an enterprise-grade native Android wrapper for the NDLI Club Management System, featuring continuous two-way synchronization with the central databases:

1. **Continuous Real-Time Database Sync**:
   - Stays synchronized with the Central Master Database (`data/master/master_clubs.csv`, `data/master/master_activities.csv`) and all 7 Regional Nodal Zone databases.
   - Built-in **Offline-First Synchronization Engine (`offline_sync.js`)** leveraging client-side `IndexedDB`. If field officers lose internet connectivity during campus visits, all activity logs, club approvals, and renewals are safely queued locally and automatically replayed to the Master DB as soon as connection is restored.

2. **Native Device Hardware Integration**:
   - **GPS Geotagging**: Direct integration with hardware location sensors to capture accurate campus latitude and longitude coordinates during offline/online field visits (`captureCampusGPS()`).
   - **Camera & Document Capture**: Native file chooser integration allowing officers to upload workshop attendance sheets, osTicket screenshots, and registration renewals directly from the phone camera or photo gallery.
   - **Native Pull-to-Refresh**: Hardware-accelerated refresh gesture with official NDLI theme colors (`#103125` forest green & `#D97706` golden amber).
   - **Offline Fallback Screen**: Graceful UI indicator when completely disconnected, retaining cached operational data without crashing.

---

## 🛠️ Project Structure

```text
android_app/
├── capacitor.config.json           # Capacitor / Mobile Configuration
├── package.json                   # Project Metadata
├── README.md                      # Compilation & Deployment Guide
└── android/                       # Full Android Studio Native Project
    ├── build.gradle               # Root Gradle Script (Gradle 8.2+)
    ├── settings.gradle            # Project Name & Module Definitions
    ├── gradle.properties          # JVM & AndroidX Compiler Flags
    └── app/
        ├── build.gradle           # Application Module (SDK 34, Min SDK 24)
        ├── proguard-rules.pro     # Optimization & Code Obfuscation Rules
        └── src/main/
            ├── AndroidManifest.xml # Permissions (Internet, GPS, Camera)
            ├── java/in/gov/ndl/clubmanagement/
            │   └── MainActivity.java # WebView Controller & Hardware Bridge
            └── res/               # Android App Resources
                ├── values/        # Strings, Colors, App Themes
                ├── xml/           # FileProvider & Security Configs
                └── mipmap-*/      # High-Definition Launcher Icons (mdpi to xxxhdpi)
```

---

## 🚀 How to Build the `.apk` / `.aab` in Android Studio

### Prerequisites:
- Android Studio Hedgehog (2023.1.1) or Ladybug / Iguana or newer.
- Android SDK Platform 34 (Android 14) installed via SDK Manager.
- Java JDK 17 (recommended for Gradle 8.2+).

### Step-by-Step Instructions:
1. Launch **Android Studio**.
2. Select **File > Open...** (or click **Open** on the Welcome screen).
3. Navigate to and select the directory:
   `C:\Users\HP\.gemini\antigravity\scratch\ndli_club_management\android_app\android`
4. Android Studio will automatically perform a Gradle Sync and download necessary AndroidX dependencies:
   - `androidx.appcompat:appcompat:1.6.1`
   - `com.google.android.material:material:1.11.0`
   - `androidx.swiperefreshlayout:swiperefreshlayout:1.1.0`
   - `androidx.webkit:webkit:1.9.0`
5. To build the debug APK:
   - Go to **Build > Build Bundle(s) / APK(s) > Build APK(s)**.
   - Once compilation finishes, click **locate** in the popup notification to find `app-debug.apk` in:
     `android/app/build/outputs/apk/debug/app-debug.apk`
6. Transfer `app-debug.apk` to any Android phone (Android 7.0 to Android 14) via USB, WhatsApp, or Google Drive, tap to install, and run!

---

## 💻 Building via Command Line (Gradle CLI)

If you have Android SDK and Gradle installed in your terminal PATH:

```powershell
# Navigate into the android directory
cd android_app/android

# Build Debug APK
./gradlew assembleDebug

# Build Release APK / App Bundle (for Google Play Store)
./gradlew assembleRelease
./gradlew bundleRelease
```

---

## ⚙️ Configuring App Server Target

By default, `MainActivity.java` is pre-configured to load the live deployed cloud endpoint:
- **Cloud Endpoint**: `https://script.google.com/macros/s/AKfycbyyBeTLzjrA018d79S1yvgCDduGtyLlG95oJ5BgThV-bU2GUcoQWudYiBkOL_LADDo3/exec`
- **Local Testing Mode**: If testing against your local Python server on the same Wi-Fi network, change `DEFAULT_URL` in `MainActivity.java` to:
  `http://192.168.x.x:8000/employee` (or run `adb reverse tcp:8000 tcp:8000` and use `http://localhost:8000/employee`).

---

## 🛡️ Developer Attribution & Technical Support

- **Lead System Architect & Full-Stack Developer**: Dr. Anirban Mukherjee
- **Location**: Midnapore, West Bengal 721101, India
- **Email**: anirbanmid@gmail.com
- **Contact**: +91 7797387474
- **Affiliation**: National Digital Library of India (NDLI) Project • Central Administration Office, IIT Kharagpur
