# CloudLens AI

AI-assisted cloud cost optimization prototype. Final-year B.Tech I.T. major project.

Everything runs locally on **simulated data**. No cloud account or paid API is used, savings are estimates, and optimization actions are simulated.

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

A new account starts empty. On the Connections page a person links Amazon Web Services, Microsoft Azure or Google Cloud, and the dashboard then shows only the data from the clouds they connected.

In this prototype each provider links a sample account (the `provider` column in `data/resources.csv`). No real cloud credentials are asked for or stored. Reading live bills through each provider's billing API is a future extension.

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
