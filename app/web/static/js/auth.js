/**
 * Accounts in the UI: the sidebar account row and the sign-in / sign-up dialog.
 *
 * Everyone can ask about the demo store as a guest. Uploading needs an account (uploads are
 * private), so requireSignIn(reason) opens the dialog and resolves true once signed in.
 *
 * Exports: initAuth(), currentUser(), onAuthChange(fn), requireSignIn(reason)
 */

import { ApiError, getMe, signIn, signOut, signUp } from "./api.js";
import { escapeHtml } from "./format.js";
import { hydrateIcons } from "./icons.js";
import { toast } from "./toast.js";

let me = { signed_in: false, email: "", is_admin: false };
let mode = "signin"; // or "signup"
let pending = null; // resolve() of an open requireSignIn()
const listeners = new Set();
const $ = (id) => document.getElementById(id);

export const currentUser = () => me;
export const onAuthChange = (fn) => listeners.add(fn);

function renderAccount() {
  const el = $("account");
  el.innerHTML = me.signed_in
    ? `<span class="acct-avatar" data-icon="user"></span>
       <span class="acct-text"><span class="acct-email" title="${escapeHtml(me.email)}">${escapeHtml(me.email)}</span>
         <span class="acct-sub">Your uploads are private</span></span>
       <button class="icon-btn acct-out" id="sign-out" title="Sign out" aria-label="Sign out"><span data-icon="logout"></span></button>`
    : `<span class="acct-avatar guest" data-icon="user"></span>
       <span class="acct-text"><span class="acct-email">Guest</span><span class="acct-sub">Sign in to upload your data</span></span>
       <button class="btn btn-small" id="sign-in">Sign in</button>`;
  hydrateIcons(el);
}

function setMe(next, { animate = false } = {}) {
  const changed = next.signed_in !== me.signed_in || next.email !== me.email;
  me = next;
  renderAccount();
  if (animate) {
    const el = $("account");
    el.classList.remove("acct-enter");
    void el.offsetWidth; // restart the animation
    el.classList.add("acct-enter");
  }
  if (changed) listeners.forEach((fn) => fn(me));
}

const wait = (ms) => new Promise((r) => window.setTimeout(r, ms));
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Success moment: the form gives way to a drawn checkmark, then the dialog floats away. */
async function celebrate(signup, email) {
  const form = $("auth-form");
  $("auth-success-title").textContent = signup ? "Account created" : "Welcome back";
  $("auth-success-sub").textContent = signup ? `Signed in as ${email}. Your uploads stay private.` : `Signed in as ${email}`;
  form.classList.add("is-success");
  await wait(reducedMotion() ? 500 : 1350);
  const dialog = $("auth-dialog");
  dialog.classList.add("is-closing");
  await wait(reducedMotion() ? 0 : 190);
  dialog.classList.remove("is-closing");
  form.classList.remove("is-success");
}

function setMode(next, reason = "") {
  // Cross-fade the texts when switching between "sign in" and "create account".
  const form = $("auth-form");
  if (next !== mode && $("auth-dialog").open && !reducedMotion()) {
    form.classList.remove("is-switching");
    void form.offsetWidth;
    form.classList.add("is-switching");
  }
  mode = next;
  const signup = mode === "signup";
  $("auth-title").textContent = signup ? "Create your account" : "Welcome back";
  $("auth-reason").textContent = reason || (signup ? "Keep your uploads private and pick up conversations later." : "Sign in to use your own data.");
  $("auth-submit").textContent = signup ? "Create account" : "Sign in";
  $("auth-password").autocomplete = signup ? "new-password" : "current-password";
  $("auth-switch").innerHTML = signup
    ? `Already have an account? <button type="button" class="link-btn" data-mode="signin">Sign in</button>`
    : `New here? <button type="button" class="link-btn" data-mode="signup">Create an account</button>`;
  $("auth-hint").hidden = !signup;
  $("auth-error").hidden = true;
}

function open(reason = "") {
  // Always start on "Sign in" (the last mode may have been "Create account" from an earlier visit).
  mode = "signin";
  setMode("signin", reason);
  $("auth-error").hidden = true;
  $("auth-dialog").showModal();
  $("auth-email").focus();
}

function close(signedIn) {
  if ($("auth-dialog").open) $("auth-dialog").close();
  pending?.(signedIn);
  pending = null;
}

/** Open the dialog (with an explanation); resolves true if the user signs in. */
export function requireSignIn(reason) {
  if (me.signed_in) return Promise.resolve(true);
  return new Promise((resolve) => {
    pending = resolve;
    open(reason);
  });
}

async function submit(e) {
  e.preventDefault();
  const email = $("auth-email").value.trim();
  const password = $("auth-password").value;
  const btn = $("auth-submit");
  btn.disabled = true;
  $("auth-error").hidden = true;
  try {
    const signup = mode === "signup";
    const next = signup ? await signUp(email, password) : await signIn(email, password);
    $("auth-password").value = "";
    await celebrate(signup, next.email);
    close(true);
    setMe(next, { animate: true }); // after the dialog: the account row animates in
  } catch (err) {
    $("auth-error").textContent = err instanceof ApiError ? err.message.replace(/^./, (c) => c.toUpperCase()) : "Something went wrong";
    $("auth-error").hidden = false;
  } finally {
    btn.disabled = false;
  }
}

export async function initAuth() {
  $("account").addEventListener("click", async (e) => {
    if (e.target.closest("#sign-in")) open();
    if (e.target.closest("#sign-out")) {
      try {
        setMe(await signOut(), { animate: true });
        toast("Signed out");
      } catch (err) {
        toast(`Couldn't sign out: ${err.message}`, { error: true });
      }
    }
  });
  $("auth-form").addEventListener("submit", submit);
  $("auth-switch").addEventListener("click", (e) => {
    const b = e.target.closest("[data-mode]");
    if (b) setMode(b.dataset.mode);
  });
  $("auth-close").addEventListener("click", () => close(false));
  $("auth-dialog").addEventListener("cancel", () => close(false)); // Esc
  setMode("signin");
  try {
    me = await getMe();
  } catch {
    /* offline: stay a guest */
  }
  renderAccount();
}
