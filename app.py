import pandas as pd
import streamlit as st

from algebra_engine import (
    AlgebraError,
    validate_elements,
    validate_operation,
    generate_operation_table,
    check_properties,
    detect_structure,
    check_distributivity,
    detect_pair_structure,
    verify_theorem,
)
from database import (
    initialize_database,
    save_theorem,
    list_theorems,
    delete_theorem,
    save_algebra,
    list_algebras,
    delete_algebra,
    register_user,
    authenticate_user,
    storage_backend,
    list_all_users,
    set_user_status,
    request_password_reset,
    complete_password_reset,
)

st.set_page_config(
    page_title="Advanced Algebra Engine",
    page_icon="📐",
    layout="wide"
)
try:
    initialize_database()
except Exception as exc:
    st.error("The database connection is not ready. Check your Streamlit Secrets and Supabase schema.")
    st.exception(exc)
    st.stop()

# ----------------------------- Authentication -----------------------------
st.title("📐 Advanced Algebraic Theorem Verification Engine")
st.caption("Finite algebra structures • theorem verification • proof traces • personal libraries")

if "authenticated_user" not in st.session_state:
    st.session_state.authenticated_user = None
if "authenticated_email" not in st.session_state:
    st.session_state.authenticated_email = None
if "is_root_admin" not in st.session_state:
    st.session_state.is_root_admin = False

if not st.session_state.authenticated_user:
    login_tab, register_tab, reset_tab = st.tabs(["Log in", "Create account", "Reset password"])
    with login_tab:
        st.subheader("Welcome back")
        with st.form("login_form"):
            login_identifier = st.text_input("Username or email")
            login_password = st.text_input("Password", type="password")
            login_submit = st.form_submit_button("Log in", type="primary")
        if login_submit:
            ok, user, message = authenticate_user(login_identifier, login_password)
            if ok:
                st.session_state.authenticated_user = user["username"]
                st.session_state.authenticated_email = user.get("email")
                st.session_state.is_root_admin = user["is_admin"]
                st.rerun()
            else:
                st.error(message)
    with register_tab:
        st.subheader("Request an account")
        st.caption("New accounts require root-admin approval before the workspace can be used.")
        with st.form("register_form"):
            new_email = st.text_input("Email address")
            new_username = st.text_input("Choose a username")
            new_password = st.text_input("Choose a password", type="password")
            confirm_password = st.text_input("Confirm password", type="password")
            register_submit = st.form_submit_button("Submit registration", type="primary")
        if register_submit:
            if new_password != confirm_password:
                st.error("The passwords do not match.")
            else:
                ok, message = register_user(new_username, new_email, new_password)
                (st.success if ok else st.error)(message)
    with reset_tab:
        st.subheader("Reset your password")
        st.caption("A six-digit code will be sent to your registered email. Configure SMTP in Streamlit Secrets first.")
        with st.form("request_reset_form"):
            reset_email = st.text_input("Registered email address")
            send_code = st.form_submit_button("Send reset code")
        if send_code:
            try:
                _, message = request_password_reset(reset_email)
                st.success(message)
            except Exception as exc:
                st.error(str(exc))
        with st.form("complete_reset_form"):
            reset_email_confirm = st.text_input("Email address", key="reset_email_confirm")
            reset_code = st.text_input("Six-digit reset code")
            reset_new_password = st.text_input("New password", type="password")
            reset_new_confirm = st.text_input("Confirm new password", type="password")
            complete_reset = st.form_submit_button("Update password", type="primary")
        if complete_reset:
            if reset_new_password != reset_new_confirm:
                st.error("The passwords do not match.")
            else:
                ok, message = complete_password_reset(reset_email_confirm, reset_code, reset_new_password)
                (st.success if ok else st.error)(message)
    st.info("Your account becomes usable after the root administrator approves it.")
    st.stop()

