"""S1 master data (docs/07 section 2): departments, cost centers and budgets, employees and hierarchy,
cost center assignments, holidays, FX, leave and expense policies, approval rules, delegations, users and roles.

Only raw inputs are random (names, countries, departments, grades, dates, budgets, delegation picks,
synthetic passwords). Structure rules (ASM-014, ASM-015) are applied deterministically.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal

import bcrypt

from src.common import ids
from src.common.enums import CURRENCY_BY_COUNTRY, EmploymentStatus, Grade, RoleName
from src.common.money import fx_rate_on, money, round_to_unit
from src.common.rng import RngStreams
from src.data.sampling import half_up_int, largest_remainder, pick, scaled_count, uniform_date, weighted_pick
from src.data.stages import GenParams

GRADES = [g.value for g in Grade]
GRADE_RANK = {g: i for i, g in enumerate(GRADES)}
BCRYPT_ALPHABET = "./ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def currency_of(country: str) -> str:
    return str(CURRENCY_BY_COUNTRY[country])


def build_master(cfg: dict, p: GenParams, streams: RngStreams) -> tuple[dict[str, list[dict]], list[dict]]:
    """Return (tables, dev_credentials). Credentials are synthetic and go to data/processed only."""
    t: dict[str, list[dict]] = {}
    t["fx_rate"] = _fx_rates(cfg)
    t["country_holiday"] = _holidays(cfg)
    t["department"], t["cost_center"] = _departments_and_cost_centers(cfg, p)
    t["cost_center_budget"] = _budgets(cfg, t["cost_center"], t["fx_rate"], streams)
    t["employee"] = _employees(cfg, p, streams, t["department"], t["cost_center"])
    _department_heads(t["employee"], t["department"])
    t["employee_cost_center_assignment"] = _assignments(t["employee"], p)
    t["leave_policy"] = _leave_policies(cfg)
    t["expense_policy"] = _expense_policies(cfg, t["fx_rate"])
    t["approval_rule"] = _approval_rules(cfg)
    t["exception_code"] = _exception_codes(cfg)
    t["delegation"] = _delegations(cfg, p, streams, t["employee"])
    t["role"], t["application_user"], t["user_role"], credentials = _users(cfg, p, streams, t["employee"])
    return t, credentials


# --- reference data straight from config -------------------------------------------------------------------
def _fx_rates(cfg: dict) -> list[dict]:
    return [
        {
            "fx_rate_id": ids.fx_rate_id(r["from"], r["to"], r["effective_from"]),
            "from_currency": r["from"],
            "to_currency": r["to"],
            "rate": Decimal(r["rate"]),
            "effective_from": r["effective_from"],
        }
        for r in cfg["calendar"]["fx_rates"]
    ]


def _holidays(cfg: dict) -> list[dict]:
    rows = []
    for country, days in cfg["calendar"]["holidays"].items():
        for d, name in sorted(days.items()):
            rows.append({"holiday_id": ids.holiday_id(country, d), "country": country, "holiday_date": d,
                         "holiday_name": name})
    return rows


def _departments_and_cost_centers(cfg: dict, p: GenParams) -> tuple[list[dict], list[dict]]:
    org = cfg["organisation"]
    departments, cost_centers = [], []
    n = 0
    for dept in org["departments"]:
        departments.append({"department_id": dept["id"], "department_name": dept["name"],
                            "head_employee_id": None, "created_at": p.master_ts})
        for country in org["cost_center_countries"]:
            n += 1
            cost_centers.append({
                "cost_center_id": ids.cost_center_id(n),
                "cost_center_name": f"{dept['name']} {country}",
                "department_id": dept["id"],
                "country": country,
                "currency": currency_of(country),
                "is_active": True,
                "effective_from": org["cost_center_effective_from"],
                "effective_to": None,
                "created_at": p.master_ts,
            })
    return departments, cost_centers


def _budgets(cfg: dict, cost_centers: list[dict], fx: list[dict], streams: RngStreams) -> list[dict]:
    """ASM-016: USD amount drawn per (cost center, year), converted at that year's Jan 1 rate."""
    bcfg = cfg["organisation"]["budgets"]
    rng = streams.get("cost_centers")
    rows = []
    for cc in cost_centers:
        for year in bcfg["years"]:
            drawn = rng.uniform(bcfg["usd_min"], bcfg["usd_max"])  # always drawn, so fixed overrides keep positions
            usd = Decimal(half_up_int(drawn / bcfg["usd_round_to"]) * bcfg["usd_round_to"])
            usd = Decimal(bcfg["fixed_usd"].get(cc["cost_center_id"], usd))
            rate = fx_rate_on(fx, "USD", cc["currency"], date(year, 1, 1))
            rows.append({
                "cost_center_budget_id": ids.cost_center_budget_id(cc["cost_center_id"], year),
                "cost_center_id": cc["cost_center_id"],
                "budget_period_start": date(year, 1, 1),
                "budget_period_end": date(year, 12, 31),
                "currency": cc["currency"],
                "budget_amount": money(usd * rate),
                "committed_amount": money(0),
                "actual_amount": money(0),
            })
    return rows


