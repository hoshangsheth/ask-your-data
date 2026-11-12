/**
 * "How to use" popup: short steps for new users.
 *
 * Opens automatically on the first visit (remembered in localStorage "ayd-help-seen") and any
 * time from the "?" button in the top bar. Esc, the close button or "Got it" dismisses it.
 *
 * Exports: initHelp()
 */

const KEY = "ayd-help-seen";
const $ = (id) => document.getElementById(id);

function seen() {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return true; // storage blocked: don't pop up on every visit
  }
}

function markSeen() {
  try {
    localStorage.setItem(KEY, "1");
  } catch {
    /* ignore */
  }
}

function open() {
  const d = $("help-dialog");
  if (!d.open) d.showModal();
  $("help-ok").focus();
}

function close() {
  markSeen();
  const d = $("help-dialog");
  if (!d.open) return;
  d.classList.add("is-closing");
  window.setTimeout(() => {
    d.classList.remove("is-closing");
    d.close();
  }, 180);
}

export function initHelp() {
  $("help-btn").addEventListener("click", open);
  $("help-ok").addEventListener("click", close);
  $("help-close").addEventListener("click", close);
  $("help-dialog").addEventListener("cancel", (e) => {
    e.preventDefault(); // play the closing animation instead of vanishing
    close();
  });
  $("help-dialog").addEventListener("click", (e) => {
    if (e.target === $("help-dialog")) close(); // click on the backdrop
  });
  if (!seen()) window.setTimeout(open, 600); // let the page settle first
}
