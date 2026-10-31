plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Version follows CAMS (cams/__init__.py), passed in by the build: -PcamsVersion=1.7.0
val camsVersion = (project.findProperty("camsVersion") as String?) ?: "1.0.0"
val parts = camsVersion.split(".").map { it.toIntOrNull() ?: 0 } + listOf(0, 0, 0)

android {
    namespace = "com.transittech.camsguard"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.transittech.camsguard"
        minSdk = 24
        targetSdk = 34
        versionCode = parts[0] * 10000 + parts[1] * 100 + parts[2]
        versionName = camsVersion
    }

    signingConfigs {
        create("release") {
            val ks = System.getenv("CAMS_KEYSTORE")
            if (ks != null && file(ks).exists()) {
                storeFile = file(ks)
                storePassword = System.getenv("CAMS_KEYSTORE_PASSWORD")
                keyAlias = System.getenv("CAMS_KEY_ALIAS") ?: "camsguard"
                keyPassword = System.getenv("CAMS_KEYSTORE_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = if (System.getenv("CAMS_KEYSTORE") != null) signingConfigs.getByName("release")
                            else signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures { buildConfig = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.journeyapps:zxing-android-embedded:4.3.0")
}