# --- employees and hierarchy --------------------------------------------------------------------------------
def _employees(cfg: dict, p: GenParams, streams: RngStreams, departments: list[dict],
               cost_centers: list[dict]) -> list[dict]:
    ecfg = cfg["generation"]["employees"]
    rng = streams.get("employees")
    fakers = streams.fakers("employees")
    n = p.employees
    dept_names = {d["department_id"]: d["department_name"] for d in departments}
    finance = ecfg["finance_department"]
    other_depts = [d for d in dept_names if d != finance]
    countries = list(ecfg["country_shares"])

    # Structural roles first (ASM-014, ASM-015): one G7 (CFO-level, heads Finance), one G6 head per other
    # department, one G5 finance controller per country. Grade quotas keep these minimums (ASM-P3-03).
    slots = [{"grade": "G7", "dept": finance, "role": "CFO"}]
    slots += [{"grade": "G6", "dept": d, "role": "HEAD"} for d in other_depts]
    slots += [{"grade": "G5", "dept": finance, "role": "CONTROLLER", "country": c} for c in countries]
    if n < len(slots) + 1:
        raise ValueError(f"--employees must be at least {len(slots) + 1}")
    grade_quota = largest_remainder(n, ecfg["grade_shares"], fixed={"G7": 1},
                                    minimums={"G6": len(other_depts), "G5": len(countries)})
    country_quota = largest_remainder(n, ecfg["country_shares"])
    for s in slots:
        grade_quota[s["grade"]] -= 1
        if "country" in s:
            country_quota[s["country"]] -= 1
    grade_pool = [g for g in GRADES for _ in range(grade_quota[g])]
    grade_pool = [grade_pool[i] for i in rng.permutation(len(grade_pool))]
    country_pool = [c for c in countries for _ in range(country_quota[c])]
    country_pool = [country_pool[i] for i in rng.permutation(len(country_pool))]

    drafts: list[dict] = []
    next_country = iter(country_pool)
    for i in range(n):
        if i < len(slots):
            s = slots[i]
            grade, dept, role = s["grade"], s["dept"], s["role"]
            country = s.get("country") or next(next_country)
            start = uniform_date(rng, ecfg["employment_start_min"], ecfg["structural_start_max"])
        else:
            grade, role = grade_pool[i - len(slots)], None
            country = next(next_country)
            dept = weighted_pick(rng, ecfg["department_shares"])
            start = uniform_date(rng, ecfg["employment_start_min"], ecfg["employment_start_max"])
        fake = fakers[country]
        drafts.append({"idx": i, "grade": grade, "dept": dept, "role": role, "country": country,
                       "start": start, "end": None, "status": EmploymentStatus.ACTIVE.value,
                       "first": fake.first_name(), "last": fake.last_name(), "manager": None})

    # IDs in hire-date order (docs/07 section 3), stable tiebreak on draw index.
    drafts.sort(key=lambda d: (d["start"], d["idx"]))
    for k, d in enumerate(drafts, start=1):
        d["employee_id"] = ids.employee_id(k)

    # Terminations and leave of absence (ASM-026); structural roles are never selected (ASM-P3-03).
    candidates = [d for d in drafts if d["role"] is None]
    for j in rng.choice(len(candidates), size=half_up_int(n * ecfg["terminated_share"]), replace=False):
        d = candidates[int(j)]
        d["end"] = uniform_date(rng, max(d["start"], ecfg["termination_end_min"]), ecfg["termination_end_max"])
        d["status"] = EmploymentStatus.TERMINATED.value
    candidates = [d for d in drafts if d["role"] is None and d["end"] is None]
    for j in rng.choice(len(candidates), size=half_up_int(n * ecfg["leave_of_absence_share"]), replace=False):
        candidates[int(j)]["status"] = EmploymentStatus.ON_LEAVE_OF_ABSENCE.value

    _assign_managers(drafts, rng, p.window_start, finance)
    _promote_country_g7s(drafts, countries, p.window_start)

    cc_by_key = {(c["department_id"], c["country"]): c["cost_center_id"] for c in cost_centers}
    titles = ecfg["grade_titles"]
    rows = []
    for d in drafts:
        if d["role"] == "CFO" or d["grade"] == "G7":
            title = titles["G7"]
        elif d["role"] == "HEAD":
            title = f"Head of {dept_names[d['dept']]}"
        elif d["role"] == "CONTROLLER":
            title = f"Finance Controller ({d['country']})"
        else:
            title = f"{titles[d['grade']]}, {dept_names[d['dept']]}"
        local = ".".join(_ascii(x) for x in (d["first"], d["last"]))
        rows.append({
            "employee_id": d["employee_id"],
            "full_name": f"{d['first']} {d['last']}",
            "email": f"{local}.{d['employee_id'][4:]}@{ecfg['email_domain']}",
            "manager_id": d["manager"],
            "department_id": d["dept"],
            "job_title": title,
            "grade": d["grade"],
            "country": d["country"],
            "currency": currency_of(d["country"]),
            "employment_start": d["start"],
            "employment_end": d["end"],
            "employment_status": d["status"],
            "default_cost_center_id": cc_by_key[(d["dept"], d["country"])],
            "is_department_head": d["role"] in ("CFO", "HEAD"),
            "is_finance_controller": d["role"] == "CONTROLLER",
            "created_at": p.master_ts,
        })
    return rows


