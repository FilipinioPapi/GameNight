// Signing in with Discord. All the real work happens on the Windows side (account.rs):
// the window never sees the sign-in pass and never talks to the internet itself.

import { inTauri } from "./settings";

export interface User { id: string; name: string; avatar?: string; }
export interface Status { server: string; user: User | null; }

async function invoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<T>(cmd, args);
}

export async function status(): Promise<Status> {
  if (!inTauri) return { server: "preview", user: null };
  return invoke<Status>("account_status");
}

/** Opens Discord in the web browser. The answer arrives later through onSignIn / onSignInFailed. */
export async function signIn(): Promise<void> {
  if (!inTauri) return;
  await invoke("sign_in");
}

export async function signOut(): Promise<void> {
  if (inTauri) await invoke("sign_out");
}

export async function setServer(address: string): Promise<string> {
  return invoke<string>("set_server", { address });
}

export async function listen(handlers: { signedIn: (u: User) => void; failed: (msg: string) => void; signedOut: () => void }) {
  if (!inTauri) return;
  const { listen } = await import("@tauri-apps/api/event");
  await listen<User>("signed-in", (e) => handlers.signedIn(e.payload));
  await listen<string>("sign-in-failed", (e) => handlers.failed(e.payload));
  await listen("signed-out", () => handlers.signedOut());
}

/** "http://192.168.1.33:8094" -> "192.168.1.33:8094" for showing on screen. */
export const shortAddress = (a: string) => a.replace(/^https?:\/\//, "");
