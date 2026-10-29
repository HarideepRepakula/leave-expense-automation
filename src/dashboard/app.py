"""Streamlit dashboard (Phase 10). Start the API first, then:

    streamlit run src/dashboard/app.py

Login through the API (POST /auth/login, simulated authentication, amendment F2). Four views: Overview, Requests,
Exceptions (operational, analytics views + API) and Evaluation (GET /evaluation only). Read-only: the dashboard
changes nothing. Open to approvers, process owners, analysts and admins; Evaluation to analysts and admins (the API
enforces it). Synthetic data only.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:                      # `streamlit run` puts only src/dashboard on the path
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from src.dashboard import client  # noqa: E402
from src.dashboard.evaluation_view import evaluation  # noqa: E402
from src.dashboard.views import exceptions, overview, requests  # noqa: E402

VIEWS = {"Overview": overview, "Requests": requests, "Exceptions": exceptions, "Evaluation": evaluation}
DASHBOARD_ROLES = {"APPROVER", "PROCESS_OWNER", "OPS_ANALYST", "SYSTEM_ADMIN"}
FOOTER = ("Synthetic data only. Policy values are illustrative (ASSUMPTION, illustrative synthetic), not real "
          "company policy. Simulated login, not production authentication.")


def login_form() -> None:
    st.title("Leave and Expense Approvals")
    st.caption(f"Log in with a synthetic dev user (data/processed/dev_credentials.csv). API: {client.API_URL}")
    with st.form("login"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        try:
            st.session_state["auth"] = client.login(username.strip(), password)
        except client.DashboardError as exc:
            st.error(str(exc))
            return
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Leave and Expense Approvals", layout="wide")
    auth = st.session_state.get("auth")
    if auth is None:
        login_form()
        st.caption(FOOTER)
        return
    st.sidebar.markdown(f"**{auth['user_id']}**  \n{', '.join(auth['roles'])}")
    if st.sidebar.button("Log out"):
        del st.session_state["auth"]
        st.rerun()
    if not DASHBOARD_ROLES & set(auth["roles"]):
        st.warning("This dashboard is for approvers, process owners, analysts and admins.")
        return
    choice = st.sidebar.radio("View", list(VIEWS))
    try:
        VIEWS[choice](auth["access_token"], auth)
    except client.DashboardError as exc:
        st.error(str(exc))
    st.caption(FOOTER)


main()