def _assign_managers(drafts: list[dict], rng, window_start: date, finance: str) -> None:
    """Tree by grade (ASM-014): manager has a strictly higher grade, same department where possible.

    A manager must already be employed when the report can first submit (start <= max(report start, window
    start)) and must not have left before the report joined (ASM-P3-03). Among candidates the closest higher
    grade is preferred, giving the deepest tree (max depth 7). Fallback: department head, then the G7 root.
    """
    root = next(d for d in drafts if d["role"] == "CFO")
    heads = {d["dept"]: d for d in drafts if d["role"] == "HEAD"}
    heads[finance] = root
    by_dept: dict[str, list[dict]] = {}
    for d in drafts:
        by_dept.setdefault(d["dept"], []).append(d)
    for e in drafts:  # employee_id order
        if e is root:
            continue
        if e["role"] == "HEAD":
            e["manager"] = root["employee_id"]
            continue
        limit = max(e["start"], window_start)
        cands = [
            m for m in by_dept[e["dept"]]
            if GRADE_RANK[m["grade"]] > GRADE_RANK[e["grade"]] and m["start"] <= limit
            and (m["end"] is None or m["end"] > e["start"])
        ]
        if cands:
            closest = min(GRADE_RANK[m["grade"]] for m in cands)
            pool = [m for m in cands if GRADE_RANK[m["grade"]] == closest]
            e["manager"] = pick(rng, pool)["employee_id"]
        elif GRADE_RANK[heads[e["dept"]]["grade"]] > GRADE_RANK[e["grade"]]:
            e["manager"] = heads[e["dept"]]["employee_id"]
        else:
            e["manager"] = root["employee_id"]


