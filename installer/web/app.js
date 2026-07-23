// CraftBot installer — front-end glue.
//
// Responsibilities:
//   1. Wait for the pywebview JS bridge to be ready.
//   2. Wire up button click handlers that call into Python (window.pywebview.api).
//   3. Poll get_state() every second to drive button enable/disable + status pill.
//   4. Receive log lines from Python via window.appendLog(text) and append to
//      the output panel.
//   5. Receive progress events (py:progress) and update the progress bar.
//
// State machine (mirrors api.py's get_state() return values):
//
//   not_installed       → Install enabled, others disabled
//   installed_stopped   → Start/Repair/Uninstall enabled
//   installed_running   → Stop/Repair/Uninstall enabled
//   running_uninstalled → Stop + Install enabled (rare edge case)

(function () {
  "use strict";

  // ── DOM references ──────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);
  const els = {
    output: $("output"),
    statusDot: $("status-dot"),
    statusText: $("status-text"),
    progressSection: $("progress-section"),
    progressLabel: $("progress-label"),
    progressFill: $("progress-fill"),
    btnInstall: $("btn-install"),
    btnStart: $("btn-start"),
    btnStop: $("btn-stop"),
    btnRepair: $("btn-repair"),
    btnUninstall: $("btn-uninstall"),
    btnViewLog: $("btn-view-log"),
    btnOpenBrowser: $("btn-open-browser"),
    chkAutostart: $("chk-autostart"),
  };

  // ── Output panel: append helper ─────────────────────────────────────────
  // Exposed on window so Python's evaluate_js() can call it.

  window.appendLog = function (text) {
    if (!text) return;
    const node = document.createTextNode(text);
    els.output.appendChild(node);
    // Auto-scroll to bottom unless the user scrolled up (preserves their
    // position if they're reading earlier output).
    const distanceFromBottom =
      els.output.scrollHeight - els.output.scrollTop - els.output.clientHeight;
    if (distanceFromBottom < 60) {
      els.output.scrollTop = els.output.scrollHeight;
    }
  };

  // ── Bridge readiness ────────────────────────────────────────────────────
  // pywebview injects window.pywebview.api asynchronously. Wait for it.

  function whenBridgeReady(callback) {
    if (window.pywebview && window.pywebview.api) {
      callback();
      return;
    }
    window.addEventListener("pywebviewready", callback, { once: true });
    // Belt-and-suspenders: poll for up to 5s in case the event already fired
    // before this script ran.
    let waited = 0;
    const tick = () => {
      if (window.pywebview && window.pywebview.api) {
        callback();
      } else if (waited < 5000) {
        waited += 100;
        setTimeout(tick, 100);
      }
    };
    setTimeout(tick, 100);
  }

  // ── State polling ───────────────────────────────────────────────────────

  let lastState = null;
  let workerBusy = false;
  let autostartBusy = false;

  async function pollState() {
    try {
      const s = await window.pywebview.api.get_state();
      applyState(s);
    } catch (e) {
      // Window closing or bridge gone — silently stop.
    }
  }

  function applyState(s) {
    workerBusy = !!s.worker_busy;
    lastState = s.state;

    // Status pill
    els.statusDot.classList.remove("is-running", "is-stopped");
    if (s.state === "installed_running" || s.state === "running_uninstalled") {
      els.statusDot.classList.add("is-running");
      els.statusText.textContent =
        s.pid != null ? `Running · PID ${s.pid}` : "Running";
    } else if (s.state === "installed_stopped") {
      els.statusDot.classList.add("is-stopped");
      els.statusText.textContent = "Installed · stopped";
    } else {
      els.statusText.textContent = "Not installed";
    }

    // Button enable/disable per state, all gated by workerBusy.
    const flags = {
      install: false,
      start: false,
      stop: false,
      repair: false,
      uninstall: false,
    };
    if (s.state === "not_installed") {
      flags.install = true;
    } else if (s.state === "installed_stopped") {
      flags.start = true;
      flags.repair = true;
      flags.uninstall = true;
    } else if (s.state === "installed_running") {
      flags.stop = true;
      flags.repair = true;
      flags.uninstall = true;
    } else if (s.state === "running_uninstalled") {
      flags.stop = true;
      flags.install = true;
    }

    setEnabled(els.btnInstall, flags.install && !workerBusy);
    setEnabled(els.btnStart, flags.start && !workerBusy);
    setEnabled(els.btnStop, flags.stop && !workerBusy);
    setEnabled(els.btnRepair, flags.repair && !workerBusy);
    setEnabled(els.btnUninstall, flags.uninstall && !workerBusy);

    // Launch-on-startup only applies once CraftBot is installed.
    const installed =
      s.state === "installed_running" || s.state === "installed_stopped";
    els.chkAutostart.disabled = !installed || workerBusy || autostartBusy;
  }

  // ── Launch-on-startup toggle ────────────────────────────────────────────

  async function refreshAutostart() {
    try {
      const on = await window.pywebview.api.get_autostart_enabled();
      els.chkAutostart.checked = !!on;
    } catch (e) {
      // Bridge gone — leave the checkbox as-is.
    }
  }

  async function onAutostartToggle() {
    const wanted = els.chkAutostart.checked;
    autostartBusy = true;
    els.chkAutostart.disabled = true;
    window.appendLog(
      `\nLaunch on startup: ${wanted ? "enabling" : "disabling"}…\n`
    );
    try {
      const res = await window.pywebview.api.set_autostart(wanted);
      // Re-sync to the actual OS state — the change may have failed.
      els.chkAutostart.checked = !!(res && res.enabled);
      if (res && res.ok) {
        window.appendLog(
          `Launch on startup is now ${res.enabled ? "ON" : "OFF"}.\n`
        );
      } else {
        window.appendLog(
          `Could not change launch-on-startup${
            res && res.error ? ": " + res.error : ""
          }.\n`
        );
      }
    } catch (e) {
      window.appendLog(`\n[autostart] bridge error: ${e}\n`);
      await refreshAutostart();
    } finally {
      autostartBusy = false;
      pollState();
    }
  }

  function setEnabled(btn, on) {
    btn.disabled = !on;
  }

  // ── Button handlers ─────────────────────────────────────────────────────

  els.btnInstall.addEventListener("click", async () => {
    if (els.btnInstall.disabled) return;
    // Pop the OS-native folder picker first.
    const targetDir = await window.pywebview.api.pick_install_location();
    if (!targetDir) {
      window.appendLog("\nInstall cancelled (no location chosen).\n");
      return;
    }
    await window.pywebview.api.install(targetDir);
  });

  els.btnStart.addEventListener("click", () => callApi("start"));
  els.btnStop.addEventListener("click", () => callApi("stop"));
  els.btnRepair.addEventListener("click", () => callApi("repair"));
  els.btnUninstall.addEventListener("click", () => callApi("uninstall"));

  els.btnViewLog.addEventListener("click", async () => {
    const text = await window.pywebview.api.view_log();
    window.appendLog("\n━━━ Latest log session ━━━\n" + text + "\n");
  });

  els.btnOpenBrowser.addEventListener("click", () => {
    window.pywebview.api.open_in_browser();
  });

  els.chkAutostart.addEventListener("change", onAutostartToggle);

  async function callApi(name) {
    const btn = document.querySelector(`[data-action="${name}"]`);
    if (btn && btn.disabled) return;
    try {
      await window.pywebview.api[name]();
    } catch (e) {
      window.appendLog(`\n[${name}] bridge error: ${e}\n`);
    }
  }

  // ── Event listeners pushed from Python ──────────────────────────────────

  window.addEventListener("py:progress", (e) => {
    const { read, total } = e.detail || {};
    showProgress(read, total);
  });

  window.addEventListener("py:workerStarted", () => {
    // Force a state refresh so buttons grey out immediately rather than
    // waiting for the next 1s poll.
    pollState();
  });

  window.addEventListener("py:workerDone", () => {
    pollState();
    // Install/uninstall change the auto-start registration — re-sync the
    // toggle to match.
    refreshAutostart();
    // Hide progress bar once the worker finishes — extraction can complete
    // before the download "100%" tick lands.
    setTimeout(hideProgress, 600);
  });

  function showProgress(read, total) {
    els.progressSection.hidden = false;
    if (total) {
      const pct = Math.max(0, Math.min(1, read / total)) * 100;
      els.progressFill.style.width = pct.toFixed(1) + "%";
      const mb = (n) => (n / (1024 * 1024)).toFixed(1);
      els.progressLabel.textContent = `Downloading… ${mb(read)} / ${mb(total)} MB`;
      if (read >= total) {
        setTimeout(hideProgress, 800);
      }
    } else {
      const mb = (read / (1024 * 1024)).toFixed(1);
      els.progressLabel.textContent = `Downloading… ${mb} MB`;
    }
  }

  function hideProgress() {
    els.progressSection.hidden = true;
    els.progressFill.style.width = "0%";
    els.progressLabel.textContent = "";
  }

  // ── Bootstrap ───────────────────────────────────────────────────────────

  whenBridgeReady(() => {
    pollState();
    refreshAutostart();
    setInterval(pollState, 1000);
  });
})();
