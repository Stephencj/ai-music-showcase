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
    // Serve the bundled UI over http (not https) so calling the Mac's http
    // API isn't blocked as mixed content (Amazon's WebView enforces that
    // even when "allow mixed content" is set).
    private static final String APP_ORIGIN = "http://appassets.androidplatform.net";
    private static final String APP_URL = APP_ORIGIN + "/assets/web/index.html";
    private static final String PREFS = "aimusic";
    private static final String KEY_URL = "server_url";

    private WebView web;
    private WebViewAssetLoader assetLoader;
    private String apiBase = "";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        WebView.setWebContentsDebuggingEnabled(true);

        assetLoader = new WebViewAssetLoader.Builder()
                .setHttpAllowed(true)   // serve the bundled UI over http (matches the http API)
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
            public void onPageFinished(WebView v, String url) {
                report("loaded", "page=" + url + " ua=" + v.getSettings().getUserAgentString());
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView v, WebResourceRequest req) {
                String path = req.getUrl().getPath();
                // Serve index.html ourselves with the API base injected inline,
                // so it works on ANY WebView (no addDocumentStartJavaScript /
                // androidx feature needed — Amazon's WebView may lack it).
                if (path != null && path.endsWith("/index.html")) {
                    WebResourceResponse r = injectedIndexHtml();
                    if (r != null) return r;
                }
                return assetLoader.shouldInterceptRequest(req.getUrl());
            }

            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                report("loaderror", err.getErrorCode() + ": " + err.getDescription()
                        + " for=" + req.getUrl() + " mainFrame=" + req.isForMainFrame());
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
                    report("console", m);
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

    /** Remember the API base (injected into index.html as it's served), then
     * load the bundled UI. Also try addDocumentStartJavaScript as a backup. */
    private void startApp(String base) {
        this.apiBase = base;
        if (WebViewFeature.isFeatureSupported(WebViewFeature.DOCUMENT_START_SCRIPT)) {
            String js = "try{localStorage.setItem('aimusic.apiBase'," + jsString(base) + ");}catch(e){}";
            try {
                WebViewCompat.addDocumentStartJavaScript(web, js, Collections.singleton(APP_ORIGIN));
            } catch (Exception ignored) {
            }
        }
        web.loadUrl(APP_URL);
    }

    /** Serve the bundled index.html with the API base injected inline so the
     * web app knows where the Mac is — independent of any WebView feature. */
    private WebResourceResponse injectedIndexHtml() {
        try {
            java.io.InputStream is = getAssets().open("web/index.html");
            java.io.ByteArrayOutputStream bos = new java.io.ByteArrayOutputStream();
            byte[] tmp = new byte[8192];
            int n;
            while ((n = is.read(tmp)) > 0) bos.write(tmp, 0, n);
            is.close();
            String html = bos.toString("UTF-8");
            String b = jsString(apiBase);
            // Set the API base + a visible diagnostic: any failed /api call (network
            // error or non-OK status) shows a red bar with the address + reason, so
            // a "not connecting" report becomes self-explanatory.
            String inject = "<script>(function(){"
                    + "try{localStorage.setItem('aimusic.apiBase'," + b + ");}catch(e){}"
                    + "function show(m){try{var d=document.getElementById('aimusic_diag')||document.createElement('div');"
                    + "d.id='aimusic_diag';d.style.cssText='position:fixed;bottom:0;left:0;right:0;max-height:40%;overflow:auto;"
                    + "background:#b00020;color:#fff;font:11px monospace;padding:6px;z-index:2147483647;white-space:pre-wrap';"
                    + "d.textContent='API base: '+(" + b + ")+'\\n'+m;(document.body||document.documentElement).appendChild(d);}catch(e){}"
                    + "try{console.error('AIMUSIC_DIAG '+m);}catch(e){}}"
                    + "var of=window.fetch;window.fetch=function(u,o){return of(u,o).then(function(res){"
                    + "if(!res.ok&&(''+u).indexOf('/api/')>=0)show('HTTP '+res.status+' for '+u);return res;})"
                    + ".catch(function(err){show('FETCH FAILED: '+u+'\\n'+err);throw err;});};"
                    + "})();</script>";
            int i = html.indexOf("<head>");
            html = (i >= 0)
                    ? html.substring(0, i + 6) + inject + html.substring(i + 6)
                    : inject + html;
            return new WebResourceResponse("text/html", "UTF-8",
                    new java.io.ByteArrayInputStream(html.getBytes("UTF-8")));
        } catch (Exception e) {
            return null;
        }
    }

    private static String jsString(String v) {
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'";
    }

    private static String jsonStr(String v) {
        if (v == null) return "null";
        return "\"" + v.replace("\\", "\\\\").replace("\"", "\\\"")
                .replace("\n", "\\n").replace("\r", "") + "\"";
    }

    /** POST a diagnostic to the Mac (Java HTTP, off the UI thread) so the
     * tablet's WebView errors land in data/outputs/clientlog.jsonl — eyes I
     * can read without being on the device. */
    private void report(final String kind, final String msg) {
        final String base = this.apiBase;
        if (base == null || base.isEmpty()) return;
        new Thread(() -> {
            try {
                java.net.HttpURLConnection c =
                        (java.net.HttpURLConnection) new java.net.URL(base + "/api/clientlog").openConnection();
                c.setConnectTimeout(5000);
                c.setReadTimeout(5000);
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json");
                String body = "{\"kind\":" + jsonStr(kind) + ",\"msg\":" + jsonStr(msg)
                        + ",\"apiBase\":" + jsonStr(base) + "}";
                c.getOutputStream().write(body.getBytes("UTF-8"));
                c.getResponseCode();
                c.disconnect();
            } catch (Exception ignored) {
            }
        }).start();
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
