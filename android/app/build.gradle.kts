plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Optional release signing: provided by CI secrets / env. Without them the release APK is debug-signed
// (still installable, just not suitable for the Play Store).
val ksPath: String? = System.getenv("GITDESK_KEYSTORE")

android {
    namespace = "dev.gitdesk.client"
    compileSdk = 34

    defaultConfig {
        applicationId = "dev.gitdesk.client"
        minSdk = 26            // Android 8.0+
        targetSdk = 34
        versionCode = 11
        versionName = "1.3.0"
    }

    signingConfigs {
        if (ksPath != null) {
            create("release") {
                storeFile = file(ksPath)
                storePassword = System.getenv("GITDESK_KS_PASS")
                keyAlias = System.getenv("GITDESK_KEY_ALIAS")
                keyPassword = System.getenv("GITDESK_KEY_PASS")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release") ?: signingConfigs.getByName("debug")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
