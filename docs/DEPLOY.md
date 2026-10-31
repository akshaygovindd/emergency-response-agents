# Deploying the dashboard on Streamlit Community Cloud

The dashboard only replays saved runs (event logs and result tables committed to the repo) and re-runs the naive and greedy baselines in memory on the What-if page.
It never calls the OpenAI API, so **no secrets are needed** and no `.env` is deployed.

## Readiness checklist (checked on a clean clone, no `.env`, no `OPENAI_API_KEY`)

| Check | Result |
|---|---|
| Entry point | `dashboard/app.py` (it adds `src/` to `sys.path` itself, so the `erc` package needs no install) |
| Dependencies | `requirements.txt` at the repo root (pinned). Tests and the analysis script use `requirements-dev.txt`, which Streamlit does not read |
| Theme and server settings | `.streamlit/config.toml` (dark theme in the design-system colors, headless, no usage stats) |
| Data the app reads | `logs/`, `results/`, `data/scenarios/`, `data/descriptions/` are all committed (about 110 MB including the LLM cache); nothing is downloaded or generated at start-up |
| Starts without an API key | `streamlit run dashboard/app.py` serves (`/_stcore/health` returns `ok`), and `AppTest` renders Replay, Compare, What-if, Results and Negotiations with no exception |
| Test suite on a clean clone | `pytest -q`: 243 passed (CI runs the same on every push) |

Not verified: behaviour on the Community Cloud host itself (memory limits, and the page reload used when you change the run selector, which relies on query parameters on the app URL). Check these after the first deploy (step 6).

## Steps

1. Push the repository to GitHub (`akshaygovindd/emergency-response-agents`). Community Cloud deploys public repositories without extra setup; for a private repository, grant Streamlit access when it asks.
2. Go to <https://share.streamlit.io> and sign in with GitHub.
3. Click **Create app**, then **Deploy a public app from GitHub** (or **Yup, I have an app**).
4. Fill in:
   * Repository: `akshaygovindd/emergency-response-agents`
   * Branch: `master`
   * Main file path: `dashboard/app.py`
   * App URL: choose a name, for example `emergency-response-agents`
5. Open **Advanced settings** and set **Python version** to `3.12` (the project requires 3.12 or newer). Leave **Secrets** empty. Click **Deploy**.
6. Wait for the build (it installs `requirements.txt`). When the app opens, check:
   * Replay loads on v1, normal, run 1, negotiation and plays;
   * changing the run in the selector reloads the page with the new run;
   * Compare, Results (v1 and v2 toggle) and Negotiations open;
   * What-if: press Run once and wait for the two result cards.
7. Put the app URL in the README and in the slides. Later pushes to `master` redeploy automatically; **Reboot app** in the app menu clears a stuck session.

## If something fails

* *ModuleNotFoundError*: the Python version is wrong (must be 3.12) or the build used a cached older `requirements.txt`; reboot the app after changing the requirements.
* *App too slow or out of memory on the free tier*: the Replay page loads one run bundle at a time; the What-if page runs the simulation in memory (a few seconds). If memory is the problem, run the dashboard locally with `streamlit run dashboard/app.py`.
* *Run selector does nothing*: the selector reloads the page through query parameters; open the app directly at its own `*.streamlit.app` URL rather than inside another site's frame.

## Local launch (same code)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run dashboard/app.py
```
