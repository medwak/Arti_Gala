#!/usr/bin/env sh
# Build the Arti Gala Android app (APK) with the plain Android build tools, no Gradle.
#
# Needs: a JDK (javac, keytool), aapt, dx (dalvik-exchange), zipalign, apksigner,
# and android.jar for API 34. On Ubuntu/Debian:
#   sudo apt install openjdk-17-jdk-headless aapt dalvik-exchange zipalign apksigner
#   curl -L -o android-34.jar https://raw.githubusercontent.com/Sable/android-platforms/master/android-34/android.jar
#   ANDROID_JAR=$PWD/android-34.jar ./build.sh
#
# With the full Android SDK installed you can instead point ANDROID_JAR at
# $ANDROID_HOME/platforms/android-34/android.jar.
set -eu
cd "$(dirname "$0")"

: "${ANDROID_JAR:?set ANDROID_JAR to the path of android.jar (API 34)}"
VERSION_CODE=${VERSION_CODE:-1}
VERSION_NAME=${VERSION_NAME:-0.1.0}
KEYSTORE=${KEYSTORE:-arti-gala.keystore}
KEY_ALIAS=${KEY_ALIAS:-artigala}
KEY_PASS=${KEY_PASS:-artigala}
DX=$(command -v dalvik-exchange || command -v dx)

rm -rf build
mkdir -p build/gen build/classes build/dex

echo "1/6 resources"
aapt package -f -m \
  -J build/gen \
  -M AndroidManifest.xml \
  -S res \
  -I "$ANDROID_JAR" \
  --min-sdk-version 21 --target-sdk-version 34 \
  --version-code "$VERSION_CODE" --version-name "$VERSION_NAME" \
  -F build/unsigned.apk

echo "2/6 compile"
javac --release 8 -nowarn -Xlint:-options \
  -classpath "$ANDROID_JAR" \
  -d build/classes \
  $(find src build/gen -name '*.java')

echo "3/6 dex"
"$DX" --dex --min-sdk-version=21 --output=build/dex/classes.dex build/classes

echo "4/6 package"
(cd build/dex && aapt add ../unsigned.apk classes.dex >/dev/null)

echo "5/6 align"
zipalign -f -p 4 build/unsigned.apk build/aligned.apk

echo "6/6 sign"
if [ ! -f "$KEYSTORE" ]; then
  keytool -genkeypair -noprompt -keystore "$KEYSTORE" -alias "$KEY_ALIAS" \
    -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$KEY_PASS" -keypass "$KEY_PASS" -dname "CN=Arti Gala, O=Arti Gala"
fi
apksigner sign --ks "$KEYSTORE" --ks-key-alias "$KEY_ALIAS" \
  --ks-pass "pass:$KEY_PASS" --key-pass "pass:$KEY_PASS" \
  --min-sdk-version 21 \
  --out "build/arti-gala-$VERSION_NAME.apk" build/aligned.apk
apksigner verify --min-sdk-version 21 "build/arti-gala-$VERSION_NAME.apk"

echo "Built android/build/arti-gala-$VERSION_NAME.apk"
