const byId = (id) => document.getElementById(id);
let csrf = "";
let people = [];

async function api(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || data.message || `Error HTTP ${response.status}`);
  return data;
}

function showStatus(text, error = false) {
  const el = byId("status");
  el.textContent = text;
  el.classList.toggle("error", error);
}

function filteredUsers() {
  const query = byId("user-search").value.trim().toLocaleLowerCase();
  return people.filter((user) => `${user.name} ${user.username} ${user.id}`.toLocaleLowerCase().includes(query));
}

function renderUsers() {
  const selected = byId("user-select").value;
  const visible = filteredUsers();
  const select = byId("user-select");
  select.replaceChildren(new Option(visible.length ? "Elige una cuenta" : "No hay coincidencias", ""));
  for (const user of visible) {
    const option = new Option(`${user.name || user.username || "Usuario"} · ${user.id}${user.premium ? " · Premium" : ""}`, user.id);
    select.add(option);
  }
  if (visible.some((user) => user.id === selected)) select.value = selected;
  const tbody = byId("users");
  tbody.replaceChildren();
  for (const user of visible) {
    const row = document.createElement("tr");
    const values = [user.name || "—", user.username ? `@${user.username}` : "—", user.id, user.premium ? "Activo" : "No activo", user.expires_at == null ? (user.premium ? "Permanente" : "—") : new Date(user.expires_at * 1000).toLocaleString()];
    for (const value of values) { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); }
    tbody.append(row);
  }
  if (!visible.length) { const row = document.createElement("tr"); const cell = document.createElement("td"); cell.colSpan = 5; cell.textContent = people.length ? "No hay coincidencias." : "Aún no hay cuentas registradas."; row.append(cell); tbody.append(row); }
}

async function loadUsers() { const result = await api("/api/admin/users"); people = result.users; renderUsers(); }
async function postAdmin(endpoint, payload) { return api(endpoint, { method: "POST", headers: { "X-CSRF-Token": csrf }, body: JSON.stringify(payload) }); }

async function init() {
  try {
    const me = await api("/api/me");
    if (!me.is_admin) { byId("denied").hidden = false; return; }
    csrf = me.csrf;
    byId("dashboard").hidden = false;
    await loadUsers();
  } catch (_) { byId("login").hidden = false; }
}

byId("key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await postAdmin("/api/admin/keys/generate", { days: Number(byId("key-days").value) });
    byId("generated-key").textContent = result.key;
    byId("key-result").hidden = false;
    showStatus(`Key de ${result.days} días generada. Cópiala y guárdala; no se volverá a mostrar.`);
  } catch (error) { showStatus(error.message, true); }
});

byId("copy-key").addEventListener("click", async () => { try { await navigator.clipboard.writeText(byId("generated-key").textContent); showStatus("Key copiada."); } catch { showStatus("No se pudo copiar; selecciónala y cópiala manualmente.", true); } });
byId("user-search").addEventListener("input", renderUsers);
byId("permanent").addEventListener("change", (event) => { byId("grant-days").disabled = event.target.checked; });
byId("grant-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await postAdmin("/api/admin/grant", { user_id: byId("user-select").value, permanent: byId("permanent").checked, days: Number(byId("grant-days").value) });
    showStatus(result.message); await loadUsers();
  } catch (error) { showStatus(error.message, true); }
});
byId("revoke-user").addEventListener("click", async () => {
  const userId = byId("user-select").value;
  if (!userId) return showStatus("Selecciona primero una cuenta registrada.", true);
  if (!confirm("¿Seguro que quieres quitar el Premium de esta cuenta?")) return;
  try { const result = await postAdmin("/api/admin/revoke", { user_id: userId }); showStatus(result.message); await loadUsers(); }
  catch (error) { showStatus(error.message, true); }
});
byId("revoke-key-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const key = byId("revoke-key").value.trim();
  if (!key) return showStatus("Introduce la key que quieres revocar.", true);
  if (!confirm("Se eliminará esta key y, si ya fue canjeada, se quitará el acceso que concedió. ¿Continuar?")) return;
  try { const result = await postAdmin("/api/admin/keys/revoke", { key }); showStatus(result.message); byId("revoke-key").value = ""; await loadUsers(); }
  catch (error) { showStatus(error.message, true); }
});
byId("refresh").addEventListener("click", () => loadUsers().then(() => showStatus("Lista actualizada.")).catch((error) => showStatus(error.message, true)));
init();
