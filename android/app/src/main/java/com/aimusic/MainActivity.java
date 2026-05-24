package com.aimusic;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.ConsoleMessage;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.Toast;

import androidx.webkit.WebViewAssetLoader;
import androidx.webkit.WebViewCompat;
import androidx.webkit.WebViewFeature;

import java.util.Collections;

/**
 * Self-contained app: the React UI is bundled in the APK (assets/web) and
 * served to the WebView over a virtual https origin via WebViewAssetLoader,
 * so the screen loads instantly from the device — a flaky connection can no
 * longer leave it blank. Only the music data is fetched from the Mac's API,
 * whose address is injected as the web app's apiBase before it runs.
 */
public class MainActivity extends Activity {

    private static final String DEFAULT_API = "http://100.64.0.10:7860";
    private static final String APP_ORIGIN = "https://appassets.androidplatform.net";
    private static final String APP_URL = APP_ORIGIN + "/assets/web/index.html";
    private static final String PREFS = "aimusic";
    private static final String KEY_URL = "server_url";

    private WebView web;
    private WebViewAssetLoader assetLoader;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView.setWebContentsDebuggingEnabled(true);

        assetLoader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        // The page is https (appassets) but the Mac API is http → allow it.
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
                return assetLoader.shouldInterceptRequest(req.getUrl());
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {
                    showError("Load error " + err.getErrorCode() + ": " + err.getDescription()
                            + "\n" + req.getUrl());
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(ConsoleMessage cm) {
                if (cm.messageLevel() == ConsoleMessage.MessageLevel.ERROR) {
                    final String m = cm.message() + "  (" + cm.sourceId() + ":" + cm.lineNumber() + ")";
                    runOnUiThread(() -> Toast.makeText(MainActivity.this, m, Toast.LENGTH_LONG).show());
                }
                return true;
            }
        });

        setContentView(web);

        String api = prefs().getString(KEY_URL, "");
        if (api.isEmpty()) {
            promptForUrl();
        } else {
            startApp(api);
        }
    }

    /** Inject the API base into the page, then load the bundled UI. */
    private void startApp(String apiBase) {
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            String js = "try{localStorage.setItem('aimusic.apiBase'," + jsString(apiBase) + ");}catch(e){}";
            try {
                WebViewCompat.addDocumentStartJavaScript(web, js, Collections.singleton(APP_ORIGIN));
            } catch (Exception ignored) {
            }
        }
        web.loadUrl(APP_URL);
    }

    private static String jsString(String v) {
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'";
    }

    private void showError(final String msg) {
        runOnUiThread(() -> web.loadData(
                "<html><body style='font:16px -apple-system,sans-serif;padding:1.2em;color:#b00020'>"
                        + "<h3>Couldn't load</h3><pre style='white-space:pre-wrap;word-break:break-word'>"
                        + msg.replace("<", "&lt;") + "</pre></body></html>",
                "text/html", "utf-8"));
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private void promptForUrl() {
        final EditText input = new EditText(this);
        input.setText(prefs().getString(KEY_URL, DEFAULT_API));
        input.setSelection(input.getText().length());
        new AlertDialog.Builder(this)
                .setTitle("Mac server (API) address")
                .setMessage("Where to fetch music from — e.g. http://100.64.0.10:7860 (Tailscale) "
                        + "or http://192.168.1.10:7860 (same Wi-Fi). The app screen is built in; this "
                        + "is only the data connection.")
                .setView(input)
                .setCancelable(false)
                .setPositiveButton("Connect", (d, w) -> {
                    String u = input.getText().toString().trim();
                    if (!u.isEmpty()) {
                        prefs().edit().putString(KEY_URL, u).apply();
                        recreate();   // fresh WebView with the new injected apiBase
                    }
                })
                .show();
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "Server URL…");
        menu.add(0, 2, 0, "Reload");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        switch (item.getItemId()) {
            case 1: promptForUrl(); return true;
            case 2: web.reload(); return true;
            default: return super.onOptionsItemSelected(item);
        }
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
