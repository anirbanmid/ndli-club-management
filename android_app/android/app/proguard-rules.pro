# NDLI Club Management App ProGuard Rules
-keepattributes JavascriptInterface
-keepclassmembers class * {
    @android.webkit.JavascriptInterface <methods>;
}
-keepclassmembers class in.gov.ndl.clubmanagement.MainActivity$AndroidBridge {
    <methods>;
}
