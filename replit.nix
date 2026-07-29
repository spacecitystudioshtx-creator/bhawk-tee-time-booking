{ pkgs }: {
  deps = [
    # System Chromium — main.py auto-detects it via `which chromium`,
    # avoiding Playwright's bundled-browser download (which fails on Replit
    # due to missing system libraries).
    pkgs.chromium
  ];
}
