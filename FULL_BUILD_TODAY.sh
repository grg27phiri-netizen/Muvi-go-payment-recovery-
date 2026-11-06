#!/data/data/com.termux/files/usr/bin/bash

cd "$HOME/MUVI_GO_PAYMENT_RECOVERY_V1" || exit 1

REPORT="FULL_BUILD_REPORT_$(date +%Y%m%d_%H%M%S).txt"
mkdir -p reports backups

exec > >(tee "$REPORT") 2>&1

echo "=========================================="
echo "          MUVI GO V6 FULL BUILD"
echo "          GP CREATIONS"
echo "=========================================="

echo
echo "1. DATABASE CHECKPOINT"
if [ -f data/muvi_go.db ]; then
    cp -p data/muvi_go.db "backups/database_before_full_build_$(date +%Y%m%d_%H%M%S).db"
    echo "DATABASE CHECKPOINT: PASS"
else
    echo "DATABASE MISSING"
    exit 1
fi

echo
echo "2. PROJECT IDENTITY"
python -m json.tool BUILD_MANIFEST.json >/dev/null || exit 1
python -m json.tool static/manifest.json >/dev/null || exit 1
echo "IDENTITY: PASS"

echo
echo "3. PYTHON COMPILATION"
python -m py_compile app.py auth.py payments.py run.py || exit 1
echo "PYTHON: PASS"

echo
echo "4. REGRESSION TESTS"
python -m unittest discover -s tests -v
TEST_RESULT=$?

if [ "$TEST_RESULT" -ne 0 ]; then
    echo "REGRESSION: FAILED"
    echo "STOPPING BUILD TO PROTECT WORKING BASELINE"
    exit 1
fi
echo "REGRESSION: PASS"

echo
echo "5. MEDIA ROUTE CHECK"
python -m py_compile test_media_routes.py verify_media.py || exit 1
echo "MEDIA TEST FILES: PASS"

echo
echo "6. ANDROID BUILD ENVIRONMENT"
command -v java
java -version 2>&1 | head -2

for tool in gradle aapt aapt2 d8 apksigner zipalign; do
    if command -v "$tool" >/dev/null 2>&1; then
        echo "$tool: AVAILABLE"
    else
        echo "$tool: MISSING"
    fi
done

echo
echo "7. ANDROID SDK CHECK"
if [ -n "${ANDROID_HOME:-}" ]; then
    SDK="$ANDROID_HOME"
elif [ -n "${ANDROID_SDK_ROOT:-}" ]; then
    SDK="$ANDROID_SDK_ROOT"
else
    SDK=""
fi

if [ -n "$SDK" ] && [ -d "$SDK/platforms" ]; then
    echo "ANDROID SDK: FOUND"
else
    echo "ANDROID SDK: NOT CONFIGURED"
fi

echo
echo "8. ANDROID PROJECT CHECK"
if [ -x ./gradlew ] && [ -d android ]; then
    if [ -n "$SDK" ]; then
        ./gradlew --no-daemon assembleDebug
        BUILD_RESULT=$?
        if [ "$BUILD_RESULT" -eq 0 ]; then
            echo "ANDROID APK BUILD: PASS"
            find android -name '*.apk' -type f -exec ls -lh {} \;
        else
            echo "ANDROID APK BUILD: FAILED"
        fi
    else
        echo "APK BUILD BLOCKED: ANDROID SDK REQUIRED"
    fi
else
    echo "APK BUILD BLOCKED: ANDROID PROJECT/GRADLE WRAPPER MISSING"
fi

echo
echo "9. FINAL STATUS"
echo "Project: MUVI GO V6"
echo "Owner/operator: GP Creations"
echo "Regression: PASS"
echo "Production streams: NOT VERIFIED"
echo "Live payments: NOT CONNECTED"
echo "DRM: NOT IMPLEMENTED"
echo "APK: SEE ANDROID BUILD RESULT"

echo
echo "REPORT: $REPORT"
echo "=========================================="
echo "          INSPECTION FINISHED"
echo "=========================================="
