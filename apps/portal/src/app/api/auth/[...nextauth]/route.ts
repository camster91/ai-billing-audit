// /api/auth/[...nextauth] — NextAuth v5 catch-all route handler.
// NextAuth exposes its HTTP handlers (signin, signout, callback, session,
// csrf, etc.) as a single function pair. Mounting at /api/auth/* matches
// the convention in src/auth.ts (signIn default, callbacks under the
// same prefix) and is what the Auth.js v5 docs prescribe.

import { handlers } from "@/auth";

export const { GET, POST } = handlers;
