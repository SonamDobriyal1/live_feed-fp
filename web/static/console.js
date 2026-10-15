(() => {
  const body = document.body;
  const tz = body.dataset.tz || "Asia/Kolkata";

  const passwordToggle = document.querySelector("[data-toggle-password]");
  if (passwordToggle) {
    passwordToggle.addEventListener("click", () => {
      const input = document.getElementById(passwordToggle.getAttribute("aria-controls"));
      if (!input) return;
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      passwordToggle.textContent = show ? "Hide" : "Show";
      passwordToggle.setAttribute("aria-pressed", show ? "true" : "false");
    });
  }

  const clock = document.getElementById("clock");
  if (clock) {
    const paint = () => {
      clock.textContent = new Intl.DateTimeFormat("en-GB", {
        timeZone: tz,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hourCycle: "h23",
      }).format(new Date());
    };
    paint();
    window.setInterval(paint, 1000);
  }

  const eventLabel = (raw) =>
    String(raw || "").toLowerCase() === "violence" ? "Safety incident" : raw;

  const formatStamp = (iso) => {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: tz,
      day: "2-digit",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    }).format(date);
  };

  const ago = (iso) => {
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    const seconds = Math.max(0, (Date.now() - date.getTime()) / 1000);
    if (seconds < 45) return "Just now";
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
    return `${Math.floor(seconds / 86400)}d ago`;
  };

  document.querySelectorAll(".stamp").forEach((node) => {
    const iso = node.getAttribute("datetime") || node.dataset.time;
    if (iso) node.textContent = formatStamp(iso);
  });
  document.querySelectorAll(".ago").forEach((node) => {
    if (node.dataset.time) node.textContent = ago(node.dataset.time);
  });

  document.querySelectorAll(".toast").forEach((toast) => {
    const close = () => toast.remove();
    toast.querySelector("[data-dismiss]")?.addEventListener("click", close);
    window.setTimeout(close, 5200);
  });

  const showToast = (message, kind = "ok") => {
    const host = document.getElementById("toasts");
    if (!host) return;
    const toast = document.createElement("div");
    toast.className = `toast ${kind}`;
    toast.setAttribute("role", "status");
    toast.innerHTML = `<span></span><button type="button" data-dismiss aria-label="Dismiss">×</button>`;
    toast.querySelector("span").textContent = message;
    toast.querySelector("[data-dismiss]").addEventListener("click", () => toast.remove());
    host.appendChild(toast);
    window.setTimeout(() => toast.remove(), 5200);
  };

  const urlBase64ToUint8Array = (value) => {
    const padding = "=".repeat((4 - (value.length % 4)) % 4);
    const base64 = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const output = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) output[i] = raw.charCodeAt(i);
    return output;
  };

  const initPushAlerts = async () => {
    const button = document.getElementById("push-toggle");
    if (!button) return;

    const setState = (mode, label) => {
      button.hidden = false;
      button.disabled = mode === "unsupported" || mode === "blocked";
      button.textContent = label;
      button.classList.toggle("is-on", mode === "on");
      button.classList.toggle("is-blocked", mode === "blocked" || mode === "unsupported");
      button.setAttribute("aria-pressed", mode === "on" ? "true" : "false");
    };

    if (!window.isSecureContext) {
      setState("unsupported", "Alerts need HTTPS");
      button.title = "Open this site on https:// or http://127.0.0.1 to enable push alerts.";
      return;
    }
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
      setState("unsupported", "Alerts unavailable");
      button.title = "This browser does not support web push notifications.";
      return;
    }

    let registration;
    try {
      registration = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
    } catch (error) {
      setState("unsupported", "Alerts unavailable");
      button.title = String(error);
      return;
    }

    const currentSubscription = () => registration.pushManager.getSubscription();

    const refreshLabel = async () => {
      if (Notification.permission === "denied") {
        setState("blocked", "Alerts blocked");
        button.title = "Allow notifications for this site in the browser settings, then reload.";
        return;
      }
      const sub = await currentSubscription();
      if (sub && Notification.permission === "granted") {
        setState("on", "Alerts on");
        button.title = "Click to turn off incident push notifications.";
      } else {
        setState("off", "Enable alerts");
        button.title = "Get a push notification when a safety incident is detected.";
      }
    };

    const subscribe = async () => {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        await refreshLabel();
        showToast("Notifications were not allowed. Enable them in the browser if you want alerts.", "error");
        return;
      }
      const config = await fetch("/api/push/config", { headers: { Accept: "application/json" } });
      if (!config.ok) throw new Error("Could not load push keys");
      const { publicKey } = await config.json();
      const subscription = await registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(publicKey),
      });
      const saved = await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify(subscription.toJSON()),
      });
      if (!saved.ok) throw new Error("Could not save this browser for alerts");
      await refreshLabel();
      showToast("Alerts are on. You will be notified of unusual or safety incidents.");
      fetch("/api/push/test", { method: "POST", headers: { Accept: "application/json" } }).catch(() => {});
    };

    const unsubscribe = async () => {
      const subscription = await currentSubscription();
      if (subscription) {
        await fetch("/api/push/unsubscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify({ endpoint: subscription.endpoint }),
        });
        await subscription.unsubscribe();
      }
      await refreshLabel();
      showToast("Push alerts are off for this browser.");
    };

    button.addEventListener("click", async () => {
      try {
        const subscription = await currentSubscription();
        if (subscription && Notification.permission === "granted") await unsubscribe();
        else await subscribe();
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Could not update alerts.", "error");
      }
    });

    try {
      const existing = await currentSubscription();
      if (existing && Notification.permission === "granted") {
        await fetch("/api/push/subscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: JSON.stringify(existing.toJSON()),
        });
      }
    } catch {
      /* Keep the current label if the sync fails. */
    }
    await refreshLabel();
  };

  initPushAlerts();

  const workspace = document.getElementById("workspace");
  if (!workspace) return;

  const panels = {
    queue: document.getElementById("panel-queue"),
    archive: document.getElementById("panel-archive"),
  };
  const tabs = [...document.querySelectorAll("[data-tab]")];
  const search = document.getElementById("search");
  const severity = document.getElementById("severity");
  const sort = document.getElementById("sort");
  const inspector = document.getElementById("inspector");
  const lightbox = document.getElementById("lightbox");
  const confirmBox = document.getElementById("confirm");
  let activeTab = "queue";
  let selected = null;
  let pendingForm = null;

  const visibleCards = () =>
    [...(panels[activeTab]?.querySelectorAll(".event") || [])].filter((card) => !card.hidden);

  const setTab = (name) => {
    if (!panels[name]) return;
    activeTab = name;
    sessionStorage.setItem("console.tab", name);
    tabs.forEach((tab) => {
      const on = tab.dataset.tab === name;
      tab.classList.toggle("is-active", on);
      tab.setAttribute("aria-selected", on ? "true" : "false");
    });
    Object.entries(panels).forEach(([key, panel]) => {
      const on = key === name;
      panel.hidden = !on;
      panel.classList.toggle("is-active", on);
    });
    applyFilters();
    if (selected && !panels[name].contains(selected)) closeInspector();
  };

  const setView = (mode) => {
    localStorage.setItem("console.view", mode);
    document.querySelectorAll("[data-view]").forEach((button) => {
      const on = button.dataset.view === mode;
      button.classList.toggle("is-active", on);
      button.setAttribute("aria-pressed", on ? "true" : "false");
    });
    document.querySelectorAll(".board").forEach((board) => {
      board.classList.toggle("list", mode === "list");
    });
  };

  const sortBoard = (panel) => {
    const board = panel.querySelector(".board");
    if (!board) return;
    const cards = [...board.querySelectorAll(".event")];
    const mode = sort.value;
    cards.sort((a, b) => {
      if (mode === "confidence") {
        return Number(b.dataset.confidence) - Number(a.dataset.confidence);
      }
      return String(b.dataset.time).localeCompare(String(a.dataset.time));
    });
    cards.forEach((card) => board.appendChild(card));
  };

  const applyFilters = () => {
    const query = search.value.trim().toLowerCase();
    const level = severity.value;
    const panel = panels[activeTab];
    if (!panel) return;
    sortBoard(panel);
    const cards = [...panel.querySelectorAll(".event")];
    let shown = 0;
    cards.forEach((card) => {
      const hay = card.textContent.toLowerCase();
      const match = (!query || hay.includes(query)) && (level === "all" || card.dataset.severity === level);
      card.hidden = !match;
      if (match) shown += 1;
    });
    const empty = panel.querySelector(".filter-empty");
    if (empty) empty.hidden = shown !== 0 || cards.length === 0;
    if (selected && selected.hidden) closeInspector();
  };

  const fillInspector = (card) => {
    selected = card;
    document.querySelectorAll(".event.is-selected").forEach((node) => node.classList.remove("is-selected"));
    card.classList.add("is-selected");
    card.scrollIntoView({ block: "nearest" });
    inspector.hidden = false;
    workspace.classList.add("inspecting");

    const pct = Math.floor(Number(card.dataset.confidence) * 100);
    const saved = card.dataset.saved === "1";
    const sev = inspector.querySelector("#inspector-sev");
    sev.textContent = card.dataset.severity;
    sev.className = `pill ${card.dataset.severity}`;
    inspector.querySelector("#inspector-ch").textContent = `CH ${card.dataset.channel}`;
    inspector.querySelector("#inspector-title").textContent = `${pct}% ${eventLabel(card.dataset.label)}`;
    inspector.querySelector("#inspector-meter").style.width = `${pct}%`;
    inspector.querySelector("#inspector-time").textContent = formatStamp(card.dataset.time);
    inspector.querySelector("#inspector-status").textContent = saved ? "Retained in archive" : "In the review queue";

    const img = inspector.querySelector("#inspector-img");
    const blank = inspector.querySelector("#inspector-empty");
    if (card.dataset.url) {
      img.src = card.dataset.url;
      img.alt = `${eventLabel(card.dataset.label)} frame`;
      img.hidden = false;
      blank.hidden = true;
    } else {
      img.removeAttribute("src");
      img.hidden = true;
      blank.hidden = false;
    }

    inspector.querySelector("#inspector-expand").hidden = !card.dataset.url;
    const saveForm = inspector.querySelector("#inspect-save");
    const unsaveForm = inspector.querySelector("#inspect-unsave");
    saveForm.hidden = saved;
    unsaveForm.hidden = !saved;
    saveForm.action = card.dataset.saveUrl;
    unsaveForm.action = card.dataset.unsaveUrl;
    inspector.querySelector("#inspect-delete").action = card.dataset.deleteUrl;
  };

  const closeInspector = () => {
    selected = null;
    inspector.hidden = true;
    workspace.classList.remove("inspecting");
    document.querySelectorAll(".event.is-selected").forEach((node) => node.classList.remove("is-selected"));
  };

  const openLightbox = (card) => {
    if (!card?.dataset.url) return;
    const pct = Math.floor(Number(card.dataset.confidence) * 100);
    const img = document.getElementById("lightbox-img");
    img.src = card.dataset.url;
    img.alt = `${eventLabel(card.dataset.label)} frame`;
    document.getElementById("lightbox-caption").textContent =
      `${pct}% ${eventLabel(card.dataset.label)} · CH ${card.dataset.channel} · ${formatStamp(card.dataset.time)}`;
    lightbox.hidden = false;
  };

  const closeLightbox = () => {
    lightbox.hidden = true;
  };

  const closeConfirm = () => {
    confirmBox.hidden = true;
    pendingForm = null;
  };

  const openConfirm = (message, form) => {
    pendingForm = form;
    document.getElementById("confirm-copy").textContent = message;
    confirmBox.hidden = false;
    document.getElementById("confirm-ok").focus();
  };

  document.querySelectorAll("[data-tab]").forEach((tab) => {
    tab.addEventListener("click", () => setTab(tab.dataset.tab));
  });
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.view));
  });
  search.addEventListener("input", applyFilters);
  severity.addEventListener("change", applyFilters);
  sort.addEventListener("change", () => {
    localStorage.setItem("console.sort", sort.value);
    applyFilters();
  });

  workspace.addEventListener("click", (event) => {
    const expand = event.target.closest("[data-expand]");
    const card = event.target.closest(".event");
    if (expand && card) {
      openLightbox(card);
      return;
    }
    if (!card || event.target.closest("button, a, form, input, select")) return;
    fillInspector(card);
  });

  workspace.addEventListener("keydown", (event) => {
    const card = event.target.closest(".event");
    if (!card) return;
    if (event.key === "Enter") {
      event.preventDefault();
      fillInspector(card);
    }
  });

  document.getElementById("inspector-close").addEventListener("click", closeInspector);
  document.getElementById("inspector-expand").addEventListener("click", () => openLightbox(selected));
  document.querySelector(".lightbox-close").addEventListener("click", closeLightbox);
  lightbox.addEventListener("click", (event) => {
    if (event.target === lightbox) closeLightbox();
  });
  document.getElementById("confirm-cancel").addEventListener("click", closeConfirm);
  confirmBox.addEventListener("click", (event) => {
    if (event.target === confirmBox) closeConfirm();
  });
  document.getElementById("confirm-ok").addEventListener("click", () => {
    if (!pendingForm) return;
    pendingForm.dataset.confirmed = "1";
    pendingForm.submit();
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmed === "1") return;
    event.preventDefault();
    openConfirm(form.dataset.confirm, form);
  });

  document.addEventListener("keydown", (event) => {
    const typing = event.target.matches("input, textarea, select");
    if (event.key === "Escape") {
      if (!lightbox.hidden) closeLightbox();
      else if (!confirmBox.hidden) closeConfirm();
      else if (!inspector.hidden) closeInspector();
      else if (typing) event.target.blur();
      return;
    }
    if (typing) return;
    if (event.key === "/") {
      event.preventDefault();
      search.focus();
    } else if (event.key === "1") setTab("queue");
    else if (event.key === "2") setTab("archive");
    else if (event.key === "ArrowRight" || event.key === "ArrowDown" || event.key === "ArrowLeft" || event.key === "ArrowUp") {
      const cards = visibleCards();
      if (!cards.length) return;
      event.preventDefault();
      const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
      const current = cards.indexOf(selected);
      const index = current === -1 ? (step > 0 ? -1 : 0) : current;
      const next = cards[(index + step + cards.length) % cards.length];
      fillInspector(next);
      next.focus({ preventScroll: true });
    }
  });

  const storedView = localStorage.getItem("console.view") || "grid";
  const storedSort = localStorage.getItem("console.sort") || "newest";
  sort.value = storedSort;
  setView(storedView);

  const pending = Number(body.dataset.pending || 0);
  const savedCount = Number(body.dataset.saved || 0);
  const storedTab = sessionStorage.getItem("console.tab");
  if (storedTab === "queue" || storedTab === "archive") setTab(storedTab);
  else if (pending === 0 && savedCount > 0) setTab("archive");
  else applyFilters();

  const refreshBar = document.getElementById("refresh-bar");
  document.getElementById("refresh-now")?.addEventListener("click", () => window.location.reload());
  const signature = `${body.dataset.pending}:${body.dataset.saved}:${body.dataset.latest}`;
  window.setInterval(async () => {
    if (!refreshBar.hidden) return;
    try {
      const response = await fetch("/api/board", { headers: { Accept: "application/json" } });
      if (!response.ok) return;
      const data = await response.json();
      const next = `${data.pending}:${data.saved}:${data.latest_id ?? ""}`;
      if (next !== signature) refreshBar.hidden = false;
    } catch {
      /* The console keeps the current view if the check fails. */
    }
  }, 20000);
})();
