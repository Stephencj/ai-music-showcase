package com.aimusic;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.Menu;
import android.view.MenuItem;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;

/**
 * Minimal WebView wrapper for the AI Music Studio React app. Loads a server
 * URL (the Mac's LAN/Tailscale address, e.g. http://192.168.1.10:5174) and
 * keeps it in SharedPreferences. First launch prompts for the URL (prefilled
 * with the default); the overflow menu lets you change it or reload. No
 * cloudflare, no extra dependencies — pure framework WebView.
 */
public class MainActivity extends Activity {

    private static final String DEFAULT_URL = "http://100.64.0.10:5174";
    private static final String PREFS = "aimusic";
    private static final String KEY_URL = "server_url";

    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);                 // PWA localStorage (apiBase etc.)
        s.setMediaPlaybackRequiresUserGesture(false); // let vocal/audio previews play
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        web.setWebViewClient(new WebViewClient());     // keep navigation inside the app
        web.setWebChromeClient(new WebChromeClient());
        setContentView(web);

        String url = prefs().getString(KEY_URL, "");
        if (url.isEmpty()) {
            promptForUrl();
        } else {
            web.loadUrl(url);
        }
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
