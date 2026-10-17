# CloudLens AI

AI-assisted cloud cost optimization prototype. Final-year B.Tech I.T. major project.

CloudLens reads real AWS, Azure and Google Cloud accounts with read-only keys, and also includes a made-up sample company for demos. Savings are estimates, and approving a fix only records the decision: CloudLens never changes anything in a cloud account.

## Layout

| Folder | Contents |
|---|---|
| `data/` | Data generator and the generated CSV files |
| `backend/` | FastAPI service: accounts, cost analysis, optimization rules, forecasting, assistant |
| `frontend/` | React + Vite app: homepage, sign-up, login, dashboard |

## Setup

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

## Regenerate the sample data

```bash
backend/.venv/bin/python data/generate_data.py
```

The seed is fixed, so this always reproduces the same files. `ground_truth.csv` and `cost_anomalies.csv` are the answer key used for evaluation; the application itself never reads them.

## Accounts and MongoDB

People sign up and log in before they see the dashboard. Accounts and each person's choices are stored in MongoDB.

1. Open `backend/.env` (created for you; never commit it).
2. Paste your connection string after `MONGODB_URI=`.
3. Restart the backend.

Until that is filled in, the backend uses a temporary in-memory database: everything works, but accounts are lost each time the backend restarts. `GET /api/health` shows which one is in use.

Passwords are stored only as bcrypt hashes. The login is kept in an httpOnly cookie that page scripts cannot read.

## Cloud connections

A new account starts empty. On the Connections page a person can:

- **Connect a real cloud account** (AWS, Microsoft Azure or Google Cloud) with read-only keys. A step-by-step guide in the app shows exactly how to create them. CloudLens checks the keys with the provider, stores them encrypted, then syncs: it reads up to a year of the daily bill, the current servers and disks, and 30 days of hourly processor use. The waste checks, forecast and assistant then run on that real data.
- **Use a sample account** (the made-up company in `data/`), for trying the app and for demos.

| Provider | Keys | What is read |
|---|---|---|
| AWS | Access key for an IAM user with the read-only policy shown in the app | Cost Explorer (daily bill), EC2 servers and EBS disks in every region, CloudWatch processor use |
| Azure | Service principal with the Reader role on one subscription | Cost Management (daily bill, per resource), virtual machines, managed disks, Azure Monitor processor use |
| Google Cloud | Service account key with Compute Viewer, Monitoring Viewer (and BigQuery roles for the bill) | Compute Engine servers and disks, Cloud Monitoring processor use, the BigQuery billing export (daily bill) |

How it works, briefly:

- `backend/app/cloud/` has one small module per provider that calls the provider's REST API directly (AWS requests are signed with Signature Version 4, checked against Amazon's own `botocore`). No cloud SDKs are needed, which keeps the deployment small.
- `backend/app/live.py` turns what each provider returns into the same tables as the sample data. Whole-account costs always match the real bill; per-server costs come from the provider (Azure) or from list prices (AWS, Google Cloud), and anything not matched to a server or disk appears as "Other charges".
- `backend/app/vault.py` encrypts keys with Fernet before they are saved. The key for that lives only in `CREDENTIALS_KEY` (in `backend/.env` locally and in Vercel's settings), never in the database. Keys are never sent back to the browser, and removing an account deletes its keys and data.
- CloudLens never changes anything in a cloud account. Approving a fix records the decision only.
- Memory use is not read yet (most providers need an agent for it), so the memory parts of the checks are skipped for real accounts.
- `backend/tests/fake_clouds.py` imitates all three providers' APIs so the whole flow is tested without real accounts.

## Showcase account

For demos, `backend/seed_demo.py` sets up one account with all three clouds already connected and a short history of approved and skipped fixes, so every page has content straight away:

```bash
cd backend
.venv/bin/python seed_demo.py --email you@example.com --password "at-least-8-characters"
```

Running it again resets that account to the same showcase state (the password is kept). Other accounts are not touched.

## Run the backend

```bash
cd backend
.venv/bin/uvicorn app.main:app --reload
```

Interactive API docs: http://127.0.0.1:8000/docs

## Run the dashboard

In a second terminal, with the backend still running:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173

## Run the tests

```bash
cd backend
.venv/bin/pytest
```