current_user = st.session_state.authenticated_user
with st.sidebar:
    st.markdown(f"**Signed in as:** `{current_user}`")
    if st.session_state.authenticated_email:
        st.caption(st.session_state.authenticated_email)
    if st.session_state.is_root_admin:
        st.success("Root administrator")
    st.caption(f"Storage: {storage_backend()}")
    if storage_backend().startswith("SQLite"):
        st.warning("Local SQLite mode: cloud data may not persist. Configure Supabase before publishing.")
    if st.button("Log out", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

if st.session_state.is_root_admin:
    st.title("Root administration")
    st.subheader("Account access management")
    st.caption("Review every account and control access to the algebra workspace.")
    users = list_all_users()
    st.metric("Registered accounts", len(users))
    if users:
        st.dataframe(pd.DataFrame([{
            "Username": u["username"], "Email": u.get("email") or "",
            "Status": u.get("status", "approved"), "Root admin": bool(u.get("is_admin")),
            "Registered": u.get("created_at", "")
        } for u in users]), use_container_width=True, hide_index=True)
        for user in users:
            if user.get("is_admin"):
                continue
            with st.expander(f'{user["username"]} · {user.get("email") or "No email"} · {user.get("status", "pending").upper()}'):
                c1, c2, c3 = st.columns(3)
                with c1:
                    if st.button("Approve", key=f'approve_{user["username"]}', disabled=user.get("status")=="approved"):
                        set_user_status(user["username"], "approved")
                        st.rerun()
                with c2:
                    if st.button("Suspend", key=f'suspend_{user["username"]}', disabled=user.get("status")=="suspended"):
                        set_user_status(user["username"], "suspended")
                        st.rerun()
                with c3:
                    if st.button("Reactivate", key=f'reactivate_{user["username"]}', disabled=user.get("status")=="approved"):
                        set_user_status(user["username"], "approved")
                        st.rerun()
    st.info("The root admin account is provisioned from deployment secrets and cannot be managed or suspended from this page. You can also use the algebra workspace below.")

if "elements" not in st.session_state:
    st.session_state.elements = ["0", "1"]
if "theta_values" not in st.session_state:
    st.session_state.theta_values = {}
if "phi_values" not in st.session_state:
    st.session_state.phi_values = {}

tabs = st.tabs([
    "Algebra & Theorem Workbench",
    "Operation Generator",
    "Structure Detection"
])

def table_to_df(elements, table):
    return pd.DataFrame(
        [[table.get((a, b), "") for b in elements] for a in elements],
        index=elements,
        columns=elements
    )

def df_to_table(df, elements):
    return {
        (str(a), str(b)): str(df.loc[a, b]).strip()
        for a in elements for b in elements
    }

def show_property(label, item):
    if item["holds"]:
        st.success(f"✓ {label}")
    else:
        st.error(f"✗ {label}")
        if item.get("counterexample"):
            st.json(item["counterexample"])

with tabs[0]:
    st.subheader("Algebra & theorem workbench")
    st.caption("Define or load an algebra, save it, then select any built-in or saved theorem below to generate a proof against this algebra.")

    # Apply generated tables before the editors are instantiated on this run.
    if "pending_generated" in st.session_state:
        pending = st.session_state.pop("pending_generated")
        st.session_state.elements = pending["elements"]
        st.session_state.elements_input = ",".join(pending["elements"])
        if pending["target"] == "θ":
            st.session_state.theta_values = pending["table"]
        else:
            st.session_state.phi_values = pending["table"]
        st.session_state.pop("theta_editor", None)
        st.session_state.pop("phi_editor", None)
        st.session_state.pop("workspace_validation", None)

    # Loading is an explicit action. Previously, the selected saved algebra was
    # reloaded on every rerun, which overwrote unsaved cell edits.
    saved_algebras = list_algebras(current_user)
    saved_options = {f'{a["name"]} (#{a["id"]})': a for a in saved_algebras}
    load_col, load_btn_col = st.columns([4, 1])
    with load_col:
        chosen_saved = st.selectbox(
            "Load saved algebra",
            ["— Select a saved algebra —"] + list(saved_options),
            key="saved_algebra_choice",
        )
    with load_btn_col:
        st.write("")
        st.write("")
        load_clicked = st.button("Load", disabled=chosen_saved == "— Select a saved algebra —")
    if load_clicked:
        match = saved_options[chosen_saved]
        st.session_state.elements = match["elements"]
        st.session_state.theta_values = match["theta"]
        st.session_state.phi_values = match["phi"]
        st.session_state.elements_input = ",".join(match["elements"])
        # A new algebra may have a different shape; reset only the editor widget state.
        st.session_state.pop("theta_editor", None)
        st.session_state.pop("phi_editor", None)
        st.session_state.pop("workspace_validation", None)
        st.success(f'Loaded {match["name"]}.')
        st.rerun()

    st.markdown("**Set elements**")
    element_col, apply_col = st.columns([4, 1])
    with element_col:
        elements_draft = st.text_input(
            "Elements (comma separated)",
            value=",".join(st.session_state.elements),
            key="elements_input",
            help="Example: 0,1,2. Press Apply set to resize the operation tables.",
        )
    with apply_col:
        st.write("")
        st.write("")
        apply_elements = st.button("Apply set", type="secondary")

    if apply_elements:
        new_elements = [item.strip() for item in elements_draft.split(",") if item.strip()]
        try:
            validate_elements(new_elements)
            old_elements = st.session_state.elements
            # Preserve cells whose row/column labels still exist.
            st.session_state.theta_values = {
                (a, b): st.session_state.theta_values.get((a, b), "")
                for a in new_elements for b in new_elements
            }
            st.session_state.phi_values = {
                (a, b): st.session_state.phi_values.get((a, b), "")
                for a in new_elements for b in new_elements
            }
            st.session_state.elements = new_elements
            st.session_state.pop("theta_editor", None)
            st.session_state.pop("phi_editor", None)
            st.success("Set updated. Existing values for unchanged elements were preserved.")
            st.rerun()
        except AlgebraError as exc:
            st.error(str(exc))

    elements = st.session_state.elements
    st.markdown("---")
    st.subheader("Edit operation tables")
    st.caption("Click a cell and type its result. Use Tab / Shift+Tab to move between cells. Each cell must contain an element from the set.")

    theta_col, phi_col = st.columns(2, gap="large")
    with theta_col:
        st.markdown("**θ operation table**")
        theta_df = st.data_editor(
            table_to_df(elements, st.session_state.theta_values),
            key="theta_editor",
            use_container_width=True,
            num_rows="fixed",
            height=min(420, 42 * (len(elements) + 1) + 10),
            column_config={c: st.column_config.TextColumn(str(c), help=f"θ(row, {c})") for c in elements},
        )
    with phi_col:
        st.markdown("**φ operation table**")
        phi_df = st.data_editor(
            table_to_df(elements, st.session_state.phi_values),
            key="phi_editor",
            use_container_width=True,
            num_rows="fixed",
            height=min(420, 42 * (len(elements) + 1) + 10),
            column_config={c: st.column_config.TextColumn(str(c), help=f"φ(row, {c})") for c in elements},
        )

    # Persist the current editor output on every rerun, so navigation and other
    # controls do not discard values already entered by the user.
    theta = df_to_table(theta_df, elements)
    phi = df_to_table(phi_df, elements)
    st.session_state.theta_values = theta
    st.session_state.phi_values = phi
    current_signature = (tuple(elements), tuple(sorted(theta.items())), tuple(sorted(phi.items())))
    if st.session_state.get("validated_signature") != current_signature:
        st.session_state.pop("workspace_validation", None)
    # The signature is recorded only when the user explicitly validates.
    if st.session_state.get("workspace_validation") is not None:
        st.session_state.validated_signature = current_signature

    st.markdown("---")
    st.markdown("**Table status**")
    status_left, status_right = st.columns(2)
    with status_left:
        st.caption("θ operation")
        theta_filled = sum(bool(str(v).strip()) for v in theta.values())
        st.caption(f"{theta_filled} / {len(elements) ** 2} cells entered")
    with status_right:
        st.caption("φ operation")
        phi_filled = sum(bool(str(v).strip()) for v in phi.values())
        st.caption(f"{phi_filled} / {len(elements) ** 2} cells entered")

    if st.button("Validate both operation tables", key="validate_workspace"):
        theta_errors = validate_operation(elements, theta, "theta")
        phi_errors = validate_operation(elements, phi, "phi")
        st.session_state.workspace_validation = {"theta": theta_errors, "phi": phi_errors}
        st.session_state.validated_signature = (tuple(elements), tuple(sorted(theta.items())), tuple(sorted(phi.items())))
    validation = st.session_state.get("workspace_validation")
    if validation is not None:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**θ validation**")
            if validation["theta"]:
                for error in validation["theta"]:
                    st.error(error)
            else:
                st.success("θ is a complete and closed binary operation.")
        with c2:
            st.markdown("**φ validation**")
            if validation["phi"]:
                for error in validation["phi"]:
                    st.error(error)
            else:
                st.success("φ is a complete and closed binary operation.")

    algebra_name = st.text_input("Name this algebra to save it", "My algebra", key="algebra_name")
    if st.button("Save algebra configuration", type="primary"):
        theta_errors = validate_operation(elements, theta, "theta")
        phi_errors = validate_operation(elements, phi, "phi")
        if theta_errors or phi_errors:
            st.error("Fix validation errors before saving.")
        else:
            save_algebra(current_user, algebra_name.strip(), elements, theta, phi)
            st.success("Algebra configuration saved to your account.")

# Theorem selection, creation, verification, and saved-algebra management all live
# in the same workbench as the operation tables.

    st.markdown("---")
    st.subheader("Theorem & proof workspace")
    STANDARD_THEOREMS = [
        {"name": "Commutativity of θ", "vars": 2, "lhs": "theta(x,y)", "rhs": "theta(y,x)", "kind": "Built-in"},
        {"name": "Commutativity of φ", "vars": 2, "lhs": "phi(x,y)", "rhs": "phi(y,x)", "kind": "Built-in"},
        {"name": "Associativity of θ", "vars": 3, "lhs": "theta(x,theta(y,z))", "rhs": "theta(theta(x,y),z)", "kind": "Built-in"},
        {"name": "Associativity of φ", "vars": 3, "lhs": "phi(x,phi(y,z))", "rhs": "phi(phi(x,y),z)", "kind": "Built-in"},
        {"name": "Left Distributive", "vars": 3, "lhs": "theta(x,phi(y,z))", "rhs": "phi(theta(x,y),theta(x,z))", "kind": "Built-in"},
        {"name": "Right Distributive", "vars": 3, "lhs": "theta(phi(x,y),z)", "rhs": "phi(theta(x,z),theta(y,z))", "kind": "Built-in"},
    ]
    saved_theorems = list_theorems(current_user)
    theorem_choices = {f'Built-in · {item["name"]}': item for item in STANDARD_THEOREMS}
    for item in saved_theorems:
        theorem_choices[f'Saved · {item["name"]} (#{item["id"]})'] = {
            "name": item["name"], "vars": int(item["variable_count"]),
            "lhs": item["lhs"], "rhs": item["rhs"], "kind": "Saved"
        }

    selected_label = st.selectbox(
        "Choose an algorithm to run", list(theorem_choices), key="unified_theorem_choice"
    )
    selected_theorem = theorem_choices[selected_label]
    st.code(f'{selected_theorem["lhs"]} = {selected_theorem["rhs"]}')
    if selected_theorem["kind"] == "Built-in":
        st.caption("Permanent built-in algorithm — it cannot be deleted.")
    else:
        st.caption("Your saved algorithm — reusable with any compatible saved or current algebra.")

    if st.button("Verify selected theorem and generate proof", key="run_selected_theorem", type="primary"):
        try:
            theta_errors = validate_operation(elements, theta, "theta")
            phi_errors = validate_operation(elements, phi, "phi")
            if theta_errors or phi_errors:
                st.error("Complete both operation tables and ensure closure before running a proof.")
            else:
                result = verify_theorem(
                    selected_theorem["lhs"], selected_theorem["rhs"],
                    selected_theorem["vars"], elements, theta, phi
                )
                st.metric("Assignments verified", f'{result["passed"]}/{result["total"]}')
                if result["verified"]:
                    st.success(f'{selected_theorem["name"]} holds for every assignment in this algebra.')
                else:
                    st.error(f'{selected_theorem["name"]} fails for {result["failed"]} assignment(s).')
                for row in result["results"]:
                    outcome = "PASS" if row["passed"] else "FAIL"
                    with st.expander(f'Assignment: {row["variables"]} — {outcome}'):
                        st.markdown("**LHS evaluation**")
                        for step in row["lhs_steps"]:
                            st.write(f'{step["expression"]} = {step["result"]}')
                        st.write("LHS final value:", row["lhs"])
                        st.markdown("**RHS evaluation**")
                        for step in row["rhs_steps"]:
                            st.write(f'{step["expression"]} = {step["result"]}')
                        st.write("RHS final value:", row["rhs"])
                        if not row["passed"]:
                            st.error("Counterexample: " + str(row["variables"]))
        except AlgebraError as exc:
            st.error(str(exc))

    st.markdown("---")
    st.subheader("Add a reusable theorem / algorithm")
    st.caption("Save a theorem once; it immediately appears in the algorithm selector above and can be verified against any algebra you load.")
    theorem_name = st.text_input("Theorem / algorithm name", key="new_thm_name")
    variable_count = st.selectbox("Number of variables", [2, 3], key="new_var_count")
    lhs = st.text_input("Left-hand expression (LHS)", placeholder="theta(x,theta(y,z))", key="new_lhs")
    rhs = st.text_input("Right-hand expression (RHS)", placeholder="theta(theta(x,y),z)", key="new_rhs")
    st.caption('Syntax: theta(x,y), phi(x,phi(y,z)). Variables: x, y, z. Constants can be written as quoted values, e.g. theta("0",x).')
    if st.button("Save theorem to my algorithm library", key="save_custom_theorem"):
        try:
            if not theorem_name.strip():
                st.error("Enter a name for this theorem.")
            elif not lhs.strip() or not rhs.strip():
                st.error("Enter both the LHS and RHS expressions.")
            else:
                # Parse/validate syntax even if the current algebra tables are not yet complete.
                from algebra_engine import parse_expression
                allowed = ["x", "y", "z"][:int(variable_count)]
                parse_expression(lhs.strip(), allowed)
                parse_expression(rhs.strip(), allowed)
                save_theorem(current_user, theorem_name.strip(), int(variable_count), lhs.strip(), rhs.strip())
                st.success("Saved. This theorem is now available in 'Choose an algorithm to run'.")
                st.rerun()
        except AlgebraError as exc:
            st.error(f"The theorem was not saved: {exc}")

    st.markdown("---")
    st.subheader("Your saved algebra & theorem assets")
    asset_col1, asset_col2 = st.columns(2, gap="large")
    with asset_col1:
        st.markdown("**Saved algebras**")
        for item in list_algebras(current_user):
            with st.expander(f'{item["name"]} · algebra #{item["id"]}'):
                st.write("Set:", item["elements"])
                st.dataframe(table_to_df(item["elements"], item["theta"]), use_container_width=True)
                st.caption("φ operation")
                st.dataframe(table_to_df(item["elements"], item["phi"]), use_container_width=True)
                if st.button("Load this algebra into the workbench", key=f'load_asset_alg_{item["id"]}'):
                    st.session_state.elements = item["elements"]
                    st.session_state.theta_values = item["theta"]
                    st.session_state.phi_values = item["phi"]
                    st.session_state.elements_input = ",".join(item["elements"])
                    for widget_key in ("theta_editor", "phi_editor", "workspace_validation"):
                        st.session_state.pop(widget_key, None)
                    st.rerun()
                if st.button("Delete algebra", key=f'del_asset_alg_{item["id"]}'):
                    delete_algebra(current_user, item["id"])
                    st.rerun()
    with asset_col2:
        st.markdown("**Saved theorems / algorithms**")
        for item in list_theorems(current_user):
            with st.expander(f'{item["name"]} · theorem #{item["id"]}'):
                st.write(f'Variables: {item["variable_count"]}')
                st.code(f'{item["lhs"]} = {item["rhs"]}')
                st.caption("Select this algorithm in the theorem selector above to generate a fresh proof for the currently loaded algebra.")
                if st.button("Delete theorem", key=f'del_asset_thm_{item["id"]}'):
                    delete_theorem(current_user, item["id"])
                    st.rerun()

with tabs[1]:
    st.subheader("Automatic operation table generator")
    n = st.number_input("Modulus n", min_value=1, max_value=20, value=3, step=1)
    op_choice = st.selectbox(
        "Operation",
        ["Addition modulo n", "Subtraction modulo n", "Multiplication modulo n"]
    )
    op_key = {
        "Addition modulo n": "add",
        "Subtraction modulo n": "subtract",
        "Multiplication modulo n": "multiply"
    }[op_choice]
    generated_elements = [str(i) for i in range(int(n))]
    generated = generate_operation_table(generated_elements, op_key, int(n))
    st.dataframe(table_to_df(generated_elements, generated), use_container_width=True)
    target = st.selectbox("Apply generated table to", ["θ", "φ"])
    if st.button("Use generated table in workspace"):
        st.session_state.pending_generated = {
            "elements": generated_elements,
            "table": generated,
            "target": target
        }
        st.rerun()

with tabs[2]:
    st.subheader("Automatic structure detection")
    theta_errors = validate_operation(elements, theta, "theta")
    phi_errors = validate_operation(elements, phi, "phi")
    if theta_errors or phi_errors:
        st.info("Structure detection is ready once both tables are filled and validated. No errors are reported for an untouched workspace.")
    else:
        left, right = st.columns(2)
        with left:
            st.markdown("### θ as a single operation")
            tp = check_properties(elements, theta)
            st.info(detect_structure(tp))
            show_property("Commutativity", tp["commutativity"])
            show_property("Associativity", tp["associativity"])
            show_property("Idempotence", tp["idempotence"])
            show_property("Left cancellation", tp["left_cancellation"])
            show_property("Right cancellation", tp["right_cancellation"])
            st.write("Left identities:", tp["left_identity"])
            st.write("Right identities:", tp["right_identity"])
            st.write("Two-sided identities:", tp["identities"])
            st.write("Two-sided inverse candidates:", tp["inverses"])
        with right:
            st.markdown("### φ as a single operation")
            pp = check_properties(elements, phi)
            st.info(detect_structure(pp))
            show_property("Commutativity", pp["commutativity"])
            show_property("Associativity", pp["associativity"])
            show_property("Idempotence", pp["idempotence"])
            show_property("Left cancellation", pp["left_cancellation"])
            show_property("Right cancellation", pp["right_cancellation"])
            st.write("Left identities:", pp["left_identity"])
            st.write("Right identities:", pp["right_identity"])
            st.write("Two-sided identities:", pp["identities"])
            st.write("Two-sided inverse candidates:", pp["inverses"])

        st.markdown("---")
        st.markdown("### Pair structure: (L, θ, φ)")
        pair = detect_pair_structure(elements, theta, phi)
        st.header(pair["classification"])
        if pair.get("reasons"):
            for reason in pair["reasons"]:
                st.write("•", reason)
        if pair.get("distributivity", {}).get("valid"):
            show_property("Left distributivity", pair["distributivity"]["left"])
            show_property("Right distributivity", pair["distributivity"]["right"])
        if pair.get("zero") is not None:
            st.write("Additive zero:", pair["zero"])
            st.write("Multiplicative identity:", pair.get("one"))
            st.write("Nonzero multiplicative inverses:", pair.get("nonzero_multiplicative_inverses", {}))