def _promote_country_g7s(drafts: list[dict], countries: list[str], window_start: date) -> None:
    """Owner decision S19 option (a), AMB-P7B-09: every country has exactly one G7. In each country without one,
    the lowest-id G6 that is ACTIVE and employed for the whole window becomes G7 at the top of the chain
    (manager NULL); department, head flag and reports stay. No random draws (runs after the managers).
    A country with no such G6 (small scales) keeps no G7; the generator warns and records it (AMB-P7B-10)."""
    for c in countries:
        if any(d["grade"] == "G7" and d["country"] == c for d in drafts):
            continue
        d = min((d for d in drafts if d["grade"] == "G6" and d["country"] == c
                 and d["status"] == EmploymentStatus.ACTIVE.value and d["end"] is None
                 and d["start"] <= window_start), key=lambda d: d["employee_id"], default=None)
        if d is not None:
            d["grade"], d["manager"] = "G7", None


def _ascii(name: str) -> str:
    return re.sub(r"[^a-z]", "", name.lower()) or "x"


def _department_heads(employees: list[dict], departments: list[dict]) -> None:
    """Fill department.head_employee_id from the employee flags (the G7 heads Finance)."""
    head_by_dept = {e["department_id"]: e["employee_id"] for e in employees if e["is_department_head"]}
    for d in departments:
        d["head_employee_id"] = head_by_dept[d["department_id"]]


def _assignments(employees: list[dict], p: GenParams) -> list[dict]:
    """One assignment per employee covering the whole employment (ASM-P3-15)."""
    return [
        {
            "assignment_id": ids.assignment_id(k),
            "employee_id": e["employee_id"],
            "cost_center_id": e["default_cost_center_id"],
            "effective_from": e["employment_start"],
            "effective_to": e["employment_end"],
            "created_at": p.master_ts,
        }
        for k, e in enumerate(employees, start=1)
    ]


# --- policies and rules --------------------------------------------------------------------------------------
def _leave_policies(cfg: dict) -> list[dict]:
    common = cfg["leave_policies"]["common"]

    def dec(v):
        return None if v is None else Decimal(v)

    return [
        {
            "leave_policy_id": pol["id"],
            "policy_family": pol["family"],
            "version": pol["version"],
            "policy_name": pol["name"],
            "leave_type": pol["leave_type"],
            "country_scope": pol["country_scope"],
            "annual_entitlement_days": Decimal(pol["annual_entitlement_days"]),
            "accrual_method": pol["accrual_method"],
            "carry_forward_cap_days": Decimal(pol["carry_forward_cap_days"]),
            "negative_balance_allowed": pol["negative_balance_allowed"],
            "negative_limit_days": Decimal(pol["negative_limit_days"]),
            "min_service_days": common["min_service_days"],
            "requires_medical_cert_over_days": dec(pol["requires_medical_cert_over_days"]),
            "max_days_per_year": dec(pol["max_days_per_year"]),
            "effective_start": common["effective_start"],
            "effective_end": common["effective_end"],
            "is_active": common["is_active"],
        }
        for pol in cfg["leave_policies"]["policies"]
    ]


def _expense_policies(cfg: dict, fx: list[dict]) -> list[dict]:
    """ASM-011/012, DEC-05: USD bases converted once at the reference rate, rounded per currency."""
    x = cfg["expense_policies"]
    rows = []
    for category in x["categories"]:
        versions = x["versioned"].get(category) or [
            {"version": 1, "effective_start": x["default_effective_start"], "effective_end": None,
             "per_line_multiplier": "1.00"}
        ]
        for country in x["countries"]:
            ccy = currency_of(country)
            rate = fx_rate_on(fx, "USD", ccy, x["reference_rate_date"])
            unit = x["local_rounding"][ccy]
            family = f"XPOL-{category}-{country}"
            for v in versions:
                line_usd = Decimal(x["per_line_limit_usd"][category]) * Decimal(v["per_line_multiplier"])
                rows.append({
                    "expense_policy_id": f"{family}-V{v['version']}",
                    "policy_family": family,
                    "version": v["version"],
                    "policy_name": f"{category.replace('_', ' ').title()} ({country}) v{v['version']}",
                    "country": country,
                    "category": category,
                    "currency": ccy,
                    "per_line_limit": round_to_unit(line_usd * rate, unit),
                    "per_claim_limit": round_to_unit(Decimal(x["per_claim_limit_usd"]) * rate, unit),
                    "receipt_threshold": round_to_unit(Decimal(x["receipt_threshold_usd"]) * rate, unit),
                    "requires_pre_approval": False,
                    "effective_start": v["effective_start"],
                    "effective_end": v["effective_end"],
                    "is_active": True,
                })
    return rows


