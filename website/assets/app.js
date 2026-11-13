const $ = (selector) => document.querySelector(selector);
const tabSections = [...document.querySelectorAll("main > section[id]")];
const nav = $("#nav");
const menuToggle = $("#menu-toggle");
const SUPPORT_DISCORD_URL = "https://discord.gg/jet4qeU6X";
let csrfToken = "";

function activateTab(id, { updateHash = true } = {}) {
  const active = tabSections.find((section) => section.id === id) || tabSections[0];
  for (const section of tabSections) {
    const selected = section === active;
    section.hidden = !selected;
    section.classList.toggle("active-tab", selected);
    section.setAttribute("role", "tabpanel");
    section.setAttribute("aria-hidden", String(!selected));
  }
  if (nav) {
    for (const link of nav.querySelectorAll("a[href^='#']")) {
      const selected = link.hash === `#${active.id}`;
      link.classList.toggle("active", selected);
      link.setAttribute("aria-current", selected ? "page" : "false");
    }
    nav.classList.remove("open");
  }
  menuToggle?.setAttribute("aria-expanded", "false");
  if (updateHash && location.hash !== `#${active.id}`) history.replaceState(null, "", `#${active.id}`);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function toast(message) {
  const el = $("#toast");
  if (!el) return;
  el.textContent = message;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 3000);
}

async function api(path, options = {}) {
  try {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...options });
    let data = {};
    try { data = await response.json(); } catch { /* non-JSON response */ }
    return { response, data };
  } catch {
    return { response: { ok: false }, data: {} };
  }
}

function configureInvite(config) {
  const select = $("#guild-select");
  const button = $("#invite-button");
  if (!button) return;
  button.href = config.invite_url || `https://discord.com/oauth2/authorize?client_id=${encodeURIComponent(config.bot_client_id || "")}&scope=bot%20applications.commands&permissions=8`;
  button.target = "_blank";
  button.rel = "noopener";
  select?.addEventListener("change", () => {
    const url = new URL(button.href);
    if (select.value) {
      url.searchParams.set("guild_id", select.value);
      url.searchParams.set("disable_guild_select", "true");
    } else {
      url.searchParams.delete("guild_id");
      url.searchParams.delete("disable_guild_select");
    }
    button.href = url.toString();
  });
}

function setupPremiumKeyClaim() {
  const premiumCard = $(".premium-plan");
  if (!premiumCard) return;

  // Keep the existing contact/consult button and point it to the requested Discord.
  const consultButton = premiumCard.querySelector("a.button");
  if (consultButton) {
    consultButton.href = SUPPORT_DISCORD_URL;
    consultButton.target = "_blank";
    consultButton.rel = "noopener noreferrer";
    consultButton.textContent = "Consultar Premium en Discord ↗";
  }

  if (premiumCard.querySelector("#premium-key-form")) return;
  const claim = document.createElement("div");
  claim.className = "redeem";
  claim.innerHTML = '<label for="premium-key-input">¿Ya tienes una key Premium? Reclámala aquí</label><form id="premium-key-form" class="redeem-row"><input id="premium-key-input" type="text" placeholder="VANT-…" autocomplete="off" maxlength="160" required><button class="button button-small" type="submit">Reclamar key</button></form><p id="premium-key-message" role="status" aria-live="polite"></p>';
  premiumCard.append(claim);

  claim.querySelector("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = $("#premium-key-input");
    const button = claim.querySelector("button");
    const status = $("#premium-key-message");
    const key = input.value.trim();
    if (!key) return;
    if (!csrfToken) {
      status.textContent = "Inicia sesión con Discord para reclamar tu key.";
      return;
    }
    button.disabled = true;
    status.textContent = "Validando la key…";
    const { response, data } = await api("/api/redeem", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrfToken },
      body: JSON.stringify({ key }),
    });
    button.disabled = false;
    status.textContent = data.message || data.error || (response.ok ? "¡Premium activado!" : "No se pudo reclamar la key.");
    if (response.ok) {
      input.value = "";
      toast("¡Premium activado en tu cuenta!");
      const profileStatus = $("#profile-status");
      if (profileStatus) profileStatus.textContent = "Premium activo";
    }
  });
}

async function boot() {
  activateTab(location.hash.slice(1), { updateHash: false });
  nav?.addEventListener("click", (event) => {
    const link = event.target.closest("a[href^='#']");
    if (!link) return;
    event.preventDefault();
    activateTab(link.hash.slice(1));
  });
  document.querySelectorAll("a[href^='#']").forEach((link) => {
    if (nav?.contains(link)) return;
    link.addEventListener("click", (event) => {
      event.preventDefault();
      activateTab(link.hash.slice(1));
    });
  });
  menuToggle?.addEventListener("click", () => {
    const open = nav.classList.toggle("open");
    menuToggle.setAttribute("aria-expanded", String(open));
  });

  const configResult = await api("/config.json");
  configureInvite(configResult.data || {});
  setupPremiumKeyClaim();

  const stats = await api("/api/stats");
  if (stats.response.ok) {
    const servers = $("#server-count");
    const users = $("#web-count");
    if (servers) servers.textContent = Number(stats.data.servers || 0).toLocaleString("es");
    if (users) users.textContent = Number(stats.data.website_users || 0).toLocaleString("es");
  }

  const me = await api("/api/me");
  if (!me.response.ok || !me.data.authenticated) return;
  csrfToken = me.data.csrf || "";
  const user = me.data.user || {};
  const profileName = $("#profile-name");
  const profileStatus = $("#profile-status");
  if (profileName) profileName.textContent = user.name || user.username || "Cuenta de Discord";
  if (profileStatus) profileStatus.textContent = `${user.username ? `@${user.username} · ` : ""}${me.data.premium ? "Premium activo" : "Plan Free"}`;
  const avatar = $(".avatar");
  if (avatar && user.avatar) {
    const image = document.createElement("img");
    image.src = user.avatar;
    image.alt = "Avatar de Discord";
    image.className = "avatar";
    avatar.replaceWith(image);
  }
  const login = $("#profile-login");
  if (login) login.hidden = true;
  const accountActions = $("#account-actions");
  if (accountActions) accountActions.innerHTML = '<a class="button secondary button-small" href="/auth/logout">Cerrar sesión</a>';
  const adminLink = $("#admin-link");
  if (adminLink && me.data.is_admin) adminLink.hidden = false;

  const guilds = await api("/api/guilds");
  const select = $("#guild-select");
  if (select && guilds.response.ok) {
    select.replaceChildren(new Option("Elige un servidor (opcional)", ""), ...guilds.data.guilds.map((guild) => new Option(guild.name, guild.id)));
  }
}

boot();
