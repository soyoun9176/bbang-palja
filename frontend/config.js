// Public API address only. Never add passwords or DB credentials here.
window.KAMBO_CONFIG = {
  "apiBase": "https://gore-descending-purse-universe.trycloudflare.com",
  "prototype": true
};
if (['localhost', '127.0.0.1', '::1', '[::1]'].includes(window.location.hostname)) {
  window.KAMBO_CONFIG.apiBase = '';
}