def _approval_rules(cfg: dict) -> list[dict]:
    a = cfg["approval_rules"]

    def dec(r, k):
        return None if r.get(k) is None else Decimal(r[k])

    return [
        {
            "approval_rule_id": r["id"],
            "request_type": r["request_type"],
            "country": r.get("country"),
            "category_or_leave_type": r.get("category_or_leave_type"),
            "min_amount_usd": dec(r, "min_amount_usd"),
            "max_amount_usd": dec(r, "max_amount_usd"),
            "min_days": dec(r, "min_days"),
            "max_days": dec(r, "max_days"),
            "required_levels": list(r["levels"]),
            "priority": r["priority"],
            "effective_start": a["effective_start"],
            "effective_end": None,
            "is_active": True,
        }
        for r in a["rules"]
    ]


DEFAULT_ROUTE = {"HARD": "REJECTED", "CORRECTABLE": "RETURNED_FOR_CORRECTION", "SOFT": "ESCALATED_FOR_REVIEW",
                 "INFO": "NONE"}


def _exception_codes(cfg: dict) -> list[dict]:
    """Exception code catalogue from config/exception_codes.yaml (docs/02 section 5, docs/05 section 9.1)."""
    return [
        {"exception_code": c["code"], "exception_class": c["class"], "severity": c["severity"],
         "default_route": DEFAULT_ROUTE[c["severity"]], "requester_message_template": c["requester"],
         "analyst_message_template": c["analyst"]}
        for c in cfg["exception_codes"]["codes"]
    ]


# --- delegations ----------------------------------------------------------------------------------------------
def _delegations(cfg: dict, p: GenParams, streams: RngStreams, employees: list[dict]) -> list[dict]:
    """ASM-049: managers present for the whole window delegate to a same-grade peer in their department
    (fallback: their own manager) for 5-20 days inside the window (ASM-P3-16)."""
    dcfg = cfg["generation"]["delegations"]
    rng = streams.get("delegations")
    by_id = {e["employee_id"]: e for e in employees}
    managers = {e["manager_id"] for e in employees if e["manager_id"]}

    def present(e: dict) -> bool:
        return e["employment_end"] is None and e["employment_start"] <= p.window_start

    cands = [e for e in employees if e["employee_id"] in managers and e["grade"] != "G7" and present(e)]
    count = min(len(cands), scaled_count(dcfg["count_at_reference"], p.employees,
                                         cfg["generation"]["volumes"]["reference_employees"]))
    drafts = []
    for j in rng.choice(len(cands), size=count, replace=False):
        approver = cands[int(j)]
        peers = [e for e in employees if e["department_id"] == approver["department_id"]
                 and e["grade"] == approver["grade"] and e is not approver and present(e)]
        delegate = pick(rng, peers) if peers else by_id[approver["manager_id"]]
        length = int(rng.integers(dcfg["min_days"], dcfg["max_days"] + 1))
        start = uniform_date(rng, p.window_start, p.as_of - timedelta(days=length - 1))
        drafts.append({"approver_id": approver["employee_id"], "delegate_id": delegate["employee_id"],
                       "effective_from": start, "effective_to": start + timedelta(days=length - 1)})
    drafts.sort(key=lambda d: (d["effective_from"], d["approver_id"]))
    return [
        {"delegation_id": ids.delegation_id(k), **d, "reason": "Approver on planned leave (synthetic)",
         "created_at": p.master_ts}
        for k, d in enumerate(drafts, start=1)
    ]


