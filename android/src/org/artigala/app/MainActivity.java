package org.artigala.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.view.inputmethod.EditorInfo;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.TextView;

/**
 * Arti Gala for Android: shows the Arti Gala dashboard from a server on your
 * computer or network. The first screen asks for the server address.
 */
public class MainActivity extends Activity {
    private static final String PREFS = "arti_gala";
    private static final String KEY_SERVER = "server_url";
    private static final int MENU_RELOAD = 1;
    private static final int MENU_SERVER = 2;

    private WebView web;
    private ScrollView setup;
    private EditText serverInput;
    private TextView setupError;
    private ProgressBar progress;
    private String serverUrl;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        FrameLayout root = new FrameLayout(this);

        web = new WebView(this);
        configureWebView();
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        setup = buildSetupScreen();
        root.addView(setup, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        progress = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progress.setMax(100);
        progress.setVisibility(View.GONE);
        root.addView(progress, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(4), Gravity.TOP));

        setContentView(root);

        serverUrl = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_SERVER, null);
        if (serverUrl == null) {
            showSetup(null);
        } else if (savedInstanceState != null && web.restoreState(savedInstanceState) != null) {
            showWeb();
        } else {
            open(serverUrl);
        }
    }

    // ------------------------------------------------------------------ WebView

    private void configureWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setBuiltInZoomControls(true);
        s.setDisplayZoomControls(false);
        s.setMediaPlaybackRequiresUserGesture(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return openExternallyIfForeign(request.getUrl());
            }

            @SuppressWarnings("deprecation")
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return openExternallyIfForeign(Uri.parse(url));
            }

            @Override
            public void onPageStarted(WebView view, String url, Bitmap favicon) {
                progress.setVisibility(View.VISIBLE);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                progress.setVisibility(View.GONE);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                if (Build.VERSION.SDK_INT >= 23 && request.isForMainFrame()) {
                    connectionFailed(String.valueOf(error.getDescription()));
                }
            }

            @SuppressWarnings("deprecation")
            @Override
            public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
                if (Build.VERSION.SDK_INT < 23) {
                    connectionFailed(description);
                }
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public void onProgressChanged(WebView view, int newProgress) {
                progress.setProgress(newProgress);
            }
        });
    }

    /** Links to museum records etc. open in the browser; the dashboard stays in the app. */
    private boolean openExternallyIfForeign(Uri uri) {
        Uri server = serverUrl == null ? null : Uri.parse(serverUrl);
        boolean sameServer = server != null
                && eq(uri.getHost(), server.getHost())
                && uri.getPort() == server.getPort()
                && eq(uri.getScheme(), server.getScheme());
        if (sameServer) {
            return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException ignored) {
            // nothing can open it; stay put
        }
        return true;
    }

    private void connectionFailed(String detail) {
        progress.setVisibility(View.GONE);
        showSetup("Could not reach " + serverUrl + " (" + detail + ").\n\n"
                + "Check that the Arti Gala server is running with --host 0.0.0.0 and that the phone "
                + "is on the same Wi-Fi as the computer.");
    }

    private void open(String url) {
        showWeb();
        web.loadUrl(url);
    }

    // ------------------------------------------------------------------ setup screen

    private ScrollView buildSetupScreen() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(24), dp(32), dp(24), dp(24));

        TextView title = new TextView(this);
        title.setText("Arti Gala");
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 28);
        title.setTextColor(Color.parseColor("#9A4A1C"));
        box.addView(title);

        box.addView(paragraph("Sub-Saharan African artifacts: where they are, where they have been, "
                + "what they sold for, and the cases around them.", 15, dp(4)));

        box.addView(paragraph("Server address", 14, dp(24)));
        serverInput = new EditText(this);
        serverInput.setHint("http://192.168.1.20:8000");
        serverInput.setSingleLine(true);
        serverInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        serverInput.setImeOptions(EditorInfo.IME_ACTION_GO);
        serverInput.setOnEditorActionListener(new TextView.OnEditorActionListener() {
            @Override
            public boolean onEditorAction(TextView v, int actionId, KeyEvent event) {
                connect();
                return true;
            }
        });
        box.addView(serverInput);

        setupError = paragraph("", 14, dp(8));
        setupError.setTextColor(Color.parseColor("#C62828"));
        setupError.setVisibility(View.GONE);
        box.addView(setupError);

        Button connect = new Button(this);
        connect.setText("Connect");
        connect.setOnClickListener(new View.OnClickListener() {
            @Override
            public void onClick(View v) {
                connect();
            }
        });
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(12);
        box.addView(connect, lp);

        box.addView(paragraph("How to start the server", 16, dp(32)));
        box.addView(paragraph(
                "1. On your computer, unzip Arti Gala and start it so other devices can reach it:\n"
                + "     Windows:  run.bat --host 0.0.0.0\n"
                + "     Mac/Linux:  ./run.sh --host 0.0.0.0\n\n"
                + "2. The server prints the address to use, e.g. http://192.168.1.20:8000. Type it above.\n\n"
                + "3. The phone and the computer must be on the same Wi-Fi. If Windows asks, allow "
                + "Python through the firewall on private networks.\n\n"
                + "If the server is hosted online, enter its https:// address instead.", 14, dp(8)));

        ScrollView scroll = new ScrollView(this);
        scroll.setFillViewport(true);
        TypedValue bg = new TypedValue();
        if (getTheme().resolveAttribute(android.R.attr.colorBackground, bg, true)) {
            scroll.setBackgroundColor(bg.data);
        }
        scroll.addView(box);
        return scroll;
    }

    private TextView paragraph(String text, int sp, int topMargin) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        tv.setLineSpacing(0, 1.15f);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.topMargin = topMargin;
        tv.setLayoutParams(lp);
        return tv;
    }

    private void connect() {
        String url = normalize(serverInput.getText().toString());
        if (url == null) {
            setupError.setText("Enter an address like http://192.168.1.20:8000");
            setupError.setVisibility(View.VISIBLE);
            return;
        }
        serverUrl = url;
        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString(KEY_SERVER, url).apply();
        web.clearHistory();
        open(url);
    }

    /** Accepts "192.168.1.20:8000", "http://host:8000/" etc.; returns null if unusable. */
    static String normalize(String raw) {
        String s = raw == null ? "" : raw.trim();
        if (s.isEmpty()) {
            return null;
        }
        if (!s.matches("(?i)^https?://.*")) {
            s = "http://" + s;
        }
        while (s.endsWith("/")) {
            s = s.substring(0, s.length() - 1);
        }
        Uri uri = Uri.parse(s);
        if (uri.getHost() == null || uri.getHost().isEmpty()) {
            return null;
        }
        return s + "/";
    }

    private void showSetup(String error) {
        if (serverUrl != null && serverInput.getText().length() == 0) {
            serverInput.setText(serverUrl);
        }
        if (error == null) {
            setupError.setVisibility(View.GONE);
        } else {
            setupError.setText(error);
            setupError.setVisibility(View.VISIBLE);
        }
        setup.setVisibility(View.VISIBLE);
        web.setVisibility(View.INVISIBLE);
    }

    private void showWeb() {
        setup.setVisibility(View.GONE);
        web.setVisibility(View.VISIBLE);
    }

    // ------------------------------------------------------------------ menu / lifecycle

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, MENU_RELOAD, 0, "Reload");
        menu.add(0, MENU_SERVER, 1, "Change server");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == MENU_RELOAD) {
            if (serverUrl == null) {
                showSetup(null);
            } else if (setup.getVisibility() == View.VISIBLE) {
                open(serverUrl);
            } else {
                web.reload();
            }
            return true;
        }
        if (item.getItemId() == MENU_SERVER) {
            showSetup(null);
            return true;
        }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onBackPressed() {
        if (setup.getVisibility() == View.VISIBLE && serverUrl != null && web.getUrl() != null) {
            showWeb();
        } else if (setup.getVisibility() != View.VISIBLE && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onDestroy() {
        web.destroy();
        super.onDestroy();
    }

    private int dp(int value) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, value, getResources().getDisplayMetrics()));
    }

    private static boolean eq(String a, String b) {
        return a == null ? b == null : a.equalsIgnoreCase(b);
    }
}
