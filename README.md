# Algebraic Theorem Verification Engine

A Streamlit application for finite algebra workspaces, algebraic structure detection, operation-table generation, theorem verification, proof traces, and per-account libraries.

## Features
- Account registration and login; passwords are stored as salted PBKDF2-HMAC-SHA256 hashes.
- Per-user saved custom theorems and algebra configurations.
- Six original built-in theorem checks remain available and cannot be deleted.
- Editable theta/phi operation tables with session-persistent values.
- Explicit validation (blank tables do not show errors until validation is requested).
- Modular operation table generator.
- Closure, commutativity, associativity, idempotence, cancellation, identity and inverse checks.
- Semigroup, monoid, group and abelian-group classification.
- Pair checks for ring/field-related properties.
- Restricted AST parser for custom theorem expressions (does not use Python `eval`).
- SQLite for local development; Supabase-hosted PostgreSQL for persistent cloud deployment.

## Run locally

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Without Supabase credentials, the app uses a local SQLite database (`algebra_data.db`). That is for local development and is not durable on Streamlit Community Cloud.

## Deploy to Streamlit Community Cloud (persistent setup)

### 1. Create a Supabase project

1. Create a project at https://supabase.com/.
2. Open **SQL Editor** and run all statements in `supabase_schema.sql`.
3. In **Project Settings → API**, copy the Project URL and the `service_role` key. Keep the service-role key secret.

### 2. Push this project to GitHub

Create a new GitHub repository and upload the contents of this folder. Ensure `app.py`, `algebra_engine.py`, `database.py`, `requirements.txt`, and `supabase_schema.sql` are at the repository root. Do not upload `.streamlit/secrets.toml` or any database key.

### 3. Deploy

1. Open https://share.streamlit.io/ and sign in with GitHub.
2. Select **New app**, choose your repository and branch, and set the main file path to `app.py`.
3. Deploy the app.

### 4. Add secrets in Streamlit Cloud

Open the deployed app's **Settings → Secrets** and add:

```toml
SUPABASE_URL = "https://YOUR-PROJECT-REF.supabase.co"
SUPABASE_SERVICE_ROLE_KEY = "YOUR_SUPABASE_SERVICE_ROLE_KEY"
```

Save secrets and reboot/redeploy the app. The application checks the Supabase tables at startup and uses hosted storage automatically when both secrets are present. If the secrets are missing, it falls back to SQLite; do not use that fallback for a public production deployment because Streamlit Community Cloud's local filesystem is not a durable database.

## Important production notes

- The current login is a custom username/password system, not Supabase Auth. Use HTTPS (provided by Streamlit Cloud), keep the service-role key only in Streamlit Secrets, and restrict repository access appropriately.
- For a public application with sensitive user data, add email verification, password reset, login rate limiting, stronger session management, audit logging, and consider migrating authentication to Supabase Auth before launch.
- User data queries are filtered by `user_id` in server-side code. The service-role key bypasses Supabase RLS, so never expose it to client-side code. For a higher-assurance multi-tenant deployment, migrate user identity to Supabase Auth and enforce ownership with database RLS policies.
- Back up the Supabase database and configure appropriate retention before real users depend on it.
- Test with at least two separate accounts before sharing the public URL.

## Pre-deployment checklist

- [ ] `supabase_schema.sql` successfully executed.
- [ ] Streamlit Cloud secrets saved and app rebooted.
- [ ] Register two test accounts and verify their saved theorems/algebras are isolated.
- [ ] Verify built-in theorems still work and cannot be deleted.
- [ ] Verify blank tables show no validation errors until Validate is clicked.
- [ ] Save, reload, and delete a custom theorem and an algebra.
- [ ] Confirm data remains after app reboot.