# --- simulated authentication (ASM-036) -------------------------------------------------------------------------
ROLE_DESCRIPTIONS = {
    RoleName.REQUESTER: "Submits leave requests and expense claims",
    RoleName.APPROVER: "Approves or rejects steps assigned to them",
    RoleName.PROCESS_OWNER: "Resolves escalated requests",
    RoleName.OPS_ANALYST: "Reads analytics and annotates exceptions",
    RoleName.SYSTEM_ADMIN: "Administers configuration and users",
}


def _users(cfg: dict, p: GenParams, streams: RngStreams, employees: list[dict]):
    ucfg = cfg["generation"]["users"]
    rng = streams.get("users")
    roles = [{"role_id": ids.role_id(r.value), "role_name": r.value, "description": ROLE_DESCRIPTIONS[r]}
             for r in RoleName]

    def password() -> str:
        return "".join(PASSWORD_ALPHABET[int(i)] for i in rng.integers(0, len(PASSWORD_ALPHABET),
                                                                        ucfg["password_length"]))

    def hash_pw(pw: str) -> str:
        # Deterministic salt from the users stream so checksums are reproducible (ASM-P3-10).
        body = "".join(BCRYPT_ALPHABET[int(i)] for i in rng.integers(0, 64, 21)) + pick(rng, list(".Oeu"))
        salt = f"$2b${ucfg['bcrypt_rounds']:02d}${body}".encode()
        return bcrypt.hashpw(pw.encode(), salt).decode()

    managers = {e["manager_id"] for e in employees if e["manager_id"]}
    heads = {e["department_id"]: e["employee_id"] for e in employees if e["is_department_head"]}
    process_owners = {heads[d] for d in ucfg["process_owner_departments"]}
    ops_dept = cfg["generation"]["employees"]["operations_department"]
    ops_pool = [e for e in employees if e["department_id"] == ops_dept and e["employment_end"] is None]
    n_analysts = min(len(ops_pool), scaled_count(ucfg["ops_analysts_at_reference"], p.employees,
                                                 cfg["generation"]["volumes"]["reference_employees"]))
    analysts = {ops_pool[int(j)]["employee_id"] for j in rng.choice(len(ops_pool), size=n_analysts, replace=False)}

    users, user_roles, creds = [], [], []
    for k, e in enumerate(employees, start=1):
        uid = ids.user_id(k)
        pw = password()
        users.append({"user_id": uid, "username": e["email"], "password_hash": hash_pw(pw),
                      "employee_id": e["employee_id"],
                      "is_active": e["employment_status"] != EmploymentStatus.TERMINATED.value,
                      "created_at": p.master_ts})
        granted = [RoleName.REQUESTER]
        if (e["employee_id"] in managers or e["is_department_head"] or e["is_finance_controller"]
                or e["grade"] == "G7"):
            granted.append(RoleName.APPROVER)
        if e["employee_id"] in process_owners:
            granted.append(RoleName.PROCESS_OWNER)
        if e["employee_id"] in analysts:
            granted.append(RoleName.OPS_ANALYST)
        user_roles += [{"user_id": uid, "role_id": ids.role_id(r.value)} for r in granted]
        creds.append({"user_id": uid, "username": e["email"], "password": pw,
                      "roles": ";".join(r.value for r in granted)})

    admin_id = ids.user_id(len(employees) + 1)
    pw = password()
    users.append({"user_id": admin_id, "username": ucfg["admin_username"], "password_hash": hash_pw(pw),
                  "employee_id": None, "is_active": True, "created_at": p.master_ts})
    user_roles.append({"user_id": admin_id, "role_id": ids.role_id(RoleName.SYSTEM_ADMIN.value)})
    creds.append({"user_id": admin_id, "username": ucfg["admin_username"], "password": pw,
                  "roles": RoleName.SYSTEM_ADMIN.value})
    return roles, users, user_roles, creds
