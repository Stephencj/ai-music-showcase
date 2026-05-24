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

/**
 * WebView wrapper for the AI Music Studio React app. Loads a configurable
 * server URL (default the Mac's Tailscale address). Surfaces load + JS
 * errors on screen / as toasts instead of failing to a blank white page,
 * and disables HTTP caching so a fresh server build always loads.
 */
public class MainActivity extends Activity {

    private static final String DEFAULT_URL = "http://100.64.0.10:5174";
    private static final String PREFS = "aimusic";
    private static final String KEY_URL = "server_url";

    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        WebView.setWebContentsDebuggingEnabled(true);
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);   // always fetch the current build

        web.setWebViewClient(new WebViewClient() {
            @Override
            public void onReceivedError(WebView v, WebResourceRequest req, WebResourceError err) {
                if (req != null && req.isForMainFrame()) {
                    showError("Load error " + err.getErrorCode() + ": " + err.getDescription()
                            + "\n" + req.getUrl());
                }
            }

            @Override
            public void onReceivedHttpError(WebView v, WebResourceRequest req, WebResourceResponse resp) {
                if (req != null && req.isForMainFrame()) {
                    showError("HTTP " + resp.getStatusCode() + "\n" + req.getUrl());
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

        String url = prefs().getString(KEY_URL, "");
        if (url.isEmpty()) {
            promptForUrl();
        } else {
            web.loadUrl(url);
        }
    }

    private void showError(final String msg) {
        runOnUiThread(() -> web.loadData(
                "<html><body style='font:16px -apple-system,sans-serif;padding:1.2em;color:#b00020'>"
                        + "<h3>Couldn't load the app</h3><pre style='white-space:pre-wrap;word-break:break-word'>"
                        + msg.replace("<", "&lt;") + "</pre></body></html>",
                "text/html", "utf-8"));
    }

    private SharedPreferences prefs() {
        return getSharedPreferences(PREFS, MODE_PRIVATE);
    }

    private void promptForUrl() {
        final EditText input = new EditText(this);
        input.setText(prefs().getString(KEY_URL, DEFAULT_URL));
        input.setSelection(input.getText().length());
        new AlertDialog.Builder(this)
                .setTitle("Studio server URL")
                .setMessage("The Mac's address — e.g. http://100.64.0.10:5174 (Tailscale) "
                        + "or http://192.168.1.10:5174 (same Wi-Fi).")
                .setView(input)
                .setCancelable(false)
                .setPositiveButton("Connect", (d, w) -> {
                    String u = input.getText().toString().trim();
                    if (!u.isEmpty()) {
                        prefs().edit().putString(KEY_URL, u).apply();
                        web.loadUrl(u);
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
